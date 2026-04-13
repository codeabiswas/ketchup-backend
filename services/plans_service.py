"""Plan round service (generation, voting, refinement, finalization)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from uuid import UUID

from analytics.repositories import (
    get_group_venue_priors,
    get_latest_group_feature_snapshot,
)
from agents.planning import PlannerError, generate_group_plans
from config import get_settings
from database import db
from services.errors import BadRequestError, NotFoundError, UpstreamServiceError
from services.group_access import require_active_group_member, require_group_lead
from utils.email import send_voting_open_email, send_event_finalized_email

logger = logging.getLogger(__name__)

VOTING_WINDOW_HOURS = 24
DEFAULT_EVENT_OFFSET_DAYS = 7
RECENT_VENUE_LIMIT = 40

REFINEMENT_DESCRIPTOR_GUIDANCE: dict[str, str] = {
    "budget_friendly": (
        "CRITICAL BUDGET CONSTRAINT: The group selected 'budget friendly'. "
        "ALL 5 plans MUST have estimated cost under $15 per person. "
        "Prioritize: free activities (parks, public spaces, free museum days, "
        "community events), picnics, hiking, free outdoor concerts, "
        "cheap eats under $10, BYOB gatherings, and other low/no-cost options. "
        "Do NOT suggest restaurants with entrees over $12 or any paid attractions over $10."
    ),
    "short_travel": "Minimize travel time and distance for most members.",
    "more_active": "Bias toward higher-energy, activity-heavy options.",
    "more_chill": "Bias toward calmer, conversation-friendly options.",
    "indoor": "Prefer indoor or weather-safe venues.",
    "outdoor": "Prefer outdoor options when feasible.",
    "food_focused": "Favor food-centric experiences.",
    "accessible": "Prioritize easy-access, low-friction logistics.",
}


def _parse_rankings(raw_rankings: str | list[str] | None) -> list[str]:
    if not raw_rankings:
        return []
    if isinstance(raw_rankings, str):
        try:
            parsed = json.loads(raw_rankings)
        except json.JSONDecodeError:
            return []
        return [str(value) for value in parsed if value]
    return [str(value) for value in raw_rankings if value]


def _first_choice_counts(votes: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for vote in votes:
        rankings = _parse_rankings(vote["rankings"])
        if rankings:
            first_choice = rankings[0]
            counts[first_choice] = counts.get(first_choice, 0) + 1
    return counts


def _borda_scores(votes: list, num_plans: int = 5) -> dict[str, float]:
    """Compute Borda count scores. Rank 1 gets num_plans points, rank 2 gets num_plans-1, etc."""
    scores: dict[str, float] = {}
    for vote in votes:
        rankings = _parse_rankings(vote["rankings"])
        for position, plan_id in enumerate(rankings):
            points = max(0, num_plans - position)
            scores[plan_id] = scores.get(plan_id, 0) + points
    return scores


def _top_n_sets(votes: list, n: int = 3) -> list[set[str]]:
    """Return the top-N plan IDs for each vote as a list of sets."""
    result = []
    for vote in votes:
        rankings = _parse_rankings(vote["rankings"])
        result.append(set(rankings[:n]))
    return result


def _determine_consensus(
    votes: list, total_members: int
) -> tuple[bool, str | None, dict[str, int]]:
    """Determine consensus using a multi-strategy approach.

    Strategy 1: First-choice strict majority (>50%).
    Strategy 2: Borda count — if top scorer leads by a scaled margin AND
                all voters have that plan in their top 3.
    Strategy 3: Borda tie-break for small groups (≤3 voters) — if the top
                Borda scores are tied and both candidates are in every
                voter's top 3, pick the one with more first-choice votes.

    Returns (consensus, winning_plan_id, first_choice_counts).
    """
    first_choices = _first_choice_counts(votes)

    if not first_choices or not total_members:
        return False, None, first_choices

    # Strategy 1: First-choice majority
    max_votes = max(first_choices.values())
    if max_votes >= (total_members / 2) + 1:
        winner = max(first_choices, key=first_choices.get)  # type: ignore[arg-type]
        return True, winner, first_choices

    # Strategy 2: Borda count with top-3 overlap
    if len(votes) >= 2:
        borda = _borda_scores(votes)
        if borda:
            sorted_borda = sorted(borda.items(), key=lambda x: x[1], reverse=True)
            best_id, best_score = sorted_borda[0]
            second_score = sorted_borda[1][1] if len(sorted_borda) > 1 else 0

            # Scale margin by voter count: 2 voters → 1, 3+ → 2
            min_margin = max(1, len(votes) - 1)
            if best_score - second_score >= min_margin:
                # Check that every voter has this plan in their top 3
                top3_sets = _top_n_sets(votes, n=3)
                if all(best_id in voter_top3 for voter_top3 in top3_sets):
                    return True, best_id, first_choices

            # Strategy 3: Borda tie-break for small groups
            if len(votes) <= 3 and len(sorted_borda) >= 2:
                if best_score == second_score:
                    top3_sets = _top_n_sets(votes, n=3)
                    candidates = [
                        cid for cid, sc in sorted_borda if sc == best_score
                    ]
                    viable = [
                        c
                        for c in candidates
                        if all(c in t3 for t3 in top3_sets)
                    ]
                    if viable:
                        # Tiebreak: most first-choice votes, then plan_id
                        winner = max(
                            viable,
                            key=lambda c: (first_choices.get(c, 0), c),
                        )
                        return True, winner, first_choices

    return False, None, first_choices


def _clamp_novelty_target(value: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _normalize_refinement_descriptors(descriptors: list[str] | None) -> list[str]:
    if not descriptors:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in descriptors:
        token = str(raw or "").strip().lower()
        if not token or token in seen or token not in REFINEMENT_DESCRIPTOR_GUIDANCE:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def _descriptor_guidance(descriptors: list[str]) -> list[str]:
    return [REFINEMENT_DESCRIPTOR_GUIDANCE[d] for d in descriptors if d in REFINEMENT_DESCRIPTOR_GUIDANCE]


def _build_refinement_notes(
    votes: list,
    descriptors: list[str] | None = None,
    lead_note: str | None = None,
) -> str:
    first_choice_counts = _first_choice_counts(votes)
    notes: list[str] = []
    for vote in votes:
        if vote["notes"]:
            notes.append(str(vote["notes"]))
    normalized_descriptors = _normalize_refinement_descriptors(descriptors)
    return json.dumps(
        {
            "first_choice_counts": first_choice_counts,
            "notes": notes[:10],
            "descriptors": normalized_descriptors,
            "descriptor_guidance": _descriptor_guidance(normalized_descriptors),
            "lead_note": (lead_note or "").strip(),
        }
    )


async def _fetch_recent_venue_names(group_id: UUID, limit: int = RECENT_VENUE_LIMIT) -> list[str]:
    rows = await db.fetch(
        """
        SELECT COALESCE(NULLIF(TRIM(p.venue_name), ''), NULLIF(TRIM(p.title), '')) AS venue
        FROM plans p
        JOIN plan_rounds pr ON pr.id = p.plan_round_id
        WHERE pr.group_id = $1
        ORDER BY p.created_at DESC
        LIMIT $2
        """,
        group_id,
        limit,
    )
    venues: list[str] = []
    seen: set[str] = set()
    for row in rows:
        venue = row["venue"]
        if not venue:
            continue
        venue_s = str(venue).strip()
        if not venue_s:
            continue
        key = venue_s.lower()
        if key in seen:
            continue
        seen.add(key)
        venues.append(venue_s)
    return venues


async def _load_planner_analytics_context(
    group_id: UUID,
) -> tuple[dict[str, object] | None, list[dict[str, object]], dict[str, object]]:
    try:
        snapshot = await get_latest_group_feature_snapshot(group_id)
        priors = await get_group_venue_priors(group_id, limit=40)
    except Exception as exc:
        logger.warning(
            "Analytics context unavailable for group %s (%s: %s)",
            group_id,
            exc.__class__.__name__,
            exc,
        )
        return None, [], {"analytics_unavailable": True}

    metadata: dict[str, object] = {"venue_prior_count": len(priors)}
    if snapshot:
        metadata["feature_snapshot_at"] = snapshot.get("snapshot_at")
        metadata["feature_version"] = snapshot.get("feature_version")

    return snapshot, priors, metadata


async def _insert_generated_plans(
    round_id: UUID,
    plans: list[dict],
    generation_metadata: dict[str, object] | None = None,
) -> list[dict[str, str | None]]:
    saved: list[dict[str, str | None]] = []
    for plan in plans:
        logistics = dict(plan.get("logistics") or {})
        if generation_metadata:
            logistics.setdefault("analytics", dict(generation_metadata))

        row = await db.fetchrow(
            """
            INSERT INTO plans
                (plan_round_id, title, description, vibe_type, date_time, location, venue_name, estimated_cost, logistics)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id, title, description, vibe_type, date_time, location, venue_name, estimated_cost
            """,
            round_id,
            plan.get("title"),
            plan.get("description"),
            plan.get("vibe_type"),
            plan.get("date_time"),
            plan.get("location"),
            plan.get("venue_name"),
            plan.get("estimated_cost"),
            json.dumps(logistics),
        )
        saved.append(
            {
                "id": str(row["id"]),
                "title": row["title"],
                "description": row["description"],
                "vibe_type": row["vibe_type"],
                "location": row["location"],
                "venue_name": row["venue_name"],
                "estimated_cost": row["estimated_cost"],
            }
        )
    return saved


async def _create_generation_round(group_id: UUID) -> tuple[UUID, int, datetime]:
    # Only count rounds created after the most recent finalized event so that
    # each hangout cycle starts at Round 1.
    max_iter = await db.fetchval(
        """
        SELECT COALESCE(MAX(pr.iteration), 0)
        FROM plan_rounds pr
        WHERE pr.group_id = $1
          AND pr.created_at > COALESCE(
            (SELECT MAX(e.created_at) FROM events e WHERE e.group_id = $1),
            '1970-01-01'::timestamptz
          )
        """,
        group_id,
    )
    iteration = (max_iter or 0) + 1
    voting_deadline = datetime.utcnow() + timedelta(hours=VOTING_WINDOW_HOURS)
    round_row = await db.fetchrow(
        """
        INSERT INTO plan_rounds (group_id, iteration, status, voting_deadline)
        VALUES ($1, $2, 'generating', $3)
        RETURNING id
        """,
        group_id,
        iteration,
        voting_deadline,
    )
    return round_row["id"], iteration, voting_deadline


async def generate_plans(group_id: UUID, user_id: UUID) -> dict[str, object]:
    await require_active_group_member(group_id, user_id)
    await require_group_lead(
        group_id,
        user_id,
        detail="Only group lead can generate plans",
    )

    round_id, _, voting_deadline = await _create_generation_round(group_id)
    settings = get_settings()
    novelty_target = _clamp_novelty_target(
        settings.planner_novelty_target_generate,
        default=0.7,
    )
    prior_venues = await _fetch_recent_venue_names(group_id)
    analytics_snapshot, venue_priors, generation_metadata = await _load_planner_analytics_context(
        group_id
    )

    try:
        generated = await generate_group_plans(
            group_id,
            planning_constraints={
                "plan_mode": "generate",
                "novelty_target": novelty_target,
                "prior_venues": prior_venues,
                "analytics_snapshot": analytics_snapshot,
                "venue_priors": venue_priors,
            },
        )
        plans_data = await _insert_generated_plans(
            round_id,
            generated,
            generation_metadata=generation_metadata,
        )
        await db.execute("UPDATE plan_rounds SET status = 'voting_open' WHERE id = $1", round_id)
    except PlannerError as exc:
        await db.execute(
            "UPDATE plan_rounds SET status = 'manual_handoff' WHERE id = $1",
            round_id,
        )
        raise UpstreamServiceError(f"Plan generation failed: {exc}") from exc
    except Exception as exc:
        await db.execute(
            "UPDATE plan_rounds SET status = 'manual_handoff' WHERE id = $1",
            round_id,
        )
        raise UpstreamServiceError("Plan generation failed") from exc

    # Notify all group members that voting is open.
    await _send_voting_notifications(group_id, round_id)

    return {
        "plan_round_id": str(round_id),
        "plans": plans_data,
        "status": "voting_open",
        "voting_deadline": voting_deadline.isoformat(),
    }


async def _send_voting_notifications(group_id: UUID, round_id: UUID) -> None:
    """Send voting-open emails to all active group members."""
    try:
        group = await db.fetchrow("SELECT name FROM groups WHERE id = $1", group_id)
        group_name = group["name"] if group else "your group"
        members = await db.fetch(
            """
            SELECT u.email FROM group_members gm
            JOIN users u ON gm.user_id = u.id
            WHERE gm.group_id = $1 AND gm.status = 'active'
            """,
            group_id,
        )
        for member in members:
            send_voting_open_email(
                to_email=member["email"],
                group_name=group_name,
                group_id=str(group_id),
                round_id=str(round_id),
            )
    except Exception:
        logger.exception("Failed to send voting notification emails for group %s", group_id)


async def get_plans(group_id: UUID, round_id: UUID, user_id: UUID) -> dict[str, object]:
    await require_active_group_member(group_id, user_id)

    round_row = await db.fetchrow(
        "SELECT id, voting_deadline FROM plan_rounds WHERE id = $1 AND group_id = $2",
        round_id,
        group_id,
    )
    if not round_row:
        raise NotFoundError("Plan round not found")

    plans = await db.fetch(
        "SELECT id, title, description, vibe_type, date_time, location, venue_name, estimated_cost, logistics FROM plans WHERE plan_round_id = $1 ORDER BY vibe_type",
        round_id,
    )

    return {
        "plans": [
            {
                "id": str(p["id"]),
                "title": p["title"],
                "description": p["description"],
                "vibe_type": p["vibe_type"],
                "date_time": p["date_time"].isoformat() if p["date_time"] else None,
                "location": p["location"],
                "venue_name": p["venue_name"],
                "estimated_cost": p["estimated_cost"],
                "logistics": p["logistics"] or {},
            }
            for p in plans
        ],
        "voting_deadline": round_row["voting_deadline"].isoformat()
        if round_row["voting_deadline"]
        else None,
        "user_logistics": {},
    }


async def submit_vote(
    group_id: UUID,
    round_id: UUID,
    user_id: UUID,
    rankings: list[UUID],
    notes: str | None,
) -> dict[str, object]:
    await require_active_group_member(group_id, user_id)

    round_row = await db.fetchrow(
        "SELECT id FROM plan_rounds WHERE id = $1 AND group_id = $2 AND status IN ('voting_open', 'votes_complete')",
        round_id,
        group_id,
    )
    if not round_row:
        raise NotFoundError("Plan round not found or voting closed")

    plans_in_round = await db.fetch(
        "SELECT id FROM plans WHERE plan_round_id = $1",
        round_id,
    )
    plan_ids = {str(plan["id"]) for plan in plans_in_round}
    for plan_id in rankings:
        if str(plan_id) not in plan_ids:
            raise BadRequestError(f"Invalid plan id: {plan_id}")

    serialized_rankings = [str(ranking) for ranking in rankings]
    await db.execute(
        """
        INSERT INTO votes (plan_round_id, user_id, rankings, notes)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (plan_round_id, user_id) DO UPDATE SET rankings = EXCLUDED.rankings, notes = EXCLUDED.notes
        """,
        round_id,
        user_id,
        json.dumps(serialized_rankings),
        notes,
    )

    # Check if all active members have now voted; if so, close voting.
    total_members = await db.fetchval(
        "SELECT COUNT(*) FROM group_members WHERE group_id = $1 AND status = 'active'",
        group_id,
    )
    total_votes = await db.fetchval(
        "SELECT COUNT(*) FROM votes WHERE plan_round_id = $1",
        round_id,
    )
    if total_votes >= total_members:
        await db.execute(
            "UPDATE plan_rounds SET status = 'votes_complete' WHERE id = $1 AND status = 'voting_open'",
            round_id,
        )

    return {
        "vote_id": "ok",
        "rankings": serialized_rankings,
        "notes": notes,
    }


async def get_voting_results(
    group_id: UUID,
    round_id: UUID,
    user_id: UUID,
) -> dict[str, object]:
    await require_active_group_member(group_id, user_id)

    round_row = await db.fetchrow(
        "SELECT id FROM plan_rounds WHERE id = $1 AND group_id = $2",
        round_id,
        group_id,
    )
    if not round_row:
        raise NotFoundError("Plan round not found")

    votes = await db.fetch(
        "SELECT rankings FROM votes WHERE plan_round_id = $1",
        round_id,
    )
    total_votes = len(votes)

    total_members = await db.fetchval(
        "SELECT COUNT(*) FROM group_members WHERE group_id = $1 AND status = 'active'",
        group_id,
    )

    consensus, winning_plan_id, first_choices = _determine_consensus(votes, total_members)

    # If consensus was found, persist the winning plan on the round.
    if consensus and winning_plan_id:
        await db.execute(
            "UPDATE plan_rounds SET winning_plan_id = $1 WHERE id = $2 AND winning_plan_id IS NULL",
            UUID(winning_plan_id),
            round_id,
        )

    return {
        "consensus": consensus,
        "winning_plan_id": winning_plan_id,
        "vote_summary": first_choices,
        "iteration_count": 1,
        "votes_in": total_votes,
        "total_members": total_members,
    }


async def refine_plans(
    group_id: UUID,
    round_id: UUID,
    user_id: UUID,
    descriptors: list[str] | None = None,
    lead_note: str | None = None,
) -> dict[str, object]:
    await require_active_group_member(group_id, user_id)
    await require_group_lead(group_id, user_id, detail="Only group lead can refine")

    current_round = await db.fetchrow(
        "SELECT id FROM plan_rounds WHERE id = $1 AND group_id = $2",
        round_id,
        group_id,
    )
    if not current_round:
        raise NotFoundError("Plan round not found")

    await db.execute(
        "UPDATE plan_rounds SET status = 'manual_handoff' WHERE id = $1",
        round_id,
    )

    new_round_id, iteration, voting_deadline = await _create_generation_round(group_id)
    vote_rows = await db.fetch(
        "SELECT rankings, notes FROM votes WHERE plan_round_id = $1",
        round_id,
    )
    normalized_descriptors = _normalize_refinement_descriptors(descriptors)
    refinement_notes = _build_refinement_notes(
        vote_rows,
        descriptors=normalized_descriptors,
        lead_note=lead_note,
    )
    settings = get_settings()
    novelty_target = _clamp_novelty_target(
        settings.planner_novelty_target_refine,
        default=0.35,
    )
    prior_venues = await _fetch_recent_venue_names(group_id)
    analytics_snapshot, venue_priors, generation_metadata = await _load_planner_analytics_context(
        group_id
    )

    try:
        generated = await generate_group_plans(
            group_id,
            refinement_notes=refinement_notes,
            planning_constraints={
                "plan_mode": "refine",
                "novelty_target": novelty_target,
                "prior_venues": prior_venues,
                "refinement_descriptors": normalized_descriptors,
                "refinement_focus_note": (lead_note or "").strip(),
                "analytics_snapshot": analytics_snapshot,
                "venue_priors": venue_priors,
            },
        )
        plans_data = await _insert_generated_plans(
            new_round_id,
            generated,
            generation_metadata=generation_metadata,
        )
        await db.execute(
            "UPDATE plan_rounds SET status = 'voting_open' WHERE id = $1",
            new_round_id,
        )
    except PlannerError as exc:
        await db.execute(
            "UPDATE plan_rounds SET status = 'manual_handoff' WHERE id = $1",
            new_round_id,
        )
        raise UpstreamServiceError(f"Plan refinement failed: {exc}") from exc
    except Exception as exc:
        await db.execute(
            "UPDATE plan_rounds SET status = 'manual_handoff' WHERE id = $1",
            new_round_id,
        )
        raise UpstreamServiceError("Plan refinement failed") from exc

    return {
        "plan_round_id": str(new_round_id),
        "plans": plans_data,
        "status": "voting_open",
        "iteration": iteration,
        "voting_deadline": voting_deadline.isoformat(),
    }


async def finalize_plan(group_id: UUID, round_id: UUID, user_id: UUID) -> dict[str, str]:
    await require_group_lead(group_id, user_id, detail="Only group lead can finalize")

    round_row = await db.fetchrow(
        "SELECT id, winning_plan_id FROM plan_rounds WHERE id = $1 AND group_id = $2",
        round_id,
        group_id,
    )
    if not round_row:
        raise NotFoundError("Plan round not found")

    winning_id = round_row["winning_plan_id"]
    if not winning_id:
        votes = await db.fetch("SELECT rankings FROM votes WHERE plan_round_id = $1", round_id)
        first_choices = _first_choice_counts(votes)
        if first_choices:
            winning_id = UUID(max(first_choices, key=first_choices.get))
            await db.execute(
                "UPDATE plan_rounds SET winning_plan_id = $1 WHERE id = $2",
                winning_id,
                round_id,
            )

    if not winning_id:
        raise BadRequestError("Cannot finalize without a winning plan")

    plan = await db.fetchrow(
        "SELECT id, title, description, location, date_time FROM plans WHERE id = $1",
        winning_id,
    )
    if not plan:
        raise NotFoundError("Winning plan not found")

    event_date = plan["date_time"] or datetime.utcnow() + timedelta(
        days=DEFAULT_EVENT_OFFSET_DAYS
    )
    event_row = await db.fetchrow(
        """
        INSERT INTO events (group_id, plan_id, plan_round_id, event_date)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (plan_round_id) DO UPDATE SET
            plan_id = EXCLUDED.plan_id,
            event_date = EXCLUDED.event_date
        RETURNING id, event_date
        """,
        group_id,
        winning_id,
        round_id,
        event_date,
    )
    await db.execute(
        "UPDATE plan_rounds SET status = 'consensus_reached', winning_plan_id = $1 WHERE id = $2",
        winning_id,
        round_id,
    )

    # Send event confirmation emails with .ics to all group members.
    await _send_event_finalized_notifications(
        group_id=group_id,
        plan_title=plan["title"],
        event_date=event_row["event_date"],
        location=plan["location"],
        description=plan["description"],
    )

    return {
        "event_id": str(event_row["id"]),
        "plan_title": plan["title"],
        "event_date": event_row["event_date"].isoformat(),
    }


async def _send_event_finalized_notifications(
    group_id: UUID,
    plan_title: str,
    event_date: datetime,
    location: str | None = None,
    description: str | None = None,
) -> None:
    """Send event finalization emails with .ics to all active group members."""
    try:
        group = await db.fetchrow("SELECT name FROM groups WHERE id = $1", group_id)
        group_name = group["name"] if group else "your group"
        members = await db.fetch(
            """
            SELECT u.email FROM group_members gm
            JOIN users u ON gm.user_id = u.id
            WHERE gm.group_id = $1 AND gm.status = 'active'
            """,
            group_id,
        )
        for member in members:
            send_event_finalized_email(
                to_email=member["email"],
                group_name=group_name,
                plan_title=plan_title,
                event_date=event_date,
                location=location,
                description=description,
            )
    except Exception:
        logger.exception("Failed to send event finalized emails for group %s", group_id)

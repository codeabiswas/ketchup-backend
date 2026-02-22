# api/routes/plans.py

"""Plan generation and voting routes."""

import json
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from database import db
from models.schemas import VoteRequest

router = APIRouter(prefix="/api/groups", tags=["plans"])


def _get_user_id(x_user_id: str | None = Header(None, alias="X-User-Id")) -> UUID:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID")


@router.post("/{group_id}/generate-plans", status_code=201)
async def generate_plans(
    group_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Trigger AI plan generation. Returns mock plans (replace with vLLM when ready)."""
    user_id = _get_user_id(x_user_id)

    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    group = await db.fetchrow(
        "SELECT lead_id FROM groups WHERE id = $1",
        group_id,
    )
    if not group or group["lead_id"] != user_id:
        raise HTTPException(
            status_code=403, detail="Only group lead can generate plans"
        )

    voting_deadline = datetime.utcnow() + timedelta(hours=24)
    round_row = await db.fetchrow(
        """
        INSERT INTO plan_rounds (group_id, iteration, status, voting_deadline)
        VALUES ($1, 1, 'voting_open', $2)
        RETURNING id, iteration, status
        """,
        group_id,
        voting_deadline,
    )

    vibe_types = ["anchor", "pivot", "reach", "chill", "wildcard"]
    titles = [
        "Cozy Coffee & Board Games",
        "Bowling Night at Back Bay",
        "Sunset Picnic at the Park",
        "Food Truck Tour Downtown",
        "Escape Room Adventure",
    ]
    plans_data = []
    for vibe, title in zip(vibe_types, titles):
        plan_row = await db.fetchrow(
            """
            INSERT INTO plans (plan_round_id, title, description, vibe_type, location, venue_name, estimated_cost, logistics)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, title, description, vibe_type, date_time, location, venue_name, estimated_cost, logistics
            """,
            round_row["id"],
            title,
            f"Fun {vibe} option for the group.",
            vibe,
            "Boston, MA",
            title.split(" at ")[0] if " at " in title else title,
            "$15-30 per person",
            json.dumps({"driver_view": {}, "passenger_view": {}}),
        )
        plans_data.append(
            {
                "id": str(plan_row["id"]),
                "title": plan_row["title"],
                "description": plan_row["description"],
                "vibe_type": plan_row["vibe_type"],
                "location": plan_row["location"],
                "venue_name": plan_row["venue_name"],
                "estimated_cost": plan_row["estimated_cost"],
            }
        )

    return {
        "plan_round_id": str(round_row["id"]),
        "plans": plans_data,
        "status": "voting_open",
        "voting_deadline": voting_deadline.isoformat(),
    }


@router.get("/{group_id}/plans/{round_id}")
async def get_plans(
    group_id: UUID,
    round_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    round_row = await db.fetchrow(
        "SELECT id, status, voting_deadline FROM plan_rounds WHERE id = $1 AND group_id = $2",
        round_id,
        group_id,
    )
    if not round_row:
        raise HTTPException(status_code=404, detail="Plan round not found")

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


@router.post("/{group_id}/plans/{round_id}/vote", status_code=201)
async def submit_vote(
    group_id: UUID,
    round_id: UUID,
    body: VoteRequest,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    round_row = await db.fetchrow(
        "SELECT id FROM plan_rounds WHERE id = $1 AND group_id = $2 AND status = 'voting_open'",
        round_id,
        group_id,
    )
    if not round_row:
        raise HTTPException(
            status_code=404, detail="Plan round not found or voting closed"
        )

    plans_in_round = await db.fetch(
        "SELECT id FROM plans WHERE plan_round_id = $1",
        round_id,
    )
    plan_ids = {str(p["id"]) for p in plans_in_round}
    for pid in body.rankings:
        if str(pid) not in plan_ids:
            raise HTTPException(status_code=400, detail=f"Invalid plan id: {pid}")

    await db.execute(
        """
        INSERT INTO votes (plan_round_id, user_id, rankings, notes)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (plan_round_id, user_id) DO UPDATE SET rankings = EXCLUDED.rankings, notes = EXCLUDED.notes
        """,
        round_id,
        user_id,
        json.dumps([str(r) for r in body.rankings]),
        body.notes,
    )
    return {
        "vote_id": "ok",
        "rankings": [str(r) for r in body.rankings],
        "notes": body.notes,
    }


@router.get("/{group_id}/plans/{round_id}/results")
async def get_voting_results(
    group_id: UUID,
    round_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    round_row = await db.fetchrow(
        "SELECT id, status, winning_plan_id FROM plan_rounds WHERE id = $1 AND group_id = $2",
        round_id,
        group_id,
    )
    if not round_row:
        raise HTTPException(status_code=404, detail="Plan round not found")

    votes = await db.fetch(
        "SELECT user_id, rankings, notes FROM votes WHERE plan_round_id = $1",
        round_id,
    )

    first_choices = {}
    for v in votes:
        ranks = (
            json.loads(v["rankings"])
            if isinstance(v["rankings"], str)
            else v["rankings"]
        )
        if ranks:
            fc = ranks[0]
            first_choices[fc] = first_choices.get(fc, 0) + 1

    total_members = await db.fetchval(
        "SELECT COUNT(*) FROM group_members WHERE group_id = $1 AND status = 'active'",
        group_id,
    )
    consensus = False
    winning_plan_id = None
    if first_choices and total_members:
        max_votes = max(first_choices.values())
        if max_votes >= (total_members / 2) + 1:
            winning_plan_id = max(first_choices, key=first_choices.get)
            consensus = True

    return {
        "consensus": consensus,
        "winning_plan_id": winning_plan_id,
        "vote_summary": first_choices,
        "iteration_count": 1,
    }


@router.post("/{group_id}/plans/{round_id}/refine", status_code=201)
async def refine_plans(
    group_id: UUID,
    round_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Trigger AI refinement - generates 5 new plans (mock for local)."""
    user_id = _get_user_id(x_user_id)

    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    group = await db.fetchrow(
        "SELECT lead_id FROM groups WHERE id = $1",
        group_id,
    )
    if not group or group["lead_id"] != user_id:
        raise HTTPException(status_code=403, detail="Only group lead can refine")

    # Mark current round as manual_handoff or closed
    await db.execute(
        "UPDATE plan_rounds SET status = 'manual_handoff' WHERE id = $1",
        round_id,
    )

    # Create new round
    max_iter = await db.fetchval(
        "SELECT COALESCE(MAX(iteration), 0) FROM plan_rounds WHERE group_id = $1",
        group_id,
    )
    voting_deadline = datetime.utcnow() + timedelta(hours=24)
    round_row = await db.fetchrow(
        """
        INSERT INTO plan_rounds (group_id, iteration, status, voting_deadline)
        VALUES ($1, $2, 'voting_open', $3)
        RETURNING id, iteration, status
        """,
        group_id,
        (max_iter or 0) + 1,
        voting_deadline,
    )

    vibe_types = ["anchor", "pivot", "reach", "chill", "wildcard"]
    titles = [
        "Trivia Night at Local Pub",
        "Hiking Trail Adventure",
        "Potluck Dinner at Park",
        "Arcade & Pizza Night",
        "Sunset Kayaking",
    ]
    plans_data = []
    for vibe, title in zip(vibe_types, titles):
        plan_row = await db.fetchrow(
            """
            INSERT INTO plans (plan_round_id, title, description, vibe_type, location, venue_name, estimated_cost, logistics)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, title, description, vibe_type, location, venue_name, estimated_cost
            """,
            round_row["id"],
            title,
            f"Refined {vibe} option.",
            vibe,
            "Boston, MA",
            title.split(" at ")[0] if " at " in title else title,
            "$20-40 per person",
            json.dumps({"driver_view": {}, "passenger_view": {}}),
        )
        plans_data.append(
            {
                "id": str(plan_row["id"]),
                "title": plan_row["title"],
                "description": plan_row["description"],
                "vibe_type": plan_row["vibe_type"],
                "location": plan_row["location"],
                "venue_name": plan_row["venue_name"],
                "estimated_cost": plan_row["estimated_cost"],
            }
        )

    return {
        "plan_round_id": str(round_row["id"]),
        "plans": plans_data,
        "status": "voting_open",
        "iteration": round_row["iteration"],
        "voting_deadline": voting_deadline.isoformat(),
    }


@router.post("/{group_id}/plans/{round_id}/finalize", status_code=201)
async def finalize_plan(
    group_id: UUID,
    round_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Create event from winning plan when consensus reached. Lead only."""
    user_id = _get_user_id(x_user_id)

    lead = await db.fetchrow(
        "SELECT id FROM groups WHERE id = $1 AND lead_id = $2",
        group_id,
        user_id,
    )
    if not lead:
        raise HTTPException(status_code=403, detail="Only group lead can finalize")

    round_row = await db.fetchrow(
        "SELECT id, winning_plan_id, status FROM plan_rounds WHERE id = $1 AND group_id = $2",
        round_id,
        group_id,
    )
    if not round_row:
        raise HTTPException(status_code=404, detail="Plan round not found")

    winning_id = round_row["winning_plan_id"]
    if not winning_id:
        # Compute winning plan from votes
        votes = await db.fetch(
            "SELECT rankings FROM votes WHERE plan_round_id = $1",
            round_id,
        )
        first_choices = {}
        for v in votes:
            ranks = (
                json.loads(v["rankings"])
                if isinstance(v["rankings"], str)
                else v["rankings"]
            )
            if ranks:
                fc = ranks[0]
                first_choices[fc] = first_choices.get(fc, 0) + 1
        if first_choices:
            winning_id = UUID(max(first_choices, key=first_choices.get))
            await db.execute(
                "UPDATE plan_rounds SET winning_plan_id = $1, status = 'consensus_reached' WHERE id = $2",
                winning_id,
                round_id,
            )

    plan = await db.fetchrow(
        "SELECT id, title, date_time FROM plans WHERE id = $1",
        winning_id,
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Winning plan not found")

    event_date = plan["date_time"] or datetime.utcnow() + timedelta(days=7)
    event_row = await db.fetchrow(
        """
        INSERT INTO events (group_id, plan_id, plan_round_id, event_date)
        VALUES ($1, $2, $3, $4)
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
    return {
        "event_id": str(event_row["id"]),
        "plan_title": plan["title"],
        "event_date": event_row["event_date"].isoformat(),
    }

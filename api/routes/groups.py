"""Group routes."""
import json
from fastapi import APIRouter, HTTPException, Header
from uuid import UUID

from database import db
from models.schemas import (
    GroupCreate,
    GroupUpdate,
    GroupInviteRequest,
    GroupPreferencesUpdate,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _get_user_id(x_user_id: str | None = Header(None, alias="X-User-Id")) -> UUID:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID")


@router.post("", status_code=201)
async def create_group(
    body: GroupCreate,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    row = await db.fetchrow(
        """
        INSERT INTO groups (name, lead_id)
        VALUES ($1, $2)
        RETURNING id, name, lead_id, status, created_at
        """,
        body.name,
        user_id,
    )
    await db.execute(
        """
        INSERT INTO group_members (group_id, user_id, status, role)
        VALUES ($1, $2, 'active', 'lead')
        """,
        row["id"],
        user_id,
    )
    return {
        "group_id": str(row["id"]),
        "name": row["name"],
        "lead_id": str(row["lead_id"]),
        "members": [{"user_id": str(user_id), "role": "lead", "status": "active"}],
        "status": row["status"],
    }


@router.get("")
async def list_groups(x_user_id: str | None = Header(None, alias="X-User-Id")):
    user_id = _get_user_id(x_user_id)

    groups = await db.fetch(
        """
        SELECT g.id, g.name, g.lead_id, g.status
        FROM groups g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = $1 AND gm.status = 'active'
        ORDER BY g.name
        """,
        user_id,
    )

    invites = await db.fetch(
        """
        SELECT gi.id, gi.group_id, g.name as group_name, u.name as inviter_name
        FROM group_invites gi
        JOIN groups g ON gi.group_id = g.id
        JOIN users u ON gi.invited_by = u.id
        WHERE gi.email = (SELECT email FROM users WHERE id = $1) AND gi.status = 'pending'
        """,
        user_id,
    )

    return {
        "groups": [{"id": str(g["id"]), "name": g["name"], "lead_id": str(g["lead_id"]), "status": g["status"]} for g in groups],
        "pending_invites": [
            {"id": str(i["id"]), "group_id": str(i["group_id"]), "group_name": i["group_name"], "inviter_name": i["inviter_name"]}
            for i in invites
        ],
    }


@router.get("/{group_id}")
async def get_group(
    group_id: UUID,
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

    group = await db.fetchrow(
        "SELECT id, name, lead_id, status FROM groups WHERE id = $1",
        group_id,
    )
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    members = await db.fetch(
        """
        SELECT gm.id, gm.user_id, u.name, u.email, gm.status, gm.role
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        WHERE gm.group_id = $1 AND gm.status = 'active'
        """,
        group_id,
    )

    rounds = await db.fetch(
        """
        SELECT id, iteration, status, voting_deadline, created_at
        FROM plan_rounds
        WHERE group_id = $1 AND status = 'voting_open'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        group_id,
    )

    events = await db.fetch(
        """
        SELECT e.id, e.event_date, p.title as plan_title
        FROM events e
        JOIN plans p ON e.plan_id = p.id
        WHERE e.group_id = $1
        ORDER BY e.event_date DESC
        LIMIT 10
        """,
        group_id,
    )

    prefs_row = await db.fetchrow(
        """
        SELECT default_location, activity_likes, activity_dislikes, meetup_frequency, budget_preference, notes
        FROM group_preferences
        WHERE group_id = $1 AND user_id = $2
        """,
        group_id,
        user_id,
    )
    preferences = {}
    if prefs_row:
        preferences = {
            "default_location": prefs_row["default_location"],
            "activity_likes": prefs_row["activity_likes"] if prefs_row["activity_likes"] is not None else [],
            "activity_dislikes": prefs_row["activity_dislikes"] if prefs_row["activity_dislikes"] is not None else [],
            "meetup_frequency": prefs_row["meetup_frequency"],
            "budget_preference": prefs_row["budget_preference"],
            "notes": prefs_row["notes"],
        }

    return {
        "group_id": str(group["id"]),
        "name": group["name"],
        "lead_id": str(group["lead_id"]),
        "members": [
            {"id": str(m["id"]), "user_id": str(m["user_id"]), "name": m["name"], "email": m["email"], "status": m["status"], "role": m["role"]}
            for m in members
        ],
        "current_plans": [
            {"round_id": str(r["id"]), "iteration": r["iteration"], "status": r["status"], "voting_deadline": r["voting_deadline"].isoformat() if r["voting_deadline"] else None}
            for r in rounds
        ],
        "events": [
            {"id": str(e["id"]), "event_date": e["event_date"].isoformat(), "plan_title": e["plan_title"]}
            for e in events
        ],
        "preferences": preferences,
        "history": [],
    }


@router.put("/{group_id}")
async def update_group(
    group_id: UUID,
    body: GroupUpdate,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Update group settings (name)."""
    user_id = _get_user_id(x_user_id)

    lead = await db.fetchrow(
        "SELECT id FROM groups WHERE id = $1 AND lead_id = $2",
        group_id,
        user_id,
    )
    if not lead:
        raise HTTPException(status_code=403, detail="Only group lead can update")

    if body.name:
        await db.execute(
            "UPDATE groups SET name = $1, updated_at = NOW() WHERE id = $2",
            body.name,
            group_id,
        )
    group = await db.fetchrow(
        "SELECT id, name, lead_id, status FROM groups WHERE id = $1",
        group_id,
    )
    return {"group_id": str(group["id"]), "name": group["name"], "status": group["status"]}


@router.post("/{group_id}/invite", status_code=201)
async def invite_members(
    group_id: UUID,
    body: GroupInviteRequest,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    if len(body.emails) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 invites per request")

    lead = await db.fetchrow(
        "SELECT id FROM groups WHERE id = $1 AND lead_id = $2",
        group_id,
        user_id,
    )
    if not lead:
        raise HTTPException(status_code=403, detail="Only group lead can invite")

    invites_sent = []
    for email in body.emails:
        try:
            await db.execute(
                """
                INSERT INTO group_invites (group_id, email, invited_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (group_id, email) DO NOTHING
                """,
                group_id,
                email,
                user_id,
            )
            invites_sent.append({"email": email, "status": "pending"})
        except Exception:
            invites_sent.append({"email": email, "status": "error"})

    return {"invites_sent": invites_sent}


@router.post("/{group_id}/invite/accept")
async def accept_invite(
    group_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    user = await db.fetchrow("SELECT email FROM users WHERE id = $1", user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    invite = await db.fetchrow(
        "SELECT id FROM group_invites WHERE group_id = $1 AND email = $2 AND status = 'pending'",
        group_id,
        user["email"],
    )
    if not invite:
        raise HTTPException(status_code=404, detail="No pending invite found")

    await db.execute(
        "UPDATE group_invites SET status = 'accepted' WHERE id = $1",
        invite["id"],
    )
    await db.execute(
        """
        INSERT INTO group_members (group_id, user_id, status, role)
        VALUES ($1, $2, 'active', 'member')
        ON CONFLICT (group_id, user_id) DO UPDATE SET status = 'active'
        """,
        group_id,
        user_id,
    )
    return {"group_id": str(group_id), "member_status": "active"}


@router.post("/{group_id}/invite/reject")
async def reject_invite(
    group_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    user = await db.fetchrow("SELECT email FROM users WHERE id = $1", user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.execute(
        """
        UPDATE group_invites SET status = 'rejected'
        WHERE group_id = $1 AND email = $2 AND status = 'pending'
        """,
        group_id,
        user["email"],
    )
    return {"group_id": str(group_id), "member_status": "rejected"}


@router.put("/{group_id}/preferences")
async def update_group_preferences(
    group_id: UUID,
    body: GroupPreferencesUpdate,
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

    data = body.model_dump(exclude_none=True)
    if not data:
        return {"group_id": str(group_id), "user_id": str(user_id), "preferences": {}}

    # JSONB columns need JSON strings; use None for partial updates so COALESCE keeps existing
    activity_likes = json.dumps(data["activity_likes"]) if "activity_likes" in data else None
    activity_dislikes = json.dumps(data["activity_dislikes"]) if "activity_dislikes" in data else None
    await db.execute(
        """
        INSERT INTO group_preferences (group_id, user_id, default_location, activity_likes, activity_dislikes, meetup_frequency, budget_preference, notes)
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
        ON CONFLICT (group_id, user_id) DO UPDATE SET
            default_location = COALESCE(EXCLUDED.default_location, group_preferences.default_location),
            activity_likes = COALESCE(EXCLUDED.activity_likes, group_preferences.activity_likes),
            activity_dislikes = COALESCE(EXCLUDED.activity_dislikes, group_preferences.activity_dislikes),
            meetup_frequency = COALESCE(EXCLUDED.meetup_frequency, group_preferences.meetup_frequency),
            budget_preference = COALESCE(EXCLUDED.budget_preference, group_preferences.budget_preference),
            notes = COALESCE(EXCLUDED.notes, group_preferences.notes),
            updated_at = NOW()
        """,
        group_id,
        user_id,
        data.get("default_location"),
        activity_likes,
        activity_dislikes,
        data.get("meetup_frequency"),
        data.get("budget_preference"),
        data.get("notes"),
    )
    return {"group_id": str(group_id), "user_id": str(user_id), "preferences": data}

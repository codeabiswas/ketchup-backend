# api/routes/users.py

"""User routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user_id
from database import db
from models.schemas import UserPreferencesUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=dict)
async def get_current_user(user_id: UUID = Depends(get_current_user_id)):
    """Get current user profile with groups and pending invites."""
    user = await db.fetchrow(
        "SELECT id, email, name FROM users WHERE id = $1",
        user_id,
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    groups = await db.fetch(
        """
        SELECT g.id, g.name, g.lead_id, g.status, gm.role
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
        WHERE gi.email = $1 AND gi.status = 'pending'
        """,
        user["email"],
    )

    return {
        "user_id": str(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "google_calendar_connected": False,
        "groups": [
            {
                "id": str(g["id"]),
                "name": g["name"],
                "lead_id": str(g["lead_id"]),
                "status": g["status"],
                "role": g["role"],
            }
            for g in groups
        ],
        "pending_invites": [
            {
                "id": str(i["id"]),
                "group_id": str(i["group_id"]),
                "group_name": i["group_name"],
                "inviter_name": i["inviter_name"],
            }
            for i in invites
        ],
    }


@router.put("/me/preferences")
async def update_preferences(
    body: UserPreferencesUpdate,
    user_id: UUID = Depends(get_current_user_id),
):
    return {"user_id": str(user_id), "preferences": body.model_dump(exclude_none=True)}

# api/routes/feedback.py

"""Post-event feedback routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user_id
from database import db
from models.schemas import FeedbackCreate

router = APIRouter(prefix="/api/groups", tags=["feedback"])


@router.post("/{group_id}/events/{event_id}/feedback", status_code=201)
async def submit_feedback(
    group_id: UUID,
    event_id: UUID,
    body: FeedbackCreate,
    user_id: UUID = Depends(get_current_user_id),
):
    """Submit post-event feedback (Loved/Liked/Disliked)."""
    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    event = await db.fetchrow(
        "SELECT id FROM events WHERE id = $1 AND group_id = $2",
        event_id,
        group_id,
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if body.rating not in ("loved", "liked", "disliked"):
        raise HTTPException(
            status_code=400, detail="Rating must be loved, liked, or disliked"
        )

    row = await db.fetchrow(
        """
        INSERT INTO feedback (event_id, user_id, rating, notes, attended)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (event_id, user_id) DO UPDATE SET rating = EXCLUDED.rating, notes = EXCLUDED.notes, attended = EXCLUDED.attended
        RETURNING id, rating, notes, attended
        """,
        event_id,
        user_id,
        body.rating,
        body.notes,
        body.attended,
    )
    return {
        "feedback_id": str(row["id"]),
        "rating": row["rating"],
        "notes": row["notes"],
    }


@router.get("/{group_id}/events/{event_id}/feedback")
async def get_feedback(
    group_id: UUID,
    event_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    """Get all feedback for an event."""
    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    event = await db.fetchrow(
        "SELECT id FROM events WHERE id = $1 AND group_id = $2",
        event_id,
        group_id,
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    rows = await db.fetch(
        """
        SELECT f.id, f.user_id, u.name, f.rating, f.notes, f.attended
        FROM feedback f
        JOIN users u ON f.user_id = u.id
        WHERE f.event_id = $1
        """,
        event_id,
    )

    loved = sum(1 for r in rows if r["rating"] == "loved")
    liked = sum(1 for r in rows if r["rating"] == "liked")
    disliked = sum(1 for r in rows if r["rating"] == "disliked")

    return {
        "feedbacks": [
            {
                "id": str(r["id"]),
                "user_id": str(r["user_id"]),
                "name": r["name"],
                "rating": r["rating"],
                "notes": r["notes"],
                "attended": r["attended"],
            }
            for r in rows
        ],
        "summary": {"loved": loved, "liked": liked, "disliked": disliked},
    }

"""Availability blocks routes."""
from fastapi import APIRouter, HTTPException, Header
from uuid import UUID
from datetime import time

from database import db
from models.schemas import AvailabilityBlocksUpdate

router = APIRouter(prefix="/api/users", tags=["availability"])


def _get_user_id(x_user_id: str | None = Header(None, alias="X-User-Id")) -> UUID:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID")


@router.get("/me/availability")
async def get_availability(x_user_id: str | None = Header(None, alias="X-User-Id")):
    user_id = _get_user_id(x_user_id)

    rows = await db.fetch(
        """
        SELECT id, day_of_week, start_time, end_time, label
        FROM availability_blocks
        WHERE user_id = $1
        ORDER BY day_of_week, start_time
        """,
        user_id,
    )
    return {
        "blocks": [
            {
                "id": str(r["id"]),
                "day_of_week": r["day_of_week"],
                "start_time": str(r["start_time"]) if r["start_time"] else None,
                "end_time": str(r["end_time"]) if r["end_time"] else None,
                "label": r["label"],
            }
            for r in rows
        ],
    }


@router.put("/me/availability")
async def update_availability(
    body: AvailabilityBlocksUpdate,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    user_id = _get_user_id(x_user_id)

    await db.execute("DELETE FROM availability_blocks WHERE user_id = $1", user_id)

    blocks = []
    for b in body.blocks:
        start = time.fromisoformat(b.start_time) if ":" in b.start_time else time(9, 0)
        end = time.fromisoformat(b.end_time) if ":" in b.end_time else time(17, 0)
        row = await db.fetchrow(
            """
            INSERT INTO availability_blocks (user_id, day_of_week, start_time, end_time, label)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, day_of_week, start_time, end_time, label
            """,
            user_id,
            b.day_of_week,
            start,
            end,
            b.label,
        )
        blocks.append({
            "id": str(row["id"]),
            "day_of_week": row["day_of_week"],
            "start_time": str(row["start_time"]),
            "end_time": str(row["end_time"]),
            "label": row["label"],
        })

    return {"blocks": blocks}

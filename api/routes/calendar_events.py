"""Add Ketchup events to user's Google Calendar."""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Header
from uuid import UUID

from config import get_settings
from database import db

router = APIRouter(prefix="/api", tags=["calendar"])


def _get_user_id(x_user_id: str | None = Header(None, alias="X-User-Id")) -> UUID:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID")


async def _get_valid_token(user_id: UUID) -> str:
    import httpx

    row = await db.fetchrow(
        "SELECT access_token, refresh_token, expires_at FROM google_tokens WHERE user_id = $1",
        user_id,
    )
    if not row:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    # If expired, refresh (simplified - in prod use google-auth)
    if row["expires_at"] and row["expires_at"] <= datetime.utcnow():
        if not row["refresh_token"]:
            raise HTTPException(status_code=400, detail="Token expired, please reconnect")
        settings = get_settings()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": row["refresh_token"],
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Token refresh failed")
        data = r.json()
        expires_at = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
        await db.execute(
            "UPDATE google_tokens SET access_token = $1, expires_at = $2, updated_at = NOW() WHERE user_id = $3",
            data["access_token"],
            expires_at,
            user_id,
        )
        return data["access_token"]
    return row["access_token"]


@router.post("/events/{event_id}/add-to-calendar")
async def add_event_to_calendar(
    event_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Add a Ketchup event to the user's Google Calendar."""
    user_id = _get_user_id(x_user_id)
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=503,
            detail="Google Calendar not configured",
        )

    event_row = await db.fetchrow(
        """
        SELECT e.id, e.event_date, e.group_id, p.title, p.location, p.venue_name, p.description
        FROM events e
        JOIN plans p ON e.plan_id = p.id
        WHERE e.id = $1
        """,
        event_id,
    )
    if not event_row:
        raise HTTPException(status_code=404, detail="Event not found")

    # Check user is in the group
    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        event_row["group_id"],
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this event's group")

    access_token = await _get_valid_token(user_id)

    event_date = event_row["event_date"]
    if isinstance(event_date, datetime):
        start_dt = event_date
    else:
        start_dt = datetime.fromisoformat(str(event_date).replace("Z", "+00:00"))
    end_dt = start_dt + timedelta(hours=2)

    summary = event_row["title"] or "Ketchup Event"
    location = event_row["location"] or event_row["venue_name"] or ""
    description = event_row["description"] or ""

    import httpx

    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "UTC",
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Google Calendar error: {resp.text[:200]}",
        )

    data = resp.json()
    return {
        "google_event_id": data.get("id"),
        "html_link": data.get("htmlLink"),
        "message": "Event added to your calendar",
    }

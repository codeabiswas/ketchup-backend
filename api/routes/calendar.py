"""Google Calendar OAuth and event sync routes."""
import logging
from datetime import datetime, timedelta, time
from urllib.parse import urlencode
from fastapi import APIRouter, HTTPException, Header, Query

logger = logging.getLogger(__name__)
from fastapi.responses import RedirectResponse
from uuid import UUID

from config import get_settings
from database import db

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


def _get_user_id(x_user_id: str | None = Header(None, alias="X-User-Id")) -> UUID:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID")


def _calendar_available() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


@router.get("/connect")
async def get_connect_url(
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Return Google OAuth URL for user to connect calendar."""
    user_id = _get_user_id(x_user_id)
    if not _calendar_available():
        raise HTTPException(
            status_code=503,
            detail="Google Calendar not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": str(user_id),
    }
    url = GOOGLE_AUTH_URI + "?" + urlencode(params)
    return {"auth_url": url}


@router.get("/callback")
async def oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    """
    OAuth callback - exchange code for tokens and store.
    Redirects to frontend with ?calendar=connected or ?calendar=error
    """
    settings = get_settings()
    if not _calendar_available():
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?calendar=config_error"
        )

    if error:
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?calendar=denied"
        )
    if not code or not state:
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?calendar=error"
        )

    try:
        user_id = UUID(state)
    except ValueError:
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?calendar=error"
        )

    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URI,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?calendar=error"
        )

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in", 3600)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if not access_token:
        return RedirectResponse(
            url=f"{settings.frontend_url}/settings?calendar=error"
        )

    await db.execute(
        """
        INSERT INTO google_tokens (user_id, access_token, refresh_token, expires_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE SET
            access_token = EXCLUDED.access_token,
            refresh_token = COALESCE(EXCLUDED.refresh_token, google_tokens.refresh_token),
            expires_at = EXCLUDED.expires_at,
            updated_at = NOW()
        """,
        user_id,
        access_token,
        refresh_token,
        expires_at,
    )

    return RedirectResponse(
        url=f"{settings.frontend_url}/settings?calendar=connected"
    )


@router.get("/status")
async def get_status(
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Check if user has Google Calendar connected and get details."""
    user_id = _get_user_id(x_user_id)
    row = await db.fetchrow(
        "SELECT id, access_token, expires_at FROM google_tokens WHERE user_id = $1",
        user_id,
    )
    if not row:
        return {"connected": False, "available": _calendar_available(), "email": None}

    # Fetch connected account email from Google
    email = None
    if row["access_token"]:
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {row['access_token']}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    email = data.get("email")
        except Exception:
            pass

    return {
        "connected": True,
        "available": _calendar_available(),
        "email": email,
    }


async def _get_valid_token(user_id: UUID) -> str:
    """Get access token. Tries stored token; refreshes if Google returns 401."""
    row = await db.fetchrow(
        "SELECT access_token, refresh_token FROM google_tokens WHERE user_id = $1",
        user_id,
    )
    if not row:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    return row["access_token"]


async def _refresh_and_get_token(user_id: UUID) -> str:
    """Refresh token and return new access token."""
    row = await db.fetchrow(
        "SELECT access_token, refresh_token FROM google_tokens WHERE user_id = $1",
        user_id,
    )
    if not row or not row["refresh_token"]:
        raise HTTPException(status_code=400, detail="Token expired. Please disconnect and reconnect Google Calendar.")
    import httpx
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            GOOGLE_TOKEN_URI,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": row["refresh_token"],
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Token refresh failed. Please reconnect Google Calendar.")
    data = r.json()
    new_expires = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
    await db.execute(
        "UPDATE google_tokens SET access_token = $1, expires_at = $2, updated_at = NOW() WHERE user_id = $3",
        data["access_token"],
        new_expires,
        user_id,
    )
    return data["access_token"]


@router.get("/busy")
async def get_busy_times(
    x_user_id: str | None = Header(None, alias="X-User-Id"),
    days: int = Query(7, ge=1, le=14),
):
    """Fetch busy times from Google Calendar for the next N days."""
    user_id = _get_user_id(x_user_id)
    if not _calendar_available():
        raise HTTPException(status_code=503, detail="Google Calendar not configured")
    access_token = await _get_valid_token(user_id)

    import httpx
    time_min = datetime.utcnow()
    time_max = time_min + timedelta(days=days)
    params = {
        "timeMin": time_min.isoformat() + "Z",
        "timeMax": time_max.isoformat() + "Z",
        "singleEvents": "true",
        "orderBy": "startTime",
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch calendar events")

    data = r.json()
    events = data.get("items", [])
    blocks = []
    for ev in events:
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
        if not start or not end:
            continue
        try:
            if "T" in start:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            else:
                start_dt = datetime.fromisoformat(start + "T00:00:00")
                end_dt = datetime.fromisoformat(end + "T23:59:59")
            # day_of_week: 0=Sun, 1=Mon, ..., 6=Sat (matches availability_blocks)
            dow = (start_dt.weekday() + 1) % 7
            blocks.append({
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "summary": ev.get("summary", "Busy"),
                "day_of_week": dow,
                "start_time": start_dt.strftime("%H:%M"),
                "end_time": end_dt.strftime("%H:%M"),
            })
        except (ValueError, TypeError):
            continue

    return {"blocks": blocks, "count": len(blocks)}


@router.post("/import-blocks")
async def import_calendar_blocks(
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Import busy times from Google Calendar into availability blocks."""
    try:
        user_id = _get_user_id(x_user_id)
        if not _calendar_available():
            raise HTTPException(status_code=503, detail="Google Calendar not configured")
        access_token = await _get_valid_token(user_id)

        import httpx
        time_min = datetime.utcnow()
        time_max = time_min + timedelta(days=30)
        params = {
            "timeMin": time_min.isoformat() + "Z",
            "timeMax": time_max.isoformat() + "Z",
            "singleEvents": "true",
        }

        async def fetch_events(token: str):
            async with httpx.AsyncClient() as client:
                return await client.get(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )

        r = await fetch_events(access_token)
        if r.status_code == 401:
            access_token = await _refresh_and_get_token(user_id)
            r = await fetch_events(access_token)
        if r.status_code != 200:
            err_detail = r.text[:500] if r.text else str(r.status_code)
            logger.warning("Google Calendar API error: status=%s body=%s", r.status_code, err_detail)
            if r.status_code == 401:
                raise HTTPException(
                    status_code=400,
                    detail="Calendar token expired. Please disconnect and reconnect Google Calendar in Settings.",
                )
            if r.status_code == 403:
                raise HTTPException(
                    status_code=400,
                    detail="Calendar access denied. Enable Google Calendar API at console.cloud.google.com/apis/library/calendar-json.",
                )
            if r.status_code == 404:
                raise HTTPException(
                    status_code=400,
                    detail="Calendar not found. Try disconnecting and reconnecting Google Calendar.",
                )
            raise HTTPException(status_code=400, detail=f"Calendar error ({r.status_code}): {err_detail}")

        data = r.json()
        events = data.get("items", [])

        # Build unique slots to import (deduplicate same day+time in one run)
        seen = set()
        slots_to_insert = []
        for ev in events:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
            if not start or not end or "T" not in start:
                continue
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                dow = (start_dt.weekday() + 1) % 7
                start_t = start_dt.time()
                end_t = end_dt.time()
                slot_key = (dow, start_t, end_t)
                if slot_key in seen:
                    continue
                seen.add(slot_key)
                label = "Calendar: " + ((ev.get("summary") or "Busy")[:90])
                slots_to_insert.append((dow, start_t, end_t, label))
            except (ValueError, TypeError):
                continue

        # Delete any existing blocks at these exact slots (removes old calendar imports + duplicates)
        for dow, start_t, end_t, _ in slots_to_insert:
            await db.execute(
                """
                DELETE FROM availability_blocks
                WHERE user_id = $1 AND day_of_week = $2 AND start_time = $3 AND end_time = $4
                """,
                user_id,
                dow,
                start_t,
                end_t,
            )

        imported = 0
        for dow, start_t, end_t, label in slots_to_insert:
            await db.execute(
                """
                INSERT INTO availability_blocks (user_id, day_of_week, start_time, end_time, label)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_id,
                dow,
                start_t,
                end_t,
                label,
            )
            imported += 1

        return {"imported": imported, "message": f"Imported {imported} blocks from Google Calendar"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect")
async def disconnect(
    x_user_id: str | None = Header(None, alias="X-User-Id"),
):
    """Remove Google Calendar connection."""
    user_id = _get_user_id(x_user_id)
    await db.execute(
        "DELETE FROM google_tokens WHERE user_id = $1",
        user_id,
    )
    return {"connected": False}

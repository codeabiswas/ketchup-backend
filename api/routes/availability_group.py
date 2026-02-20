"""Group availability - compute common free slots from manual blocks."""
from fastapi import APIRouter, HTTPException, Header
from uuid import UUID
from datetime import datetime, timedelta, time
from typing import Optional

from database import db

router = APIRouter(prefix="/api/groups", tags=["availability"])


def _get_user_id(x_user_id: str | None = Header(None, alias="X-User-Id")) -> UUID:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user ID")


def _expand_blocks_to_intervals(
    blocks: list, time_min: datetime, time_max: datetime
) -> list[tuple[datetime, datetime]]:
    """Expand recurring weekly blocks into (start, end) intervals for the window."""
    intervals = []
    # day_of_week: 0=Sunday, 1=Monday, ..., 6=Saturday
    for block in blocks:
        dow = block["day_of_week"]
        start_t = block["start_time"]
        end_t = block["end_time"]
        if isinstance(start_t, str):
            h, m = map(int, start_t.split(":")[:2])
            start_t = time(h, m)
        if isinstance(end_t, str):
            h, m = map(int, end_t.split(":")[:2])
            end_t = time(h, m)

        # Iterate over days in range (dow: 0=Sun, 1=Mon, ..., 6=Sat; Python weekday: 0=Mon, 6=Sun)
        current = time_min.replace(hour=0, minute=0, second=0, microsecond=0)
        target_weekday = (dow + 6) % 7  # map 0=Sun->6, 1=Mon->0, etc.
        while current <= time_max:
            if current.weekday() == target_weekday:
                start_dt = datetime.combine(current.date(), start_t)
                end_dt = datetime.combine(current.date(), end_t)
                if start_dt < time_max and end_dt > time_min:
                    intervals.append(
                        (max(start_dt, time_min), min(end_dt, time_max))
                    )
            current += timedelta(days=1)
    return intervals


def _merge_overlapping(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_i = sorted(intervals)
    merged = [sorted_i[0]]
    for s, e in sorted_i[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _split_slot_by_day(slot_start: datetime, slot_end: datetime, slot_hours: float) -> list[dict]:
    """Split a long free slot into day-sized chunks so users see options per day."""
    result = []
    current = slot_start
    while current < slot_end:
        day_end = current.replace(hour=23, minute=59, second=59, microsecond=999)
        chunk_end = min(day_end, slot_end)
        if (chunk_end - current).total_seconds() >= slot_hours * 3600:
            result.append({
                "start": current.isoformat(),
                "end": chunk_end.isoformat(),
            })
        # Advance to start of next calendar day
        current = datetime.combine(chunk_end.date() + timedelta(days=1), time(0, 0, 0))
    return result


def _find_common_free(
    all_busy: dict, time_min: datetime, time_max: datetime, slot_hours: float = 2
) -> list[dict]:
    """Find slots where ALL members are free. Returns slots of at least slot_hours.
    Long continuous slots are split by day so users see options per day."""
    if not all_busy:
        return [{"start": time_min.isoformat(), "end": time_max.isoformat()}]

    # Get all busy intervals merged per user
    merged = {uid: _merge_overlapping(busy) for uid, busy in all_busy.items()}

    # Simple approach: find gaps in the union of all busy periods
    all_starts = []
    all_ends = []
    for busy in merged.values():
        for s, e in busy:
            all_starts.append(s)
            all_ends.append(e)

    if not all_starts:
        return [{"start": time_min.isoformat(), "end": time_max.isoformat()}]

    # Sort and find gaps
    events = sorted([(s, 1) for s in all_starts] + [(e, -1) for e in all_ends])
    count = 0
    gap_start = None
    free_slots = []
    for t, delta in events:
        count += delta
        if count == 0:
            gap_start = t
        elif gap_start and count == 1:
            if (t - gap_start).total_seconds() >= slot_hours * 3600:
                # Split slots longer than 24h into day-sized chunks
                if (t - gap_start).total_seconds() > 24 * 3600:
                    free_slots.extend(_split_slot_by_day(gap_start, t, slot_hours))
                else:
                    free_slots.append({
                        "start": gap_start.isoformat(),
                        "end": t.isoformat(),
                    })
            gap_start = None

    return free_slots[:15]  # Limit to 15 slots (more days visible)


@router.post("/{group_id}/availability")
async def compute_group_availability(
    group_id: UUID,
    x_user_id: str | None = Header(None, alias="X-User-Id"),
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
):
    """
    Compute common free slots across group members (manual blocks only for local dev).
    time_min, time_max: ISO format, default to next 7 days.
    """
    user_id = _get_user_id(x_user_id)

    member = await db.fetchrow(
        "SELECT id FROM group_members WHERE group_id = $1 AND user_id = $2 AND status = 'active'",
        group_id,
        user_id,
    )
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    now = datetime.utcnow()
    start = datetime.fromisoformat(time_min.replace("Z", "+00:00")) if time_min else now
    end = datetime.fromisoformat(time_max.replace("Z", "+00:00")) if time_max else now + timedelta(days=7)

    members = await db.fetch(
        "SELECT user_id FROM group_members WHERE group_id = $1 AND status = 'active'",
        group_id,
    )

    all_busy = {}
    for m in members:
        blocks = await db.fetch(
            """
            SELECT day_of_week, start_time, end_time
            FROM availability_blocks
            WHERE user_id = $1
            """,
            m["user_id"],
        )
        intervals = _expand_blocks_to_intervals(
            [dict(b) for b in blocks], start, end
        )
        all_busy[str(m["user_id"])] = intervals

    common_free = _find_common_free(all_busy, start, end)

    return {
        "common_slots": common_free,
        "per_user_busy": {uid: len(busy) for uid, busy in all_busy.items()},
    }

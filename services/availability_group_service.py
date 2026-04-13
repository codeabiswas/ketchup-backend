"""Group availability domain service.

Returns common free slots as **weekday-based patterns** (e.g. "Monday 5 PM – 9 PM")
clipped to sensible plannable hours (8 AM – 11 PM).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import UUID

from database import db
from services.group_access import require_active_group_member

# Only show free slots within these hours (Issue 10: filter overnight).
PLANNABLE_START = time(8, 0)
PLANNABLE_END = time(23, 0)

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def _time_to_str(t: time) -> str:
    """Format time as '5:00 PM'."""
    hour = t.hour
    minute = t.minute
    ampm = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    if minute == 0:
        return f"{display_hour}:00 {ampm}"
    return f"{display_hour}:{minute:02d} {ampm}"


def _parse_time(raw: str | time) -> time:
    if isinstance(raw, time):
        return raw
    parts = raw.split(":")[:2]
    return time(int(parts[0]), int(parts[1]))


def _compute_weekday_free_slots(
    all_blocks: dict[str, list[dict]],
) -> list[dict]:
    """Compute common free slots per weekday across all users.

    For each day of the week (0=Sun..6=Sat):
    1. Collect each user's busy intervals on that day.
    2. Find gaps where ALL users are free.
    3. Clip to plannable hours and filter out short (<1h) slots.

    Returns list of {day_of_week, day_name, start_time, end_time}.
    """
    results: list[dict] = []

    for dow in range(7):
        # Collect busy intervals for this day of week per user.
        user_busy: dict[str, list[tuple[time, time]]] = {}
        for uid, blocks in all_blocks.items():
            intervals = []
            for block in blocks:
                if block["day_of_week"] == dow:
                    s = _parse_time(block["start_time"])
                    e = _parse_time(block["end_time"])
                    if s < e:
                        intervals.append((s, e))
            user_busy[uid] = intervals

        if not user_busy:
            continue

        # Merge all busy intervals across all users into one timeline.
        all_intervals: list[tuple[time, time]] = []
        for intervals in user_busy.values():
            all_intervals.extend(intervals)

        if not all_intervals:
            # Everyone is free all day — return the plannable window.
            results.append({
                "day_of_week": dow,
                "day_name": DAY_NAMES[dow],
                "start_time": _time_to_str(PLANNABLE_START),
                "end_time": _time_to_str(PLANNABLE_END),
            })
            continue

        # Sweep-line on this weekday to find free gaps.
        events: list[tuple[int, int]] = []  # (minutes_since_midnight, +1/-1)
        for s, e in all_intervals:
            events.append((s.hour * 60 + s.minute, 1))
            events.append((e.hour * 60 + e.minute, -1))
        events.sort(key=lambda x: (x[0], -x[1]))

        # Find gaps where count == 0 (nobody busy).
        plannable_start_min = PLANNABLE_START.hour * 60 + PLANNABLE_START.minute
        plannable_end_min = PLANNABLE_END.hour * 60 + PLANNABLE_END.minute

        count = 0
        gap_start: int | None = plannable_start_min  # Start of day (plannable)
        free_gaps: list[tuple[int, int]] = []

        for moment, delta in events:
            if gap_start is not None and count == 0 and moment > gap_start:
                free_gaps.append((gap_start, moment))
            count += delta
            if count == 0:
                gap_start = moment
            else:
                gap_start = None

        # Close final gap to end of plannable day.
        if gap_start is not None and count == 0 and plannable_end_min > gap_start:
            free_gaps.append((gap_start, plannable_end_min))

        # Clip to plannable hours and filter short slots.
        for gap_s, gap_e in free_gaps:
            clipped_s = max(gap_s, plannable_start_min)
            clipped_e = min(gap_e, plannable_end_min)
            duration_hours = (clipped_e - clipped_s) / 60
            if duration_hours >= 1.0:
                start_t = time(clipped_s // 60, clipped_s % 60)
                end_t = time(clipped_e // 60, clipped_e % 60)
                results.append({
                    "day_of_week": dow,
                    "day_name": DAY_NAMES[dow],
                    "start_time": _time_to_str(start_t),
                    "end_time": _time_to_str(end_t),
                })

    return results


async def compute_group_availability(
    group_id: UUID,
    user_id: UUID,
    time_min: str | None,
    time_max: str | None,
) -> dict[str, object]:
    await require_active_group_member(group_id, user_id)

    members = await db.fetch(
        "SELECT user_id FROM group_members WHERE group_id = $1 AND status = 'active'",
        group_id,
    )

    all_blocks: dict[str, list[dict]] = {}
    for member in members:
        blocks = await db.fetch(
            """
            SELECT day_of_week, start_time, end_time
            FROM availability_blocks
            WHERE user_id = $1
            """,
            member["user_id"],
        )
        all_blocks[str(member["user_id"])] = [dict(block) for block in blocks]

    common_free = _compute_weekday_free_slots(all_blocks)
    return {
        "common_slots": common_free,
        "per_user_busy": {uid: len(blocks) for uid, blocks in all_blocks.items()},
    }


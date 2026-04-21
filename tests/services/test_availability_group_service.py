"""Unit tests for services/availability_group_service.py.

Focuses on pure helper functions: _time_to_str, _parse_time, and
_compute_weekday_free_slots — all are deterministic and database-free.
"""

from __future__ import annotations

from datetime import time

import pytest

from services.availability_group_service import (
    DAY_NAMES,
    PLANNABLE_END,
    PLANNABLE_START,
    _compute_weekday_free_slots,
    _parse_time,
    _time_to_str,
)


# ---------------------------------------------------------------------------
# _time_to_str
# ---------------------------------------------------------------------------

def test_time_to_str_midnight():
    assert _time_to_str(time(0, 0)) == "12:00 AM"


def test_time_to_str_noon():
    assert _time_to_str(time(12, 0)) == "12:00 PM"


def test_time_to_str_8am():
    assert _time_to_str(time(8, 0)) == "8:00 AM"


def test_time_to_str_11pm():
    assert _time_to_str(time(23, 0)) == "11:00 PM"


def test_time_to_str_530pm():
    assert _time_to_str(time(17, 30)) == "5:30 PM"


def test_time_to_str_1am():
    assert _time_to_str(time(1, 0)) == "1:00 AM"


def test_time_to_str_9_05am():
    assert _time_to_str(time(9, 5)) == "9:05 AM"


def test_time_to_str_plannable_start():
    # Verify the constant itself formats correctly
    assert _time_to_str(PLANNABLE_START) == "8:00 AM"


def test_time_to_str_plannable_end():
    assert _time_to_str(PLANNABLE_END) == "11:00 PM"


# ---------------------------------------------------------------------------
# _parse_time
# ---------------------------------------------------------------------------

def test_parse_time_passes_through_time_object():
    t = time(9, 30)
    assert _parse_time(t) is t


def test_parse_time_parses_hhmm_string():
    assert _parse_time("08:00") == time(8, 0)


def test_parse_time_parses_2330():
    assert _parse_time("23:30") == time(23, 30)


def test_parse_time_parses_midnight():
    assert _parse_time("00:00") == time(0, 0)


def test_parse_time_ignores_seconds_component():
    # "08:00:00" → splits on ":" → ["08","00","00"][:2] = ["08","00"]
    assert _parse_time("08:00:00") == time(8, 0)


# ---------------------------------------------------------------------------
# _compute_weekday_free_slots — empty input
# ---------------------------------------------------------------------------

def test_compute_weekday_free_slots_empty_dict():
    assert _compute_weekday_free_slots({}) == []


# ---------------------------------------------------------------------------
# _compute_weekday_free_slots — all free (no busy blocks)
# ---------------------------------------------------------------------------

def test_compute_all_free_returns_plannable_window_per_day():
    all_blocks = {"user-1": []}
    results = _compute_weekday_free_slots(all_blocks)
    # All 7 days should have the full plannable window
    assert len(results) == 7
    for slot in results:
        assert slot["start_time"] == "8:00 AM"
        assert slot["end_time"] == "11:00 PM"


def test_compute_all_free_covers_all_seven_days():
    all_blocks = {"user-1": []}
    results = _compute_weekday_free_slots(all_blocks)
    days = {s["day_of_week"] for s in results}
    assert days == {0, 1, 2, 3, 4, 5, 6}


def test_compute_all_free_day_names_are_correct():
    all_blocks = {"user-1": []}
    results = _compute_weekday_free_slots(all_blocks)
    for slot in results:
        assert slot["day_name"] == DAY_NAMES[slot["day_of_week"]]


# ---------------------------------------------------------------------------
# _compute_weekday_free_slots — busy splits the day
# ---------------------------------------------------------------------------

def test_compute_busy_midday_splits_into_two_slots():
    # User is busy 12:00–14:00 on Monday (dow=1)
    all_blocks = {
        "user-1": [{"day_of_week": 1, "start_time": "12:00", "end_time": "14:00"}]
    }
    results = _compute_weekday_free_slots(all_blocks)
    monday = [s for s in results if s["day_of_week"] == 1]
    assert len(monday) == 2
    start_times = {s["start_time"] for s in monday}
    assert "8:00 AM" in start_times
    assert "2:00 PM" in start_times


def test_compute_busy_at_start_leaves_afternoon_free():
    # User busy 8:00–18:00 → free 18:00–23:00 (5 h)
    all_blocks = {
        "user-1": [{"day_of_week": 2, "start_time": "08:00", "end_time": "18:00"}]
    }
    results = _compute_weekday_free_slots(all_blocks)
    tuesday = [s for s in results if s["day_of_week"] == 2]
    assert len(tuesday) == 1
    assert tuesday[0]["start_time"] == "6:00 PM"
    assert tuesday[0]["end_time"] == "11:00 PM"


def test_compute_busy_at_end_leaves_morning_free():
    # User busy 20:00–23:00 → free 08:00–20:00 (12 h)
    all_blocks = {
        "user-1": [{"day_of_week": 5, "start_time": "20:00", "end_time": "23:00"}]
    }
    results = _compute_weekday_free_slots(all_blocks)
    friday = [s for s in results if s["day_of_week"] == 5]
    assert len(friday) == 1
    assert friday[0]["start_time"] == "8:00 AM"
    assert friday[0]["end_time"] == "8:00 PM"


# ---------------------------------------------------------------------------
# _compute_weekday_free_slots — short gap filtering (< 1 hour)
# ---------------------------------------------------------------------------

def test_compute_short_gap_filtered_out():
    # Busy 08:00–10:00 and 10:30–23:00 → 30 min gap (< 1 h), filtered
    all_blocks = {
        "user-1": [
            {"day_of_week": 1, "start_time": "08:00", "end_time": "10:00"},
            {"day_of_week": 1, "start_time": "10:30", "end_time": "23:00"},
        ]
    }
    results = _compute_weekday_free_slots(all_blocks)
    monday = [s for s in results if s["day_of_week"] == 1]
    assert len(monday) == 0


def test_compute_exactly_one_hour_gap_kept():
    # Busy 08:00–10:00 and 11:00–23:00 → exactly 1 h gap, kept
    all_blocks = {
        "user-1": [
            {"day_of_week": 1, "start_time": "08:00", "end_time": "10:00"},
            {"day_of_week": 1, "start_time": "11:00", "end_time": "23:00"},
        ]
    }
    results = _compute_weekday_free_slots(all_blocks)
    monday = [s for s in results if s["day_of_week"] == 1]
    assert len(monday) == 1
    assert monday[0]["start_time"] == "10:00 AM"
    assert monday[0]["end_time"] == "11:00 AM"


# ---------------------------------------------------------------------------
# _compute_weekday_free_slots — multiple users
# ---------------------------------------------------------------------------

def test_compute_multiple_users_non_overlapping_busy():
    # User A: busy 8–12 on Wednesday; User B: busy 15–23 on Wednesday
    # Combined gap: 12:00–15:00 (3 h) should appear
    all_blocks = {
        "user-A": [{"day_of_week": 3, "start_time": "08:00", "end_time": "12:00"}],
        "user-B": [{"day_of_week": 3, "start_time": "15:00", "end_time": "23:00"}],
    }
    results = _compute_weekday_free_slots(all_blocks)
    wednesday = [s for s in results if s["day_of_week"] == 3]
    assert len(wednesday) >= 1
    assert any(s["start_time"] == "12:00 PM" for s in wednesday)


def test_compute_multiple_users_fully_covered_no_slot():
    # User A: busy 8–16; User B: busy 14–23 → 8–23 fully covered (overlap at 14–16)
    all_blocks = {
        "user-A": [{"day_of_week": 1, "start_time": "08:00", "end_time": "16:00"}],
        "user-B": [{"day_of_week": 1, "start_time": "14:00", "end_time": "23:00"}],
    }
    results = _compute_weekday_free_slots(all_blocks)
    monday = [s for s in results if s["day_of_week"] == 1]
    assert len(monday) == 0


def test_compute_second_user_all_free_doesnt_restrict():
    # User A: busy 12–14 on Thursday; User B: no blocks on Thursday
    # Both users together → free 8–12 and 14–23
    all_blocks = {
        "user-A": [{"day_of_week": 4, "start_time": "12:00", "end_time": "14:00"}],
        "user-B": [],
    }
    results = _compute_weekday_free_slots(all_blocks)
    thursday = [s for s in results if s["day_of_week"] == 4]
    assert len(thursday) == 2


# ---------------------------------------------------------------------------
# _compute_weekday_free_slots — day name correctness
# ---------------------------------------------------------------------------

def test_compute_sunday_is_day_zero():
    all_blocks = {"user-1": []}
    results = _compute_weekday_free_slots(all_blocks)
    sunday = next(s for s in results if s["day_of_week"] == 0)
    assert sunday["day_name"] == "Sunday"


def test_compute_saturday_is_day_six():
    all_blocks = {"user-1": []}
    results = _compute_weekday_free_slots(all_blocks)
    saturday = next(s for s in results if s["day_of_week"] == 6)
    assert saturday["day_name"] == "Saturday"

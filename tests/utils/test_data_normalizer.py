"""Unit tests for utils/data_normalizer.py — DataNormalizer and DataValidator."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.schemas import FreeBusyInterval, VenueLocation, VenueMetadata
from utils.data_normalizer import DataNormalizer, DataValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_calendar(busy_periods):
    return {"busy": busy_periods}


def _make_venue_meta(name, lat, lng, venue_id="v1"):
    loc = VenueLocation(latitude=lat, longitude=lng, address="", city="", state="", zip_code="")
    return VenueMetadata(
        venue_id=venue_id,
        name=name,
        category="Restaurant",
        rating=4.0,
        review_count=100,
        location=loc,
        source="google_places",
        source_url="",
        retrieved_at=datetime.now(timezone.utc),
    )


def _make_place(**overrides):
    base = {
        "place_id": "ChIJtest123",
        "name": "Test Venue",
        "types": ["restaurant", "food"],
        "rating": 4.2,
        "user_ratings_total": 320,
        "price_level": 2,
        "formatted_address": "123 Main St",
        "location": {"latitude": 42.3601, "longitude": -71.0589},
        "photos": [
            {"photo_reference": "abc"},
            {"photo_reference": "def"},
            {"photo_reference": "ghi"},
            {"photo_reference": "jkl"},  # 4th photo — should be dropped
        ],
        "url": "https://maps.google.com/place/test",
    }
    base.update(overrides)
    return base


def _make_interval(start_iso, end_iso):
    return FreeBusyInterval(
        start=datetime.fromisoformat(start_iso),
        end=datetime.fromisoformat(end_iso),
        busy=True,
    )


# ---------------------------------------------------------------------------
# DataNormalizer.normalize_calendar_data
# ---------------------------------------------------------------------------

def test_normalize_calendar_data_empty_busy_list():
    result = DataNormalizer.normalize_calendar_data("user-1", _raw_calendar([]))
    assert result.user_id == "user-1"
    assert result.intervals == []


def test_normalize_calendar_data_single_period():
    raw = _raw_calendar([
        {"start": "2024-06-01T09:00:00Z", "end": "2024-06-01T10:30:00Z"}
    ])
    result = DataNormalizer.normalize_calendar_data("user-1", raw)
    assert len(result.intervals) == 1
    interval = result.intervals[0]
    assert interval.busy is True
    assert interval.start.hour == 9
    assert interval.end.hour == 10


def test_normalize_calendar_data_multiple_periods():
    raw = _raw_calendar([
        {"start": "2024-06-01T09:00:00Z", "end": "2024-06-01T10:00:00Z"},
        {"start": "2024-06-01T14:00:00Z", "end": "2024-06-01T15:30:00Z"},
    ])
    result = DataNormalizer.normalize_calendar_data("user-2", raw, calendar_id="primary")
    assert len(result.intervals) == 2
    assert result.calendar_id == "primary"


def test_normalize_calendar_data_attaches_user_id():
    result = DataNormalizer.normalize_calendar_data("abc-123", _raw_calendar([]))
    assert result.user_id == "abc-123"


def test_normalize_calendar_data_propagates_exception():
    with pytest.raises(Exception):
        DataNormalizer.normalize_calendar_data("user", {"busy": [{"start": "bad-date"}]})


# ---------------------------------------------------------------------------
# DataNormalizer.normalize_google_place
# ---------------------------------------------------------------------------

def test_normalize_google_place_basic_fields():
    venue = DataNormalizer.normalize_google_place(_make_place())
    assert venue.venue_id == "ChIJtest123"
    assert venue.name == "Test Venue"
    assert venue.category == "Restaurant"  # types[0] title-cased
    assert venue.rating == 4.2
    assert venue.review_count == 320
    assert venue.price_level == 2
    assert venue.source == "google_places"


def test_normalize_google_place_photos_capped_at_three():
    venue = DataNormalizer.normalize_google_place(_make_place())
    assert len(venue.photos) == 3


def test_normalize_google_place_no_types_gives_other_category():
    venue = DataNormalizer.normalize_google_place(_make_place(types=[]))
    assert venue.category == "Other"


def test_normalize_google_place_underscore_in_type_replaced():
    venue = DataNormalizer.normalize_google_place(_make_place(types=["coffee_shop"]))
    assert venue.category == "Coffee Shop"


def test_normalize_google_place_fallback_name_when_none():
    venue = DataNormalizer.normalize_google_place(_make_place(name=None))
    assert venue.name == "Unknown venue"


def test_normalize_google_place_fallback_venue_id_to_id_field():
    place = _make_place()
    del place["place_id"]
    place["id"] = "alt-id-456"
    venue = DataNormalizer.normalize_google_place(place)
    assert venue.venue_id == "alt-id-456"


def test_normalize_google_place_no_location_data_defaults_to_zero():
    venue = DataNormalizer.normalize_google_place(_make_place(location={}))
    assert venue.location.latitude == 0
    assert venue.location.longitude == 0


def test_normalize_google_place_address_from_formatted_address():
    venue = DataNormalizer.normalize_google_place(_make_place())
    assert venue.location.address == "123 Main St"


# ---------------------------------------------------------------------------
# DataNormalizer.normalize_route
# ---------------------------------------------------------------------------

def test_normalize_route_new_format_meters_and_seconds():
    route_data = {"legs": [{"distanceMeters": 8046.72, "duration": "300s"}]}
    route = DataNormalizer.normalize_route("user-1", "venue-A", route_data)
    assert abs(route.distance_miles - 5.0) < 0.1
    assert route.duration_minutes == 5


def test_normalize_route_legacy_text_format():
    route_data = {
        "legs": [{
            "distance": {"text": "3.1 mi"},
            "duration": {"text": "12 mins"},
        }]
    }
    route = DataNormalizer.normalize_route("user-1", "venue-B", route_data)
    assert abs(route.distance_miles - 3.1) < 0.01
    assert route.duration_minutes == 12


def test_normalize_route_flat_dict_no_legs():
    route_data = {"distanceMeters": 1609.34, "duration": "60s"}
    route = DataNormalizer.normalize_route("user-1", "venue-C", route_data)
    assert abs(route.distance_miles - 1.0) < 0.01
    assert route.duration_minutes == 1


def test_normalize_route_sets_origin_and_destination():
    route_data = {"legs": [{"distanceMeters": 0.0, "duration": "0s"}]}
    route = DataNormalizer.normalize_route("u-abc", "v-xyz", route_data)
    assert route.origin_user_id == "u-abc"
    assert route.destination_venue_id == "v-xyz"


# ---------------------------------------------------------------------------
# DataNormalizer.validate_schema
# ---------------------------------------------------------------------------

def test_validate_schema_valid_group_create():
    from models.schemas import GroupCreate
    assert DataNormalizer.validate_schema({"name": "MyGroup"}, GroupCreate) is True


def test_validate_schema_missing_required_field():
    from models.schemas import GroupCreate
    assert DataNormalizer.validate_schema({}, GroupCreate) is False


def test_validate_schema_int_for_str_field_returns_false():
    from models.schemas import FeedbackCreate
    # Pydantic v2 does not coerce int → str in strict-enough contexts
    assert DataNormalizer.validate_schema({"rating": 99, "attended": True}, FeedbackCreate) is False


# ---------------------------------------------------------------------------
# DataNormalizer.deduplicate_venues
# ---------------------------------------------------------------------------

def test_deduplicate_venues_empty_list():
    assert DataNormalizer.deduplicate_venues([]) == []


def test_deduplicate_venues_all_unique():
    venues = [
        _make_venue_meta("Venue A", 42.0, -71.0, "v1"),
        _make_venue_meta("Venue B", 42.1, -71.1, "v2"),
    ]
    result = DataNormalizer.deduplicate_venues(venues)
    assert len(result) == 2


def test_deduplicate_venues_removes_exact_duplicate():
    v1 = _make_venue_meta("Same Venue", 42.3601, -71.0589, "v1")
    v2 = _make_venue_meta("Same Venue", 42.3601, -71.0589, "v2")
    result = DataNormalizer.deduplicate_venues([v1, v2])
    assert len(result) == 1
    assert result[0].venue_id == "v1"  # first one kept


def test_deduplicate_venues_same_coords_different_name_kept():
    v1 = _make_venue_meta("Venue A", 42.3601, -71.0589, "v1")
    v2 = _make_venue_meta("Venue B", 42.3601, -71.0589, "v2")
    result = DataNormalizer.deduplicate_venues([v1, v2])
    assert len(result) == 2


def test_deduplicate_venues_rounds_coords_to_4_decimal_places():
    v1 = _make_venue_meta("Near Venue", 42.36010, -71.05890, "v1")
    v2 = _make_venue_meta("Near Venue", 42.360100001, -71.058900001, "v2")
    result = DataNormalizer.deduplicate_venues([v1, v2])
    assert len(result) == 1


# ---------------------------------------------------------------------------
# DataNormalizer.compress_event_options
# ---------------------------------------------------------------------------

def test_compress_event_options_empty_list_returns_header():
    result = DataNormalizer.compress_event_options([])
    assert "Event Options Summary" in result


def test_compress_event_options_includes_option_title():
    options = [{
        "title": "Pizza Night",
        "vibe_category": "Casual",
        "venue": {"name": "Pizza Place"},
        "estimated_cost_per_person": 15,
        "estimated_duration_minutes": 90,
    }]
    result = DataNormalizer.compress_event_options(options)
    assert "Pizza Night" in result
    assert "Casual" in result
    assert "Pizza Place" in result
    assert "$15" in result


def test_compress_event_options_truncates_at_max_tokens():
    options = [{"title": "X" * 2000, "vibe_category": "", "venue": {"name": ""}, "estimated_cost_per_person": 0, "estimated_duration_minutes": 0}]
    result = DataNormalizer.compress_event_options(options, max_tokens=10)
    assert len(result) <= 40  # 10 tokens * 4 chars


def test_compress_event_options_numbers_items():
    options = [
        {"title": "Plan A", "vibe_category": "Fun", "venue": {"name": "V1"}, "estimated_cost_per_person": 10, "estimated_duration_minutes": 60},
        {"title": "Plan B", "vibe_category": "Chill", "venue": {"name": "V2"}, "estimated_cost_per_person": 20, "estimated_duration_minutes": 120},
    ]
    result = DataNormalizer.compress_event_options(options)
    assert "1." in result
    assert "2." in result


# ---------------------------------------------------------------------------
# DataValidator.validate_calendar_intervals
# ---------------------------------------------------------------------------

def test_validate_calendar_intervals_empty_list():
    assert DataValidator.validate_calendar_intervals([]) is True


def test_validate_calendar_intervals_single_valid():
    intervals = [_make_interval("2024-06-01T09:00:00+00:00", "2024-06-01T10:00:00+00:00")]
    assert DataValidator.validate_calendar_intervals(intervals) is True


def test_validate_calendar_intervals_two_non_overlapping():
    intervals = [
        _make_interval("2024-06-01T09:00:00+00:00", "2024-06-01T10:00:00+00:00"),
        _make_interval("2024-06-01T11:00:00+00:00", "2024-06-01T12:00:00+00:00"),
    ]
    assert DataValidator.validate_calendar_intervals(intervals) is True


def test_validate_calendar_intervals_end_before_start():
    intervals = [
        _make_interval("2024-06-01T10:00:00+00:00", "2024-06-01T09:00:00+00:00"),
    ]
    assert DataValidator.validate_calendar_intervals(intervals) is False


def test_validate_calendar_intervals_end_equals_start():
    intervals = [
        _make_interval("2024-06-01T10:00:00+00:00", "2024-06-01T10:00:00+00:00"),
    ]
    assert DataValidator.validate_calendar_intervals(intervals) is False


def test_validate_calendar_intervals_overlapping():
    intervals = [
        _make_interval("2024-06-01T09:00:00+00:00", "2024-06-01T11:00:00+00:00"),
        _make_interval("2024-06-01T10:00:00+00:00", "2024-06-01T12:00:00+00:00"),
    ]
    assert DataValidator.validate_calendar_intervals(intervals) is False


# ---------------------------------------------------------------------------
# DataValidator.validate_venue_metadata
# ---------------------------------------------------------------------------

def test_validate_venue_metadata_valid():
    assert DataValidator.validate_venue_metadata(_make_venue_meta("Good Venue", 42.0, -71.0)) is True


def test_validate_venue_metadata_blank_name():
    v = _make_venue_meta("   ", 42.0, -71.0)
    assert DataValidator.validate_venue_metadata(v) is False


def test_validate_venue_metadata_rating_too_high():
    v = _make_venue_meta("Venue", 42.0, -71.0)
    v.rating = 5.1
    assert DataValidator.validate_venue_metadata(v) is False


def test_validate_venue_metadata_rating_negative():
    v = _make_venue_meta("Venue", 42.0, -71.0)
    v.rating = -0.1
    assert DataValidator.validate_venue_metadata(v) is False


def test_validate_venue_metadata_rating_boundary_zero():
    v = _make_venue_meta("Venue", 42.0, -71.0)
    v.rating = 0.0
    assert DataValidator.validate_venue_metadata(v) is True


def test_validate_venue_metadata_rating_boundary_five():
    v = _make_venue_meta("Venue", 42.0, -71.0)
    v.rating = 5.0
    assert DataValidator.validate_venue_metadata(v) is True


def test_validate_venue_metadata_latitude_too_high():
    v = _make_venue_meta("Venue", 91.0, -71.0)
    assert DataValidator.validate_venue_metadata(v) is False


def test_validate_venue_metadata_latitude_too_low():
    v = _make_venue_meta("Venue", -91.0, -71.0)
    assert DataValidator.validate_venue_metadata(v) is False


def test_validate_venue_metadata_longitude_too_high():
    v = _make_venue_meta("Venue", 42.0, 181.0)
    assert DataValidator.validate_venue_metadata(v) is False


def test_validate_venue_metadata_longitude_too_low():
    v = _make_venue_meta("Venue", 42.0, -181.0)
    assert DataValidator.validate_venue_metadata(v) is False


def test_validate_venue_metadata_extreme_valid_coords():
    v = _make_venue_meta("North Pole", 90.0, 180.0)
    assert DataValidator.validate_venue_metadata(v) is True

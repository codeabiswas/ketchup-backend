"""
Data normalization and preprocessing utilities for ETL pipeline.
Converts raw API responses into canonical Ketchup schemas.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from models.schemas import (
    CalendarData,
    EventOption,
    FreeBusyInterval,
    TravelRoute,
    VenueLocation,
    VenueMetadata,
)

logger = logging.getLogger(__name__)


class DataNormalizer:
    """Normalizes raw API data into canonical schemas."""

    @staticmethod
    def normalize_calendar_data(
        user_id: str,
        raw_calendar_response: Dict[str, Any],
        calendar_id: Optional[str] = None,
    ) -> CalendarData:
        """
        Normalize Google Calendar free/busy data.

        Args:
            user_id: User ID
            raw_calendar_response: Raw response from Google Calendar API
            calendar_id: Optional calendar ID

        Returns:
            Normalized CalendarData schema
        """
        try:
            intervals = []
            busy_times = raw_calendar_response.get("busy", [])

            for busy_period in busy_times:
                start = datetime.fromisoformat(
                    busy_period["start"].replace("Z", "+00:00"),
                )
                end = datetime.fromisoformat(busy_period["end"].replace("Z", "+00:00"))

                interval = FreeBusyInterval(
                    start=start,
                    end=end,
                    busy=True,
                )
                intervals.append(interval)

            calendar_data = CalendarData(
                user_id=user_id,
                intervals=intervals,
                retrieved_at=datetime.utcnow(),
                calendar_id=calendar_id,
            )

            logger.info(
                f"Normalized calendar data for {user_id}: {len(intervals)} busy intervals",
            )
            return calendar_data

        except Exception as e:
            logger.error(f"Error normalizing calendar data: {e}")
            raise

    @staticmethod
    def normalize_google_place(
        place_data: Dict[str, Any],
    ) -> VenueMetadata:
        """
        Normalize Google Places data to VenueMetadata.

        Args:
            place_data: Raw Google Places API object

        Returns:
            Normalized VenueMetadata schema
        """
        try:
            location_data = place_data.get("location", {})

            location = VenueLocation(
                latitude=location_data.get("latitude", 0),
                longitude=location_data.get("longitude", 0),
                address=place_data.get("formatted_address", ""),
                city="",  # Parse from address if needed
                state="",
                zip_code="",
            )

            photos = [
                f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photo_reference={ph['photo_reference']}"
                for ph in place_data.get("photos", [])
            ]

            # Extract category from types
            category = "Other"
            types = place_data.get("types", [])
            if types:
                category = types[0].replace("_", " ").title()

            venue = VenueMetadata(
                venue_id=place_data.get("place_id"),
                name=place_data.get("name"),
                category=category,
                rating=place_data.get("rating", 0),
                review_count=place_data.get("user_ratings_total", 0),
                price_level=place_data.get("price_level"),
                location=location,
                photos=photos[:3],
                source="google_places",
                source_url=place_data.get("url", ""),
                retrieved_at=datetime.utcnow(),
            )

            logger.info(f"Normalized Google Place: {venue.name}")
            return venue

        except Exception as e:
            logger.error(f"Error normalizing Google Place: {e}")
            raise

    @staticmethod
    def normalize_route(
        origin_user_id: str,
        destination_venue_id: str,
        route_data: Dict[str, Any],
    ) -> TravelRoute:
        """
        Normalize Google Maps route data.

        Args:
            origin_user_id: Starting user ID
            destination_venue_id: Destination venue ID
            route_data: Raw route response from Google Maps API

        Returns:
            Normalized TravelRoute schema
        """
        try:
            # Extract distance and duration from first leg
            legs = route_data.get("legs", [{}])
            leg = legs[0] if legs else {}

            distance_text = leg.get("distance", {}).get("text", "0 mi")
            duration_text = leg.get("duration", {}).get("text", "0 mins")

            # Parse distance (e.g., "5.2 mi" -> 5.2)
            distance_miles = float(distance_text.split()[0])

            # Parse duration (e.g., "45 mins" -> 45)
            duration_minutes = int(duration_text.split()[0])

            route = TravelRoute(
                origin_user_id=origin_user_id,
                destination_venue_id=destination_venue_id,
                distance_miles=distance_miles,
                duration_minutes=duration_minutes,
                retrieved_at=datetime.utcnow(),
            )

            logger.info(
                f"Normalized route: {distance_miles}mi, {duration_minutes}min",
            )
            return route

        except Exception as e:
            logger.error(f"Error normalizing route: {e}")
            raise

    @staticmethod
    def validate_schema(data: Dict[str, Any], schema_class: type) -> bool:
        """
        Validate data against a Pydantic schema.

        Args:
            data: Data to validate
            schema_class: Pydantic schema class

        Returns:
            True if valid, False otherwise
        """
        try:
            schema_class(**data)
            return True
        except Exception as e:
            logger.warning(f"Schema validation failed: {e}")
            return False

    @staticmethod
    def deduplicate_venues(venues: List[VenueMetadata]) -> List[VenueMetadata]:
        """
        Remove duplicate venues based on name and location.

        Args:
            venues: List of venues

        Returns:
            Deduplicated list
        """
        seen = {}
        unique = []

        for venue in venues:
            key = (
                venue.name,
                round(venue.location.latitude, 4),
                round(venue.location.longitude, 4),
            )
            if key not in seen:
                seen[key] = True
                unique.append(venue)

        logger.info(f"Deduplicated {len(venues)} venues to {len(unique)}")
        return unique

    @staticmethod
    def compress_event_options(
        options: List[Dict[str, Any]],
        max_tokens: int = 2000,
    ) -> str:
        """
        Compress event options into a summary for token efficiency.

        Args:
            options: List of event option dictionaries
            max_tokens: Target token count

        Returns:
            Compressed summary string
        """
        summary = "Event Options Summary:\n"

        for idx, option in enumerate(options, 1):
            summary += f"\n{idx}. {option.get('title', 'Unknown')}\n"
            summary += f"   Vibe: {option.get('vibe_category', 'N/A')}\n"
            summary += f"   Location: {option.get('venue', {}).get('name', 'N/A')}\n"
            summary += f"   Cost: ${option.get('estimated_cost_per_person', 0)}\n"
            summary += (
                f"   Duration: {option.get('estimated_duration_minutes', 0)} min\n"
            )

        logger.info(f"Compressed {len(options)} options to ~{len(summary)} chars")
        return summary


class DataValidator:
    """Validates data quality and contracts."""

    @staticmethod
    def validate_calendar_intervals(intervals: List[FreeBusyInterval]) -> bool:
        """Validate calendar intervals for consistency."""
        try:
            for i, interval in enumerate(intervals):
                if interval.end <= interval.start:
                    logger.warning(f"Invalid interval {i}: end before start")
                    return False

                # Check for duplicate/overlapping intervals
                for j in range(i + 1, len(intervals)):
                    other = intervals[j]
                    if interval.start < other.end and interval.end > other.start:
                        logger.warning(f"Overlapping intervals: {i} and {j}")
                        return False

            return True
        except Exception as e:
            logger.error(f"Calendar validation error: {e}")
            return False

    @staticmethod
    def validate_venue_metadata(venue: VenueMetadata) -> bool:
        """Validate venue metadata quality."""
        try:
            # Check required fields
            if not venue.name or len(venue.name.strip()) == 0:
                logger.warning("Venue missing name")
                return False

            if venue.rating < 0 or venue.rating > 5:
                logger.warning(f"Invalid rating: {venue.rating}")
                return False

            if venue.location.latitude < -90 or venue.location.latitude > 90:
                logger.warning(f"Invalid latitude: {venue.location.latitude}")
                return False

            if venue.location.longitude < -180 or venue.location.longitude > 180:
                logger.warning(f"Invalid longitude: {venue.location.longitude}")
                return False

            return True
        except Exception as e:
            logger.error(f"Venue validation error: {e}")
            return False

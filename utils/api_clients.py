"""
External API clients with built-in error handling, retries, and caching.
Integrates with Google Calendar and Google Maps APIs.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import redis
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import settings

logger = logging.getLogger(__name__)


class CachedAPIClient:
    """Base class with caching and retry logic."""

    def __init__(self, cache_ttl: int = settings.cache_ttl_seconds):
        """
        Initialize cached API client.

        Args:
            cache_ttl: Cache time-to-live in seconds
        """
        self.cache_ttl = cache_ttl
        self.timeout = settings.api_timeout_seconds
        self.max_retries = settings.api_max_retries

        # Initialize Redis cache
        try:
            self.cache = redis.from_url(settings.redis_url, decode_responses=True)
            self.cache.ping()
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}. Operating without cache.")
            self.cache = None

        # Session with retries
        self.session = self._create_session_with_retries()

    def _create_session_with_retries(self) -> requests.Session:
        """Create requests session with exponential backoff retries."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=settings.api_retry_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve value from cache."""
        if not self.cache:
            return None
        try:
            cached = self.cache.get(key)
            if cached:
                logger.debug(f"Cache hit: {key}")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache retrieval error: {e}")
        return None

    def _set_to_cache(self, key: str, value: Dict[str, Any]) -> None:
        """Store value in cache."""
        if not self.cache:
            return
        try:
            self.cache.setex(key, self.cache_ttl, json.dumps(value))
        except Exception as e:
            logger.warning(f"Cache storage error: {e}")


class GoogleCalendarClient(CachedAPIClient):
    """Google Calendar API client."""

    def __init__(self):
        super().__init__()
        self.base_url = "https://www.googleapis.com/calendar/v3"
        self._auth_token: Optional[str] = None

    def set_auth_token(self, token: str) -> None:
        """Set OAuth token for user requests."""
        self._auth_token = token

    def get_freebusy(
        self,
        user_email: str,
        time_min: datetime,
        time_max: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Fetch user's free/busy intervals.

        Args:
            user_email: User's email address
            time_min: Start of time range
            time_max: End of time range

        Returns:
            List of busy intervals
        """
        cache_key = f"calendar:freebusy:{user_email}:{time_min}:{time_max}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            headers = {"Authorization": f"Bearer {self._auth_token}"}
            body = {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "items": [{"id": user_email}],
            }

            response = self.session.post(
                f"{self.base_url}/calendars/primary/events/import",
                headers=headers,
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            busy_intervals = (
                data.get("calendars", {}).get(user_email, {}).get("busy", [])
            )

            self._set_to_cache(cache_key, busy_intervals)
            logger.info(
                f"Retrieved {len(busy_intervals)} busy intervals for {user_email}",
            )
            return busy_intervals

        except requests.RequestException as e:
            logger.error(f"Error fetching calendar data: {e}")
            raise

    def create_event(
        self,
        user_email: str,
        event_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a calendar event for the user."""
        try:
            headers = {"Authorization": f"Bearer {self._auth_token}"}
            response = self.session.post(
                f"{self.base_url}/calendars/{user_email}/events",
                headers=headers,
                json=event_data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            logger.info(f"Calendar event created for {user_email}")
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Error creating calendar event: {e}")
            raise


class GoogleMapsClient(CachedAPIClient):
    """Google Maps API client for routes."""

    def __init__(self):
        super().__init__()
        self.api_key = settings.google_maps_api_key
        self.routes_url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def get_route(
        self,
        origin: tuple,
        destination: tuple,
    ) -> Dict[str, Any]:
        """
        Calculate route between two points.

        Args:
            origin: (latitude, longitude)
            destination: (latitude, longitude)

        Returns:
            Route summary with distance and duration
        """
        cache_key = f"maps:route:{origin}:{destination}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            body = {
                "origin": {
                    "location": {
                        "latLng": {"latitude": origin[0], "longitude": origin[1]},
                    },
                },
                "destination": {
                    "location": {
                        "latLng": {
                            "latitude": destination[0],
                            "longitude": destination[1],
                        },
                    },
                },
                "travelMode": "DRIVE",
                "computeAlternativeRoutes": False,
            }
            headers = {"X-Goog-Api-Key": self.api_key}

            response = self.session.post(
                self.routes_url,
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()

            route_data = response.json().get("routes", [{}])[0]
            self._set_to_cache(cache_key, route_data)
            logger.info(f"Route calculated: {origin} -> {destination}")
            return route_data

        except requests.RequestException as e:
            logger.error(f"Error calculating route: {e}")
            raise


# Singleton instances
_calendar_client: Optional[GoogleCalendarClient] = None
_maps_client: Optional[GoogleMapsClient] = None


def get_calendar_client() -> GoogleCalendarClient:
    """Get or create Google Calendar client."""
    global _calendar_client
    if _calendar_client is None:
        _calendar_client = GoogleCalendarClient()
    return _calendar_client


def get_maps_client() -> GoogleMapsClient:
    """Get or create Google Maps client."""
    global _maps_client
    if _maps_client is None:
        _maps_client = GoogleMapsClient()
    return _maps_client

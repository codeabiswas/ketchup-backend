"""External API clients used by optional ETL/DAG paths."""

import json
import logging
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import get_settings

try:
    import redis
except Exception:  # pragma: no cover - optional dependency
    redis = None

logger = logging.getLogger(__name__)


class CachedAPIClient:
    """Base API client with retries and optional Redis cache."""

    def __init__(self):
        settings = get_settings()
        self.cache_ttl = settings.cache_ttl_seconds
        self.timeout = settings.api_timeout_seconds
        self.max_retries = settings.api_max_retries
        self.cache = self._init_cache(settings.redis_url)
        self.session = self._create_session_with_retries(settings.api_retry_backoff_factor)

    def _init_cache(self, redis_url: str):
        if redis is None:
            logger.info("Redis package not installed; API cache disabled.")
            return None
        try:
            cache = redis.from_url(redis_url, decode_responses=True)
            cache.ping()
            return cache
        except Exception as exc:
            logger.warning("Redis unavailable; API cache disabled: %s", exc)
            return None

    def _create_session_with_retries(self, backoff_factor: float) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_from_cache(self, key: str) -> Any | None:
        if not self.cache:
            return None
        try:
            value = self.cache.get(key)
            return json.loads(value) if value else None
        except Exception as exc:
            logger.warning("Cache read error for key %s: %s", key, exc)
            return None

    def _set_to_cache(self, key: str, value: Any) -> None:
        if not self.cache:
            return
        try:
            self.cache.setex(key, self.cache_ttl, json.dumps(value))
        except Exception as exc:
            logger.warning("Cache write error for key %s: %s", key, exc)


class GoogleCalendarClient(CachedAPIClient):
    """Google Calendar API client."""

    def __init__(self):
        super().__init__()
        self.base_url = "https://www.googleapis.com/calendar/v3"
        self._auth_token: str | None = None

    def set_auth_token(self, token: str) -> None:
        self._auth_token = token

    def get_freebusy(
        self,
        user_email: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch busy intervals for a user in a time range."""
        if not self._auth_token:
            raise RuntimeError("GoogleCalendarClient auth token is not set.")

        cache_key = f"calendar:freebusy:{user_email}:{time_min.isoformat()}:{time_max.isoformat()}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        headers = {"Authorization": f"Bearer {self._auth_token}"}
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": user_email}],
        }
        response = self.session.post(
            f"{self.base_url}/freeBusy",
            headers=headers,
            json=body,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        busy_intervals = payload.get("calendars", {}).get(user_email, {}).get("busy", [])
        self._set_to_cache(cache_key, busy_intervals)
        return busy_intervals


class GoogleMapsClient(CachedAPIClient):
    """Google Maps Places+Routes API client."""

    def __init__(self):
        super().__init__()
        settings = get_settings()
        self.api_key = settings.google_maps_api_key
        self.routes_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        self.places_url = "https://places.googleapis.com/v1/places:searchText"

    def _api_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is not set.")
        return {"X-Goog-Api-Key": self.api_key}

    def search_places(
        self,
        query: str,
        location: str | None = None,
        max_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search places using Places API Text Search."""
        cache_key = f"maps:places:{query}:{location}:{max_results}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        text_query = f"{query} in {location}" if location else query
        headers = self._api_headers()
        headers["X-Goog-FieldMask"] = (
            "places.id,places.displayName,places.formattedAddress,"
            "places.rating,places.priceLevel,places.location"
        )

        response = self.session.post(
            self.places_url,
            json={"textQuery": text_query, "maxResultCount": max_results},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        places = response.json().get("places", [])
        results: list[dict[str, Any]] = []
        for place in places:
            display_name = place.get("displayName")
            results.append(
                {
                    "place_id": place.get("id"),
                    "name": (
                        display_name.get("text")
                        if isinstance(display_name, dict)
                        else place.get("name")
                    ),
                    "formatted_address": place.get("formattedAddress"),
                    "rating": place.get("rating"),
                    "price_level": place.get("priceLevel"),
                    "location": place.get("location", {}),
                }
            )

        self._set_to_cache(cache_key, results)
        return results

    def get_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> dict[str, Any]:
        """Compute route between two coordinates."""
        cache_key = f"maps:route:{origin}:{destination}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        body = {
            "origin": {
                "location": {
                    "latLng": {"latitude": origin[0], "longitude": origin[1]},
                },
            },
            "destination": {
                "location": {
                    "latLng": {"latitude": destination[0], "longitude": destination[1]},
                },
            },
            "travelMode": "DRIVE",
            "computeAlternativeRoutes": False,
        }
        headers = self._api_headers()
        headers["X-Goog-FieldMask"] = (
            "routes.distanceMeters,routes.duration,routes.legs.distanceMeters,routes.legs.duration"
        )

        response = self.session.post(
            self.routes_url,
            json=body,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        routes = response.json().get("routes", [])
        route = routes[0] if routes else {}
        self._set_to_cache(cache_key, route)
        return route


_calendar_client: GoogleCalendarClient | None = None
_maps_client: GoogleMapsClient | None = None


def get_calendar_client() -> GoogleCalendarClient:
    global _calendar_client
    if _calendar_client is None:
        _calendar_client = GoogleCalendarClient()
    return _calendar_client


def get_maps_client() -> GoogleMapsClient:
    global _maps_client
    if _maps_client is None:
        _maps_client = GoogleMapsClient()
    return _maps_client

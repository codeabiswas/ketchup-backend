# agents/planning.py

"""Canonical planning agent orchestration with vLLM tool-calling."""

import ast
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from openai import APIConnectionError, AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from config import get_settings
from database import db

logger = logging.getLogger(__name__)

# Shared AsyncOpenAI client for connection pooling.
_planner_client: AsyncOpenAI | None = None

# Tool schema exposed to the LLM.
PLANNER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_directions",
            "description": "Get travel distance and duration between an origin and destination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Starting address or place."},
                    "destination": {
                        "type": "string",
                        "description": "Destination address or place.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["driving", "transit", "walking"],
                        "description": "Travel mode.",
                    },
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_places",
            "description": "Search venues near a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Venue type query, e.g. 'bowling alley'.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Area to search near, e.g. 'Boston, MA'.",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 3,
                    },
                },
                "required": ["query", "location"],
            },
        },
    },
]

SYSTEM_PROMPT_TOOL_GROUNDED = (
    "You are Ketchup's planning engine. Build exactly 5 plans for a friend group. "
    "Use tools to ground recommendations in real places and travel times. "
    "Return strict JSON only with key 'plans'."
)

SYSTEM_PROMPT_BEST_EFFORT = (
    "You are Ketchup's planning engine. Build exactly 5 plans for a friend group. "
    "Tooling may be unavailable; do not mention missing tools, integrations, or API keys. "
    "Return strict JSON only with key 'plans'."
)

DEFAULT_VIBES = ["anchor", "pivot", "reach", "chill", "wildcard"]
MAX_TOOL_ROUNDS = 2
MAX_COMPLETION_TOKENS = 512
REPAIR_MAX_COMPLETION_TOKENS = 192
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.rating,places.priceLevel"
)
ROUTES_COMPUTE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ROUTES_FIELD_MASK = (
    "routes.distanceMeters,routes.duration,routes.legs.distanceMeters,routes.legs.duration"
)


class PlannerError(Exception):
    """Raised when plan generation cannot complete."""


async def init_planner_client() -> None:
    """Initialize and cache the AsyncOpenAI client for vLLM."""
    global _planner_client
    if _planner_client is not None:
        return

    settings = get_settings()
    timeout = httpx.Timeout(
        connect=settings.vllm_connect_timeout_seconds,
        read=settings.vllm_read_timeout_seconds,
        write=settings.vllm_write_timeout_seconds,
        pool=settings.vllm_pool_timeout_seconds,
    )

    http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.vllm_max_connections,
            max_keepalive_connections=settings.vllm_max_keepalive_connections,
        )
    )

    _planner_client = AsyncOpenAI(
        base_url=settings.vllm_base_url,
        api_key=settings.vllm_api_key,
        timeout=timeout,
        max_retries=0,
        http_client=http_client,
    )


async def close_planner_client() -> None:
    """Close shared AsyncOpenAI client."""
    global _planner_client
    if _planner_client is not None:
        await _planner_client.close()
        _planner_client = None


def _get_planner_client() -> AsyncOpenAI:
    if _planner_client is None:
        raise PlannerError("Planner client not initialized")
    return _planner_client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=10, jitter=2),
    retry=retry_if_exception_type(
        (
            APIConnectionError,
            httpx.ConnectTimeout,
            httpx.ConnectError,
            httpx.PoolTimeout,
        )
    ),
)
async def _call_vllm_chat(messages: list[dict[str, Any]], **kwargs):
    client = _get_planner_client()
    settings = get_settings()

    # llama.cpp's OpenAI shim can ignore max_tokens in some paths; n_predict enforces output cap.
    max_tokens = kwargs.get("max_tokens")
    raw_extra_body = kwargs.pop("extra_body", None)
    extra_body = raw_extra_body if isinstance(raw_extra_body, dict) else {}
    if isinstance(max_tokens, int) and max_tokens > 0 and "n_predict" not in extra_body:
        extra_body["n_predict"] = max_tokens
    if extra_body:
        kwargs["extra_body"] = extra_body

    return await client.chat.completions.create(
        model=settings.vllm_model,
        messages=messages,
        **kwargs,
    )


def _strip_code_fence(text: str) -> str:
    candidate = text.strip()
    # Qwen/llama.cpp can emit reasoning traces; remove them before JSON parsing.
    candidate = re.sub(r"<think>.*?</think>", "", candidate, flags=re.DOTALL | re.IGNORECASE).strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_\-]*", "", candidate).strip()
        if candidate.endswith("```"):
            candidate = candidate[:-3].strip()
    return candidate


def _extract_balanced_segment(text: str, start_idx: int) -> str | None:
    opener = text[start_idx]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start_idx : idx + 1]

    return None


def _extract_json_candidate(text: str) -> str | None:
    for idx, ch in enumerate(text):
        if ch not in "{[":
            continue
        candidate = _extract_balanced_segment(text, idx)
        if candidate:
            return candidate
    return None


def _sanitize_json_like(candidate: str) -> str:
    # Remove trailing commas that some models add before object/array close.
    return re.sub(r",\s*([}\]])", r"\1", candidate)


def _parse_json_like(text: str) -> Any:
    candidate = text.strip()
    if not candidate:
        raise PlannerError("LLM output was empty")

    # 1) Strict JSON first.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 2) Try JSON candidate substring.
    substring = _extract_json_candidate(candidate)
    if substring:
        cleaned = _sanitize_json_like(substring)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 3) Python-literal fallback (single quotes/None/True/False).
            try:
                return ast.literal_eval(cleaned)
            except (ValueError, SyntaxError) as exc:
                raise PlannerError("LLM output JSON parse failed") from exc

    # 4) Full-text Python-literal fallback.
    try:
        return ast.literal_eval(candidate)
    except (ValueError, SyntaxError) as exc:
        raise PlannerError("LLM output was not valid JSON") from exc


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_plan(raw: dict[str, Any], idx: int) -> dict[str, Any]:
    vibe = raw.get("vibe_type")
    if vibe not in DEFAULT_VIBES:
        vibe = DEFAULT_VIBES[min(idx, len(DEFAULT_VIBES) - 1)]

    logistics = raw.get("logistics")
    if not isinstance(logistics, dict):
        logistics = {}

    return {
        "title": str(raw.get("title") or f"Plan Option {idx + 1}"),
        "description": raw.get("description") or "",
        "vibe_type": vibe,
        "date_time": _parse_datetime(raw.get("date_time")),
        "location": raw.get("location") or "",
        "venue_name": raw.get("venue_name") or raw.get("title") or "",
        "estimated_cost": raw.get("estimated_cost") or "",
        "logistics": logistics,
    }


def _extract_plans(raw_text: str) -> list[dict[str, Any]]:
    text = _strip_code_fence(raw_text)

    parsed: Any = _parse_json_like(text)

    raw_plans: list[Any]
    if isinstance(parsed, dict):
        raw_plans = parsed.get("plans") or []
    elif isinstance(parsed, list):
        raw_plans = parsed
    else:
        raw_plans = []

    if not raw_plans:
        raise PlannerError("LLM returned no plans")

    plans: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_plans[:5]):
        if isinstance(item, dict):
            plans.append(_normalize_plan(item, idx))

    if not plans:
        raise PlannerError("LLM returned malformed plans")

    while len(plans) < 5:
        plans.append(
            _normalize_plan(
                {
                    "title": f"Plan Option {len(plans) + 1}",
                    "description": "Fallback option generated due to incomplete model response.",
                    "vibe_type": DEFAULT_VIBES[len(plans)],
                    "location": "",
                    "estimated_cost": "",
                    "logistics": {},
                },
                len(plans),
            )
        )

    return plans


def _format_member(member: dict[str, Any]) -> str:
    likes = member.get("activity_likes") or []
    dislikes = member.get("activity_dislikes") or []
    likes_s = ", ".join(likes) if likes else "none"
    dislikes_s = ", ".join(dislikes) if dislikes else "none"
    return (
        f"- {member.get('name') or member.get('email')}: "
        f"location={member.get('default_location') or 'unknown'}, "
        f"budget={member.get('budget_preference') or 'unspecified'}, "
        f"likes={likes_s}, dislikes={dislikes_s}"
    )


def _build_fallback_plans(
    context: dict[str, Any], reason: str, refinement_notes: str | None = None
) -> list[dict[str, Any]]:
    base_location = "Boston, MA"
    for member in context["members"]:
        location = member.get("default_location")
        if location:
            base_location = str(location)
            break

    member_names = [
        str(member.get("name") or member.get("email") or "member")
        for member in context["members"]
    ]
    group_name = context["group"]["name"]
    reason_short = reason[:180]
    refinement_short = (refinement_notes or "")[:240]

    templates = [
        ("Cozy Cafe Catch-up", "Relaxed hangout over coffee and conversation.", "$10-20 per person"),
        ("Food Hall Sampler", "Try multiple cuisines together in one spot.", "$20-35 per person"),
        ("Park Picnic Sunset", "Low-cost outdoor plan with time to talk.", "$5-15 per person"),
        ("Bowling + Snacks", "Casual activity with light competition.", "$25-40 per person"),
        ("Live Event Night", "Explore a slightly adventurous local event.", "$30-60 per person"),
    ]

    plans: list[dict[str, Any]] = []
    for idx, (title, description, cost) in enumerate(templates):
        plans.append(
            {
                "title": title,
                "description": f"{description} (Fallback plan for {group_name}.)",
                "vibe_type": DEFAULT_VIBES[idx],
                "date_time": datetime.utcnow() + timedelta(days=7 + idx),
                "location": base_location,
                "venue_name": title,
                "estimated_cost": cost,
                "logistics": {
                    "source": "fallback",
                    "reason": reason_short,
                    "refinement_notes": refinement_short,
                    "members": member_names,
                },
            }
        )
    return plans


def _cost_from_price_level(price_level: Any) -> str:
    if isinstance(price_level, str):
        enum_map = {
            "PRICE_LEVEL_FREE": 0,
            "PRICE_LEVEL_INEXPENSIVE": 1,
            "PRICE_LEVEL_MODERATE": 2,
            "PRICE_LEVEL_EXPENSIVE": 3,
            "PRICE_LEVEL_VERY_EXPENSIVE": 4,
        }
        mapped = enum_map.get(price_level.strip().upper())
        if mapped is not None:
            price_level = mapped
    try:
        level = int(price_level)
    except (TypeError, ValueError):
        return "$20-40 per person"

    if level <= 0:
        return "$0-10 per person"
    if level == 1:
        return "$10-20 per person"
    if level == 2:
        return "$20-40 per person"
    if level == 3:
        return "$40-80 per person"
    return "$80+ per person"


def _duration_to_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    token = value.strip()
    if token.endswith("s"):
        token = token[:-1]
    try:
        return float(token)
    except ValueError:
        return None


def _format_duration(seconds: float | None) -> str | None:
    if seconds is None or seconds <= 0:
        return None
    minutes = max(1, int(round(seconds / 60.0)))
    if minutes < 60:
        return f"{minutes} min"
    hours, rem = divmod(minutes, 60)
    if rem == 0:
        return f"{hours} hr"
    return f"{hours} hr {rem} min"


def _format_distance(meters: Any) -> str | None:
    try:
        meters_value = float(meters)
    except (TypeError, ValueError):
        return None
    if meters_value <= 0:
        return None

    miles = meters_value / 1609.344
    if miles < 0.2:
        feet = int(round(meters_value * 3.28084))
        return f"{max(1, feet)} ft"
    return f"{miles:.1f} mi"


def _extract_places_from_tool_messages(tool_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    places: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for message in tool_messages:
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        payload_places = payload.get("places")
        if not isinstance(payload_places, list):
            continue

        for place in payload_places:
            if not isinstance(place, dict):
                continue
            name = str(place.get("name") or "").strip()
            address = str(place.get("address") or "").strip()
            if not name and not address:
                continue

            key = (name.lower(), address.lower())
            if key in seen:
                continue
            seen.add(key)

            places.append(
                {
                    "name": name,
                    "address": address,
                    "rating": place.get("rating"),
                    "price_level": place.get("price_level"),
                }
            )
    return places


def _build_maps_grounded_fallback_plans(
    context: dict[str, Any],
    tool_messages: list[dict[str, Any]],
    reason: str,
    refinement_notes: str | None = None,
) -> list[dict[str, Any]] | None:
    places = _extract_places_from_tool_messages(tool_messages)
    if not places:
        return None

    base_location = "Boston, MA"
    for member in context["members"]:
        location = member.get("default_location")
        if location:
            base_location = str(location)
            break

    member_names = [
        str(member.get("name") or member.get("email") or "member")
        for member in context["members"]
    ]
    reason_short = reason[:180]
    refinement_short = (refinement_notes or "")[:240]

    plans: list[dict[str, Any]] = []
    for idx, place in enumerate(places[:5]):
        venue_name = place["name"] or f"Local Option {idx + 1}"
        location = place["address"] or base_location
        rating = place.get("rating")
        rating_text = f" Rated {rating}/5." if rating is not None else ""
        plans.append(
            {
                "title": venue_name,
                "description": f"Meet at {venue_name} in {location}.{rating_text}",
                "vibe_type": DEFAULT_VIBES[idx],
                "date_time": datetime.utcnow() + timedelta(days=7 + idx),
                "location": location,
                "venue_name": venue_name,
                "estimated_cost": _cost_from_price_level(place.get("price_level")),
                "logistics": {
                    "source": "maps_fallback",
                    "reason": reason_short,
                    "refinement_notes": refinement_short,
                    "members": member_names,
                    "venue": place,
                },
            }
        )

    if len(plans) < 5:
        generic = _build_fallback_plans(
            context=context,
            reason=reason,
            refinement_notes=refinement_notes,
        )
        for plan in generic:
            if len(plans) >= 5:
                break
            plans.append(plan)

    return plans[:5]


def _summarize_tool_results(tool_messages: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "tool_calls": 0,
        "place_calls": 0,
        "place_results": 0,
        "errors": [],
    }

    for message in tool_messages:
        if message.get("role") != "tool":
            continue
        summary["tool_calls"] += 1

        content = message.get("content")
        if not isinstance(content, str):
            continue

        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            summary["errors"].append("Tool payload was not valid JSON")
            continue

        if not isinstance(payload, dict):
            continue

        error = payload.get("error")
        if isinstance(error, str) and error:
            summary["errors"].append(error)

        places = payload.get("places")
        if isinstance(places, list):
            summary["place_calls"] += 1
            summary["place_results"] += len(places)

    return summary


async def _load_group_context(group_id: UUID) -> dict[str, Any]:
    group = await db.fetchrow(
        "SELECT id, name FROM groups WHERE id = $1",
        group_id,
    )
    if not group:
        raise PlannerError("Group not found")

    members = await db.fetch(
        """
        SELECT
            u.id,
            u.name,
            u.email,
            gp.default_location,
            gp.activity_likes,
            gp.activity_dislikes,
            gp.budget_preference,
            gp.notes
        FROM group_members gm
        JOIN users u ON u.id = gm.user_id
        LEFT JOIN group_preferences gp ON gp.group_id = gm.group_id AND gp.user_id = gm.user_id
        WHERE gm.group_id = $1 AND gm.status = 'active'
        ORDER BY u.name NULLS LAST, u.email
        """,
        group_id,
    )

    recent_events = await db.fetch(
        """
        SELECT p.title, e.event_date
        FROM events e
        JOIN plans p ON p.id = e.plan_id
        WHERE e.group_id = $1
        ORDER BY e.event_date DESC
        LIMIT 5
        """,
        group_id,
    )

    return {
        "group": dict(group),
        "members": [dict(m) for m in members],
        "recent_events": [dict(e) for e in recent_events],
    }


def _build_prompt(
    context: dict[str, Any],
    refinement_notes: str | None = None,
    require_tool_grounding: bool = True,
) -> str:
    member_lines = "\n".join(_format_member(m) for m in context["members"])

    if context["recent_events"]:
        history_lines = "\n".join(
            f"- {e['title']} at {e['event_date'].isoformat() if e.get('event_date') else 'unknown'}"
            for e in context["recent_events"]
        )
    else:
        history_lines = "- No recent events"

    refinement_block = ""
    if refinement_notes:
        refinement_block = f"\nVoting feedback to consider:\n{refinement_notes}\n"

    if require_tool_grounding:
        grounding_block = (
            "Use tool calls to ground plans:\n"
            "1) search_places(query, location) to find real venues.\n"
            "2) get_directions(origin, destination, mode) for each member with known location."
        )
        logistics_example = (
            '"per_member": [\n'
            '  {"member": "...", "origin": "...", "duration": "...", "distance": "...", "mode": "..."}\n'
            "]"
        )
    else:
        grounding_block = (
            "Google Maps tools are unavailable in this environment. "
            "Do not mention missing tools or API keys. "
            "Generate realistic best-effort plans from member preferences, budgets, and recent events."
        )
        logistics_example = '"per_member": []'

    return f"""
Group name: {context['group']['name']}

Members:
{member_lines}

Recent events:
{history_lines}
{refinement_block}
Generate exactly 5 plans with these vibe types in order: anchor, pivot, reach, chill, wildcard.
{grounding_block}

Return strict JSON with this schema:
{{
  "plans": [
    {{
      "title": "...",
      "description": "...",
      "vibe_type": "anchor|pivot|reach|chill|wildcard",
      "date_time": "ISO-8601 or null",
      "location": "...",
      "venue_name": "...",
      "estimated_cost": "...",
      "logistics": {{
        {logistics_example}
      }}
    }}
  ]
}}
""".strip()


async def _search_places(query: str, location: str, max_results: int = 3) -> dict[str, Any]:
    settings = get_settings()
    if not settings.google_maps_api_key:
        return {"error": "GOOGLE_MAPS_API_KEY not set"}

    safe_query = str(query or "").strip()
    safe_location = str(location or "").strip()
    if not safe_query:
        return {"error": "search_places query is required"}

    text_query = f"{safe_query} near {safe_location}" if safe_location else safe_query

    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                PLACES_TEXT_SEARCH_URL,
                headers=headers,
                json={"textQuery": text_query},
            )
    except httpx.HTTPError as exc:
        return {
            "error": f"search_places failed: {exc.__class__.__name__}",
            "details": str(exc),
        }

    try:
        data = response.json()
    except ValueError:
        return {
            "error": f"search_places failed: non-JSON response (HTTP {response.status_code})",
            "details": response.text[:500],
        }

    if response.status_code >= 400:
        err = data.get("error") if isinstance(data, dict) else None
        message = err.get("message") if isinstance(err, dict) else response.text[:300]
        return {
            "error": f"search_places failed: HTTP {response.status_code}",
            "details": message,
        }

    api_error = data.get("error") if isinstance(data, dict) else None
    if isinstance(api_error, dict):
        return {
            "error": "search_places failed: upstream API error",
            "details": api_error.get("message") or str(api_error),
        }

    places = []
    raw_places = data.get("places") if isinstance(data, dict) else None
    for item in (raw_places or [])[: max(1, min(max_results, 10))]:
        display_name = item.get("displayName") if isinstance(item, dict) else None
        name = (
            display_name.get("text")
            if isinstance(display_name, dict)
            else item.get("name")
            if isinstance(item, dict)
            else None
        )
        address = item.get("formattedAddress") if isinstance(item, dict) else None
        places.append(
            {
                "name": name,
                "address": address,
                "rating": item.get("rating") if isinstance(item, dict) else None,
                "price_level": item.get("priceLevel") if isinstance(item, dict) else None,
            }
        )
    return {"places": places}


async def _get_directions(
    origin: str, destination: str, mode: str = "driving"
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.google_maps_api_key:
        return {"error": "GOOGLE_MAPS_API_KEY not set"}

    safe_mode = mode if mode in {"driving", "transit", "walking"} else "driving"
    travel_mode = {
        "driving": "DRIVE",
        "walking": "WALK",
        "transit": "TRANSIT",
    }[safe_mode]

    body: dict[str, Any] = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel_mode,
    }
    if travel_mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"

    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": ROUTES_FIELD_MASK,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                ROUTES_COMPUTE_URL,
                headers=headers,
                json=body,
            )
    except httpx.HTTPError as exc:
        return {
            "error": f"get_directions failed: {exc.__class__.__name__}",
            "details": str(exc),
        }

    try:
        data = response.json()
    except ValueError:
        return {
            "error": f"get_directions failed: non-JSON response (HTTP {response.status_code})",
            "details": response.text[:500],
        }

    if response.status_code >= 400:
        err = data.get("error") if isinstance(data, dict) else None
        message = err.get("message") if isinstance(err, dict) else response.text[:300]
        return {
            "error": f"get_directions failed: HTTP {response.status_code}",
            "details": message,
        }

    api_error = data.get("error") if isinstance(data, dict) else None
    if isinstance(api_error, dict):
        return {
            "error": "get_directions failed: upstream API error",
            "details": api_error.get("message") or str(api_error),
        }

    routes = data.get("routes") if isinstance(data, dict) else None
    if not routes:
        return {
            "error": "NO_ROUTE",
            "origin": origin,
            "destination": destination,
            "mode": safe_mode,
            "details": data,
        }

    route = routes[0]
    legs = route.get("legs") if isinstance(route, dict) else None
    leg = legs[0] if isinstance(legs, list) and legs else route
    distance_meters = leg.get("distanceMeters") if isinstance(leg, dict) else None
    if distance_meters is None and isinstance(route, dict):
        distance_meters = route.get("distanceMeters")
    duration_seconds = _duration_to_seconds(
        leg.get("duration") if isinstance(leg, dict) else None
    )
    if duration_seconds is None and isinstance(route, dict):
        duration_seconds = _duration_to_seconds(route.get("duration"))

    return {
        "origin": origin,
        "destination": destination,
        "distance": _format_distance(distance_meters),
        "duration": _format_duration(duration_seconds),
        "distance_meters": distance_meters,
        "duration_seconds": duration_seconds,
        "mode": safe_mode,
    }


async def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    logger.info("Planner invoking tool '%s'", name)
    if name == "search_places":
        result = await _search_places(**arguments)
    elif name == "get_directions":
        result = await _get_directions(**arguments)
    else:
        result = {"error": f"Unknown tool: {name}"}

    if isinstance(result, dict) and result.get("error"):
        logger.warning("Planner tool '%s' returned error: %s", name, result["error"])
    return result


async def _run_tool_loop(
    messages: list[dict[str, Any]],
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> tuple[str, list[dict[str, Any]]]:
    work_messages = list(messages)
    consecutive_all_error_rounds = 0

    for _ in range(max_rounds):
        response = await _call_vllm_chat(
            messages=work_messages,
            tools=PLANNER_TOOLS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=MAX_COMPLETION_TOKENS,
        )

        message = response.choices[0].message
        if not message.tool_calls:
            return message.content or "", work_messages

        work_messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [tc.model_dump(exclude_none=True) for tc in message.tool_calls],
            }
        )

        round_had_success = False
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            raw_args = tool_call.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            try:
                tool_result = await _execute_tool(tool_name, args)
            except Exception as exc:  # pragma: no cover - guardrail
                tool_result = {
                    "error": f"Tool execution failed: {exc.__class__.__name__}",
                    "details": str(exc),
                }

            if not (isinstance(tool_result, dict) and tool_result.get("error")):
                round_had_success = True

            work_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result),
                }
            )

        if round_had_success:
            consecutive_all_error_rounds = 0
        else:
            consecutive_all_error_rounds += 1
            if consecutive_all_error_rounds >= 2:
                logger.warning(
                    "Planner stopping tool loop early after %s consecutive all-error rounds.",
                    consecutive_all_error_rounds,
                )
                summary = _summarize_tool_results(work_messages)
                if summary["place_results"] > 0:
                    # Avoid another expensive generation step when we already have venue grounding.
                    return '{"plans":[]}', work_messages
                break

    summary = _summarize_tool_results(work_messages)
    if summary["place_results"] > 0:
        logger.warning(
            "Planner collected %s grounded place candidates; skipping extra LLM finalize call.",
            summary["place_results"],
        )
        # Let caller synthesize deterministic maps-grounded plans.
        return '{"plans":[]}', work_messages

    work_messages.append(
        {
            "role": "user",
            "content": "Finalize now and return valid JSON with exactly 5 plans.",
        }
    )
    final = await _call_vllm_chat(
        messages=work_messages,
        temperature=0.2,
        max_tokens=MAX_COMPLETION_TOKENS,
    )
    return final.choices[0].message.content or "", work_messages


async def _run_structured_retry(
    prompt: str,
    prior_output: str,
    system_prompt: str,
) -> str:
    """Ask the model to rewrite prior output into strict schema-valid JSON."""
    response = await _call_vllm_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
            {
                "role": "assistant",
                "content": prior_output,
            },
            {
                "role": "user",
                "content": (
                    "Your last response was not parser-safe. "
                    "Return ONLY valid minified JSON with key 'plans' and exactly 5 plan objects "
                    "matching the required schema. "
                    "Do not include markdown fences, explanations, comments, or any text outside JSON. "
                    "Start with '{' and end with '}'."
                ),
            },
        ],
        temperature=0.0,
        max_tokens=REPAIR_MAX_COMPLETION_TOKENS,
    )
    return response.choices[0].message.content or ""


async def generate_group_plans(
    group_id: UUID,
    refinement_notes: str | None = None,
) -> list[dict[str, Any]]:
    """Generate and normalize 5 plans for a group using vLLM tool-calling."""
    context = await _load_group_context(group_id)
    settings = get_settings()
    use_tool_grounding = bool(settings.google_maps_api_key.strip())
    system_prompt = (
        SYSTEM_PROMPT_TOOL_GROUNDED if use_tool_grounding else SYSTEM_PROMPT_BEST_EFFORT
    )
    prompt = _build_prompt(
        context,
        refinement_notes=refinement_notes,
        require_tool_grounding=use_tool_grounding,
    )

    try:
        tool_messages: list[dict[str, Any]] = []
        if use_tool_grounding:
            logger.warning(
                "GOOGLE_MAPS_API_KEY detected; generating tool-grounded plans for group %s.",
                group_id,
            )
            output, tool_messages = await _run_tool_loop(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
            )
            tool_summary = _summarize_tool_results(tool_messages)
            logger.warning(
                "Planner tool summary for group %s: calls=%s place_calls=%s place_results=%s errors=%s",
                group_id,
                tool_summary["tool_calls"],
                tool_summary["place_calls"],
                tool_summary["place_results"],
                len(tool_summary["errors"]),
            )
        else:
            logger.warning(
                "GOOGLE_MAPS_API_KEY missing; generating best-effort plans without tool grounding."
            )
            response = await _call_vllm_chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=MAX_COMPLETION_TOKENS,
            )
            output = response.choices[0].message.content or ""
        try:
            return _extract_plans(output)
        except PlannerError as parse_exc:
            parse_message = str(parse_exc)
            if use_tool_grounding and "no plans" in parse_message.lower():
                tool_summary = _summarize_tool_results(tool_messages)
                synthesized = _build_maps_grounded_fallback_plans(
                    context=context,
                    tool_messages=tool_messages,
                    reason=f"LLM produced empty plans: {parse_message}",
                    refinement_notes=refinement_notes,
                )
                if synthesized:
                    logger.warning(
                        "Planner returned no plans for group %s; using maps-grounded fallback synthesis.",
                        group_id,
                    )
                    return synthesized
                if tool_summary["place_calls"] > 0 and tool_summary["place_results"] == 0:
                    details = (
                        "; ".join(tool_summary["errors"][:2])
                        if tool_summary["errors"]
                        else "search_places returned zero results"
                    )
                    raise PlannerError(
                        f"LLM returned no plans and map search produced no usable venues ({details})"
                    ) from parse_exc

            snippet = _strip_code_fence(output)[:800].replace("\n", "\\n")
            logger.warning(
                "Planner parse failed after tool loop for group %s: %s. "
                "Output length=%d snippet=%s Retrying structured output.",
                group_id,
                parse_exc,
                len(output or ""),
                snippet,
            )
            repaired = await _run_structured_retry(
                prompt=prompt,
                prior_output=output,
                system_prompt=system_prompt,
            )
            repaired_snippet = _strip_code_fence(repaired)[:800].replace("\n", "\\n")
            logger.info(
                "Planner structured retry output for group %s: length=%d snippet=%s",
                group_id,
                len(repaired or ""),
                repaired_snippet,
            )
            try:
                return _extract_plans(repaired)
            except PlannerError as repaired_exc:
                if use_tool_grounding:
                    synthesized = _build_maps_grounded_fallback_plans(
                        context=context,
                        tool_messages=tool_messages,
                        reason=f"Structured retry failed: {repaired_exc}",
                        refinement_notes=refinement_notes,
                    )
                    if synthesized:
                        logger.warning(
                            "Structured retry failed for group %s; using maps-grounded fallback synthesis.",
                            group_id,
                        )
                        return synthesized
                raise
    except Exception as exc:
        if settings.planner_fallback_enabled:
            reason = f"{exc.__class__.__name__}: {str(exc)}"
            return _build_fallback_plans(
                context=context,
                reason=reason,
                refinement_notes=refinement_notes,
            )
        raise PlannerError(f"Planner failed: {exc.__class__.__name__}: {exc}") from exc

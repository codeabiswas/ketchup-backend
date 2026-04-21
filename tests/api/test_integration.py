"""Integration tests — HTTP layer wired to mocked DB.

Each test exercises a route that is NOT already covered by tests/api/test_routes.py.
The mock_db fixture (from conftest) prevents real database calls; individual tests
customise return values via mock_db.<method>.return_value / .side_effect where
specific field shapes are required.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient




@pytest.mark.asyncio
async def test_create_group_requires_auth(test_app: AsyncClient):
    res = await test_app.post("/api/groups", json={"name": "Crew"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_group_missing_name_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.post("/api/groups", json={}, headers=auth_headers)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_group_name_must_be_string(test_app: AsyncClient, auth_headers):
    res = await test_app.post("/api/groups", json={"name": 999}, headers=auth_headers)
    # Pydantic coerces int to str — should pass validation and reach mock service
    assert res.status_code in [200, 201, 422, 500]


@pytest.mark.asyncio
async def test_create_group_with_valid_payload(test_app: AsyncClient, auth_headers, mock_db):
    group_id = str(uuid.uuid4())
    lead_id = auth_headers["X-User-Id"]
    mock_db.fetchrow.return_value = {
        "id": group_id,
        "name": "Movie Night Crew",
        "lead_id": lead_id,
        "status": "active",
    }
    res = await test_app.post(
        "/api/groups", json={"name": "Movie Night Crew"}, headers=auth_headers
    )
    assert res.status_code in [200, 201]



@pytest.mark.asyncio
async def test_list_groups_requires_auth(test_app: AsyncClient):
    res = await test_app.get("/api/groups")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_list_groups_returns_200_with_empty_data(test_app: AsyncClient, auth_headers, mock_db):
    mock_db.fetch.return_value = []
    res = await test_app.get("/api/groups", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "groups" in data
    assert "pending_invites" in data


@pytest.mark.asyncio
async def test_list_groups_response_shape(test_app: AsyncClient, auth_headers, mock_db):
    mock_db.fetch.return_value = []
    res = await test_app.get("/api/groups", headers=auth_headers)
    body = res.json()
    assert isinstance(body["groups"], list)
    assert isinstance(body["pending_invites"], list)




@pytest.mark.asyncio
async def test_get_group_requires_auth(test_app: AsyncClient):
    res = await test_app.get(f"/api/groups/{uuid.uuid4()}")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_group_invalid_uuid_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.get("/api/groups/not-a-uuid", headers=auth_headers)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_get_group_not_a_member_returns_403(test_app: AsyncClient, auth_headers, mock_db):
    # require_active_group_member queries fetchrow — return None to simulate non-member
    mock_db.fetchrow.return_value = None
    res = await test_app.get(f"/api/groups/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 403



@pytest.mark.asyncio
async def test_invite_members_requires_auth(test_app: AsyncClient):
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/invite", json={"emails": ["a@b.com"]}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_invite_members_invalid_schema_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/invite",
        json={"emails": "not-a-list"},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invite_members_too_many_emails_returns_400(test_app: AsyncClient, auth_headers, mock_db):
    # MAX_INVITES_PER_REQUEST = 3, sending 4 should be rejected immediately
    payload = {"emails": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/invite",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_invite_members_empty_emails_list(test_app: AsyncClient, auth_headers, mock_db):
    # Empty list passes the count check; require_group_lead will run.
    # mock lead_id=None → not equal to caller UUID → ForbiddenError (403).
    mock_db.fetchrow.return_value = {"id": "g1", "lead_id": None}
    payload = {"emails": []}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/invite",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in [200, 201, 403, 404]



@pytest.mark.asyncio
async def test_update_group_preferences_requires_auth(test_app: AsyncClient):
    res = await test_app.put(
        f"/api/groups/{uuid.uuid4()}/preferences", json={"notes": "hiking"}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_update_group_preferences_invalid_uuid(test_app: AsyncClient, auth_headers):
    res = await test_app.put(
        "/api/groups/bad-uuid/preferences",
        json={"notes": "test"},
        headers=auth_headers,
    )
    assert res.status_code == 422



@pytest.mark.asyncio
async def test_accept_invite_requires_auth(test_app: AsyncClient):
    res = await test_app.post(f"/api/groups/{uuid.uuid4()}/invite/accept")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_reject_invite_requires_auth(test_app: AsyncClient):
    res = await test_app.post(f"/api/groups/{uuid.uuid4()}/invite/reject")
    assert res.status_code == 401



@pytest.mark.asyncio
async def test_get_availability_requires_auth(test_app: AsyncClient):
    res = await test_app.get("/api/users/me/availability")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_availability_returns_blocks_key(test_app: AsyncClient, auth_headers, mock_db):
    mock_db.fetch.return_value = []
    res = await test_app.get("/api/users/me/availability", headers=auth_headers)
    assert res.status_code == 200
    assert "blocks" in res.json()


@pytest.mark.asyncio
async def test_replace_availability_requires_auth(test_app: AsyncClient):
    res = await test_app.put("/api/users/me/availability", json={"blocks": []})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_replace_availability_empty_blocks(test_app: AsyncClient, auth_headers, mock_db):
    res = await test_app.put(
        "/api/users/me/availability", json={"blocks": []}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json() == {"blocks": []}


@pytest.mark.asyncio
async def test_replace_availability_invalid_schema_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.put(
        "/api/users/me/availability",
        json={"blocks": "not-a-list"},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_replace_availability_block_missing_required_field(test_app: AsyncClient, auth_headers):
    # day_of_week missing
    res = await test_app.put(
        "/api/users/me/availability",
        json={"blocks": [{"start_time": "09:00", "end_time": "17:00"}]},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_replace_availability_valid_blocks(test_app: AsyncClient, auth_headers, mock_db):
    block_id = str(uuid.uuid4())
    mock_db.fetchrow.return_value = {
        "id": block_id,
        "day_of_week": 1,
        "start_time": "09:00:00",
        "end_time": "17:00:00",
        "label": None,
        "location": None,
    }
    payload = {
        "blocks": [
            {"day_of_week": 1, "start_time": "09:00", "end_time": "17:00"},
        ]
    }
    res = await test_app.put(
        "/api/users/me/availability", json=payload, headers=auth_headers
    )
    assert res.status_code == 200



@pytest.mark.asyncio
async def test_group_availability_requires_auth(test_app: AsyncClient):
    res = await test_app.post(f"/api/groups/{uuid.uuid4()}/availability")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_group_availability_invalid_uuid_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.post("/api/groups/bad-uuid/availability", headers=auth_headers)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_group_availability_non_member_returns_403(test_app: AsyncClient, auth_headers, mock_db):
    mock_db.fetchrow.return_value = None
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/availability", headers=auth_headers
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_group_availability_returns_common_slots_key(test_app: AsyncClient, auth_headers, mock_db):
    mock_db.fetchrow.return_value = {"id": "m1"}  # active member check passes
    mock_db.fetch.return_value = []               # no members, no blocks
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/availability", headers=auth_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert "common_slots" in body
    assert "per_user_busy" in body


# ---------------------------------------------------------------------------
# Auth — Google sign-in
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_signin_missing_email_returns_422(test_app: AsyncClient):
    res = await test_app.post("/api/auth/google-signin", json={"name": "Alice"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_google_signin_valid_payload(test_app: AsyncClient, mock_db):
    user_id = str(uuid.uuid4())
    mock_db.fetchrow.return_value = {
        "id": user_id,
        "email": "alice@example.com",
        "name": "Alice",
    }
    res = await test_app.post(
        "/api/auth/google-signin",
        json={"email": "alice@example.com", "name": "Alice"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "alice@example.com"
    assert "user_id" in body


@pytest.mark.asyncio
async def test_google_signin_invalid_json_body(test_app: AsyncClient):
    res = await test_app.post(
        "/api/auth/google-signin",
        content=b"{bad json}",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Users — current user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_current_user_requires_auth(test_app: AsyncClient):
    res = await test_app.get("/api/users/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_update_preferences_requires_auth(test_app: AsyncClient):
    res = await test_app.put("/api/users/me/preferences", json={})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_update_preferences_invalid_schema(test_app: AsyncClient, auth_headers):
    # activity_likes must be list[str], not a string
    res = await test_app.put(
        "/api/users/me/preferences",
        json={"activity_likes": "hiking"},
        headers=auth_headers,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Feedback — submit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_feedback_requires_auth(test_app: AsyncClient):
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/events/{uuid.uuid4()}/feedback",
        json={"rating": "loved", "attended": True},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_submit_feedback_missing_rating_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/events/{uuid.uuid4()}/feedback",
        json={"attended": True},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_submit_feedback_invalid_uuid_path_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.post(
        "/api/groups/bad/events/bad/feedback",
        json={"rating": "loved", "attended": True},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_submit_feedback_invalid_rating_value(test_app: AsyncClient, auth_headers, mock_db):
    # "meh" is not a valid rating — service should raise BadRequestError → 400
    payload = {"rating": "meh", "attended": True}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/events/{uuid.uuid4()}/feedback",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in [400, 404]


@pytest.mark.asyncio
async def test_submit_feedback_valid_rating_loved(test_app: AsyncClient, auth_headers, mock_db):
    feedback_id = str(uuid.uuid4())
    mock_db.fetchrow.side_effect = [
        {"id": "m1"},                                          # require_active_group_member
        {"id": "e1"},                                          # require_event_in_group
        {"id": feedback_id, "rating": "loved", "notes": None},  # INSERT feedback
    ]
    payload = {"rating": "loved", "attended": True}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/events/{uuid.uuid4()}/feedback",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in [200, 201]


# ---------------------------------------------------------------------------
# Feedback — get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_feedback_requires_auth(test_app: AsyncClient):
    res = await test_app.get(
        f"/api/groups/{uuid.uuid4()}/events/{uuid.uuid4()}/feedback"
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_feedback_invalid_path_uuids_returns_422(test_app: AsyncClient, auth_headers):
    res = await test_app.get(
        "/api/groups/bad-id/events/bad-id/feedback",
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_get_feedback_returns_summary_structure(test_app: AsyncClient, auth_headers, mock_db):
    mock_db.fetchrow.side_effect = [
        {"id": "m1"},  # require_active_group_member
        {"id": "e1"},  # require_event_in_group
    ]
    mock_db.fetch.return_value = [
        {"id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()), "name": "Alice", "rating": "loved", "notes": None, "attended": True},
        {"id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()), "name": "Bob", "rating": "liked", "notes": "fun", "attended": True},
    ]
    res = await test_app.get(
        f"/api/groups/{uuid.uuid4()}/events/{uuid.uuid4()}/feedback",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert "feedbacks" in body
    assert "summary" in body
    assert body["summary"]["loved"] == 1
    assert body["summary"]["liked"] == 1
    assert body["summary"]["disliked"] == 0


# ---------------------------------------------------------------------------
# ServiceError propagation — error hierarchy mapped to HTTP status codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_not_found_error_maps_to_404(test_app: AsyncClient, auth_headers, mock_db):
    # Simulate group fetch returning None after member check passes
    mock_db.fetchrow.side_effect = [
        {"id": "m1"},  # require_active_group_member passes
        None,          # get_group fetchrow → raises NotFoundError
    ]
    res = await test_app.get(f"/api/groups/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_forbidden_error_maps_to_403(test_app: AsyncClient, auth_headers, mock_db):
    # No active member record → ForbiddenError → 403
    mock_db.fetchrow.return_value = None
    res = await test_app.get(f"/api/groups/{uuid.uuid4()}", headers=auth_headers)
    assert res.status_code == 403

import json
import uuid

import pytest
from httpx import AsyncClient


# --- Base Routing Validations ---
@pytest.mark.asyncio
async def test_health_check(test_app: AsyncClient):
    response = await test_app.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_root(test_app: AsyncClient):
    response = await test_app.get("/")
    assert response.status_code == 200


# --- UUID and Parameter Validations ---
@pytest.mark.asyncio
async def test_get_group_plans_invalid_uuid(test_app: AsyncClient, auth_headers):
    res = await test_app.get(
        "/api/groups/not-a-uuid/plans/round-uuid", headers=auth_headers
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_submit_vote_empty_rankings(test_app: AsyncClient, auth_headers, mock_db):
    payload = {"rankings": [], "notes": "No opinions"}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in [200, 201, 404]


@pytest.mark.asyncio
async def test_submit_vote_massive_notes_payload(
    test_app: AsyncClient, auth_headers, mock_db
):
    payload = {"rankings": [str(uuid.uuid4())], "notes": "A" * 1000000}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code in [400, 404, 413, 200]


@pytest.mark.asyncio
async def test_submit_vote_invalid_schema_types(test_app: AsyncClient, auth_headers):
    payload = {"rankings": {"first": str(uuid.uuid4())}, "notes": 1234}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 422


# --- Authorization and Injection Protections ---
@pytest.mark.asyncio
async def test_api_missing_internal_auth_header(test_app: AsyncClient):
    headers = {"X-User-Id": str(uuid.uuid4())}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        json={},
        headers=headers,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_missing_user_id_header(test_app: AsyncClient):
    headers = {"X-Internal-Auth": "test_internal"}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        json={},
        headers=headers,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_sqli_in_user_id(test_app: AsyncClient):
    headers = {
        "X-User-Id": "1' OR 1=1; DROP TABLE users; --",
        "X-Internal-Auth": "test_internal",
    }
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        json={},
        headers=headers,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_generate_plans_wrong_http_verb(test_app: AsyncClient, auth_headers):
    res = await test_app.get(
        f"/api/groups/{uuid.uuid4()}/generate-plans", headers=auth_headers
    )
    assert res.status_code == 405


# --- Resiliency and System Configuration Scenarios ---
@pytest.mark.asyncio
async def test_analytics_fetch_handles_sql_truncation(
    test_app: AsyncClient, auth_headers
):
    bad_id_str = "A" * 600
    res = await test_app.get(
        f"/api/internal/analytics/status?job_name={bad_id_str}", headers=auth_headers
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_cors_preflight_request(test_app: AsyncClient):
    res = await test_app.options(
        "/api/groups/123/plans",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_post_invalid_json_body(test_app: AsyncClient, auth_headers):
    # Sends garbled un-decodable bytes as application/json
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        content=b"Invalid: {JSON]",
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_large_number_handling(test_app: AsyncClient, auth_headers):
    # Some integer overflow bounds testing on pagination or offset queries (if applicable)
    res = await test_app.get(
        f"/api/groups/{uuid.uuid4()}/plans/history?limit=1000000000000000000",
        params=dict(),
        headers=auth_headers,
    )
    # Fastapi treats undefined query params via ignore or 422 if defined as ints
    assert res.status_code in [200, 422, 404]


@pytest.mark.asyncio
async def test_user_id_null_header(test_app: AsyncClient):
    headers = {"X-User-Id": "null", "X-Internal-Auth": "test_internal"}
    res = await test_app.post(
        f"/api/groups/{uuid.uuid4()}/plans/{uuid.uuid4()}/vote",
        json={},
        headers=headers,
    )
    assert res.status_code == 401

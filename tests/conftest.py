"""Pytest test-path bootstrap for local package imports."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from database.connection import db


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    """Override essential settings to prevent hitting external APIs unintentionally."""
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("VLLM_API_KEY", "test_key")
    monkeypatch.setenv("VLLM_BASE_URL", "http://testserver/v1")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test_maps_key")
    monkeypatch.setenv("BACKEND_INTERNAL_API_KEY", "test_internal")
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_db(mocker):
    """Mock the entire asyncpg database pool wrapper to prevent actual network calls."""
    from database.connection import db

    mocker.patch.object(
        db,
        "fetch",
        new_callable=mocker.AsyncMock,
        return_value=[{"id": "c30ff049-7c4d-4444-93ff-ee1cda7c5555"}],
    )
    mocker.patch.object(
        db, "fetchrow", new_callable=mocker.AsyncMock, return_value={"id": "test"}
    )
    mocker.patch.object(db, "fetchval", new_callable=mocker.AsyncMock, return_value=1)
    mocker.patch.object(db, "execute", new_callable=mocker.AsyncMock, return_value="OK")
    return db


@pytest.fixture
async def test_app(mock_db):
    """Yield a FastAPI TestClient using HTTpx AsyncClient."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def auth_headers():
    return {"X-User-Id": str(uuid4()), "X-Internal-Auth": "test_internal"}

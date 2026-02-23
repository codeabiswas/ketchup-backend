"""Deprecated standalone agent service.

This module is intentionally kept as a compatibility stub to avoid running a
second orchestration surface with drift from the canonical planner in
``agents/planning.py``.
"""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

DEPRECATION_MESSAGE = (
    "Standalone agent service is deprecated. "
    "Use backend planning endpoints backed by agents.planning "
    "(/api/groups/{group_id}/generate-plans and /refine)."
)

app = FastAPI(
    title="Ketchup Agent Service (Deprecated)",
    version="0.1.0",
    description="Deprecated compatibility surface. No LLM or tool orchestration is executed.",
)


@app.get("/healthz")
def healthz():
    return {"ok": True, "deprecated": True}


@app.get("/readyz")
def readyz():
    return {"ready": True, "deprecated": True}


def _deprecated_response(endpoint: str) -> JSONResponse:
    logger.warning("Deprecated endpoint called: %s", endpoint)
    return JSONResponse(
        status_code=410,
        content={
            "error": "deprecated_endpoint",
            "endpoint": endpoint,
            "detail": DEPRECATION_MESSAGE,
        },
    )


@app.post("/agent")
async def agent():
    return _deprecated_response("/agent")


@app.post("/agent/stream")
async def agent_stream():
    return _deprecated_response("/agent/stream")


@app.post("/v1/chat/completions")
async def chat_completions():
    return _deprecated_response("/v1/chat/completions")

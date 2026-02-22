# agents/app/main.py

import asyncio
import json
import logging
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openai import OpenAI
from pydantic import BaseModel

app = FastAPI()
logger = logging.getLogger(__name__)

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen3-4B-Instruct-2507")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")
VLLM_HEALTH_TIMEOUT = float(os.getenv("VLLM_HEALTH_TIMEOUT", "3"))
VLLM_INFER_TIMEOUT = float(os.getenv("VLLM_INFER_TIMEOUT", "120"))

health_client = OpenAI(
    api_key=VLLM_API_KEY,
    base_url=VLLM_BASE_URL,
    timeout=VLLM_HEALTH_TIMEOUT,
    max_retries=0,
)

infer_client = OpenAI(
    api_key=VLLM_API_KEY,
    base_url=VLLM_BASE_URL,
    timeout=VLLM_INFER_TIMEOUT,
    max_retries=0,
)

MAPS_API_KEY = os.getenv("MAPS_API_KEY", "")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_directions",
            "description": "Get travel distance and duration between an origin and destination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "Starting address or place.",
                    },
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


def _vllm_ping():
    # minimal ping: list models
    health_client.models.list()
    return True


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    try:
        _vllm_ping()
        return {"ready": True}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "error": str(e)},
        )


async def search_places(query: str, location: str, max_results: int = 3):
    if not MAPS_API_KEY:
        return {"error": "MAPS_API_KEY not set"}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={
                    "query": f"{query} near {location}",
                    "key": MAPS_API_KEY,
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.exception("search_places failed")
        return {
            "error": f"search_places failed: {exc.__class__.__name__}",
            "details": str(exc),
        }

    places = []
    for item in data.get("results", [])[: max(1, min(max_results, 10))]:
        places.append(
            {
                "name": item.get("name"),
                "address": item.get("formatted_address"),
                "rating": item.get("rating"),
                "price_level": item.get("price_level"),
            }
        )
    return {"places": places}


async def get_directions(origin: str, destination: str, mode: str = "driving"):
    if not MAPS_API_KEY:
        return {"error": "MAPS_API_KEY not set"}

    safe_mode = mode if mode in {"driving", "transit", "walking"} else "driving"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params={
                    "origin": origin,
                    "destination": destination,
                    "mode": safe_mode,
                    "key": MAPS_API_KEY,
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.exception("get_directions failed")
        return {
            "error": f"get_directions failed: {exc.__class__.__name__}",
            "details": str(exc),
        }

    if data.get("status") != "OK" or not data.get("routes"):
        return {
            "error": data.get("status", "NO_ROUTE"),
            "origin": origin,
            "destination": destination,
            "mode": safe_mode,
        }

    leg = data["routes"][0]["legs"][0]
    return {
        "origin": leg.get("start_address"),
        "destination": leg.get("end_address"),
        "distance": (leg.get("distance") or {}).get("text"),
        "duration": (leg.get("duration") or {}).get("text"),
        "mode": safe_mode,
    }


async def execute_tool(name: str, args: dict):
    if name == "search_places":
        return await search_places(**args)
    if name == "get_directions":
        return await get_directions(**args)
    return {"error": f"Unknown tool: {name}"}


async def run_tool_loop(messages, model: str = MODEL_NAME, max_iters: int = 6):
    work_messages = list(messages)
    for _ in range(max_iters):
        try:
            resp = infer_client.chat.completions.create(
                model=model,
                messages=work_messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
        except Exception as e:
            logger.exception("LLM call failed")
            return {
                "ok": False,
                "messages": work_messages,
                "final_text": f"Model call failed: {str(e)}",
                "stopped": True,
            }

        msg = resp.choices[0].message

        if not msg.tool_calls:
            return {
                "ok": True,
                "messages": work_messages,
                "final_text": msg.content or "",
                "stopped": False,
            }

        work_messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
        )

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                tool_args = json.loads(raw_args)
            except json.JSONDecodeError:
                tool_args = {}
                tool_result = {
                    "error": "Tool arguments were not valid JSON",
                    "raw_arguments": raw_args,
                }
            else:
                try:
                    tool_result = await execute_tool(tool_name, tool_args)
                except Exception as e:
                    logger.exception("Tool execution failed")
                    tool_result = {"error": f"Tool execution failed: {str(e)}"}
            work_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result),
                }
            )

    return {
        "ok": True,
        "messages": work_messages,
        "final_text": "Stopped after too many tool iterations.",
        "stopped": True,
    }


def _final_stream(messages, model: str = MODEL_NAME):
    return infer_client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        temperature=0.2,
    )


def _extract_delta_text(delta) -> str:
    if delta is None:
        return ""
    content = getattr(delta, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text", ""))
            else:
                text = getattr(part, "text", None)
                if text:
                    parts.append(text)
        return "".join(parts)
    return ""


def _sse_data(payload: str) -> str:
    return f"data: {payload}\n\n"


async def _agent_sse_stream(messages, model: str = MODEL_NAME):
    try:
        stream = _final_stream(messages, model=model)
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                await asyncio.sleep(0)
                continue
            text = _extract_delta_text(choices[0].delta)
            if text:
                yield _sse_data(json.dumps({"delta": text, "done": False}))
            await asyncio.sleep(0)
    except Exception as e:
        logger.exception("Streaming failed")
        yield _sse_data(
            json.dumps(
                {"delta": "", "done": True, "error": f"Model stream failed: {str(e)}"}
            )
        )
        return
    yield _sse_data(json.dumps({"delta": "", "done": True}))


async def _agent_sse_text(text: str):
    if text:
        yield _sse_data(json.dumps({"delta": text, "done": False}))
    yield _sse_data(json.dumps({"delta": "", "done": True}))


async def _openai_sse_stream(messages, model: str = MODEL_NAME):
    try:
        stream = _final_stream(messages, model=model)
        for chunk in stream:
            if hasattr(chunk, "model_dump"):
                payload = chunk.model_dump(mode="json", exclude_none=True)
            else:
                payload = {}
            yield _sse_data(json.dumps(payload))
            await asyncio.sleep(0)
    except Exception as e:
        logger.exception("Streaming failed")
        yield _sse_data(
            json.dumps(
                {
                    "id": "chatcmpl-local",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"Model stream failed: {str(e)}"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
        )
        yield _sse_data("[DONE]")
        return
    yield _sse_data("[DONE]")


async def _openai_sse_text(text: str, model: str = MODEL_NAME):
    yield _sse_data(
        json.dumps(
            {
                "id": "chatcmpl-local",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
        )
    )
    if text:
        yield _sse_data(
            json.dumps(
                {
                    "id": "chatcmpl-local",
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None,
                        }
                    ],
                }
            )
        )
    yield _sse_data(
        json.dumps(
            {
                "id": "chatcmpl-local",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
    )
    yield _sse_data("[DONE]")


class AgentReq(BaseModel):
    input: str


@app.post("/agent")
async def agent(req: AgentReq):
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Use tools when needed for venue search and travel logistics.",
        },
        {"role": "user", "content": req.input},
    ]
    result = await run_tool_loop(messages, model=MODEL_NAME)
    return {"output": result["final_text"]}


@app.post("/agent/stream")
async def agent_stream(req: AgentReq):
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Use tools when needed for venue search and travel logistics.",
        },
        {"role": "user", "content": req.input},
    ]
    result = await run_tool_loop(messages, model=MODEL_NAME)
    if not result["ok"] or result["stopped"]:
        return StreamingResponse(
            _agent_sse_text(result["final_text"]),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return StreamingResponse(
        _agent_sse_stream(result["messages"], model=MODEL_NAME),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model") or MODEL_NAME
    if not messages:
        return {"error": "messages is required"}

    result = await run_tool_loop(messages, model=model)
    if body.get("stream"):
        if not result["ok"] or result["stopped"]:
            return StreamingResponse(
                _openai_sse_text(result["final_text"], model=model),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return StreamingResponse(
            _openai_sse_stream(result["messages"], model=model),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result["final_text"]},
                "finish_reason": "stop",
            }
        ],
    }

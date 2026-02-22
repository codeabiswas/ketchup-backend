from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
import httpx
import os
import json
import logging
import asyncio

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
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "maps_text_search",
            "description": "Search places using Google Places Text Search (returns name/address/rating).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "User query like 'coffee near Times Square'"},
                    "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Web search for up-to-date info; returns top results with titles/snippets/links.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
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

async def maps_text_search(query: str, max_results: int = 5):
    if not MAPS_API_KEY:
        return {"error": "MAPS_API_KEY not set"}
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": MAPS_API_KEY,
        # Field masks are required for Text Search (New). :contentReference[oaicite:7]{index=7}
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.googleMapsUri",
    }
    payload = {"textQuery": query, "maxResultCount": max_results}
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        logger.exception("maps_text_search failed")
        return {"error": f"maps_text_search failed: {e.__class__.__name__}: {str(e)}"}

    places = data.get("places", [])[:max_results]
    out = []
    for p in places:
        out.append({
            "name": p.get("displayName", {}).get("text"),
            "address": p.get("formattedAddress"),
            "rating": p.get("rating"),
            "maps_url": p.get("googleMapsUri"),
        })
    return {"results": out}

async def web_search(query: str, num_results: int = 5):
    if not SERPER_API_KEY:
        return {"error": "SERPER_API_KEY not set"}
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num_results}
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        logger.exception("web_search failed")
        return {"error": f"web_search failed: {e.__class__.__name__}: {str(e)}"}

    organic = data.get("organic", [])[:num_results]
    out = []
    for it in organic:
        out.append({
            "title": it.get("title"),
            "link": it.get("link"),
            "snippet": it.get("snippet"),
        })
    return {"results": out}

async def execute_tool(name: str, args: dict):
    if name == "maps_text_search":
        return await maps_text_search(**args)
    if name == "web_search":
        return await web_search(**args)
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

        work_messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

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
            work_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result),
            })

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
        yield _sse_data(json.dumps({"delta": "", "done": True, "error": f"Model stream failed: {str(e)}"}))
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
        yield _sse_data(json.dumps({
            "id": "chatcmpl-local",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": f"Model stream failed: {str(e)}"},
                "finish_reason": "stop",
            }],
        }))
        yield _sse_data("[DONE]")
        return
    yield _sse_data("[DONE]")

async def _openai_sse_text(text: str, model: str = MODEL_NAME):
    yield _sse_data(json.dumps({
        "id": "chatcmpl-local",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant"},
            "finish_reason": None,
        }],
    }))
    if text:
        yield _sse_data(json.dumps({
            "id": "chatcmpl-local",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": text},
                "finish_reason": None,
            }],
        }))
    yield _sse_data(json.dumps({
        "id": "chatcmpl-local",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }))
    yield _sse_data("[DONE]")

class AgentReq(BaseModel):
    input: str

@app.post("/agent")
async def agent(req: AgentReq):
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use tools when needed for fresh info or places."},
        {"role": "user", "content": req.input},
    ]
    result = await run_tool_loop(messages, model=MODEL_NAME)
    return {"output": result["final_text"]}

@app.post("/agent/stream")
async def agent_stream(req: AgentReq):
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use tools when needed for fresh info or places."},
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
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result["final_text"]},
            "finish_reason": "stop",
        }],
    }

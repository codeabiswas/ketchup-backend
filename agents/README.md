# Ketchup Agents

`agents/planning.py` is the only supported orchestration surface for plan generation.

## Status

- Canonical: `planning.py`
- Deprecated compatibility stub: `app/main.py`

`app/main.py` intentionally returns `410 Gone` for legacy endpoints (`/agent`,
`/agent/stream`, `/v1/chat/completions`) to prevent orchestration drift.

## Planner Capabilities (`planning.py`)

- OpenAI-compatible tool-calling against `VLLM_BASE_URL`
- Maps grounding tools:
  - `search_places` (Places API New)
  - `get_directions` (Routes API)
- Optional web-search tool:
  - `web_search` (enabled only when `TAVILY_API_KEY` is set)
  - Fallback behavior: used when maps search yields no usable venues
- Deterministic fallback synthesis:
  - `maps_fallback` when tool-grounded places are available
  - `web_fallback` when maps has no venues but web search yields candidates
  - generic `fallback` when planner fallback is enabled

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `VLLM_BASE_URL` | `http://localhost:8080/v1` | OpenAI-compatible model endpoint |
| `VLLM_MODEL` | `Qwen/Qwen3-4B-Instruct` | Model name used for completions |
| `VLLM_API_KEY` | `EMPTY` | API key for OpenAI-compatible endpoint |
| `GOOGLE_MAPS_API_KEY` | empty | Enables maps grounding tools |
| `TAVILY_API_KEY` | empty | Enables optional `web_search` tool/fallback |
| `PLANNER_FALLBACK_ENABLED` | `false` | Enables generic non-grounded fallback |

## Notes

- Do not build new product flows on `agents/app/main.py`.
- Use backend API routes and services that call `agents/planning.py`.

## Quick Verification

```bash
docker compose -f ketchup-local/docker-compose.yml exec -T backend env PYTHONPATH=/app \
  python -c "import asyncio,json; import agents.planning as planning; out=asyncio.run(planning._web_search(query='group activities for friends', location='Boston, MA', max_results=3)); print('ERROR:', out.get('error')); print('RESULT_COUNT:', len(out.get('results', []))); print(json.dumps(out.get('results', [])[:2], indent=2))"
```

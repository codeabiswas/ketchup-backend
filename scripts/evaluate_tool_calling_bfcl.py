#!/usr/bin/env python3
"""Evaluate vLLM tool-calling on a synthetic group-outings benchmark.

Benchmark choice:
- local synthetic dataset tailored to Ketchup's outing-planning workflow
- mock Google Maps-style tools plus web search

Why this benchmark:
- mirrors real group-planning asks better than BFCL,
- covers venue discovery, directions lookup, and timely web-search cases,
- includes abstain examples where the model should not call a tool yet,
- uses LLM-as-a-judge scoring for argument quality instead of strict argument equality.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "benchmarks"
    / "synthetic_group_outings_tool_calling.json"
)
DEFAULT_JUDGE_THRESHOLD = 0.8


def _maybe_init_wandb(args: argparse.Namespace) -> Any | None:
    project = args.wandb_project or os.getenv("WANDB_PROJECT")
    if not project:
        return None

    try:
        import wandb
    except ImportError as exc:
        raise RuntimeError(
            "W&B tracking was requested, but `wandb` is not installed. "
            "Install dependencies from requirements.txt or add `pip install wandb`."
        ) from exc

    entity = args.wandb_entity or os.getenv("WANDB_ENTITY")
    tags = list(args.wandb_tags or [])
    config = {
        "benchmark": "synthetic_group_outings_tool_calling",
        "dataset_path": args.dataset_path,
        "model": args.model,
        "model_ref": args.model_ref or args.model,
        "judge_model": args.judge_model or args.model,
        "judge_threshold": args.judge_threshold,
        "judge_max_tokens": args.judge_max_tokens,
        "sample_size": args.sample_size,
        "seed": args.seed,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "mode": "existing_endpoint" if args.base_url else "spawned_local_vllm",
        "base_url": args.base_url,
        "host": args.host,
        "port": args.port,
        "startup_timeout": args.startup_timeout,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "max_model_len": args.max_model_len,
        "max_num_seqs": args.max_num_seqs,
        "tool_call_parser": args.tool_call_parser,
        "output": args.output,
    }
    return wandb.init(
        project=project,
        entity=entity,
        name=args.wandb_run_name,
        group=args.wandb_group,
        tags=tags,
        config=config,
    )


def _log_wandb_results(run: Any, summary: dict[str, Any], output_path: Path) -> None:
    import wandb

    for key, value in summary.items():
        if key != "results":
            run.summary[key] = value
    run.summary["output_path"] = str(output_path.resolve())
    run.summary["failure_count"] = sum(not item["exact_match"] for item in summary["results"])

    run.log(
        {
            "benchmark/total_examples": summary["benchmark_info"]["total_examples"],
            "benchmark/abstain_examples": summary["benchmark_info"]["abstain_examples"],
            "decision_accuracy": summary["decision_accuracy"],
            "no_tool_accuracy": summary["no_tool_accuracy"],
            "tool_name_accuracy": summary["tool_name_accuracy"],
            "argument_judge_score_mean": summary["argument_judge_score_mean"],
            "argument_judge_pass_rate": summary["argument_judge_pass_rate"],
            "exact_match_accuracy": summary["exact_match_accuracy"],
            "failure_count": run.summary["failure_count"],
            "sample_size": summary["sample_size"],
            "predicted_tool_rate": summary["predicted_tool_rate"],
        }
    )

    table = wandb.Table(
        columns=[
            "id",
            "category",
            "difficulty",
            "question",
            "expected_tool_name",
            "expected_arguments",
            "expected_argument_contains",
            "predicted_name",
            "predicted_arguments",
            "raw_arguments",
            "decision_match",
            "tool_name_match",
            "argument_judge_score",
            "argument_judge_pass",
            "argument_judge_verdict",
            "argument_judge_rationale",
            "exact_match",
            "tool_call_count",
        ]
    )
    for item in summary["results"]:
        table.add_data(
            item["id"],
            item["category"],
            item["difficulty"],
            item["question"],
            item["expected_tool_name"],
            _canonical_json(item["expected_arguments"]),
            _canonical_json(item["expected_argument_contains"]),
            item["predicted_name"],
            _canonical_json(item["predicted_arguments"]) if item["predicted_arguments"] is not None else None,
            item["raw_arguments"],
            item["decision_match"],
            item["tool_name_match"],
            item["argument_judge_score"],
            item["argument_judge_pass"],
            item["argument_judge_verdict"],
            item["argument_judge_rationale"],
            item["exact_match"],
            item["tool_call_count"],
        )
    run.log({"results_table": table})

    artifact = wandb.Artifact(name=f"tool-calling-group-outings-{run.id}", type="evaluation")
    artifact.add_file(str(output_path.resolve()))
    run.log_artifact(artifact)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _build_benchmark_info(dataset: dict[str, Any]) -> dict[str, Any]:
    """Summarize the synthetic benchmark composition for reporting."""
    examples = dataset["examples"]
    by_category: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    by_expected_tool: dict[str, int] = {"no_tool": 0}

    for entry in examples:
        category = entry.get("category", "unknown")
        difficulty = entry.get("difficulty", "unknown")
        by_category[category] = by_category.get(category, 0) + 1
        by_difficulty[difficulty] = by_difficulty.get(difficulty, 0) + 1

        expected = entry.get("expected_tool_call")
        if expected is None:
            by_expected_tool["no_tool"] += 1
        else:
            tool_name = expected.get("name", "unknown")
            by_expected_tool[tool_name] = by_expected_tool.get(tool_name, 0) + 1

    return {
        "name": dataset.get("name"),
        "description": dataset.get("description"),
        "benchmark_focus": dataset.get("benchmark_focus", []),
        "scoring_notes": dataset.get("scoring_notes", []),
        "total_examples": len(examples),
        "abstain_examples": by_expected_tool["no_tool"],
        "categories": by_category,
        "difficulty_distribution": by_difficulty,
        "expected_tool_distribution": by_expected_tool,
    }


def _normalize_schema(node: Any) -> Any:
    if isinstance(node, dict):
        normalized: dict[str, Any] = {}
        for key, value in node.items():
            if key == "type" and isinstance(value, str):
                normalized[key] = {
                    "dict": "object",
                    "float": "number",
                    "bool": "boolean",
                }.get(value, value)
            else:
                normalized[key] = _normalize_schema(value)
        return normalized
    if isinstance(node, list):
        return [_normalize_schema(item) for item in node]
    return node


def _load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Dataset must be a JSON object.")

    examples = payload.get("examples")
    tools = payload.get("tools")
    if not isinstance(examples, list) or not examples:
        raise ValueError("Dataset must include a non-empty `examples` list.")
    if not isinstance(tools, list) or not tools:
        raise ValueError("Dataset must include a non-empty `tools` list.")

    payload["tools"] = [_normalize_schema(tool) for tool in tools]
    return payload


def _extract_messages(dataset: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    system_prompt = dataset.get("system_prompt")
    if isinstance(system_prompt, str) and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})

    entry_messages = entry.get("messages")
    if not isinstance(entry_messages, list) or not entry_messages:
        raise ValueError(f"Entry {entry.get('id')} must include non-empty `messages`.")

    for message in entry_messages:
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError(f"Entry {entry.get('id')} has malformed message content.")
        messages.append({"role": role, "content": content})
    return messages


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_values_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_values_equal(left[k], right[k]) for k in left)
    return left == right


def _extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    choices = response.get("choices") or []
    if not choices:
        return []
    message = choices[0].get("message") or {}
    return message.get("tool_calls") or []


def _extract_prediction(response: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, str | None]:
    tool_calls = _extract_tool_calls(response)
    if not tool_calls:
        return None, None, None

    first_call = tool_calls[0]
    function = first_call.get("function") or {}
    name = function.get("name")
    raw_arguments = function.get("arguments")

    if not isinstance(raw_arguments, str):
        return name, None, None

    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return name, None, raw_arguments
    return name, arguments, raw_arguments


def _extract_message_text(response: dict[str, Any]) -> str:
    """Extract assistant text from a chat completion payload."""
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _parse_first_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object embedded in text."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        start = match.start()
        try:
            candidate, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def _call_text_model(
    client: httpx.Client,
    *,
    completions_url: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Call the served model without tools, used for judge prompts."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = client.post(completions_url, json=payload, timeout=120.0)
    response.raise_for_status()
    return response.json()


def _judge_argument_match(
    client: httpx.Client,
    *,
    completions_url: str,
    judge_model: str,
    question: str,
    expected_tool_name: str,
    expected_arguments: dict[str, Any],
    expected_argument_contains: dict[str, list[str]],
    predicted_name: str | None,
    predicted_arguments: dict[str, Any] | None,
    raw_arguments: str | None,
    max_tokens: int,
) -> dict[str, Any]:
    """Use the served model as a semantic judge for argument quality only."""
    if predicted_name != expected_tool_name:
        return {
            "score": 0.0,
            "pass": False,
            "verdict": "wrong_tool",
            "rationale": "Predicted tool name did not match expected tool name.",
        }
    if predicted_arguments is None:
        return {
            "score": 0.0,
            "pass": False,
            "verdict": "missing_arguments",
            "rationale": "Predicted tool arguments were missing or not valid JSON.",
        }

    judge_messages = [
        {
            "role": "system",
            "content": (
                "You are grading tool-call arguments for a planning benchmark. "
                "Score only the predicted arguments, not the tool choice. "
                "Return JSON only with keys: score, verdict, rationale. "
                "Use score from 0.0 to 1.0. "
                "A high score means the predicted arguments would likely produce the intended tool result, "
                "even if wording differs from the reference."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{question}\n\n"
                f"Expected tool:\n{expected_tool_name}\n\n"
                f"Reference required arguments:\n{json.dumps(expected_arguments, ensure_ascii=True, sort_keys=True)}\n\n"
                f"Reference semantic argument cues:\n{json.dumps(expected_argument_contains, ensure_ascii=True, sort_keys=True)}\n\n"
                f"Predicted tool:\n{predicted_name}\n\n"
                f"Predicted parsed arguments:\n{json.dumps(predicted_arguments, ensure_ascii=True, sort_keys=True)}\n\n"
                f"Predicted raw arguments:\n{raw_arguments}\n\n"
                "Rubric:\n"
                "- 1.0: arguments are fully suitable and preserve the key intent.\n"
                "- 0.7 to 0.9: mostly correct, minor omissions or wording differences.\n"
                "- 0.4 to 0.6: partially useful but missing an important part.\n"
                "- 0.0 to 0.3: unlikely to retrieve the intended result.\n"
                "Return strict JSON only."
            ),
        },
    ]
    response = _call_text_model(
        client,
        completions_url=completions_url,
        model=judge_model,
        messages=judge_messages,
        temperature=0.0,
        max_tokens=max_tokens,
    )
    parsed = _parse_first_json_object(_extract_message_text(response))
    if parsed is None:
        return {
            "score": 0.0,
            "pass": False,
            "verdict": "judge_parse_error",
            "rationale": "Judge response was not parseable JSON.",
        }

    raw_score = parsed.get("score", 0.0)
    try:
        score = max(0.0, min(1.0, float(raw_score)))
    except (TypeError, ValueError):
        score = 0.0
    verdict = parsed.get("verdict")
    rationale = parsed.get("rationale")
    return {
        "score": score,
        "pass": False,
        "verdict": verdict if isinstance(verdict, str) else "unlabeled",
        "rationale": rationale if isinstance(rationale, str) else "No rationale returned by judge.",
    }


def _compute_running_metrics(
    *,
    seen: int,
    decision_hits: int,
    no_tool_hits: int,
    tool_name_hits: int,
    exact_hits: int,
    predicted_tool_calls: int,
    expected_tool_call_examples: int,
    expected_no_tool_examples: int,
    argument_score_total: float,
    argument_passes: int,
) -> dict[str, float]:
    """Compute running metrics for console and W&B step logging."""
    return {
        "decision_accuracy": decision_hits / seen,
        "no_tool_accuracy": no_tool_hits / expected_no_tool_examples if expected_no_tool_examples else 0.0,
        "tool_name_accuracy": tool_name_hits / expected_tool_call_examples if expected_tool_call_examples else 0.0,
        "argument_judge_score_mean": (
            argument_score_total / expected_tool_call_examples if expected_tool_call_examples else 0.0
        ),
        "argument_judge_pass_rate": (
            argument_passes / expected_tool_call_examples if expected_tool_call_examples else 0.0
        ),
        "exact_match_accuracy": exact_hits / seen,
        "predicted_tool_rate": predicted_tool_calls / seen,
    }


def _log_wandb_step(run: Any, *, step_index: int, result: dict[str, Any], metrics: dict[str, float]) -> None:
    """Log per-example benchmark results and running metrics to W&B."""
    payload = {
        "step/example_index": step_index,
        "example/id": result["id"],
        "example/category": result["category"],
        "example/difficulty": result["difficulty"],
        "example/expected_tool_name": result["expected_tool_name"] or "no_tool",
        "example/predicted_name": result["predicted_name"] or "no_tool",
        "example/decision_match": int(result["decision_match"]),
        "example/tool_name_match": int(result["tool_name_match"]),
        "example/argument_judge_score": result["argument_judge_score"],
        "example/argument_judge_pass": int(result["argument_judge_pass"]),
        "example/exact_match": int(result["exact_match"]),
    }
    for key, value in metrics.items():
        payload[f"running/{key}"] = value
    run.log(payload, step=step_index)


def _evaluate_prediction(
    entry: dict[str, Any],
    predicted_name: str | None,
    argument_judge_pass: bool,
) -> dict[str, bool]:
    expected = entry.get("expected_tool_call")
    if expected is None:
        no_tool = predicted_name is None
        return {
            "decision_match": no_tool,
            "tool_name_match": no_tool,
            "exact_match": no_tool,
        }

    expected_name = expected["name"]
    tool_name_match = predicted_name == expected_name
    return {
        "decision_match": predicted_name is not None,
        "tool_name_match": tool_name_match,
        "exact_match": tool_name_match and argument_judge_pass,
    }


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return normalized


def _candidate_completion_urls(base_url: str) -> list[str]:
    normalized = _normalize_base_url(base_url)
    candidates = [f"{normalized}/chat/completions"]

    if normalized.endswith("/v1"):
        root = normalized[: -len("/v1")]
        if root:
            candidates.append(f"{root}/chat/completions")
    else:
        candidates.insert(0, f"{normalized}/v1/chat/completions")

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            ordered.append(candidate)
            seen.add(candidate)
    return ordered


def _candidate_models_urls(base_url: str) -> list[str]:
    normalized = _normalize_base_url(base_url)
    candidates = [f"{normalized}/models"]
    if normalized.endswith("/v1"):
        root = normalized[: -len("/v1")]
        if root:
            candidates.append(f"{root}/models")
    else:
        candidates.insert(0, f"{normalized}/v1/models")

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            ordered.append(candidate)
            seen.add(candidate)
    return ordered


def _describe_base_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    path = parts.path or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _ensure_endpoint_available(client: httpx.Client, base_url: str) -> str:
    model_urls = _candidate_models_urls(base_url)
    completion_urls = _candidate_completion_urls(base_url)

    for model_url, completion_url in zip(model_urls, completion_urls, strict=False):
        try:
            response = client.get(model_url, timeout=30.0)
        except httpx.HTTPError:
            continue
        if response.status_code == 200:
            return completion_url

    errors = []
    for model_url in model_urls:
        try:
            response = client.get(model_url, timeout=30.0)
            errors.append(f"{model_url} -> HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            errors.append(f"{model_url} -> {exc.__class__.__name__}")

    raise RuntimeError(
        "Could not find an OpenAI-compatible models endpoint for the provided base URL "
        f"{_describe_base_url(base_url)}. Tried: {', '.join(errors)}. "
        "If you passed your backend API URL by mistake, point this script at the raw vLLM server instead, "
        "for example `http://localhost:8080/v1`."
    )


def _allocate_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _spawn_local_vllm_server(
    *,
    model_ref: str,
    served_model_name: str,
    host: str,
    port: int,
    gpu_memory_utilization: float,
    max_model_len: int,
    max_num_seqs: int,
    tool_call_parser: str,
    log_path: Path,
) -> subprocess.Popen[str]:
    command = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--host",
        host,
        "--port",
        str(port),
        "--model",
        model_ref,
        "--served-model-name",
        served_model_name,
        "--gpu-memory-utilization",
        str(gpu_memory_utilization),
        "--max-model-len",
        str(max_model_len),
        "--max-num-seqs",
        str(max_num_seqs),
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        tool_call_parser,
    ]

    log_handle = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
    )


def _read_log_excerpt(log_path: Path, max_chars: int = 4000) -> str:
    if not log_path.exists():
        return "(no log file created)"
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return "(log file is empty)"
    return text[-max_chars:]


def _wait_for_server(
    base_url: str,
    timeout_seconds: float,
    process: subprocess.Popen[str] | None = None,
    log_path: Path | None = None,
) -> str:
    deadline = time.time() + timeout_seconds
    last_error: str | None = None

    with httpx.Client() as client:
        while time.time() < deadline:
            if process is not None:
                return_code = process.poll()
                if return_code is not None:
                    log_excerpt = _read_log_excerpt(log_path) if log_path is not None else "(no logs available)"
                    raise RuntimeError(
                        "Local vLLM server exited before becoming ready "
                        f"(exit code {return_code}). Startup log tail:\n{log_excerpt}"
                    )
            try:
                return _ensure_endpoint_available(client, base_url)
            except Exception as exc:
                last_error = str(exc)
                time.sleep(2)

    if process is not None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    log_suffix = ""
    if log_path is not None:
        log_suffix = f"\nStartup log tail:\n{_read_log_excerpt(log_path)}"
    raise RuntimeError(
        "Timed out waiting for the local vLLM server to become ready. "
        f"Last error: {last_error}{log_suffix}"
    )


def _call_model(
    client: httpx.Client,
    *,
    completions_url: str,
    model: str,
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = client.post(completions_url, json=payload, timeout=120.0)
    if response.status_code == 400 and "tool_choice" in response.text:
        payload.pop("tool_choice", None)
        response = client.post(completions_url, json=payload, timeout=120.0)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=None,
        help="Existing OpenAI-compatible vLLM base URL. If omitted, the script launches a local vLLM server.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Served model name reported to the OpenAI-compatible endpoint.",
    )
    parser.add_argument(
        "--model-ref",
        default=None,
        help="Model path or HF repo passed to local vLLM when spawning a server. Defaults to `--model`.",
    )
    parser.add_argument(
        "--dataset-path",
        default=str(DEFAULT_DATASET_PATH),
        help="Path to the synthetic tool-calling benchmark JSON.",
    )
    parser.add_argument("--sample-size", type=int, default=25, help="Number of examples to evaluate.")
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed for reproducible slices.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--host", default="127.0.0.1", help="Host for the local vLLM server.")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for the local vLLM server. Use 0 to auto-select a free port.",
    )
    parser.add_argument("--startup-timeout", type=float, default=180.0, help="Seconds to wait for local vLLM readiness.")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.7)
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--max-num-seqs", type=int, default=4)
    parser.add_argument("--tool-call-parser", default="hermes")
    parser.add_argument(
        "--output",
        default="data/reports/tool_calling_group_outings_synthetic_25.json",
        help="Path for the evaluation summary JSON.",
    )
    parser.add_argument("--wandb-project", default=None, help="W&B project name. Falls back to WANDB_PROJECT.")
    parser.add_argument("--wandb-entity", default=None, help="W&B entity/team. Falls back to WANDB_ENTITY.")
    parser.add_argument("--wandb-run-name", default=None, help="Optional W&B run name.")
    parser.add_argument("--wandb-group", default=None, help="Optional W&B run group.")
    parser.add_argument("--wandb-tags", nargs="*", default=None, help="Optional W&B tags.")
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Model used for argument judging. Defaults to the benchmark model.",
    )
    parser.add_argument(
        "--judge-threshold",
        type=float,
        default=DEFAULT_JUDGE_THRESHOLD,
        help="Judge score threshold for counting an argument pass.",
    )
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        default=180,
        help="Max tokens for the argument-judge completion.",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset_path)
    dataset = _load_dataset(dataset_path)
    benchmark_info = _build_benchmark_info(dataset)
    examples = dataset["examples"]
    if args.sample_size > len(examples):
        raise ValueError(f"Requested {args.sample_size} examples but dataset only has {len(examples)} rows.")

    rng = random.Random(args.seed)
    sampled_entries = rng.sample(examples, args.sample_size)
    tools = dataset["tools"]

    local_process: subprocess.Popen[str] | None = None
    log_path: Path | None = None
    wandb_run = _maybe_init_wandb(args)
    run_succeeded = False

    try:
        base_url = args.base_url
        if base_url is None:
            port = args.port or _allocate_free_port(args.host)
            base_url = f"http://{args.host}:{port}/v1"
            model_ref = args.model_ref or args.model
            log_path = Path(tempfile.gettempdir()) / f"evaluate_tool_calling_synthetic_vllm_{port}.log"
            print(f"Starting local vLLM server for model ref: {model_ref}")
            print(f"Using local port: {port}")
            print(f"vLLM startup log: {log_path}")
            local_process = _spawn_local_vllm_server(
                model_ref=model_ref,
                served_model_name=args.model,
                host=args.host,
                port=port,
                gpu_memory_utilization=args.gpu_memory_utilization,
                max_model_len=args.max_model_len,
                max_num_seqs=args.max_num_seqs,
                tool_call_parser=args.tool_call_parser,
                log_path=log_path,
            )
            try:
                completions_url = _wait_for_server(
                    base_url,
                    args.startup_timeout,
                    process=local_process,
                    log_path=log_path,
                )
            except Exception:
                if local_process.poll() is None:
                    local_process.kill()
                    local_process.wait(timeout=10)
                raise
        else:
            with httpx.Client() as client:
                completions_url = _ensure_endpoint_available(client, base_url)

        if wandb_run is not None:
            wandb_run.config.update(
                {
                    "base_url": base_url,
                    "completions_url": completions_url,
                    "dataset_name": dataset.get("name"),
                    "format_version": dataset.get("format_version"),
                    "benchmark_info": benchmark_info,
                },
                allow_val_change=True,
            )

        results: list[dict[str, Any]] = []
        decision_hits = 0
        no_tool_hits = 0
        tool_name_hits = 0
        exact_hits = 0
        predicted_tool_calls = 0
        expected_tool_call_examples = 0
        expected_no_tool_examples = 0
        argument_score_total = 0.0
        argument_passes = 0
        judge_model = args.judge_model or args.model

        with httpx.Client() as client:
            print(f"Using completions endpoint: {completions_url}")
            print(f"Dataset: {dataset.get('name')} ({args.sample_size} samples)")
            print(
                "Benchmark info: "
                f"{benchmark_info['total_examples']} total examples, "
                f"{benchmark_info['abstain_examples']} abstain examples, "
                f"tool mix={_canonical_json(benchmark_info['expected_tool_distribution'])}"
            )
            for index, entry in enumerate(sampled_entries, start=1):
                question = _extract_messages(dataset, entry)[-1]["content"]
                response = _call_model(
                    client,
                    completions_url=completions_url,
                    model=args.model,
                    messages=_extract_messages(dataset, entry),
                    tools=tools,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                )

                predicted_name, predicted_arguments, raw_arguments = _extract_prediction(response)
                predicted_tool_calls += int(predicted_name is not None)

                expected = entry.get("expected_tool_call")
                if expected is None:
                    judge_result = {
                        "score": None,
                        "pass": predicted_name is None,
                        "verdict": "not_applicable",
                        "rationale": "Argument judge is only applied to examples that expect a tool call.",
                    }
                else:
                    expected_tool_call_examples += 1
                    judge_result = _judge_argument_match(
                        client,
                        completions_url=completions_url,
                        judge_model=judge_model,
                        question=question,
                        expected_tool_name=expected["name"],
                        expected_arguments=expected.get("arguments") or {},
                        expected_argument_contains=expected.get("argument_contains") or {},
                        predicted_name=predicted_name,
                        predicted_arguments=predicted_arguments,
                        raw_arguments=raw_arguments,
                        max_tokens=args.judge_max_tokens,
                    )
                    judge_result["pass"] = bool(judge_result["score"] >= args.judge_threshold)
                    argument_score_total += float(judge_result["score"])
                    argument_passes += int(judge_result["pass"])

                evaluation = _evaluate_prediction(entry, predicted_name, judge_result["pass"])
                decision_hits += int(evaluation["decision_match"])
                exact_hits += int(evaluation["exact_match"])
                if expected is None:
                    expected_no_tool_examples += 1
                    no_tool_hits += int(evaluation["exact_match"])
                else:
                    tool_name_hits += int(evaluation["tool_name_match"])

                result = {
                    "id": entry["id"],
                    "category": entry.get("category"),
                    "difficulty": entry.get("difficulty"),
                    "group_profile": entry.get("group_profile"),
                    "question": question,
                    "expected_tool_name": expected.get("name") if expected else None,
                    "expected_arguments": expected.get("arguments", {}) if expected else {},
                    "expected_argument_contains": expected.get("argument_contains", {}) if expected else {},
                    "predicted_name": predicted_name,
                    "predicted_arguments": predicted_arguments,
                    "raw_arguments": raw_arguments,
                    "decision_match": evaluation["decision_match"],
                    "tool_name_match": evaluation["tool_name_match"],
                    "argument_judge_score": judge_result["score"],
                    "argument_judge_pass": judge_result["pass"],
                    "argument_judge_verdict": judge_result["verdict"],
                    "argument_judge_rationale": judge_result["rationale"],
                    "exact_match": evaluation["exact_match"],
                    "tool_call_count": len(_extract_tool_calls(response)),
                }
                results.append(result)

                running_metrics = _compute_running_metrics(
                    seen=index,
                    decision_hits=decision_hits,
                    no_tool_hits=no_tool_hits,
                    tool_name_hits=tool_name_hits,
                    exact_hits=exact_hits,
                    predicted_tool_calls=predicted_tool_calls,
                    expected_tool_call_examples=expected_tool_call_examples,
                    expected_no_tool_examples=expected_no_tool_examples,
                    argument_score_total=argument_score_total,
                    argument_passes=argument_passes,
                )
                if wandb_run is not None:
                    _log_wandb_step(wandb_run, step_index=index, result=result, metrics=running_metrics)

        summary = {
            "benchmark": "synthetic_group_outings_tool_calling",
            "dataset_name": dataset.get("name"),
            "format_version": dataset.get("format_version"),
            "dataset_path": str(dataset_path.resolve()),
            "benchmark_info": benchmark_info,
            "sample_size": args.sample_size,
            "seed": args.seed,
            "model": args.model,
            "judge_model": judge_model,
            "judge_threshold": args.judge_threshold,
            "base_url": base_url,
            "expected_tool_call_examples": expected_tool_call_examples,
            "expected_no_tool_examples": expected_no_tool_examples,
            "decision_accuracy": decision_hits / args.sample_size,
            "no_tool_accuracy": (
                no_tool_hits / expected_no_tool_examples if expected_no_tool_examples else 0.0
            ),
            "tool_name_accuracy": (
                tool_name_hits / expected_tool_call_examples if expected_tool_call_examples else 0.0
            ),
            "argument_judge_score_mean": (
                argument_score_total / expected_tool_call_examples if expected_tool_call_examples else 0.0
            ),
            "argument_judge_pass_rate": (
                argument_passes / expected_tool_call_examples if expected_tool_call_examples else 0.0
            ),
            "exact_match_accuracy": exact_hits / args.sample_size,
            "predicted_tool_rate": predicted_tool_calls / args.sample_size,
            "results": results,
        }

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        if wandb_run is not None:
            _log_wandb_results(wandb_run, summary, output_path)

        print(f"Benchmark: {summary['benchmark']}")
        print(f"Dataset: {summary['dataset_name']}")
        print(f"Model: {args.model}")
        print(f"Sample size: {args.sample_size}")
        print(f"Decision accuracy: {summary['decision_accuracy']:.2%}")
        print(f"No-tool accuracy: {summary['no_tool_accuracy']:.2%}")
        print(f"Tool name accuracy: {summary['tool_name_accuracy']:.2%}")
        print(f"Argument judge score mean: {summary['argument_judge_score_mean']:.3f}")
        print(f"Argument judge pass rate: {summary['argument_judge_pass_rate']:.2%}")
        print(f"Exact match accuracy: {summary['exact_match_accuracy']:.2%}")
        print(f"Saved summary: {output_path}")

        failures = [item for item in results if not item["exact_match"]]
        if failures:
            print("\nFirst 5 failures:")
            for failure in failures[:5]:
                print(
                    f"- {failure['id']}: expected {failure['expected_tool_name']} "
                    f"{_canonical_json(failure['expected_arguments'])} "
                    f"{_canonical_json(failure['expected_argument_contains'])}, got "
                    f"{failure['predicted_name']} "
                    f"{_canonical_json(failure['predicted_arguments']) if failure['predicted_arguments'] is not None else failure['raw_arguments']} "
                    f"(judge_score={failure['argument_judge_score']}, verdict={failure['argument_judge_verdict']})"
                )

        run_succeeded = True
    except Exception:
        if wandb_run is not None:
            wandb_run.summary["status"] = "failed"
        raise
    finally:
        if local_process is not None:
            local_process.terminate()
            try:
                local_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                local_process.kill()
                local_process.wait(timeout=15)
        if wandb_run is not None:
            wandb_run.summary["status"] = "completed" if run_succeeded else "failed"
            wandb_run.finish(exit_code=0 if run_succeeded else 1)


if __name__ == "__main__":
    main()

"""Synthetic slice evaluation harness for planner JSON-output quality and parity."""

import argparse
import json
import os
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

PRICE_LEVELS = ["$", "$$", "$$$"]
CATEGORIES = [
    "pizza",
    "thai",
    "mexican",
    "sushi",
    "bbq",
    "salad",
    "ramen",
    "coffee",
    "museum",
    "bowling",
    "karaoke",
    "park",
    "hike",
]


def budget_allows(price: str, budget_tier: str) -> bool:
    if budget_tier == "low":
        return price in ["$", "$$"]
    if budget_tier == "med":
        return price in ["$", "$$", "$$$"]
    return True


def make_venues(
    city_tier: str,
    budget_tier: str,
    distance_bucket: str,
) -> List[Dict[str, Any]]:
    base_n = {"big": 18, "mid": 10, "small": 5}[city_tier]
    venues = []

    for _ in range(base_n):
        cat = random.choice(CATEGORIES)
        price = random.choice(PRICE_LEVELS)

        if distance_bucket == "0-5":
            dist = round(random.uniform(0.2, 4.9), 1)
        elif distance_bucket == "5-15":
            dist = round(random.uniform(5.0, 14.9), 1)
        else:
            dist = round(random.uniform(15.0, 29.9), 1)

        has_hours = True
        if city_tier == "small" and random.random() < 0.35:
            has_hours = False

        if city_tier == "small" and budget_tier == "low" and random.random() < 0.40:
            price = "$$$"

        venues.append(
            {
                "name": f"{cat.title()} Spot {random.randint(1, 99)}",
                "price": price,
                "distance_miles": dist,
                "categories": [cat],
                "has_hours": has_hours,
            },
        )
    return venues


def generate_sample() -> Dict[str, Any]:
    city_tier = random.choices(["big", "mid", "small"], weights=[0.45, 0.35, 0.20])[0]
    budget_tier = random.choices(["low", "med", "high"], weights=[0.35, 0.50, 0.15])[0]
    distance_bucket = random.choices(
        ["0-5", "5-15", "15-30"],
        weights=[0.55, 0.30, 0.15],
    )[0]
    group_size = random.randint(2, 8)
    car_ownership_ratio = random.choice([0.0, 0.25, 0.5, 0.75, 1.0])
    dietary = random.choices(
        [[], ["vegan"], ["gluten_free"], ["vegan", "gluten_free"]],
        weights=[0.55, 0.20, 0.20, 0.05],
    )[0]
    vibe = random.sample(
        ["chill", "loud", "indoors", "outdoors", "active", "low_key"],
        k=2,
    )

    tool_snapshot = {"venues": make_venues(city_tier, budget_tier, distance_bucket)}
    return {
        "cycle_id": str(uuid.uuid4()),
        "city_tier": city_tier,
        "budget_tier": budget_tier,
        "car_ownership_ratio": car_ownership_ratio,
        "distance_bucket": distance_bucket,
        "group_size": group_size,
        "dietary": dietary,
        "vibe": vibe,
        "tool_snapshot": tool_snapshot,
    }


def bucket_car_ratio(x: float) -> str:
    if x == 0.0:
        return "none"
    if x <= 0.25:
        return "low"
    if x <= 0.75:
        return "mid"
    return "high"


SYSTEM_PROMPT = """You are Ketchup, a group hangout planner.

Return STRICT JSON only (no markdown, no extra text).
Pick exactly 3 venues from the provided list that best match constraints.
Respect budget and distance constraints.
Then propose a simple logistics plan.

Rules:
- If car_ownership_ratio == 0 and distance_bucket is 5-15 or 15-30, do NOT assign a driver.
  Instead suggest transit/meetpoint/rideshare.
- Otherwise, you may assign driver(s) but keep it simple.

Output schema:
{
 "options":[{"name":str,"why":str,"price":str,"distance_miles":number,"category":str}],
 "logistics":{"plan":str,"driver_assignment":[{"member_index":int,"drives":bool}]}
}
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "why": {"type": "string"},
                    "price": {"type": "string"},
                    "distance_miles": {"type": "number"},
                    "category": {"type": "string"},
                },
                "required": ["name", "why", "price", "distance_miles", "category"],
            },
        },
        "logistics": {
            "type": "object",
            "properties": {
                "plan": {"type": "string"},
                "driver_assignment": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "member_index": {"type": "integer"},
                            "drives": {"type": "boolean"},
                        },
                        "required": ["member_index", "drives"],
                    },
                },
            },
            "required": ["plan", "driver_assignment"],
        },
    },
    "required": ["options", "logistics"],
}


def build_user_prompt(sample: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "constraints": {
                "budget_tier": sample["budget_tier"],
                "distance_bucket": sample["distance_bucket"],
                "car_ownership_ratio": sample["car_ownership_ratio"],
                "dietary": sample["dietary"],
                "vibe": sample["vibe"],
                "group_size": sample["group_size"],
            },
            "venues": sample["tool_snapshot"]["venues"],
        },
    )


def parse_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        # Recover if the model wraps JSON in extra text.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None


def call_vllm_chat(
    session: requests.Session,
    base_url: str,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    use_schema: bool,
) -> Tuple[str, bool]:
    """Call chat completions and retry once without schema on schema-related 400."""
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if use_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "ketchup-plan", "schema": OUTPUT_SCHEMA},
        }

    r = session.post(url, json=payload, timeout=90)

    if r.status_code != 200 and use_schema:
        body = r.text[:800]
        print(
            f"[WARN] Non-200 with schema (HTTP {r.status_code}). Retrying without schema. Body: {body}",
        )
        payload.pop("response_format", None)
        r2 = session.post(url, json=payload, timeout=90)
        if r2.status_code != 200:
            print(f"[ERROR] HTTP {r2.status_code} Body: {r2.text[:800]}")
            r2.raise_for_status()
        data2 = r2.json()
        return (
            data2["choices"][0]["message"]["content"],
            False,
        )

    if r.status_code != 200:
        print(f"[ERROR] HTTP {r.status_code} Body: {r.text[:800]}")
        r.raise_for_status()

    data = r.json()
    return data["choices"][0]["message"]["content"], use_schema


def score(sample: Dict[str, Any], out: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = {
        "json_valid": 0,
        "options_count_ok": 0,
        "budget_compliance": 0.0,
        "distance_compliance": 0.0,
        "logistics_feasible": 0,
    }
    if out is None:
        return result

    options = out.get("options", [])
    logistics = out.get("logistics", {})

    result["json_valid"] = 1
    result["options_count_ok"] = (
        1 if isinstance(options, list) and len(options) == 3 else 0
    )

    budget_tier = sample["budget_tier"]
    dist_bucket = sample["distance_bucket"]
    max_dist = {"0-5": 5.0, "5-15": 15.0, "15-30": 30.0}[dist_bucket]

    bud_ok = 0
    dist_ok = 0
    for opt in options[:3]:
        price = str(opt.get("price", ""))
        try:
            dist = float(opt.get("distance_miles", 999))
        except Exception:
            dist = 999.0

        if budget_allows(price, budget_tier):
            bud_ok += 1
        if dist <= max_dist:
            dist_ok += 1

    if isinstance(options, list) and len(options) >= 3:
        result["budget_compliance"] = bud_ok / 3.0
        result["distance_compliance"] = dist_ok / 3.0

    # Basic logistics feasibility heuristic for scoring.
    car_ratio = sample["car_ownership_ratio"]
    is_far = sample["distance_bucket"] in ["5-15", "15-30"]
    plan = (logistics.get("plan") or "").lower()

    if car_ratio == 0.0 and is_far:
        if any(
            k in plan
            for k in [
                "transit",
                "subway",
                "bus",
                "meet",
                "meetpoint",
                "rideshare",
                "uber",
                "lyft",
            ]
        ):
            result["logistics_feasible"] = 1
    else:
        result["logistics_feasible"] = 1

    return result


def print_overall(df: pd.DataFrame) -> None:
    cols = [
        "json_valid",
        "options_count_ok",
        "budget_compliance",
        "distance_compliance",
        "logistics_feasible",
    ]
    print("\n=== Overall ===")
    print(df[cols].mean())


def print_slices(df: pd.DataFrame) -> None:
    print("\n=== Slice: city_tier x budget_tier ===")
    g = (
        df.groupby(["city_tier", "budget_tier"])
        .agg(
            n=("cycle_id", "count"),
            json_valid=("json_valid", "mean"),
            budget_compliance=("budget_compliance", "mean"),
            logistics_feasible=("logistics_feasible", "mean"),
        )
        .reset_index()
    )
    print(
        g.sort_values(["budget_compliance", "logistics_feasible"]).to_string(
            index=False,
        ),
    )

    print("\n=== Slice: distance_bucket x car_ratio_bucket ===")
    g2 = (
        df.groupby(["distance_bucket", "car_ratio_bucket"])
        .agg(
            n=("cycle_id", "count"),
            logistics_feasible=("logistics_feasible", "mean"),
            distance_compliance=("distance_compliance", "mean"),
        )
        .reset_index()
    )
    print(
        g2.sort_values(["logistics_feasible", "distance_compliance"]).to_string(
            index=False,
        ),
    )

    print("\n=== Worst slices (n>=8) by budget_compliance ===")
    g3 = (
        df.groupby(["city_tier", "budget_tier", "distance_bucket", "car_ratio_bucket"])
        .agg(
            n=("cycle_id", "count"),
            budget_compliance=("budget_compliance", "mean"),
            json_valid=("json_valid", "mean"),
            logistics_feasible=("logistics_feasible", "mean"),
        )
        .reset_index()
    )
    worst = g3[g3["n"] >= 8].sort_values("budget_compliance").head(12)
    if len(worst) == 0:
        print("(none with n>=8; reduce threshold or increase N_SAMPLES)")
    else:
        print(worst.to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.getenv("VLLM_BASE_URL", "http://localhost:18000"),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("VLLM_MODEL", "Qwen/Qwen3-4B-Instruct-2507"),
    )
    parser.add_argument("--n", type=int, default=int(os.getenv("N_SAMPLES", "200")))
    parser.add_argument("--seed", type=int, default=int(os.getenv("SEED", "25")))
    parser.add_argument(
        "--temperature",
        type=float,
        default=float(os.getenv("LLM_TEMPERATURE", "0.2")),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.getenv("MAX_TOKENS", "4096")),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=int(os.getenv("PROGRESS_EVERY", "1")),
    )
    parser.add_argument(
        "--no-schema",
        action="store_true",
        help="Disable json_schema response_format",
    )
    parser.add_argument(
        "--save-csv",
        default=os.getenv("SAVE_CSV", ""),
        help="Path to save per-sample results CSV",
    )
    parser.add_argument(
        "--print-failures",
        type=int,
        default=int(os.getenv("PRINT_FAILURES", "2")),
        help="Print raw model outputs for first N parse failures",
    )
    args = parser.parse_args()

    random.seed(args.seed)

    print("=== Config ===")
    print(f"base_url: {args.base_url}")
    print(f"model:    {args.model}")
    print(f"N:        {args.n}")
    print(f"schema:   {'OFF' if args.no_schema else 'ON (with auto-fallback)'}")
    print(f"progress: every {args.progress_every}")
    print("=============\n")

    session = requests.Session()

    try:
        r = session.get(f"{args.base_url.rstrip('/')}/v1/models", timeout=10)
        if r.status_code == 200:
            models = r.json().get("data", [])
            print(f"[INFO] /v1/models reachable. {len(models)} model(s) advertised.")
        else:
            print(
                f"[INFO] /v1/models returned HTTP {r.status_code}. Continuing anyway.",
            )
    except Exception as e:
        print(f"[WARN] Could not reach /v1/models: {repr(e)}. Continuing anyway.")

    rows = []
    t0 = time.time()
    ok_calls = 0
    err_calls = 0
    schema_on = not args.no_schema
    parse_fail_printed = 0

    for i in range(1, args.n + 1):
        sample = generate_sample()
        user_prompt = build_user_prompt(sample)

        try:
            txt, schema_on = call_vllm_chat(
                session=session,
                base_url=args.base_url,
                model=args.model,
                system=SYSTEM_PROMPT,
                user=user_prompt,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                use_schema=schema_on,
            )
            out = parse_json_safe(txt)
            if out is None and parse_fail_printed < args.print_failures:
                print("\n[DEBUG] Parse failure raw output:")
                print(txt[:800])
                print("-----")
                parse_fail_printed += 1

            ok_calls += 1
        except Exception as e:
            out = None
            err_calls += 1
            if err_calls <= 3:
                print(f"[ERROR] Call failed (showing first 3). {repr(e)}")

        metrics = score(sample, out)

        rows.append(
            {
                "cycle_id": sample["cycle_id"],
                "city_tier": sample["city_tier"],
                "budget_tier": sample["budget_tier"],
                "distance_bucket": sample["distance_bucket"],
                "group_size": sample["group_size"],
                "car_ratio_bucket": bucket_car_ratio(sample["car_ownership_ratio"]),
                "dietary_flag": "yes" if len(sample["dietary"]) else "no",
                **metrics,
            },
        )

        if i % args.progress_every == 0 or i == args.n:
            df_tmp = pd.DataFrame(rows)
            means = df_tmp[
                ["json_valid", "budget_compliance", "logistics_feasible"]
            ].mean()
            elapsed = time.time() - t0
            print(
                f"[PROGRESS] {i}/{args.n} | ok={ok_calls} err={err_calls} | "
                f"json_valid={means['json_valid']:.2f} "
                f"budget={means['budget_compliance']:.2f} "
                f"logistics={means['logistics_feasible']:.2f} | "
                f"elapsed={elapsed:.1f}s | schema={'ON' if schema_on else 'OFF'}",
            )

    df = pd.DataFrame(rows)

    print_overall(df)
    print_slices(df)

    if args.save_csv:
        df.to_csv(args.save_csv, index=False)
        print(f"\n[INFO] Saved results to: {args.save_csv}")


if __name__ == "__main__":
    main()

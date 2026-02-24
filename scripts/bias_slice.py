#!/usr/bin/env python3
"""Generate a markdown bias-slicing report from synthetic evaluation results."""
import argparse

import numpy as np
import pandas as pd


def bootstrap_ci(values, n_boot=5000, alpha=0.05, seed=0):
    rng = np.random.default_rng(seed)
    vals = np.array(values)
    boots = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
    lo = np.quantile(boots, alpha / 2)
    hi = np.quantile(boots, 1 - alpha / 2)
    return float(lo), float(hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to results.csv")
    ap.add_argument(
        "--out",
        default="bias_slicing_report.md",
        help="Markdown report output path",
    )
    ap.add_argument(
        "--min_n",
        type=int,
        default=5,
        help="Minimum n for 'worst slice' table",
    )
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df["full_budget_ok"] = np.isclose(df["budget_compliance"], 1.0).astype(int)

    overall = df[
        [
            "json_valid",
            "options_count_ok",
            "budget_compliance",
            "distance_compliance",
            "logistics_feasible",
            "full_budget_ok",
        ]
    ].mean()
    overall_ci = bootstrap_ci(df["budget_compliance"])

    slice_city_budget = (
        df.groupby(["city_tier", "budget_tier"])
        .agg(
            n=("cycle_id", "count"),
            budget_compliance=("budget_compliance", "mean"),
            full_budget_ok=("full_budget_ok", "mean"),
            json_valid=("json_valid", "mean"),
        )
        .reset_index()
        .sort_values(["budget_compliance", "n"])
    )

    worst = slice_city_budget.iloc[0]
    worst_vals = df[
        (df.city_tier == worst["city_tier"]) & (df.budget_tier == worst["budget_tier"])
    ]["budget_compliance"]
    worst_ci = bootstrap_ci(worst_vals)

    print("\n=== Overall ===")
    print(overall)
    print(
        f"\nOverall budget_compliance 95% CI (bootstrap): [{overall_ci[0]:.3f}, {overall_ci[1]:.3f}]",
    )

    print("\n=== Slice: city_tier x budget_tier ===")
    print(
        slice_city_budget[
            ["city_tier", "budget_tier", "n", "budget_compliance", "full_budget_ok"]
        ].to_string(index=False),
    )

    g3 = (
        df.groupby(["city_tier", "budget_tier", "distance_bucket", "car_ratio_bucket"])
        .agg(
            n=("cycle_id", "count"),
            budget_compliance=("budget_compliance", "mean"),
            full_budget_ok=("full_budget_ok", "mean"),
        )
        .reset_index()
    )
    worst3 = g3[g3["n"] >= args.min_n].sort_values("budget_compliance").head(10)

    report = f"""# Bias Slicing Eval Report (Synthetic Baseline)

_Data source:_ `{args.csv}`
_Rows (planning cycles):_ {len(df)}

## Overall metrics

{pd.DataFrame({"metric": overall.index, "value": overall.values}).to_markdown(index=False)}

Overall `budget_compliance` bootstrap 95% CI: **[{overall_ci[0]:.3f}, {overall_ci[1]:.3f}]**

## Slice: city_tier x budget_tier

{slice_city_budget[["city_tier","budget_tier","n","budget_compliance","full_budget_ok"]].to_markdown(index=False)}

### Worst slice

- Slice: **{worst["city_tier"]} x {worst["budget_tier"]}** (n={int(worst["n"])})
- Mean `budget_compliance`: **{worst["budget_compliance"]:.3f}** (overall {overall["budget_compliance"]:.3f})
- Mean `full_budget_ok`: **{worst["full_budget_ok"]:.3f}** (overall {overall["full_budget_ok"]:.3f})
- Slice `budget_compliance` bootstrap 95% CI: **[{worst_ci[0]:.3f}, {worst_ci[1]:.3f}]**

## Worst intersection slices (min_n={args.min_n})

{(worst3.to_markdown(index=False) if len(worst3) else "(none; increase N or lower min_n)")}

## Suggested mitigations

This baseline indicates constraint compliance varies across slices.

1. Prefilter candidate venues by budget before generation.
2. Add validate-then-repair pass for budget violations.
3. Add deterministic low-cost fallback when compliant venue supply is sparse.

Trade-offs:
- Repair adds latency and model cost.
- Aggressive prefiltering can reduce option diversity.
"""
    with open(args.out, "w") as f:
        f.write(report)

    print(f"\n[INFO] Wrote report: {args.out}")


if __name__ == "__main__":
    main()

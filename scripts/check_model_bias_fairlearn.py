#!/usr/bin/env python3
"""Check model bias with Fairlearn MetricFrame over synthetic eval outputs."""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from fairlearn.metrics import MetricFrame, selection_rate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="data/reports/model_bias_results.csv")
    parser.add_argument(
        "--slice",
        default="city_tier,budget_tier",
        help="Comma-separated columns used to define slices.",
    )
    parser.add_argument(
        "--success-rule",
        default="full_budget_ok",
        choices=["full_budget_ok", "budget_ge_0.67", "budget_ge_1.0"],
        help="Rule used to convert budget performance into a binary success label.",
    )
    parser.add_argument("--min-n", type=int, default=5)
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    if args.success_rule in ["full_budget_ok", "budget_ge_1.0"]:
        outcomes = np.isclose(df["budget_compliance"], 1.0).astype(int)
        rule_description = "success = (budget_compliance == 1.0) [all 3 in-budget]"
    else:
        outcomes = (df["budget_compliance"] >= 2 / 3).astype(int)
        rule_description = "success = (budget_compliance >= 0.67) [>=2 of 3 in-budget]"

    slice_cols = [col.strip() for col in args.slice.split(",") if col.strip()]
    for column in slice_cols:
        if column not in df.columns:
            raise ValueError(f"Slice column '{column}' not present in CSV columns: {list(df.columns)}")

    sensitive_features = df[slice_cols].astype(str).agg(" | ".join, axis=1)
    metric_frame = MetricFrame(
        metrics={"success_rate": selection_rate},
        y_true=outcomes,
        y_pred=outcomes,
        sensitive_features=sensitive_features,
    )

    by_group = metric_frame.by_group
    if isinstance(by_group, pd.Series):
        group_rates = by_group.rename("success_rate").to_frame()
    else:
        group_rates = by_group.copy()
        if group_rates.shape[1] == 1 and group_rates.columns[0] != "success_rate":
            group_rates = group_rates.rename(columns={group_rates.columns[0]: "success_rate"})

    counts = sensitive_features.value_counts().rename("n").to_frame()
    group_budget = df.groupby(sensitive_features)["budget_compliance"].mean().rename("mean_budget_compliance").to_frame()
    report = counts.join(group_rates).join(group_budget).reset_index().rename(columns={"index": "slice"})
    report = report[report["n"] >= args.min_n].copy().sort_values(["success_rate", "mean_budget_compliance", "n"])

    overall_success = float(outcomes.mean())
    overall_budget = float(df["budget_compliance"].mean())

    if len(report) > 0:
        min_rate = float(report["success_rate"].min())
        max_rate = float(report["success_rate"].max())
        diff = max_rate - min_rate
        ratio = (min_rate / max_rate) if max_rate > 0 else np.nan
    else:
        diff = np.nan
        ratio = np.nan

    print("\n=== Fairlearn Slicing Report ===")
    print(f"CSV: {args.csv}")
    print(f"Slices: {slice_cols}")
    print(f"Success rule: {rule_description}")
    print(f"Overall success_rate: {overall_success:.3f}")
    print(f"Overall mean_budget_compliance: {overall_budget:.3f}")
    print(f"Disparity (success_rate): difference={diff:.3f}, ratio={ratio:.3f} (min/max)")

    print(f"\n=== Per-slice metrics (min_n={args.min_n}) ===")
    print(report.to_string(index=False))

    if len(report) > 0:
        worst = report.iloc[0]
        print("\n=== Worst slice ===")
        print(worst.to_string())


if __name__ == "__main__":
    main()

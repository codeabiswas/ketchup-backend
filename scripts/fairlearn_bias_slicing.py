import argparse

import numpy as np
import pandas as pd
from fairlearn.metrics import MetricFrame, selection_rate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="results.csv")
    ap.add_argument(
        "--slice",
        default="city_tier,budget_tier",
        help="Comma-separated columns to define group slices",
    )
    ap.add_argument(
        "--success_rule",
        default="full_budget_ok",
        choices=["full_budget_ok", "budget_ge_0.67", "budget_ge_1.0"],
        help="How to convert budget performance into a binary success",
    )
    ap.add_argument("--min_n", type=int, default=5)
    args = ap.parse_args()

    df = pd.read_csv(args.csv)

    # ---- Define binary success label from your eval metrics ----
    if args.success_rule in ["full_budget_ok", "budget_ge_1.0"]:
        # success = all 3 options in-budget
        y = (np.isclose(df["budget_compliance"], 1.0)).astype(int)
        rule_desc = "success = (budget_compliance == 1.0) [all 3 in-budget]"
    else:
        # success = >=2 out of 3 options in-budget
        y = (df["budget_compliance"] >= 2 / 3).astype(int)
        rule_desc = "success = (budget_compliance >= 0.67) [>=2 of 3 in-budget]"

    # In this setting, we treat success as the key outcome we want parity on.
    y_true = y.copy()
    y_pred = y.copy()

    # ---- Build slice key ----
    slice_cols = [c.strip() for c in args.slice.split(",") if c.strip()]
    for c in slice_cols:
        if c not in df.columns:
            raise ValueError(
                f"Slice column '{c}' not in CSV columns: {list(df.columns)}",
            )

    sf = df[slice_cols].astype(str).agg(" | ".join, axis=1)  # sensitive_features label

    # ---- Fairlearn MetricFrame ----
    mf = MetricFrame(
        metrics={"success_rate": selection_rate},
        y_true=y_true,
        y_pred=y_pred,
        sensitive_features=sf,
    )

    # mf.by_group can be Series OR DataFrame depending on Fairlearn/pandas versions
    by_group = mf.by_group
    if isinstance(by_group, pd.Series):
        group_rates = by_group.rename("success_rate").to_frame()
    else:
        group_rates = by_group.copy()
        # It should have a single column named "success_rate" because we used that key above,
        # but to be safe:
        if group_rates.shape[1] == 1 and group_rates.columns[0] != "success_rate":
            group_rates = group_rates.rename(
                columns={group_rates.columns[0]: "success_rate"},
            )

    # Group sizes + continuous metric per group
    counts = sf.value_counts().rename("n").to_frame()
    group_budget = (
        df.groupby(sf)["budget_compliance"]
        .mean()
        .rename("mean_budget_compliance")
        .to_frame()
    )

    report = (
        counts.join(group_rates)
        .join(group_budget)
        .reset_index()
        .rename(columns={"index": "slice"})
    )
    report_stable = report[report["n"] >= args.min_n].copy()
    report_stable = report_stable.sort_values(
        ["success_rate", "mean_budget_compliance", "n"],
    )

    overall_success = float(y.mean())
    overall_budget = float(df["budget_compliance"].mean())

    # ---- Disparity summary (Fairlearn-style) ----
    if len(report_stable) > 0:
        min_rate = float(report_stable["success_rate"].min())
        max_rate = float(report_stable["success_rate"].max())
        diff = max_rate - min_rate
        ratio = (min_rate / max_rate) if max_rate > 0 else np.nan
    else:
        min_rate = max_rate = diff = ratio = np.nan

    print("\n=== Fairlearn Slicing Report ===")
    print(f"CSV: {args.csv}")
    print(f"Slices: {slice_cols}")
    print(f"Success rule: {rule_desc}")
    print(f"Overall success_rate: {overall_success:.3f}")
    print(f"Overall mean_budget_compliance: {overall_budget:.3f}")
    print(
        f"Disparity (success_rate): difference={diff:.3f}, ratio={ratio:.3f} (min/max)",
    )

    print(f"\n=== Per-slice metrics (min_n={args.min_n}) ===")
    print(report_stable.to_string(index=False))

    if len(report_stable) > 0:
        worst = report_stable.iloc[0]
        print("\n=== Worst slice ===")
        print(worst.to_string())


if __name__ == "__main__":
    main()

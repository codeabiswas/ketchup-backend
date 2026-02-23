"""Detect bias across demographic slices in processed data."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipelines.bias_detection import BiasAnalyzer, BiasMitigationStrategy, DataSlicer


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    processed_dir = root / "data" / "processed"
    reports_dir = root / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    calendar_df = pd.read_csv(processed_dir / "calendar_processed.csv")

    if "availability_category" not in calendar_df.columns:
        calendar_df["availability_category"] = "unknown"

    if "selected" not in calendar_df.columns:
        calendar_df["selected"] = (
            calendar_df["availability_percentage"].fillna(0) >= 50
        ).astype(int)

    if "predicted_selected" not in calendar_df.columns:
        calendar_df["predicted_selected"] = calendar_df["selected"]

    slices = DataSlicer.slice_by_demographic(
        calendar_df,
        "availability_category",
    )

    bias_metrics = BiasAnalyzer.detect_bias_in_slices(
        slices,
        target_column="selected",
        prediction_column="predicted_selected",
        positive_label=1,
    )

    biased_slices = sorted({m.slice_name for m in bias_metrics if m.is_biased})
    mitigation_report = BiasMitigationStrategy.generate_mitigation_report(
        bias_metrics,
        biased_slices,
    )

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "bias_metrics": [
            {
                "slice": m.slice_name,
                "metric": m.metric_name,
                "value": float(m.value),
                "threshold": float(m.threshold),
                "is_biased": bool(m.is_biased),
            }
            for m in bias_metrics
        ],
        "mitigation_report": json.loads(
            json.dumps(
                mitigation_report,
                default=lambda x: (
                    bool(x)
                    if isinstance(x, (bool, np.bool_))
                    else float(x) if isinstance(x, (float, np.floating)) else str(x)
                ),
            ),
        ),
    }

    report_path = reports_dir / "bias_report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(f"Saved bias report to {report_path}")


if __name__ == "__main__":
    main()

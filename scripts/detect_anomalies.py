"""Detect anomalies in processed data and emit a report."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from pipelines.validation import AnomalyDetector, ValidationResult


def _summarize_result(result: ValidationResult) -> dict:
    return {
        "passed": bool(result.passed),
        "issue_count": int(result.issue_count),
        "issues": result.issues,
        "quality_level": result.quality_level.value,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    processed_dir = root / "data" / "processed"
    reports_dir = root / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    calendar_df = pd.read_csv(processed_dir / "calendar_processed.csv")

    calendar_missing = AnomalyDetector.detect_missing_values(calendar_df, 10.0)
    calendar_duplicates = AnomalyDetector.detect_duplicates(
        calendar_df,
        subset=["user_id"],
    )
    calendar_outliers = AnomalyDetector.detect_outliers(
        calendar_df,
        column="total_busy_hours",
        method="iqr",
    )

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "calendar": {
            "missing_values": _summarize_result(calendar_missing),
            "duplicates": _summarize_result(calendar_duplicates),
            "outliers": _summarize_result(calendar_outliers),
        },
    }

    report_path = reports_dir / "anomaly_report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(f"Saved anomaly report to {report_path}")


if __name__ == "__main__":
    main()

"""Validate processed data against schema and range rules."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipelines.validation import RangeValidator, SchemaValidator, ValidationResult


def _summarize_result(result: ValidationResult) -> dict:
    return {
        "passed": result.passed,
        "issue_count": result.issue_count,
        "issues": result.issues,
        "quality_level": result.quality_level.value,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    processed_dir = root / "data" / "processed"
    reports_dir = root / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    calendar_df = pd.read_csv(processed_dir / "calendar_processed.csv")

    if "reference_date" in calendar_df.columns:
        calendar_df["reference_date"] = pd.to_datetime(calendar_df["reference_date"])

    calendar_schema = {
        "user_id": np.object_,
        "reference_date": np.datetime64,
        "availability_percentage": np.floating,
        "num_busy_intervals": np.integer,
        "total_busy_hours": np.floating,
    }

    calendar_schema_result = SchemaValidator.validate_schema(
        calendar_df,
        calendar_schema,
    )
    calendar_required = SchemaValidator.validate_required_fields(
        calendar_df,
        ["user_id", "reference_date"],
    )

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "calendar": {
            "schema": _summarize_result(calendar_schema_result),
            "required_fields": _summarize_result(calendar_required),
        },
    }

    report_path = reports_dir / "validation_report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(f"Saved validation report to {report_path}")


if __name__ == "__main__":
    main()

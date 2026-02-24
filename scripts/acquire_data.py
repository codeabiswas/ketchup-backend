"""Acquire raw calendar data for the pipeline."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _ensure_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def _generate_calendar_data(user_count: int = 50) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    user_ids = [f"user_{i:03d}" for i in range(1, user_count + 1)]
    rng = np.random.default_rng(42)

    records = []
    for user_id in user_ids:
        availability_pct = float(rng.integers(10, 95))
        num_busy = int(rng.integers(1, 12))
        total_busy_hours = float(rng.uniform(2.0, 45.0))
        reference_date = now - timedelta(days=int(rng.integers(0, 30)))

        records.append(
            {
                "user_id": user_id,
                "availability_percentage": availability_pct,
                "num_busy_intervals": num_busy,
                "total_busy_hours": round(total_busy_hours, 2),
                "reference_date": reference_date.isoformat(),
            },
        )

    df = pd.DataFrame(records)

    if len(df) > 5:
        df.loc[2, "availability_percentage"] = np.nan
        df.loc[4, "reference_date"] = None

    return df


def main() -> None:
    try:
        root = Path(__file__).resolve().parents[1]
        raw_dir = root / "data" / "raw"
        metrics_dir = root / "data" / "metrics"
        _ensure_dirs(raw_dir, metrics_dir)

        calendar_df = _generate_calendar_data()

        calendar_path = raw_dir / "calendar_data.csv"
        calendar_df.to_csv(calendar_path, index=False)

        metrics = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "calendar_records": int(len(calendar_df)),
            "calendar_missing_values": int(calendar_df.isnull().sum().sum()),
        }

        metrics_path = metrics_dir / "acquisition_metrics.json"
        with metrics_path.open("w", encoding="utf-8") as handle:
            json.dump(metrics, handle, indent=2)

        logger.info("Saved calendar data to %s", calendar_path)
        logger.info("Saved metrics to %s", metrics_path)
    except Exception:
        logger.exception("Data acquisition stage failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

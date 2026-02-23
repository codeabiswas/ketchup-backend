"""Generate statistics and plots for processed datasets."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pipelines.validation import DataStatisticsGenerator


def _ensure_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def _save_distribution(values: pd.Series, output_path: Path) -> None:
    counts, bins = np.histogram(values.dropna(), bins=10)
    bins_labels = [f"{bins[i]:.2f}-{bins[i + 1]:.2f}" for i in range(len(bins) - 1)]
    df_plot = pd.DataFrame({"bins": bins_labels, "frequency": counts})
    df_plot.to_csv(output_path, index=False)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    processed_dir = root / "data" / "processed"
    stats_dir = root / "data" / "statistics"
    plots_dir = root / "data" / "analysis" / "plots"
    _ensure_dirs(stats_dir, plots_dir)

    calendar_df = pd.read_csv(processed_dir / "calendar_processed.csv")

    calendar_stats = DataStatisticsGenerator.generate_statistics(calendar_df)

    calendar_stats_path = stats_dir / "calendar_stats.json"

    DataStatisticsGenerator.save_statistics(calendar_stats, str(calendar_stats_path))

    if "availability_percentage" in calendar_df.columns:
        _save_distribution(
            calendar_df["availability_percentage"],
            plots_dir / "data_distribution.csv",
        )

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "calendar_records": int(len(calendar_df)),
        "calendar_stats_path": str(calendar_stats_path),
    }

    summary_path = stats_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print(f"Saved calendar stats to {calendar_stats_path}")
    print(f"Saved summary stats to {summary_path}")


if __name__ == "__main__":
    main()

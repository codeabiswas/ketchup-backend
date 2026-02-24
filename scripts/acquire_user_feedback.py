"""Generate synthetic user feedback data for DVC pipeline stage."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _generate_feedback(records: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(73)

    rows = []
    for idx in range(records):
        user_id = f"user_{(idx % 50) + 1:03d}"
        group_id = f"group_{(idx % 10) + 1:02d}"
        rating = int(rng.integers(1, 6))
        attended = bool(rng.integers(0, 2))
        comments = ["great", "good", "neutral", "bad", "excellent"]

        rows.append(
            {
                "feedback_id": f"fb_{idx + 1:04d}",
                "user_id": user_id,
                "group_id": group_id,
                "rating": rating,
                "attended": attended,
                "comment": comments[rating - 1],
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    return pd.DataFrame(rows)


def main() -> None:
    try:
        root = Path(__file__).resolve().parents[1]
        raw_dir = root / "data" / "raw"
        _ensure_dir(raw_dir)

        feedback_df = _generate_feedback()
        output_path = raw_dir / "user_feedback.csv"
        feedback_df.to_csv(output_path, index=False)

        logger.info("Saved user feedback data to %s", output_path)
    except Exception:
        logger.exception("User feedback acquisition stage failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

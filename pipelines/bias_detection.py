"""Bias slicing and mitigation reporting helpers for evaluation datasets."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BiasMetric:
    """Metric record for one slice and one fairness signal."""

    slice_name: str
    metric_name: str
    value: float
    threshold: float
    is_biased: bool


class DataSlicer:
    """Helpers for creating demographic slices from tabular datasets."""

    @staticmethod
    def slice_by_demographic(
        df: pd.DataFrame,
        demographic_column: str,
    ) -> Dict[str, pd.DataFrame]:
        slices = {}

        for value in df[demographic_column].unique():
            slice_df = df[df[demographic_column] == value]
            slices[f"{demographic_column}={value}"] = slice_df

            logger.info(
                f"Created slice {demographic_column}={value} "
                f"with {len(slice_df)} records",
            )

        return slices


class BiasAnalyzer:
    """Fairness metric calculations across demographic slices."""

    @staticmethod
    def calculate_statistical_parity(
        slices: Dict[str, pd.DataFrame],
        target_column: str,
        positive_label: Any,
    ) -> Dict[str, float]:
        parity_metrics = {}

        for slice_name, slice_df in slices.items():
            if len(slice_df) == 0:
                parity_metrics[slice_name] = 0
                continue

            positive_count = (slice_df[target_column] == positive_label).sum()
            selection_rate = positive_count / len(slice_df)
            parity_metrics[slice_name] = selection_rate

        logger.info(
            f"Calculated statistical parity for {len(slices)} slices: "
            f"{parity_metrics}",
        )

        return parity_metrics

    @staticmethod
    def calculate_equalized_odds(
        slices: Dict[str, pd.DataFrame],
        target_column: str,
        prediction_column: str,
        positive_label: Any,
    ) -> Dict[str, Dict[str, float]]:
        odds_metrics = {}

        for slice_name, slice_df in slices.items():
            if len(slice_df) == 0:
                odds_metrics[slice_name] = {"TPR": 0, "FPR": 0}
                continue

            positives = slice_df[slice_df[target_column] == positive_label]
            if len(positives) > 0:
                tpr = (positives[prediction_column] == positive_label).sum() / len(
                    positives,
                )
            else:
                tpr = 0

            negatives = slice_df[slice_df[target_column] != positive_label]
            if len(negatives) > 0:
                fpr = (negatives[prediction_column] == positive_label).sum() / len(
                    negatives,
                )
            else:
                fpr = 0

            odds_metrics[slice_name] = {"TPR": tpr, "FPR": fpr}

        logger.info(
            f"Calculated equalized odds for {len(slices)} slices",
        )

        return odds_metrics

    @staticmethod
    def detect_bias_in_slices(
        slices: Dict[str, pd.DataFrame],
        target_column: str,
        prediction_column: str = None,
        positive_label: Any = 1,
        thresholds: Dict[str, float] = None,
    ) -> List[BiasMetric]:
        bias_metrics = []
        thresholds = thresholds or {
            "selection_rate_std": 0.05,
            "tpr_std": 0.10,
            "fpr_std": 0.10,
        }

        selection_rates = BiasAnalyzer.calculate_statistical_parity(
            slices,
            target_column,
            positive_label,
        )

        rate_std = np.std(list(selection_rates.values()))
        for slice_name, rate in selection_rates.items():
            is_biased = rate_std > thresholds.get("selection_rate_std", 0.05)
            bias_metrics.append(
                BiasMetric(
                    slice_name=slice_name,
                    metric_name="selection_rate",
                    value=rate,
                    threshold=thresholds.get("selection_rate_std", 0.05),
                    is_biased=is_biased,
                ),
            )

        if prediction_column:
            odds = BiasAnalyzer.calculate_equalized_odds(
                slices,
                target_column,
                prediction_column,
                positive_label,
            )

            tpr_values = [v["TPR"] for v in odds.values()]
            fpr_values = [v["FPR"] for v in odds.values()]
            tpr_std = np.std(tpr_values)
            fpr_std = np.std(fpr_values)

            for slice_name, metrics in odds.items():
                bias_metrics.append(
                    BiasMetric(
                        slice_name=slice_name,
                        metric_name="TPR",
                        value=metrics["TPR"],
                        threshold=thresholds.get("tpr_std", 0.10),
                        is_biased=tpr_std > thresholds.get("tpr_std", 0.10),
                    ),
                )
                bias_metrics.append(
                    BiasMetric(
                        slice_name=slice_name,
                        metric_name="FPR",
                        value=metrics["FPR"],
                        threshold=thresholds.get("fpr_std", 0.10),
                        is_biased=fpr_std > thresholds.get("fpr_std", 0.10),
                    ),
                )

        return bias_metrics


class BiasMitigationStrategy:
    """Produce a mitigation checklist based on detected slice imbalance."""

    @staticmethod
    def generate_mitigation_report(
        bias_metrics: List[BiasMetric],
        biased_slices: List[str],
    ) -> Dict[str, Any]:
        report = {
            "bias_detected": len(biased_slices) > 0,
            "biased_slices": biased_slices,
            "total_slices_analyzed": len(set(m.slice_name for m in bias_metrics)),
            "metrics": [
                {
                    "slice": m.slice_name,
                    "metric": m.metric_name,
                    "value": m.value,
                    "threshold": m.threshold,
                    "is_biased": m.is_biased,
                }
                for m in bias_metrics
            ],
            "recommendations": [],
        }

        if report["bias_detected"]:
            report["recommendations"] = [
                f"Consider resampling to balance {slice.split('=')[0]}"
                for slice in biased_slices
            ]
            report["recommendations"].append(
                "Use stratified sampling in data preparation",
            )
            report["recommendations"].append(
                "Apply fairness constraints during model training",
            )
            report["recommendations"].append("Monitor equalized odds during evaluation")

        logger.info(
            f"Generated mitigation report with "
            f"{len(report['recommendations'])} recommendations",
        )

        return report

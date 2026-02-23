"""Bias detection and fairness analysis modules."""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BiasMetric:
    """Bias metric result."""

    slice_name: str
    metric_name: str
    value: float
    threshold: float
    is_biased: bool


class DataSlicer:
    """Slices data by categorical and demographic features."""

    @staticmethod
    def slice_by_demographic(
        df: pd.DataFrame,
        demographic_column: str,
    ) -> Dict[str, pd.DataFrame]:
        """
        Slice data by demographic feature.

        Args:
            df: Input DataFrame
            demographic_column: Column name for slicing

        Returns:
            Dictionary of sliced DataFrames
        """
        slices = {}

        for value in df[demographic_column].unique():
            slice_df = df[df[demographic_column] == value]
            slices[f"{demographic_column}={value}"] = slice_df

            logger.info(
                f"Created slice {demographic_column}={value} "
                f"with {len(slice_df)} records",
            )

        return slices

    @staticmethod
    def slice_by_multiple_features(
        df: pd.DataFrame,
        feature_columns: List[str],
    ) -> Dict[str, pd.DataFrame]:
        """
        Slice data by multiple features.

        Args:
            df: Input DataFrame
            feature_columns: List of columns for slicing

        Returns:
            Dictionary of sliced DataFrames
        """
        slices = {}

        for col in feature_columns:
            col_slices = DataSlicer.slice_by_demographic(df, col)
            slices.update(col_slices)

        logger.info(f"Created {len(slices)} data slices")
        return slices

    @staticmethod
    def create_demographic_strata(
        df: pd.DataFrame,
        demographic_features: List[str],
    ) -> Dict[str, pd.DataFrame]:
        """
        Create demographic strata (intersectional slices).

        Args:
            df: Input DataFrame
            demographic_features: Features to create strata with

        Returns:
            Dictionary of stratified DataFrames
        """
        strata = {}

        combinations = df[demographic_features].drop_duplicates()

        for idx, row in combinations.iterrows():
            mask = pd.Series([True] * len(df))
            stratum_name_parts = []

            for col in demographic_features:
                mask = mask & (df[col] == row[col])
                stratum_name_parts.append(f"{col}={row[col]}")

            stratum_name = "_".join(stratum_name_parts)
            strata[stratum_name] = df[mask]

            logger.info(
                f"Created stratum {stratum_name} " f"with {len(df[mask])} records",
            )

        return strata


class BiasAnalyzer:
    """Analyzes bias in data and model predictions."""

    @staticmethod
    def calculate_statistical_parity(
        slices: Dict[str, pd.DataFrame],
        target_column: str,
        positive_label: Any,
    ) -> Dict[str, float]:
        """
        Calculate statistical parity (demographic parity).

        Measures if different groups have equal selection rates.

        Args:
            slices: Dictionary of sliced DataFrames
            target_column: Column name with target values
            positive_label: Value considered as positive outcome

        Returns:
            Dictionary of selection rates by slice
        """
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
        """
        Calculate equalized odds metrics.

        Measures if different groups have equal true positive and false positive rates.

        Args:
            slices: Dictionary of sliced DataFrames
            target_column: Actual target column
            prediction_column: Model prediction column
            positive_label: Value considered as positive

        Returns:
            Dictionary with TPR and FPR by slice
        """
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
    def calculate_disparate_impact_ratio(
        reference_group_rate: float,
        comparison_group_rate: float,
    ) -> float:
        """
        Calculate disparate impact ratio.

        Ratio < 0.8 indicates potential discrimination.

        Args:
            reference_group_rate: Selection rate for reference group
            comparison_group_rate: Selection rate for comparison group

        Returns:
            Disparate impact ratio
        """
        if reference_group_rate == 0:
            return 0

        di_ratio = comparison_group_rate / reference_group_rate
        logger.info(f"Disparate impact ratio: {di_ratio:.4f}")

        return di_ratio

    @staticmethod
    def detect_bias_in_slices(
        slices: Dict[str, pd.DataFrame],
        target_column: str,
        prediction_column: str = None,
        positive_label: Any = 1,
        thresholds: Dict[str, float] = None,
    ) -> List[BiasMetric]:
        """
        Detect bias across all slices.

        Args:
            slices: Dictionary of sliced DataFrames
            target_column: Target column name
            prediction_column: Optional prediction column
            positive_label: Positive outcome value
            thresholds: Custom thresholds for metrics

        Returns:
            List of BiasMetric results
        """
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
    """Mitigation strategies for detected bias."""

    @staticmethod
    def resample_underrepresented(
        df: pd.DataFrame,
        demographic_column: str,
        target_column: str,
    ) -> pd.DataFrame:
        """
        Resample data to balance underrepresented groups.

        Args:
            df: Input DataFrame
            demographic_column: Demographic feature column
            target_column: Target column

        Returns:
            Resampled DataFrame
        """
        resampled_dfs = []
        max_samples = 0

        for group in df[demographic_column].unique():
            group_df = df[df[demographic_column] == group]
            max_samples = max(max_samples, len(group_df))

        for group in df[demographic_column].unique():
            group_df = df[df[demographic_column] == group]

            if len(group_df) < max_samples:
                upsampled = group_df.sample(n=max_samples, replace=True)
                resampled_dfs.append(upsampled)
            else:
                resampled_dfs.append(group_df)

        df_balanced = pd.concat(resampled_dfs, ignore_index=True)
        logger.info(
            f"Resampled data from {len(df)} to {len(df_balanced)} records "
            f"to balance {demographic_column}",
        )

        return df_balanced

    @staticmethod
    def stratified_sampling(
        df: pd.DataFrame,
        demographic_columns: List[str],
        sample_size: int = None,
    ) -> pd.DataFrame:
        """
        Use stratified sampling to ensure representation.

        Args:
            df: Input DataFrame
            demographic_columns: Columns to stratify on
            sample_size: Total sample size

        Returns:
            Stratified sample DataFrame
        """
        if sample_size is None:
            sample_size = len(df)

        # Calculate stratum sizes
        group_counts = df.groupby(demographic_columns).size()
        total = group_counts.sum()
        stratum_sizes = (group_counts / total * sample_size).round().astype(int)

        sampled_dfs = []
        for stratum_name, count in zip(stratum_sizes.index, stratum_sizes.values):
            mask = pd.Series([True] * len(df))
            for i, col in enumerate(demographic_columns):
                mask = mask & (df[col] == stratum_name[i])

            stratum_df = df[mask]
            if len(stratum_df) > 0:
                sampled = stratum_df.sample(
                    n=min(count, len(stratum_df)),
                    replace=False,
                )
                sampled_dfs.append(sampled)

        df_stratified = pd.concat(sampled_dfs, ignore_index=True)
        logger.info(
            f"Created stratified sample of {len(df_stratified)} records",
        )

        return df_stratified

    @staticmethod
    def generate_mitigation_report(
        bias_metrics: List[BiasMetric],
        biased_slices: List[str],
    ) -> Dict[str, Any]:
        """
        Generate bias mitigation report.

        Args:
            bias_metrics: List of bias metrics
            biased_slices: List of slices with detected bias

        Returns:
            Mitigation strategy report
        """
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

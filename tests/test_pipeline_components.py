"""Comprehensive tests for pipeline components."""

import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from pipelines.bias_detection import BiasAnalyzer, BiasMitigationStrategy, DataSlicer
from pipelines.monitoring import (
    AnomalyAlert,
    PerformanceProfiler,
    PipelineLogger,
    PipelineMonitor,
)
from pipelines.preprocessing import (
    DataAggregator,
    DataCleaner,
    DataTransformer,
    FeatureEngineer,
)
from pipelines.validation import (
    AnomalyDetector,
    DataStatisticsGenerator,
    RangeValidator,
    SchemaValidator,
)

# ==================== Data Cleaning Tests ====================


class TestDataCleaner:
    """Tests for data cleaning operations."""

    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame."""
        return pd.DataFrame(
            {
                "user_id": ["u1", "u1", "u2", "u3", None],
                "rating": [4.5, 4.5, 3.2, 5.0, 2.1],
                "price_level": [2, 2, 1, 3, 1],
                "category": ["restaurant", "restaurant", "cafe", "bar", "cafe"],
            },
        )

    def test_remove_duplicates(self, sample_df):
        """Test duplicate removal."""
        result = DataCleaner.remove_duplicates(sample_df, subset=["user_id", "rating"])
        assert len(result) < len(sample_df)
        assert result.duplicated(subset=["user_id", "rating"]).sum() == 0

    def test_handle_missing_values_drop(self, sample_df):
        """Test missing value handling with drop strategy."""
        result = DataCleaner.handle_missing_values(sample_df, strategy="drop")
        assert result.isnull().sum().sum() == 0

    def test_handle_missing_values_fill(self, sample_df):
        """Test missing value handling with fill strategy."""
        result = DataCleaner.handle_missing_values(
            sample_df,
            strategy="fill",
            fill_value="unknown",
        )
        assert result.isnull().sum().sum() == 0

    def test_remove_outliers_iqr(self, sample_df):
        """Test outlier removal using IQR method."""
        result = DataCleaner.remove_outliers(sample_df, column="rating", method="iqr")
        assert isinstance(result, pd.DataFrame)


# ==================== Data Transformation Tests ====================


class TestDataTransformer:
    """Tests for data transformation operations."""

    @pytest.fixture
    def numeric_df(self):
        """Create numeric DataFrame."""
        return pd.DataFrame(
            {
                "rating": [1, 2, 3, 4, 5],
                "price": [10, 20, 30, 40, 50],
                "reviews": [100, 200, 300, 400, 500],
            },
        )

    @pytest.fixture
    def categorical_df(self):
        """Create categorical DataFrame."""
        return pd.DataFrame(
            {
                "category": ["A", "B", "A", "C", "B"],
                "type": ["X", "Y", "X", "Y", "X"],
                "value": [1, 2, 3, 4, 5],
            },
        )

    def test_normalize_minmax(self, numeric_df):
        """Test min-max normalization."""
        result = DataTransformer.normalize_numeric(
            numeric_df,
            columns=["rating"],
            method="minmax",
        )
        assert result["rating"].min() == pytest.approx(0)
        assert result["rating"].max() == pytest.approx(1)

    def test_normalize_zscore(self, numeric_df):
        """Test z-score normalization."""
        result = DataTransformer.normalize_numeric(
            numeric_df,
            columns=["rating"],
            method="zscore",
        )
        assert result["rating"].mean() == pytest.approx(0, abs=1e-5)
        assert result["rating"].std() == pytest.approx(1, abs=1e-5)

    def test_encode_categorical_onehot(self, categorical_df):
        """Test one-hot encoding."""
        result = DataTransformer.encode_categorical(
            categorical_df,
            columns=["category"],
            method="onehot",
        )
        assert len(result) == len(categorical_df)
        assert result.columns.tolist().count("category_B") == 1

    def test_create_temporal_features(self):
        """Test temporal feature creation."""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=5),
                "value": [1, 2, 3, 4, 5],
            },
        )
        result = DataTransformer.create_temporal_features(df, "date")
        assert "date_year" in result.columns
        assert "date_month" in result.columns
        assert "date_dayofweek" in result.columns
        assert "date_is_weekend" in result.columns


# ==================== Validation Tests ====================


class TestSchemaValidator:
    """Tests for schema validation."""

    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame."""
        return pd.DataFrame(
            {
                "user_id": ["u1", "u2", "u3"],
                "rating": [4.5, 3.2, 5.0],
                "active": [True, False, True],
            },
        )

    def test_validate_schema_passes(self, sample_df):
        """Test schema validation passes."""
        schema = {
            "user_id": np.object_,
            "rating": np.float64,
            "active": np.bool_,
        }
        result = SchemaValidator.validate_schema(sample_df, schema)
        assert result.passed or len(result.issues) == 0

    def test_validate_schema_missing_column(self, sample_df):
        """Test schema validation fails on missing column."""
        schema = {
            "user_id": np.object_,
            "rating": np.float64,
            "active": np.bool_,
            "missing_col": np.object_,
        }
        result = SchemaValidator.validate_schema(sample_df, schema)
        assert len(result.issues) > 0

    def test_validate_required_fields(self, sample_df):
        """Test required fields validation."""
        result = SchemaValidator.validate_required_fields(
            sample_df,
            required_fields=["user_id", "rating"],
        )
        assert result.passed or len(result.issues) == 0

    def test_validate_required_fields_with_nulls(self):
        """Test required fields validation with null values."""
        df = pd.DataFrame(
            {
                "user_id": ["u1", None, "u3"],
                "rating": [4.5, 3.2, None],
            },
        )
        result = SchemaValidator.validate_required_fields(
            df,
            required_fields=["user_id", "rating"],
        )
        assert len(result.issues) > 0


class TestRangeValidator:
    """Tests for range validation."""

    @pytest.fixture
    def numeric_df(self):
        """Create numeric DataFrame."""
        return pd.DataFrame(
            {
                "rating": [1, 2, 3, 4, 5],
                "price": [10, 20, 30, 40, 50],
            },
        )

    def test_validate_numeric_range_passes(self, numeric_df):
        """Test numeric range validation passes."""
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="rating",
            min_value=0,
            max_value=5,
        )
        assert result.passed

    def test_validate_numeric_range_fails(self, numeric_df):
        """Test numeric range validation fails."""
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="rating",
            min_value=2,
            max_value=4,
        )
        assert not result.passed
        assert len(result.issues) > 0


class TestAnomalyDetector:
    """Tests for anomaly detection."""

    @pytest.fixture
    def df_with_issues(self):
        """Create DataFrame with data quality issues."""
        return pd.DataFrame(
            {
                "col1": [1, 2, None, None, 5],
                "col2": [1, 1, 2, 2, 2],
                "col3": [100, 100, 200, 300, 10000],
            },
        )

    def test_detect_missing_values(self, df_with_issues):
        """Test missing value detection."""
        result = AnomalyDetector.detect_missing_values(df_with_issues, threshold_pct=20)
        assert len(result.issues) > 0

    def test_detect_duplicates(self):
        """Test duplicate detection."""
        df = pd.DataFrame(
            {
                "val": [1, 1, 2, 3, 3],
            },
        )
        result = AnomalyDetector.detect_duplicates(df)
        assert result.issue_count > 0


# ==================== Bias Detection Tests ====================


class TestBiasDetection:
    """Tests for bias detection."""

    @pytest.fixture
    def demographic_df(self):
        """Create demographic DataFrame."""
        return pd.DataFrame(
            {
                "age_group": ["young", "young", "old", "old", "young", "old"],
                "gender": ["M", "F", "M", "F", "M", "F"],
                "approved": [1, 0, 1, 1, 1, 0],
                "prediction": [1, 0, 1, 1, 1, 0],
            },
        )

    def test_slice_by_demographic(self, demographic_df):
        """Test demographic slicing."""
        slices = DataSlicer.slice_by_demographic(demographic_df, "age_group")
        assert len(slices) == 2
        assert "age_group=young" in slices
        assert len(slices["age_group=young"]) == 3

    def test_calculate_statistical_parity(self, demographic_df):
        """Test statistical parity calculation."""
        slices = DataSlicer.slice_by_demographic(demographic_df, "age_group")
        parity = BiasAnalyzer.calculate_statistical_parity(
            slices,
            "approved",
            positive_label=1,
        )
        assert len(parity) == 2
        assert all(isinstance(v, float) for v in parity.values())

    def test_detect_bias_in_slices(self, demographic_df):
        """Test bias detection across slices."""
        slices = DataSlicer.slice_by_demographic(demographic_df, "gender")
        metrics = BiasAnalyzer.detect_bias_in_slices(
            slices,
            "approved",
            positive_label=1,
        )
        assert len(metrics) > 0


class TestBiasMitigation:
    """Tests for bias mitigation strategies."""

    @pytest.fixture
    def imbalanced_df(self):
        """Create imbalanced demographic DataFrame."""
        return pd.DataFrame(
            {
                "group": ["A"] * 100 + ["B"] * 20,
                "outcome": [1] * 100 + [0] * 20,
                "value": np.random.randn(120),
            },
        )

    def test_resample_underrepresented(self, imbalanced_df):
        """Test resampling for underrepresented groups."""
        result = BiasMitigationStrategy.resample_underrepresented(
            imbalanced_df,
            "group",
            "outcome",
        )
        assert len(result) > len(imbalanced_df)

    def test_stratified_sampling(self, imbalanced_df):
        """Test stratified sampling."""
        result = BiasMitigationStrategy.stratified_sampling(
            imbalanced_df,
            ["group"],
            sample_size=60,
        )
        assert len(result) <= len(imbalanced_df)


# ==================== Monitoring Tests ====================


class TestPipelineMonitor:
    """Tests for pipeline monitoring."""

    def test_record_metric(self):
        """Test recording metrics."""
        monitor = PipelineMonitor()
        monitor.record_metric("task_duration", 5.5, {"task": "data_load"})
        assert "task_duration" in monitor.metrics

    def test_get_metrics_summary(self):
        """Test metrics summary."""
        monitor = PipelineMonitor()
        monitor.record_metric("duration", 5.0)
        monitor.record_metric("duration", 3.0)
        summary = monitor.get_metrics_summary()
        assert summary["duration"]["avg"] == 4.0

    def test_check_performance_threshold(self):
        """Test performance threshold checking."""
        monitor = PipelineMonitor()
        monitor.record_metric("latency", 100)
        exceeded = monitor.check_performance_threshold(
            "latency",
            threshold=50,
            operator=">",
        )
        assert exceeded is True


class TestPerformanceProfiler:
    """Tests for performance profiling."""

    def test_profiling(self):
        """Test task profiling."""
        profiler = PerformanceProfiler()
        profiler.start_profiling("task1")
        import time

        time.sleep(0.1)
        duration = profiler.end_profiling("task1")
        assert duration > 0.05

    def test_profile_summary(self):
        """Test profiling summary."""
        profiler = PerformanceProfiler()
        profiler.start_profiling("task1")
        profiler.end_profiling("task1")
        summary = profiler.get_profile_summary()
        assert "task1" in summary["tasks"]


# ==================== Data Statistics Tests ====================


class TestDataStatisticsGenerator:
    """Tests for data statistics generation."""

    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame."""
        return pd.DataFrame(
            {
                "numeric": [1, 2, 3, 4, 5],
                "text": ["a", "b", "c", "d", "e"],
                "float_col": [1.1, 2.2, 3.3, 4.4, 5.5],
            },
        )

    def test_generate_statistics(self, sample_df):
        """Test statistics generation."""
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        assert stats["record_count"] == 5
        assert stats["column_count"] == 3
        assert "columns" in stats

    def test_statistics_contains_numeric_info(self, sample_df):
        """Test statistics include numeric column info."""
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        numeric_stats = stats["columns"]["numeric"]
        assert "mean" in numeric_stats
        assert "std" in numeric_stats
        assert "min" in numeric_stats
        assert "max" in numeric_stats

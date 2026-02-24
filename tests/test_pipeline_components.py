"""Comprehensive tests for pipeline components"""

import json
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from pipelines.bias_detection import BiasAnalyzer, BiasMitigationStrategy, DataSlicer
from pipelines.monitoring import (
    AlertLevel,
    AnomalyAlert,
    PerformanceProfiler,
    PipelineLogger,
    PipelineMonitor,
)
from pipelines.preprocessing import DataAggregator, DataCleaner, FeatureEngineer
from pipelines.validation import (
    AnomalyDetector,
    DataQualityLevel,
    DataStatisticsGenerator,
    RangeValidator,
    SchemaValidator,
)

# ====================  Fixtures  ====================


@pytest.fixture
def simple_numeric_df():
    return pd.DataFrame({"rating": [1, 2, 3, 4, 5], "price": [10, 20, 30, 40, 50]})


@pytest.fixture
def demographic_df():
    return pd.DataFrame(
        {
            "age_group": ["young", "young", "old", "old", "young", "old"],
            "gender": ["M", "F", "M", "F", "M", "F"],
            "approved": [1, 0, 1, 1, 1, 0],
            "prediction": [1, 0, 1, 1, 1, 0],
        },
    )


# ==================== DataCleaner Tests ====================


class TestDataCleaner:
    """Tests for data cleaning operations."""

    @pytest.fixture
    def sample_df(self):
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

    def test_remove_duplicates_no_subset(self, sample_df):
        """remove_duplicates without a subset considers all columns."""
        result = DataCleaner.remove_duplicates(sample_df)
        assert isinstance(result, pd.DataFrame)
        assert result.duplicated().sum() == 0

    def test_remove_duplicates_preserves_all_unique_rows(self):
        """When there are no duplicates, all rows are preserved."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        result = DataCleaner.remove_duplicates(df)
        assert len(result) == len(df)

    def test_remove_duplicates_all_identical(self):
        """When every row is identical, only one row survives."""
        df = pd.DataFrame({"a": [7, 7, 7], "b": [10, 10, 10]})
        result = DataCleaner.remove_duplicates(df)
        assert len(result) == 1

    def test_handle_missing_values_forward_fill(self):
        """Test forward-fill strategy propagates prior values."""
        df = pd.DataFrame({"val": [1.0, None, None, 4.0]})
        result = DataCleaner.handle_missing_values(df, strategy="forward_fill")
        assert result["val"].isnull().sum() == 0
        assert result["val"].iloc[1] == 1.0

    def test_handle_missing_values_backward_fill(self):
        """Test backward-fill strategy propagates next values."""
        df = pd.DataFrame({"val": [None, None, 3.0, 4.0]})
        result = DataCleaner.handle_missing_values(df, strategy="backward_fill")
        assert result["val"].isnull().sum() == 0
        assert result["val"].iloc[0] == 3.0

    def test_handle_missing_values_invalid_strategy(self, sample_df):
        """Unknown strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            DataCleaner.handle_missing_values(sample_df, strategy="interpolate")

    def test_handle_missing_values_no_missing(self):
        """DataFrame with no NaNs is returned unchanged for 'drop'."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = DataCleaner.handle_missing_values(df, strategy="drop")
        assert len(result) == len(df)

    def test_remove_outliers_zscore(self):
        """Test outlier removal using z-score method."""
        # Build data with an obvious outlier
        df = pd.DataFrame({"val": [1, 2, 2, 3, 2, 3, 100]})
        result = DataCleaner.remove_outliers(
            df,
            column="val",
            method="zscore",
            threshold=2.0,
        )
        assert 100 not in result["val"].values

    def test_remove_outliers_invalid_method(self, sample_df):
        """Unknown outlier method raises ValueError."""
        with pytest.raises(ValueError, match="Unknown method"):
            DataCleaner.remove_outliers(sample_df, column="rating", method="percentile")

    def test_remove_outliers_no_outliers(self):
        """IQR with tight data — nothing is removed."""
        df = pd.DataFrame({"val": [4, 5, 5, 6, 5]})
        result = DataCleaner.remove_outliers(df, column="val", method="iqr")
        assert len(result) == len(df)

    def test_handle_missing_fill_numeric(self):
        """Numeric fill value fills NaNs in numeric column."""
        df = pd.DataFrame({"score": [1.0, None, 3.0]})
        result = DataCleaner.handle_missing_values(df, strategy="fill", fill_value=0)
        assert result["score"].iloc[1] == 0.0


# ==================== DataAggregator Tests ====================


class TestDataAggregator:
    """Tests for data aggregation operations (not previously tested)."""

    def test_aggregate_calendar_data_basic(self):
        """Calendar records are correctly aggregated."""
        records = [
            {
                "user_id": "u1",
                "busy_intervals": [
                    {"start": "2024-01-01T09:00:00", "end": "2024-01-01T10:00:00"},
                ],
                "availability_percentage": 75,
            },
        ]
        df = DataAggregator.aggregate_calendar_data(records)
        assert len(df) == 1
        assert df.iloc[0]["user_id"] == "u1"
        assert df.iloc[0]["num_busy_intervals"] == 1
        assert df.iloc[0]["total_busy_hours"] == pytest.approx(1.0)
        assert df.iloc[0]["availability_percentage"] == 75

    def test_aggregate_calendar_data_empty(self):
        """Empty calendar list returns empty DataFrame."""
        df = DataAggregator.aggregate_calendar_data([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_aggregate_calendar_data_no_busy_intervals(self):
        """User with no busy intervals has total_busy_hours == 0."""
        records = [
            {"user_id": "u2", "busy_intervals": [], "availability_percentage": 100},
        ]
        df = DataAggregator.aggregate_calendar_data(records)
        assert df.iloc[0]["total_busy_hours"] == 0.0
        assert df.iloc[0]["num_busy_intervals"] == 0

    def test_aggregate_calendar_data_multiple_users(self):
        """Multiple calendar records aggregate to multiple rows."""
        records = [
            {
                "user_id": f"u{i}",
                "busy_intervals": [],
                "availability_percentage": i * 10,
            }
            for i in range(1, 4)
        ]
        df = DataAggregator.aggregate_calendar_data(records)
        assert len(df) == 3

    def test_aggregate_venue_data_basic(self):
        """Venue records are correctly aggregated into a DataFrame."""
        venues = [
            {
                "venue_id": "v1",
                "name": "Pasta Place",
                "category": "restaurant",
                "rating": 4.5,
                "price_level": 2,
                "location": {"latitude": 40.7128, "longitude": -74.0060},
                "review_count": 200,
            },
        ]
        df = DataAggregator.aggregate_venue_data(venues)
        assert len(df) == 1
        assert df.iloc[0]["venue_id"] == "v1"
        assert df.iloc[0]["latitude"] == pytest.approx(40.7128)
        assert df.iloc[0]["rating"] == 4.5

    def test_aggregate_venue_data_missing_location(self):
        """Venues without a location key produce None lat/lon."""
        venues = [{"venue_id": "v2", "name": "Mystery Bar"}]
        df = DataAggregator.aggregate_venue_data(venues)
        assert df.iloc[0]["latitude"] is None
        assert df.iloc[0]["longitude"] is None

    def test_aggregate_venue_data_empty(self):
        """Empty venue list produces empty DataFrame."""
        df = DataAggregator.aggregate_venue_data([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_aggregate_group_preferences_basic(self):
        """Group preference records aggregate correctly."""
        records = [
            {
                "group_id": "g1",
                "members": ["u1", "u2", "u3"],
                "preferences": {
                    "avg_price_level": 2,
                    "categories": ["restaurant", "cafe"],
                    "dietary": ["vegan"],
                    "max_distance_km": 5,
                },
            },
        ]
        df = DataAggregator.aggregate_group_preferences(records)
        assert len(df) == 1
        assert df.iloc[0]["num_members"] == 3
        assert df.iloc[0]["avg_price_level"] == 2
        cats = json.loads(df.iloc[0]["preferred_categories"])
        assert "restaurant" in cats

    def test_aggregate_group_preferences_empty_members(self):
        """Group record with no members gives num_members == 0."""
        records = [{"group_id": "g2", "members": [], "preferences": {}}]
        df = DataAggregator.aggregate_group_preferences(records)
        assert df.iloc[0]["num_members"] == 0


# ==================== FeatureEngineer Tests ====================


class TestFeatureEngineer:
    """Tests for feature engineering operations (not previously tested)."""

    @pytest.fixture
    def venue_df(self):
        return pd.DataFrame(
            {
                "rating": [3.5, 4.5, 2.0, 5.0, 1.5],
                "price_level": [1, 2, 3, 4, 1],
                "review_count": [50, 200, 10, 500, 5],
            },
        )

    @pytest.fixture
    def availability_df(self):
        return pd.DataFrame(
            {
                "availability_percentage": [10, 30, 60, 85, 0],
                "num_busy_intervals": [5, 3, 2, 1, 0],
                "total_busy_hours": [4.0, 2.0, 1.0, 0.5, 0.0],
            },
        )

    def test_create_venue_features_columns(self, venue_df):
        """Venue feature engineering adds expected columns."""
        result = FeatureEngineer.create_venue_features(venue_df)
        assert "rating_bucket" in result.columns
        assert "price_quality_ratio" in result.columns
        assert "popularity_score" in result.columns
        assert "quality_score" in result.columns

    def test_create_venue_features_no_mutation(self, venue_df):
        """Venue feature engineering does not mutate the original DataFrame."""
        original_cols = set(venue_df.columns)
        FeatureEngineer.create_venue_features(venue_df)
        assert set(venue_df.columns) == original_cols

    def test_create_venue_features_popularity_score_range(self, venue_df):
        """Popularity score (normalised review count) is in [0, 1]."""
        result = FeatureEngineer.create_venue_features(venue_df)
        assert result["popularity_score"].min() >= 0.0
        assert result["popularity_score"].max() <= 1.0

    def test_create_venue_features_rating_bucket_labels(self, venue_df):
        """Rating buckets only contain expected labels."""
        result = FeatureEngineer.create_venue_features(venue_df)
        valid_labels = {"low", "medium", "high", "excellent"}
        actual_labels = set(result["rating_bucket"].astype(str).unique()) - {"nan"}
        assert actual_labels.issubset(valid_labels)

    def test_create_venue_features_quality_score_range(self, venue_df):
        """Composite quality score stays within a sensible range (0–1)."""
        result = FeatureEngineer.create_venue_features(venue_df)
        assert result["quality_score"].min() >= 0.0
        assert result["quality_score"].max() <= 1.0

    def test_create_availability_features_columns(self, availability_df):
        """Availability feature engineering adds expected columns."""
        result = FeatureEngineer.create_availability_features(availability_df)
        assert "availability_category" in result.columns
        assert "busy_intensity" in result.columns
        assert "availability_score" in result.columns

    def test_create_availability_features_score_range(self, availability_df):
        """Availability score is in [0, 1]."""
        result = FeatureEngineer.create_availability_features(availability_df)
        assert result["availability_score"].between(0, 1).all()

    def test_create_availability_features_no_mutation(self, availability_df):
        """Availability feature engineering does not mutate the original."""
        original_cols = set(availability_df.columns)
        FeatureEngineer.create_availability_features(availability_df)
        assert set(availability_df.columns) == original_cols


# ==================== Validation: SchemaValidator Tests ====================


class TestSchemaValidator:
    """Tests for schema validation."""

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame(
            {
                "user_id": ["u1", "u2", "u3"],
                "rating": [4.5, 3.2, 5.0],
                "active": [True, False, True],
            },
        )

    def test_validate_schema_passes(self, sample_df):
        schema = {"user_id": np.object_, "rating": np.float64, "active": np.bool_}
        result = SchemaValidator.validate_schema(sample_df, schema)
        assert result.passed or len(result.issues) == 0

    def test_validate_schema_missing_column(self, sample_df):
        schema = {
            "user_id": np.object_,
            "rating": np.float64,
            "active": np.bool_,
            "missing_col": np.object_,
        }
        result = SchemaValidator.validate_schema(sample_df, schema)
        assert len(result.issues) > 0

    def test_validate_required_fields(self, sample_df):
        result = SchemaValidator.validate_required_fields(
            sample_df,
            required_fields=["user_id", "rating"],
        )
        assert result.passed or len(result.issues) == 0

    def test_validate_required_fields_with_nulls(self):
        df = pd.DataFrame({"user_id": ["u1", None, "u3"], "rating": [4.5, 3.2, None]})
        result = SchemaValidator.validate_required_fields(
            df,
            required_fields=["user_id", "rating"],
        )
        assert len(result.issues) > 0

    def test_validate_schema_empty_schema(self, sample_df):
        """Empty schema dict: all schema checks pass (no expectations)."""
        result = SchemaValidator.validate_schema(sample_df, {})
        assert result.passed

    def test_validate_schema_returns_validation_result(self, sample_df):
        """validate_schema always returns a ValidationResult."""
        schema = {"user_id": np.object_}
        result = SchemaValidator.validate_schema(sample_df, schema)
        assert hasattr(result, "passed")
        assert hasattr(result, "issues")
        assert hasattr(result, "issue_count")
        assert hasattr(result, "quality_level")

    def test_validate_schema_multiple_missing_columns(self):
        """Multiple missing columns each appear as separate issues."""
        df = pd.DataFrame({"a": [1, 2]})
        schema = {"a": np.integer, "b": np.object_, "c": np.float64}
        result = SchemaValidator.validate_schema(df, schema)
        # "b" and "c" missing → at least 2 issues
        assert result.issue_count >= 2

    def test_validate_schema_quality_level_high_on_pass(self, sample_df):
        """Passing schema validation sets quality_level to HIGH."""
        schema = {"user_id": np.object_, "rating": np.float64, "active": np.bool_}
        result = SchemaValidator.validate_schema(sample_df, schema)
        if result.passed:
            assert result.quality_level == DataQualityLevel.HIGH

    def test_validate_required_fields_field_not_in_df(self):
        """Requiring a field that doesn't exist at all is flagged."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = SchemaValidator.validate_required_fields(df, required_fields=["b"])
        assert len(result.issues) > 0
        assert not result.passed

    def test_validate_required_fields_all_null_column(self):
        """An entirely null required field generates a null-count issue."""
        df = pd.DataFrame({"a": [None, None, None]})
        result = SchemaValidator.validate_required_fields(df, required_fields=["a"])
        assert not result.passed
        assert result.issue_count > 0

    def test_validate_schema_empty_dataframe(self):
        """Schema validation on empty DataFrame with matching columns passes."""
        df = pd.DataFrame({"rating": pd.Series([], dtype=np.float64)})
        schema = {"rating": np.float64}
        result = SchemaValidator.validate_schema(df, schema)
        assert result.passed


# ==================== Validation: RangeValidator Tests ====================


class TestRangeValidator:
    """Tests for range validation."""

    @pytest.fixture
    def numeric_df(self):
        return pd.DataFrame({"rating": [1, 2, 3, 4, 5], "price": [10, 20, 30, 40, 50]})

    # --- Original tests preserved ---

    def test_validate_numeric_range_passes(self, numeric_df):
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="rating",
            min_value=0,
            max_value=5,
        )
        assert result.passed

    def test_validate_numeric_range_fails(self, numeric_df):
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="rating",
            min_value=2,
            max_value=4,
        )
        assert not result.passed
        assert len(result.issues) > 0

    def test_validate_numeric_range_only_min(self, numeric_df):
        """Only min_value specified — values below min are caught."""
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="rating",
            min_value=3,
        )
        assert not result.passed  # 1 and 2 violate min of 3

    def test_validate_numeric_range_only_max(self, numeric_df):
        """Only max_value specified — values above max are caught."""
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="rating",
            max_value=3,
        )
        assert not result.passed  # 4 and 5 violate max of 3

    def test_validate_numeric_range_missing_column(self, numeric_df):
        """Missing column name is reported as an issue."""
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="nonexistent",
            min_value=0,
            max_value=10,
        )
        assert not result.passed
        assert len(result.issues) > 0

    def test_validate_numeric_range_exact_boundary(self, numeric_df):
        """Boundary values are inclusive."""
        result = RangeValidator.validate_numeric_range(
            numeric_df,
            column="rating",
            min_value=1,
            max_value=5,
        )
        assert result.passed

    def test_validate_categorical_values_passes(self):
        """All valid values → passes."""
        df = pd.DataFrame({"status": ["active", "inactive", "active"]})
        result = RangeValidator.validate_categorical_values(
            df,
            column="status",
            allowed_values=["active", "inactive"],
        )
        assert result.passed

    def test_validate_categorical_values_fails_on_invalid(self):
        """Invalid category value is flagged."""
        df = pd.DataFrame({"status": ["active", "unknown", "inactive"]})
        result = RangeValidator.validate_categorical_values(
            df,
            column="status",
            allowed_values=["active", "inactive"],
        )
        assert not result.passed
        assert result.issue_count > 0

    def test_validate_categorical_values_missing_column(self):
        """Missing column name is reported as an issue."""
        df = pd.DataFrame({"status": ["active"]})
        result = RangeValidator.validate_categorical_values(
            df,
            column="nonexistent",
            allowed_values=["active"],
        )
        assert not result.passed

    def test_validate_categorical_values_all_invalid(self):
        """When every value is invalid, at least one issue is raised."""
        df = pd.DataFrame({"cat": ["X", "Y", "Z"]})
        result = RangeValidator.validate_categorical_values(
            df,
            column="cat",
            allowed_values=["A", "B"],
        )
        assert not result.passed


# ==================== Validation: AnomalyDetector Tests ====================


class TestAnomalyDetector:
    """Tests for anomaly detection."""

    @pytest.fixture
    def df_with_issues(self):
        return pd.DataFrame(
            {
                "col1": [1, 2, None, None, 5],
                "col2": [1, 1, 2, 2, 2],
                "col3": [100, 100, 200, 300, 10000],
            },
        )

    def test_detect_missing_values(self, df_with_issues):
        result = AnomalyDetector.detect_missing_values(df_with_issues, threshold_pct=20)
        assert len(result.issues) > 0

    def test_detect_duplicates(self):
        df = pd.DataFrame({"val": [1, 1, 2, 3, 3]})
        result = AnomalyDetector.detect_duplicates(df)
        assert result.issue_count > 0

    # --- Edge cases / new tests ---

    def test_detect_missing_values_no_missing(self):
        """Clean DataFrame generates no issues."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        result = AnomalyDetector.detect_missing_values(df, threshold_pct=10)
        assert result.passed
        assert len(result.issues) == 0

    def test_detect_missing_values_threshold_respected(self):
        """Only columns exceeding the threshold generate issues."""
        df = pd.DataFrame({"a": [1, None, 3, 4, 5], "b": [1, 2, 3, 4, 5]})
        # 20% missing in 'a', threshold=10 → issue; no issue for 'b'
        result = AnomalyDetector.detect_missing_values(df, threshold_pct=10)
        assert any("a" in issue for issue in result.issues)
        assert all("b" not in issue for issue in result.issues)

    def test_detect_duplicates_no_duplicates(self):
        """Unique-row DataFrame returns passed result and issue_count == 0."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = AnomalyDetector.detect_duplicates(df)
        assert result.passed
        assert result.issue_count == 0

    def test_detect_duplicates_with_subset(self):
        """Duplicates detected only on the specified subset."""
        df = pd.DataFrame({"a": [1, 1, 2], "b": [10, 20, 30]})
        result = AnomalyDetector.detect_duplicates(df, subset=["a"])
        assert not result.passed

    def test_detect_outliers_iqr_detects_extreme_value(self):
        """IQR method flags a clearly extreme value."""
        df = pd.DataFrame({"val": [1, 2, 2, 2, 3, 3, 3, 1000]})
        result = AnomalyDetector.detect_outliers(df, column="val", method="iqr")
        assert not result.passed
        assert len(result.issues) > 0

    def test_detect_outliers_no_outliers(self):
        """Tight data has no outliers."""
        df = pd.DataFrame({"val": [5, 5, 6, 5, 6, 5]})
        result = AnomalyDetector.detect_outliers(df, column="val", method="iqr")
        assert result.passed

    def test_detect_outliers_missing_column(self):
        """Missing column is flagged as an issue."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = AnomalyDetector.detect_outliers(df, column="nonexistent", method="iqr")
        assert not result.passed

    def test_detect_missing_values_quality_level_critical(self):
        """Many problematic columns set quality_level to CRITICAL."""
        df = pd.DataFrame(
            {
                "a": [None] * 10,
                "b": [None] * 10,
                "c": [None] * 10,
                "d": [None] * 10,
            },
        )
        result = AnomalyDetector.detect_missing_values(df, threshold_pct=5)
        assert result.quality_level == DataQualityLevel.CRITICAL


# ==================== Validation: DataStatisticsGenerator Tests ====================


class TestDataStatisticsGenerator:
    """Tests for data statistics generation."""

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame(
            {
                "numeric": [1, 2, 3, 4, 5],
                "text": ["a", "b", "c", "d", "e"],
                "float_col": [1.1, 2.2, 3.3, 4.4, 5.5],
            },
        )

    # --- Original tests preserved ---

    def test_generate_statistics(self, sample_df):
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        assert stats["record_count"] == 5
        assert stats["column_count"] == 3
        assert "columns" in stats

    def test_statistics_contains_numeric_info(self, sample_df):
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        numeric_stats = stats["columns"]["numeric"]
        assert "mean" in numeric_stats
        assert "std" in numeric_stats
        assert "min" in numeric_stats
        assert "max" in numeric_stats

    # --- Edge cases / new tests ---

    def test_statistics_text_column_has_mode(self, sample_df):
        """Object (text) columns include a mode field."""
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        text_stats = stats["columns"]["text"]
        assert "mode" in text_stats

    def test_statistics_null_percentage(self):
        """Null percentage is correctly computed."""
        df = pd.DataFrame({"a": [1.0, None, 3.0, None, 5.0]})
        stats = DataStatisticsGenerator.generate_statistics(df)
        assert stats["columns"]["a"]["null_percentage"] == pytest.approx(40.0)

    def test_statistics_empty_dataframe(self):
        """Empty DataFrame is handled without error."""
        df = pd.DataFrame({"a": pd.Series([], dtype=float)})
        stats = DataStatisticsGenerator.generate_statistics(df)
        assert stats["record_count"] == 0

    def test_statistics_duplicates_count(self):
        """Duplicates count is correct."""
        df = pd.DataFrame({"val": [1, 1, 2, 3, 3]})
        stats = DataStatisticsGenerator.generate_statistics(df)
        assert stats["duplicates_count"] == 2

    def test_statistics_memory_usage_positive(self, sample_df):
        """Memory usage is a positive number."""
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        assert stats["memory_usage_mb"] > 0

    def test_statistics_numeric_quartiles(self, sample_df):
        """Quartile statistics are present and ordered correctly."""
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        num = stats["columns"]["numeric"]
        assert "q25" in num and "q75" in num
        assert num["q25"] <= num["median"] <= num["q75"]

    def test_save_statistics(self, sample_df, tmp_path):
        """Statistics can be serialised and reloaded from JSON."""
        stats = DataStatisticsGenerator.generate_statistics(sample_df)
        out_path = str(tmp_path / "stats.json")
        DataStatisticsGenerator.save_statistics(stats, out_path)
        with open(out_path) as f:
            loaded = json.load(f)
        assert loaded["record_count"] == stats["record_count"]


# ==================== Bias Detection Tests ====================


class TestBiasDetection:
    """Tests for bias detection."""

    @pytest.fixture
    def demographic_df(self):
        return pd.DataFrame(
            {
                "age_group": ["young", "young", "old", "old", "young", "old"],
                "gender": ["M", "F", "M", "F", "M", "F"],
                "approved": [1, 0, 1, 1, 1, 0],
                "prediction": [1, 0, 1, 1, 1, 0],
            },
        )

    def test_slice_by_demographic(self, demographic_df):
        slices = DataSlicer.slice_by_demographic(demographic_df, "age_group")
        assert len(slices) == 2
        assert "age_group=young" in slices
        assert len(slices["age_group=young"]) == 3

    def test_calculate_statistical_parity(self, demographic_df):
        slices = DataSlicer.slice_by_demographic(demographic_df, "age_group")
        parity = BiasAnalyzer.calculate_statistical_parity(
            slices,
            "approved",
            positive_label=1,
        )
        assert len(parity) == 2
        assert all(isinstance(v, float) for v in parity.values())

    def test_detect_bias_in_slices(self, demographic_df):
        slices = DataSlicer.slice_by_demographic(demographic_df, "gender")
        metrics = BiasAnalyzer.detect_bias_in_slices(
            slices,
            "approved",
            positive_label=1,
        )
        assert len(metrics) > 0

    # --- Edge cases / new tests ---

    def test_slice_by_demographic_single_value(self):
        """Slicing a column with only one distinct value produces one slice."""
        df = pd.DataFrame({"group": ["A", "A", "A"], "val": [1, 2, 3]})
        slices = DataSlicer.slice_by_demographic(df, "group")
        assert len(slices) == 1

    def test_slice_by_multiple_features(self, demographic_df):
        """Multiple feature slicing produces a slice per unique value per column."""
        slices = DataSlicer.slice_by_multiple_features(
            demographic_df,
            ["age_group", "gender"],
        )
        # 2 distinct age_groups + 2 distinct genders = 4 slices total
        assert len(slices) == 4

    def test_create_demographic_strata(self, demographic_df):
        """Intersectional strata create unique combinations."""
        strata = DataSlicer.create_demographic_strata(
            demographic_df,
            ["age_group", "gender"],
        )
        # young-M, young-F, old-M, old-F = up to 4 combinations
        assert len(strata) >= 2

    def test_statistical_parity_values_in_range(self, demographic_df):
        """All selection rates are between 0 and 1."""
        slices = DataSlicer.slice_by_demographic(demographic_df, "gender")
        parity = BiasAnalyzer.calculate_statistical_parity(
            slices,
            "approved",
            positive_label=1,
        )
        for v in parity.values():
            assert 0.0 <= v <= 1.0

    def test_statistical_parity_empty_slice(self):
        """Empty slices return 0 selection rate."""
        slices = {"empty_slice": pd.DataFrame({"target": []})}
        result = BiasAnalyzer.calculate_statistical_parity(
            slices,
            "target",
            positive_label=1,
        )
        assert result["empty_slice"] == 0

    def test_calculate_equalized_odds_structure(self, demographic_df):
        """Equalized odds returns TPR and FPR keys per slice."""
        slices = DataSlicer.slice_by_demographic(demographic_df, "gender")
        odds = BiasAnalyzer.calculate_equalized_odds(
            slices,
            "approved",
            "prediction",
            positive_label=1,
        )
        for v in odds.values():
            assert "TPR" in v and "FPR" in v

    def test_calculate_equalized_odds_values_in_range(self, demographic_df):
        """TPR and FPR values are between 0 and 1."""
        slices = DataSlicer.slice_by_demographic(demographic_df, "gender")
        odds = BiasAnalyzer.calculate_equalized_odds(
            slices,
            "approved",
            "prediction",
            positive_label=1,
        )
        for metrics in odds.values():
            assert 0.0 <= metrics["TPR"] <= 1.0
            assert 0.0 <= metrics["FPR"] <= 1.0

    def test_disparate_impact_ratio_zero_reference(self):
        """Zero reference rate returns 0 (no division by zero)."""
        ratio = BiasAnalyzer.calculate_disparate_impact_ratio(0.0, 0.5)
        assert ratio == 0

    def test_disparate_impact_ratio_equal_groups(self):
        """Equal rates give a ratio of 1.0."""
        ratio = BiasAnalyzer.calculate_disparate_impact_ratio(0.8, 0.8)
        assert ratio == pytest.approx(1.0)

    def test_disparate_impact_ratio_below_threshold(self):
        """Ratio below 0.8 suggests potential discrimination (80% rule)."""
        ratio = BiasAnalyzer.calculate_disparate_impact_ratio(1.0, 0.5)
        assert ratio < 0.8

    def test_detect_bias_includes_prediction_metrics(self, demographic_df):
        """When prediction_column is provided, TPR/FPR metrics are included."""
        slices = DataSlicer.slice_by_demographic(demographic_df, "gender")
        metrics = BiasAnalyzer.detect_bias_in_slices(
            slices,
            "approved",
            prediction_column="prediction",
            positive_label=1,
        )
        metric_names = {m.metric_name for m in metrics}
        assert "TPR" in metric_names or "FPR" in metric_names


# ==================== Bias Mitigation Tests ====================


class TestBiasMitigation:
    """Tests for bias mitigation strategies."""

    @pytest.fixture
    def imbalanced_df(self):
        np.random.seed(42)
        return pd.DataFrame(
            {
                "group": ["A"] * 100 + ["B"] * 20,
                "outcome": [1] * 100 + [0] * 20,
                "value": np.random.randn(120),
            },
        )

    def test_resample_underrepresented(self, imbalanced_df):
        result = BiasMitigationStrategy.resample_underrepresented(
            imbalanced_df,
            "group",
            "outcome",
        )
        assert len(result) > len(imbalanced_df)

    def test_stratified_sampling(self, imbalanced_df):
        result = BiasMitigationStrategy.stratified_sampling(
            imbalanced_df,
            ["group"],
            sample_size=60,
        )
        assert len(result) <= len(imbalanced_df)

    # ==================== Monitoring Tests ====================

    def test_resample_produces_balanced_groups(self, imbalanced_df):
        """After resampling, all groups have the same size."""
        result = BiasMitigationStrategy.resample_underrepresented(
            imbalanced_df,
            "group",
            "outcome",
        )
        group_counts = result["group"].value_counts()
        assert group_counts["A"] == group_counts["B"]

    def test_stratified_sampling_preserves_group_ratio(self, imbalanced_df):
        """Stratified sampling roughly preserves group proportions."""
        sample_size = 60
        result = BiasMitigationStrategy.stratified_sampling(
            imbalanced_df,
            ["group"],
            sample_size=sample_size,
        )
        # Both groups should be present
        assert "A" in result["group"].values
        assert "B" in result["group"].values

    def test_stratified_sampling_default_size(self, imbalanced_df):
        """Without explicit sample_size, all rows are returned (≈ len(df))."""
        result = BiasMitigationStrategy.stratified_sampling(imbalanced_df, ["group"])
        assert len(result) <= len(imbalanced_df)

    def test_generate_mitigation_report_no_bias(self):
        """Report with no biased slices sets bias_detected to False."""
        report = BiasMitigationStrategy.generate_mitigation_report([], [])
        assert report["bias_detected"] is False
        assert report["recommendations"] == []

    def test_generate_mitigation_report_with_bias(self):
        """Report with biased slices includes recommendations."""
        from pipelines.bias_detection import BiasMetric

        metrics = [
            BiasMetric(
                slice_name="gender=M",
                metric_name="selection_rate",
                value=0.9,
                threshold=0.05,
                is_biased=True,
            ),
        ]
        report = BiasMitigationStrategy.generate_mitigation_report(
            metrics,
            ["gender=M"],
        )
        assert report["bias_detected"] is True
        assert len(report["recommendations"]) > 0

    def test_generate_mitigation_report_total_slices_count(self):
        """total_slices_analyzed reflects the number of unique slice names."""
        from pipelines.bias_detection import BiasMetric

        metrics = [
            BiasMetric("slice_A", "selection_rate", 0.6, 0.05, False),
            BiasMetric("slice_B", "selection_rate", 0.4, 0.05, False),
        ]
        report = BiasMitigationStrategy.generate_mitigation_report(metrics, [])
        assert report["total_slices_analyzed"] == 2


# ==================== Monitoring: PipelineMonitor Tests ====================


class TestPipelineMonitor:
    """Tests for pipeline monitoring."""

    def test_record_metric(self):
        monitor = PipelineMonitor()
        monitor.record_metric("task_duration", 5.5, {"task": "data_load"})
        assert "task_duration" in monitor.metrics

    def test_get_metrics_summary(self):
        monitor = PipelineMonitor()
        monitor.record_metric("duration", 5.0)
        monitor.record_metric("duration", 3.0)
        summary = monitor.get_metrics_summary()
        assert summary["duration"]["avg"] == 4.0

    def test_check_performance_threshold(self):
        monitor = PipelineMonitor()
        monitor.record_metric("latency", 100)
        exceeded = monitor.check_performance_threshold(
            "latency",
            threshold=50,
            operator=">",
        )
        assert exceeded is True

    def test_record_metric_multiple_values(self):
        """Recording the same metric twice stores both data points."""
        monitor = PipelineMonitor()
        monitor.record_metric("load", 1.0)
        monitor.record_metric("load", 2.0)
        assert len(monitor.metrics["load"]) == 2

    def test_metrics_summary_min_max(self):
        """Summary min and max are correct."""
        monitor = PipelineMonitor()
        for v in [10, 20, 30]:
            monitor.record_metric("m", float(v))
        summary = monitor.get_metrics_summary()
        assert summary["m"]["min"] == 10
        assert summary["m"]["max"] == 30

    def test_metrics_summary_latest(self):
        """Summary latest reflects the most-recently recorded value."""
        monitor = PipelineMonitor()
        monitor.record_metric("x", 1.0)
        monitor.record_metric("x", 99.0)
        assert monitor.get_metrics_summary()["x"]["latest"] == 99.0

    def test_check_threshold_less_than(self):
        """'<' operator works correctly."""
        monitor = PipelineMonitor()
        monitor.record_metric("mem", 30)
        assert (
            monitor.check_performance_threshold("mem", threshold=50, operator="<")
            is True
        )

    def test_check_threshold_equal(self):
        """'==' operator works correctly."""
        monitor = PipelineMonitor()
        monitor.record_metric("code", 200)
        assert (
            monitor.check_performance_threshold("code", threshold=200, operator="==")
            is True
        )

    def test_check_threshold_not_equal(self):
        """'!=' operator works correctly."""
        monitor = PipelineMonitor()
        monitor.record_metric("status", 500)
        assert (
            monitor.check_performance_threshold("status", threshold=200, operator="!=")
            is True
        )

    def test_check_threshold_gte_lte(self):
        """'>=' and '<=' operators work correctly."""
        monitor = PipelineMonitor()
        monitor.record_metric("v", 5)
        assert (
            monitor.check_performance_threshold("v", threshold=5, operator=">=") is True
        )
        assert (
            monitor.check_performance_threshold("v", threshold=5, operator="<=") is True
        )

    def test_check_threshold_nonexistent_metric(self):
        """Non-existent metric returns False without error."""
        monitor = PipelineMonitor()
        assert (
            monitor.check_performance_threshold("ghost", threshold=1, operator=">")
            is False
        )

    def test_record_metric_stores_metadata(self):
        """Metadata is persisted alongside the metric value."""
        monitor = PipelineMonitor()
        monitor.record_metric("cpu", 80.0, {"host": "worker-1"})
        entry = monitor.metrics["cpu"][0]
        assert entry["metadata"]["host"] == "worker-1"

    def test_metrics_summary_count(self):
        """Summary count reflects the number of recorded data points."""
        monitor = PipelineMonitor()
        for _ in range(7):
            monitor.record_metric("req", 1.0)
        assert monitor.get_metrics_summary()["req"]["count"] == 7


# ==================== Monitoring: PerformanceProfiler Tests ====================


class TestPerformanceProfiler:
    """Tests for performance profiling."""

    def test_profiling(self):
        profiler = PerformanceProfiler()
        profiler.start_profiling("task1")
        time.sleep(0.1)
        duration = profiler.end_profiling("task1")
        assert duration > 0.05

    def test_profile_summary(self):
        profiler = PerformanceProfiler()
        profiler.start_profiling("task1")
        profiler.end_profiling("task1")
        summary = profiler.get_profile_summary()
        assert "task1" in summary["tasks"]

    def test_end_profiling_without_start_returns_zero(self):
        """end_profiling on an unstarted task returns 0 instead of raising."""
        profiler = PerformanceProfiler()
        duration = profiler.end_profiling("ghost_task")
        assert duration == 0

    def test_profiling_multiple_tasks(self):
        """Multiple tasks are independently tracked."""
        profiler = PerformanceProfiler()
        profiler.start_profiling("a")
        profiler.start_profiling("b")
        profiler.end_profiling("a", status="completed")
        profiler.end_profiling("b", status="failed")
        summary = profiler.get_profile_summary()
        assert "a" in summary["tasks"]
        assert "b" in summary["tasks"]
        assert summary["tasks"]["b"]["status"] == "failed"

    def test_profiling_total_duration(self):
        """Total duration is the sum of all individual task durations."""
        profiler = PerformanceProfiler()
        profiler.start_profiling("t1")
        time.sleep(0.05)
        d1 = profiler.end_profiling("t1")
        profiler.start_profiling("t2")
        time.sleep(0.05)
        d2 = profiler.end_profiling("t2")
        summary = profiler.get_profile_summary()
        assert summary["total_duration"] == pytest.approx(d1 + d2, abs=1e-4)

    def test_profile_summary_total_tasks(self):
        """total_tasks count matches the number of profiled tasks."""
        profiler = PerformanceProfiler()
        for i in range(5):
            profiler.start_profiling(f"task_{i}")
            profiler.end_profiling(f"task_{i}")
        assert profiler.get_profile_summary()["total_tasks"] == 5

    def test_profiling_status_stored(self):
        """Custom status is persisted in the profile summary."""
        profiler = PerformanceProfiler()
        profiler.start_profiling("step")
        profiler.end_profiling("step", status="skipped")
        summary = profiler.get_profile_summary()
        assert summary["tasks"]["step"]["status"] == "skipped"


# ==================== Monitoring: PipelineLogger Tests ====================


class TestPipelineLogger:
    """Tests for structured pipeline logging."""

    def test_logger_initialised(self):
        """PipelineLogger can be instantiated without error."""
        pl = PipelineLogger(name="test_logger")
        assert pl.logger is not None

    def test_log_task_start_does_not_raise(self):
        """log_task_start runs without raising."""
        pl = PipelineLogger(name="test_start")
        pl.log_task_start("my_task", params={"batch_size": 100})

    def test_log_task_end_does_not_raise(self):
        """log_task_end runs without raising."""
        pl = PipelineLogger(name="test_end")
        pl.log_task_end("my_task", status="success", duration_seconds=1.5)

    def test_log_data_quality_does_not_raise(self):
        """log_data_quality runs without raising."""
        pl = PipelineLogger(name="test_dq")
        pl.log_data_quality("preprocessing", record_count=500, quality_score=0.98)

    def test_log_error_does_not_raise(self):
        """log_error with a real exception runs without raising."""
        pl = PipelineLogger(name="test_err")
        try:
            raise RuntimeError("test error")
        except RuntimeError as exc:
            pl.log_error("failing_task", exc, context={"stage": "ingestion"})


# ==================== Monitoring: AnomalyAlert Tests ====================


class TestAnomalyAlert:
    """Tests for the AnomalyAlert alerting system."""

    def test_trigger_alert_info_does_not_raise(self):
        """INFO alert triggers without error when no integrations are configured."""
        alert = AnomalyAlert()
        alert.trigger_alert(AlertLevel.INFO, "Test Alert", "Everything is fine.")

    def test_trigger_alert_critical_does_not_raise(self):
        """CRITICAL alert triggers without error."""
        alert = AnomalyAlert()
        alert.trigger_alert(
            AlertLevel.CRITICAL,
            "Critical!",
            "System is down.",
            {"node": "n1"},
        )

    def test_trigger_alert_with_context(self):
        """Alert with context dict runs without error."""
        alert = AnomalyAlert()
        alert.trigger_alert(
            AlertLevel.WARNING,
            "High Latency",
            "P99 latency exceeded 500ms",
            context={"endpoint": "/api/recommend", "p99_ms": 520},
        )

    @patch("pipelines.monitoring.requests")
    def test_slack_alert_called_when_webhook_set(self, mock_requests):
        """Slack webhook is invoked when configured."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_requests.post.return_value = mock_response

        alert = AnomalyAlert(slack_webhook_url="https://hooks.slack.com/test")
        alert.trigger_alert(AlertLevel.ERROR, "DB Down", "Cannot reach database.")

        mock_requests.post.assert_called_once()

    def test_email_skipped_when_not_enabled(self):
        """Email is not attempted when enabled is not True."""
        alert = AnomalyAlert(
            email_config={"enabled": False, "smtp_server": "smtp.example.com"},
        )
        # Should not raise even though SMTP details are incomplete
        alert.trigger_alert(AlertLevel.INFO, "Test", "No email should be sent.")

    def test_alert_level_values(self):
        """AlertLevel enum has the expected string values."""
        assert AlertLevel.INFO.value == "INFO"
        assert AlertLevel.WARNING.value == "WARNING"
        assert AlertLevel.ERROR.value == "ERROR"
        assert AlertLevel.CRITICAL.value == "CRITICAL"

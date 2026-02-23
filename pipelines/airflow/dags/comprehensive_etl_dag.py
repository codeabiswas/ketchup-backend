"""
Comprehensive Ketchup Data Pipeline DAG

Pipeline stages:
1. Data Acquisition - Fetch from APIs
2. Data Preprocessing - Cleaning, transformation
3. Data Validation - Schema and quality checks
4. Anomaly Detection - Detect data issues
5. Bias Detection - Data slicing analysis
6. Statistics Generation - Data profiling
7. Storage - Persist to Firestore/BigQuery
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import numpy as np
import pandas as pd
from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.decorators import task

from config.settings import settings
from database.firestore_client import get_firestore_client
from pipelines.bias_detection import BiasAnalyzer, BiasMitigationStrategy, DataSlicer
from pipelines.monitoring import (
    AnomalyAlert,
    PerformanceProfiler,
    PipelineLogger,
    PipelineMonitor,
)

# Import pipeline components
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
from utils.api_clients import get_calendar_client, get_maps_client

# Configure logging
logger = logging.getLogger(__name__)
pipeline_logger = PipelineLogger("ketchup_pipeline", "logs/pipeline.log")
monitor = PipelineMonitor()
profiler = PerformanceProfiler()

# Airflow DAG Configuration
default_args = {
    "owner": "data-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry": False,
    "email": ["data-team@ketchup.com"],
    "start_date": datetime(2024, 1, 1),
}

dag = DAG(
    "ketchup_comprehensive_pipeline",
    default_args=default_args,
    description="Comprehensive data pipeline for Ketchup social coordination",
    schedule_interval="0 2 * * *",  # Daily at 2 AM UTC
    catchup=False,
    tags=["data-pipeline", "ketchup", "production"],
)


# ==================== Data Acquisition ====================


def acquire_calendar_data(**context) -> Dict[str, Any]:
    """Extract calendar data from all active users."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        calendar_client = get_calendar_client()
        firestore_client = get_firestore_client()

        # Get all active users
        users = firestore_client.get_all_users()
        logger.info(f"Found {len(users)} active users")

        calendar_data = []
        for user in users:
            try:
                # Fetch calendar availability
                availability = calendar_client.get_freebusy(
                    user_id=user.get("user_id"),
                    time_min=(datetime.now()).isoformat(),
                    time_max=(datetime.now() + timedelta(days=7)).isoformat(),
                )
                calendar_data.append(availability)
            except Exception as e:
                logger.warning(
                    f"Failed to fetch calendar for {user.get('user_id')}: {e}",
                )

        pipeline_logger.log_task_end(
            task_id,
            "success",
            profiler.end_profiling(task_id),
            {"record_count": len(calendar_data)},
        )

        # Push to XCom for next tasks
        context["task_instance"].xcom_push(key="calendar_data", value=calendar_data)
        return {"record_count": len(calendar_data), "status": "success"}

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Failed to acquire calendar data: {e}")


def acquire_venue_data(**context) -> Dict[str, Any]:
    """Extract venue data from Google Maps."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        maps_client = get_maps_client()
        # Locations (approximate centers)
        locations = {
            "Boston, MA": (42.3601, -71.0589),
            "Cambridge, MA": (42.3736, -71.1097),
            "Somerville, MA": (42.3876, -71.1000),
        }
        venue_categories = ["restaurant", "cafe", "bar"]

        venue_data = []

        for location_name, coords in locations.items():
            for category in venue_categories:
                try:
                    # Search venues via Google Maps
                    places = maps_client.search_places(
                        query=category,
                        location=coords,
                        radius=2000,
                    )
                    venue_data.extend(places)

                except Exception as e:
                    logger.warning(
                        f"Failed to fetch {category} venues in {location_name}: {e}",
                    )

        pipeline_logger.log_task_end(
            task_id,
            "success",
            profiler.end_profiling(task_id),
            {"record_count": len(venue_data)},
        )

        context["task_instance"].xcom_push(key="venue_data", value=venue_data)
        return {"record_count": len(venue_data), "status": "success"}

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Failed to acquire venue data: {e}")


# ==================== Data Preprocessing ====================


def preprocess_data(**context) -> Dict[str, Any]:
    """Preprocess and transform acquired data."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        task_instance = context["task_instance"]

        # Get data from previous tasks
        calendar_data = task_instance.xcom_pull(
            task_ids="acquire_calendar_data",
            key="calendar_data",
        )
        venue_data = task_instance.xcom_pull(
            task_ids="acquire_venue_data",
            key="venue_data",
        )

        logger.info(f"Processing {len(calendar_data)} calendar records")
        logger.info(f"Processing {len(venue_data)} venue records")

        # Aggregate calendar data
        df_calendar = DataAggregator.aggregate_calendar_data(calendar_data)

        # Aggregate venue data
        df_venues = DataAggregator.aggregate_venue_data(venue_data)

        # Clean data
        df_calendar = DataCleaner.remove_duplicates(df_calendar)
        df_calendar = DataCleaner.handle_missing_values(df_calendar, strategy="drop")

        df_venues = DataCleaner.remove_duplicates(df_venues, subset=["venue_id"])
        df_venues = DataCleaner.remove_outliers(
            df_venues,
            column="rating",
            method="iqr",
        )

        # Transform data
        df_venues = DataTransformer.normalize_numeric(
            df_venues,
            columns=["rating", "price_level"],
            method="minmax",
        )

        # Feature engineering
        df_venues = FeatureEngineer.create_venue_features(df_venues)

        pipeline_logger.log_task_end(
            task_id,
            "success",
            profiler.end_profiling(task_id),
            {
                "calendar_records": len(df_calendar),
                "venue_records": len(df_venues),
            },
        )

        # Store preprocessed data
        task_instance.xcom_push(
            key="preprocessed_calendar",
            value=df_calendar.to_dict(),
        )
        task_instance.xcom_push(key="preprocessed_venues", value=df_venues.to_dict())

        return {
            "calendar_records": len(df_calendar),
            "venue_records": len(df_venues),
            "status": "success",
        }

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Failed to preprocess data: {e}")


# ==================== Data Validation ====================


def validate_data_quality(**context) -> Dict[str, Any]:
    """Validate data schemas and quality."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        task_instance = context["task_instance"]

        # Get preprocessed data
        calendar_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_calendar",
        )
        venue_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_venues",
        )

        df_calendar = pd.DataFrame(calendar_dict)
        df_venues = pd.DataFrame(venue_dict)

        # Validate schemas
        calendar_schema = {
            "user_id": np.object_,
            "num_busy_intervals": np.int64,
            "availability_percentage": np.float64,
            "total_busy_hours": np.float64,
        }

        venue_schema = {
            "venue_id": np.object_,
            "name": np.object_,
            "rating": np.float64,
            "price_level": np.float64,
        }

        calendar_result = SchemaValidator.validate_schema(df_calendar, calendar_schema)
        venue_result = SchemaValidator.validate_schema(df_venues, venue_schema)

        # Validate ranges
        calendar_range = RangeValidator.validate_numeric_range(
            df_calendar,
            column="availability_percentage",
            min_value=0,
            max_value=100,
        )

        venue_range = RangeValidator.validate_numeric_range(
            df_venues,
            column="rating",
            min_value=0,
            max_value=5,
        )

        # Compile results
        all_passed = all(
            [
                calendar_result.passed,
                venue_result.passed,
                calendar_range.passed,
                venue_range.passed,
            ],
        )

        validation_report = {
            "calendar_schema_passed": calendar_result.passed,
            "venue_schema_passed": venue_result.passed,
            "calendar_range_passed": calendar_range.passed,
            "venue_range_passed": venue_range.passed,
            "all_passed": all_passed,
            "issues": [
                *calendar_result.issues,
                *venue_result.issues,
                *calendar_range.issues,
                *venue_range.issues,
            ],
        }

        quality_score = 100 if all_passed else 50
        pipeline_logger.log_data_quality(
            stage="validation",
            record_count=len(df_calendar) + len(df_venues),
            quality_score=quality_score,
            issues=validation_report["issues"],
        )

        pipeline_logger.log_task_end(
            task_id,
            "success",
            profiler.end_profiling(task_id),
            validation_report,
        )

        task_instance.xcom_push(key="validation_report", value=validation_report)

        if not all_passed:
            logger.warning(f"Data validation warnings: {validation_report['issues']}")

        return validation_report

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Data validation failed: {e}")


# ==================== Anomaly Detection ====================


def detect_anomalies(**context) -> Dict[str, Any]:
    """Detect anomalies in data."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        task_instance = context["task_instance"]

        # Get data
        calendar_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_calendar",
        )
        venue_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_venues",
        )

        df_calendar = pd.DataFrame(calendar_dict)
        df_venues = pd.DataFrame(venue_dict)

        # Detect anomalies
        calendar_missing = AnomalyDetector.detect_missing_values(df_calendar)
        calendar_duplicates = AnomalyDetector.detect_duplicates(df_calendar)
        venue_missing = AnomalyDetector.detect_missing_values(df_venues)
        venue_outliers = AnomalyDetector.detect_outliers(df_venues, column="rating")

        anomalies_detected = [
            not calendar_missing.passed,
            calendar_duplicates.issue_count > 0,
            not venue_missing.passed,
            not venue_outliers.passed,
        ]

        anomaly_report = {
            "timestamp": datetime.now().isoformat(),
            "calendar_missing_values": calendar_missing.issue_count,
            "calendar_duplicates": calendar_duplicates.issue_count,
            "venue_missing_values": venue_missing.issue_count,
            "venue_outliers": venue_outliers.issue_count,
            "anomalies_detected": any(anomalies_detected),
            "details": {
                "calendar_issues": calendar_missing.issues + calendar_duplicates.issues,
                "venue_issues": venue_missing.issues + venue_outliers.issues,
            },
        }

        monitor.record_metric(
            "anomalies_detected",
            int(any(anomalies_detected)),
            metadata={"stage": "anomaly_detection"},
        )

        pipeline_logger.log_task_end(
            task_id,
            "success",
            profiler.end_profiling(task_id),
            anomaly_report,
        )

        task_instance.xcom_push(key="anomaly_report", value=anomaly_report)

        return anomaly_report

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Anomaly detection failed: {e}")


# ==================== Bias Detection ====================


def detect_bias(**context) -> Dict[str, Any]:
    """Detect bias in data through data slicing."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        task_instance = context["task_instance"]

        # Get data
        venue_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_venues",
        )

        df_venues = pd.DataFrame(venue_dict)

        # Create demographic slices
        if "category" in df_venues.columns:
            slices = DataSlicer.slice_by_demographic(df_venues, "category")

            # Detect bias
            bias_metrics = BiasAnalyzer.detect_bias_in_slices(
                slices,
                target_column="rating",
                positive_label=1,
            )

            # Generate mitigation report
            biased_slices = [m.slice_name for m in bias_metrics if m.is_biased]
            mitigation_report = BiasMitigationStrategy.generate_mitigation_report(
                bias_metrics,
                biased_slices,
            )

            bias_report = {
                "timestamp": datetime.now().isoformat(),
                "bias_detected": mitigation_report["bias_detected"],
                "num_biased_slices": len(biased_slices),
                "total_slices": mitigation_report["total_slices_analyzed"],
                "recommendations": mitigation_report["recommendations"],
                "metrics": [
                    {
                        "slice": m.slice_name,
                        "metric": m.metric_name,
                        "value": m.value,
                        "is_biased": m.is_biased,
                    }
                    for m in bias_metrics
                ],
            }

            monitor.record_metric(
                "bias_detected",
                int(mitigation_report["bias_detected"]),
                metadata={"stage": "bias_detection"},
            )

            pipeline_logger.log_task_end(
                task_id,
                "success",
                profiler.end_profiling(task_id),
                bias_report,
            )

            task_instance.xcom_push(key="bias_report", value=bias_report)

            return bias_report
        else:
            logger.warning("No categorical column for bias analysis")
            return {"bias_detected": False}

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Bias detection failed: {e}")


# ==================== Statistics Generation ====================


def generate_statistics(**context) -> Dict[str, Any]:
    """Generate data statistics and profiles."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        task_instance = context["task_instance"]

        # Get data
        calendar_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_calendar",
        )
        venue_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_venues",
        )

        df_calendar = pd.DataFrame(calendar_dict)
        df_venues = pd.DataFrame(venue_dict)

        # Generate statistics
        calendar_stats = DataStatisticsGenerator.generate_statistics(df_calendar)
        venue_stats = DataStatisticsGenerator.generate_statistics(df_venues)

        # Save statistics
        DataStatisticsGenerator.save_statistics(
            calendar_stats,
            "data/statistics/calendar_stats.json",
        )
        DataStatisticsGenerator.save_statistics(
            venue_stats,
            "data/statistics/venue_stats.json",
        )

        stats_report = {
            "timestamp": datetime.now().isoformat(),
            "calendar_records": calendar_stats["record_count"],
            "venue_records": venue_stats["record_count"],
            "calendar_columns": calendar_stats["column_count"],
            "venue_columns": venue_stats["column_count"],
            "calendar_stats_saved": True,
            "venue_stats_saved": True,
        }

        pipeline_logger.log_task_end(
            task_id,
            "success",
            profiler.end_profiling(task_id),
            stats_report,
        )

        task_instance.xcom_push(key="statistics_report", value=stats_report)

        return stats_report

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Statistics generation failed: {e}")


# ==================== Data Storage ====================


def store_processed_data(**context) -> Dict[str, Any]:
    """Store processed data to Firestore and BigQuery."""
    task_id = context["task"].task_id
    pipeline_logger.log_task_start(task_id)
    profiler.start_profiling(task_id)

    try:
        task_instance = context["task_instance"]
        firestore_client = get_firestore_client()

        # Get preprocessed data
        calendar_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_calendar",
        )
        venue_dict = task_instance.xcom_pull(
            task_ids="preprocess_data",
            key="preprocessed_venues",
        )

        df_calendar = pd.DataFrame(calendar_dict)
        df_venues = pd.DataFrame(venue_dict)

        # Store to Firestore
        for _, row in df_calendar.iterrows():
            firestore_client.store_calendar_data(
                user_id=row.get("user_id"),
                data={
                    "availability_percentage": row.get("availability_percentage"),
                    "busy_intervals": row.get("num_busy_intervals"),
                    "timestamp": datetime.now().isoformat(),
                },
            )

        for _, row in df_venues.iterrows():
            firestore_client.store_venue_metadata(
                venue_id=row.get("venue_id"),
                data={
                    "name": row.get("name"),
                    "rating": row.get("rating"),
                    "price_level": row.get("price_level"),
                    "category": row.get("category"),
                    "timestamp": datetime.now().isoformat(),
                },
            )

        storage_report = {
            "timestamp": datetime.now().isoformat(),
            "calendar_records_stored": len(df_calendar),
            "venue_records_stored": len(df_venues),
            "status": "success",
        }

        pipeline_logger.log_task_end(
            task_id,
            "success",
            profiler.end_profiling(task_id),
            storage_report,
        )

        return storage_report

    except Exception as e:
        pipeline_logger.log_error(task_id, e)
        profiler.end_profiling(task_id, status="failed")
        raise AirflowException(f"Data storage failed: {e}")


# ==================== Pipeline Report Generation ====================


def generate_pipeline_report(**context) -> Dict[str, Any]:
    """Generate final pipeline execution report."""
    task_id = context["task"].task_id
    task_instance = context["task_instance"]

    try:
        # Collect all reports
        validation_report = task_instance.xcom_pull(
            task_ids="validate_data",
            key="validation_report",
        )
        anomaly_report = task_instance.xcom_pull(
            task_ids="detect_anomalies",
            key="anomaly_report",
        )
        bias_report = task_instance.xcom_pull(
            task_ids="detect_bias",
            key="bias_report",
        )
        stats_report = task_instance.xcom_pull(
            task_ids="generate_statistics",
            key="statistics_report",
        )

        # Get performance summary
        perf_summary = profiler.get_profile_summary()
        metrics_summary = monitor.get_metrics_summary()

        # Compile final report
        final_report = {
            "pipeline_run_date": datetime.now().isoformat(),
            "status": "completed",
            "validation": validation_report or {},
            "anomalies": anomaly_report or {},
            "bias": bias_report or {},
            "statistics": stats_report or {},
            "performance": perf_summary,
            "metrics": metrics_summary,
        }

        # Save report
        with open("data/reports/pipeline_report.json", "w") as f:
            json.dump(final_report, f, indent=2)

        logger.info("Pipeline execution completed successfully")
        return final_report

    except Exception as e:
        logger.error(f"Failed to generate pipeline report: {e}")
        raise AirflowException(f"Report generation failed: {e}")


# ==================== Task Definitions ====================

# Create tasks
task_acquire_calendar = PythonOperator(
    task_id="acquire_calendar_data",
    python_callable=acquire_calendar_data,
    dag=dag,
)

task_acquire_venues = PythonOperator(
    task_id="acquire_venue_data",
    python_callable=acquire_venue_data,
    dag=dag,
)

task_preprocess = PythonOperator(
    task_id="preprocess_data",
    python_callable=preprocess_data,
    dag=dag,
)

task_validate = PythonOperator(
    task_id="validate_data",
    python_callable=validate_data_quality,
    dag=dag,
)

task_anomalies = PythonOperator(
    task_id="detect_anomalies",
    python_callable=detect_anomalies,
    dag=dag,
)

task_bias = PythonOperator(
    task_id="detect_bias",
    python_callable=detect_bias,
    dag=dag,
)

task_synthetic_bias_eval = BashOperator(
    task_id="generate_synthetic_eval_data",
    bash_command='python {{ var.value.get("workspace_path", "/opt/airflow") }}/scripts/synthetic_bias_slicing_eval.py --n 50 --save-csv {{ var.value.get("workspace_path", "/opt/airflow") }}/data/raw/synthetic_eval_results.csv',
    dag=dag,
)

task_analyze_bias_slices = BashOperator(
    task_id="analyze_bias_slices",
    bash_command='python {{ var.value.get("workspace_path", "/opt/airflow") }}/scripts/bias_slice.py --csv {{ var.value.get("workspace_path", "/opt/airflow") }}/data/raw/synthetic_eval_results.csv --out {{ var.value.get("workspace_path", "/opt/airflow") }}/data/reports/bias_slicing_report.md',
    dag=dag,
)

task_fairlearn_bias_analysis = BashOperator(
    task_id="fairlearn_bias_analysis",
    bash_command='python {{ var.value.get("workspace_path", "/opt/airflow") }}/scripts/fairlearn_bias_slicing.py --csv {{ var.value.get("workspace_path", "/opt/airflow") }}/data/raw/synthetic_eval_results.csv > {{ var.value.get("workspace_path", "/opt/airflow") }}/data/reports/fairlearn_report.txt',
    dag=dag,
)

task_statistics = PythonOperator(
    task_id="generate_statistics",
    python_callable=generate_statistics,
    dag=dag,
)

task_storage = PythonOperator(
    task_id="store_data",
    python_callable=store_processed_data,
    dag=dag,
)

task_report = PythonOperator(
    task_id="generate_report",
    python_callable=generate_pipeline_report,
    dag=dag,
)

# ==================== Task Dependencies ====================

# Parallel data acquisition
[task_acquire_calendar, task_acquire_venues] >> task_preprocess

# Sequential processing pipeline
task_preprocess >> [
    task_validate,
    task_anomalies,
    task_bias,
    task_synthetic_bias_eval,
    task_statistics,
]

task_synthetic_bias_eval >> [task_analyze_bias_slices, task_fairlearn_bias_analysis]

# Final storage and reporting
(
    [
        task_validate,
        task_anomalies,
        task_bias,
        task_analyze_bias_slices,
        task_fairlearn_bias_analysis,
        task_statistics,
    ]
    >> task_storage
    >> task_report
)

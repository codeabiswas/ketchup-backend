"""Comprehensive ETL DAG with preprocessing, validation, and bias checks."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from airflow.utils.trigger_rule import TriggerRule

logger = logging.getLogger(__name__)

default_args = {
    "owner": "data-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "start_date": datetime(2024, 1, 1),
}

dag = DAG(
    "ketchup_comprehensive_pipeline",
    default_args=default_args,
    description="Comprehensive ETL pipeline for quality, anomaly, and bias analysis.",
    schedule_interval="0 3 * * *",
    catchup=False,
    tags=["data-pipeline", "quality", "bias"],
)


def acquire_data(**context) -> dict[str, int]:
    """Acquire calendar and venue snapshots for active users/groups."""
    from database.firestore_client import get_firestore_client
    from utils.api_clients import get_maps_client

    firestore_client = get_firestore_client()
    maps_client = get_maps_client()

    users = firestore_client.get_all_users(active_only=True)
    calendar_records: list[dict[str, object]] = []
    for user in users:
        calendar_doc = (
            firestore_client.db.collection("calendar_data")
            .document(user["user_id"])
            .get()
        )
        if calendar_doc.exists:
            calendar_records.append(calendar_doc.to_dict() or {})

    groups = firestore_client.db.collection("groups").where("active", "==", True).stream()
    venue_records: list[dict[str, object]] = []
    for group_doc in groups:
        group = group_doc.to_dict() or {}
        location = group.get("default_location") or group.get("location") or "Boston, MA"
        for category in ("restaurant", "cafe", "bar"):
            try:
                places = maps_client.search_places(category, str(location), max_results=4)
            except Exception as exc:
                logger.warning(
                    "Skipping maps query group=%s category=%s: %s",
                    group_doc.id,
                    category,
                    exc,
                )
                continue
            for place in places:
                venue_records.append(
                    {
                        **place,
                        "group_id": group_doc.id,
                        "category": category,
                    }
                )

    context["ti"].xcom_push(key="calendar_records", value=calendar_records)
    context["ti"].xcom_push(key="venue_records", value=venue_records)
    return {"calendar_records": len(calendar_records), "venue_records": len(venue_records)}


def preprocess_data(**context) -> dict[str, object]:
    """Run aggregator/cleaner/feature engineering transforms."""
    from pipelines.preprocessing import DataAggregator, DataCleaner, FeatureEngineer

    calendar_records = context["ti"].xcom_pull(
        task_ids="acquire_data",
        key="calendar_records",
    ) or []
    venue_records = context["ti"].xcom_pull(
        task_ids="acquire_data",
        key="venue_records",
    ) or []

    calendar_df = DataAggregator.aggregate_calendar_data(calendar_records)
    venues_df = DataAggregator.aggregate_venue_data(venue_records)

    if not calendar_df.empty:
        calendar_df = DataCleaner.handle_missing_values(calendar_df, strategy="fill", fill_value=0)
        calendar_df = FeatureEngineer.create_availability_features(calendar_df)
    if not venues_df.empty:
        venues_df = DataCleaner.remove_duplicates(venues_df, subset=["venue_id"])
        venues_df = DataCleaner.handle_missing_values(venues_df, strategy="fill", fill_value=0)
        venues_df = FeatureEngineer.create_venue_features(venues_df)

    calendar_rows = calendar_df.to_dict(orient="records")
    venue_rows = venues_df.to_dict(orient="records")
    context["ti"].xcom_push(key="calendar_preprocessed", value=calendar_rows)
    context["ti"].xcom_push(key="venue_preprocessed", value=venue_rows)

    return {"calendar_rows": len(calendar_rows), "venue_rows": len(venue_rows)}


def validate_data(**context) -> dict[str, object]:
    """Run schema/range/anomaly checks over preprocessed data."""
    import pandas as pd

    from pipelines.validation import AnomalyDetector, RangeValidator, SchemaValidator

    venue_rows = context["ti"].xcom_pull(task_ids="preprocess_data", key="venue_preprocessed") or []
    venues_df = pd.DataFrame(venue_rows)

    issues: list[str] = []
    if venues_df.empty:
        issues.append("No venue rows available after preprocessing.")
    else:
        schema_result = SchemaValidator.validate_required_fields(
            venues_df,
            required_fields=["venue_id", "name", "rating"],
        )
        if not schema_result.passed:
            issues.extend(schema_result.issues)

        range_result = RangeValidator.validate_numeric_range(
            venues_df,
            column="rating",
            min_value=0.0,
            max_value=5.0,
        )
        if not range_result.passed:
            issues.extend(range_result.issues)

        anomaly_result = AnomalyDetector.detect_duplicates(venues_df, subset=["venue_id"])
        if not anomaly_result.passed:
            issues.extend(anomaly_result.issues)

    result = {"passed": len(issues) == 0, "issues": issues}
    context["ti"].xcom_push(key="validation_report", value=result)
    return result


def should_run_extended_bias_analysis(**context) -> bool:
    """Gate heavy bias analysis with Airflow variable."""
    raw = Variable.get("run_extended_bias_analysis", default_var="false")
    return str(raw).lower() in {"1", "true", "yes", "on"}


def detect_bias(**context) -> dict[str, object]:
    """Run slice-based bias checks when enabled."""
    import pandas as pd

    from pipelines.bias_detection import BiasAnalyzer, BiasMitigationStrategy, DataSlicer

    venue_rows = context["ti"].xcom_pull(task_ids="preprocess_data", key="venue_preprocessed") or []
    if not venue_rows:
        return {"bias_detected": False, "reason": "no_venue_rows"}

    df = pd.DataFrame(venue_rows)
    if "category" not in df.columns or "rating" not in df.columns:
        return {"bias_detected": False, "reason": "missing_columns"}

    df["positive"] = (df["rating"].fillna(0) >= 4.0).astype(int)
    slices = DataSlicer.slice_by_demographic(df, "category")
    metrics = BiasAnalyzer.detect_bias_in_slices(
        slices=slices,
        target_column="positive",
        positive_label=1,
    )
    biased_slices = sorted({m.slice_name for m in metrics if m.is_biased})
    report = BiasMitigationStrategy.generate_mitigation_report(metrics, biased_slices)
    context["ti"].xcom_push(key="bias_report", value=report)
    return report


def generate_report(**context) -> dict[str, object]:
    """Generate final pipeline report artifact."""
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "acquisition": context["ti"].xcom_pull(task_ids="acquire_data"),
        "preprocessing": context["ti"].xcom_pull(task_ids="preprocess_data"),
        "validation": context["ti"].xcom_pull(task_ids="validate_data", key="validation_report"),
        "bias": context["ti"].xcom_pull(task_ids="detect_bias", key="bias_report"),
    }

    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pipeline_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Wrote pipeline report: %s", out_path)
    return report


acquire_task = PythonOperator(
    task_id="acquire_data",
    python_callable=acquire_data,
    dag=dag,
)

preprocess_task = PythonOperator(
    task_id="preprocess_data",
    python_callable=preprocess_data,
    dag=dag,
)

validate_task = PythonOperator(
    task_id="validate_data",
    python_callable=validate_data,
    dag=dag,
)

bias_gate_task = ShortCircuitOperator(
    task_id="should_run_extended_bias_analysis",
    python_callable=should_run_extended_bias_analysis,
    dag=dag,
)

bias_task = PythonOperator(
    task_id="detect_bias",
    python_callable=detect_bias,
    dag=dag,
)

report_task = PythonOperator(
    task_id="generate_report",
    python_callable=generate_report,
    trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    dag=dag,
)

acquire_task >> preprocess_task >> validate_task
validate_task >> bias_gate_task >> bias_task >> report_task
validate_task >> report_task

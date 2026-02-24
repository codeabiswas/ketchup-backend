"""Daily ETL DAG for availability and venue enrichment."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

default_args = {
    "owner": "ketchup-data-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2026, 1, 26),
}

dag = DAG(
    "daily_etl_pipeline",
    default_args=default_args,
    description="Daily ETL pipeline for user availability and venue metadata.",
    schedule_interval="0 2 * * *",
    catchup=False,
    tags=["data-pipeline", "etl"],
)


def extract_calendar_data(**context) -> dict[str, int]:
    """Extract and persist user busy intervals from Google Calendar."""
    from database.firestore_client import get_firestore_client
    from utils.api_clients import get_calendar_client

    firestore_client = get_firestore_client()
    calendar_client = get_calendar_client()

    now = datetime.utcnow()
    window_end = now + timedelta(days=30)

    extracted = 0
    skipped = 0

    for user in firestore_client.get_all_users(active_only=True):
        user_id = user.get("user_id")
        user_email = user.get("email")
        token = user.get("google_access_token")

        if not user_id or not user_email or not token:
            skipped += 1
            continue

        try:
            calendar_client.set_auth_token(token)
            busy = calendar_client.get_freebusy(
                user_email=user_email,
                time_min=now,
                time_max=window_end,
            )
            firestore_client.store_calendar_data(
                user_id=user_id,
                calendar_data={
                    "user_id": user_id,
                    "email": user_email,
                    "busy": busy,
                    "retrieved_at": datetime.utcnow().isoformat(),
                },
            )
            extracted += 1
        except Exception as exc:
            logger.warning("Calendar extraction failed for user_id=%s: %s", user_id, exc)

    result = {"extracted": extracted, "skipped": skipped}
    context["ti"].xcom_push(key="calendar_extract", value=result)
    return result


def extract_venue_data(**context) -> dict[str, int]:
    """Extract venue candidates from Google Maps Text Search."""
    from database.firestore_client import get_firestore_client
    from utils.api_clients import get_maps_client

    firestore_client = get_firestore_client()
    maps_client = get_maps_client()

    categories = ["restaurant", "cafe", "bar", "park", "museum"]
    inserted = 0

    groups = firestore_client.db.collection("groups").where("active", "==", True).stream()
    for group_doc in groups:
        group = group_doc.to_dict() or {}
        location = group.get("default_location") or group.get("location") or "Boston, MA"
        for category in categories:
            try:
                places = maps_client.search_places(
                    query=category,
                    location=str(location),
                    max_results=5,
                )
            except Exception as exc:
                logger.warning(
                    "Venue extraction failed for group=%s category=%s: %s",
                    group_doc.id,
                    category,
                    exc,
                )
                continue

            for place in places:
                venue_id = place.get("place_id")
                if not venue_id:
                    continue
                firestore_client.store_venue_metadata(
                    venue_id=venue_id,
                    venue_data={
                        **place,
                        "group_id": group_doc.id,
                        "category_query": category,
                    },
                )
                inserted += 1

    result = {"venues_inserted": inserted}
    context["ti"].xcom_push(key="venue_extract", value=result)
    return result


def normalize_and_validate(**context) -> dict[str, int]:
    """Normalize and validate venue records in Firestore."""
    from database.firestore_client import get_firestore_client
    from utils.data_normalizer import DataNormalizer, DataValidator

    firestore_client = get_firestore_client()

    valid = 0
    invalid = 0

    for venue_doc in firestore_client.db.collection("venues").stream():
        venue_data = venue_doc.to_dict() or {}
        try:
            normalized = DataNormalizer.normalize_google_place(venue_data)
            if DataValidator.validate_venue_metadata(normalized):
                firestore_client.db.collection("venues").document(venue_doc.id).set(
                    normalized.model_dump(mode="json"),
                    merge=True,
                )
                valid += 1
            else:
                invalid += 1
        except Exception:
            invalid += 1

    result = {"valid": valid, "invalid": invalid}
    context["ti"].xcom_push(key="validation", value=result)
    return result


def report_metrics(**context) -> dict[str, object]:
    """Write ETL metrics snapshot to Firestore."""
    from database.firestore_client import get_firestore_client

    firestore_client = get_firestore_client()
    users_count = len(list(firestore_client.db.collection("users").stream()))
    groups_count = len(list(firestore_client.db.collection("groups").stream()))
    venues_count = len(list(firestore_client.db.collection("venues").stream()))

    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "users_count": users_count,
        "groups_count": groups_count,
        "venues_count": venues_count,
        "calendar_extract": context["ti"].xcom_pull(
            task_ids="extract_calendar_data",
            key="calendar_extract",
        ),
        "venue_extract": context["ti"].xcom_pull(
            task_ids="extract_venue_data",
            key="venue_extract",
        ),
        "validation": context["ti"].xcom_pull(
            task_ids="normalize_and_validate",
            key="validation",
        ),
        "pipeline_status": "success",
    }
    firestore_client.db.collection("pipeline_metrics").add(metrics)
    return metrics


extract_calendar_task = PythonOperator(
    task_id="extract_calendar_data",
    python_callable=extract_calendar_data,
    dag=dag,
)

extract_venues_task = PythonOperator(
    task_id="extract_venue_data",
    python_callable=extract_venue_data,
    dag=dag,
)

normalize_task = PythonOperator(
    task_id="normalize_and_validate",
    python_callable=normalize_and_validate,
    dag=dag,
)

metrics_task = PythonOperator(
    task_id="report_metrics",
    python_callable=report_metrics,
    dag=dag,
)

[extract_calendar_task, extract_venues_task] >> normalize_task >> metrics_task

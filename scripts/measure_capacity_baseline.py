from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPORT_SCHEMA = "capacity-baseline-report.v1"
INPUT_SCHEMA = "capacity-baseline-input.v1"
ALLOWED_CLASSIFICATIONS = {
    "representative_integration_database",
    "operational_read_only_snapshot",
}
REQUIRED_LIMITS = {
    "live_capture_concurrency",
    "live_session_concurrency",
    "render_concurrency",
    "browser_use_concurrency",
    "workflow_worker_concurrency",
}
REQUIRED_FORECAST_SIGNALS = {
    "assets",
    "recording_hours",
    "events",
    "artifacts_bytes",
    "workflows",
}
REQUIRED_APPROVALS = {"engineering", "data", "operations"}


class CapacityMeasurementError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_report_fingerprint(report: dict[str, Any]) -> bool:
    claimed = report.get("report_fingerprint")
    unsigned = dict(report)
    unsigned.pop("report_fingerprint", None)
    return isinstance(claimed, str) and claimed == _canonical_fingerprint(unsigned)


def _one(
    connection: Any, statement: str, parameters: tuple[Any, ...] = ()
) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(statement, parameters)
        row = cursor.fetchone()
    if row is None:
        raise CapacityMeasurementError("capacity query returned no row")
    return _json_value(dict(row))


def _many(
    connection: Any,
    statement: str,
    parameters: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(statement, parameters)
        return [_json_value(dict(row)) for row in cursor.fetchall()]


def _max_concurrency(
    connection: Any,
    *,
    relation: str,
    start_column: str,
    end_column: str,
    window_start: datetime,
    window_end: datetime,
    where: str = "true",
) -> int:
    allowed = {
        ("live_capture_sessions", "observed_started_at", "observed_ended_at"),
        ("live_sessions", "actual_start_at", "actual_end_at"),
        ("video_production_jobs", "started_at", "completed_at"),
        ("workflow_runs", "started_at", "completed_at"),
        ("maitu_workbench_draft_execution_jobs", "started_at", "completed_at"),
    }
    if (relation, start_column, end_column) not in allowed:
        raise CapacityMeasurementError("unsupported concurrency relation")
    statement = f"""
        WITH intervals AS (
            SELECT greatest({start_column}, %s) AS starts_at,
                   least(coalesce({end_column}, %s), %s) AS ends_at
            FROM {relation}
            WHERE {where} AND {start_column} IS NOT NULL
              AND {start_column} < %s
              AND coalesce({end_column}, %s) > %s
        ), boundaries AS (
            SELECT starts_at AS boundary_at, 1 AS delta FROM intervals
            UNION ALL
            SELECT ends_at AS boundary_at, -1 AS delta FROM intervals
        ), grouped AS (
            SELECT boundary_at, sum(delta) AS delta
            FROM boundaries GROUP BY boundary_at
        ), running AS (
            SELECT sum(delta) OVER (ORDER BY boundary_at ROWS UNBOUNDED PRECEDING) AS value
            FROM grouped
        )
        SELECT coalesce(max(value), 0)::integer AS maximum FROM running
    """
    result = _one(
        connection,
        statement,
        (window_start, window_end, window_end, window_end, window_end, window_start),
    )
    return int(result["maximum"])


def _asset_metrics(
    connection: Any, window_start: datetime, window_end: datetime
) -> dict[str, Any]:
    totals = _one(
        connection,
        """
        SELECT count(*) AS total_rows,
               count(*) FILTER (WHERE deleted_at IS NULL) AS non_deleted,
               count(*) FILTER (
                   WHERE deleted_at IS NULL AND archived_at IS NULL
               ) AS active,
               count(*) FILTER (WHERE archived_at IS NOT NULL) AS archived,
               count(*) FILTER (WHERE deleted_at IS NOT NULL) AS deleted,
               coalesce(sum(file_size) FILTER (WHERE deleted_at IS NULL), 0) AS catalog_bytes
        FROM assets
        """,
    )
    additions = _many(
        connection,
        """
        SELECT date_trunc('day', created_at) AS day, count(*) AS added
        FROM assets
        WHERE created_at >= %s AND created_at < %s
        GROUP BY day ORDER BY day
        """,
        (window_start, window_end),
    )
    return {"totals": totals, "daily_additions_utc": additions}


def _capture_metrics(
    connection: Any,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    totals = _one(
        connection,
        """
        SELECT count(*) FILTER (
                   WHERE observed_started_at < %s
                     AND coalesce(observed_ended_at, %s) > %s
               ) AS sessions_overlapping_window,
               count(*) FILTER (
                   WHERE status IN ('starting', 'recording', 'finalizing')
               ) AS currently_active,
               coalesce(sum(
                   extract(epoch FROM (
                       least(coalesce(observed_ended_at, %s), %s)
                       - greatest(observed_started_at, %s)
                   )) / 3600
               ) FILTER (
                   WHERE observed_started_at < %s
                     AND coalesce(observed_ended_at, %s) > %s
               ), 0) AS recording_hours_in_window
        FROM live_capture_sessions
        """,
        (
            window_end,
            window_end,
            window_start,
            window_end,
            window_end,
            window_start,
            window_end,
            window_end,
            window_start,
        ),
    )
    daily = _many(
        connection,
        """
        WITH days AS (
            SELECT generate_series(
                date_trunc('day', %s::timestamptz),
                date_trunc('day', %s::timestamptz - interval '1 microsecond'),
                interval '1 day'
            ) AS day
        )
        SELECT day,
               coalesce(sum(
                   extract(epoch FROM (
                       least(coalesce(session.observed_ended_at, %s), day + interval '1 day')
                       - greatest(session.observed_started_at, day)
                   )) / 3600
               ) FILTER (
                   WHERE session.observed_started_at < day + interval '1 day'
                     AND coalesce(session.observed_ended_at, %s) > day
               ), 0) AS recording_hours
        FROM days
        LEFT JOIN live_capture_sessions AS session
          ON session.observed_started_at < day + interval '1 day'
         AND coalesce(session.observed_ended_at, %s) > day
        GROUP BY day ORDER BY day
        """,
        (window_start, window_end, window_end, window_end, window_end),
    )
    return {
        "totals": totals,
        "daily_recording_hours_utc": daily,
        "peak_concurrent_capture": _max_concurrency(
            connection,
            relation="live_capture_sessions",
            start_column="observed_started_at",
            end_column="observed_ended_at",
            window_start=window_start,
            window_end=window_end,
        ),
    }


def _event_metrics(
    connection: Any, window_start: datetime, window_end: datetime
) -> dict[str, Any]:
    standard = _one(
        connection,
        """
        WITH event_buckets AS (
            SELECT date_trunc('second', event_time) AS second, count(*) AS count
            FROM standard_events
            WHERE event_time >= %s AND event_time < %s
            GROUP BY second
        ), processing_buckets AS (
            SELECT date_trunc('second', processing_time) AS second, count(*) AS count
            FROM standard_events
            WHERE processing_time >= %s AND processing_time < %s
            GROUP BY second
        )
        SELECT (
                   SELECT count(*) FROM standard_events
                   WHERE event_time >= %s AND event_time < %s
               ) AS event_count,
               coalesce((SELECT max(count) FROM event_buckets), 0) AS peak_event_time_eps,
               coalesce((SELECT max(count) FROM processing_buckets), 0) AS peak_processing_time_eps,
               (
                   SELECT count(*) FROM standard_events
                   WHERE quality_status = 'quarantined'
                     AND processing_time >= %s AND processing_time < %s
               ) AS quarantined_count
        """,
        (
            window_start,
            window_end,
            window_start,
            window_end,
            window_start,
            window_end,
            window_start,
            window_end,
        ),
    )
    raw = _one(
        connection,
        """
        SELECT count(*) FILTER (
                   WHERE created_at >= %s AND created_at < %s
               ) AS batches_created,
               coalesce(sum(event_count) FILTER (
                   WHERE created_at >= %s AND created_at < %s
               ), 0) AS events_in_batches,
               count(*) FILTER (WHERE status <> 'finalized') AS current_backlog_batches,
               coalesce(sum(event_count) FILTER (WHERE status <> 'finalized'), 0)
                   AS current_backlog_events,
               coalesce(max(
                   event_count / greatest(
                       extract(epoch FROM (last_received_at - first_received_at)), 1
                   )
               ) FILTER (
                   WHERE created_at >= %s AND created_at < %s
                     AND first_received_at IS NOT NULL AND last_received_at IS NOT NULL
               ), 0) AS maximum_batch_average_receive_eps
        FROM live_raw_event_batches
        """,
        (
            window_start,
            window_end,
            window_start,
            window_end,
            window_start,
            window_end,
        ),
    )
    return {
        "standard_events_exact": standard,
        "raw_batches": raw,
        "raw_batch_rate_semantics": (
            "maximum batch-average receive rate; never treated as an exact per-second peak"
        ),
    }


def _live_session_metrics(
    connection: Any,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    totals = _one(
        connection,
        """
        SELECT count(*) FILTER (
                   WHERE actual_start_at < %s
                     AND coalesce(actual_end_at, %s) > %s
                     AND deleted_at IS NULL
               ) AS sessions_overlapping_window,
               count(*) FILTER (
                   WHERE actual_start_at IS NOT NULL AND actual_end_at IS NULL
                     AND deleted_at IS NULL
               ) AS currently_active
        FROM live_sessions
        """,
        (window_end, window_end, window_start),
    )
    return {
        "totals": totals,
        "peak_concurrent_live_sessions": _max_concurrency(
            connection,
            relation="live_sessions",
            start_column="actual_start_at",
            end_column="actual_end_at",
            where="deleted_at IS NULL",
            window_start=window_start,
            window_end=window_end,
        ),
    }


def _render_metrics(
    connection: Any, window_start: datetime, window_end: datetime
) -> dict[str, Any]:
    totals = _one(
        connection,
        """
        SELECT count(*) FILTER (
                   WHERE created_at >= %s AND created_at < %s
               ) AS jobs_created,
               count(*) FILTER (WHERE status = 'running') AS currently_running,
               count(*) FILTER (
                   WHERE status = 'succeeded' AND completed_at >= %s AND completed_at < %s
               ) AS succeeded,
               count(*) FILTER (
                   WHERE status = 'failed' AND completed_at >= %s AND completed_at < %s
               ) AS failed,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM (completed_at - started_at))
               ) FILTER (
                   WHERE started_at IS NOT NULL AND completed_at IS NOT NULL
                     AND completed_at >= %s AND completed_at < %s
               ) AS duration_p50_seconds,
               percentile_cont(0.95) WITHIN GROUP (
                   ORDER BY extract(epoch FROM (completed_at - started_at))
               ) FILTER (
                   WHERE started_at IS NOT NULL AND completed_at IS NOT NULL
                     AND completed_at >= %s AND completed_at < %s
               ) AS duration_p95_seconds
        FROM video_production_jobs
        """,
        (
            window_start,
            window_end,
            window_start,
            window_end,
            window_start,
            window_end,
            window_start,
            window_end,
            window_start,
            window_end,
        ),
    )
    daily = _many(
        connection,
        """
        SELECT date_trunc('day', created_at) AS day, count(*) AS jobs_created
        FROM video_production_jobs
        WHERE created_at >= %s AND created_at < %s
        GROUP BY day ORDER BY day
        """,
        (window_start, window_end),
    )
    return {
        "totals": totals,
        "daily_jobs_utc": daily,
        "peak_concurrent_render_jobs": _max_concurrency(
            connection,
            relation="video_production_jobs",
            start_column="started_at",
            end_column="completed_at",
            window_start=window_start,
            window_end=window_end,
        ),
    }


def _artifact_metrics(
    connection: Any, window_start: datetime, window_end: datetime
) -> dict[str, Any]:
    totals = _one(
        connection,
        """
        SELECT count(*) AS artifact_count,
               coalesce(sum(byte_size), 0) AS artifact_bytes,
               count(*) FILTER (WHERE NOT content_addressed) AS non_content_addressed,
               count(*) FILTER (WHERE storage_uri !~ '^s3://') AS non_s3_uri_count
        FROM artifact_refs
        """,
    )
    by_retention = _many(
        connection,
        """
        SELECT retention_policy_code, sensitivity, count(*) AS artifact_count,
               coalesce(sum(byte_size), 0) AS artifact_bytes
        FROM artifact_refs
        GROUP BY retention_policy_code, sensitivity
        ORDER BY retention_policy_code, sensitivity
        """,
    )
    daily = _many(
        connection,
        """
        SELECT date_trunc('day', created_at) AS day, count(*) AS artifacts_created,
               coalesce(sum(byte_size), 0) AS bytes_created
        FROM artifact_refs
        WHERE created_at >= %s AND created_at < %s
        GROUP BY day ORDER BY day
        """,
        (window_start, window_end),
    )
    return {
        "totals": totals,
        "by_retention_and_sensitivity": by_retention,
        "daily_growth_utc": daily,
    }


def _workflow_metrics(
    connection: Any, window_start: datetime, window_end: datetime
) -> dict[str, Any]:
    totals = _one(
        connection,
        """
        SELECT count(*) AS total_workflows,
               count(*) FILTER (
                   WHERE created_at >= %s AND created_at < %s
               ) AS workflows_created,
               count(*) FILTER (WHERE status = 'queued') AS current_queue_depth,
               count(*) FILTER (WHERE status = 'running') AS currently_running,
               count(*) FILTER (WHERE status = 'waiting_human') AS waiting_human,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM (completed_at - started_at))
               ) FILTER (
                   WHERE started_at IS NOT NULL AND completed_at IS NOT NULL
                     AND completed_at >= %s AND completed_at < %s
               ) AS duration_p50_seconds,
               percentile_cont(0.95) WITHIN GROUP (
                   ORDER BY extract(epoch FROM (completed_at - started_at))
               ) FILTER (
                   WHERE started_at IS NOT NULL AND completed_at IS NOT NULL
                     AND completed_at >= %s AND completed_at < %s
               ) AS duration_p95_seconds
        FROM workflow_runs
        """,
        (
            window_start,
            window_end,
            window_start,
            window_end,
            window_start,
            window_end,
        ),
    )
    steps = _one(
        connection,
        """
        SELECT count(*) FILTER (WHERE status = 'queued') AS queued_steps,
               count(*) FILTER (WHERE status = 'running') AS leased_steps,
               count(*) FILTER (
                   WHERE status = 'running' AND lease_expires_at < now()
               ) AS expired_running_leases
        FROM workflow_steps
        """,
    )
    return {
        "totals": totals,
        "steps": steps,
        "peak_concurrent_workflows": _max_concurrency(
            connection,
            relation="workflow_runs",
            start_column="started_at",
            end_column="completed_at",
            window_start=window_start,
            window_end=window_end,
        ),
    }


def _browser_use_metrics(
    connection: Any,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    active = _one(
        connection,
        """
        SELECT (
                   SELECT count(*) FROM maitu_workbench_draft_execution_jobs
                   WHERE status = 'running' AND lease_expires_at > now()
               ) AS active_draft_leases,
               (
                   SELECT count(*) FROM maitu_execution_retry_tasks
                   WHERE status = 'in_progress' AND deleted_at IS NULL
                     AND claim_expires_at > now()
               ) AS active_retry_leases,
               (
                   SELECT count(*) FROM maitu_workbench_draft_execution_jobs
                   WHERE status = 'running' AND lease_expires_at <= now()
               ) AS expired_draft_leases,
               (
                   SELECT count(*) FROM maitu_execution_retry_tasks
                   WHERE status = 'in_progress' AND deleted_at IS NULL
                     AND claim_expires_at <= now()
               ) AS expired_retry_leases
        """,
    )
    observed_draft_peak = _max_concurrency(
        connection,
        relation="maitu_workbench_draft_execution_jobs",
        start_column="started_at",
        end_column="completed_at",
        window_start=window_start,
        window_end=window_end,
    )
    return {
        "current_leases": active,
        "observed_draft_execution_peak": observed_draft_peak,
        "historical_limit": None,
        "historical_limit_reason": (
            "Lease rows do not preserve every reclaimed retry interval; the approved configured "
            "account/room cap must come from the capacity input contract."
        ),
    }


def measure_database(
    connection: Any,
    *,
    expected_database: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    identity = _one(
        connection,
        """
        SELECT current_database() AS database_name,
               current_setting('server_version') AS server_version,
               pg_is_in_recovery() AS in_recovery,
               pg_database_size(current_database()) AS database_size_bytes
        """,
    )
    if identity["database_name"] != expected_database:
        raise CapacityMeasurementError(
            f"database identity mismatch: expected {expected_database}, got {identity['database_name']}"
        )
    return {
        "identity": identity,
        "window": {
            "start": _json_value(window_start),
            "end": _json_value(window_end),
            "duration_days": (window_end - window_start).total_seconds() / 86400,
            "timezone": "UTC",
            "interval_semantics": "half-open [start,end)",
        },
        "assets": _asset_metrics(connection, window_start, window_end),
        "recordings": _capture_metrics(connection, window_start, window_end),
        "events": _event_metrics(connection, window_start, window_end),
        "live_sessions": _live_session_metrics(connection, window_start, window_end),
        "renders": _render_metrics(connection, window_start, window_end),
        "artifacts": _artifact_metrics(connection, window_start, window_end),
        "workflows": _workflow_metrics(connection, window_start, window_end),
        "browser_use": _browser_use_metrics(connection, window_start, window_end),
    }


def load_capacity_input(path: Path | None) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, ["approved capacity input was not supplied"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, [f"capacity input is unreadable: {error}"]
    errors: list[str] = []
    if payload.get("schema_version") != INPUT_SCHEMA:
        errors.append("capacity input schema_version is invalid")

    limits = payload.get("configured_limits")
    if not isinstance(limits, dict):
        errors.append("configured_limits must be an object")
    else:
        for key in sorted(REQUIRED_LIMITS):
            value = limits.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.append(f"configured_limits.{key} must be a positive integer")

    forecasts = payload.get("forecast")
    if not isinstance(forecasts, dict):
        errors.append("forecast must be an object")
    else:
        for key in sorted(REQUIRED_FORECAST_SIGNALS):
            item = forecasts.get(key)
            if not isinstance(item, dict):
                errors.append(f"forecast.{key} must be an object")
                continue
            for field in ("annual_growth_rate", "peak_factor"):
                value = item.get(field)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < 0
                ):
                    errors.append(f"forecast.{key}.{field} must be non-negative")

    unit_costs = payload.get("unit_costs")
    if not isinstance(unit_costs, list) or not unit_costs:
        errors.append("unit_costs must be a non-empty list")
    elif any(
        not isinstance(item, dict)
        or not str(item.get("cost_code") or "").strip()
        or not isinstance(item.get("amount"), (int, float))
        or isinstance(item.get("amount"), bool)
        or item["amount"] < 0
        or not str(item.get("currency") or "").strip()
        or not str(item.get("source_ref") or "").strip()
        for item in unit_costs
    ):
        errors.append(
            "every unit_cost must have code, non-negative amount, currency and source_ref"
        )

    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, list) or not thresholds:
        errors.append("thresholds must be a non-empty list")
    elif any(
        not isinstance(item, dict)
        or not str(item.get("signal") or "").strip()
        or not isinstance(item.get("warning"), (int, float))
        or not isinstance(item.get("stop"), (int, float))
        or item["warning"] < 0
        or item["stop"] < item["warning"]
        or not str(item.get("owner") or "").strip()
        for item in thresholds
    ):
        errors.append("every threshold must have signal, warning <= stop and owner")

    approvals = payload.get("approvals")
    if not isinstance(approvals, dict):
        errors.append("approvals must be an object")
    else:
        for role in sorted(REQUIRED_APPROVALS):
            item = approvals.get(role)
            if (
                not isinstance(item, dict)
                or not str(item.get("owner") or "").strip()
                or not str(item.get("decision_ref") or "").strip()
                or item.get("decision") != "approved"
            ):
                errors.append(
                    f"approvals.{role} must contain an approved owner/decision_ref"
                )
    return _json_value(payload), errors


def reconcile_object_storage(
    connection: Any,
    *,
    endpoint: str | None,
    bucket: str | None,
    access_key: str | None,
    secret_key: str | None,
    secure: bool,
    max_objects: int,
) -> dict[str, Any]:
    if not all((endpoint, bucket, access_key, secret_key)):
        return {
            "status": "not_run",
            "passed": False,
            "reason": "object-store endpoint, bucket or ephemeral credentials were not supplied",
        }
    from minio import Minio

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT storage_uri, byte_size FROM artifact_refs ORDER BY storage_uri"
        )
        rows = cursor.fetchall()
    expected: dict[str, int] = {}
    unsupported_uri_count = 0
    for storage_uri, byte_size in rows:
        parsed = urlparse(str(storage_uri))
        if (
            parsed.scheme != "s3"
            or parsed.netloc != bucket
            or not parsed.path.lstrip("/")
        ):
            unsupported_uri_count += 1
            continue
        expected[parsed.path.lstrip("/")] = int(byte_size)
    if len(expected) > max_objects:
        raise CapacityMeasurementError(
            "artifact reference count exceeds --max-object-scan"
        )

    client = Minio(
        endpoint, access_key=access_key, secret_key=secret_key, secure=secure
    )
    observed: dict[str, int] = {}
    for item in client.list_objects(bucket, recursive=True):
        observed[str(item.object_name)] = int(item.size or 0)
        if len(observed) > max_objects:
            raise CapacityMeasurementError(
                "object-store count exceeds --max-object-scan"
            )
    missing = set(expected) - set(observed)
    unmatched = set(observed) - set(expected)
    size_mismatch = {
        key for key in set(expected) & set(observed) if expected[key] != observed[key]
    }
    passed = (
        not missing
        and not unmatched
        and not size_mismatch
        and unsupported_uri_count == 0
    )
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "endpoint": endpoint,
        "bucket": bucket,
        "secure": secure,
        "artifact_ref_object_count": len(expected),
        "artifact_ref_bytes": sum(expected.values()),
        "object_store_current_count": len(observed),
        "object_store_current_bytes": sum(observed.values()),
        "missing_object_count": len(missing),
        "unmatched_object_count": len(unmatched),
        "size_mismatch_count": len(size_mismatch),
        "unsupported_uri_count": unsupported_uri_count,
        "object_names_retained": False,
        "credentials_retained": False,
    }


def build_report(
    *,
    database_url: str,
    expected_database: str,
    classification: str,
    source_snapshot_ref: str | None,
    window_start: datetime,
    window_end: datetime,
    capacity_input_path: Path | None,
    object_store: dict[str, Any],
) -> dict[str, Any]:
    import psycopg

    if classification not in ALLOWED_CLASSIFICATIONS:
        raise CapacityMeasurementError("unsupported measurement classification")
    if (
        window_start.tzinfo is None
        or window_end.tzinfo is None
        or window_start >= window_end
    ):
        raise CapacityMeasurementError(
            "measurement window must be a valid timezone-aware interval"
        )
    started_at = _utc_now()
    capacity_input, input_errors = load_capacity_input(capacity_input_path)
    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '120s'")
            cursor.execute("SET LOCAL timezone = 'UTC'")
        database = measure_database(
            connection,
            expected_database=expected_database,
            window_start=window_start,
            window_end=window_end,
        )
        object_reconciliation = reconcile_object_storage(connection, **object_store)
        connection.rollback()

    window_days = (window_end - window_start).total_seconds() / 86400
    gates = {
        "operational_classification": classification
        == "operational_read_only_snapshot",
        "source_snapshot_attested": bool(source_snapshot_ref),
        "minimum_seven_day_window": window_days >= 7,
        "approved_capacity_input": not input_errors,
        "object_storage_reconciled": object_reconciliation["passed"],
        "database_measurement_complete": True,
    }
    qualifies = all(gates.values())
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "status": "passed",
        "classification": classification,
        "source_snapshot_ref": source_snapshot_ref,
        "database_measurement": database,
        "object_storage_reconciliation": object_reconciliation,
        "capacity_input": capacity_input,
        "capacity_input_errors": input_errors,
        "qualification_gates": gates,
        "credentials_retained": False,
        "raw_business_rows_retained": False,
        "known_limits": [
            "Integration fixtures validate the collector only and never establish operational capacity."
            if classification == "representative_integration_database"
            else "This point-in-time baseline must be repeated when workload shape or topology changes."
        ],
        "qualifies_for_chk_0110": qualifies,
    }
    report["report_fingerprint"] = _canonical_fingerprint(report)
    return _json_value(report)


def _parse_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a timezone")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure AssetGraph operational capacity using read-only queries"
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("ASSETGRAPH_DATABASE_URL"),
        help="Database DSN; defaults to ASSETGRAPH_DATABASE_URL and is never reported",
    )
    parser.add_argument("--expected-database", required=True)
    parser.add_argument(
        "--classification", choices=sorted(ALLOWED_CLASSIFICATIONS), required=True
    )
    parser.add_argument("--source-snapshot-ref")
    parser.add_argument("--window-start", type=_parse_datetime)
    parser.add_argument("--window-end", type=_parse_datetime)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--capacity-input", type=Path)
    parser.add_argument("--object-store-endpoint")
    parser.add_argument("--object-store-bucket")
    parser.add_argument(
        "--object-store-access-key-env", default="ASSETGRAPH_MINIO_ACCESS_KEY"
    )
    parser.add_argument(
        "--object-store-secret-key-env", default="ASSETGRAPH_MINIO_SECRET_KEY"
    )
    parser.add_argument("--object-store-secure", action="store_true")
    parser.add_argument("--max-object-scan", type=int, default=1_000_000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.database_url:
        raise SystemExit("database URL is required")
    if args.window_days < 1:
        raise SystemExit("--window-days must be positive")
    if args.max_object_scan < 1:
        raise SystemExit("--max-object-scan must be positive")
    window_end = args.window_end or datetime.now(UTC)
    window_start = args.window_start or (window_end - timedelta(days=args.window_days))
    if args.window_start is not None and args.window_end is None:
        window_end = args.window_start + timedelta(days=args.window_days)
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"report already exists: {args.output}")
    try:
        report = build_report(
            database_url=args.database_url,
            expected_database=args.expected_database,
            classification=args.classification,
            source_snapshot_ref=args.source_snapshot_ref,
            window_start=window_start,
            window_end=window_end,
            capacity_input_path=args.capacity_input,
            object_store={
                "endpoint": args.object_store_endpoint,
                "bucket": args.object_store_bucket,
                "access_key": os.getenv(args.object_store_access_key_env),
                "secret_key": os.getenv(args.object_store_secret_key_env),
                "secure": args.object_store_secure,
                "max_objects": args.max_object_scan,
            },
        )
    except CapacityMeasurementError as error:
        raise SystemExit(str(error)) from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"status={report['status']} qualifies_for_chk_0110="
        f"{str(report['qualifies_for_chk_0110']).lower()} output={args.output}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

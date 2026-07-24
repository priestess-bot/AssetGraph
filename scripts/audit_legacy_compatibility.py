from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "legacy-compatibility-audit.v1"
ALLOWED_CLASSIFICATIONS = {
    "representative_integration_database",
    "production_sanitized_copy",
    "production_encrypted_copy",
}
EXPECTED_VIEWS = (
    "legacy_asset_observations_v1",
    "legacy_content_project_projections_v1",
    "legacy_live_room_variant_projections_v1",
    "legacy_layout_hypothesis_projections_v1",
    "legacy_delivery_unknown_projections_v1",
    "legacy_workflow_run_projections_v1",
    "legacy_workflow_step_projections_v1",
)
REQUIRED_WORKFLOW_SOURCE_TYPES = (
    "maitu_workbench_run",
    "video_production_job",
    "live_capture_session",
    "live_clip_job",
    "live_analysis_run",
    "maitu_retry_task",
)
REQUIRED_DOMAIN_PROJECTIONS = (
    "legacy_asset_observations_v1",
    "legacy_content_project_projections_v1",
    "legacy_live_room_variant_projections_v1",
    "legacy_layout_hypothesis_projections_v1",
    "legacy_delivery_unknown_projections_v1",
)
CANONICAL_FACT_TABLES = (
    "content_projects",
    "production_variants",
    "workflow_runs",
    "releases",
    "delivery_attempts",
    "content_exposure_events",
)
SOURCE_COUNT_SQL = {
    "maitu_workbench_run": "SELECT count(*) FROM maitu_workbench_runs",
    "video_production_job": "SELECT count(*) FROM video_production_jobs",
    "live_capture_session": "SELECT count(*) FROM live_capture_sessions",
    "live_clip_job": "SELECT count(*) FROM live_clip_jobs",
    "live_analysis_run": "SELECT count(*) FROM live_analysis_runs",
    "maitu_retry_task": (
        "SELECT count(*) FROM maitu_execution_retry_tasks WHERE deleted_at IS NULL"
    ),
}
STEP_SOURCE_COUNT_SQL = {
    "maitu_workbench_run": "SELECT count(*) FROM maitu_workbench_runs",
    "video_production_stage": "SELECT count(*) FROM video_production_stages",
    "live_capture_session": "SELECT count(*) FROM live_capture_sessions",
    "live_clip_job": "SELECT count(*) FROM live_clip_jobs",
    "live_analysis_run": "SELECT count(*) FROM live_analysis_runs",
    "maitu_retry_task": (
        "SELECT count(*) FROM maitu_execution_retry_tasks WHERE deleted_at IS NULL"
    ),
}
DOMAIN_ENDPOINTS = {
    "legacy_asset_observations_v1": "/api/compatibility/assets",
    "legacy_content_project_projections_v1": "/api/compatibility/content-projects",
    "legacy_live_room_variant_projections_v1": "/api/compatibility/live-room-variants",
    "legacy_layout_hypothesis_projections_v1": "/api/compatibility/layout-hypotheses",
    "legacy_delivery_unknown_projections_v1": "/api/compatibility/delivery-unknown",
}


class CompatibilityAuditError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_report_fingerprint(report: dict[str, Any]) -> bool:
    claimed = report.get("report_fingerprint")
    unsigned = dict(report)
    unsigned.pop("report_fingerprint", None)
    return isinstance(claimed, str) and claimed == _canonical_fingerprint(unsigned)


def _migration_checksums() -> dict[str, str]:
    required_prefixes = ("036_", "040_")
    result: dict[str, str] = {}
    for path in sorted((REPO_ROOT / "backend" / "migrations").glob("*.sql")):
        if path.name.startswith(required_prefixes):
            result[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(result) != len(required_prefixes):
        raise CompatibilityAuditError("required compatibility migrations are missing")
    return result


def _scalar(connection: Any, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters)
        row = cursor.fetchone()
    if row is None:
        raise CompatibilityAuditError("audit query returned no row")
    return row[0]


def _group_counts(connection: Any, statement: str) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(statement)
        return {str(row[0]): int(row[1]) for row in cursor.fetchall()}


def _table_counts(connection: Any, table_names: tuple[str, ...]) -> dict[str, int]:
    from psycopg import sql

    result: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table_name in table_names:
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name))
            )
            result[table_name] = int(cursor.fetchone()[0])
    return result


def _assertion(code: str, invalid_count: int, detail: str) -> dict[str, Any]:
    return {
        "code": code,
        "passed": invalid_count == 0,
        "invalid_count": invalid_count,
        "detail": detail,
    }


def _sql_assertions(connection: Any) -> list[dict[str, Any]]:
    checks = (
        (
            "workflow_semantics_are_explicit",
            """
            SELECT count(*) FROM legacy_workflow_run_projections_v1
            WHERE NOT read_only OR mapping_quality <> 'legacy_import'
               OR jsonb_typeof(source_snapshot) <> 'object'
               OR status NOT IN (
                   'queued', 'running', 'waiting_human', 'succeeded', 'failed',
                   'cancelled', 'reconcile_required'
               )
            """,
            "Every legacy workflow is read-only, legacy_import and explicitly mapped.",
        ),
        (
            "workflow_steps_are_read_only_and_parented",
            """
            SELECT count(*) FROM legacy_workflow_step_projections_v1 AS step
            LEFT JOIN legacy_workflow_run_projections_v1 AS run
              ON run.projection_run_code = step.projection_run_code
            WHERE NOT step.read_only OR run.projection_run_code IS NULL
               OR jsonb_typeof(step.source_snapshot) <> 'object'
            """,
            "Every projected step is read-only and belongs to a projected run.",
        ),
        (
            "workflow_codes_are_unique",
            """
            SELECT count(*) FROM (
                SELECT projection_run_code FROM legacy_workflow_run_projections_v1
                GROUP BY projection_run_code HAVING count(*) <> 1
            ) AS duplicates
            """,
            "Workflow projection codes are unique across all legacy queues.",
        ),
        (
            "asset_geometry_remains_observation",
            """
            SELECT count(*) FROM legacy_asset_observations_v1
            WHERE NOT read_only OR is_constraint OR is_user_group
               OR geometry_semantics <> 'observed_legacy_placement'
               OR duplicate_group_semantics <> 'legacy_duplicate_candidate'
               OR mapping_quality <> 'legacy_import'
            """,
            "Geometry and duplicate groups remain observations, never constraints/groups.",
        ),
        (
            "content_missing_provenance_is_explicit",
            """
            SELECT count(*) FROM legacy_content_project_projections_v1
            WHERE NOT read_only OR mapping_quality <> 'legacy_import'
               OR jsonb_typeof(missing_provenance) <> 'array'
               OR jsonb_array_length(missing_provenance) = 0
               OR NOT (missing_provenance ? 'confirmed_content_project_revision')
            """,
            "Synthetic content roots retain a non-empty missing-provenance list.",
        ),
        (
            "variant_verification_requires_explicit_links",
            """
            SELECT count(*) FROM legacy_live_room_variant_projections_v1
            WHERE NOT read_only OR carrier_kind <> 'live_room'
               OR mapping_quality NOT IN ('verified', 'legacy_import')
               OR ((mapping_quality = 'verified') IS DISTINCT FROM (
                   variant_code IS NOT NULL AND variant_revision IS NOT NULL
                   AND configuration_code IS NOT NULL
                   AND configuration_revision IS NOT NULL
               ))
            """,
            "A legacy live-room variant is verified only when both explicit links exist.",
        ),
        (
            "layout_hypothesis_stays_reference_only",
            """
            SELECT count(*) FROM legacy_layout_hypothesis_projections_v1
            WHERE NOT read_only OR contract_version <> 'layout-hypothesis.v1'
               OR reference_mode <> 'reference_only'
               OR layout_fidelity <> 'approximate'
               OR buildability <> 'reference_only'
               OR conversion_allowed OR mapping_quality <> 'descriptive_only'
            """,
            "Legacy layout hypotheses are approximate, non-convertible references.",
        ),
        (
            "legacy_completion_never_fabricates_delivery",
            """
            SELECT count(*) FROM legacy_delivery_unknown_projections_v1
            WHERE NOT read_only OR delivery_semantics <> 'legacy_delivery_unknown'
               OR release_code IS NOT NULL OR delivery_code IS NOT NULL
               OR external_identity IS NOT NULL OR readback_evidence IS NOT NULL
               OR is_actual_delivery OR is_exposure
            """,
            "Legacy completion never becomes Release, Delivery or Exposure evidence.",
        ),
    )
    return [
        _assertion(code, int(_scalar(connection, statement)), detail)
        for code, statement, detail in checks
    ]


def _relation_guard_audit(connection: Any) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT c.relname AS view_name, c.relkind,
                   obj_description(c.oid, 'pg_class') AS comment,
                   count(t.oid) FILTER (
                       WHERE NOT t.tgisinternal
                         AND t.tgname = 'trg_' || c.relname || '_read_only'
                         AND t.tgenabled IN ('O', 'A')
                   ) AS enabled_read_only_triggers
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            LEFT JOIN pg_trigger AS t ON t.tgrelid = c.oid
            WHERE n.nspname = 'public' AND c.relname = ANY(%s)
            GROUP BY c.relname, c.relkind, c.oid
            ORDER BY c.relname
            """,
            (list(EXPECTED_VIEWS),),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    by_name = {row["view_name"]: row for row in rows}
    missing = sorted(set(EXPECTED_VIEWS) - set(by_name))
    invalid = sorted(
        name
        for name, row in by_name.items()
        if row["relkind"] != "v"
        or not row["comment"]
        or int(row["enabled_read_only_triggers"]) != 1
    )
    return {
        "passed": not missing and not invalid,
        "expected_count": len(EXPECTED_VIEWS),
        "observed_count": len(rows),
        "missing_views": missing,
        "invalid_guard_views": invalid,
        "views": [
            {
                "view_name": row["view_name"],
                "relation_kind": row["relkind"],
                "has_semantic_comment": bool(row["comment"]),
                "enabled_read_only_triggers": int(row["enabled_read_only_triggers"]),
            }
            for row in rows
        ],
    }


def _migration_audit(connection: Any) -> dict[str, Any]:
    expected = _migration_checksums()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT migration_name, checksum_sha256
            FROM assetgraph_schema_migrations
            WHERE migration_name = ANY(%s)
            ORDER BY migration_name
            """,
            (list(expected),),
        )
        actual = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
    mismatches = sorted(
        name for name, checksum in expected.items() if actual.get(name) != checksum
    )
    return {
        "passed": not mismatches and len(actual) == len(expected),
        "expected": expected,
        "observed": actual,
        "mismatches": mismatches,
    }


def _cardinality_audit(connection: Any) -> dict[str, Any]:
    source_counts = {
        source_type: int(_scalar(connection, statement))
        for source_type, statement in SOURCE_COUNT_SQL.items()
    }
    projected_counts = _group_counts(
        connection,
        """
        SELECT source_type, count(*)
        FROM legacy_workflow_run_projections_v1
        GROUP BY source_type
        """,
    )
    normalized_projection_counts = {
        source_type: projected_counts.get(source_type, 0)
        for source_type in SOURCE_COUNT_SQL
    }
    run_mismatches = {
        source_type: {
            "source": source_counts[source_type],
            "projection": normalized_projection_counts[source_type],
        }
        for source_type in SOURCE_COUNT_SQL
        if source_counts[source_type] != normalized_projection_counts[source_type]
    }

    step_source_counts = {
        source_type: int(_scalar(connection, statement))
        for source_type, statement in STEP_SOURCE_COUNT_SQL.items()
    }
    projected_step_counts = _group_counts(
        connection,
        """
        SELECT source_type, count(*)
        FROM legacy_workflow_step_projections_v1
        GROUP BY source_type
        """,
    )
    normalized_step_counts = {
        source_type: projected_step_counts.get(source_type, 0)
        for source_type in STEP_SOURCE_COUNT_SQL
    }
    step_mismatches = {
        source_type: {
            "source": step_source_counts[source_type],
            "projection": normalized_step_counts[source_type],
        }
        for source_type in STEP_SOURCE_COUNT_SQL
        if step_source_counts[source_type] != normalized_step_counts[source_type]
    }

    domain_counts = {
        view_name: int(_scalar(connection, f"SELECT count(*) FROM {view_name}"))
        for view_name in REQUIRED_DOMAIN_PROJECTIONS
    }
    missing_workflow_samples = sorted(
        source_type
        for source_type in REQUIRED_WORKFLOW_SOURCE_TYPES
        if source_counts[source_type] == 0
    )
    missing_domain_samples = sorted(
        view_name for view_name, count in domain_counts.items() if count == 0
    )
    return {
        "passed": not run_mismatches and not step_mismatches,
        "workflow_sources": source_counts,
        "workflow_projections": normalized_projection_counts,
        "workflow_mismatches": run_mismatches,
        "step_sources": step_source_counts,
        "step_projections": normalized_step_counts,
        "step_mismatches": step_mismatches,
        "domain_projections": domain_counts,
        "representative_sample_coverage": {
            "passed": not missing_workflow_samples and not missing_domain_samples,
            "missing_workflow_source_types": missing_workflow_samples,
            "missing_domain_projections": missing_domain_samples,
        },
    }


def _request_json(
    *,
    url: str,
    token: str,
    expected_status: int = 200,
) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read()
    except urllib.error.URLError as error:
        raise CompatibilityAuditError(
            f"compatibility API is unavailable: {error.reason}"
        ) from error
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise CompatibilityAuditError(
            "compatibility API returned non-JSON content"
        ) from error
    if status != expected_status:
        raise CompatibilityAuditError(
            f"compatibility API returned {status}, expected {expected_status}: {url}"
        )
    return status, payload


def _paged_api_rows(*, base_url: str, path: str, token: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"limit": 100, "offset": offset})
        _, payload = _request_json(
            url=f"{base_url.rstrip('/')}{path}?{query}",
            token=token,
        )
        if not isinstance(payload, list) or not all(
            isinstance(row, dict) for row in payload
        ):
            raise CompatibilityAuditError(
                f"compatibility API list contract failed: {path}"
            )
        rows.extend(payload)
        if len(payload) < 100:
            break
        offset += len(payload)
    return rows


def _api_audit(
    *,
    base_url: str,
    token: str,
    expected_workflow_count: int,
    expected_domain_counts: dict[str, int],
) -> dict[str, Any]:
    endpoint_results: list[dict[str, Any]] = []
    workflow_rows = _paged_api_rows(
        base_url=base_url,
        path="/api/compatibility/workflow-runs",
        token=token,
    )
    endpoint_results.append(
        {
            "path": "/api/compatibility/workflow-runs",
            "expected_count": expected_workflow_count,
            "observed_count": len(workflow_rows),
            "all_read_only": all(row.get("read_only") is True for row in workflow_rows),
        }
    )
    detail_source_types: list[str] = []
    for source_type in sorted({str(row["source_type"]) for row in workflow_rows}):
        sample = next(row for row in workflow_rows if row["source_type"] == source_type)
        projection_code = urllib.parse.quote(
            str(sample["projection_run_code"]), safe=""
        )
        _, detail = _request_json(
            url=(
                f"{base_url.rstrip('/')}/api/compatibility/workflow-runs/"
                f"{projection_code}"
            ),
            token=token,
        )
        if not isinstance(detail, dict) or detail.get("read_only") is not True:
            raise CompatibilityAuditError("compatibility API detail contract failed")
        steps = detail.get("steps")
        if (
            not isinstance(steps, list)
            or not steps
            or not all(
                isinstance(step, dict) and step.get("read_only") is True
                for step in steps
            )
        ):
            raise CompatibilityAuditError("compatibility API step contract failed")
        detail_source_types.append(source_type)

    for view_name, path in DOMAIN_ENDPOINTS.items():
        rows = _paged_api_rows(base_url=base_url, path=path, token=token)
        endpoint_results.append(
            {
                "path": path,
                "expected_count": expected_domain_counts[view_name],
                "observed_count": len(rows),
                "all_read_only": all(row.get("read_only") is True for row in rows),
            }
        )

    missing_code = "LEGACY-AUDIT-NOT-FOUND"
    _, missing_payload = _request_json(
        url=(f"{base_url.rstrip('/')}/api/compatibility/workflow-runs/{missing_code}"),
        token=token,
        expected_status=404,
    )
    if not isinstance(missing_payload, dict):
        raise CompatibilityAuditError("compatibility API error contract failed")
    detail = missing_payload.get("detail")
    problem_code = None
    if isinstance(detail, dict):
        problem_code = detail.get("code")
    if problem_code is None:
        problem_code = missing_payload.get("code")

    endpoint_passed = all(
        result["expected_count"] == result["observed_count"] and result["all_read_only"]
        for result in endpoint_results
    )
    stable_not_found = problem_code == "LEGACY_WORKFLOW_PROJECTION_NOT_FOUND"
    return {
        "passed": endpoint_passed
        and stable_not_found
        and set(detail_source_types) == set(REQUIRED_WORKFLOW_SOURCE_TYPES),
        "base_url": base_url,
        "authentication": "bearer token supplied through environment; value not retained",
        "endpoints": endpoint_results,
        "detail_source_types": detail_source_types,
        "stable_not_found": {
            "status": 404,
            "code": problem_code,
            "passed": stable_not_found,
        },
    }


def audit_database(
    *,
    database_url: str,
    expected_database: str,
    classification: str,
    api_base_url: str,
    operator_token: str,
) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    if classification not in ALLOWED_CLASSIFICATIONS:
        raise CompatibilityAuditError("unsupported compatibility audit classification")
    started_at = _utc_now()
    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute(
                """
                SELECT current_database() AS database_name,
                       current_setting('server_version') AS server_version,
                       pg_is_in_recovery() AS in_recovery
                """
            )
            identity = dict(cursor.fetchone())
        if identity["database_name"] != expected_database:
            raise CompatibilityAuditError(
                "database identity mismatch: "
                f"expected {expected_database}, got {identity['database_name']}"
            )
        migration_audit = _migration_audit(connection)
        relation_guards = _relation_guard_audit(connection)
        cardinality = _cardinality_audit(connection)
        assertions = _sql_assertions(connection)
        canonical_before = _table_counts(connection, CANONICAL_FACT_TABLES)
        connection.rollback()

    api_audit = _api_audit(
        base_url=api_base_url,
        token=operator_token,
        expected_workflow_count=sum(cardinality["workflow_projections"].values()),
        expected_domain_counts=cardinality["domain_projections"],
    )

    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
        canonical_after = _table_counts(connection, CANONICAL_FACT_TABLES)
        connection.rollback()

    canonical_unchanged = canonical_before == canonical_after
    sample_coverage = cardinality["representative_sample_coverage"]
    passed = all(
        (
            migration_audit["passed"],
            relation_guards["passed"],
            cardinality["passed"],
            sample_coverage["passed"],
            all(assertion["passed"] for assertion in assertions),
            api_audit["passed"],
            canonical_unchanged,
        )
    )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "status": "passed" if passed else "failed",
        "classification": classification,
        "database": identity,
        "migration_audit": migration_audit,
        "relation_guards": relation_guards,
        "cardinality": cardinality,
        "semantic_assertions": assertions,
        "api_audit": api_audit,
        "canonical_fact_write_check": {
            "passed": canonical_unchanged,
            "before": canonical_before,
            "after": canonical_after,
        },
        "raw_business_rows_retained": False,
        "credentials_retained": False,
        "known_limits": [
            (
                "Representative integration data proves compatibility contracts and old "
                "repository/API behavior; it is not a production volume or data-quality claim."
            )
            if classification == "representative_integration_database"
            else (
                "Production-derived classification does not by itself satisfy the separate "
                "CHK-0260 migration timing/lock approval gate."
            )
        ],
        "qualifies_for_chk_0294": passed,
    }
    report["report_fingerprint"] = _canonical_fingerprint(report)
    return report


def write_report(path: Path, report: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise CompatibilityAuditError(f"report already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit read-only legacy compatibility projections and API contracts"
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("ASSETGRAPH_DATABASE_URL"),
        help="Database DSN; defaults to ASSETGRAPH_DATABASE_URL",
    )
    parser.add_argument("--expected-database", required=True)
    parser.add_argument(
        "--classification",
        choices=sorted(ALLOWED_CLASSIFICATIONS),
        required=True,
    )
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument(
        "--operator-token-env",
        default="ASSETGRAPH_CONSOLE_OPERATOR_TOKEN",
        help="Environment variable containing the bearer token; the value is never reported",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.database_url:
        raise SystemExit("database URL is required")
    operator_token = os.getenv(args.operator_token_env)
    if not operator_token:
        raise SystemExit(
            f"operator token environment variable is required: {args.operator_token_env}"
        )
    try:
        report = audit_database(
            database_url=args.database_url,
            expected_database=args.expected_database,
            classification=args.classification,
            api_base_url=args.api_base_url,
            operator_token=operator_token,
        )
        write_report(args.output, report, overwrite=args.overwrite)
    except CompatibilityAuditError as error:
        raise SystemExit(str(error)) from error
    print(
        f"status={report['status']} qualifies_for_chk_0294="
        f"{str(report['qualifies_for_chk_0294']).lower()} output={args.output}"
    )
    return 0 if report["qualifies_for_chk_0294"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

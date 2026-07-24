from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__:
    from .apply_migrations import apply_migrations, database_url, discover_migrations
else:
    from apply_migrations import apply_migrations, database_url, discover_migrations


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_COPY_CLASSIFICATIONS = {
    "production_sanitized_copy",
    "production_encrypted_copy",
}
COPY_CLASSIFICATIONS = REAL_COPY_CLASSIFICATIONS | {"synthetic_fixture"}
DEFAULT_EXACT_COUNT_TABLES = (
    "assets",
    "maitu_workbench_runs",
    "video_production_jobs",
    "live_room_template_revisions",
    "live_capture_sessions",
    "live_analysis_runs",
    "maitu_workbench_video_analyses",
    "jd_live_metric_samples",
)
IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")


class RehearsalSafetyError(RuntimeError):
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


def validate_copy_attestation(
    *,
    copy_classification: str,
    source_snapshot_ref: str | None,
    sanitization_evidence_ref: str | None,
) -> None:
    if copy_classification not in COPY_CLASSIFICATIONS:
        raise RehearsalSafetyError("unsupported migration copy classification")
    if copy_classification in REAL_COPY_CLASSIFICATIONS and not source_snapshot_ref:
        raise RehearsalSafetyError("a real-copy rehearsal requires source_snapshot_ref")
    if copy_classification == "production_sanitized_copy" and not sanitization_evidence_ref:
        raise RehearsalSafetyError(
            "a sanitized production copy requires sanitization_evidence_ref"
        )
    if copy_classification == "synthetic_fixture" and (
        source_snapshot_ref or sanitization_evidence_ref
    ):
        raise RehearsalSafetyError(
            "synthetic fixtures cannot claim production snapshot or sanitization evidence"
        )


def _migration_ledger(connection: Any) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT to_regclass('public.assetgraph_schema_migrations') IS NOT NULL AS exists"
        )
        if not cursor.fetchone()["exists"]:
            return []
        cursor.execute(
            """
            SELECT migration_name, checksum_sha256, applied_at
            FROM assetgraph_schema_migrations
            ORDER BY migration_name
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def _schema_objects(connection: Any) -> dict[str, list[dict[str, Any]]]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT table_name, column_name, ordinal_position, data_type,
                   udt_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """
        )
        columns = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT c.conname AS constraint_name, c.contype AS constraint_type,
                   c.convalidated AS validated, c.conrelid::regclass::text AS relation_name,
                   pg_get_constraintdef(c.oid, true) AS definition
            FROM pg_constraint AS c
            JOIN pg_namespace AS n ON n.oid = c.connamespace
            WHERE n.nspname = 'public'
            ORDER BY relation_name, constraint_name
            """
        )
        constraints = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT tablename AS table_name, indexname AS index_name, indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname
            """
        )
        indexes = [dict(row) for row in cursor.fetchall()]
    return {"columns": columns, "constraints": constraints, "indexes": indexes}


def _exact_counts(connection: Any, tables: tuple[str, ...]) -> dict[str, int | None]:
    from psycopg import sql

    counts: dict[str, int | None] = {}
    with connection.cursor() as cursor:
        for table in tables:
            if not IDENTIFIER_PATTERN.fullmatch(table):
                raise RehearsalSafetyError(f"invalid exact-count table identifier: {table}")
            cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
            if cursor.fetchone()[0] is None:
                counts[table] = None
                continue
            cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            counts[table] = int(cursor.fetchone()[0])
    return counts


def database_snapshot(connection: Any, *, exact_count_tables: tuple[str, ...]) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT current_database() AS database_name,
                   current_setting('server_version') AS server_version,
                   pg_database_size(current_database()) AS database_size_bytes,
                   pg_is_in_recovery() AS in_recovery,
                   (
                       SELECT count(*)
                       FROM pg_stat_activity
                       WHERE datname = current_database() AND pid <> pg_backend_pid()
                   ) AS other_session_count
            """
        )
        identity = dict(cursor.fetchone())
        cursor.execute(
            """
            SELECT c.relname AS table_name,
                   pg_total_relation_size(c.oid) AS total_bytes,
                   pg_relation_size(c.oid) AS heap_bytes,
                   pg_indexes_size(c.oid) AS index_bytes,
                   c.reltuples::bigint AS estimated_rows,
                   coalesce(s.n_live_tup, 0) AS observed_live_rows,
                   coalesce(s.n_dead_tup, 0) AS observed_dead_rows
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables AS s ON s.relid = c.oid
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
            ORDER BY c.relname
            """
        )
        table_stats = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT count(*) FILTER (WHERE NOT i.indisvalid) AS invalid_indexes,
                   count(*) FILTER (WHERE NOT i.indisready) AS unready_indexes
            FROM pg_index AS i
            JOIN pg_class AS c ON c.oid = i.indrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
            """
        )
        index_health = dict(cursor.fetchone())
        cursor.execute(
            """
            SELECT count(*) AS unvalidated_constraints
            FROM pg_constraint AS c
            JOIN pg_namespace AS n ON n.oid = c.connamespace
            WHERE n.nspname = 'public' AND NOT c.convalidated
            """
        )
        constraint_health = dict(cursor.fetchone())

    schema_objects = _schema_objects(connection)
    return {
        "captured_at": _utc_now(),
        "identity": identity,
        "schema_fingerprint": _canonical_fingerprint(schema_objects),
        "migration_ledger": _migration_ledger(connection),
        "table_stats": table_stats,
        "exact_counts": _exact_counts(connection, exact_count_tables),
        "index_health": index_health,
        "constraint_health": constraint_health,
    }


def load_invariant_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "migration-invariants.v1":
        raise RehearsalSafetyError("unsupported migration invariant schema")
    assertions = payload.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise RehearsalSafetyError("migration invariant contract has no assertions")
    codes: set[str] = set()
    for assertion in assertions:
        if not isinstance(assertion, dict):
            raise RehearsalSafetyError("migration invariant assertion must be an object")
        code = assertion.get("code")
        statement = str(assertion.get("sql") or "").strip()
        if not isinstance(code, str) or not IDENTIFIER_PATTERN.fullmatch(code):
            raise RehearsalSafetyError("migration invariant code is invalid")
        if code in codes:
            raise RehearsalSafetyError(f"duplicate migration invariant code: {code}")
        if ";" in statement or not re.match(r"^(SELECT|WITH)\b", statement, re.IGNORECASE):
            raise RehearsalSafetyError(
                f"migration invariant {code} must be one read-only statement"
            )
        codes.add(code)
    return payload


def execute_invariants(connection: Any, contract: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            for assertion in contract["assertions"]:
                cursor.execute(assertion["sql"])
                row = cursor.fetchone()
                if row is None or len(row) != 1:
                    raise RehearsalSafetyError(
                        f"migration invariant {assertion['code']} must return one scalar"
                    )
                actual = row[0]
                expected = assertion["expected"]
                results.append(
                    {
                        "code": assertion["code"],
                        "expected": expected,
                        "actual": actual,
                        "passed": actual == expected,
                    }
                )
    finally:
        connection.rollback()
    return results


class LockMonitor:
    def __init__(self, dsn: str, *, application_name: str, sample_interval_ms: int) -> None:
        self.dsn = dsn
        self.application_name = application_name
        self.sample_interval_seconds = sample_interval_ms / 1000
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.observations: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.first_ungranted_seen: dict[tuple[Any, ...], float] = {}
        self.max_ungranted_wait_ms = 0
        self.monitor_errors: list[str] = []

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="migration-lock-monitor", daemon=True)
        self.thread.start()

    def stop(self) -> dict[str, Any]:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        return {
            "sample_interval_ms": round(self.sample_interval_seconds * 1000),
            "max_ungranted_wait_ms": self.max_ungranted_wait_ms,
            "observations": list(self.observations.values()),
            "monitor_errors": self.monitor_errors,
        }

    def _run(self) -> None:
        import psycopg
        from psycopg.rows import dict_row

        try:
            with psycopg.connect(
                self.dsn,
                application_name=f"{self.application_name}-monitor"[:63],
                autocommit=True,
            ) as connection:
                while not self.stop_event.wait(self.sample_interval_seconds):
                    with connection.cursor(row_factory=dict_row) as cursor:
                        cursor.execute(
                            """
                            SELECT a.pid, a.wait_event_type, a.wait_event,
                                   l.mode, l.granted, c.relname AS relation_name,
                                   pg_blocking_pids(a.pid) AS blocking_pids
                            FROM pg_stat_activity AS a
                            LEFT JOIN pg_locks AS l ON l.pid = a.pid
                            LEFT JOIN pg_class AS c ON c.oid = l.relation
                            WHERE a.application_name = %s
                            ORDER BY a.pid, relation_name NULLS FIRST, l.mode
                            """,
                            (self.application_name,),
                        )
                        now = time.monotonic()
                        for row in cursor.fetchall():
                            key = (
                                row["mode"],
                                bool(row["granted"]),
                                row["relation_name"],
                                tuple(row["blocking_pids"] or []),
                            )
                            if key not in self.observations and len(self.observations) < 250:
                                self.observations[key] = {
                                    "mode": row["mode"],
                                    "granted": bool(row["granted"]),
                                    "relation_name": row["relation_name"],
                                    "blocking_pid_count": len(row["blocking_pids"] or []),
                                    "wait_event_type": row["wait_event_type"],
                                    "wait_event": row["wait_event"],
                                }
                            if row["granted"] is False:
                                first_seen = self.first_ungranted_seen.setdefault(key, now)
                                waited_ms = round((now - first_seen) * 1000)
                                self.max_ungranted_wait_ms = max(
                                    self.max_ungranted_wait_ms,
                                    waited_ms,
                                )
        except Exception as exc:
            self.monitor_errors.append(type(exc).__name__)


def _forward_fix_validation(connection: Any) -> dict[str, Any]:
    ledger = {row["migration_name"] for row in _migration_ledger(connection)}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT coalesce(bool_and(convalidated), false)
            FROM pg_constraint
            WHERE conname = 'chk_maitu_video_neutral_analysis_identity'
            """
        )
        constraint_validated = bool(cursor.fetchone()[0])
    predecessor = "043_provider_neutral_producer_contracts.sql"
    repair = "044_provider_neutral_analysis_identity.sql"
    passed = predecessor in ledger and repair in ledger and constraint_validated
    return {
        "predecessor_migration": predecessor,
        "forward_fix_migration": repair,
        "repair_semantics": "additive database enforcement of neutral material-analysis identity",
        "constraint_validated": constraint_validated,
        "passed": passed,
    }


def _count_stability(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for table, before_count in before["exact_counts"].items():
        after_count = after["exact_counts"].get(table)
        comparable = before_count is not None and after_count is not None
        results.append(
            {
                "table": table,
                "before": before_count,
                "after": after_count,
                "comparable": comparable,
                "stable": bool(comparable and before_count == after_count),
            }
        )
    return results


def run_rehearsal(
    dsn: str,
    migrations: list[Path],
    *,
    expected_database: str,
    copy_classification: str,
    source_snapshot_ref: str | None,
    sanitization_evidence_ref: str | None,
    invariant_contract: dict[str, Any],
    exact_count_tables: tuple[str, ...] = DEFAULT_EXACT_COUNT_TABLES,
    lock_timeout_ms: int = 5_000,
    statement_timeout_ms: int = 900_000,
    lock_sample_interval_ms: int = 50,
) -> dict[str, Any]:
    import psycopg

    validate_copy_attestation(
        copy_classification=copy_classification,
        source_snapshot_ref=source_snapshot_ref,
        sanitization_evidence_ref=sanitization_evidence_ref,
    )
    run_code = f"MIGREH-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}"
    application_name = f"assetgraph-migration-rehearsal-{run_code[-12:].lower()}"
    started_at = _utc_now()
    started = time.monotonic()

    with psycopg.connect(
        dsn,
        application_name=f"{application_name}-inspect"[:63],
    ) as connection:
        before = database_snapshot(connection, exact_count_tables=exact_count_tables)
        database_name = str(before["identity"]["database_name"])
        if database_name != expected_database:
            raise RehearsalSafetyError(
                f"connected database {database_name!r} does not match --expected-database"
            )
        if before["identity"]["in_recovery"]:
            raise RehearsalSafetyError("migration rehearsal target is a read-only recovery server")
        if int(before["identity"]["other_session_count"]) != 0:
            raise RehearsalSafetyError(
                "migration rehearsal target is not isolated; other database sessions are active"
            )

    file_checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in migrations
    }
    before_ledger = {
        row["migration_name"]: row["checksum_sha256"]
        for row in before["migration_ledger"]
    }
    changed = [
        name
        for name, checksum in before_ledger.items()
        if name in file_checksums and file_checksums[name] != checksum
    ]
    unknown = sorted(set(before_ledger) - set(file_checksums))
    if changed:
        raise RehearsalSafetyError(
            f"applied migrations changed on disk: {', '.join(sorted(changed))}"
        )
    if unknown:
        raise RehearsalSafetyError(
            f"database ledger contains migrations absent from this repository: {', '.join(unknown)}"
        )
    pending = [path for path in migrations if path.name not in before_ledger]

    monitor = LockMonitor(
        dsn,
        application_name=application_name,
        sample_interval_ms=lock_sample_interval_ms,
    )
    executions: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    monitor.start()
    try:
        for path in pending:
            migration_started = time.monotonic()
            try:
                newly_applied = apply_migrations(
                    dsn,
                    [path],
                    lock_timeout_ms=lock_timeout_ms,
                    statement_timeout_ms=statement_timeout_ms,
                    application_name=application_name,
                )
                executions.append(
                    {
                        "migration_name": path.name,
                        "checksum_sha256": file_checksums[path.name],
                        "duration_ms": round((time.monotonic() - migration_started) * 1000),
                        "status": "applied" if newly_applied else "already_applied",
                    }
                )
            except Exception as exc:
                failure = {
                    "migration_name": path.name,
                    "error_type": type(exc).__name__,
                    "sqlstate": getattr(exc, "sqlstate", None),
                }
                executions.append(
                    {
                        "migration_name": path.name,
                        "checksum_sha256": file_checksums[path.name],
                        "duration_ms": round((time.monotonic() - migration_started) * 1000),
                        "status": "failed",
                        **failure,
                    }
                )
                break
    finally:
        lock_report = monitor.stop()

    with psycopg.connect(
        dsn,
        application_name=f"{application_name}-validate"[:63],
    ) as connection:
        after = database_snapshot(connection, exact_count_tables=exact_count_tables)
        invariant_results = (
            execute_invariants(connection, invariant_contract) if failure is None else []
        )
        forward_fix = _forward_fix_validation(connection)

    after_ledger = {
        row["migration_name"]: row["checksum_sha256"]
        for row in after["migration_ledger"]
    }
    all_migrations_applied = after_ledger == file_checksums
    count_stability = _count_stability(before, after)
    comparable_counts = [row for row in count_stability if row["comparable"]]
    counts_stable = bool(comparable_counts) and all(row["stable"] for row in comparable_counts)
    health_passed = (
        int(after["index_health"]["invalid_indexes"]) == 0
        and int(after["index_health"]["unready_indexes"]) == 0
        and int(after["constraint_health"]["unvalidated_constraints"]) == 0
    )
    invariants_passed = bool(invariant_results) and all(
        result["passed"] for result in invariant_results
    )
    status = "passed" if failure is None and all_migrations_applied else "failed"
    qualifies = bool(
        status == "passed"
        and pending
        and copy_classification in REAL_COPY_CLASSIFICATIONS
        and source_snapshot_ref
        and health_passed
        and counts_stable
        and invariants_passed
        and forward_fix["passed"]
        and not lock_report["monitor_errors"]
    )
    report: dict[str, Any] = {
        "schema_version": "migration-rehearsal-report.v1",
        "run_code": run_code,
        "status": status,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "duration_ms": round((time.monotonic() - started) * 1000),
        "copy_attestation": {
            "classification": copy_classification,
            "source_snapshot_ref": source_snapshot_ref,
            "sanitization_evidence_ref": sanitization_evidence_ref,
            "expected_database": expected_database,
        },
        "safety": {
            "isolated_at_start": True,
            "database_url_persisted": False,
            "lock_timeout_ms": lock_timeout_ms,
            "statement_timeout_ms": statement_timeout_ms,
            "advisory_lock": "assetgraph-schema-migrations-v1",
        },
        "before": before,
        "migration_executions": executions,
        "failure": failure,
        "lock_report": lock_report,
        "after": after,
        "validation": {
            "all_repository_migrations_applied": all_migrations_applied,
            "schema_changed": before["schema_fingerprint"] != after["schema_fingerprint"],
            "count_stability": count_stability,
            "counts_stable": counts_stable,
            "catalog_health_passed": health_passed,
            "invariants": invariant_results,
            "invariants_passed": invariants_passed,
            "forward_fix": forward_fix,
        },
        "qualifies_for_chk_0260": qualifies,
    }
    report["report_fingerprint_sha256"] = _canonical_fingerprint(report)
    return report


def write_report(path: Path, report: dict[str, Any], *, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        target.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rehearse forward-only AssetGraph migrations on an isolated database copy"
    )
    parser.add_argument("--database-url")
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--copy-classification", choices=sorted(COPY_CLASSIFICATIONS), required=True)
    parser.add_argument("--source-snapshot-ref")
    parser.add_argument("--sanitization-evidence-ref")
    parser.add_argument(
        "--invariants",
        type=Path,
        default=REPO_ROOT / "docs" / "operations" / "phase-0-migration-invariants.v1.json",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=REPO_ROOT / "backend" / "migrations",
    )
    parser.add_argument("--exact-count-table", action="append", default=[])
    parser.add_argument("--lock-timeout-ms", type=int, default=5_000)
    parser.add_argument("--statement-timeout-ms", type=int, default=900_000)
    parser.add_argument("--lock-sample-interval-ms", type=int, default=50)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--acknowledge-isolated-copy",
        action="store_true",
        help="Required acknowledgement that this target is disposable and not production",
    )
    args = parser.parse_args(argv)
    if not args.acknowledge_isolated_copy:
        parser.error("--acknowledge-isolated-copy is required")
    if args.lock_sample_interval_ms < 10 or args.lock_sample_interval_ms > 1_000:
        parser.error("--lock-sample-interval-ms must be between 10 and 1000")

    try:
        report = run_rehearsal(
            args.database_url or database_url(REPO_ROOT),
            discover_migrations(args.migrations_dir),
            expected_database=args.expected_database,
            copy_classification=args.copy_classification,
            source_snapshot_ref=args.source_snapshot_ref,
            sanitization_evidence_ref=args.sanitization_evidence_ref,
            invariant_contract=load_invariant_contract(args.invariants),
            exact_count_tables=tuple(args.exact_count_table) or DEFAULT_EXACT_COUNT_TABLES,
            lock_timeout_ms=args.lock_timeout_ms,
            statement_timeout_ms=args.statement_timeout_ms,
            lock_sample_interval_ms=args.lock_sample_interval_ms,
        )
        write_report(args.output, report, overwrite=args.overwrite)
    except (OSError, ValueError, RehearsalSafetyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(
        f"status={report['status']} qualifies_for_chk_0260="
        f"{str(report['qualifies_for_chk_0260']).lower()} output={args.output}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

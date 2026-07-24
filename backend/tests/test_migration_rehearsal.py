from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.apply_migrations import MIGRATION_ADVISORY_LOCK, apply_migrations  # noqa: E402
from scripts.rehearse_migrations import (  # noqa: E402
    RehearsalSafetyError,
    _forward_fix_validation,
    database_snapshot,
    execute_invariants,
    load_invariant_contract,
    validate_copy_attestation,
)


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")


def test_real_copy_attestation_requires_source_and_sanitization_evidence() -> None:
    with pytest.raises(RehearsalSafetyError, match="source_snapshot_ref"):
        validate_copy_attestation(
            copy_classification="production_sanitized_copy",
            source_snapshot_ref=None,
            sanitization_evidence_ref=None,
        )
    with pytest.raises(RehearsalSafetyError, match="sanitization_evidence_ref"):
        validate_copy_attestation(
            copy_classification="production_sanitized_copy",
            source_snapshot_ref="SNAPSHOT-001",
            sanitization_evidence_ref=None,
        )
    with pytest.raises(RehearsalSafetyError, match="cannot claim production"):
        validate_copy_attestation(
            copy_classification="synthetic_fixture",
            source_snapshot_ref="SNAPSHOT-001",
            sanitization_evidence_ref=None,
        )
    validate_copy_attestation(
        copy_classification="production_sanitized_copy",
        source_snapshot_ref="SNAPSHOT-001",
        sanitization_evidence_ref="SANITIZE-001",
    )


@pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")
def test_phase0_invariant_contract_and_forward_fix_hold_on_migrated_database() -> None:
    contract = load_invariant_contract(
        REPO_ROOT / "docs" / "operations" / "phase-0-migration-invariants.v1.json"
    )
    with psycopg.connect(DATABASE_URL) as connection:
        snapshot = database_snapshot(connection, exact_count_tables=("assets",))
        assertions = execute_invariants(connection, contract)
        forward_fix = _forward_fix_validation(connection)

    assert len(snapshot["schema_fingerprint"]) == 64
    assert snapshot["exact_counts"]["assets"] is not None
    assert assertions and all(assertion["passed"] for assertion in assertions)
    assert forward_fix["passed"] is True


@pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")
def test_migration_runner_rejects_concurrent_runner() -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as holder:
        with holder.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                (MIGRATION_ADVISORY_LOCK,),
            )
        with pytest.raises(RuntimeError, match="already running"):
            apply_migrations(DATABASE_URL, [])
        with holder.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                (MIGRATION_ADVISORY_LOCK,),
            )


@pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")
def test_lock_timeout_leaves_no_receipt_and_explicit_retry_can_finish(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    table_name = f"migration_lock_probe_{suffix}"
    migration_name = f"900_lock_probe_{suffix}.sql"
    migration = tmp_path / migration_name
    migration.write_text(
        f"ALTER TABLE {table_name} ADD COLUMN repaired_value INTEGER;\n",
        encoding="utf-8",
    )

    with psycopg.connect(DATABASE_URL) as setup:
        with setup.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE TABLE {} (id INTEGER PRIMARY KEY)").format(sql.Identifier(table_name)))
        setup.commit()

    try:
        with psycopg.connect(DATABASE_URL) as blocker:
            with blocker.cursor() as cursor:
                cursor.execute(
                    sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
                        sql.Identifier(table_name)
                    )
                )
            with pytest.raises(psycopg.errors.LockNotAvailable):
                apply_migrations(
                    DATABASE_URL,
                    [migration],
                    lock_timeout_ms=100,
                    statement_timeout_ms=5_000,
                    application_name="assetgraph-migration-lock-test",
                )

            with psycopg.connect(DATABASE_URL) as observer:
                with observer.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM assetgraph_schema_migrations WHERE migration_name = %s",
                        (migration_name,),
                    )
                    assert cursor.fetchone()[0] == 0
                    cursor.execute(
                        """
                        SELECT count(*) FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                          AND column_name = 'repaired_value'
                        """,
                        (table_name,),
                    )
                    assert cursor.fetchone()[0] == 0
            blocker.rollback()

        assert apply_migrations(
            DATABASE_URL,
            [migration],
            lock_timeout_ms=1_000,
            statement_timeout_ms=5_000,
        ) == [migration_name]
        assert apply_migrations(DATABASE_URL, [migration]) == []

        migration.write_text(
            f"ALTER TABLE {table_name} ADD COLUMN changed_after_apply TEXT;\n",
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="changed on disk"):
            apply_migrations(DATABASE_URL, [migration])
    finally:
        with psycopg.connect(DATABASE_URL) as cleanup:
            with cleanup.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM assetgraph_schema_migrations WHERE migration_name = %s",
                    (migration_name,),
                )
                cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name)))
            cleanup.commit()

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

if __package__:
    from .apply_migrations import apply_migrations, discover_migrations
    from .rehearse_migrations import execute_invariants, load_invariant_contract
else:
    from apply_migrations import apply_migrations, discover_migrations
    from rehearse_migrations import execute_invariants, load_invariant_contract


REPO_ROOT = Path(__file__).resolve().parents[1]


class DisasterRecoveryError(RuntimeError):
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
    expected = report.get("report_fingerprint_sha256")
    unsigned = dict(report)
    unsigned.pop("report_fingerprint_sha256", None)
    return isinstance(expected, str) and expected == _canonical_fingerprint(unsigned)


def _run(
    command: list[str],
    *,
    timeout_seconds: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )


def _binary_version(path: Path) -> str:
    result = _run([str(path), "--version"], timeout_seconds=15)
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _assert_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise DisasterRecoveryError(f"required local port is already in use: {port}") from exc


def _wait_http(url: str, *, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise DisasterRecoveryError(f"service did not become ready: {url}")


def _safe_workspace(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        raise DisasterRecoveryError("disaster-recovery workspace already exists")
    if any(character in str(resolved) for character in ("'", '"', "\\", "\n", "\r")):
        raise DisasterRecoveryError("workspace path contains unsupported shell/config characters")
    resolved.mkdir(parents=True)
    return resolved


def _append_postgres_config(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as target:
        target.write("\n# AssetGraph disaster-recovery rehearsal\n")
        for key, value in values.items():
            escaped = value.replace("'", "''")
            target.write(f"{key} = '{escaped}'\n")


def _pg_dsn(port: int, database: str) -> str:
    return f"postgresql://assetgraph@127.0.0.1:{port}/{database}"


def _pg_ctl(
    pg_bin: Path,
    data_dir: Path,
    action: str,
    *,
    log_path: Path,
    mode: str | None = None,
) -> None:
    command = [str(pg_bin / "pg_ctl"), "-D", str(data_dir)]
    if action == "start":
        command.extend(["-l", str(log_path), "-w", "-t", "60", "start"])
    elif action == "stop":
        command.extend(["-w", "-t", "60", "stop", "-m", mode or "fast"])
    else:
        raise ValueError(f"unsupported pg_ctl action: {action}")
    _run(command, timeout_seconds=75)


def _force_archive(connection: Any, *, timeout_seconds: int = 20) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT coalesce(archived_count, 0) FROM pg_stat_archiver")
        before_count = int(cursor.fetchone()[0])
        cursor.execute("SELECT pg_switch_wal()::text")
        switched_lsn = str(cursor.fetchone()[0])
    connection.commit()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT coalesce(archived_count, 0), last_archived_wal,
                       coalesce(failed_count, 0)
                FROM pg_stat_archiver
                """
            )
            archived_count, last_archived_wal, failed_count = cursor.fetchone()
        connection.commit()
        if int(archived_count) > before_count:
            return {
                "switched_lsn": switched_lsn,
                "archived_count": int(archived_count),
                "last_archived_wal": str(last_archived_wal),
                "failed_count": int(failed_count),
            }
        time.sleep(0.1)
    raise DisasterRecoveryError("WAL segment was not archived before timeout")


def _wait_for_promotion(dsn: str, *, timeout_seconds: int = 30) -> None:
    import psycopg

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_is_in_recovery()")
                    if not bool(cursor.fetchone()[0]):
                        return
        except psycopg.OperationalError:
            pass
        time.sleep(0.05)
    raise DisasterRecoveryError("recovered database did not promote before timeout")


def _start_minio(
    binary: Path,
    data_dir: Path,
    log_path: Path,
    *,
    api_port: int,
    console_port: int,
    access_key: str,
    secret_key: str,
) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "MINIO_ROOT_USER": access_key,
        "MINIO_ROOT_PASSWORD": secret_key,
        "MINIO_BROWSER": "off",
    }
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(binary),
            "server",
            str(data_dir),
            "--address",
            f"127.0.0.1:{api_port}",
            "--console-address",
            f"127.0.0.1:{console_port}",
            "--anonymous",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    setattr(process, "_assetgraph_log_handle", log)
    try:
        _wait_http(f"http://127.0.0.1:{api_port}/minio/health/ready")
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        log.close()
        raise
    return process


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    log = getattr(process, "_assetgraph_log_handle", None)
    if log is not None:
        log.close()


def _restore_object_version(
    client: Any,
    *,
    bucket: str,
    object_key: str,
    original_version_id: str,
    expected_checksum: str,
) -> dict[str, Any]:
    operation_started = time.monotonic()
    response = client.get_object(bucket, object_key, version_id=original_version_id)
    try:
        content = response.read()
    finally:
        response.close()
        response.release_conn()
    restored_checksum = hashlib.sha256(content).hexdigest()
    if restored_checksum != expected_checksum:
        raise DisasterRecoveryError("historical object version checksum does not match ArtifactRef")
    result = client.put_object(
        bucket,
        object_key,
        io.BytesIO(content),
        len(content),
        content_type="application/json",
        metadata={"sha256": restored_checksum, "schema-version": "dr-artifact.v1"},
    )
    current = client.get_object(bucket, object_key)
    try:
        current_content = current.read()
    finally:
        current.close()
        current.release_conn()
    current_checksum = hashlib.sha256(current_content).hexdigest()
    stat = client.stat_object(bucket, object_key)
    return {
        "source_version_id": original_version_id,
        "restored_version_id": str(result.version_id),
        "restored_checksum_sha256": current_checksum,
        "restored_byte_size": len(current_content),
        "metadata_checksum_sha256": (stat.metadata or {}).get("x-amz-meta-sha256"),
        "operation_duration_ms": round((time.monotonic() - operation_started) * 1000),
        "passed": current_checksum == expected_checksum,
    }


def run_rehearsal(
    *,
    workspace: Path,
    pg_bin: Path,
    minio_binary: Path,
    source_port: int,
    recovery_port: int,
    minio_port: int,
    minio_console_port: int,
    database_name: str,
    migrations: list[Path],
    invariant_contract: dict[str, Any],
) -> dict[str, Any]:
    import psycopg
    from minio import Minio
    from minio.commonconfig import ENABLED
    from minio.error import S3Error
    from minio.versioningconfig import VersioningConfig
    from psycopg.types.json import Jsonb

    for port in (source_port, recovery_port, minio_port, minio_console_port):
        _assert_port_available(port)
    required_pg_binaries = (
        "initdb",
        "pg_ctl",
        "createdb",
        "pg_basebackup",
        "pg_verifybackup",
        "pg_amcheck",
        "pg_checksums",
    )
    missing = [name for name in required_pg_binaries if not (pg_bin / name).is_file()]
    if missing:
        raise DisasterRecoveryError(f"missing PostgreSQL binaries: {', '.join(missing)}")
    if not minio_binary.is_file():
        raise DisasterRecoveryError("MinIO binary is missing")

    workspace = _safe_workspace(workspace)
    source_data = workspace / "postgres-source"
    base_backup = workspace / "postgres-basebackup"
    recovery_data = workspace / "postgres-recovery"
    archive_dir = workspace / "wal-archive"
    minio_data = workspace / "minio-data"
    archive_dir.mkdir()
    minio_data.mkdir()
    source_log = workspace / "postgres-source.log"
    recovery_log = workspace / "postgres-recovery.log"
    minio_log = workspace / "minio.log"
    run_code = f"DR-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}"
    started_at = _utc_now()
    started = time.monotonic()
    source_started = False
    recovery_started = False
    minio_process: subprocess.Popen[str] | None = None
    access_key = f"dr{secrets.token_hex(6)}"
    secret_key = secrets.token_urlsafe(32)
    report: dict[str, Any] = {
        "schema_version": "disaster-recovery-rehearsal.v1",
        "run_code": run_code,
        "classification": "local_baseline",
        "status": "failed",
        "started_at": started_at,
        "environment": {
            "postgres": _binary_version(pg_bin / "postgres"),
            "pg_basebackup": _binary_version(pg_bin / "pg_basebackup"),
            "minio": _binary_version(minio_binary),
            "data_page_checksums_requested": True,
            "archive_mode_requested": True,
            "credentials_persisted": False,
        },
    }
    stage = "initialize_postgres"
    try:
        _run(
            [
                str(pg_bin / "initdb"),
                "-D",
                str(source_data),
                "-U",
                "assetgraph",
                "--auth=trust",
                "--no-locale",
                "--encoding=UTF8",
                "--data-checksums",
            ]
        )
        _append_postgres_config(
            source_data / "postgresql.conf",
            {
                "port": str(source_port),
                "listen_addresses": "127.0.0.1",
                "unix_socket_directories": str(workspace),
                "archive_mode": "on",
                "archive_command": f"test ! -f {archive_dir}/%f && cp %p {archive_dir}/%f",
                "wal_level": "replica",
                "max_wal_senders": "5",
                "full_page_writes": "on",
            },
        )
        _pg_ctl(pg_bin, source_data, "start", log_path=source_log)
        source_started = True
        _run(
            [
                str(pg_bin / "createdb"),
                "-h",
                "127.0.0.1",
                "-p",
                str(source_port),
                "-U",
                "assetgraph",
                database_name,
            ]
        )
        source_dsn = _pg_dsn(source_port, database_name)
        stage = "apply_migrations"
        applied = apply_migrations(
            source_dsn,
            migrations,
            lock_timeout_ms=5_000,
            statement_timeout_ms=900_000,
            application_name="assetgraph-dr-migration",
        )

        stage = "start_object_storage"
        minio_process = _start_minio(
            minio_binary,
            minio_data,
            minio_log,
            api_port=minio_port,
            console_port=minio_console_port,
            access_key=access_key,
            secret_key=secret_key,
        )
        client = Minio(
            f"127.0.0.1:{minio_port}",
            access_key=access_key,
            secret_key=secret_key,
            secure=False,
        )
        bucket = "assetgraph-dr-evidence"
        client.make_bucket(bucket)
        client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
        content = json.dumps(
            {"run_code": run_code, "evidence": "original"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        checksum = hashlib.sha256(content).hexdigest()
        object_key = f"artifacts/sha256/{checksum[:2]}/{checksum}"
        original_put = client.put_object(
            bucket,
            object_key,
            io.BytesIO(content),
            len(content),
            content_type="application/json",
            metadata={"sha256": checksum, "schema-version": "dr-artifact.v1"},
        )
        original_version_id = str(original_put.version_id)
        artifact_code = f"ART-{run_code}"

        with psycopg.connect(source_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE dr_recovery_markers (
                        marker_code TEXT PRIMARY KEY,
                        marker_payload TEXT NOT NULL,
                        committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO dr_recovery_markers (marker_code, marker_payload)
                    VALUES ('base_backup', %s)
                    """,
                    (run_code,),
                )
                cursor.execute(
                    """
                    INSERT INTO artifact_refs (
                        artifact_code, artifact_kind, media_type, schema_version,
                        storage_uri, checksum_sha256, byte_size, producer_type,
                        producer_code, sensitivity, retention_policy_code, metadata
                    ) VALUES (%s, 'dr_recovery_evidence', 'application/json',
                              'dr-artifact.v1', %s, %s, %s, 'dr_rehearsal', %s,
                              'confidential', 'critical-audit-evidence', %s)
                    """,
                    (
                        artifact_code,
                        f"s3://{bucket}/{object_key}",
                        checksum,
                        len(content),
                        run_code,
                        Jsonb({"original_version_id": original_version_id}),
                    ),
                )
            connection.commit()

        stage = "create_and_verify_base_backup"
        base_backup_started = time.monotonic()
        _run(
            [
                str(pg_bin / "pg_basebackup"),
                "-h",
                "127.0.0.1",
                "-p",
                str(source_port),
                "-U",
                "assetgraph",
                "-D",
                str(base_backup),
                "-Fp",
                "-Xs",
                "-c",
                "fast",
                "--manifest-checksums=SHA256",
            ],
            timeout_seconds=180,
        )
        base_backup_duration_ms = round((time.monotonic() - base_backup_started) * 1000)
        _run([str(pg_bin / "pg_verifybackup"), str(base_backup)], timeout_seconds=120)

        stage = "create_recovery_boundary_and_archive_wal"
        with psycopg.connect(source_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO dr_recovery_markers (marker_code, marker_payload)
                    VALUES ('before_target', %s) RETURNING committed_at
                    """,
                    (f"{run_code}:before",),
                )
                before_target_at = cursor.fetchone()[0]
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute("SELECT clock_timestamp()")
                recovery_target_at = cursor.fetchone()[0]
            connection.commit()
            time.sleep(0.25)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO dr_recovery_markers (marker_code, marker_payload)
                    VALUES ('after_target', %s) RETURNING committed_at
                    """,
                    (f"{run_code}:after",),
                )
                after_target_at = cursor.fetchone()[0]
            connection.commit()
            archive_event = _force_archive(connection)

        stage = "declare_disaster"
        corrupt = b'{"evidence":"corrupt-current-version"}'
        corrupt_put = client.put_object(
            bucket,
            object_key,
            io.BytesIO(corrupt),
            len(corrupt),
            content_type="application/json",
        )
        client.remove_object(bucket, object_key)
        try:
            client.stat_object(bucket, object_key)
            delete_marker_observed = False
        except S3Error as exc:
            delete_marker_observed = getattr(exc, "code", None) in {
                "NoSuchKey",
                "NoSuchObject",
            }
        if not delete_marker_observed:
            raise DisasterRecoveryError("current object remained readable after delete marker")
        disaster_declared_at = _utc_now()
        disaster_started = time.monotonic()
        _pg_ctl(
            pg_bin,
            source_data,
            "stop",
            log_path=source_log,
            mode="immediate",
        )
        source_started = False

        stage = "restore_database_to_time_target"
        restore_copy_started = time.monotonic()
        shutil.copytree(base_backup, recovery_data)
        restore_copy_duration_ms = round((time.monotonic() - restore_copy_started) * 1000)
        _append_postgres_config(
            recovery_data / "postgresql.auto.conf",
            {
                "port": str(recovery_port),
                "listen_addresses": "127.0.0.1",
                "unix_socket_directories": str(workspace),
                "restore_command": f"cp {archive_dir}/%f %p",
                "recovery_target_time": recovery_target_at.isoformat(),
                "recovery_target_action": "promote",
                "archive_mode": "off",
            },
        )
        (recovery_data / "recovery.signal").touch()
        _pg_ctl(pg_bin, recovery_data, "start", log_path=recovery_log)
        recovery_started = True
        recovery_dsn = _pg_dsn(recovery_port, database_name)
        _wait_for_promotion(recovery_dsn)

        stage = "validate_recovered_database"
        with psycopg.connect(recovery_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT marker_code, marker_payload, committed_at FROM dr_recovery_markers ORDER BY marker_code"
                )
                recovered_markers = [
                    {
                        "marker_code": row[0],
                        "marker_payload": row[1],
                        "committed_at": row[2],
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT artifact_code, storage_uri, checksum_sha256, byte_size
                    FROM artifact_refs WHERE artifact_code = %s
                    """,
                    (artifact_code,),
                )
                artifact_row = cursor.fetchone()
                cursor.execute("SELECT pg_is_in_recovery()")
                promoted = not bool(cursor.fetchone()[0])
                cursor.execute("SELECT count(*) FROM assetgraph_schema_migrations")
                migration_count = int(cursor.fetchone()[0])
            connection.commit()
            invariant_results = execute_invariants(connection, invariant_contract)

        marker_codes = {marker["marker_code"] for marker in recovered_markers}
        marker_boundary_passed = (
            "base_backup" in marker_codes
            and "before_target" in marker_codes
            and "after_target" not in marker_codes
        )
        artifact_row_passed = bool(
            artifact_row
            and artifact_row[0] == artifact_code
            and artifact_row[1] == f"s3://{bucket}/{object_key}"
            and str(artifact_row[2]) == checksum
            and int(artifact_row[3]) == len(content)
        )
        database_rto_ms = round((time.monotonic() - disaster_started) * 1000)

        stage = "restore_object_version"
        object_restore = _restore_object_version(
            client,
            bucket=bucket,
            object_key=object_key,
            original_version_id=original_version_id,
            expected_checksum=checksum,
        )
        object_rto_from_disaster_ms = round((time.monotonic() - disaster_started) * 1000)
        cross_store_passed = artifact_row_passed and object_restore["passed"]
        composite_rto_ms = round((time.monotonic() - disaster_started) * 1000)

        stage = "run_database_integrity_checks"
        _run(
            [
                str(pg_bin / "pg_amcheck"),
                "-h",
                "127.0.0.1",
                "-p",
                str(recovery_port),
                "-U",
                "assetgraph",
                "--database",
                database_name,
                "--install-missing",
                "--parent-check",
            ],
            timeout_seconds=120,
        )
        _pg_ctl(pg_bin, recovery_data, "stop", log_path=recovery_log, mode="fast")
        recovery_started = False
        checksum_check = _run(
            [str(pg_bin / "pg_checksums"), "--check", "-D", str(recovery_data)],
            timeout_seconds=120,
        )
        checksum_passed = "Checksum operation completed" in checksum_check.stdout
        invariants_passed = bool(invariant_results) and all(
            result["passed"] for result in invariant_results
        )
        database_passed = bool(
            promoted
            and marker_boundary_passed
            and artifact_row_passed
            and migration_count == len(migrations)
            and invariants_passed
            and checksum_passed
        )
        object_passed = bool(
            original_version_id
            and str(corrupt_put.version_id) != original_version_id
            and object_restore["passed"]
            and object_restore["metadata_checksum_sha256"] == checksum
        )
        report.update(
            {
                "status": "passed" if database_passed and object_passed and cross_store_passed else "failed",
                "disaster_declared_at": disaster_declared_at,
                "database": {
                    "database_name": database_name,
                    "migrations_applied_before_backup": len(applied),
                    "base_backup_duration_ms": base_backup_duration_ms,
                    "base_backup_bytes": sum(
                        path.stat().st_size for path in base_backup.rglob("*") if path.is_file()
                    ),
                    "pg_verifybackup_passed": True,
                    "recovery_target_at": recovery_target_at,
                    "latest_retained_marker_at": before_target_at,
                    "excluded_marker_at": after_target_at,
                    "measured_rpo_ms": max(
                        0,
                        round((recovery_target_at - before_target_at).total_seconds() * 1000),
                    ),
                    "measured_rto_ms": database_rto_ms,
                    "base_backup_restore_copy_duration_ms": restore_copy_duration_ms,
                    "wal_archive_events": [archive_event],
                    "recovered_markers": recovered_markers,
                    "marker_boundary_passed": marker_boundary_passed,
                    "promoted": promoted,
                    "migration_count": migration_count,
                    "expected_migration_count": len(migrations),
                    "business_invariants": invariant_results,
                    "business_invariants_passed": invariants_passed,
                    "pg_amcheck_passed": True,
                    "data_checksum_check_passed": checksum_passed,
                    "passed": database_passed,
                },
                "object_storage": {
                    "bucket": bucket,
                    "versioning_enabled": True,
                    "object_key": object_key,
                    "artifact_code": artifact_code,
                    "expected_checksum_sha256": checksum,
                    "expected_byte_size": len(content),
                    "original_version_id": original_version_id,
                    "corrupt_version_id": str(corrupt_put.version_id),
                    "delete_marker_created": delete_marker_observed,
                    "measured_rpo_bytes": 0,
                    "measured_rto_from_disaster_ms": object_rto_from_disaster_ms,
                    "restore": object_restore,
                    "passed": object_passed,
                },
                "cross_store_validation": {
                    "recovered_artifact_ref_matches_restored_object": cross_store_passed,
                    "passed": cross_store_passed,
                },
                "composite_measured_rto_ms": composite_rto_ms,
                "qualifies_for_chk_0295": bool(
                    database_passed and object_passed and cross_store_passed
                ),
                "known_limits": [
                    "local baseline with repository schema and deterministic drill data, not production volume",
                    "does not establish the production RPO/RTO targets required by CHK-7230",
                    "does not cover a multi-node PostgreSQL or distributed object-store failure",
                ],
            }
        )
    except Exception as exc:
        report["failure"] = {
            "stage": stage,
            "stage_error_type": type(exc).__name__,
            "sqlstate": getattr(exc, "sqlstate", None),
        }
        report["qualifies_for_chk_0295"] = False
    finally:
        if recovery_started:
            try:
                _pg_ctl(pg_bin, recovery_data, "stop", log_path=recovery_log, mode="immediate")
            except Exception:
                pass
        if source_started:
            try:
                _pg_ctl(pg_bin, source_data, "stop", log_path=source_log, mode="immediate")
            except Exception:
                pass
        _stop_process(minio_process)
        report["completed_at"] = _utc_now()
        report["total_duration_ms"] = round((time.monotonic() - started) * 1000)
        report["report_fingerprint_sha256"] = _canonical_fingerprint(report)
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        target.write("\n")


def main(argv: list[str] | None = None) -> int:
    default_pg_bin = Path(
        _run(["pg_config", "--bindir"], timeout_seconds=15).stdout.strip()
    )
    parser = argparse.ArgumentParser(
        description="Run a local PostgreSQL PITR and versioned artifact restore baseline"
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--postgres-bin-dir", type=Path, default=default_pg_bin)
    parser.add_argument("--minio-binary", type=Path, default=REPO_ROOT / ".external" / "bin" / "minio")
    parser.add_argument("--source-port", type=int, default=55434)
    parser.add_argument("--recovery-port", type=int, default=55435)
    parser.add_argument("--minio-port", type=int, default=9100)
    parser.add_argument("--minio-console-port", type=int, default=9101)
    parser.add_argument("--database-name", default="assetgraph_dr_rehearsal")
    parser.add_argument("--cleanup-workspace-on-success", action="store_true")
    args = parser.parse_args(argv)
    if not re_full_identifier(args.database_name):
        parser.error("--database-name must be a lowercase PostgreSQL identifier")
    try:
        report = run_rehearsal(
            workspace=args.workspace,
            pg_bin=args.postgres_bin_dir.resolve(),
            minio_binary=args.minio_binary.resolve(),
            source_port=args.source_port,
            recovery_port=args.recovery_port,
            minio_port=args.minio_port,
            minio_console_port=args.minio_console_port,
            database_name=args.database_name,
            migrations=discover_migrations(REPO_ROOT / "backend" / "migrations"),
            invariant_contract=load_invariant_contract(
                REPO_ROOT / "docs" / "operations" / "phase-0-migration-invariants.v1.json"
            ),
        )
        write_report(args.output, report)
    except (OSError, ValueError, DisasterRecoveryError) as exc:
        parser.error(str(exc))
    if report["status"] == "passed" and args.cleanup_workspace_on_success:
        shutil.rmtree(args.workspace.resolve())
    print(
        f"status={report['status']} qualifies_for_chk_0295="
        f"{str(report.get('qualifies_for_chk_0295', False)).lower()} output={args.output}"
    )
    return 0 if report["status"] == "passed" else 1


def re_full_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value))


if __name__ == "__main__":
    raise SystemExit(main())

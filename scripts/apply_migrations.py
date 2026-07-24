from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
MIGRATION_ADVISORY_LOCK = "assetgraph-schema-migrations-v1"


def discover_migrations(directory: Path) -> list[Path]:
    paths = sorted(path for path in directory.glob("*.sql") if MIGRATION_PATTERN.fullmatch(path.name))
    numbers = [int(path.name[:3]) for path in paths]
    expected = list(range(1, len(paths) + 1))
    if numbers != expected:
        raise ValueError(f"migration sequence must be contiguous from 001: {numbers}")
    return paths


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def database_url(root: Path) -> str:
    file_env = _load_env(Path(os.getenv("ASSETGRAPH_ENV_FILE", root / ".env")))
    direct = os.getenv("ASSETGRAPH_DATABASE_URL") or os.getenv("DATABASE_URL")
    if direct:
        return direct
    def get(name: str, default: str) -> str:
        return os.getenv(name) or file_env.get(name) or default

    return (
        f"postgresql://{get('POSTGRES_USER', 'assetgraph')}:{get('POSTGRES_PASSWORD', 'assetgraph')}"
        f"@{get('POSTGRES_HOST', 'localhost')}:{get('POSTGRES_PORT', '5432')}/{get('POSTGRES_DB', 'assetgraph')}"
    )


def _set_transaction_timeouts(
    cursor: Any,
    *,
    lock_timeout_ms: int | None,
    statement_timeout_ms: int | None,
) -> None:
    if lock_timeout_ms is not None:
        if lock_timeout_ms <= 0:
            raise ValueError("lock_timeout_ms must be greater than zero")
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            (f"{lock_timeout_ms}ms",),
        )
    if statement_timeout_ms is not None:
        if statement_timeout_ms <= 0:
            raise ValueError("statement_timeout_ms must be greater than zero")
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{statement_timeout_ms}ms",),
        )


def apply_migrations(
    dsn: str,
    migrations: list[Path],
    *,
    lock_timeout_ms: int | None = None,
    statement_timeout_ms: int | None = None,
    application_name: str = "assetgraph-migration-runner",
) -> list[str]:
    import psycopg

    applied: list[str] = []
    with psycopg.connect(dsn, application_name=application_name[:63]) as connection:
        advisory_lock_acquired = False
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                    (MIGRATION_ADVISORY_LOCK,),
                )
                advisory_lock_acquired = bool(cursor.fetchone()[0])
            connection.commit()
            if not advisory_lock_acquired:
                raise RuntimeError("another AssetGraph schema migration is already running")

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assetgraph_schema_migrations (
                        migration_name TEXT PRIMARY KEY,
                        checksum_sha256 TEXT NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            connection.commit()

            for path in migrations:
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                try:
                    with connection.cursor() as cursor:
                        _set_transaction_timeouts(
                            cursor,
                            lock_timeout_ms=lock_timeout_ms,
                            statement_timeout_ms=statement_timeout_ms,
                        )
                        cursor.execute(
                            "SELECT checksum_sha256 FROM assetgraph_schema_migrations WHERE migration_name = %s",
                            (path.name,),
                        )
                        row = cursor.fetchone()
                        if row:
                            if row[0] != checksum:
                                raise RuntimeError(
                                    f"applied migration changed on disk: {path.name}"
                                )
                        else:
                            cursor.execute(sql)
                            cursor.execute(
                                """
                                INSERT INTO assetgraph_schema_migrations (
                                    migration_name, checksum_sha256
                                ) VALUES (%s, %s)
                                """,
                                (path.name, checksum),
                            )
                            applied.append(path.name)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        finally:
            if advisory_lock_acquired:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                            (MIGRATION_ADVISORY_LOCK,),
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply AssetGraph PostgreSQL migrations in deterministic order")
    parser.add_argument("--database-url")
    parser.add_argument("--migrations-dir", type=Path, default=REPO_ROOT / "backend" / "migrations")
    parser.add_argument("--lock-timeout-ms", type=int, default=5_000)
    parser.add_argument("--statement-timeout-ms", type=int, default=900_000)
    parser.add_argument("--application-name", default="assetgraph-migration-runner")
    args = parser.parse_args(argv)
    migrations = discover_migrations(args.migrations_dir)
    applied = apply_migrations(
        args.database_url or database_url(REPO_ROOT),
        migrations,
        lock_timeout_ms=args.lock_timeout_ms,
        statement_timeout_ms=args.statement_timeout_ms,
        application_name=args.application_name,
    )
    print(f"migrations_total={len(migrations)} applied={len(applied)}")
    for name in applied:
        print(f"applied {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

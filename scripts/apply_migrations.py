from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATTERN = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


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


def apply_migrations(dsn: str, migrations: list[Path]) -> list[str]:
    import psycopg

    applied: list[str] = []
    with psycopg.connect(dsn) as connection:
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
            for path in migrations:
                sql = path.read_text(encoding="utf-8")
                import hashlib

                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                cursor.execute(
                    "SELECT checksum_sha256 FROM assetgraph_schema_migrations WHERE migration_name = %s",
                    (path.name,),
                )
                row = cursor.fetchone()
                if row:
                    if row[0] != checksum:
                        raise RuntimeError(f"applied migration changed on disk: {path.name}")
                    continue
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO assetgraph_schema_migrations (migration_name, checksum_sha256) VALUES (%s, %s)",
                    (path.name, checksum),
                )
                applied.append(path.name)
        connection.commit()
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply AssetGraph PostgreSQL migrations in deterministic order")
    parser.add_argument("--database-url")
    parser.add_argument("--migrations-dir", type=Path, default=REPO_ROOT / "backend" / "migrations")
    args = parser.parse_args(argv)
    migrations = discover_migrations(args.migrations_dir)
    applied = apply_migrations(args.database_url or database_url(REPO_ROOT), migrations)
    print(f"migrations_total={len(migrations)} applied={len(applied)}")
    for name in applied:
        print(f"applied {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

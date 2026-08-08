from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when a test connection targets the configured development database."""


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    port: int
    database: str

    def display(self) -> str:
        host = "localhost" if self.host == "loopback" else self.host
        return f"{host}:{self.port}/{self.database}"


def _normalize_host(host: str) -> str:
    normalized = host.strip().rstrip(".").casefold()
    return "loopback" if normalized in LOOPBACK_HOSTS else normalized


def database_identity_from_url(database_url: str) -> DatabaseIdentity:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("database URL must use the postgres or postgresql scheme")
    if parsed.hostname is None:
        raise ValueError("database URL must include a host")
    database = unquote(parsed.path.lstrip("/")).strip()
    if not database or "/" in database:
        raise ValueError("database URL must include exactly one database name")
    return DatabaseIdentity(
        host=_normalize_host(parsed.hostname),
        port=parsed.port or 5432,
        database=database.casefold(),
    )


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def development_database_identity(env_file: Path) -> DatabaseIdentity | None:
    values = _load_env_file(env_file)
    if not values:
        return None
    direct_url = values.get("ASSETGRAPH_DATABASE_URL") or values.get("DATABASE_URL")
    if direct_url:
        return database_identity_from_url(direct_url)
    return DatabaseIdentity(
        host=_normalize_host(values.get("POSTGRES_HOST", "localhost")),
        port=int(values.get("POSTGRES_PORT", "5432")),
        database=values.get("POSTGRES_DB", "assetgraph").strip().casefold(),
    )


def assert_test_database_is_isolated(
    test_database_url: str | None,
    *,
    development_env_file: Path,
) -> None:
    if not test_database_url:
        return
    development = development_database_identity(development_env_file)
    if development is None:
        return
    test_database = database_identity_from_url(test_database_url)
    if test_database == development:
        raise UnsafeTestDatabaseError(
            "Refusing to run PostgreSQL tests against the development database "
            f"{development.display()} configured by {development_env_file}. "
            "Set ASSETGRAPH_TEST_DATABASE_URL to a dedicated disposable database."
        )

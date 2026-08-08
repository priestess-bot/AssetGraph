from __future__ import annotations

from pathlib import Path

import pytest

from scripts.database_safety import (
    DatabaseIdentity,
    UnsafeTestDatabaseError,
    assert_test_database_is_isolated,
    database_identity_from_url,
    development_database_identity,
)


def test_database_identity_normalizes_loopback_aliases() -> None:
    assert database_identity_from_url(
        "postgresql://user:secret@127.0.0.1:5432/AssetGraph"
    ) == DatabaseIdentity(host="loopback", port=5432, database="assetgraph")
    assert database_identity_from_url(
        "postgresql://user:secret@localhost/assetgraph"
    ) == DatabaseIdentity(host="loopback", port=5432, database="assetgraph")


def test_development_identity_reads_postgres_settings(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_HOST=localhost\nPOSTGRES_PORT=55432\nPOSTGRES_DB=assetgraph_dev\n",
        encoding="utf-8",
    )

    assert development_database_identity(env_file) == DatabaseIdentity(
        host="loopback",
        port=55432,
        database="assetgraph_dev",
    )


def test_guard_rejects_the_development_database_with_a_host_alias(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\nPOSTGRES_DB=assetgraph\n",
        encoding="utf-8",
    )

    with pytest.raises(UnsafeTestDatabaseError, match="development database"):
        assert_test_database_is_isolated(
            "postgresql://assetgraph:secret@127.0.0.1:5432/assetgraph",
            development_env_file=env_file,
        )


def test_guard_allows_a_dedicated_test_database(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\nPOSTGRES_DB=assetgraph\n",
        encoding="utf-8",
    )

    assert_test_database_is_isolated(
        "postgresql://assetgraph:secret@127.0.0.1:5432/assetgraph_test_windows",
        development_env_file=env_file,
    )


def test_guard_is_inactive_without_a_test_url(tmp_path: Path) -> None:
    assert_test_database_is_isolated(
        None,
        development_env_file=tmp_path / "missing.env",
    )

from __future__ import annotations

from pathlib import Path

from pglast import parse_sql

MIGRATIONS_DIR = Path("migrations")


def test_all_migrations_parse_as_postgresql() -> None:
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        parse_sql(path.read_text(encoding="utf-8"))


def test_asset_ingestion_hardening_migration_exists_and_adds_idempotency_constraints() -> None:
    migration = MIGRATIONS_DIR / "007_asset_ingestion_hardening.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "idx_assets_source_local_code_active" in sql
    assert "source_system, local_file_code" in sql
    assert "source_relative_path" in sql
    assert "idx_asset_files_asset_role_unique" in sql


def test_maitu_live_room_blueprint_migration_exists_and_stores_profile_and_blueprint() -> None:
    migration = MIGRATIONS_DIR / "008_maitu_live_room_blueprints.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "maitu_reference_room_profiles" in sql
    assert "maitu_live_room_blueprints" in sql
    assert "reference_profile_code" in sql
    assert "scenes JSONB" in sql
    assert "script_blocks JSONB" in sql

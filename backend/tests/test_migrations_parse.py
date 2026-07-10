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


def test_maitu_live_room_build_plan_migration_exists_and_stores_operations() -> None:
    migration = MIGRATIONS_DIR / "009_maitu_live_room_build_plans.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "maitu_live_room_build_plans" in sql
    assert "maitu_live_room_build_plan_operations" in sql
    assert "build_plan_code" in sql
    assert "operation_type" in sql


def test_maitu_layout_adjustment_migration_exists_and_stores_geometry() -> None:
    migration = MIGRATIONS_DIR / "010_maitu_layout_adjustments.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "maitu_layout_adjustments" in sql
    assert "adjustment_code" in sql
    assert "before_geometry JSONB" in sql
    assert "target_geometry JSONB" in sql
    assert "operation JSONB" in sql


def test_maitu_live_room_build_execution_result_migration_exists_and_stores_evidence() -> None:
    migration = MIGRATIONS_DIR / "011_maitu_live_room_build_execution_results.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "maitu_live_room_build_plan_executions" in sql
    assert "maitu_live_room_build_plan_operation_results" in sql
    assert "build_plan_code" in sql
    assert "execution_code" in sql
    assert "dom_snapshot_asset_code" in sql


def test_maitu_live_room_build_operation_selection_migration_exists_and_stores_selected_assets() -> None:
    migration = MIGRATIONS_DIR / "012_maitu_build_plan_operation_asset_selection.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "selected_asset_code" in sql
    assert "selected_asset_local_file_code" in sql
    assert "match_reasons JSONB" in sql
    assert "selection_source" in sql


def test_maitu_template_component_index_migration_exists_and_stores_scene_components() -> None:
    migration = MIGRATIONS_DIR / "013_maitu_live_room_template_component_index.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "maitu_live_room_template_scenes" in sql
    assert "maitu_live_room_template_components" in sql
    assert "scene_template_code" in sql
    assert "component_template_code" in sql
    assert "script_content TEXT" in sql
    assert "geometry JSONB" in sql


def test_jd_live_metric_capture_migration_exists_and_stores_sync_samples() -> None:
    migration = MIGRATIONS_DIR / "014_jd_live_metric_capture.sql"

    assert migration.exists()
    sql = migration.read_text(encoding="utf-8")
    assert "maitu_jd_live_metric_sessions" in sql
    assert "maitu_jd_live_metric_samples" in sql
    assert "capture_session_code" in sql
    assert "frontend_execution_code" in sql
    assert "online_viewers INTEGER" in sql
    assert "traffic_sources JSONB" in sql

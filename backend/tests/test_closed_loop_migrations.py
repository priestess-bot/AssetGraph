from __future__ import annotations

from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_closed_loop_core_migration_defines_distinct_revisioned_content_objects() -> None:
    sql = (MIGRATIONS / "027_closed_loop_content_core.sql").read_text(encoding="utf-8")

    for table in (
        "content_projects",
        "content_project_revisions",
        "story_brief_revisions",
        "content_script_revisions",
        "content_program_revisions",
        "program_segments",
        "shot_list_revisions",
        "shots",
        "production_variant_revisions",
        "shot_projection_links",
        "domain_derivation_edges",
        "stale_propagation_records",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "target_type IN ('maitu_scene_blueprint', 'layer_blueprint', 'timeline_segment')" in sql
    assert "protect_closed_loop_revision" in sql


def test_content_production_completion_migration_adds_explicit_sources_and_legacy_branch_links() -> None:
    sql = (MIGRATIONS / "034_content_production_aggregate_completion.sql").read_text(encoding="utf-8")

    for table in (
        "program_segment_script_block_adoptions",
        "shot_script_block_sources",
        "live_room_configurations",
        "live_room_configuration_revisions",
        "legacy_production_variant_links",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "ADD COLUMN production_variant_revision_id" in sql
    assert "shot projection links are append-only" in sql
    assert "Freshness is a rebuildable projection" in sql


def test_integrity_migration_hash_chains_authorizations_and_external_results() -> None:
    sql = (MIGRATIONS / "035_evidence_integrity_alerting.sql").read_text(encoding="utf-8")

    for table in (
        "execution_authorization_history",
        "evidence_integrity_alerts",
        "integrity_check_runs",
        "projection_event_consumptions",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "ADD COLUMN event_fingerprint" in sql
    assert "trg_workflow_external_history_append_only" in sql


def test_legacy_workflow_projection_migration_keeps_source_tables_authoritative() -> None:
    sql = (MIGRATIONS / "036_legacy_workflow_compatibility_projections.sql").read_text(encoding="utf-8")

    assert "CREATE OR REPLACE VIEW legacy_workflow_run_projections_v1" in sql
    assert "CREATE OR REPLACE VIEW legacy_workflow_step_projections_v1" in sql
    for source in (
        "maitu_workbench_runs",
        "video_production_jobs",
        "live_capture_sessions",
        "live_analysis_runs",
        "maitu_execution_retry_tasks",
    ):
        assert source in sql
    assert "Source tables remain authoritative" in sql


def test_control_plane_migration_defines_artifact_workflow_outbox_and_append_only_guards() -> None:
    sql = (MIGRATIONS / "028_artifact_workflow_control_plane.sql").read_text(encoding="utf-8")

    for table in (
        "artifact_refs",
        "run_manifests",
        "workflow_runs",
        "workflow_steps",
        "human_tasks",
        "lineage_edges",
        "transactional_outbox_events",
        "projection_checkpoints",
        "graph_projection_versions",
        "audit_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation()" in sql
    assert "claim_token UUID" in sql
    assert "lease_version INTEGER NOT NULL" in sql


def test_policy_release_data_migration_keeps_completion_delivery_and_exposure_distinct() -> None:
    sql = (MIGRATIONS / "029_policy_release_data_governance.sql").read_text(encoding="utf-8")

    for table in (
        "policy_decisions",
        "execution_authorizations",
        "protected_resources",
        "releases",
        "release_manifests",
        "delivery_attempts",
        "content_exposure_events",
        "metric_definition_revisions",
        "data_contracts",
        "attribution_results",
        "feature_snapshots",
        "decision_logs",
        "deletion_runs",
        "data_tombstones",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "VALUES ('go_live', '*', false, true" in sql
    assert "evidence_level IN ('descriptive', 'associational', 'quasi_experimental', 'randomized')" in sql


def test_console_draft_migration_separates_mutable_saves_from_explicit_commands() -> None:
    sql = (MIGRATIONS / "041_console_drafts_and_explicit_commands.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS console_drafts" in sql
    assert "CREATE TABLE IF NOT EXISTS console_draft_events" in sql
    assert "UNIQUE (entity_type, entity_code, draft_kind)" in sql
    assert "status IN ('active', 'consumed')" in sql
    assert "trg_console_draft_events_append_only" in sql
    assert "source_human_task_id UUID REFERENCES human_tasks(id)" in sql
    assert "uq_execution_authorization_source_task" in sql


def test_console_command_receipts_make_explicit_commands_idempotent() -> None:
    sql = (MIGRATIONS / "042_console_command_receipts.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS console_command_receipts" in sql
    assert "UNIQUE (command_type, entity_type, entity_code, idempotency_key)" in sql
    assert "'confirm', 'publish', 'approve', 'reject', 'authorize'" in sql
    assert "trg_console_command_receipts_append_only" in sql

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_script(relative_path: str, module_name: str) -> ModuleType:
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_verifier_accepts_committed_core_contract() -> None:
    verifier = load_script("scripts/verify_reproducibility.py", "assetgraph_verify_reproducibility")

    assert verifier.validate_repository(REPO_ROOT) == []


def test_bootstrap_generates_distinct_phase_d_secrets(tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_reproducible")
    (tmp_path / ".env.example").write_text(
        "ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN=\n"
        "ASSETGRAPH_MAITU_RECONCILIATION_OPERATOR_TOKEN=\n"
        "ASSETGRAPH_MAITU_AUTHORITY_TOKEN=\n"
        "ASSETGRAPH_MAITU_READBACK_ATTESTATION_KEY=\n",
        encoding="utf-8",
    )

    env_path = bootstrap.ensure_environment(tmp_path)
    values = [line.split("=", 1)[1] for line in env_path.read_text(encoding="utf-8").splitlines()]

    assert len(values) == 4
    assert len(set(values)) == 4
    assert all(len(value) >= 32 for value in values)


def test_windows_private_file_permissions_use_explicit_acl(monkeypatch, tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_windows_acl")
    target = tmp_path / ".env"
    target.write_text("A=1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    bootstrap._restrict_private_permissions(target, platform_name="nt", windows_user="assetgraph-user")

    assert calls == [[
        "icacls",
        str(target),
        "/inheritance:r",
        "/grant:r",
        "assetgraph-user:(F)",
    ]]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not meaningful on Windows")
def test_bootstrap_creates_owner_only_environment_file(tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_permissions")
    (tmp_path / ".env.example").write_text("A=1\n", encoding="utf-8")

    target = bootstrap.ensure_environment(tmp_path)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_bootstrap_fills_blank_secrets_in_existing_env(tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_existing_env")
    (tmp_path / ".env.example").write_text("IGNORED=example\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text(
        "CUSTOM_VALUE=keep-me\n"
        "ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN=\n"
        "ASSETGRAPH_MAITU_RECONCILIATION_OPERATOR_TOKEN=already-configured-value-with-32-characters\n"
        "ASSETGRAPH_MAITU_AUTHORITY_TOKEN=\n"
        "ASSETGRAPH_MAITU_READBACK_ATTESTATION_KEY=\n",
        encoding="utf-8",
    )

    bootstrap.ensure_environment(tmp_path)
    values = dict(
        line.split("=", 1)
        for line in target.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )

    assert values["CUSTOM_VALUE"] == "keep-me"
    assert values["ASSETGRAPH_MAITU_RECONCILIATION_OPERATOR_TOKEN"] == "already-configured-value-with-32-characters"
    assert all(len(values[key]) >= 32 for key in bootstrap.SECRET_KEYS)
    assert len({values[key] for key in bootstrap.SECRET_KEYS}) == 4


def test_install_skill_rejects_incomplete_existing_copy(monkeypatch, tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_skill_integrity")
    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    installed = bootstrap.install_skill(REPO_ROOT)
    (installed / "references" / "quality-baseline.md").unlink()

    with pytest.raises(RuntimeError, match="different content"):
        bootstrap.install_skill(REPO_ROOT)


def test_bootstrap_uses_windows_hermes_home_when_not_overridden(monkeypatch, tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_home")
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    resolved = bootstrap.default_hermes_home()

    expected = tmp_path / "hermes" if bootstrap.os.name == "nt" else Path.home() / ".hermes"
    assert resolved == expected


def test_qwen_model_bootstrap_syncs_locked_service_environment(monkeypatch, tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_qwen")
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _name: "hf")
    monkeypatch.setattr(bootstrap, "_run", lambda command, *, cwd: calls.append((command, cwd)))
    monkeypatch.setattr(bootstrap, "_load_manifest", lambda _root: {
        "qwen3": {
            "embedding": {"repository": "Qwen/Embedding", "revision": "a" * 40},
            "reranker": {"repository": "Qwen/Reranker", "revision": "b" * 40},
        }
    })

    bootstrap.download_qwen_models(tmp_path)

    assert (["uv", "sync", "--python", "3.12", "--frozen"], tmp_path / "services" / "qwen3") in calls


def test_live_research_tool_bootstrap_checks_out_locked_commits(monkeypatch, tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_live_research")
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(bootstrap, "_run", lambda command, *, cwd: calls.append((command, cwd)))
    monkeypatch.setattr(
        bootstrap,
        "_load_manifest",
        lambda _root: {
            "live_research": {
                "streamcap": {
                    "repository": "https://example/StreamCap.git",
                    "commit": "a" * 40,
                    "default_path": ".external/StreamCap",
                },
                "douyin_live": {
                    "repository": "https://example/douyinLive.git",
                    "commit": "b" * 40,
                    "default_path": ".external/douyinLive",
                },
            }
        },
    )

    paths = bootstrap.install_live_research_tools(tmp_path)

    assert paths == (tmp_path / ".external" / "StreamCap", tmp_path / ".external" / "douyinLive")
    assert (["git", "checkout", "--detach", "a" * 40], paths[0]) in calls
    assert (["git", "checkout", "--detach", "b" * 40], paths[1]) in calls


def test_video_demo_bootstrap_installs_locked_runtime_and_frontend(monkeypatch, tmp_path: Path) -> None:
    bootstrap = load_script("scripts/bootstrap_reproducible.py", "assetgraph_bootstrap_video_demo")
    worker_root = tmp_path / "workers" / "video-production"
    frontend_root = tmp_path / "frontend"
    python = worker_root / ".venv" / "bin" / "python"
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        bootstrap.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"npm", "ffmpeg", "ffprobe", "fc-match"} else None,
    )
    monkeypatch.setattr(bootstrap, "_venv_python", lambda _project: python)
    monkeypatch.setattr(bootstrap, "_run", lambda command, *, cwd: calls.append((command, cwd)))

    model_root = bootstrap.install_video_demo(tmp_path)

    assert (["uv", "sync", "--python", "3.12", "--frozen"], worker_root) in calls
    assert (["npm", "ci"], frontend_root) in calls
    assert (["npm", "run", "build"], frontend_root) in calls
    assert model_root == tmp_path / ".external" / "models" / "kokoro"


def test_migration_discovery_is_contiguous() -> None:
    migrations = load_script("scripts/apply_migrations.py", "assetgraph_apply_migrations")

    discovered = migrations.discover_migrations(REPO_ROOT / "backend" / "migrations")

    assert [path.name for path in discovered] == [
        f"{index:03d}_{name}"
        for index, name in enumerate(
            [
                "initial_schema.sql",
                "digital_human_livestream_schema.sql",
                "maitu_asset_metadata.sql",
                "maitu_replacement_plans.sql",
                "maitu_execution_results.sql",
                "asset_local_material_mapping.sql",
                "asset_ingestion_hardening.sql",
                "maitu_live_room_blueprints.sql",
                "maitu_live_room_build_plans.sql",
                "maitu_layout_adjustments.sql",
                "maitu_live_room_build_execution_results.sql",
                "maitu_build_plan_operation_asset_selection.sql",
                "maitu_live_room_template_component_index.sql",
                "jd_live_metric_capture.sql",
                "asset_maitu_material_binding.sql",
                "maitu_retry_lease_idempotency.sql",
                "maitu_retry_operation_checkpoints.sql",
                "maitu_retry_operation_reconciliation.sql",
                "maitu_retry_mutation_intent.sql",
                "script_driven_build_plan_persistence.sql",
                "script_layout_execution_checkpoints.sql",
                "video_production_jobs.sql",
                "maitu_production_workbench.sql",
                "live_research_observations.sql",
                "maitu_material_analysis.sql",
                "maitu_reference_template_handoff.sql",
                "closed_loop_content_core.sql",
                "artifact_workflow_control_plane.sql",
                "policy_release_data_governance.sql",
                "phase0_capability_defaults.sql",
                "metric_contract_quality_details.sql",
                "catalog_revision_immutability.sql",
                "workflow_external_effect_protocol.sql",
                "content_production_aggregate_completion.sql",
                "evidence_integrity_alerting.sql",
                "legacy_workflow_compatibility_projections.sql",
                "least_privilege_and_protected_resource_registry.sql",
                "privacy_retention_deletion_credentials.sql",
                "deletion_retry_receipts.sql",
                "legacy_domain_compatibility_projections.sql",
                "console_drafts_and_explicit_commands.sql",
                "console_command_receipts.sql",
                "provider_neutral_producer_contracts.sql",
                "provider_neutral_analysis_identity.sql",
                "functional_fast_track_assets.sql",
                "functional_live_room_plans.sql",
                "functional_video_plans.sql",
                "functional_operations.sql",
                "functional_learning_experiments.sql",
                "functional_knowledge.sql",
                "functional_design_briefs.sql",
                "maitu_scene_blueprint_projections.sql",
                "functional_live_room_plan_gates.sql",
                "functional_live_room_release_candidates.sql",
                "functional_live_room_plan_clones.sql",
                "functional_live_room_operation_trace_links.sql",
                "functional_live_room_material_packs.sql",
                "content_strategy_template_contract.sql",
                "asset_gap_resolution_lifecycle.sql",
                "functional_video_timeline_revisions.sql",
                "functional_content_exposures.sql",
                "functional_operation_session_source_context.sql",
                "functional_content_exposure_corrections.sql",
                "functional_operation_metric_definition_refs.sql",
                "functional_session_time_mappings.sql",
                "functional_effect_estimates.sql",
                "functional_video_release_candidates.sql",
                "video_render_manifest_artifact.sql",
                "functional_attribution_report_runs.sql",
                "standard_event_quality_batches.sql",
                "functional_session_metric_snapshots.sql",
                "functional_session_metric_buckets.sql",
                "functional_effect_revocation_details.sql",
                "functional_experiment_registrations.sql",
                "functional_experiment_assignments.sql",
                "functional_decision_log_evidence.sql",
                "broadcast_schedules.sql",
                "knowledge_source_evidence.sql",
                "knowledge_evidence_revocations.sql",
                "knowledge_evidence_rejections.sql",
                "constraint_profile_promotion_provenance.sql",
                "material_pack_resolution_contract.sql",
                "functional_video_timeline_segments.sql",
                "functional_video_timeline_segment_script_sources.sql",
                "functional_video_timeline_segment_execution_artifacts.sql",
                "functional_video_timeline_segment_asset_files.sql",
                "functional_video_timeline_segment_render_artifacts.sql",
                "functional_video_timeline_segment_source_media_probes.sql",
                "video_render_manifest_retry_diff.sql",
                "video_delivery_metadata_sidecar.sql",
            ],
            start=1,
        )
    ]

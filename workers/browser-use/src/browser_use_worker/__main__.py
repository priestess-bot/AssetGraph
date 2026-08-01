from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .browser_cli_session import BrowserUseCliSession, is_trusted_browser_use_cli_session
from .build_plan_dry_run import BuildPlanDryRun
from .build_plan_non_destructive import BuildPlanNonDestructiveRunner, build_non_destructive_execution_payload
from .build_plan_preflight import BuildPlanPreflight
from .client import AssetGraphClient, AssetGraphClientError
from .config import WorkerConfig
from .jd_metrics import capture_jd_live_metric_sample
from .live_scene_fill import LiveSceneFillRunner, build_live_scene_fill_execution_payload
from .maitu_material_resolver import MaituMaterialResolutionResult, MaituMaterialResolver
from .maitu_inventory_sync import MaituInventoryCollector
from .preflight import ReplacementPlanPreflight
from .runner import BrowserUseWorker, DryRunBrowserUseExecutor
from .room_inspection import inspect_working_room
from .functional_draft_verification import verify_functional_draft
from .functional_test_draft import enable_test_pending_rights_plan, reset_allowlisted_test_room
from .script_layout_checkpoint import (
    AssetGraphScriptLayoutCheckpointStore,
    _durable_execution_value,
)
from .script_layout_draft_executor import (
    InMemoryScriptLayoutDraftSession,
    ScriptLayoutDraftResult,
    ScriptLayoutDraftRunner,
)
from .maitu_test_room_rebuild import MaituTestRoomRebuildRunner, MaituTestRoomRebuildSpec
from .workbench_draft_lease import WorkbenchDraftLeaseHeartbeat


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ASSETS_ROOT = REPO_ROOT / "素材"


def _workbench_draft_heartbeat_interval_seconds(lease_seconds: int) -> float:
    raw = os.getenv("ASSETGRAPH_WORKBENCH_DRAFT_HEARTBEAT_INTERVAL_SECONDS", "30")
    try:
        configured = float(raw)
    except ValueError as exc:
        raise ValueError("ASSETGRAPH_WORKBENCH_DRAFT_HEARTBEAT_INTERVAL_SECONDS must be numeric") from exc
    if configured <= 0:
        raise ValueError("ASSETGRAPH_WORKBENCH_DRAFT_HEARTBEAT_INTERVAL_SECONDS must be positive")
    return min(configured, lease_seconds / 3)


def _checkpoint_completion_evidence(checkpoint_result: dict) -> dict:
    public_fields = {
        "execution_code",
        "build_plan_code",
        "execution_status",
        "status",
        "expected_operation_count",
        "result_summary",
        "ready_for_go_live",
        "manual_review_required",
        "finalized_at",
    }
    return _durable_execution_value(
        {
            key: value
            for key, value in checkpoint_result.items()
            if key in public_fields
        }
    )


def _worker_result_evidence(result: object) -> dict:
    """Keep runner outcomes without persisting raw provider responses."""

    if not is_dataclass(result):
        raise TypeError("worker result evidence requires a dataclass result")
    raw_result = asdict(result)
    evidence = {
        key: raw_result[key]
        for key in (
            "status",
            "target_live_room_id",
            "ready_for_go_live",
            "manual_review_required",
            "summary",
            "operation_count",
            "executed_action_count",
            "skipped_action_count",
            "placeholder_count",
            "failure_count",
        )
        if key in raw_result
    }

    def numeric_id(value: object) -> int | str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return value
        return None

    result_fields = (
        "preflight_result",
        "rename_result",
        "create_result",
        "insert_result",
        "position_result",
        "write_result",
        "verify_result",
        "draft_result",
    )
    verification_scalar_fields = (
        "verified",
        "verification_source",
        "environment",
        "not_live",
        "save_clicked",
        "go_live_clicked",
        "script_content_verified",
        "sound_enabled",
        "expected_visual_count",
        "expected_text_count",
        "scene_count",
        "left",
        "top",
        "width",
        "height",
        "z_index",
        "fit",
        "rotation",
        "loop",
        "expected_live_room_title",
        "authoritative_live_room_title",
    )
    verification_id_fields = (
        "default_clip_id",
        "material_id",
        "text_material_id",
        "source_material_id",
        "speaker_id",
        "digital_human_image_id",
    )
    actions: list[dict] = []
    for raw_action in raw_result.get("actions") or []:
        if not isinstance(raw_action, dict):
            continue
        action = {
            key: raw_action[key]
            for key in (
                "operation_index",
                "operation_type",
                "operation_name",
                "action_type",
                "status",
                "summary",
                "scene_index",
                "scene_name",
                "layer_id",
                "layer_type",
                "asset_code",
            )
            if key in raw_action and raw_action[key] is not None
        }
        clip_id = numeric_id(raw_action.get("clip_id"))
        if clip_id is not None:
            action["clip_id"] = clip_id
        raw_details = raw_action.get("details")
        raw_details = raw_details if isinstance(raw_details, dict) else {}
        details = {"go_live_clicked": raw_details.get("go_live_clicked") is True}
        nested_result = next(
            (
                raw_details[field_name]
                for field_name in result_fields
                if isinstance(raw_details.get(field_name), dict)
            ),
            None,
        )
        if isinstance(nested_result, dict):
            verification = {
                key: nested_result[key]
                for key in verification_scalar_fields
                if key in nested_result and nested_result[key] is not None
            }
            for field_name in verification_id_fields:
                public_id = numeric_id(nested_result.get(field_name))
                if public_id is not None:
                    verification[field_name] = public_id
            for field_name in ("expected_scene_names", "actual_scene_names"):
                value = nested_result.get(field_name)
                if isinstance(value, list) and all(isinstance(item, str) for item in value):
                    verification[field_name] = list(value)
            if verification:
                details["verification"] = verification
        action["details"] = details
        actions.append(action)
    evidence["actions"] = actions
    return _durable_execution_value(evidence)


def _final_readback_evidence(room: dict) -> dict:
    """Project a Maitu room into stable, credential-free product evidence."""

    def numeric_id(value: object) -> int | str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return value
        return None

    def optional_field(source: dict, target: dict, key: str, *aliases: str) -> None:
        for candidate in (key, *aliases):
            if candidate in source and source[candidate] is not None:
                target[key] = source[candidate]
                return

    def public_style(value: object) -> dict:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return {}
        if not isinstance(value, dict):
            return {}
        result = {
            key: value[key]
            for key in ("left", "top", "width", "height", "zIndex", "fit", "opacity")
            if key in value and isinstance(value[key], (int, float, bool))
            or key == "fit" and isinstance(value.get(key), str)
        }
        transform = value.get("transform")
        if isinstance(transform, dict):
            public_transform = {
                key: transform[key]
                for key in ("rotation", "scale", "scaleX", "scaleY")
                if key in transform and isinstance(transform[key], (int, float))
            }
            if public_transform:
                result["transform"] = public_transform
        return result

    evidence: dict = {"schema_version": "maitu-final-readback-evidence.v1"}
    room_id = numeric_id(room.get("id") if room.get("id") is not None else room.get("live_room_id"))
    if room_id is not None:
        evidence["id"] = room_id
    optional_field(room, evidence, "name", "title")
    optional_field(room, evidence, "status", "live_status", "room_status")
    optional_field(room, evidence, "is_live", "living", "is_living")
    optional_field(room, evidence, "environment", "_assetgraph_read_environment")
    topics: list[dict] = []
    for raw_topic in room.get("topics") or []:
        if not isinstance(raw_topic, dict):
            continue
        topic: dict = {}
        topic_id = numeric_id(raw_topic.get("id"))
        if topic_id is not None:
            topic["id"] = topic_id
        optional_field(raw_topic, topic, "name")
        clips: list[dict] = []
        for raw_clip in raw_topic.get("clips") or []:
            if not isinstance(raw_clip, dict):
                continue
            clip: dict = {}
            clip_id = numeric_id(raw_clip.get("id"))
            if clip_id is not None:
                clip["id"] = clip_id
            optional_field(raw_clip, clip, "name")
            materials: list[dict] = []
            for raw_material in raw_clip.get("clip_materials") or []:
                if not isinstance(raw_material, dict):
                    continue
                material: dict = {}
                material_id = numeric_id(raw_material.get("id"))
                if material_id is not None:
                    material["id"] = material_id
                for field_name in (
                    "name",
                    "type",
                    "content",
                    "left",
                    "top",
                    "width",
                    "height",
                    "sound_enabled",
                ):
                    optional_field(raw_material, material, field_name)
                optional_field(raw_material, material, "z_index", "layer_n")
                optional_field(raw_material, material, "source_material_type")
                for field_name, aliases in (
                    ("source_material_id", ("material_id",)),
                    ("speaker_id", ()),
                    ("digital_human_image_id", ()),
                ):
                    source_value = next(
                        (
                            raw_material[candidate]
                            for candidate in (field_name, *aliases)
                            if raw_material.get(candidate) is not None
                        ),
                        None,
                    )
                    public_id = numeric_id(source_value)
                    if public_id is not None:
                        material[field_name] = public_id
                style_front = public_style(raw_material.get("style_front"))
                if style_front:
                    material["style_front"] = style_front
                materials.append(material)
            clip["clip_materials"] = materials
            clips.append(clip)
        topic["clips"] = clips
        topics.append(topic)
    evidence["topics"] = topics
    return evidence


def _best_effort_fail_workbench_draft_job(
    api: AssetGraphClient,
    *,
    job_code: str,
    lease_token: str,
    error: Exception,
    reconcile_required: bool = False,
) -> None:
    logging.getLogger(__name__).error(
        "Workbench draft job %s failed before durable write-back",
        job_code,
        exc_info=(type(error), error, error.__traceback__),
    )
    try:
        raw_error_text = f"{type(error).__name__}: {error}"
        error_code = (
            "MATERIAL_RESOLUTION_FAILED"
            if "素材准备失败" in raw_error_text or "material resolution" in raw_error_text.lower()
            else "WORKBENCH_DRAFT_EXECUTION_FAILED"
        )
        error_message = (
            "素材准备失败，请检查素材绑定后重试。"
            if error_code == "MATERIAL_RESOLUTION_FAILED"
            else "草稿生成失败，请查看执行日志并在确认现场状态后重试。"
        )
        api.fail_workbench_draft_execution(
            job_code,
            {
                "lease_token": lease_token,
                "error_code": error_code,
                "error_message": error_message,
                "reconcile_required": reconcile_required,
            },
        )
    except AssetGraphClientError as fail_error:
        if "HTTP 409" in str(fail_error):
            logging.getLogger(__name__).warning(
                "Workbench draft failure write-back was fenced by a lost/already-finalized lease: %s",
                fail_error,
            )
            return
        logging.getLogger(__name__).exception("Failed to persist workbench draft job failure")
    except Exception:
        logging.getLogger(__name__).exception("Failed to persist workbench draft job failure")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AssetGraph browser-use worker.")
    parser.add_argument("--once", action="store_true", help="Run a single claim/execute/write-back cycle")
    parser.add_argument("--dry-run", action="store_true", help="Validate operation plans but do not operate Maitu")
    parser.add_argument("--probe-maitu", action="store_true", help="Run a read-only browser-use probe of the current Maitu page")
    parser.add_argument("--observe-maitu", action="store_true", help="Read structured current Maitu live-room state for the Observe step")
    parser.add_argument(
        "--sync-maitu-inventory",
        action="store_true",
        help="Claim one workbench inventory job and persist an authenticated Maitu snapshot",
    )
    parser.add_argument("--inventory-sync-job-code", help="Claim one specific queued inventory sync job")
    parser.add_argument(
        "--run-workbench-draft-job",
        action="store_true",
        help="Claim and execute one preflight-passed workbench draft job",
    )
    parser.add_argument(
        "--run-room-inspection-job",
        action="store_true",
        help="Claim one read-only Maitu working-room inspection job",
    )
    parser.add_argument("--workbench-draft-job-code", help="Claim one specific workbench draft job")
    parser.add_argument(
        "--download-missing-maitu-materials",
        action="store_true",
        help="Download newly discovered regular Maitu files into the configured mirror",
    )
    parser.add_argument(
        "--maitu-mirror-root",
        default=os.getenv("ASSETGRAPH_MAITU_MIRROR_ROOT", "/DATA/Downloads/AssetGraph/maitu-mirror"),
    )
    parser.add_argument(
        "--maitu-local-catalog",
        default=os.getenv(
            "ASSETGRAPH_LOCAL_ASSET_CATALOG",
            "/DATA/Downloads/AssetGraph/catalog/current_asset_inventory.json",
        ),
    )
    parser.add_argument("--plan-code", help="Fetch a replacement plan operation plan and execute/dry-run it once")
    parser.add_argument("--build-plan-code", help="Fetch a live-room BuildPlan operation plan and run BuildPlan-specific dry-run/preflight")
    parser.add_argument("--preflight", action="store_true", help="Run read-only safety checks for --plan-code before mutating Maitu")
    parser.add_argument("--preflight-build", action="store_true", help="Run read-only safety checks for --build-plan-code before mutating Maitu")
    parser.add_argument("--non-destructive-build", action="store_true", help="Run only low-risk BuildPlan UI navigation after a green preflight")
    parser.add_argument("--live-scene-fill", action="store_true", help="Fill the first planned BuildPlan scene into an existing draft room default clip")
    parser.add_argument(
        "--script-layout-draft-execute",
        action="store_true",
        help="Execute a script-layout BuildPlan JSON file into a safe draft; real runs require --resolve-maitu-materials, use --dry-run for in-memory smoke",
    )
    parser.add_argument("--script-layout-build-plan-file", help="Path to a script-layout-build-plans JSON response for --script-layout-draft-execute")
    parser.add_argument("--resolve-maitu-materials", action="store_true", help="Resolve selected AssetGraph assets against Maitu and upload only when no existing material matches")
    parser.add_argument("--resolved-plan-file", help="Optional path for the BuildPlan JSON after Maitu material resolution")
    parser.add_argument("--target-live-room-id", help="Target Maitu draft liveRoomId for --live-scene-fill or --script-layout-draft-execute")
    parser.add_argument(
        "--maitu-test-room-rebuild-file",
        help="Destructively reset and rebuild the one explicit offline Maitu test draft described by this JSON spec",
    )
    parser.add_argument("--write-result", action="store_true", help="Write direct-plan execution/evidence result back to AssetGraph")
    parser.add_argument("--capture-jd-metrics", action="store_true", help="Capture JD live dashboard metrics and write samples to AssetGraph")
    parser.add_argument("--jd-metric-session-code", help="JD live metric capture session code (JD-METRIC-*)")
    parser.add_argument("--max-samples", type=int, default=1, help="Maximum JD dashboard metric samples to capture in this run")
    parser.add_argument("--capture-interval-seconds", type=float, default=0, help="Sleep interval between JD metric samples")
    parser.add_argument("--skip-browser-probe", action="store_true", help="Skip Browser-use/Maitu page probing during --preflight")
    parser.add_argument(
        "--assets-root",
        default=os.getenv("ASSETGRAPH_ASSETS_ROOT", str(DEFAULT_ASSETS_ROOT)),
        help="Local asset root used by --preflight file checks",
    )
    parser.add_argument("--check-config", action="store_true", help="Print resolved configuration and exit without calling AssetGraph")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    return parser.parse_args(argv)


def _selected_cli_modes(args: argparse.Namespace) -> list[str]:
    modes = [
        name
        for name, selected in (
            ("check_config", args.check_config),
            ("probe_maitu", args.probe_maitu),
            ("observe_maitu", args.observe_maitu),
            ("sync_maitu_inventory", args.sync_maitu_inventory),
            ("workbench_draft_job", args.run_workbench_draft_job),
            ("room_inspection_job", args.run_room_inspection_job),
            ("capture_jd_metrics", args.capture_jd_metrics),
            ("script_layout", args.resolve_maitu_materials or args.script_layout_draft_execute),
            ("maitu_test_room_rebuild", bool(args.maitu_test_room_rebuild_file)),
            ("live_scene_fill", args.live_scene_fill),
            ("non_destructive_build", args.non_destructive_build),
            ("preflight_build", args.preflight_build),
            ("replacement_preflight", args.preflight),
            ("queue_once", args.once),
        )
        if selected
    ]
    if args.plan_code and not args.preflight:
        modes.append("replacement_plan")
    if args.build_plan_code and args.dry_run and not any(
        (
            args.live_scene_fill,
            args.non_destructive_build,
            args.preflight_build,
            args.resolve_maitu_materials,
            args.script_layout_draft_execute,
        )
    ):
        modes.append("build_plan_dry_run")
    return modes


def _require_bound_draft_target(operation_plan: dict, requested_live_room_id: str | None) -> str:
    raw_plan_live_room_id = operation_plan.get("target_live_room_id")
    plan_live_room_id = str(raw_plan_live_room_id).strip() if raw_plan_live_room_id is not None else ""
    if not plan_live_room_id or raw_plan_live_room_id != plan_live_room_id:
        raise SystemExit("Real script-layout draft execution requires a canonical target_live_room_id bound into the BuildPlan")
    if requested_live_room_id is not None and requested_live_room_id != plan_live_room_id:
        raise SystemExit(
            f"Requested target live room {requested_live_room_id} does not match the BuildPlan target {plan_live_room_id}"
        )
    return plan_live_room_id


def _require_executable_script_layout_plan(operation_plan: dict) -> None:
    status = str(operation_plan.get("status") or "").strip()
    blocked_reasons = [str(reason) for reason in (operation_plan.get("blocked_reasons") or []) if str(reason)]
    can_execute = operation_plan.get("can_execute") is True
    manual_review_required = operation_plan.get("manual_review_required") is True
    status_is_executable = status == "ready"
    if not status_is_executable or not can_execute or manual_review_required or blocked_reasons:
        reasons = ", ".join(blocked_reasons) if blocked_reasons else "none"
        raise SystemExit(
            "Script-layout plan is not executable before material resolution: "
            f"status={status or 'missing'}, can_execute={can_execute}, "
            f"manual_review_required={manual_review_required}, blocked_reasons={reasons}"
        )


def _require_bound_live_scene_target(operation_plan: dict, requested_live_room_id: str) -> str:
    raw_plan_live_room_id = operation_plan.get("target_live_room_id")
    plan_live_room_id = str(raw_plan_live_room_id).strip() if raw_plan_live_room_id is not None else ""
    if not plan_live_room_id or raw_plan_live_room_id != plan_live_room_id:
        raise SystemExit("Real live-scene-fill execution requires a canonical target_live_room_id bound into the BuildPlan")
    if requested_live_room_id != plan_live_room_id:
        raise SystemExit(
            f"Requested target live room {requested_live_room_id} does not match the BuildPlan target {plan_live_room_id}"
        )
    return plan_live_room_id


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = WorkerConfig.from_env(dry_run=args.dry_run)
    if args.dry_run and args.live_scene_fill:
        raise SystemExit("--live-scene-fill cannot run with --dry-run; use BuildPlan dry-run instead of a mutating runner")
    if args.dry_run and args.write_result:
        raise SystemExit("--dry-run cannot use --write-result because simulations must not update production execution state")
    if args.dry_run and args.resolve_maitu_materials:
        raise SystemExit("--resolve-maitu-materials cannot run with --dry-run because binding write-back/upload is a real action")
    if args.dry_run and args.once:
        raise SystemExit("--once cannot run with --dry-run because claiming or releasing a retry task writes queue state")
    if args.dry_run and args.capture_jd_metrics:
        raise SystemExit("--capture-jd-metrics cannot run with --dry-run because metric capture writes production session/sample state")
    if args.dry_run and args.sync_maitu_inventory:
        raise SystemExit("--sync-maitu-inventory cannot run with --dry-run because it writes an immutable inventory snapshot")
    if args.dry_run and args.run_workbench_draft_job:
        raise SystemExit("--run-workbench-draft-job cannot run with --dry-run")
    if args.dry_run and args.run_room_inspection_job:
        raise SystemExit("--run-room-inspection-job cannot run with --dry-run")
    if args.dry_run and args.maitu_test_room_rebuild_file:
        raise SystemExit("--maitu-test-room-rebuild-file cannot run with --dry-run because it clears a real test draft")
    if args.dry_run and args.non_destructive_build:
        raise SystemExit("--non-destructive-build cannot run with --dry-run because it opens and operates a real browser session")
    if args.dry_run and not any(
        (
            args.check_config,
            args.probe_maitu,
            args.observe_maitu,
            args.plan_code,
            args.build_plan_code,
            args.preflight,
            args.preflight_build,
            args.script_layout_draft_execute,
        )
    ):
        raise SystemExit("--dry-run requires an explicit read-only plan, preflight, probe, observe, or in-memory script-layout mode")
    selected_modes = _selected_cli_modes(args)
    if len(selected_modes) > 1:
        raise SystemExit(f"Conflicting CLI modes: {', '.join(selected_modes)}")
    if args.resolve_maitu_materials or args.script_layout_draft_execute:
        source_count = int(bool(args.script_layout_build_plan_file)) + int(bool(args.build_plan_code))
        if source_count != 1:
            raise SystemExit(
                "Script-layout mode requires exactly one plan source: "
                "--script-layout-build-plan-file or --build-plan-code"
            )
    if args.check_config:
        config_output = asdict(config)
        if config_output.get("script_layout_worker_token"):
            config_output["script_layout_worker_token"] = "[CONFIGURED]"
        print(json.dumps(config_output, ensure_ascii=False, indent=2))
        return 0
    if args.probe_maitu:
        probe = BrowserUseCliSession().probe_current_page(open_if_needed=True)
        print(json.dumps(asdict(probe), ensure_ascii=True, indent=2))
        return 0 if probe.logged_in and not probe.login_required else 2
    if args.observe_maitu:
        state = BrowserUseCliSession().read_current_state(open_if_needed=True)
        print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
        return 0 if state.logged_in and not state.login_required else 2
    if args.maitu_test_room_rebuild_file:
        spec_path = Path(args.maitu_test_room_rebuild_file)
        try:
            raw_spec = json.loads(spec_path.read_text(encoding="utf-8"))
            spec = MaituTestRoomRebuildSpec.from_dict(raw_spec)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(f"Invalid Maitu test-room rebuild spec: {exc}") from exc
        session = BrowserUseCliSession()
        if not is_trusted_browser_use_cli_session(session):
            raise SystemExit("Maitu test-room rebuild requires the sealed Browser-use CLI session")
        result = MaituTestRoomRebuildRunner(session=session).run(spec)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0 if result.status == "completed" and result.failure_count == 0 else 2

    client: AssetGraphClient | None = None

    def assetgraph_client() -> AssetGraphClient:
        nonlocal client
        if client is None:
            client = AssetGraphClient(config.api_base_url)
            if hasattr(client, "script_layout_worker_token"):
                client.script_layout_worker_token = config.script_layout_worker_token
            if hasattr(client, "worker_id"):
                client.worker_id = config.worker_id
        return client

    source_operation_plan: dict | None = None

    def load_script_layout_operation_plan() -> dict:
        nonlocal source_operation_plan
        if source_operation_plan is None:
            if args.script_layout_build_plan_file:
                plan_path = Path(args.script_layout_build_plan_file)
                source_operation_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            else:
                source_operation_plan = assetgraph_client().get_live_room_build_plan_operation_plan(
                    str(args.build_plan_code)
                )
        return source_operation_plan

    if args.run_room_inspection_job:
        api = assetgraph_client()
        lease_seconds = 120
        claimed = api.claim_next_room_inspection({"lease_seconds": lease_seconds})
        if claimed is None:
            print(json.dumps({"status": "idle", "summary": "No queued room inspection job."}, ensure_ascii=False))
            return 0
        inspection_code = str(claimed["inspection_code"])
        lease_token = str(claimed["lease_token"])
        try:
            session = BrowserUseCliSession()
            if not is_trusted_browser_use_cli_session(session):
                raise RuntimeError("room inspection requires the sealed Browser-use CLI session")
            api.heartbeat_room_inspection(
                inspection_code,
                {"lease_token": lease_token, "lease_seconds": lease_seconds},
            )
            result = inspect_working_room(
                session,
                target_live_room_id=str(claimed["target_live_room_id"]),
                expected_title=claimed.get("expected_title"),
            )
            completed = api.complete_room_inspection(
                inspection_code,
                {"lease_token": lease_token, "result": result},
            )
        except Exception as exc:
            try:
                api.fail_room_inspection(
                    inspection_code,
                    {
                        "lease_token": lease_token,
                        "error_code": "MAITU_ROOM_INSPECTION_FAILED",
                        "error_message": f"{type(exc).__name__}: {exc}"[:4000],
                    },
                )
            except Exception:
                logging.getLogger(__name__).exception("Failed to persist room inspection failure")
            raise
        print(json.dumps(completed, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.sync_maitu_inventory:
        api = assetgraph_client()
        claim_payload = {"lease_seconds": 3600}
        claimed = (
            api.claim_maitu_inventory_sync(args.inventory_sync_job_code, claim_payload)
            if args.inventory_sync_job_code
            else api.claim_next_maitu_inventory_sync(claim_payload)
        )
        if claimed is None:
            print(json.dumps({"status": "idle", "summary": "No queued Maitu inventory sync job."}, ensure_ascii=False))
            return 0
        sync_job_code = str(claimed["sync_job_code"])
        lease_token = str(claimed["lease_token"])
        try:
            result = MaituInventoryCollector(
                session=BrowserUseCliSession(),
                mirror_root=Path(args.maitu_mirror_root),
                local_catalog_path=Path(args.maitu_local_catalog),
            ).collect(download_missing=args.download_missing_maitu_materials)
            completed = api.complete_maitu_inventory_sync(
                sync_job_code,
                {
                    "lease_token": lease_token,
                    "source_revision": result.source_revision,
                    "schema_version": "maitu-inventory-snapshot-v1",
                    "quality_status": result.quality_status,
                    "captured_at": result.captured_at,
                    "summary": result.summary,
                    "items": list(result.items),
                },
            )
        except Exception as exc:
            api.fail_maitu_inventory_sync(
                sync_job_code,
                {
                    "lease_token": lease_token,
                    "error_code": "MAITU_INVENTORY_SYNC_FAILED",
                    "error_message": f"{type(exc).__name__}: {exc}"[:4000],
                },
            )
            raise
        print(json.dumps(completed, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.run_workbench_draft_job:
        api = assetgraph_client()
        lease_seconds = 3600
        claim_payload = {"lease_seconds": lease_seconds}
        claimed = (
            api.claim_workbench_draft_execution(args.workbench_draft_job_code, claim_payload)
            if args.workbench_draft_job_code
            else api.claim_next_workbench_draft_execution(claim_payload)
        )
        if claimed is None:
            print(json.dumps({"status": "idle", "summary": "No queued workbench draft job."}, ensure_ascii=False))
            return 0
        job_code = str(claimed["execution_job_code"])
        lease_token = str(claimed["lease_token"])
        heartbeat = WorkbenchDraftLeaseHeartbeat(
            client=api,
            execution_job_code=job_code,
            lease_token=lease_token,
            lease_seconds=lease_seconds,
            configured_interval_seconds=_workbench_draft_heartbeat_interval_seconds(lease_seconds),
        )
        browser_session: BrowserUseCliSession | None = None
        checkpoint_store: AssetGraphScriptLayoutCheckpointStore | None = None
        checkpoint_finalized = False
        destructive_started = False
        source_kind = str(claimed.get("source_kind") or "workbench_run")
        try:
            heartbeat.start()
            embedded = claimed.get("payload") if isinstance(claimed.get("payload"), dict) else {}
            embedded_plan = embedded.get("build_plan") if isinstance(embedded.get("build_plan"), dict) else {}
            build_plan_code = str(embedded_plan.get("build_plan_code") or "").strip()
            if not build_plan_code:
                raise RuntimeError("workbench draft job has no persisted build_plan_code")
            source_plan = api.get_live_room_build_plan_operation_plan(build_plan_code)
            if source_kind == "functional_live_room_plan":
                source_plan = enable_test_pending_rights_plan(source_plan, job_payload=embedded)
            _require_executable_script_layout_plan(source_plan)
            browser_session = BrowserUseCliSession()
            browser_session.set_execution_guard(heartbeat.ensure_active)

            def report_stage(stage: str, current: int, message: str) -> None:
                nonlocal destructive_started
                heartbeat.ensure_active()
                if stage == "clearing_draft":
                    destructive_started = True
                api.heartbeat_workbench_draft_execution(
                    job_code,
                    {
                        "lease_token": lease_token,
                        "lease_seconds": lease_seconds,
                        "stage": stage,
                        "progress_current": current,
                        "progress_total": 5,
                        "message": message,
                    },
                )

            report_stage("preparing_materials", 0, "正在解析并核对全部麦兔素材")
            resolution = MaituMaterialResolver(
                asset_client=api,
                session=browser_session,
                assets_root=args.assets_root,
                allow_worker_readback_binding=(source_kind == "functional_live_room_plan"),
                functional_execution_job_code=(
                    job_code if source_kind == "functional_live_room_plan" else None
                ),
                functional_lease_token=(
                    lease_token if source_kind == "functional_live_room_plan" else None
                ),
            ).resolve_plan(source_plan)
            if resolution.status != "resolved" or resolution.issues or resolution.manual_required_count:
                issue_text = "、".join(
                    f"{issue.asset_code or '未知素材'}（{issue.reason}）"
                    for issue in resolution.issues
                )
                raise RuntimeError(
                    "素材准备失败："
                    f"{issue_text or '存在未解析素材'}；"
                    f"共 {len(resolution.issues)} 项需处理"
                )
            heartbeat.ensure_active()
            operation_plan = resolution.operation_plan
            target_live_room_id = _require_bound_draft_target(operation_plan, None)
            if not is_trusted_browser_use_cli_session(browser_session):
                raise RuntimeError("workbench draft execution requires the sealed Browser-use CLI session")
            checkpoint_store = AssetGraphScriptLayoutCheckpointStore.start(
                client=api,
                operation_plan=operation_plan,
                target_live_room_id=target_live_room_id,
            )
            reset_evidence: dict = {}
            if source_kind == "functional_live_room_plan":
                reset_evidence = reset_allowlisted_test_room(
                    browser_session,
                    job_payload=embedded,
                    progress=report_stage,
                )

            def combined_execution_guard() -> bool:
                heartbeat.ensure_active()
                return checkpoint_store.ensure_lease_active()

            browser_session.set_execution_guard(combined_execution_guard)
            last_reported_stage: str | None = None

            def report_operation_progress(_index: int, _total: int, operation_type: str) -> None:
                nonlocal last_reported_stage
                if operation_type == "write_script":
                    stage, current, message = "writing_scripts", 3, "正在写入每个场景的话术"
                elif operation_type in {"verify_scene", "verify_draft_persisted", "save_draft"}:
                    stage, current, message = "verifying_readback", 4, "正在刷新麦兔并核对最终结果"
                else:
                    stage, current, message = "building_scenes", 2, "正在搭建场景并按顺序放置图层"
                if stage != last_reported_stage:
                    report_stage(stage, current, message)
                    last_reported_stage = stage

            result = ScriptLayoutDraftRunner(
                session=browser_session,
                checkpoint_store=checkpoint_store,
                progress_callback=report_operation_progress,
            ).run(operation_plan, target_live_room_id=target_live_room_id)
            heartbeat.ensure_active()
            checkpoint_result = checkpoint_store.finalize(result)
            checkpoint_finalized = True
            if result.status not in {"completed", "completed_with_manual_review"} or result.failure_count:
                raise RuntimeError(f"draft execution did not complete cleanly: {result.summary}")
            # Finalizing the inner checkpoint closes its lease. Whole-room readback is
            # still part of the active outer workbench job, so fence it with that lease.
            browser_session.set_execution_guard(heartbeat.ensure_active)
            verification: dict = {"matched": True, "verification_source": "checkpoint_readback"}
            layer_order_validation: dict = {"passed": True}
            final_readback: dict = {}
            worker_result = _worker_result_evidence(result)
            if source_kind == "functional_live_room_plan":
                report_stage("verifying_readback", 4, "正在刷新麦兔并逐层核对最终结果")
                expected_title = str(embedded.get("build_plan", {}).get("expected_title") or "")
                verification, layer_order_validation = verify_functional_draft(
                    browser_session,
                    operation_plan=operation_plan,
                    target_live_room_id=target_live_room_id,
                    expected_title=expected_title,
                )
                final_readback = browser_session.read_live_room(target_live_room_id)
                worker_result = {
                    **worker_result,
                    "runner_status": result.status,
                    "status": "completed",
                    "failure_count": 0,
                }
            browser_session.set_execution_guard(None)
            heartbeat.stop_for_writeback()
            completed = api.complete_workbench_draft_execution(
                job_code,
                {
                    "lease_token": lease_token,
                    "ready_for_go_live": False,
                    "result": _durable_execution_value({
                        "status": "completed" if source_kind == "functional_live_room_plan" else result.status,
                        "target_live_room_id": target_live_room_id,
                        "worker_result": worker_result,
                        "checkpoint_result": _checkpoint_completion_evidence(checkpoint_result),
                        "reset_evidence": reset_evidence,
                        "verification": verification,
                        "layer_order_validation": layer_order_validation,
                        "final_readback": _final_readback_evidence(final_readback),
                        "authority_mode": "worker_readback" if source_kind == "functional_live_room_plan" else "independent_backend",
                        "non_releasable": source_kind == "functional_live_room_plan",
                        "go_live_clicked": False,
                        "ready_for_go_live": False,
                    }),
                },
            )
        except Exception as exc:
            if browser_session is not None:
                browser_session.set_execution_guard(None)
            if checkpoint_store is not None and not checkpoint_finalized:
                try:
                    checkpoint_store.finalize(
                        ScriptLayoutDraftResult(
                            status="failed",
                            target_live_room_id=checkpoint_store.target_live_room_id,
                            ready_for_go_live=False,
                            manual_review_required=True,
                            summary="Workbench draft preparation failed before runner completion.",
                            operation_count=len(checkpoint_store.operation_checkpoints),
                            executed_action_count=0,
                            skipped_action_count=0,
                            placeholder_count=0,
                            failure_count=1,
                            actions=[],
                        )
                    )
                    checkpoint_finalized = True
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to close script-layout checkpoint after workbench failure"
                    )
            heartbeat.stop()
            _best_effort_fail_workbench_draft_job(
                api,
                job_code=job_code,
                lease_token=lease_token,
                error=exc,
                reconcile_required=(source_kind == "functional_live_room_plan" and destructive_started),
            )
            raise
        finally:
            if browser_session is not None:
                browser_session.set_execution_guard(None)
            heartbeat.stop()
        print(json.dumps(completed, ensure_ascii=False, indent=2, default=str))
        return 0

    resolved_operation_plan: dict | None = None
    material_resolution: MaituMaterialResolutionResult | None = None
    if args.resolve_maitu_materials and args.script_layout_draft_execute:
        raise SystemExit(
            "--resolve-maitu-materials and --script-layout-draft-execute must run as separate phases; "
            "persist verified bindings first, then start the fenced draft execution"
        )
    if args.resolve_maitu_materials:
        source_operation_plan = load_script_layout_operation_plan()
        _require_executable_script_layout_plan(source_operation_plan)
        if args.script_layout_draft_execute:
            _require_bound_draft_target(source_operation_plan, args.target_live_room_id)
        if args.dry_run:
            raise SystemExit("--resolve-maitu-materials cannot run with --dry-run because binding write-back/upload is a real action")
        material_resolution = MaituMaterialResolver(
            asset_client=assetgraph_client(),
            session=BrowserUseCliSession(),
            assets_root=args.assets_root,
        ).resolve_plan(source_operation_plan)
        resolved_operation_plan = material_resolution.operation_plan
        if args.resolved_plan_file:
            resolved_path = Path(args.resolved_plan_file)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(json.dumps(resolved_operation_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if (
            material_resolution.status != "resolved"
            or bool(material_resolution.issues)
            or material_resolution.manual_required_count > 0
        ):
            print(json.dumps(asdict(material_resolution), ensure_ascii=False, indent=2))
            return 2
        unresolved_material_operations = [
            operation
            for operation in (resolved_operation_plan.get("operations") or [])
            if isinstance(operation, dict)
            and operation.get("operation_type") == "insert_asset_layer"
            and (
                not str(operation.get("asset_code") or "").strip()
                or operation.get("material_resolution_status")
                not in {"reused_assetgraph_binding", "matched_existing_maitu_material", "uploaded_to_maitu"}
                or not MaituMaterialResolver.operation_has_executable_binding(operation)
            )
        ]
        if unresolved_material_operations:
            print(
                json.dumps(
                    {
                        "status": "blocked_invalid_material_resolution",
                        "manual_required_count": len(unresolved_material_operations),
                        "operation_plan": resolved_operation_plan,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        if not args.script_layout_draft_execute:
            print(json.dumps(asdict(material_resolution), ensure_ascii=False, indent=2))
            return 0
    if args.capture_jd_metrics:
        if not args.jd_metric_session_code:
            raise SystemExit("--capture-jd-metrics requires --jd-metric-session-code")
        if args.max_samples < 1:
            raise SystemExit("--max-samples must be >= 1")
        api_client = assetgraph_client()
        browser_session = BrowserUseCliSession()
        api_client.update_jd_live_metric_session(
            args.jd_metric_session_code,
            {"status": "running", "result_summary": "JD live metric capture running with foreground agent sync"},
        )
        capture_blocked = False
        capture_failed = False
        try:
            for sample_index in range(args.max_samples):
                result = capture_jd_live_metric_sample(
                    api_client,
                    args.jd_metric_session_code,
                    browser_session=browser_session,
                )
                raw_metrics = result.get("raw_metrics") if isinstance(result, dict) else None
                result_status = result.get("status") if isinstance(result, dict) else None
                if result_status == "blocked" or (
                    isinstance(raw_metrics, dict) and raw_metrics.get("ready_to_capture") is False
                ):
                    capture_blocked = True
                elif result_status != "captured":
                    capture_failed = True
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if sample_index < args.max_samples - 1 and args.capture_interval_seconds > 0:
                    time.sleep(args.capture_interval_seconds)
        except Exception as exc:
            failure = {"status": "failed", "result_summary": f"JD live metric capture failed: {exc}"}
            try:
                api_client.update_jd_live_metric_session(args.jd_metric_session_code, failure)
            except Exception:
                logging.getLogger(__name__).exception("Failed to persist JD metric session failure state")
            print(json.dumps(failure, ensure_ascii=False, indent=2))
            return 2
        if capture_failed:
            final_status = "failed"
            result_summary = f"JD metric capture failed closed for one or more of {args.max_samples} sample(s)"
        elif capture_blocked:
            final_status = "blocked"
            result_summary = f"JD metric capture blocked in one or more of {args.max_samples} sample(s)"
        else:
            final_status = "completed"
            result_summary = f"Captured {args.max_samples} JD live metric sample(s)"
        api_client.update_jd_live_metric_session(
            args.jd_metric_session_code,
            {"status": final_status, "result_summary": result_summary},
        )
        return 2 if capture_blocked or capture_failed else 0
    if args.script_layout_draft_execute:
        operation_plan = resolved_operation_plan or load_script_layout_operation_plan()
        checkpoint_store: AssetGraphScriptLayoutCheckpointStore | None = None
        if args.dry_run:
            target_live_room_id = args.target_live_room_id or operation_plan.get("target_live_room_id")
            session = InMemoryScriptLayoutDraftSession(live_room_id=str(target_live_room_id or "DRY-RUN-ROOM"))
        else:
            target_live_room_id = _require_bound_draft_target(operation_plan, args.target_live_room_id)
            session = BrowserUseCliSession()
            if not is_trusted_browser_use_cli_session(session):
                raise SystemExit("real script-layout execution requires the sealed Browser-use CLI session")
            checkpoint_store = AssetGraphScriptLayoutCheckpointStore.start(
                client=assetgraph_client(),
                operation_plan=operation_plan,
                target_live_room_id=target_live_room_id,
            )
            session.set_execution_guard(checkpoint_store.ensure_lease_active)
        result = ScriptLayoutDraftRunner(session=session, checkpoint_store=checkpoint_store).run(
            operation_plan,
            target_live_room_id=str(target_live_room_id) if target_live_room_id is not None else None,
        )
        if checkpoint_store is not None:
            execution_result = checkpoint_store.finalize(result)
            print(
                json.dumps(
                    {"worker_result": asdict(result), "execution_result": execution_result},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        unattended_success = (
            result.status == "completed"
            and result.failure_count == 0
            and not result.manual_review_required
            and all(action.status == "completed" for action in result.actions)
        )
        return 0 if unattended_success else 2
    if args.live_scene_fill:
        if not args.build_plan_code:
            raise SystemExit("--live-scene-fill requires --build-plan-code")
        if not args.target_live_room_id:
            raise SystemExit("--live-scene-fill requires --target-live-room-id")
        api_client = assetgraph_client()
        operation_plan = api_client.get_live_room_build_plan_operation_plan(args.build_plan_code)
        _require_bound_live_scene_target(operation_plan, args.target_live_room_id)
        result = LiveSceneFillRunner(session=BrowserUseCliSession()).run(
            operation_plan,
            target_live_room_id=args.target_live_room_id,
        )
        payload = build_live_scene_fill_execution_payload(result)
        execution_result = api_client.write_live_room_build_plan_execution_result(args.build_plan_code, payload)
        print(json.dumps({"worker_result": asdict(result), "execution_result": execution_result}, ensure_ascii=False, indent=2))
        unattended_success = (
            result.status == "completed"
            and result.failure_count == 0
            and all(action.status == "completed" for action in result.actions)
        )
        return 0 if unattended_success else 2
    if args.build_plan_code and args.dry_run:
        operation_plan = assetgraph_client().get_live_room_build_plan_operation_plan(args.build_plan_code)
        dry_run = BuildPlanDryRun().run(operation_plan)
        print(json.dumps(asdict(dry_run), ensure_ascii=False, indent=2))
        clean_simulation = dry_run.safety_violation_count == 0 and dry_run.manual_review_count == 0
        return 0 if clean_simulation else 2
    if args.non_destructive_build:
        if not args.build_plan_code:
            raise SystemExit("--non-destructive-build requires --build-plan-code")
        if args.skip_browser_probe:
            raise SystemExit("--non-destructive-build cannot use --skip-browser-probe; it requires a real green preflight")
        api_client = assetgraph_client()
        operation_plan = api_client.get_live_room_build_plan_operation_plan(args.build_plan_code)
        session = BrowserUseCliSession()
        preflight = BuildPlanPreflight(session=session).run(operation_plan)
        result = BuildPlanNonDestructiveRunner(session=session).run(operation_plan, preflight)
        if args.write_result:
            execution_result = api_client.write_live_room_build_plan_execution_result(
                args.build_plan_code,
                build_non_destructive_execution_payload(result),
            )
            print(json.dumps({"worker_result": asdict(result), "execution_result": execution_result}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        unattended_success = (
            result.status == "completed"
            and result.failure_count == 0
            and result.blocked_mutation_count == 0
            and all(action.status == "executed" for action in result.actions)
        )
        return 0 if unattended_success else 2
    if args.preflight_build:
        if not args.build_plan_code:
            raise SystemExit("--preflight-build requires --build-plan-code")
        operation_plan = assetgraph_client().get_live_room_build_plan_operation_plan(args.build_plan_code)
        preflight = BuildPlanPreflight(
            session=None if args.skip_browser_probe else BrowserUseCliSession(),
            probe_browser=not args.skip_browser_probe,
        ).run(operation_plan)
        print(json.dumps(asdict(preflight), ensure_ascii=False, indent=2))
        return 0 if preflight.ready_to_execute else 2
    if args.preflight:
        if not args.plan_code:
            raise SystemExit("--preflight requires --plan-code")
        api_client = assetgraph_client()
        operation_plan = api_client.get_replacement_plan_operation_plan(args.plan_code)
        preflight = ReplacementPlanPreflight(
            asset_client=api_client,
            assets_root=args.assets_root,
            session=None if args.skip_browser_probe else BrowserUseCliSession(),
            probe_browser=not args.skip_browser_probe,
        ).run(operation_plan)
        print(json.dumps(asdict(preflight), ensure_ascii=False, indent=2))
        return 0 if preflight.ready_to_execute else 2

    executor = DryRunBrowserUseExecutor()
    if not config.dry_run:
        raise SystemExit(
            "Real browser-use executor is not wired yet. Run with --dry-run or implement BrowserUseExecutor binding."
        )
    worker = BrowserUseWorker(
        config=config,
        client=assetgraph_client(),
        executor=executor,
    )
    if args.plan_code:
        result = worker.run_plan_once(args.plan_code)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0 if result.status in {"released", "succeeded"} else 2
    if args.once:
        worker.run_once()
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

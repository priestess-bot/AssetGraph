from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .browser_cli_session import BrowserUseCliSession, is_trusted_browser_use_cli_session
from .build_plan_dry_run import BuildPlanDryRun
from .build_plan_non_destructive import BuildPlanNonDestructiveRunner, build_non_destructive_execution_payload
from .build_plan_preflight import BuildPlanPreflight
from .client import AssetGraphClient
from .config import WorkerConfig
from .jd_metrics import capture_jd_live_metric_sample
from .live_scene_fill import LiveSceneFillRunner, build_live_scene_fill_execution_payload
from .maitu_material_resolver import MaituMaterialResolutionResult, MaituMaterialResolver
from .preflight import ReplacementPlanPreflight
from .runner import BrowserUseWorker, DryRunBrowserUseExecutor
from .script_layout_checkpoint import AssetGraphScriptLayoutCheckpointStore
from .script_layout_draft_executor import (
    InMemoryScriptLayoutDraftSession,
    ScriptLayoutDraftRunner,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AssetGraph browser-use worker.")
    parser.add_argument("--once", action="store_true", help="Run a single claim/execute/write-back cycle")
    parser.add_argument("--dry-run", action="store_true", help="Validate operation plans but do not operate Maitu")
    parser.add_argument("--probe-maitu", action="store_true", help="Run a read-only browser-use probe of the current Maitu page")
    parser.add_argument("--observe-maitu", action="store_true", help="Read structured current Maitu live-room state for the Observe step")
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
    parser.add_argument("--write-result", action="store_true", help="Write direct-plan execution/evidence result back to AssetGraph")
    parser.add_argument("--capture-jd-metrics", action="store_true", help="Capture JD live dashboard metrics and write samples to AssetGraph")
    parser.add_argument("--jd-metric-session-code", help="JD live metric capture session code (JD-METRIC-*)")
    parser.add_argument("--max-samples", type=int, default=1, help="Maximum JD dashboard metric samples to capture in this run")
    parser.add_argument("--capture-interval-seconds", type=float, default=0, help="Sleep interval between JD metric samples")
    parser.add_argument("--skip-browser-probe", action="store_true", help="Skip Browser-use/Maitu page probing during --preflight")
    parser.add_argument("--assets-root", default="D:/AssetGraph/素材", help="Local asset root used by --preflight file checks")
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
            ("capture_jd_metrics", args.capture_jd_metrics),
            ("script_layout", args.resolve_maitu_materials or args.script_layout_draft_execute),
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

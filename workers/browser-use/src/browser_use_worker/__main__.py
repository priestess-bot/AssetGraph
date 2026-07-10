from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import asdict

from .browser_cli_session import BrowserUseCliSession
from .build_plan_dry_run import BuildPlanDryRun
from .build_plan_non_destructive import BuildPlanNonDestructiveRunner, build_non_destructive_execution_payload
from .build_plan_preflight import BuildPlanPreflight
from .client import AssetGraphClient
from .config import WorkerConfig
from .jd_metrics import capture_jd_live_metric_sample
from .preflight import ReplacementPlanPreflight
from .runner import BrowserUseWorker, DryRunBrowserUseExecutor


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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = WorkerConfig.from_env(dry_run=args.dry_run)
    if args.check_config:
        print(json.dumps(asdict(config), ensure_ascii=False, indent=2))
        return 0
    if args.probe_maitu:
        probe = BrowserUseCliSession().probe_current_page(open_if_needed=True)
        print(json.dumps(asdict(probe), ensure_ascii=True, indent=2))
        return 0
    if args.observe_maitu:
        state = BrowserUseCliSession().read_current_state(open_if_needed=True)
        print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
        return 0

    client = AssetGraphClient(config.api_base_url)
    if args.capture_jd_metrics:
        if not args.jd_metric_session_code:
            raise SystemExit("--capture-jd-metrics requires --jd-metric-session-code")
        if args.max_samples < 1:
            raise SystemExit("--max-samples must be >= 1")
        browser_session = BrowserUseCliSession()
        client.update_jd_live_metric_session(
            args.jd_metric_session_code,
            {"status": "running", "result_summary": "JD live metric capture running with foreground agent sync"},
        )
        for sample_index in range(args.max_samples):
            result = capture_jd_live_metric_sample(
                client,
                args.jd_metric_session_code,
                browser_session=browser_session,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if sample_index < args.max_samples - 1 and args.capture_interval_seconds > 0:
                time.sleep(args.capture_interval_seconds)
        client.update_jd_live_metric_session(
            args.jd_metric_session_code,
            {"status": "completed", "result_summary": f"Captured {args.max_samples} JD live metric sample(s)"},
        )
        return 0
    if args.build_plan_code and args.dry_run:
        operation_plan = client.get_live_room_build_plan_operation_plan(args.build_plan_code)
        dry_run = BuildPlanDryRun().run(operation_plan)
        print(json.dumps(asdict(dry_run), ensure_ascii=False, indent=2))
        return 0 if dry_run.safety_violation_count == 0 else 2
    if args.non_destructive_build:
        if not args.build_plan_code:
            raise SystemExit("--non-destructive-build requires --build-plan-code")
        if args.skip_browser_probe:
            raise SystemExit("--non-destructive-build cannot use --skip-browser-probe; it requires a real green preflight")
        operation_plan = client.get_live_room_build_plan_operation_plan(args.build_plan_code)
        session = BrowserUseCliSession()
        preflight = BuildPlanPreflight(session=session).run(operation_plan)
        result = BuildPlanNonDestructiveRunner(session=session).run(operation_plan, preflight)
        if args.write_result:
            execution_result = client.write_live_room_build_plan_execution_result(
                args.build_plan_code,
                build_non_destructive_execution_payload(result),
            )
            print(json.dumps({"worker_result": asdict(result), "execution_result": execution_result}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0 if result.failure_count == 0 else 2
    if args.preflight_build:
        if not args.build_plan_code:
            raise SystemExit("--preflight-build requires --build-plan-code")
        operation_plan = client.get_live_room_build_plan_operation_plan(args.build_plan_code)
        preflight = BuildPlanPreflight(
            session=None if args.skip_browser_probe else BrowserUseCliSession(),
            probe_browser=not args.skip_browser_probe,
        ).run(operation_plan)
        print(json.dumps(asdict(preflight), ensure_ascii=False, indent=2))
        return 0 if preflight.failure_count == 0 else 2
    if args.preflight:
        if not args.plan_code:
            raise SystemExit("--preflight requires --plan-code")
        operation_plan = client.get_replacement_plan_operation_plan(args.plan_code)
        preflight = ReplacementPlanPreflight(
            asset_client=client,
            assets_root=args.assets_root,
            session=None if args.skip_browser_probe else BrowserUseCliSession(),
            probe_browser=not args.skip_browser_probe,
        ).run(operation_plan)
        print(json.dumps(asdict(preflight), ensure_ascii=False, indent=2))
        return 0 if preflight.failure_count == 0 else 2

    executor = DryRunBrowserUseExecutor()
    if not config.dry_run:
        raise SystemExit(
            "Real browser-use executor is not wired yet. Run with --dry-run or implement BrowserUseExecutor binding."
        )
    worker = BrowserUseWorker(
        config=config,
        client=client,
        executor=executor,
    )
    if args.plan_code:
        result = worker.run_plan_once(args.plan_code)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif args.once:
        worker.run_once()
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

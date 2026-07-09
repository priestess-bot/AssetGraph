from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict

from .browser_cli_session import BrowserUseCliSession
from .client import AssetGraphClient
from .config import WorkerConfig
from .preflight import ReplacementPlanPreflight
from .runner import BrowserUseWorker, DryRunBrowserUseExecutor


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AssetGraph browser-use worker.")
    parser.add_argument("--once", action="store_true", help="Run a single claim/execute/write-back cycle")
    parser.add_argument("--dry-run", action="store_true", help="Validate operation plans but do not operate Maitu")
    parser.add_argument("--probe-maitu", action="store_true", help="Run a read-only browser-use probe of the current Maitu page")
    parser.add_argument("--plan-code", help="Fetch a replacement plan operation plan and execute/dry-run it once")
    parser.add_argument("--preflight", action="store_true", help="Run read-only safety checks for --plan-code before mutating Maitu")
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

    client = AssetGraphClient(config.api_base_url)
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

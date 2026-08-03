#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = REPO_ROOT / "workers" / "browser-use"
WORKER_SRC = WORKER_ROOT / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from browser_use_worker.browser_cli_session import BrowserUseCliSession  # noqa: E402
from browser_use_worker.client import AssetGraphClient, AssetGraphClientError  # noqa: E402
from browser_use_worker.config import WorkerConfig  # noqa: E402
from browser_use_worker.maitu_executor import MaituBrowserExecutionError  # noqa: E402
from browser_use_worker.maitu_interaction_sync import MaituInteractionCollector  # noqa: E402


LOGGER = logging.getLogger("maitu-interaction-sync")


class LeaseHeartbeat:
    def __init__(
        self,
        *,
        client: AssetGraphClient,
        run_code: str,
        lease_token: str,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        self.client = client
        self.run_code = run_code
        self.lease_token = lease_token
        self.lease_seconds = lease_seconds
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.failure: Exception | None = None
        self.thread = threading.Thread(target=self._run, name="interaction-sync-heartbeat", daemon=True)

    def __enter__(self) -> "LeaseHeartbeat":
        self.thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(1.0, self.interval_seconds + 1.0))

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                self.client.heartbeat_maitu_interaction_sync(
                    self.run_code,
                    {
                        "lease_token": self.lease_token,
                        "lease_seconds": self.lease_seconds,
                    },
                )
            except Exception as exc:
                self.failure = exc
                self.stop_event.set()
                return

    def ensure_active(self) -> None:
        if self.failure is not None:
            raise RuntimeError("Maitu interaction sync lease heartbeat failed") from self.failure


def _retry_kind(error: Exception) -> tuple[str, str]:
    message = str(error).lower()
    if "account_mismatch" in message or "differs from the bound account" in message:
        return "account", "MAITU_ACCOUNT_MISMATCH"
    if any(marker in message for marker in ("login", "token", "http 401", "http 403")):
        return "login", "MAITU_LOGIN_REQUIRED"
    if "interaction consistency mismatch" in message:
        return "network", "MAITU_INTERACTION_SOURCE_DRIFT"
    if isinstance(error, MaituBrowserExecutionError):
        return (
            ("network", "MAITU_INTERACTION_SYNC_TRANSIENT")
            if error.retryable
            else ("permanent", "MAITU_INTERACTION_SYNC_FAILED")
        )
    if isinstance(error, (AssetGraphClientError, TimeoutError, OSError)):
        return "network", "MAITU_INTERACTION_SYNC_TRANSIENT"
    return "permanent", "MAITU_INTERACTION_SYNC_FAILED"


def _run_claim(
    client: AssetGraphClient,
    claimed: dict[str, Any],
    *,
    lease_seconds: int,
    heartbeat_seconds: float,
) -> None:
    run_code = str(claimed["run_code"])
    lease_token = str(claimed["lease_token"])
    collector = MaituInteractionCollector(BrowserUseCliSession())
    with LeaseHeartbeat(
        client=client,
        run_code=run_code,
        lease_token=lease_token,
        lease_seconds=lease_seconds,
        interval_seconds=heartbeat_seconds,
    ) as heartbeat:
        catalog = collector.collect_catalog()
        heartbeat.ensure_active()
        accepted = client.write_maitu_interaction_catalog(
            run_code,
            {
                "lease_token": lease_token,
                "external_account_id": catalog.external_account_id,
                "account_name": catalog.account_name,
                "platforms": list(catalog.platforms),
                "sessions": list(catalog.sessions),
            },
        )
        targets = list(accepted.get("sessions_to_sync") or [])
        session_count = 0
        interaction_count = 0
        for live_session in targets:
            heartbeat.ensure_active()
            session_id = int(live_session["external_session_id"])
            for session_attempt in range(1, 4):
                final_result: dict[str, Any] | None = None
                for page in collector.iter_interaction_pages(live_session):
                    heartbeat.ensure_active()
                    result = client.write_maitu_interaction_batch(
                        run_code,
                        {
                            "lease_token": lease_token,
                            "external_session_id": session_id,
                            "source_total": page.source_total,
                            "final_page": page.final_page,
                            "items": list(page.items),
                        },
                    )
                    if page.final_page:
                        final_result = result
                if final_result is None:
                    raise RuntimeError("Maitu interaction collector returned no final pagination checkpoint")
                seen_count = int(final_result.get("seen_count") or 0)
                source_total = int(final_result.get("source_total") or 0)
                if seen_count == source_total:
                    interaction_count += seen_count
                    break
                LOGGER.warning(
                    "interaction source drift run=%s session=%d pass=%d seen=%d source_total=%d",
                    run_code,
                    session_id,
                    session_attempt,
                    seen_count,
                    source_total,
                )
            else:
                raise RuntimeError(
                    "Maitu interaction consistency mismatch after 3 passes "
                    f"for session {session_id}: seen={seen_count}, source_total={source_total}"
                )
            session_count += 1
        heartbeat.ensure_active()
        client.complete_maitu_interaction_sync(
            run_code,
            {
                "lease_token": lease_token,
                "partial": False,
                "summary": {
                    "catalog_session_count": len(catalog.sessions),
                    "synchronized_session_count": session_count,
                    "accepted_interaction_count": interaction_count,
                    "platform_count": len(catalog.platforms),
                },
            },
        )
    LOGGER.info(
        "completed interaction sync run=%s sessions=%d accepted_interactions=%d",
        run_code,
        session_count,
        interaction_count,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run scheduled Maitu interaction synchronization")
    parser.add_argument("--once", action="store_true", help="Claim at most one sync run and exit")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--lease-seconds", type=int, default=900)
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0)
    parser.add_argument(
        "--worker-id",
        default=f"maitu-interactions-{socket.gethostname()}-{os.getpid()}",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    args = build_parser().parse_args(argv)
    if args.poll_seconds < 1:
        raise SystemExit("--poll-seconds must be at least 1")
    if not 30 <= args.lease_seconds <= 3600:
        raise SystemExit("--lease-seconds must be between 30 and 3600")
    if args.heartbeat_seconds <= 0 or args.heartbeat_seconds > args.lease_seconds / 3:
        raise SystemExit("--heartbeat-seconds must be positive and no more than one third of the lease")
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = WorkerConfig.from_env()
    token = config.script_layout_worker_token
    client = AssetGraphClient(
        config.api_base_url,
        script_layout_worker_token=token,
        worker_id=args.worker_id,
    )
    if not token:
        raise SystemExit("ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN is required")

    # The API client retains the worker credential; browser-use children do not need it.
    for key in (
        "ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN",
        "MAITU_SCRIPT_LAYOUT_WORKER_TOKEN",
        "DEEPSEEK_API_KEY",
        "ASSETGRAPH_DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ASSETGRAPH_OPENAI_API_KEY",
    ):
        os.environ.pop(key, None)

    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stopping:
        try:
            claimed = client.claim_next_maitu_interaction_sync(
                {"lease_seconds": args.lease_seconds}
            )
        except Exception:
            LOGGER.exception("failed to poll for a Maitu interaction sync job")
            if args.once:
                return 1
            time.sleep(args.poll_seconds)
            continue
        if claimed is None:
            if args.once:
                return 0
            time.sleep(args.poll_seconds)
            continue
        run_code = str(claimed["run_code"])
        lease_token = str(claimed["lease_token"])
        try:
            _run_claim(
                client,
                claimed,
                lease_seconds=args.lease_seconds,
                heartbeat_seconds=args.heartbeat_seconds,
            )
        except Exception as exc:
            retry_kind, error_code = _retry_kind(exc)
            try:
                client.fail_maitu_interaction_sync(
                    run_code,
                    {
                        "lease_token": lease_token,
                        "error_code": error_code,
                        "error_message": f"{type(exc).__name__}: {exc}"[:4000],
                        "retry_kind": retry_kind,
                    },
                )
            except Exception:
                LOGGER.exception("failed to persist interaction sync failure for run=%s", run_code)
            LOGGER.exception("interaction sync failed run=%s", run_code)
        finally:
            BrowserUseCliSession.release_current_process_locks()
        if args.once:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

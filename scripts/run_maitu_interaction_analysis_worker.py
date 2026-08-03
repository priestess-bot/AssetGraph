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
from typing import Any, Callable

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from psycopg import connect  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.repositories.maitu_interactions import (  # noqa: E402
    MaituInteractionLeaseError,
    MaituInteractionsRepository,
)
from app.services.maitu_interactions import (  # noqa: E402
    INTERACTION_ANALYSIS_STRATEGY_REVISION,
    build_interaction_analyzer,
    interaction_analyzer_version,
)


LOGGER = logging.getLogger("maitu-interaction-analysis")


class AnalysisLeaseHeartbeat:
    def __init__(self, renew: Callable[[], bool], interval_seconds: float) -> None:
        self.renew = renew
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.failure: Exception | None = None
        self.thread = threading.Thread(target=self._run, name="interaction-analysis-heartbeat", daemon=True)

    def __enter__(self) -> "AnalysisLeaseHeartbeat":
        self.thread.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(1.0, self.interval_seconds + 1.0))

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                if not self.renew():
                    raise RuntimeError("Analysis lease is no longer active")
            except Exception as exc:
                self.failure = exc
                self.stop_event.set()
                return

    def ensure_active(self) -> None:
        if self.failure is not None:
            raise RuntimeError("Maitu interaction analysis lease heartbeat failed") from self.failure


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Maitu interaction classification and quality analysis")
    parser.add_argument("--once", action="store_true", help="Claim at most one analysis and exit")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--lease-seconds", type=int, default=600)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument(
        "--worker-id",
        default=f"interaction-analysis-{socket.gethostname()}-{os.getpid()}",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def _renew(job: dict[str, Any], worker_id: str, lease_seconds: int) -> bool:
    with connect(settings.postgres_dsn, connect_timeout=5) as connection:
        return MaituInteractionsRepository(connection).heartbeat_analysis_job(
            str(job["analysis_code"]),
            worker_id,
            str(job["lease_token"]),
            lease_seconds,
        )


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
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    analyzer_version = interaction_analyzer_version()

    with connect(settings.postgres_dsn) as connection:
        repository = MaituInteractionsRepository(connection)
        analyzer = build_interaction_analyzer(connection)
        warned_unconfigured = False
        while not stopping:
            repository.synchronize_analysis_jobs(
                analyzer_version,
                INTERACTION_ANALYSIS_STRATEGY_REVISION,
            )
            if analyzer is None:
                if not warned_unconfigured:
                    LOGGER.warning(
                        "interaction analysis is waiting for DeepSeek credentials, processing region, and active processor policy"
                    )
                    warned_unconfigured = True
                if args.once:
                    return 0
                time.sleep(args.poll_seconds)
                continue
            job = repository.claim_analysis_job(
                analyzer_version,
                args.worker_id,
                args.lease_seconds,
            )
            if job is None:
                if args.once:
                    return 0
                time.sleep(args.poll_seconds)
                continue
            try:
                interaction = job["interaction"]
                with AnalysisLeaseHeartbeat(
                    lambda: _renew(job, args.worker_id, args.lease_seconds),
                    args.heartbeat_seconds,
                ) as heartbeat:
                    result = analyzer.analyze(
                        content=str(interaction.get("content") or ""),
                        digital_reply_content=interaction.get("digital_reply_content"),
                    )
                    heartbeat.ensure_active()
                    repository.complete_analysis_job(
                        str(job["analysis_code"]),
                        args.worker_id,
                        str(job["lease_token"]),
                        result,
                    )
                LOGGER.info("completed interaction analysis code=%s", job["analysis_code"])
            except Exception as exc:
                connection.rollback()
                try:
                    repository.fail_analysis_job(
                        str(job["analysis_code"]),
                        args.worker_id,
                        str(job["lease_token"]),
                        error_code="INTERACTION_ANALYSIS_FAILED",
                        error_message=f"{type(exc).__name__}: {exc}"[:4000],
                    )
                except MaituInteractionLeaseError:
                    LOGGER.warning("analysis failure write-back was fenced code=%s", job["analysis_code"])
                LOGGER.exception("interaction analysis failed code=%s", job["analysis_code"])
            if args.once:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

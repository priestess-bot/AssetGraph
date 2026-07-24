#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from psycopg import connect  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.repositories.maitu_workbench import (  # noqa: E402
    MaituWorkbenchLeaseConflictError,
    MaituWorkbenchRepository,
)
from app.services.material_analysis import (  # noqa: E402
    MaterialAnalysisError,
    MaterialAnalysisJobProcessor,
    MaterialAnalysisLeaseHeartbeat,
    MaterialAnalysisWorkbenchService,
    MaterialVisionAnalyzer,
    RepresentativeFrameExtractor,
    build_material_analysis_router,
)
from app.services.online_models import OnlineModelError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run selected Maitu video material analysis jobs")
    parser.add_argument("--once", action="store_true", help="Claim at most one analysis and exit")
    parser.add_argument("--worker-id", default=f"material-analysis-{socket.gethostname()}-{os.getpid()}")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--lease-seconds", type=int, default=3600)
    parser.add_argument("--heartbeat-seconds", type=float, default=None)
    parser.add_argument("--assets-root", type=Path, default=REPO_ROOT / "素材")
    parser.add_argument("--analysis-root", type=Path, default=settings.material_analysis_root)
    return parser


def _build_processor(
    repository: MaituWorkbenchRepository,
    *,
    assets_root: Path,
    analysis_root: Path,
) -> MaterialAnalysisJobProcessor | None:
    router = build_material_analysis_router(repository.connection)
    if router is None:
        return None
    return MaterialAnalysisJobProcessor(
        workflow=MaterialAnalysisWorkbenchService(repository),
        analyzer=MaterialVisionAnalyzer(router),
        extractor=RepresentativeFrameExtractor(analysis_root / "representative-frames"),
        asset_materials_root=assets_root,
        maitu_mirror_root=settings.maitu_mirror_root,
    )


def _fail_claim(
    repository: MaituWorkbenchRepository,
    job: dict[str, object],
    worker_id: str,
    error_code: str,
    error: Exception,
) -> bool:
    try:
        repository.fail_video_analysis(
            str(job["analysis_code"]),
            worker_id,
            str(job["lease_token"]),
            error_code=error_code,
            error_message=str(error)[:4000] or type(error).__name__,
        )
    except MaituWorkbenchLeaseConflictError:
        return False
    return True


def _renew_claim(job: dict[str, object], worker_id: str, lease_seconds: int) -> bool:
    with connect(settings.postgres_dsn, connect_timeout=5) as heartbeat_connection:
        heartbeat_repository = MaituWorkbenchRepository(heartbeat_connection)
        return heartbeat_repository.heartbeat_video_analysis(
            str(job["analysis_code"]),
            worker_id,
            str(job["lease_token"]),
            lease_seconds,
        ) is not None


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    args = build_parser().parse_args(argv)
    if args.poll_seconds < 0.1:
        raise SystemExit("--poll-seconds must be at least 0.1")
    if not 30 <= args.lease_seconds <= 3600:
        raise SystemExit("--lease-seconds must be between 30 and 3600")
    heartbeat_seconds = args.heartbeat_seconds
    if heartbeat_seconds is None:
        heartbeat_seconds = max(5.0, min(60.0, args.lease_seconds / 3))
    if heartbeat_seconds <= 0 or heartbeat_seconds > args.lease_seconds / 3:
        raise SystemExit("--heartbeat-seconds must be positive and no more than one third of --lease-seconds")
    assets_root = args.assets_root.expanduser().resolve()
    if not assets_root.is_dir():
        raise SystemExit(f"materials root does not exist: {assets_root}")
    analysis_root = args.analysis_root.expanduser().resolve()
    analysis_root.mkdir(parents=True, exist_ok=True)
    os.chmod(analysis_root, 0o700)

    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    with connect(settings.postgres_dsn) as connection:
        repository = MaituWorkbenchRepository(connection)
        processor = _build_processor(
            repository,
            assets_root=assets_root,
            analysis_root=analysis_root,
        )
        while not stopping:
            repository.synchronize_all_selected_video_analyses()
            job = repository.claim_video_analysis(args.worker_id, args.lease_seconds)
            if job is None:
                if args.once:
                    return 0
                time.sleep(args.poll_seconds)
                continue
            try:
                if processor is None:
                    raise MaterialAnalysisError(
                        "Governed material-analysis strategy is not configured"
                    )
                with MaterialAnalysisLeaseHeartbeat(
                    renew=lambda: _renew_claim(job, args.worker_id, args.lease_seconds),
                    interval_seconds=heartbeat_seconds,
                ) as heartbeat:
                    processor.process(
                        job,
                        worker_id=args.worker_id,
                        lease_guard=heartbeat.raise_if_failed,
                    )
                print(f"completed {job['analysis_code']} asset={job['asset_code']}", flush=True)
            except OnlineModelError as exc:
                persisted = _fail_claim(repository, job, args.worker_id, "MODEL_STRATEGY_REQUEST_FAILED", exc)
                suffix = "" if persisted else " (lease lost; authoritative state was not overwritten)"
                print(f"failed {job['analysis_code']}: {exc}{suffix}", file=sys.stderr, flush=True)
            except MaterialAnalysisError as exc:
                error_code = "MODEL_STRATEGY_NOT_CONFIGURED" if processor is None else "MATERIAL_ANALYSIS_FAILED"
                persisted = _fail_claim(repository, job, args.worker_id, error_code, exc)
                suffix = "" if persisted else " (lease lost; authoritative state was not overwritten)"
                print(f"failed {job['analysis_code']}: {exc}{suffix}", file=sys.stderr, flush=True)
            except Exception as exc:
                persisted = _fail_claim(repository, job, args.worker_id, "MATERIAL_ANALYSIS_UNEXPECTED", exc)
                suffix = "" if persisted else " (lease lost; authoritative state was not overwritten)"
                print(f"failed {job['analysis_code']}: {exc}{suffix}", file=sys.stderr, flush=True)
            if args.once:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

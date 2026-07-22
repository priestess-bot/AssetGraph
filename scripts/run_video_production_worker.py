#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from psycopg import connect  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.repositories.assets import AssetRepository  # noqa: E402
from app.repositories.video_productions import VideoProductionRepository  # noqa: E402
from app.services.video_production_pipeline import (  # noqa: E402
    DatabaseFinalAssetRegistrar,
    VideoProductionPipeline,
    VideoProductionWorker,
)
from app.services.video_production_tts import KokoroTTSClient  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AssetGraph commercial-video production worker")
    parser.add_argument("--once", action="store_true", help="Claim at most one job and exit")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument(
        "--assets-root",
        type=Path,
        default=Path(os.environ.get("ASSETGRAPH_ASSETS_ROOT", REPO_ROOT / "素材")),
    )
    parser.add_argument("--output-root", type=Path, default=settings.video_production_root)
    parser.add_argument(
        "--tts-base-url",
        default=os.environ.get("ASSETGRAPH_TTS_BASE_URL", "http://127.0.0.1:8020"),
    )
    parser.add_argument("--poll-seconds", type=float, default=settings.video_production_worker_poll_seconds)
    parser.add_argument("--lease-seconds", type=int, default=settings.video_production_worker_lease_seconds)
    parser.add_argument("--heartbeat-seconds", type=int, default=settings.video_production_worker_heartbeat_seconds)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be positive")
    if args.heartbeat_seconds >= args.lease_seconds:
        raise SystemExit("--heartbeat-seconds must be less than --lease-seconds")
    assets_root = args.assets_root.expanduser().resolve()
    if not assets_root.is_dir():
        raise SystemExit(f"materials root does not exist: {assets_root}")
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    with connect(settings.postgres_dsn) as connection:
        repository = VideoProductionRepository(connection)
        pipeline = VideoProductionPipeline(
            assets_root=assets_root,
            output_root=output_root,
            tts=KokoroTTSClient(base_url=args.tts_base_url),
        )
        worker = VideoProductionWorker(
            repository=repository,
            pipeline=pipeline,
            final_asset_registrar=DatabaseFinalAssetRegistrar(AssetRepository(connection)),
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
        )
        while not stopping:
            processed = worker.run_once()
            if args.once:
                return 0
            if not processed:
                time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

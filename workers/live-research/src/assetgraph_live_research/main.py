from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from .api_client import LiveResearchAPIClient, LiveResearchAPIError
from .analysis import LiveMediaAnalysisExecutor
from .clipper import FFmpegClipper
from .events import DouyinLiveEventCollector
from .orchestrator import LiveCaptureOrchestrator
from .providers import (
    DeepSeekTemplateProvider,
    OpenAITranscriptionProvider,
    OpenAIVisionProvider,
    RoutedLayoutProvider,
)
from .retention import RetentionWorker
from .runtime import (
    ComposeSidecarRuntime,
    ExternalSidecarRuntime,
    LocalSidecarRuntime,
    LoopbackSidecarProbe,
)
from .scheduler import CaptureIngestionCoordinator, SingleChannelScheduler
from .sidecars import InstalledSidecars, REPO_ROOT, StreamCapTargetConfig
from .storage import RawEventBatchWriter, SecureStorage, initialize_private_config
from .streamcap import StreamCapChunkAdapter
from .worker import AnalysisRunWorker, ClipJobWorker


DEFAULT_ROOT = Path(
    os.environ.get(
        "ASSETGRAPH_LIVE_RESEARCH_ROOT",
        "/DATA/Downloads/AssetGraph/live-research",
    )
)
LOGGER = logging.getLogger(__name__)
API_RETRY_INITIAL_SECONDS = 1.0
API_RETRY_MAX_SECONDS = 30.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AssetGraph Douyin live-research worker")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get(
            "ASSETGRAPH_LIVE_RESEARCH_API_URL",
            "http://127.0.0.1:8000/api/live-research",
        ),
    )
    parser.add_argument(
        "--worker-token",
        default=os.environ.get("ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN", ""),
    )
    parser.add_argument(
        "--worker-id",
        default=os.environ.get(
            "ASSETGRAPH_LIVE_RESEARCH_WORKER_ID",
            f"live-research-{socket.gethostname()}-{os.getpid()}",
        ),
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("verify-sidecars")
    init = subparsers.add_parser("init-config")
    init.add_argument(
        "--destination",
        type=Path,
        default=REPO_ROOT / "workers/live-research/runtime/douyinlive-config.yaml",
    )
    init.add_argument(
        "--recordings-config",
        type=Path,
        default=REPO_ROOT / "workers/live-research/runtime/streamcap/recordings.json",
    )

    scheduler = subparsers.add_parser("scheduler")
    scheduler.add_argument("--once", action="store_true")
    scheduler.add_argument("--lease-seconds", type=int, default=120)
    scheduler.add_argument(
        "--sidecars", choices=("local", "external", "compose"), default="local"
    )
    scheduler.add_argument(
        "--recordings-config",
        type=Path,
        default=None,
    )
    scheduler.add_argument("--staging-root", type=Path, default=None)
    scheduler.add_argument("--streamcap-url", default="http://127.0.0.1:6006")
    scheduler.add_argument(
        "--douyinlive-websocket-url",
        default=os.environ.get("ASSETGRAPH_DOUYINLIVE_WS_URL", "ws://127.0.0.1:1088"),
    )
    scheduler.add_argument(
        "--douyinlive-config",
        type=Path,
        default=REPO_ROOT / "workers/live-research/runtime/douyinlive-config.yaml",
    )
    scheduler.add_argument(
        "--compose-file",
        type=Path,
        default=REPO_ROOT / "workers/live-research/compose.sidecars.yml",
    )
    scheduler.add_argument("--poll-seconds", type=float, default=2)
    scheduler.add_argument("--settle-seconds", type=float, default=10)
    scheduler.add_argument("--offline-grace-seconds", type=float, default=120)
    scheduler.add_argument("--target-wait-seconds", type=float, default=180)

    retention = subparsers.add_parser("retention")
    retention.add_argument("--once", action="store_true")
    retention.add_argument("--poll-seconds", type=float, default=300)
    retention.add_argument("--batch-limit", type=int, default=100)
    retention.add_argument("--lease-seconds", type=int, default=300)

    clip = subparsers.add_parser("clip-worker")
    clip.add_argument("--once", action="store_true")
    clip.add_argument("--poll-seconds", type=float, default=2)
    clip.add_argument("--lease-seconds", type=int, default=1800)

    analysis = subparsers.add_parser("analysis-worker")
    analysis.add_argument("--once", action="store_true")
    analysis.add_argument("--poll-seconds", type=float, default=2)
    analysis.add_argument("--lease-seconds", type=int, default=1800)

    retry_analysis = subparsers.add_parser("retry-analysis")
    retry_analysis.add_argument("--run-code", required=True)
    retry_analysis.add_argument("--reason", required=True)

    events = subparsers.add_parser("events")
    events.add_argument("--session-code", required=True)
    events.add_argument("--room-id", required=True)
    events.add_argument(
        "--websocket-url",
        default=os.environ.get("ASSETGRAPH_DOUYINLIVE_WS_URL", "ws://127.0.0.1:1088"),
    )
    events.add_argument("--batch-size", type=int, default=500)
    events.add_argument("--flush-seconds", type=float, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-sidecars":
        verified = InstalledSidecars().verify()
        print(
            f"StreamCap {verified['streamcap_version']} {verified['streamcap_commit']}; "
            f"douyinLive {verified['douyinlive_version']} {verified['douyinlive_commit']}"
        )
        return 0
    if args.command == "init-config":
        example = REPO_ROOT / "workers/live-research/config/douyinlive/config.example.yaml"
        initialize_private_config(example, args.destination)
        recordings_example = (
            REPO_ROOT / "workers/live-research/config/streamcap/recordings.json"
        )
        initialize_private_config(recordings_example, args.recordings_config)
        print(f"{args.destination.resolve()}\n{args.recordings_config.resolve()}")
        return 0
    if not args.worker_token:
        raise SystemExit("ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN/--worker-token is required")

    storage = SecureStorage(args.root)
    api = LiveResearchAPIClient(
        args.api_base_url,
        worker_token=args.worker_token,
        worker_id=args.worker_id,
    )
    try:
        if args.command == "scheduler":
            return asyncio.run(_run_scheduler(args, api, storage))
        if args.command == "retention":
            worker = RetentionWorker(
                api,
                storage,
                args.worker_id,
                args.lease_seconds,
                args.batch_limit,
            )
            return _run_polling(worker.run_once, args.once, args.poll_seconds)
        if args.command == "clip-worker":
            worker = ClipJobWorker(
                api,
                FFmpegClipper(storage),
                args.worker_id,
                args.lease_seconds,
            )
            return _run_polling(worker.run_once, args.once, args.poll_seconds)
        if args.command == "analysis-worker":
            worker = _analysis_worker(args, api, storage)
            return _run_polling(worker.run_once, args.once, args.poll_seconds)
        if args.command == "retry-analysis":
            run = api.retry_analysis_run(
                args.run_code,
                worker_id=args.worker_id,
                reason=args.reason,
            )
            print(f"{run['analysis_run_code']} {run['status']}")
            return 0
        if args.command == "events":
            return asyncio.run(_run_events(args, api, storage))
        raise SystemExit(f"unsupported command: {args.command}")
    finally:
        api.close()


async def _run_scheduler(
    args: argparse.Namespace,
    api: LiveResearchAPIClient,
    storage: SecureStorage,
) -> int:
    installed = InstalledSidecars()
    recordings_config = args.recordings_config or _default_recordings_config(args.sidecars)
    scheduler = SingleChannelScheduler(
        api=api,
        target_config=StreamCapTargetConfig(recordings_config),
        sidecars=installed,
        worker_id=args.worker_id,
        lease_seconds=args.lease_seconds,
    )
    probe = LoopbackSidecarProbe(
        streamcap_url=args.streamcap_url,
        douyinlive_websocket_url=args.douyinlive_websocket_url,
    )
    runtime = _sidecar_runtime(
        args,
        installed=installed,
        probe=probe,
        recordings_config=recordings_config,
    )
    staging_root = (args.staging_root or args.root / "staging").expanduser().resolve()
    chunk_adapter = StreamCapChunkAdapter(
        streamcap_root=staging_root,
        storage=storage,
        settle_seconds=args.settle_seconds,
    )
    coordinator = CaptureIngestionCoordinator(api=api, chunk_adapter=chunk_adapter)
    collector = DouyinLiveEventCollector(
        websocket_base_url=args.douyinlive_websocket_url,
        batch_writer=RawEventBatchWriter(storage),
    )
    orchestrator = LiveCaptureOrchestrator(
        scheduler=scheduler,
        runtime=runtime,
        coordinator=coordinator,
        event_collector=collector,
        chunk_adapter=chunk_adapter,
        poll_seconds=args.poll_seconds,
        offline_grace_seconds=args.offline_grace_seconds,
        target_wait_seconds=args.target_wait_seconds,
    )
    stopping = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return await _run_scheduler_loop(
        orchestrator,
        coordinator,
        once=args.once,
        stopping=stopping,
    )


async def _run_scheduler_loop(
    orchestrator: LiveCaptureOrchestrator,
    coordinator: CaptureIngestionCoordinator,
    *,
    once: bool,
    stopping: threading.Event,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    retry_seconds = API_RETRY_INITIAL_SECONDS
    while not stopping.is_set():
        try:
            await orchestrator.run_cycle(stop_requested=stopping.is_set)
        except LiveResearchAPIError as exc:
            coordinator.abandon_local_session()
            if once:
                raise
            LOGGER.warning(
                "AssetGraph API unavailable to scheduler; retrying in %.1f seconds: %s",
                retry_seconds,
                exc,
            )
            await sleep(retry_seconds)
            retry_seconds = min(retry_seconds * 2, API_RETRY_MAX_SECONDS)
            continue
        retry_seconds = API_RETRY_INITIAL_SECONDS
        if once or stopping.is_set():
            break
        await sleep(1)
    return 0


def _default_recordings_config(sidecars: str) -> Path:
    configured = os.environ.get("ASSETGRAPH_STREAMCAP_RECORDINGS_CONFIG")
    if configured:
        return Path(configured)
    if sidecars == "compose":
        return REPO_ROOT / "workers/live-research/runtime/streamcap/recordings.json"
    return REPO_ROOT / ".external/StreamCap/config/recordings.json"


def _sidecar_runtime(
    args: argparse.Namespace,
    *,
    installed: InstalledSidecars,
    probe: LoopbackSidecarProbe,
    recordings_config: Path,
) -> LocalSidecarRuntime | ExternalSidecarRuntime | ComposeSidecarRuntime:
    if args.sidecars == "external":
        return ExternalSidecarRuntime(probe)
    if args.sidecars == "compose":
        return ComposeSidecarRuntime(
            compose_file=args.compose_file,
            probe=probe,
            storage_root=args.root,
            recordings_config=recordings_config,
            douyinlive_config=args.douyinlive_config,
        )
    return LocalSidecarRuntime(
        installed=installed,
        probe=probe,
        storage_root=args.root,
        recordings_config=recordings_config,
        settings_template=(
            REPO_ROOT / "workers/live-research/config/streamcap/default_settings.json"
        ),
        douyinlive_config=args.douyinlive_config,
    )


def _analysis_worker(
    args: argparse.Namespace,
    api: LiveResearchAPIClient,
    storage: SecureStorage,
) -> AnalysisRunWorker:
    openai_key = os.environ.get("OPENAI_API_KEY") or os.environ.get(
        "ASSETGRAPH_OPENAI_API_KEY", ""
    )
    openai_base_url = os.environ.get(
        "OPENAI_BASE_URL",
        os.environ.get("ASSETGRAPH_OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get(
        "ASSETGRAPH_DEEPSEEK_API_KEY", ""
    )
    deepseek_base_url = os.environ.get(
        "DEEPSEEK_BASE_URL",
        os.environ.get("ASSETGRAPH_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    transcription = (
        OpenAITranscriptionProvider(api_key=openai_key, base_url=openai_base_url)
        if openai_key
        else None
    )
    vision = (
        OpenAIVisionProvider(
            api_key=openai_key,
            base_url=openai_base_url,
            storage=storage,
        )
        if openai_key
        else None
    )
    aggregation = (
        DeepSeekTemplateProvider(api_key=deepseek_key, base_url=deepseek_base_url)
        if deepseek_key
        else None
    )
    executor = LiveMediaAnalysisExecutor(
        storage=storage,
        asr_provider=transcription,
        layout_provider=RoutedLayoutProvider(vision=vision, aggregation=aggregation),
    )
    return AnalysisRunWorker(api, executor, args.worker_id, args.lease_seconds)


async def _run_events(
    args: argparse.Namespace,
    api: LiveResearchAPIClient,
    storage: SecureStorage,
) -> int:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)
    collector = DouyinLiveEventCollector(
        websocket_base_url=args.websocket_url,
        batch_writer=RawEventBatchWriter(storage),
        batch_size=args.batch_size,
        flush_seconds=args.flush_seconds,
    )

    async def register(metadata: dict[str, object]) -> None:
        await asyncio.to_thread(api.register_event_batch, args.session_code, metadata)

    await collector.collect(
        room_id=args.room_id,
        session_code=args.session_code,
        register_batch=register,
        stop_event=stop_event,
    )
    return 0


def _run_polling(run_once: Callable[[], object], once: bool, poll_seconds: float) -> int:
    if poll_seconds <= 0:
        raise SystemExit("poll interval must be positive")
    retry_seconds = API_RETRY_INITIAL_SECONDS
    while True:
        try:
            processed = bool(run_once())
        except LiveResearchAPIError as exc:
            if once:
                raise
            LOGGER.warning(
                "AssetGraph API unavailable to polling worker; retrying in %.1f seconds: %s",
                retry_seconds,
                exc,
            )
            time.sleep(retry_seconds)
            retry_seconds = min(retry_seconds * 2, API_RETRY_MAX_SECONDS)
            continue
        retry_seconds = API_RETRY_INITIAL_SECONDS
        if once:
            return 0
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from assetgraph_live_research.orchestrator import LiveCaptureOrchestrator
from assetgraph_live_research.scheduler import ActiveWatchLease


class _Scheduler:
    def __init__(self):
        self.releases: list[dict[str, Any]] = []

    def claim(self) -> ActiveWatchLease:
        return ActiveWatchLease(
            {
                "target_code": "target_1",
                "canonical_room_id": "123456",
                "room_url": "https://live.douyin.com/123456",
                "claim_token": "11111111-1111-1111-1111-111111111111",
                "lease_version": 1,
                "poll_interval_seconds": 180,
            },
            "worker-1",
            30,
        )

    def heartbeat(self, lease: ActiveWatchLease) -> None:
        del lease

    def release(self, lease: ActiveWatchLease, **payload: Any) -> None:
        self.releases.append({"target_code": lease.target_code, **payload})


class _Runtime:
    def __init__(self, source: Path):
        self.source = source
        self.closed = False
        self.started = False

    def ensure_running(self) -> None:
        self.started = True
        self.source.write_bytes(b"TS")

    def close(self) -> None:
        self.closed = True


class _Adapter:
    settle_seconds = 0.0

    def __init__(self, root: Path, source: Path):
        self.streamcap_root = root
        self.source = source

    def scan_ready(self) -> list[Path]:
        return [self.source.resolve()] if self.source.exists() else []

    def probe(self, path: Path) -> dict[str, Any]:
        assert path == self.source.resolve()
        return {"format": {"duration": "0.01"}}

    def quarantine_orphan(self, source: Path, *, target_code: str) -> dict[str, Any]:
        assert target_code == "target_1"
        source.unlink()
        return {
            "original_relative_path": source.name,
            "quarantine_relative_path": f"quarantine/{source.name}",
            "checksum_sha256": "a" * 64,
        }


class _API:
    def __init__(self):
        self.batches: list[dict[str, Any]] = []

    def register_event_batch(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.batches.append({"session_code": session_code, **payload})
        return payload


class _Coordinator:
    def __init__(self, source: Path):
        self.api = _API()
        self.source = source
        self.session: dict[str, Any] | None = None
        self.timeline = SimpleNamespace(spans=[])
        self.finished: list[str] = []

    def begin(self, lease: ActiveWatchLease, **payload: Any) -> dict[str, Any]:
        del lease, payload
        self.session = {"session_code": "capture_1"}
        return self.session

    def ingest_chunk(self, **payload: Any) -> dict[str, Any]:
        payload["source"].unlink()
        self.timeline.spans.append({"span_index": payload["part_index"]})
        return {"chunk": {"chunk_code": "chunk_1"}}

    def finish(self, *, status: str, **payload: Any) -> dict[str, Any]:
        del payload
        self.finished.append(status)
        result = dict(self.session or {})
        self.session = None
        return result


class _Collector:
    async def collect(self, **payload: Any) -> int:
        await payload["event_callback"](
            {
                "payload": {
                    "type": "system",
                    "event": "live_status",
                    "live": True,
                }
            }
        )
        await payload["stop_event"].wait()
        await payload["register_batch"]({"batch_index": 0})
        return 1


def test_orchestrator_runs_media_event_timeline_and_finish_cycle(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "part_000.TS"
    scheduler = _Scheduler()
    runtime = _Runtime(source)
    adapter = _Adapter(staging, source)
    coordinator = _Coordinator(source)
    orchestrator = LiveCaptureOrchestrator(
        scheduler=scheduler,  # type: ignore[arg-type]
        runtime=runtime,
        coordinator=coordinator,  # type: ignore[arg-type]
        event_collector=_Collector(),  # type: ignore[arg-type]
        chunk_adapter=adapter,  # type: ignore[arg-type]
        poll_seconds=0.001,
        offline_grace_seconds=0.005,
        target_wait_seconds=1,
    )

    result = asyncio.run(orchestrator.run_cycle())

    assert result.outcome == "captured"
    assert result.session_code == "capture_1"
    assert result.chunk_count == 1
    assert coordinator.finished == ["completed"]
    assert coordinator.api.batches == [
        {"session_code": "capture_1", "batch_index": 0}
    ]
    assert scheduler.releases == [{"target_code": "target_1", "outcome": "captured"}]
    assert runtime.closed is True


def test_orchestrator_quarantines_preexisting_staging_before_new_target(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "old-room.TS"
    source.write_bytes(b"old-room")
    scheduler = _Scheduler()
    runtime = _Runtime(source)
    adapter = _Adapter(staging, source)
    coordinator = _Coordinator(source)
    orchestrator = LiveCaptureOrchestrator(
        scheduler=scheduler,  # type: ignore[arg-type]
        runtime=runtime,
        coordinator=coordinator,  # type: ignore[arg-type]
        event_collector=_Collector(),  # type: ignore[arg-type]
        chunk_adapter=adapter,  # type: ignore[arg-type]
        poll_seconds=0.001,
        offline_grace_seconds=0.005,
        target_wait_seconds=1,
    )

    result = asyncio.run(orchestrator.run_cycle())

    assert result.outcome == "orphan_quarantined"
    assert not source.exists()
    assert runtime.started is False
    assert runtime.closed is True
    assert scheduler.releases[0]["outcome"] == "failed"
    assert scheduler.releases[0]["error_code"] == "ORPHANED_STAGING_QUARANTINED"

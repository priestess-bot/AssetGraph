from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .events import DouyinLiveEventCollector
from .runtime import SidecarRuntime
from .scheduler import CaptureIngestionCoordinator, LeaseHeartbeat, SingleChannelScheduler
from .streamcap import StreamCapChunkAdapter


@dataclass(frozen=True, slots=True)
class CaptureCycleResult:
    target_code: str | None
    session_code: str | None
    outcome: str
    chunk_count: int


@dataclass(slots=True)
class _EventState:
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[int] | None = None
    saw_live: bool = False
    offline_since: float | None = None


class LiveCaptureOrchestrator:
    def __init__(
        self,
        *,
        scheduler: SingleChannelScheduler,
        runtime: SidecarRuntime,
        coordinator: CaptureIngestionCoordinator,
        event_collector: DouyinLiveEventCollector,
        chunk_adapter: StreamCapChunkAdapter,
        poll_seconds: float = 2,
        offline_grace_seconds: float = 120,
        target_wait_seconds: float = 180,
    ):
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if offline_grace_seconds < chunk_adapter.settle_seconds:
            raise ValueError("offline grace must cover the chunk stability window")
        if target_wait_seconds <= 0:
            raise ValueError("target_wait_seconds must be positive")
        self.scheduler = scheduler
        self.runtime = runtime
        self.coordinator = coordinator
        self.event_collector = event_collector
        self.chunk_adapter = chunk_adapter
        self.poll_seconds = poll_seconds
        self.offline_grace_seconds = offline_grace_seconds
        self.target_wait_seconds = target_wait_seconds

    async def run_cycle(
        self, *, stop_requested: Callable[[], bool] = lambda: False
    ) -> CaptureCycleResult:
        lease = await asyncio.to_thread(self.scheduler.claim)
        if lease is None:
            return CaptureCycleResult(None, None, "no_target", 0)

        event_state = _EventState()
        released = False
        session_code: str | None = None
        try:
            baseline = self._media_states()
            if baseline:
                quarantined = await asyncio.to_thread(
                    self._quarantine_baseline,
                    baseline,
                    lease.target_code,
                )
                await asyncio.to_thread(
                    self.scheduler.release,
                    lease,
                    outcome="failed",
                    error_code="ORPHANED_STAGING_QUARANTINED",
                    error_message=json.dumps(
                        quarantined,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )[:4000],
                )
                released = True
                return CaptureCycleResult(
                    lease.target_code,
                    None,
                    "orphan_quarantined",
                    0,
                )
            await asyncio.to_thread(self.runtime.ensure_running)
            with LeaseHeartbeat(self.scheduler, lease) as heartbeat:
                decision = await self._capture_loop(
                    lease=lease,
                    heartbeat=heartbeat,
                    event_state=event_state,
                    baseline=baseline,
                    stop_requested=stop_requested,
                )
            session_code = (
                str(self.coordinator.session["session_code"])
                if self.coordinator.session is not None
                else None
            )
            await self._stop_event_collector(event_state, suppress_errors=False)
            chunk_count = len(self.coordinator.timeline.spans)
            if self.coordinator.session is not None:
                finish_status = "completed" if decision == "captured" else "abandoned"
                await asyncio.to_thread(
                    self.coordinator.finish,
                    status=finish_status,
                    failure_code=None,
                    failure_message=None,
                )
            release_outcome = "captured" if decision == "captured" else "idle"
            await asyncio.to_thread(self.scheduler.release, lease, outcome=release_outcome)
            released = True
            return CaptureCycleResult(
                lease.target_code,
                session_code,
                decision,
                chunk_count,
            )
        except Exception as exc:
            await self._stop_event_collector(event_state, suppress_errors=True)
            if self.coordinator.session is not None:
                session_code = str(self.coordinator.session["session_code"])
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        self.coordinator.finish,
                        status="failed",
                        failure_code="ORCHESTRATION_FAILED",
                        failure_message=str(exc)[:4000],
                    )
            if not released:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        self.scheduler.release,
                        lease,
                        outcome="failed",
                        error_code="ORCHESTRATION_FAILED",
                        error_message=str(exc)[:4000],
                    )
                released = True
            raise
        finally:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.runtime.close)
            if not released:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        self.scheduler.release,
                        lease,
                        outcome="failed",
                        error_code="ORCHESTRATION_INTERRUPTED",
                        error_message="capture cycle exited before releasing its lease",
                    )

    async def _capture_loop(
        self,
        *,
        lease: Any,
        heartbeat: LeaseHeartbeat,
        event_state: _EventState,
        baseline: dict[Path, tuple[int, int]],
        stop_requested: Callable[[], bool],
    ) -> str:
        states = dict(baseline)
        tracked: set[Path] = set()
        first_seen: dict[Path, datetime] = {}
        cycle_started = time.monotonic()
        last_media_change = cycle_started
        previous_chunk_end: datetime | None = None
        part_index = 0

        while True:
            heartbeat.raise_if_failed()
            if event_state.task is not None and event_state.task.done():
                event_state.task.result()
                raise RuntimeError("douyinLive event collector stopped before capture completion")
            if stop_requested():
                return "stopped"

            current = self._media_states()
            now = datetime.now(UTC)
            disappeared = tracked - set(current)
            if disappeared:
                missing = sorted(str(path) for path in disappeared)[0]
                raise RuntimeError(f"StreamCap part disappeared before finalization: {missing}")
            for path, state in current.items():
                previous = states.get(path)
                if previous is None or previous != state:
                    tracked.add(path)
                    first_seen.setdefault(path, now)
                    last_media_change = time.monotonic()
            states = current

            if tracked and self.coordinator.session is None:
                observed_started_at = min(first_seen[path] for path in tracked)
                await asyncio.to_thread(
                    self.coordinator.begin,
                    lease,
                    observed_started_at=observed_started_at,
                )
                await self._start_event_collector(lease.target, event_state)

            ready = [path for path in self.chunk_adapter.scan_ready() if path in tracked]
            ready.sort(key=lambda path: (first_seen[path], path.name))
            for path in ready:
                probe = await asyncio.to_thread(self.chunk_adapter.probe, path)
                duration = float((probe.get("format") or {}).get("duration") or 0)
                if duration <= 0:
                    raise RuntimeError("ready StreamCap part has no decoded duration")
                stat_result = path.stat()
                capture_ended_at = datetime.fromtimestamp(stat_result.st_mtime, UTC)
                decoded_start = capture_ended_at - timedelta(seconds=duration)
                capture_started_at = min(first_seen[path], decoded_start)
                discontinuity_kind, discontinuity_ms = _wall_discontinuity(
                    previous_chunk_end, capture_started_at, part_index
                )
                await asyncio.to_thread(
                    self.coordinator.ingest_chunk,
                    source=path,
                    part_index=part_index,
                    capture_started_at=capture_started_at,
                    capture_ended_at=capture_ended_at,
                    discontinuity_kind=discontinuity_kind,
                    discontinuity_milliseconds=discontinuity_ms,
                )
                previous_chunk_end = capture_ended_at
                part_index += 1
                tracked.discard(path)
                first_seen.pop(path, None)
                states.pop(path, None)

            elapsed = time.monotonic() - cycle_started
            if self.coordinator.session is None and elapsed >= self.target_wait_seconds:
                return "idle"
            inactive_for = time.monotonic() - last_media_change
            if (
                self.coordinator.session is not None
                and not tracked
                and inactive_for >= self.offline_grace_seconds
            ):
                return "captured"
            await asyncio.sleep(self.poll_seconds)

    async def _start_event_collector(
        self, target: dict[str, Any], event_state: _EventState
    ) -> None:
        if self.coordinator.session is None:
            raise RuntimeError("event collection requires an active capture session")
        session_code = str(self.coordinator.session["session_code"])
        room_id = _room_id(target)

        async def register(metadata: dict[str, Any]) -> None:
            await asyncio.to_thread(
                self.coordinator.api.register_event_batch,
                session_code,
                metadata,
            )

        async def observe(event: dict[str, Any]) -> None:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                return
            if payload.get("type") != "system" or payload.get("event") != "live_status":
                return
            if payload.get("live") is True:
                event_state.saw_live = True
                event_state.offline_since = None
            elif event_state.saw_live and payload.get("live") is False:
                event_state.offline_since = time.monotonic()

        event_state.task = asyncio.create_task(
            self.event_collector.collect(
                room_id=room_id,
                session_code=session_code,
                register_batch=register,
                stop_event=event_state.stop,
                event_callback=observe,
            ),
            name=f"douyin-events-{session_code}",
        )

    async def _stop_event_collector(
        self, event_state: _EventState, *, suppress_errors: bool
    ) -> None:
        event_state.stop.set()
        if event_state.task is None:
            return
        if suppress_errors:
            with contextlib.suppress(Exception):
                await event_state.task
        else:
            await event_state.task
        event_state.task = None

    def _media_states(self) -> dict[Path, tuple[int, int]]:
        states: dict[Path, tuple[int, int]] = {}
        root = self.chunk_adapter.streamcap_root
        if not root.is_dir():
            return states
        for path in root.rglob("*"):
            if path.suffix.lower() != ".ts":
                continue
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            stat_result = resolved.stat()
            states[resolved] = (stat_result.st_size, stat_result.st_mtime_ns)
        return states

    def _quarantine_baseline(
        self,
        baseline: dict[Path, tuple[int, int]],
        target_code: str,
    ) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for path in sorted(baseline):
            manifests.append(
                self.chunk_adapter.quarantine_orphan(path, target_code=target_code)
            )
        return manifests


def _room_id(target: dict[str, Any]) -> str:
    canonical = str(target.get("canonical_room_id") or "").strip()
    if canonical:
        if "/" in canonical:
            raise RuntimeError("canonical Douyin room ID cannot contain a slash")
        return canonical
    path = urlsplit(str(target["room_url"])).path.rstrip("/")
    room_id = path.rsplit("/", maxsplit=1)[-1]
    if not room_id:
        raise RuntimeError("Douyin room URL does not contain a room identifier")
    return room_id


def _wall_discontinuity(
    previous_end: datetime | None,
    current_start: datetime,
    part_index: int,
) -> tuple[str, int]:
    if previous_end is None:
        return "none", 0
    delta_ms = int(round((current_start - previous_end).total_seconds() * 1000))
    if abs(delta_ms) <= 2000:
        return ("reset" if part_index else "none"), delta_ms
    if delta_ms > 0:
        return "gap", delta_ms
    return "overlap", delta_ms

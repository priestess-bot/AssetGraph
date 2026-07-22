from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .api_client import LiveResearchAPIError
from .pins import DOUYINLIVE_COMMIT, DOUYINLIVE_VERSION, STREAMCAP_COMMIT, STREAMCAP_VERSION
from .sidecars import InstalledSidecars, StreamCapTargetConfig
from .streamcap import SegmentListEntry, StreamCapChunkAdapter
from .timeline import TimelineAssembler, channel_payloads


class SchedulerAPI(Protocol):
    def claim_watch_target(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None: ...

    def heartbeat_watch_target(self, target_code: str, **payload: Any) -> dict[str, Any]: ...

    def release_watch_target(self, target_code: str, **payload: Any) -> dict[str, Any]: ...

    def create_capture_session(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def add_channel(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def finalize_chunk(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def append_timeline(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def register_event_batch(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def finish_capture_session(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(slots=True)
class ActiveWatchLease:
    target: dict[str, Any]
    worker_id: str
    lease_seconds: int

    @property
    def target_code(self) -> str:
        return str(self.target["target_code"])

    @property
    def claim_token(self) -> str:
        return str(self.target["claim_token"])

    @property
    def lease_version(self) -> int:
        return int(self.target["lease_version"])


class SingleChannelScheduler:
    def __init__(
        self,
        *,
        api: SchedulerAPI,
        target_config: StreamCapTargetConfig,
        sidecars: InstalledSidecars | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 120,
    ):
        if lease_seconds < 30:
            raise ValueError("lease_seconds must be at least 30")
        self.api = api
        self.target_config = target_config
        self.sidecars = sidecars or InstalledSidecars()
        self.worker_id = worker_id or f"live-research-{socket.gethostname()}-{os.getpid()}"
        self.lease_seconds = lease_seconds

    def claim(self) -> ActiveWatchLease | None:
        target = self.api.claim_watch_target(self.worker_id, self.lease_seconds)
        if target is None:
            return None
        try:
            self.sidecars.verify()
            self.target_config.write_single_target(target)
        except Exception as exc:
            self.api.release_watch_target(
                str(target["target_code"]),
                worker_id=self.worker_id,
                claim_token=str(target["claim_token"]),
                lease_version=int(target["lease_version"]),
                outcome="blocked",
                next_check_seconds=3600,
                error_code="SIDECAR_PIN_OR_CONFIG_INVALID",
                error_message=str(exc)[:4000],
            )
            raise
        return ActiveWatchLease(target, self.worker_id, self.lease_seconds)

    def heartbeat(self, lease: ActiveWatchLease) -> None:
        lease.target = self.api.heartbeat_watch_target(
            lease.target_code,
            worker_id=lease.worker_id,
            claim_token=lease.claim_token,
            lease_version=lease.lease_version,
            lease_seconds=lease.lease_seconds,
        )

    def release(
        self,
        lease: ActiveWatchLease,
        *,
        outcome: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        next_check = int(lease.target.get("poll_interval_seconds") or 180)
        self.api.release_watch_target(
            lease.target_code,
            worker_id=lease.worker_id,
            claim_token=lease.claim_token,
            lease_version=lease.lease_version,
            outcome=outcome,
            next_check_seconds=next_check,
            error_code=error_code,
            error_message=error_message,
        )


class LeaseHeartbeat:
    def __init__(self, scheduler: SingleChannelScheduler, lease: ActiveWatchLease):
        self.scheduler = scheduler
        self.lease = lease
        self.interval = max(5.0, lease.lease_seconds / 3)
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "LeaseHeartbeat":
        self._thread = threading.Thread(target=self._run, name="live-research-heartbeat", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 5)
        self.raise_if_failed()

    def raise_if_failed(self) -> None:
        failure = self._failure
        if isinstance(failure, LiveResearchAPIError):
            raise failure
        if failure is not None:
            raise RuntimeError("watch-target lease heartbeat failed") from failure

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.scheduler.heartbeat(self.lease)
            except BaseException as exc:
                self._failure = exc
                self._stop.set()
                return


class CaptureIngestionCoordinator:
    def __init__(
        self,
        *,
        api: SchedulerAPI,
        chunk_adapter: StreamCapChunkAdapter,
        timeline: TimelineAssembler | None = None,
    ):
        self.api = api
        self.chunk_adapter = chunk_adapter
        self.timeline = timeline or TimelineAssembler()
        self.session: dict[str, Any] | None = None
        self._channels_registered = False

    def begin(
        self,
        lease: ActiveWatchLease,
        *,
        source_live_session_id: str | None = None,
        observed_started_at: datetime | None = None,
    ) -> dict[str, Any]:
        if self.session is not None:
            raise RuntimeError("a capture session is already active in this coordinator")
        observed_started = observed_started_at or datetime.now(UTC)
        self.session = self.api.create_capture_session(
            {
                "target_code": lease.target_code,
                "worker_id": lease.worker_id,
                "claim_token": lease.claim_token,
                "lease_version": lease.lease_version,
                "recorder_engine": "streamcap",
                "recorder_version": STREAMCAP_VERSION,
                "recorder_build_fingerprint": STREAMCAP_COMMIT,
                "event_adapter": "douyinlive",
                "event_adapter_version": DOUYINLIVE_VERSION,
                "source_live_session_id": source_live_session_id,
                "observed_started_at": _utc_text(observed_started),
                "monotonic_started_ns": time.monotonic_ns(),
                "capture_boot_id": _boot_id(),
                "metadata": {
                    "douyinlive_commit": DOUYINLIVE_COMMIT,
                    "clock_contract": "utc+monotonic.v1",
                    "target_quality": "720p",
                    "segment_duration_seconds": 600,
                },
            }
        )
        return self.session

    def ingest_chunk(
        self,
        *,
        source: Path,
        part_index: int,
        capture_started_at: datetime,
        capture_ended_at: datetime,
        segment_entry: SegmentListEntry | None = None,
        discontinuity_kind: str = "none",
        discontinuity_milliseconds: int = 0,
    ) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("capture session has not started")
        session_code = str(self.session["session_code"])
        manifest = self.chunk_adapter.finalize(
            source=source,
            session_code=session_code,
            part_index=part_index,
            capture_started_at=capture_started_at,
            capture_ended_at=capture_ended_at,
            segment_entry=segment_entry,
            discontinuity_kind=discontinuity_kind,
            discontinuity_milliseconds=discontinuity_milliseconds,
        )
        if not self._channels_registered:
            for channel in channel_payloads(manifest["stream_timing"]):
                self.api.add_channel(session_code, channel)
            self._channels_registered = True
        chunk = self.api.finalize_chunk(session_code, manifest)
        span = self.timeline.append(chunk)
        self.api.append_timeline(session_code, span)
        return {"chunk": chunk, "timeline_span": span}

    def finish(
        self,
        *,
        status: str = "completed",
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("capture session has not started")
        session_code = str(self.session["session_code"])
        result = self.api.finish_capture_session(
            session_code,
            {
                "status": status,
                "observed_ended_at": _utc_now(),
                "monotonic_ended_ns": time.monotonic_ns(),
                "failure_code": failure_code,
                "failure_message": failure_message,
                "metadata": {"ingested_chunk_count": len(self.timeline.spans)},
            },
        )
        self.session = None
        self.timeline = TimelineAssembler()
        self._channels_registered = False
        return result

    def abandon_local_session(self) -> None:
        # The API owns stale-session cleanup; local state must never cross a lease boundary.
        self.session = None
        self.timeline = TimelineAssembler()
        self._channels_registered = False


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("capture start must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _boot_id() -> str | None:
    path = Path("/proc/sys/kernel/random/boot_id")
    try:
        return path.read_text(encoding="ascii").strip()[:128]
    except OSError:
        return None

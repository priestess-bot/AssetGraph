from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import pytest

from assetgraph_live_research.api_client import LiveResearchAPIError
from assetgraph_live_research.main import _run_polling, _run_scheduler_loop
from assetgraph_live_research.scheduler import CaptureIngestionCoordinator, LeaseHeartbeat


def test_polling_daemon_retries_only_api_errors_with_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    failures = [LiveResearchAPIError("offline") for _ in range(7)]
    outcomes: list[object] = [*failures, RuntimeError("stop")]
    sleeps: list[float] = []

    def run_once() -> object:
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(
        "assetgraph_live_research.main.time.sleep", sleeps.append
    )
    caplog.set_level(logging.WARNING)

    with pytest.raises(RuntimeError, match="stop"):
        _run_polling(run_once, once=False, poll_seconds=0.25)

    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert caplog.text.count("AssetGraph API unavailable to polling worker") == 7


def test_polling_once_propagates_api_error_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "assetgraph_live_research.main.time.sleep", sleeps.append
    )

    def fail() -> object:
        raise LiveResearchAPIError("offline")

    with pytest.raises(LiveResearchAPIError, match="offline"):
        _run_polling(fail, once=True, poll_seconds=1)
    assert sleeps == []


class _Coordinator:
    def __init__(self) -> None:
        self.session: dict[str, Any] | None = None
        self.abandoned = 0

    def abandon_local_session(self) -> None:
        self.session = None
        self.abandoned += 1


class _RecoveringOrchestrator:
    def __init__(self, coordinator: _Coordinator, stopping: threading.Event) -> None:
        self.coordinator = coordinator
        self.stopping = stopping
        self.calls = 0

    async def run_cycle(self, **_payload: Any) -> None:
        self.calls += 1
        if self.calls == 1:
            self.coordinator.session = {"session_code": "stale-session"}
            raise LiveResearchAPIError("backend restarting")
        assert self.coordinator.session is None
        self.stopping.set()


def test_scheduler_daemon_discards_local_session_before_retry() -> None:
    stopping = threading.Event()
    coordinator = _Coordinator()
    orchestrator = _RecoveringOrchestrator(coordinator, stopping)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = asyncio.run(
        _run_scheduler_loop(
            orchestrator,  # type: ignore[arg-type]
            coordinator,  # type: ignore[arg-type]
            once=False,
            stopping=stopping,
            sleep=sleep,
        )
    )

    assert result == 0
    assert orchestrator.calls == 2
    assert coordinator.abandoned == 1
    assert sleeps == [1.0]


def test_scheduler_once_propagates_api_error() -> None:
    stopping = threading.Event()
    coordinator = _Coordinator()

    class _FailingOrchestrator:
        async def run_cycle(self, **_payload: Any) -> None:
            coordinator.session = {"session_code": "stale-session"}
            raise LiveResearchAPIError("offline")

    async def unexpected_sleep(_seconds: float) -> None:
        raise AssertionError("once mode must not sleep")

    with pytest.raises(LiveResearchAPIError, match="offline"):
        asyncio.run(
            _run_scheduler_loop(
                _FailingOrchestrator(),  # type: ignore[arg-type]
                coordinator,  # type: ignore[arg-type]
                once=True,
                stopping=stopping,
                sleep=unexpected_sleep,
            )
        )
    assert coordinator.session is None
    assert coordinator.abandoned == 1


def test_coordinator_abandons_all_local_session_state() -> None:
    coordinator = CaptureIngestionCoordinator(
        api=object(),  # type: ignore[arg-type]
        chunk_adapter=object(),  # type: ignore[arg-type]
    )
    previous_timeline = coordinator.timeline
    coordinator.session = {"session_code": "stale-session"}
    coordinator.timeline.spans.append({"span_index": 0})
    coordinator._channels_registered = True

    coordinator.abandon_local_session()

    assert coordinator.session is None
    assert coordinator.timeline is not previous_timeline
    assert coordinator.timeline.spans == []
    assert coordinator._channels_registered is False


def test_scheduler_heartbeat_preserves_api_error_type() -> None:
    heartbeat = LeaseHeartbeat.__new__(LeaseHeartbeat)
    heartbeat._failure = LiveResearchAPIError("heartbeat rejected")

    with pytest.raises(LiveResearchAPIError, match="heartbeat rejected"):
        heartbeat.raise_if_failed()

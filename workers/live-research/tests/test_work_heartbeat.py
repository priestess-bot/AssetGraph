from __future__ import annotations

import time
from typing import Any

import pytest

from assetgraph_live_research.providers import ModelProviderError
from assetgraph_live_research.worker import AnalysisRunWorker, WorkLeaseHeartbeat


class _HeartbeatAPI:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def heartbeat_clip_job(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("clip", code, payload))
        if self.fail:
            raise RuntimeError("lease lost")
        return {}

    def heartbeat_analysis_run(
        self, code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("analysis", code, payload))
        if self.fail:
            raise RuntimeError("lease lost")
        return {}


def test_work_heartbeat_renews_long_running_analysis() -> None:
    api = _HeartbeatAPI()
    with WorkLeaseHeartbeat(
        api=api,  # type: ignore[arg-type]
        work_type="analysis",
        work_code="run-1",
        worker_id="worker-1",
        lease_token="11111111-1111-1111-1111-111111111111",
        lease_seconds=30,
        interval_seconds=0.005,
    ):
        time.sleep(0.02)

    assert len(api.calls) >= 2
    assert all(call[2]["worker_id"] == "worker-1" for call in api.calls)


def test_work_heartbeat_surfaces_fencing_failure() -> None:
    api = _HeartbeatAPI(fail=True)
    with pytest.raises(RuntimeError, match="lease heartbeat failed"):
        with WorkLeaseHeartbeat(
            api=api,  # type: ignore[arg-type]
            work_type="clip",
            work_code="clip-1",
            worker_id="worker-1",
            lease_token="11111111-1111-1111-1111-111111111111",
            lease_seconds=30,
            interval_seconds=0.001,
        ):
            time.sleep(0.01)


class _AnalysisAPI:
    def __init__(self):
        self.failure: dict[str, Any] | None = None

    def claim_analysis_run(self, worker_id: str, lease_seconds: int) -> dict[str, Any]:
        del worker_id, lease_seconds
        return {
            "analysis_run_code": "run-1",
            "session_code": "capture-1",
            "lease_token": "11111111-1111-1111-1111-111111111111",
        }

    def get_capture_session(self, session_code: str) -> dict[str, Any]:
        return {"session_code": session_code}

    def heartbeat_analysis_run(
        self, code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del code, payload
        return {}

    def complete_analysis_run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"unexpected completion: {code} {payload}")

    def fail_analysis_run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.failure = {"code": code, **payload}
        return {}


class _TransientExecutor:
    def execute(self, run: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        del run, session
        raise ModelProviderError("temporary outage", retryable=True)


def test_analysis_worker_requests_bounded_retry_for_transient_provider_error() -> None:
    api = _AnalysisAPI()
    worker = AnalysisRunWorker(
        api=api,  # type: ignore[arg-type]
        executor=_TransientExecutor(),
        worker_id="worker-1",
        lease_seconds=30,
    )

    assert worker.run_once() is True
    assert api.failure is not None
    assert api.failure["retryable"] is True
    assert api.failure["retry_delay_seconds"] == 60
    assert api.failure["error_code"] == "ANALYSIS_PROVIDER_TRANSIENT"

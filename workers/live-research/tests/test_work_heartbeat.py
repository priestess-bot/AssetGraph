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
            "analysis_type": "asr",
            "strategy_revision": "live.asr.zh.v2",
            "input_fingerprint": "a" * 64,
            "lease_token": "11111111-1111-1111-1111-111111111111",
        }

    def authorize_provider_strategy(self, **_kwargs: Any) -> dict[str, str]:
        return {"processor_call_audit_code": "PROCESSOR-001"}

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


class _SuccessfulAnalysisAPI:
    def __init__(self, *, evidence_failure: bool = False) -> None:
        self.evidence_failure = evidence_failure
        self.events: list[str] = []
        self.completion: dict[str, Any] | None = None
        self.failure: dict[str, Any] | None = None

    def claim_analysis_run(self, worker_id: str, lease_seconds: int) -> dict[str, Any]:
        del worker_id, lease_seconds
        return {
            "analysis_run_code": "run-1",
            "session_code": "capture-1",
            "analysis_type": "asr",
            "strategy_revision": "live.asr.zh.v2",
            "input_fingerprint": "a" * 64,
            "lease_token": "11111111-1111-1111-1111-111111111111",
        }

    def authorize_provider_strategy(self, **_kwargs: Any) -> dict[str, str]:
        self.events.append("authorize")
        return {"processor_call_audit_code": "PROCESSOR-001"}

    def get_capture_session(self, session_code: str) -> dict[str, Any]:
        return {"session_code": session_code}

    def heartbeat_analysis_run(
        self, code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        del code, payload
        return {}

    def persist_provider_invocation_evidence(self, evidence: dict[str, Any]) -> str:
        assert evidence["processor_call_audit_code"] == "PROCESSOR-001"
        self.events.append("evidence")
        if self.evidence_failure:
            raise RuntimeError("evidence storage unavailable")
        return "ART-PROVIDER-001"

    def complete_analysis_run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.events.append("complete")
        self.completion = {"code": code, **payload}
        return {}

    def fail_analysis_run(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.events.append("fail")
        self.failure = {"code": code, **payload}
        return {}


class _SuccessfulExecutor:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def execute(self, run: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        del session
        assert run["_processor_call_audit_code"] == "PROCESSOR-001"
        self.events.append("invoke")
        return {
            "output_payload": {"transcript": {"text": "verified"}},
            "provider_invocation_evidence": {
                "processor_call_audit_code": "PROCESSOR-001"
            },
        }


def test_external_analysis_persists_evidence_before_result_completion() -> None:
    api = _SuccessfulAnalysisAPI()
    worker = AnalysisRunWorker(
        api=api,  # type: ignore[arg-type]
        executor=_SuccessfulExecutor(api.events),
        worker_id="worker-1",
        lease_seconds=30,
    )

    assert worker.run_once() is True
    assert api.events == ["authorize", "invoke", "evidence", "complete"]
    assert api.completion is not None
    assert api.completion["invocation_evidence_ref"] == "ART-PROVIDER-001"
    assert "provider_invocation_evidence" not in api.completion
    assert api.failure is None


def test_external_analysis_cannot_complete_when_evidence_storage_fails() -> None:
    api = _SuccessfulAnalysisAPI(evidence_failure=True)
    worker = AnalysisRunWorker(
        api=api,  # type: ignore[arg-type]
        executor=_SuccessfulExecutor(api.events),
        worker_id="worker-1",
        lease_seconds=30,
    )

    assert worker.run_once() is True
    assert api.events == ["authorize", "invoke", "evidence", "fail"]
    assert api.completion is None
    assert api.failure is not None
    assert api.failure["error_code"] == "ANALYSIS_EXECUTION_FAILED"

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.live_observations import (
    AnalysisRetryRequest,
    AnalysisRunCompletion,
    CaptureChunkFinalize,
    CaptureSessionFinish,
)
from app.services.live_observations import LiveObservationService


class _Repository:
    def __init__(self) -> None:
        self.finalize_call: dict[str, Any] | None = None
        self.finish_call: dict[str, Any] | None = None
        self.complete_call: dict[str, Any] | None = None
        self.retry_call: dict[str, Any] | None = None

    def finalize_capture_chunk(
        self,
        session_code: str,
        payload: dict[str, Any],
        *,
        analysis_specs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.finalize_call = {
            "session_code": session_code,
            "payload": payload,
            "analysis_specs": analysis_specs,
        }
        return {"chunk_code": "chunk-1"}

    def finish_capture_session(
        self,
        session_code: str,
        payload: dict[str, Any],
        *,
        analysis_specs: list[dict[str, Any]],
        aggregation_spec: dict[str, str],
    ) -> dict[str, Any]:
        self.finish_call = {
            "session_code": session_code,
            "payload": payload,
            "analysis_specs": analysis_specs,
            "aggregation_spec": aggregation_spec,
        }
        return {"session_code": session_code, "status": payload["status"]}

    def complete_analysis_run(
        self,
        run_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
        *,
        aggregation_spec: dict[str, str],
    ) -> dict[str, Any]:
        self.complete_call = {
            "run_code": run_code,
            "worker_id": worker_id,
            "lease_token": lease_token,
            "payload": payload,
            "aggregation_spec": aggregation_spec,
        }
        return {"analysis_run_code": run_code, "status": "succeeded"}

    def retry_analysis_run(
        self, run_code: str, worker_id: str, reason: str
    ) -> dict[str, Any]:
        self.retry_call = {
            "run_code": run_code,
            "worker_id": worker_id,
            "reason": reason,
        }
        return {"analysis_run_code": run_code, "status": "queued"}


def test_chunk_finish_and_analysis_completion_carry_the_automatic_dag() -> None:
    repository = _Repository()
    service = LiveObservationService(repository)
    now = datetime.now(UTC)
    service.finalize_chunk(
        "capture-1",
        CaptureChunkFinalize(
            part_index=0,
            relative_path="raw-recordings/capture-1/chunks/chunk.ts",
            file_size=10,
            checksum_sha256="a" * 64,
            capture_started_at=now,
            capture_ended_at=now,
            decoded_duration_seconds=10,
        ),
    )
    service.finish_capture_session(
        "capture-1",
        CaptureSessionFinish(status="completed", observed_ended_at=now),
    )
    service.complete_analysis_run(
        "analysis-1",
        AnalysisRunCompletion(
            worker_id="worker-1",
            lease_token="11111111-1111-1111-1111-111111111111",
            output_payload={"observations": [{"kind": "host"}]},
        ),
    )
    service.retry_analysis_run(
        "analysis-2",
        AnalysisRetryRequest(
            worker_id="worker-1",
            reason="Provider credentials were configured",
        ),
    )

    assert repository.finalize_call is not None
    assert {
        spec["analysis_type"] for spec in repository.finalize_call["analysis_specs"]
    } == {"frame_sampling", "asr", "ocr", "layout_inference"}
    assert repository.finish_call is not None
    assert (
        repository.finish_call["aggregation_spec"]["strategy_revision"]
        == "live.template-aggregation.v2"
    )
    assert repository.complete_call is not None
    assert (
        repository.complete_call["aggregation_spec"]["strategy_revision"]
        == "live.template-aggregation.v2"
    )
    assert repository.retry_call == {
        "run_code": "analysis-2",
        "worker_id": "worker-1",
        "reason": "Provider credentials were configured",
    }

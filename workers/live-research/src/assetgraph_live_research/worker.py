from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol

from .api_client import LiveResearchAPIClient
from .clipper import FFmpegClipper


class AnalysisExecutor(Protocol):
    def execute(self, run: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]: ...


class WorkLeaseHeartbeat:
    def __init__(
        self,
        *,
        api: LiveResearchAPIClient,
        work_type: str,
        work_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
        interval_seconds: float | None = None,
    ):
        if work_type not in {"clip", "analysis"}:
            raise ValueError("unsupported heartbeat work type")
        self.api = api
        self.work_type = work_type
        self.work_code = work_code
        self.payload = {
            "worker_id": worker_id,
            "lease_token": lease_token,
            "lease_seconds": lease_seconds,
        }
        self.interval = interval_seconds or max(5.0, min(60.0, lease_seconds / 3))
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "WorkLeaseHeartbeat":
        self._thread = threading.Thread(
            target=self._run,
            name=f"live-research-{self.work_type}-heartbeat",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 5)
        if exc_type is None:
            self.raise_if_failed()

    def raise_if_failed(self) -> None:
        if self._failure is not None:
            raise RuntimeError(f"{self.work_type} lease heartbeat failed") from self._failure

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if self.work_type == "clip":
                    self.api.heartbeat_clip_job(self.work_code, self.payload)
                else:
                    self.api.heartbeat_analysis_run(self.work_code, self.payload)
            except BaseException as exc:
                self._failure = exc
                self._stop.set()
                return


@dataclass(slots=True)
class ClipJobWorker:
    api: LiveResearchAPIClient
    clipper: FFmpegClipper
    worker_id: str
    lease_seconds: int = 1800

    def run_once(self) -> bool:
        job = self.api.claim_clip_job(self.worker_id, self.lease_seconds)
        if job is None:
            return False
        try:
            with WorkLeaseHeartbeat(
                api=self.api,
                work_type="clip",
                work_code=str(job["clip_job_code"]),
                worker_id=self.worker_id,
                lease_token=str(job["lease_token"]),
                lease_seconds=self.lease_seconds,
            ) as heartbeat:
                session = self.api.get_capture_session(str(job["session_code"]))
                completion = self.clipper.execute(job, session)
                heartbeat.raise_if_failed()
            self.api.complete_clip_job(
                str(job["clip_job_code"]),
                {
                    "worker_id": self.worker_id,
                    "lease_token": str(job["lease_token"]),
                    **completion,
                },
            )
        except Exception as exc:
            self.api.fail_clip_job(
                str(job["clip_job_code"]),
                {
                    "worker_id": self.worker_id,
                    "lease_token": str(job["lease_token"]),
                    "error_code": "CLIP_EXECUTION_FAILED",
                    "error_message": str(exc)[:4000],
                },
            )
        return True


@dataclass(slots=True)
class AnalysisRunWorker:
    api: LiveResearchAPIClient
    executor: AnalysisExecutor
    worker_id: str
    lease_seconds: int = 1800

    def run_once(self) -> bool:
        run = self.api.claim_analysis_run(self.worker_id, self.lease_seconds)
        if run is None:
            return False
        try:
            with WorkLeaseHeartbeat(
                api=self.api,
                work_type="analysis",
                work_code=str(run["analysis_run_code"]),
                worker_id=self.worker_id,
                lease_token=str(run["lease_token"]),
                lease_seconds=self.lease_seconds,
            ) as heartbeat:
                run_for_execution = dict(run)
                requires_provider = str(run.get("analysis_type")) != "frame_sampling"
                if requires_provider:
                    authorization = self.api.authorize_provider_strategy(
                        worker_id=self.worker_id,
                        strategy_revision=str(run["strategy_revision"]),
                        analysis_type=str(run["analysis_type"]),
                        input_fingerprint=str(run["input_fingerprint"]),
                    )
                    run_for_execution["_processor_call_audit_code"] = authorization[
                        "processor_call_audit_code"
                    ]
                session = self.api.get_capture_session(str(run["session_code"]))
                completion = self.executor.execute(run_for_execution, session)
                evidence = completion.pop("provider_invocation_evidence", None)
                if requires_provider:
                    if not isinstance(evidence, dict):
                        raise RuntimeError(
                            "external analysis did not return provider invocation evidence"
                        )
                    completion["invocation_evidence_ref"] = (
                        self.api.persist_provider_invocation_evidence(evidence)
                    )
                heartbeat.raise_if_failed()
            self.api.complete_analysis_run(
                str(run["analysis_run_code"]),
                {
                    "worker_id": self.worker_id,
                    "lease_token": str(run["lease_token"]),
                    **completion,
                },
            )
        except Exception as exc:
            retryable = bool(getattr(exc, "retryable", False))
            self.api.fail_analysis_run(
                str(run["analysis_run_code"]),
                {
                    "worker_id": self.worker_id,
                    "lease_token": str(run["lease_token"]),
                    "error_code": (
                        "ANALYSIS_PROVIDER_TRANSIENT"
                        if retryable
                        else "ANALYSIS_EXECUTION_FAILED"
                    ),
                    "error_message": str(exc)[:4000],
                    "retryable": retryable,
                    "retry_delay_seconds": 60,
                },
            )
        return True

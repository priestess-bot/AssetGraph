from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID


class WorkbenchDraftLeaseError(RuntimeError):
    """The draft job lease can no longer authorize browser work or write-back."""


class DraftLeaseClient(Protocol):
    timeout_seconds: float

    def heartbeat_workbench_draft_execution(
        self,
        execution_job_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class WorkbenchDraftLeaseHeartbeat:
    client: DraftLeaseClient
    execution_job_code: str
    lease_token: str
    lease_seconds: int
    configured_interval_seconds: float = 30.0
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _error: Exception | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        code = str(self.execution_job_code or "")
        if not code or code != code.strip():
            raise ValueError("draft execution lease requires a canonical job code")
        try:
            self.lease_token = str(UUID(str(self.lease_token)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("draft execution lease requires a valid lease token") from exc
        if not 30 <= self.lease_seconds <= 3600:
            raise ValueError("draft execution lease_seconds must be between 30 and 3600")
        if self.configured_interval_seconds <= 0:
            raise ValueError("draft heartbeat interval must be positive")

    @property
    def interval_seconds(self) -> float:
        return max(0.001, min(float(self.configured_interval_seconds), self.lease_seconds / 3))

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("draft heartbeat is already started")
        self._renew()
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"workbench-draft-heartbeat-{self.execution_job_code}",
            daemon=True,
        )
        self._thread.start()

    def ensure_active(self) -> bool:
        with self._lock:
            error = self._error
        if error is not None:
            raise WorkbenchDraftLeaseError(
                f"workbench draft lease heartbeat failed: {type(error).__name__}: {error}"
            ) from error
        if self._thread is None:
            raise WorkbenchDraftLeaseError("workbench draft lease heartbeat is not running")
        return True

    def stop_for_writeback(self) -> None:
        if not self.stop():
            raise WorkbenchDraftLeaseError(
                "workbench draft heartbeat request did not stop; completion is fenced"
            )
        self.ensure_no_heartbeat_error()
        try:
            self._renew()
        except Exception as exc:
            self._record_error(exc)
            raise WorkbenchDraftLeaseError(
                f"final workbench draft lease validation failed: {type(exc).__name__}: {exc}"
            ) from exc

    def ensure_no_heartbeat_error(self) -> None:
        with self._lock:
            error = self._error
        if error is not None:
            raise WorkbenchDraftLeaseError(
                f"workbench draft lease heartbeat failed: {type(error).__name__}: {error}"
            ) from error

    def stop(self) -> bool:
        self._stop.set()
        thread = self._thread
        if thread is None:
            return True
        request_timeout = max(0.1, float(getattr(self.client, "timeout_seconds", 30.0)))
        thread.join(timeout=request_timeout + 1.0)
        return not thread.is_alive()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self._renew()
            except Exception as exc:
                self._record_error(exc)
                self._stop.set()
                return

    def _renew(self) -> None:
        self.client.heartbeat_workbench_draft_execution(
            self.execution_job_code,
            {
                "lease_token": self.lease_token,
                "lease_seconds": self.lease_seconds,
            },
        )

    def _record_error(self, error: Exception) -> None:
        with self._lock:
            if self._error is None:
                self._error = error

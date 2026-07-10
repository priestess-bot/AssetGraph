from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

from .client import AssetGraphClient
from .config import WorkerConfig

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class OperationExecutionResult:
    status: str
    summary: str
    error_message: str | None = None
    screenshot_asset_code: str | None = None
    retry_instruction: str | None = None
    details: dict[str, Any] | None = None


class BrowserUseExecutor(Protocol):
    max_side_effect_seconds: float

    def set_execution_guard(self, guard: Callable[[], bool] | None) -> None:
        """Install a lease guard checked at external side-effect boundaries."""

    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        """Execute a Maitu browser-use operation plan."""


class DryRunBrowserUseExecutor:
    """Executor used by tests and initial deployments.

    It does not open a browser.  It verifies that an operation plan is shaped
    correctly and returns a release-friendly result so a real queue is not marked
    succeeded by accident.
    """

    max_side_effect_seconds = 0.0

    def set_execution_guard(self, guard: Callable[[], bool] | None) -> None:
        return None

    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        operations = operation_plan.get("operations") or []
        if not operations:
            return OperationExecutionResult(
                status="manual_required",
                summary="Dry run found no operations in operation_plan.",
                error_message="operation_plan.operations is empty",
                retry_instruction="Regenerate the retry task operation plan before browser-use execution.",
            )
        plan_identifier = operation_plan.get("retry_task_code") or operation_plan.get("plan_code") or "unknown"
        operation_summaries = [
            {
                "operation_type": operation.get("operation_type"),
                "slot_code": operation.get("slot_code"),
                "slot_name": operation.get("slot_name"),
                "asset_code": operation.get("asset_code"),
                "asset_display_code": operation.get("asset_display_code"),
                "asset_local_file_code": operation.get("asset_local_file_code"),
                "asset_original_filename": operation.get("asset_original_filename"),
                "instruction": operation.get("instruction"),
            }
            for operation in operations
        ]
        return OperationExecutionResult(
            status="released",
            summary=f"Dry run validated {len(operations)} operation(s) for {plan_identifier}; real browser-use execution not enabled.",
            details={
                "plan_code": operation_plan.get("plan_code"),
                "retry_task_code": operation_plan.get("retry_task_code"),
                "operation_count": len(operations),
                "operations": operation_summaries,
            },
        )


@dataclass(frozen=True, slots=True)
class RetryLease:
    retry_task_code: str
    claimed_by: str
    claim_token: str
    lease_version: int

    @classmethod
    def from_claim(cls, retry_task: dict[str, Any], *, expected_worker_id: str) -> "RetryLease":
        raw_retry_task_code = str(retry_task.get("retry_task_code") or "")
        retry_task_code = raw_retry_task_code.strip()
        claimed_by = str(retry_task.get("claimed_by") or "")
        raw_claim_token = str(retry_task.get("claim_token") or "")
        lease_version = retry_task.get("lease_version")
        if not retry_task_code or raw_retry_task_code != retry_task_code:
            raise ValueError("claimed retry task is missing a canonical retry_task_code")
        if claimed_by != expected_worker_id:
            raise ValueError("claimed retry task owner does not match this worker")
        try:
            claim_token = str(UUID(raw_claim_token))
        except (ValueError, AttributeError) as exc:
            raise ValueError("claimed retry task has no valid claim_token") from exc
        if isinstance(lease_version, bool) or not isinstance(lease_version, int) or lease_version < 1:
            raise ValueError("claimed retry task has no valid lease_version")
        return cls(
            retry_task_code=retry_task_code,
            claimed_by=claimed_by,
            claim_token=claim_token,
            lease_version=lease_version,
        )

    def ownership_payload(self) -> dict[str, Any]:
        return {
            "claimed_by": self.claimed_by,
            "claim_token": self.claim_token,
            "lease_version": self.lease_version,
        }


@dataclass(slots=True)
class BrowserUseWorker:
    config: WorkerConfig
    client: AssetGraphClient
    executor: BrowserUseExecutor

    def claim_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claimed_by": self.config.worker_id,
            "lock_ttl_seconds": self.config.lock_ttl_seconds,
            "max_attempts": self.config.max_attempts,
        }
        if self.config.failure_type:
            payload["failure_type"] = self.config.failure_type
        if self.config.maitu_project_code:
            payload["maitu_project_code"] = self.config.maitu_project_code
        if self.config.scene_name:
            payload["scene_name"] = self.config.scene_name
        return payload

    def _executor_timeout_is_safe(self, retry_task_code: str) -> bool:
        if self.config.dry_run:
            if type(self.executor) is not DryRunBrowserUseExecutor:
                LOGGER.error(
                    "Rejected retry task %s: dry-run queue execution requires the sealed dry-run executor",
                    retry_task_code,
                )
                return False
            return True

        # Import locally to avoid the runner/executor result-type import cycle.
        # Exact type identity is intentional: a structural Protocol, subclass, or
        # plugin can lie about guard and timeout support while performing writes.
        from .browser_cli_session import BrowserUseCliSession
        from .maitu_executor import MaituBrowserUseExecutor

        if type(self.executor) is not MaituBrowserUseExecutor:
            LOGGER.error(
                "Rejected retry task %s: real queue execution requires the trusted Maitu executor",
                retry_task_code,
            )
            return False
        if type(self.executor.session) is not BrowserUseCliSession:
            LOGGER.error(
                "Rejected retry task %s: real queue execution requires the trusted Browser-use CLI session",
                retry_task_code,
            )
            return False
        session_runner = getattr(self.executor.session, "_runner", None)
        if (
            getattr(session_runner, "__self__", None) is not self.executor.session
            or getattr(session_runner, "__func__", None) is not BrowserUseCliSession._run_command
        ):
            LOGGER.error(
                "Rejected retry task %s: trusted Browser-use CLI session cannot use an injected command runner",
                retry_task_code,
            )
            return False
        raw_timeout = getattr(self.executor, "max_side_effect_seconds", None)
        try:
            max_side_effect_seconds = float(raw_timeout)
        except (TypeError, ValueError):
            max_side_effect_seconds = 0.0
        safe_limit = self.config.lock_ttl_seconds * 0.8
        guard_setter = getattr(self.executor, "set_execution_guard", None)
        if not callable(guard_setter):
            LOGGER.error(
                "Rejected retry task %s: executor does not implement the lease execution guard",
                retry_task_code,
            )
            return False
        if not math.isfinite(max_side_effect_seconds) or max_side_effect_seconds <= 0 or max_side_effect_seconds >= safe_limit:
            LOGGER.error(
                "Rejected retry task %s: executor side-effect timeout %r must be positive and below %.3fs",
                retry_task_code,
                raw_timeout,
                safe_limit,
            )
            return False
        return True

    def _renew_retry_lease(self, lease: RetryLease) -> None:
        self.client.heartbeat_retry_task(
            lease.retry_task_code,
            **lease.ownership_payload(),
            lock_ttl_seconds=self.config.lock_ttl_seconds,
        )

    def _callback_request_timeout_seconds(self) -> float:
        client_timeout = max(0.1, float(getattr(self.client, "timeout_seconds", 30.0)))
        callback_budget = max(0.4, self.config.lock_ttl_seconds * 0.8)
        per_attempt_budget = max(0.1, (callback_budget - 0.3) / 3)
        return min(client_timeout, per_attempt_budget)

    def _start_retry_heartbeat(
        self,
        lease: RetryLease,
        heartbeat_errors: list[Exception],
    ) -> tuple[threading.Event, threading.Thread]:
        heartbeat_interval = max(
            0.001,
            min(self.config.lease_heartbeat_interval_seconds, self.config.lock_ttl_seconds / 3),
        )
        heartbeat_stop = threading.Event()

        def heartbeat_loop() -> None:
            while not heartbeat_stop.wait(heartbeat_interval):
                try:
                    self._renew_retry_lease(lease)
                except Exception as exc:
                    heartbeat_errors.append(exc)
                    heartbeat_stop.set()

        heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            name=f"retry-heartbeat-{lease.retry_task_code}",
            daemon=True,
        )
        heartbeat_thread.start()
        return heartbeat_stop, heartbeat_thread

    def _stop_retry_heartbeat(self, heartbeat_stop: threading.Event, heartbeat_thread: threading.Thread) -> bool:
        heartbeat_stop.set()
        heartbeat_request_timeout = float(getattr(self.client, "timeout_seconds", 30.0))
        heartbeat_thread.join(timeout=max(1.0, heartbeat_request_timeout + 1.0))
        return not heartbeat_thread.is_alive()

    def _write_retry_execution_result(
        self,
        lease: RetryLease,
        payload: dict[str, Any],
        *,
        request_timeout_seconds: float,
    ) -> bool:
        for attempt in range(1, 4):
            try:
                self.client.write_retry_execution_result(
                    lease.retry_task_code,
                    **lease.ownership_payload(),
                    **payload,
                    request_timeout_seconds=request_timeout_seconds,
                )
                return True
            except Exception:
                if attempt == 3:
                    LOGGER.exception(
                        "Failed to persist retry execution %s after %s attempts",
                        payload["retry_execution_id"],
                        attempt,
                    )
                    return False
                time.sleep(0.1 * attempt)
        return False

    def run_once(self) -> bool:
        if self.config.dry_run:
            LOGGER.error("Dry-run queue execution is forbidden because claiming a retry task mutates queue state")
            return False
        if not self._executor_timeout_is_safe("<before-claim>"):
            return False

        task_bundle = self.client.claim_next_retry_task(self.claim_payload())
        if task_bundle is None:
            LOGGER.info("No claimable retry task found.")
            return False

        retry_task = task_bundle["retry_task"]
        operation_plan = task_bundle["operation_plan"]
        try:
            lease = RetryLease.from_claim(retry_task, expected_worker_id=self.config.worker_id)
        except ValueError as exc:
            LOGGER.error("Rejected invalid retry claim bundle: %s", exc)
            return True
        LOGGER.info(
            "Claimed retry task %s with lease version %s",
            lease.retry_task_code,
            lease.lease_version,
        )

        try:
            self._renew_retry_lease(lease)
        except Exception:
            LOGGER.exception("Retry lease validation failed before execution for %s", lease.retry_task_code)
            return True

        heartbeat_errors: list[Exception] = []
        heartbeat_stop, heartbeat_thread = self._start_retry_heartbeat(lease, heartbeat_errors)
        guard_setter = getattr(self.executor, "set_execution_guard", None)

        def execution_guard() -> bool:
            try:
                self._renew_retry_lease(lease)
            except Exception as exc:
                heartbeat_errors.append(exc)
                return False
            return True

        if callable(guard_setter):
            guard_setter(execution_guard)

        execution_heartbeat_stopped = False
        try:
            result = self.executor.execute_operation_plan(operation_plan)
        finally:
            if callable(guard_setter):
                guard_setter(None)
            execution_heartbeat_stopped = self._stop_retry_heartbeat(heartbeat_stop, heartbeat_thread)

        if not execution_heartbeat_stopped:
            LOGGER.error(
                "Retry heartbeat request did not stop for %s; refusing write-back while lease state is uncertain",
                lease.retry_task_code,
            )
            return True

        had_execution_heartbeat_error = bool(heartbeat_errors)
        try:
            self._renew_retry_lease(lease)
        except Exception:
            LOGGER.exception(
                "Final retry lease validation failed after execution for %s; refusing stale write-back",
                lease.retry_task_code,
            )
            return True
        if had_execution_heartbeat_error:
            LOGGER.warning(
                "Recovered retry lease %s after a transient heartbeat failure",
                lease.retry_task_code,
            )

        callback_request_timeout = self._callback_request_timeout_seconds()
        callback_heartbeat_errors: list[Exception] = []
        callback_stop, callback_thread = self._start_retry_heartbeat(lease, callback_heartbeat_errors)
        try:
            retry_execution_id = str(uuid4())
            if result.status == "released":
                self._write_retry_execution_result(
                    lease,
                    {
                        "retry_execution_id": retry_execution_id,
                        "retry_execution_status": "released",
                        "result_summary": result.summary,
                        "error_message": result.error_message,
                        "screenshot_asset_code": result.screenshot_asset_code,
                        "retry_instruction": result.retry_instruction,
                    },
                    request_timeout_seconds=callback_request_timeout,
                )
                return True

            if result.status == "succeeded":
                self._write_retry_execution_result(
                    lease,
                    {
                        "retry_execution_id": retry_execution_id,
                        "retry_execution_status": "succeeded",
                        "result_summary": result.summary,
                        "screenshot_asset_code": result.screenshot_asset_code,
                    },
                    request_timeout_seconds=callback_request_timeout,
                )
            else:
                self._write_retry_execution_result(
                    lease,
                    {
                        "retry_execution_id": retry_execution_id,
                        "retry_execution_status": "manual_required",
                        "result_summary": result.summary,
                        "error_message": result.error_message,
                        "screenshot_asset_code": result.screenshot_asset_code,
                        "retry_instruction": result.retry_instruction,
                    },
                    request_timeout_seconds=callback_request_timeout,
                )
            return True
        finally:
            if not self._stop_retry_heartbeat(callback_stop, callback_thread):
                LOGGER.error(
                    "Retry heartbeat request did not stop after callback for %s",
                    lease.retry_task_code,
                )

    def run_plan_once(self, plan_code: str) -> OperationExecutionResult:
        if not self.config.dry_run:
            raise RuntimeError("Direct replacement-plan execution requires dry-run; real work must use the leased queue path")
        if type(self.executor) is not DryRunBrowserUseExecutor:
            raise RuntimeError("Direct dry-run replacement plans require the sealed dry-run executor")
        operation_plan = self.client.get_replacement_plan_operation_plan(plan_code)
        LOGGER.info("Loaded replacement plan operation plan %s", plan_code)
        return self.executor.execute_operation_plan(operation_plan)

    def run_forever(self) -> None:
        while True:
            try:
                processed = self.run_once()
            except Exception:
                LOGGER.exception("Retry worker task iteration failed; continuing after poll interval")
                processed = False
            if not processed:
                time.sleep(self.config.poll_interval_seconds)

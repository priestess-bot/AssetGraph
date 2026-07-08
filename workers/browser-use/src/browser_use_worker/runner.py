from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

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


class BrowserUseExecutor(Protocol):
    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        """Execute a Maitu browser-use operation plan."""


class DryRunBrowserUseExecutor:
    """Executor used by tests and initial deployments.

    It does not open a browser.  It verifies that an operation plan is shaped
    correctly and returns a release-friendly result so a real queue is not marked
    succeeded by accident.
    """

    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        operations = operation_plan.get("operations") or []
        if not operations:
            return OperationExecutionResult(
                status="manual_required",
                summary="Dry run found no operations in operation_plan.",
                error_message="operation_plan.operations is empty",
                retry_instruction="Regenerate the retry task operation plan before browser-use execution.",
            )
        retry_task_code = operation_plan.get("retry_task_code", "unknown")
        return OperationExecutionResult(
            status="released",
            summary=f"Dry run validated {len(operations)} operation(s) for {retry_task_code}; real browser-use execution not enabled.",
        )


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

    def run_once(self) -> bool:
        task_bundle = self.client.claim_next_retry_task(self.claim_payload())
        if task_bundle is None:
            LOGGER.info("No claimable retry task found.")
            return False

        retry_task = task_bundle["retry_task"]
        operation_plan = task_bundle["operation_plan"]
        retry_task_code = retry_task["retry_task_code"]
        LOGGER.info("Claimed retry task %s", retry_task_code)

        result = self.executor.execute_operation_plan(operation_plan)
        if result.status == "succeeded":
            self.client.write_retry_execution_result(
                retry_task_code,
                retry_execution_status="succeeded",
                result_summary=result.summary,
                screenshot_asset_code=result.screenshot_asset_code,
            )
        elif result.status == "released":
            self.client.release_retry_task(
                retry_task_code,
                status="pending",
                result_summary=result.summary,
            )
        else:
            self.client.write_retry_execution_result(
                retry_task_code,
                retry_execution_status="manual_required",
                result_summary=result.summary,
                error_message=result.error_message,
                screenshot_asset_code=result.screenshot_asset_code,
                retry_instruction=result.retry_instruction,
            )
        return True

    def run_forever(self) -> None:
        while True:
            processed = self.run_once()
            if not processed:
                time.sleep(self.config.poll_interval_seconds)

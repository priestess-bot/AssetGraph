from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .runner import OperationExecutionResult


class AssetLookupClient(Protocol):
    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        """Return AssetGraph asset metadata by asset_code."""


class MaituBrowserExecutionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True, retry_instruction: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_instruction = retry_instruction


class MaituBrowserSession(Protocol):
    """Thin interface implemented by a real browser-use / Playwright session.

    The executor owns operation dispatch and AssetGraph protocol semantics.  A
    concrete session owns page selectors, browser state, upload widgets, save
    buttons, and screenshots.
    """

    def ensure_ready(self, *, maitu_project_code: str | None, scene_name: str | None) -> None:
        """Open Maitu/project/scene and verify the browser is ready."""

    def recover_login(self) -> None:
        """Recover or verify login state before retrying an operation."""

    def upload_asset(self, asset: dict[str, Any]) -> None:
        """Upload the asset file to Maitu when needed."""

    def replace_layer_asset(self, operation: dict[str, Any], asset: dict[str, Any]) -> None:
        """Replace the target layer/slot asset while preserving layout."""

    def save_project(self) -> None:
        """Persist changes in Maitu."""

    def capture_screenshot(self, *, label: str) -> str | None:
        """Capture evidence and return screenshot_asset_code when available."""

    def execute_generic_operation(self, operation: dict[str, Any], asset: dict[str, Any] | None) -> None:
        """Fallback for operation types not yet specialized."""


@dataclass(slots=True)
class MaituBrowserUseExecutor:
    asset_client: AssetLookupClient
    session: MaituBrowserSession

    SUPPORTED_OPERATION_TYPES = frozenset(
        {
            "replace_layer_asset",
            "retry_replace_layer_asset",
            "retry_asset_upload_and_replace",
            "retry_save_project",
            "recover_login_then_retry",
            "manual_retry_required",
            "resolve_missing_slot_asset",
        }
    )

    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        operations = operation_plan.get("operations") or []
        if not operations:
            return OperationExecutionResult(
                status="manual_required",
                summary="operation_plan.operations is empty; nothing to execute.",
                error_message="operation_plan.operations is empty",
                retry_instruction="Regenerate operation plan before running browser-use worker.",
            )
        unsupported_operation_types = [
            operation.get("operation_type") if isinstance(operation, dict) else None
            for operation in operations
            if not isinstance(operation, dict)
            or operation.get("operation_type") not in self.SUPPORTED_OPERATION_TYPES
        ]
        if unsupported_operation_types:
            return OperationExecutionResult(
                status="manual_required",
                summary=f"Unsupported operation type(s) rejected before browser execution: {unsupported_operation_types}",
                error_message=f"Unsupported operation type(s): {unsupported_operation_types}",
                retry_instruction="Regenerate the operation plan with explicitly supported operation types.",
            )

        maitu_project_code = operation_plan.get("maitu_project_code")
        scene_name = operation_plan.get("scene_name")
        try:
            self.session.ensure_ready(maitu_project_code=maitu_project_code, scene_name=scene_name)
            executed = 0
            for operation in operations:
                self._execute_operation(operation)
                executed += 1
            self.session.save_project()
            screenshot_asset_code = self.session.capture_screenshot(
                label=str(operation_plan.get("retry_task_code") or operation_plan.get("plan_code") or "maitu-operation")
            )
        except MaituBrowserExecutionError as exc:
            if exc.retryable:
                return OperationExecutionResult(
                    status="released",
                    summary=f"Recoverable Maitu browser execution failure: {exc}",
                    error_message=str(exc),
                    retry_instruction=exc.retry_instruction,
                )
            return OperationExecutionResult(
                status="manual_required",
                summary=f"Manual intervention required: {exc}",
                error_message=str(exc),
                retry_instruction=exc.retry_instruction,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime boundary
            return OperationExecutionResult(
                status="released",
                summary=f"Unexpected browser-use worker failure: {exc}",
                error_message=str(exc),
                retry_instruction="Inspect worker logs, browser state, and Maitu availability before retrying.",
            )

        return OperationExecutionResult(
            status="succeeded",
            summary=f"Executed {executed} Maitu browser-use operation(s) and saved project.",
            screenshot_asset_code=screenshot_asset_code,
        )

    def _execute_operation(self, operation: dict[str, Any]) -> None:
        operation_type = operation.get("operation_type")
        asset = self._load_asset(operation.get("asset_code"))

        if operation_type in {"replace_layer_asset", "retry_replace_layer_asset"}:
            self._require_asset(operation, asset)
            self.session.replace_layer_asset(operation, asset)
            return

        if operation_type == "retry_asset_upload_and_replace":
            self._require_asset(operation, asset)
            self.session.upload_asset(asset)
            self.session.replace_layer_asset(operation, asset)
            return

        if operation_type == "retry_save_project":
            self.session.save_project()
            return

        if operation_type == "recover_login_then_retry":
            self.session.recover_login()
            self._require_asset(operation, asset)
            self.session.replace_layer_asset(operation, asset)
            return

        if operation_type == "manual_retry_required":
            raise MaituBrowserExecutionError(
                operation.get("instruction") or "operation requires manual handling",
                retryable=False,
                retry_instruction=operation.get("instruction"),
            )

        if operation_type == "resolve_missing_slot_asset":
            raise MaituBrowserExecutionError(
                "slot asset is missing and must be resolved by AssetGraph or a human operator",
                retryable=False,
                retry_instruction=operation.get("instruction") or "Select a valid replacement asset before retrying.",
            )

        raise MaituBrowserExecutionError(
            f"Unsupported operation type: {operation_type}",
            retryable=False,
            retry_instruction="Regenerate the operation plan with an explicitly supported operation type.",
        )

    def _load_asset(self, asset_code: str | None) -> dict[str, Any] | None:
        if not asset_code:
            return None
        asset = self.asset_client.get_asset(asset_code)
        if asset is None:
            raise MaituBrowserExecutionError(
                f"AssetGraph asset not found: {asset_code}",
                retryable=False,
                retry_instruction="Confirm selected asset_code exists or regenerate replacement plan.",
            )
        return asset

    @staticmethod
    def _require_asset(operation: dict[str, Any], asset: dict[str, Any] | None) -> None:
        if asset is None:
            raise MaituBrowserExecutionError(
                f"Operation {operation.get('operation_type')} requires asset_code but none was provided.",
                retryable=False,
                retry_instruction="Regenerate operation plan with selected asset_code.",
            )

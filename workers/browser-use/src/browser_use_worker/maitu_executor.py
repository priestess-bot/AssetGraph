from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .runner import OperationExecutionResult


class AssetLookupClient(Protocol):
    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        """Return AssetGraph asset metadata by asset_code."""


class MaituBrowserExecutionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True, retry_instruction: str | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_instruction = retry_instruction


class OperationCheckpointController(Protocol):
    """Lease-bound checkpoint boundary installed only for a claimed retry task."""

    retry_task_code: str

    def begin(self, operation: dict[str, Any]) -> str:
        """Return one of execute, skip, or reconcile for this operation."""

    def complete(
        self,
        operation: dict[str, Any],
        *,
        result_summary: str,
        evidence: dict[str, Any],
    ) -> None:
        """Confirm a verified operation completion before downstream work."""


class MaituBrowserSession(Protocol):
    """Thin interface implemented by a real browser-use / Playwright session.

    The executor owns operation dispatch and AssetGraph protocol semantics. A
    concrete session owns page selectors, browser state, upload widgets, save
    buttons, and screenshots. Every mutating method returns authoritative
    readback evidence with ``verified=True``.
    """

    def ensure_ready(self, *, maitu_project_code: str | None, scene_name: str | None) -> None:
        """Open Maitu/project/scene and verify the browser is ready."""

    def recover_login(self) -> dict[str, Any]:
        """Recover or verify login state before retrying an operation."""

    def upload_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        """Upload the asset file and return verified evidence."""

    def replace_layer_asset(self, operation: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
        """Replace the target layer/slot asset and return verified evidence."""

    def save_project(self) -> dict[str, Any]:
        """Persist changes and return verified evidence."""

    def capture_screenshot(self, *, label: str) -> str | None:
        """Capture evidence and return screenshot_asset_code when available."""

    def execute_generic_operation(
        self,
        operation: dict[str, Any],
        asset: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Fallback for operation types not yet specialized."""


@dataclass(slots=True)
class MaituBrowserUseExecutor:
    asset_client: AssetLookupClient
    session: MaituBrowserSession
    execution_guard: Callable[[], bool] | None = None
    _checkpoint_controller: OperationCheckpointController | None = field(default=None, init=False, repr=False)

    SUPPORTED_OPERATION_TYPES = frozenset(
        {
            "replace_layer_asset",
            "retry_replace_layer_asset",
            "retry_asset_upload_and_replace",
            "save_project",
            "retry_save_project",
            "recover_login_then_retry",
            "manual_retry_required",
            "resolve_missing_slot_asset",
        }
    )
    _CANONICAL_SEGMENT = re.compile(r"[A-Za-z0-9_-]+")
    _FINGERPRINT = re.compile(r"[0-9a-f]{64}")

    @property
    def checkpoint_controller(self) -> OperationCheckpointController | None:
        return self._checkpoint_controller

    @property
    def max_side_effect_seconds(self) -> float:
        session_config = getattr(self.session, "config", None)
        raw_timeout = getattr(session_config, "timeout_seconds", None)
        try:
            return float(raw_timeout)
        except (TypeError, ValueError):
            return float("inf")

    def set_execution_guard(self, guard: Callable[[], bool] | None) -> None:
        self.execution_guard = guard
        session_guard_setter = getattr(self.session, "set_execution_guard", None)
        if callable(session_guard_setter):
            session_guard_setter(guard)

    def set_checkpoint_controller(self, controller: OperationCheckpointController | None) -> None:
        if controller is not None and self._checkpoint_controller is not None:
            raise RuntimeError("operation checkpoint controller is already installed")
        self._checkpoint_controller = controller

    def _require_execution_guard(self) -> None:
        if self.execution_guard is not None and not self.execution_guard():
            raise MaituBrowserExecutionError(
                "retry lease heartbeat failed during browser execution",
                retryable=True,
                retry_instruction="Reclaim the retry task with a fresh lease before continuing.",
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

        validation_error = self._validate_plan_before_session(operation_plan, operations)
        if validation_error is not None:
            return OperationExecutionResult(
                status="manual_required",
                summary=validation_error,
                error_message=validation_error,
                retry_instruction="Regenerate the retry plan with canonical ready operation checkpoints.",
            )

        maitu_project_code = operation_plan.get("maitu_project_code")
        scene_name = operation_plan.get("scene_name")
        executed = 0
        skipped = 0
        session_ready = False
        try:
            for operation in operations:
                self._require_execution_guard()
                decision = self._begin_operation(operation_plan, operation)
                if decision == "skip":
                    skipped += 1
                    continue
                if decision == "reconcile":
                    retry_task_code = operation_plan["retry_task_code"]
                    operation_key = operation["operation_key"]
                    reconciliation_path = (
                        f"/api/maitu/retry-tasks/{retry_task_code}/operations/{operation_key}/reconcile"
                    )
                    raise MaituBrowserExecutionError(
                        f"Operation checkpoint requires reconciliation: {operation_key}",
                        retryable=False,
                        retry_instruction=(
                            "Perform authoritative Maitu readback, then POST "
                            f"{reconciliation_path} with confirmed_completed or confirmed_not_applied evidence "
                            "before retrying."
                        ),
                    )
                if decision != "execute":
                    raise MaituBrowserExecutionError(
                        f"Operation checkpoint returned an invalid decision: {decision!r}",
                        retryable=False,
                        retry_instruction="Inspect the checkpoint API response before retrying.",
                    )

                if self._operation_requires_session(operation) and not session_ready:
                    self._require_execution_guard()
                    self.session.ensure_ready(maitu_project_code=maitu_project_code, scene_name=scene_name)
                    session_ready = True
                evidence = self._execute_operation(operation)
                verified_evidence = self._require_verified_evidence(operation, evidence)
                self._complete_operation(operation_plan, operation, verified_evidence)
                executed += 1

            screenshot_asset_code = None
            if session_ready:
                self._require_execution_guard()
                screenshot_asset_code = self.session.capture_screenshot(
                    label=str(
                        operation_plan.get("retry_task_code")
                        or operation_plan.get("plan_code")
                        or "maitu-operation"
                    )
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
            summary=f"Checkpoint-confirmed {executed} Maitu operation(s); skipped {skipped} completed operation(s).",
            screenshot_asset_code=screenshot_asset_code,
        )

    def _validate_plan_before_session(
        self,
        operation_plan: dict[str, Any],
        operations: list[Any],
    ) -> str | None:
        unsupported_operation_types = [
            operation.get("operation_type") if isinstance(operation, dict) else None
            for operation in operations
            if not isinstance(operation, dict)
            or operation.get("operation_type") not in self.SUPPORTED_OPERATION_TYPES
        ]
        if unsupported_operation_types:
            return f"Unsupported operation type(s): {unsupported_operation_types}"

        if "retry_task_code" not in operation_plan:
            return None

        raw_retry_task_code = operation_plan.get("retry_task_code")
        if not self._is_canonical_segment(raw_retry_task_code):
            return "Retry operation plan is missing a canonical retry_task_code"
        controller = self._checkpoint_controller
        if controller is None:
            return "Retry operation plan has no lease-bound checkpoint controller"
        if controller.retry_task_code != raw_retry_task_code:
            return "Retry operation plan task identity drifted from the claimed checkpoint controller"

        operation_keys: set[str] = set()
        for index, operation in enumerate(operations):
            operation_key = operation.get("operation_key")
            fingerprint = operation.get("operation_fingerprint")
            if operation.get("status") != "ready":
                return f"Retry operation {index} is not ready"
            if not self._is_canonical_segment(operation_key):
                return f"Retry operation {index} is missing a canonical operation_key"
            if operation_key in operation_keys:
                return f"Retry operation_key is not unique: {operation_key}"
            operation_keys.add(operation_key)
            if not isinstance(fingerprint, str) or self._FINGERPRINT.fullmatch(fingerprint) is None:
                return f"Retry operation {operation_key} has no canonical operation_fingerprint"
        return None

    @classmethod
    def _is_canonical_segment(cls, value: Any) -> bool:
        return isinstance(value, str) and cls._CANONICAL_SEGMENT.fullmatch(value) is not None

    @staticmethod
    def _operation_requires_session(operation: dict[str, Any]) -> bool:
        return operation.get("operation_type") not in {
            "manual_retry_required",
            "resolve_missing_slot_asset",
        }

    def _begin_operation(self, operation_plan: dict[str, Any], operation: dict[str, Any]) -> str:
        if "retry_task_code" not in operation_plan:
            return "execute"
        controller = self._checkpoint_controller
        if controller is None:  # pragma: no cover - guaranteed by whole-plan validation
            raise MaituBrowserExecutionError("checkpoint controller disappeared before operation begin", retryable=True)
        return controller.begin(operation)

    def _complete_operation(
        self,
        operation_plan: dict[str, Any],
        operation: dict[str, Any],
        evidence: dict[str, Any],
    ) -> None:
        if "retry_task_code" not in operation_plan:
            return
        controller = self._checkpoint_controller
        if controller is None:  # pragma: no cover - guaranteed by whole-plan validation
            raise MaituBrowserExecutionError("checkpoint controller disappeared before operation complete", retryable=True)
        controller.complete(
            operation,
            result_summary=f"Verified {operation.get('operation_type')} for {operation.get('operation_key')}",
            evidence=evidence,
        )

    def _execute_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        operation_type = operation.get("operation_type")

        if operation_type in {"replace_layer_asset", "retry_replace_layer_asset"}:
            asset = self._load_asset(operation.get("asset_code"))
            self._require_asset(operation, asset)
            self._require_execution_guard()
            return self.session.replace_layer_asset(operation, asset)

        if operation_type == "retry_asset_upload_and_replace":
            asset = self._load_asset(operation.get("asset_code"))
            self._require_asset(operation, asset)
            self._require_execution_guard()
            upload_evidence = self._require_verified_evidence(operation, self.session.upload_asset(asset), step="upload")
            self._require_execution_guard()
            replace_evidence = self._require_verified_evidence(
                operation,
                self.session.replace_layer_asset(operation, asset),
                step="replace",
            )
            return {"verified": True, "steps": [upload_evidence, replace_evidence]}

        if operation_type in {"save_project", "retry_save_project"}:
            self._require_execution_guard()
            return self.session.save_project()

        if operation_type == "recover_login_then_retry":
            asset = self._load_asset(operation.get("asset_code"))
            self._require_execution_guard()
            login_evidence = self._require_verified_evidence(operation, self.session.recover_login(), step="login")
            self._require_execution_guard()
            self._require_asset(operation, asset)
            replace_evidence = self._require_verified_evidence(
                operation,
                self.session.replace_layer_asset(operation, asset),
                step="replace",
            )
            return {"verified": True, "steps": [login_evidence, replace_evidence]}

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

    @staticmethod
    def _require_verified_evidence(
        operation: dict[str, Any],
        evidence: Any,
        *,
        step: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(evidence, dict) or evidence.get("verified") is not True:
            operation_name = operation.get("operation_key") or operation.get("operation_type")
            step_label = f" ({step})" if step else ""
            raise MaituBrowserExecutionError(
                f"Mutation evidence for {operation_name}{step_label} is not a verified dict",
                retryable=False,
                retry_instruction="Reconcile the browser state manually before retrying this operation.",
            )
        if MaituBrowserUseExecutor._contains_forbidden_evidence_secret(evidence):
            raise MaituBrowserExecutionError(
                "Mutation evidence contains a forbidden secret field",
                retryable=False,
                retry_instruction="Remove secret fields from readback evidence and reconcile the operation manually.",
            )
        return evidence

    @staticmethod
    def _contains_forbidden_evidence_secret(candidate: Any) -> bool:
        if isinstance(candidate, dict):
            for key, value in candidate.items():
                normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
                if any(
                    marker in normalized_key
                    for marker in ("authorization", "credential", "password", "secret", "cookie", "token")
                ):
                    return True
                if MaituBrowserUseExecutor._contains_forbidden_evidence_secret(value):
                    return True
            return False
        if isinstance(candidate, list):
            return any(MaituBrowserUseExecutor._contains_forbidden_evidence_secret(value) for value in candidate)
        return False

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


# Capture every method/property descriptor once when the built-in implementation
# is defined. A hand-maintained list can omit an internal guard that is still
# reachable from a trusted public method.
_TRUSTED_MAITU_EXECUTOR_METHODS = tuple(
    (method_name, descriptor)
    for method_name, descriptor in vars(MaituBrowserUseExecutor).items()
    if callable(descriptor) or type(descriptor) in {staticmethod, classmethod, property}
)

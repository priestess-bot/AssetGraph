from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .build_plan_preflight import BuildPlanPreflightResult


class MaituNonDestructiveSession(Protocol):
    def read_current_state(self, *, open_if_needed: bool = True) -> Any:
        """Observe current Maitu state without saving or mutating content."""

    def select_scene(self, scene_name: str) -> dict[str, Any]:
        """Select an existing scene. This is low-risk UI navigation, not content mutation."""

    def open_material_tab(self, tab_name: str) -> dict[str, Any]:
        """Open an existing material tab. This must not upload or insert material."""

    def open_workbench_tab(self, tab_name: str) -> dict[str, Any]:
        """Open an existing workbench tab. This must not type or save text."""


@dataclass(slots=True)
class BuildPlanNonDestructiveActionResult:
    index: int
    operation_type: str | None
    operation_name: str | None
    action_type: str
    status: str
    summary: str
    scene_name: str | None = None
    layer_name: str | None = None
    tab_name: str | None = None
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class BuildPlanNonDestructiveResult:
    status: str
    ready_for_mutation: bool
    summary: str
    build_plan_code: str | None
    operation_count: int
    allowed_action_count: int
    blocked_mutation_count: int
    failure_count: int
    actions: list[BuildPlanNonDestructiveActionResult]


class BuildPlanNonDestructiveRunner:
    """Run only low-risk BuildPlan UI navigation after a green preflight.

    Allowed actions are intentionally narrow: select an already-existing scene,
    open a material tab, open the script workbench tab, and observe after each
    action. The runner never uploads/replaces assets, writes script content,
    saves drafts, or starts live streaming.
    """

    CATEGORY_TO_MATERIAL_TAB = {
        "background": "背景",
        "background_image": "背景",
        "floating_sticker": "装饰",
        "sticker": "装饰",
        "logo_title": "装饰",
        "decoration": "装饰",
        "digital_human": "数字分身",
        "product_video": "视频",
        "video": "视频",
        "text": "文本",
        "template": "模版",
    }

    def __init__(self, *, session: MaituNonDestructiveSession) -> None:
        self.session = session

    def run(
        self,
        operation_plan: dict[str, Any],
        preflight: BuildPlanPreflightResult,
    ) -> BuildPlanNonDestructiveResult:
        build_plan_code = operation_plan.get("build_plan_code")
        operations = operation_plan.get("operations") if isinstance(operation_plan.get("operations"), list) else []
        if not preflight.ready_to_execute:
            return BuildPlanNonDestructiveResult(
                status="blocked",
                ready_for_mutation=False,
                summary="BuildPlan non-destructive run blocked because preflight is not green.",
                build_plan_code=build_plan_code,
                operation_count=len(operations),
                allowed_action_count=0,
                blocked_mutation_count=0,
                failure_count=1,
                actions=[],
            )

        actions: list[BuildPlanNonDestructiveActionResult] = []
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                actions.append(
                    BuildPlanNonDestructiveActionResult(
                        index=index,
                        operation_type=None,
                        operation_name=None,
                        action_type="invalid_operation",
                        status="failed",
                        summary="Operation entry is not an object; refusing non-destructive run.",
                    )
                )
                continue
            actions.append(self._run_operation(index, operation))

        allowed_action_count = sum(1 for action in actions if action.status == "executed")
        blocked_mutation_count = sum(
            1
            for action in actions
            if action.operation_type
            in {
                "create_scene_from_template",
                "replace_layer_asset",
                "insert_template_component",
                "add_script_block",
                "save_live_room",
            }
        )
        failure_count = sum(1 for action in actions if action.status == "failed")
        status = "failed" if failure_count else "completed"
        return BuildPlanNonDestructiveResult(
            status=status,
            ready_for_mutation=False,
            summary=(
                f"BuildPlan non-destructive run {status}: {allowed_action_count} low-risk action(s), "
                f"{blocked_mutation_count} mutating operation(s) left blocked, {failure_count} failure(s)."
            ),
            build_plan_code=build_plan_code,
            operation_count=len(operations),
            allowed_action_count=allowed_action_count,
            blocked_mutation_count=blocked_mutation_count,
            failure_count=failure_count,
            actions=actions,
        )

    def _run_operation(self, index: int, operation: dict[str, Any]) -> BuildPlanNonDestructiveActionResult:
        operation_type = self._optional_string(operation.get("operation_type"))
        if operation_type in {"preflight_build_plan", "preflight_scene_build_plan"}:
            return BuildPlanNonDestructiveActionResult(
                index=index,
                operation_type=operation_type,
                operation_name=self._optional_string(operation.get("operation_name")),
                action_type="preflight_already_passed",
                status="skipped",
                summary="Preflight already passed; no UI action needed for this operation.",
            )
        if operation_type == "select_scene":
            return self._select_scene(index, operation)
        if operation_type == "create_scene_from_template":
            return BuildPlanNonDestructiveActionResult(
                index=index,
                operation_type=operation_type,
                operation_name=self._optional_string(operation.get("operation_name")),
                action_type="create_scene_from_template_blocked",
                status="blocked",
                summary="Scene creation remains blocked in non-destructive mode; no scene was created.",
                scene_name=self._optional_string(operation.get("scene_name")),
                details=operation.get("details") if isinstance(operation.get("details"), dict) else None,
            )
        if operation_type in {"replace_layer_asset", "insert_template_component"}:
            return self._open_material_tab_for_layer(index, operation)
        if operation_type == "add_script_block":
            return self._open_script_tab(index, operation)
        if operation_type == "save_live_room":
            return BuildPlanNonDestructiveActionResult(
                index=index,
                operation_type=operation_type,
                operation_name=self._optional_string(operation.get("operation_name")),
                action_type="save_live_room_blocked",
                status="blocked",
                summary="save_live_room remains blocked in non-destructive mode; no save click was executed.",
                details={"status": operation.get("status")},
            )
        return BuildPlanNonDestructiveActionResult(
            index=index,
            operation_type=operation_type,
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="unsupported_operation",
            status="failed",
            summary=f"Unsupported BuildPlan operation in non-destructive mode: {operation_type}",
        )

    def _select_scene(self, index: int, operation: dict[str, Any]) -> BuildPlanNonDestructiveActionResult:
        scene_name = self._optional_string(operation.get("scene_name"))
        if not scene_name:
            return self._missing_target(index, operation, "select_scene", "scene_name")
        try:
            click_result = self.session.select_scene(scene_name)
            state = self.session.read_current_state(open_if_needed=False)
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "select_scene", str(exc), scene_name=scene_name)
        return BuildPlanNonDestructiveActionResult(
            index=index,
            operation_type="select_scene",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="select_scene",
            status="executed",
            summary=f"Selected scene {scene_name} and re-observed current state without saving.",
            scene_name=scene_name,
            details={
                "click_result": click_result,
                "observed_active_scene_name": getattr(state, "active_scene_name", None),
            },
        )

    def _open_material_tab_for_layer(self, index: int, operation: dict[str, Any]) -> BuildPlanNonDestructiveActionResult:
        tab_name = self._material_tab_for_operation(operation)
        if not tab_name:
            operation_type = self._optional_string(operation.get("operation_type"))
            return BuildPlanNonDestructiveActionResult(
                index=index,
                operation_type=operation_type,
                operation_name=self._optional_string(operation.get("operation_name")),
                action_type=f"{operation_type or 'layer_operation'}_blocked",
                status="blocked",
                summary="Layer asset replacement remains blocked; no safe material tab could be inferred.",
                scene_name=self._optional_string(operation.get("scene_name")),
                layer_name=self._optional_string(operation.get("layer_name")),
                details={"required_category": operation.get("required_category")},
            )
        try:
            click_result = self.session.open_material_tab(tab_name)
            state = self.session.read_current_state(open_if_needed=False)
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "open_material_tab", str(exc), tab_name=tab_name)
        operation_type = self._optional_string(operation.get("operation_type"))
        return BuildPlanNonDestructiveActionResult(
            index=index,
            operation_type=operation_type,
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="open_material_tab",
            status="executed",
            summary=(
                f"Opened material tab {tab_name} for layer/component planning only; "
                "no asset upload/insert/replace was executed."
            ),
            scene_name=self._optional_string(operation.get("scene_name")),
            layer_name=self._optional_string(operation.get("layer_name")),
            tab_name=tab_name,
            details={
                "click_result": click_result,
                "observed_active_material_tab": getattr(state, "active_material_tab", None),
                "replacement_blocked": True,
            },
        )

    def _open_script_tab(self, index: int, operation: dict[str, Any]) -> BuildPlanNonDestructiveActionResult:
        tab_name = "直播脚本"
        try:
            click_result = self.session.open_workbench_tab(tab_name)
            state = self.session.read_current_state(open_if_needed=False)
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "open_workbench_tab", str(exc), tab_name=tab_name)
        return BuildPlanNonDestructiveActionResult(
            index=index,
            operation_type="add_script_block",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="open_workbench_tab",
            status="executed",
            summary="Opened 直播脚本 tab for inspection only; no script text was typed or saved.",
            scene_name=self._optional_string(operation.get("scene_name")),
            tab_name=tab_name,
            details={
                "click_result": click_result,
                "observed_active_workbench_tab": getattr(state, "active_workbench_tab", None),
                "script_write_blocked": True,
            },
        )

    def _material_tab_for_operation(self, operation: dict[str, Any]) -> str | None:
        required_category = self._optional_string(operation.get("required_category"))
        if required_category:
            mapped = self.CATEGORY_TO_MATERIAL_TAB.get(required_category)
            if mapped:
                return mapped
        accepted_asset_types = operation.get("accepted_asset_types") or []
        if isinstance(accepted_asset_types, list) and "VID" in accepted_asset_types:
            return "视频"
        if isinstance(accepted_asset_types, list) and "IMG" in accepted_asset_types:
            return "装饰"
        return None

    def _missing_target(
        self,
        index: int,
        operation: dict[str, Any],
        action_type: str,
        missing_field: str,
    ) -> BuildPlanNonDestructiveActionResult:
        return BuildPlanNonDestructiveActionResult(
            index=index,
            operation_type=self._optional_string(operation.get("operation_type")),
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type=action_type,
            status="failed",
            summary=f"Missing {missing_field}; refusing non-destructive action.",
            details={"missing_field": missing_field},
        )

    def _failed_action(
        self,
        index: int,
        operation: dict[str, Any],
        action_type: str,
        message: str,
        *,
        scene_name: str | None = None,
        tab_name: str | None = None,
    ) -> BuildPlanNonDestructiveActionResult:
        return BuildPlanNonDestructiveActionResult(
            index=index,
            operation_type=self._optional_string(operation.get("operation_type")),
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type=action_type,
            status="failed",
            summary=f"Non-destructive action failed: {message}",
            scene_name=scene_name,
            layer_name=self._optional_string(operation.get("layer_name")),
            tab_name=tab_name,
        )

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None


def build_non_destructive_execution_payload(result: BuildPlanNonDestructiveResult) -> dict[str, Any]:
    """Convert a non-destructive worker result into the backend execution-result payload."""
    execution_status = "completed" if result.status == "completed" else result.status
    payload: dict[str, Any] = {
        "executor": "browser_use",
        "execution_status": execution_status,
        "mode": "non_destructive",
        "retryable": False,
        "result_summary": result.summary,
        "operation_results": [_action_to_operation_result(action) for action in result.actions],
    }
    if result.status == "blocked":
        payload["failure_type"] = "preflight_not_green"
        if not payload["operation_results"]:
            payload["operation_results"] = [_synthetic_preflight_blocked_result(result)]
    elif result.status == "failed":
        payload["failure_type"] = "non_destructive_action_failed"
    return payload


def _action_to_operation_result(action: BuildPlanNonDestructiveActionResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation_index": action.index,
        "operation_type": action.operation_type or "unknown",
        "operation_name": action.operation_name,
        "scene_name": action.scene_name,
        "layer_name": action.layer_name,
        "action_type": action.action_type,
        "status": action.status,
        "retryable": False,
        "details": {**(action.details or {}), "summary": action.summary},
    }
    if action.status == "failed":
        payload["failure_type"] = "non_destructive_action_failed"
        payload["error_message"] = action.summary
    if action.status == "blocked":
        payload["failure_type"] = "mutation_blocked"
    return {key: value for key, value in payload.items() if value is not None}


def _synthetic_preflight_blocked_result(result: BuildPlanNonDestructiveResult) -> dict[str, Any]:
    return {
        "operation_index": 0,
        "operation_type": "preflight_build_plan",
        "operation_name": "BuildPlan preflight gate",
        "action_type": "preflight_gate",
        "status": "blocked",
        "failure_type": "preflight_not_green",
        "retryable": False,
        "error_message": result.summary,
        "details": {
            "ready_for_mutation": result.ready_for_mutation,
            "allowed_action_count": result.allowed_action_count,
            "blocked_mutation_count": result.blocked_mutation_count,
            "failure_count": result.failure_count,
        },
    }

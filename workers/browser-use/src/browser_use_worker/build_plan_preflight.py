from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class MaituCurrentStateSession(Protocol):
    def read_current_state(self, *, open_if_needed: bool = True) -> Any:
        """Return structured current Maitu state without mutating the UI."""


@dataclass(slots=True)
class BuildPlanPreflightCheck:
    name: str
    status: str
    summary: str
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class BuildPlanPreflightResult:
    status: str
    ready_to_execute: bool
    summary: str
    build_plan_code: str | None
    operation_count: int
    checks: list[BuildPlanPreflightCheck]
    failure_count: int
    warning_count: int
    skipped_count: int


class BuildPlanPreflight:
    """Read-only safety gate for Maitu live-room BuildPlans.

    This preflight validates the backend operation plan and current Maitu state.
    It never clicks, types, uploads, saves, or starts a live stream.
    """

    SUPPORTED_OPERATION_TYPES = {
        "preflight_build_plan",
        "select_scene",
        "replace_layer_asset",
        "add_script_block",
        "save_live_room",
    }

    def __init__(self, *, session: MaituCurrentStateSession | None, probe_browser: bool = True) -> None:
        self.session = session
        self.probe_browser = probe_browser

    def run(self, operation_plan: dict[str, Any]) -> BuildPlanPreflightResult:
        checks: list[BuildPlanPreflightCheck] = []
        operations = operation_plan.get("operations") or []
        build_plan_code = operation_plan.get("build_plan_code")

        if not isinstance(operations, list) or not operations:
            checks.append(
                BuildPlanPreflightCheck(
                    name="build_plan.operations",
                    status="fail",
                    summary="BuildPlan has no operation list to preflight.",
                    details={"build_plan_code": build_plan_code, "raw_type": type(operations).__name__},
                )
            )
        else:
            checks.append(
                BuildPlanPreflightCheck(
                    name="build_plan.operations",
                    status="pass",
                    summary=f"BuildPlan contains {len(operations)} operation(s).",
                    details={"build_plan_code": build_plan_code, "operation_count": len(operations)},
                )
            )
            for index, operation in enumerate(operations):
                if not isinstance(operation, dict):
                    checks.append(
                        BuildPlanPreflightCheck(
                            name=f"operation[{index}]",
                            status="fail",
                            summary="Operation entry is not an object.",
                            details={"raw_type": type(operation).__name__},
                        )
                    )
                    continue
                self._check_operation_shape(index, operation, checks)

        state = self._read_current_state(checks)
        if state is not None and isinstance(operations, list):
            self._check_current_state(operation_plan, operations, state, checks)

        return self._finalize(build_plan_code, len(operations) if isinstance(operations, list) else 0, checks)

    def _check_operation_shape(self, index: int, operation: dict[str, Any], checks: list[BuildPlanPreflightCheck]) -> None:
        operation_type = str(operation.get("operation_type") or "")
        operation_name = f"operation[{index}]"
        if not operation_type:
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"{operation_name}.operation_type",
                    status="fail",
                    summary="Operation is missing operation_type.",
                )
            )
            return
        if operation_type not in self.SUPPORTED_OPERATION_TYPES:
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"{operation_name}.operation_type",
                    status="fail",
                    summary=f"Operation type {operation_type} is not supported by the BuildPlan preflight gate.",
                    details={"operation_type": operation_type},
                )
            )
            return
        checks.append(
            BuildPlanPreflightCheck(
                name=f"{operation_name}.operation_type",
                status="pass",
                summary=f"Operation type {operation_type} is supported.",
                details={"operation_type": operation_type},
            )
        )

        instruction = str(operation.get("instruction") or "")
        if self._unsafe_go_live_instruction(instruction):
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"{operation_name}.go_live_safety",
                    status="fail",
                    summary="Operation instruction appears to click/go live; BuildPlan execution must never start live streaming by default.",
                    details={"instruction": instruction},
                )
            )

        if operation_type == "save_live_room" and operation.get("status") != "manual_review":
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"{operation_name}.save_live_room_manual_review",
                    status="fail",
                    summary="save_live_room must remain manual_review until all prior operations and screenshots are verified.",
                    details={"status": operation.get("status")},
                )
            )
        if operation_type == "replace_layer_asset":
            missing = [field for field in ("scene_name", "layer_name", "replacement_policy") if not operation.get(field)]
            if missing:
                checks.append(
                    BuildPlanPreflightCheck(
                        name=f"{operation_name}.required_fields",
                        status="fail",
                        summary="Layer operation is missing fields required for safe targeting.",
                        details={"missing_fields": missing},
                    )
                )
        if operation_type == "add_script_block":
            missing = [field for field in ("scene_name", "script_block_content") if not operation.get(field)]
            if missing:
                checks.append(
                    BuildPlanPreflightCheck(
                        name=f"{operation_name}.required_fields",
                        status="fail",
                        summary="Script operation is missing fields required for safe targeting.",
                        details={"missing_fields": missing},
                    )
                )

    def _read_current_state(self, checks: list[BuildPlanPreflightCheck]) -> Any | None:
        if not self.probe_browser:
            checks.append(
                BuildPlanPreflightCheck(
                    name="maitu_current_state_probe",
                    status="skipped",
                    summary="Browser current-state probe was skipped by configuration.",
                )
            )
            return None
        if self.session is None:
            checks.append(
                BuildPlanPreflightCheck(
                    name="maitu_current_state_probe",
                    status="skipped",
                    summary="No Browser-use current-state session was provided.",
                )
            )
            return None
        try:
            state = self.session.read_current_state(open_if_needed=True)
        except Exception as exc:  # pragma: no cover - runtime boundary
            checks.append(
                BuildPlanPreflightCheck(
                    name="maitu_current_state_probe",
                    status="fail",
                    summary=f"Browser-use current-state probe failed: {exc}",
                )
            )
            return None
        checks.append(
            BuildPlanPreflightCheck(
                name="maitu_current_state_probe",
                status="pass",
                summary="Browser-use returned structured current Maitu state.",
                details={
                    "live_room_id": getattr(state, "live_room_id", None),
                    "active_scene_name": getattr(state, "active_scene_name", None),
                },
            )
        )
        return state

    def _check_current_state(
        self,
        operation_plan: dict[str, Any],
        operations: list[Any],
        state: Any,
        checks: list[BuildPlanPreflightCheck],
    ) -> None:
        if bool(getattr(state, "login_required", False)):
            checks.append(
                BuildPlanPreflightCheck(
                    name="maitu_login_state",
                    status="fail",
                    summary="Maitu login page is visible; manual login is required before BuildPlan execution.",
                )
            )
            return
        if not bool(getattr(state, "logged_in", False)):
            checks.append(
                BuildPlanPreflightCheck(
                    name="maitu_login_state",
                    status="fail",
                    summary="Current Maitu state is not logged in; refusing BuildPlan execution.",
                )
            )
            return
        checks.append(BuildPlanPreflightCheck(name="maitu_login_state", status="pass", summary="Current Maitu state is logged in."))

        expected_room_id = operation_plan.get("reference_room_id") or operation_plan.get("live_room_id")
        current_room_id = getattr(state, "live_room_id", None)
        if expected_room_id:
            if str(expected_room_id) == str(current_room_id):
                checks.append(
                    BuildPlanPreflightCheck(
                        name="maitu_live_room_id",
                        status="pass",
                        summary="Current live room id matches the BuildPlan target.",
                        details={"expected_room_id": expected_room_id, "current_room_id": current_room_id},
                    )
                )
            else:
                checks.append(
                    BuildPlanPreflightCheck(
                        name="maitu_live_room_id",
                        status="fail",
                        summary="Current live room id does not match the BuildPlan target.",
                        details={"expected_room_id": expected_room_id, "current_room_id": current_room_id},
                    )
                )
        else:
            checks.append(
                BuildPlanPreflightCheck(
                    name="maitu_live_room_id",
                    status="warning",
                    summary="BuildPlan operation plan does not include a target live room id; preflight cannot verify room identity.",
                    details={"current_room_id": current_room_id},
                )
            )

        scene_names = {self._name(item) for item in (getattr(state, "scenes", None) or []) if self._name(item)}
        active_scene_name = getattr(state, "active_scene_name", None)
        for scene_name in self._operation_scene_names(operations):
            if scene_name in scene_names:
                checks.append(
                    BuildPlanPreflightCheck(
                        name=f"scene[{scene_name}].exists",
                        status="pass",
                        summary="BuildPlan scene exists in current Maitu state.",
                        details={"scene_name": scene_name},
                    )
                )
            elif scene_names:
                checks.append(
                    BuildPlanPreflightCheck(
                        name=f"scene[{scene_name}].exists",
                        status="fail",
                        summary="BuildPlan scene is missing from current Maitu state.",
                        details={"scene_name": scene_name, "available_scenes": sorted(scene_names)},
                    )
                )
            else:
                checks.append(
                    BuildPlanPreflightCheck(
                        name=f"scene[{scene_name}].exists",
                        status="warning",
                        summary="Current Maitu state did not expose scene names; executor must verify before mutation.",
                        details={"scene_name": scene_name},
                    )
                )

        active_layer_names = {self._name(item) for item in (getattr(state, "layers", None) or []) if self._name(item)}
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                continue
            operation_type = operation.get("operation_type")
            if operation_type == "replace_layer_asset":
                self._check_layer_visibility(index, operation, active_scene_name, active_layer_names, checks)
            elif operation_type == "add_script_block":
                self._check_script_panel(index, state, checks)

    def _check_layer_visibility(
        self,
        index: int,
        operation: dict[str, Any],
        active_scene_name: str | None,
        active_layer_names: set[str],
        checks: list[BuildPlanPreflightCheck],
    ) -> None:
        scene_name = operation.get("scene_name")
        layer_name = operation.get("layer_name")
        if not layer_name:
            return
        if scene_name != active_scene_name:
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"operation[{index}].inactive_scene_layer_visibility",
                    status="warning",
                    summary="Layer belongs to a non-active scene; worker must select that scene and re-observe before mutation.",
                    details={"scene_name": scene_name, "active_scene_name": active_scene_name, "layer_name": layer_name},
                )
            )
            return
        if layer_name in active_layer_names:
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"operation[{index}].active_scene_layer_visibility",
                    status="pass",
                    summary="Target layer is visible in the active scene state.",
                    details={"scene_name": scene_name, "layer_name": layer_name},
                )
            )
            return
        checks.append(
            BuildPlanPreflightCheck(
                name=f"operation[{index}].active_scene_layer_visibility",
                status="fail",
                summary="Target layer is missing from the active scene state; refusing unattended mutation.",
                details={"scene_name": scene_name, "layer_name": layer_name, "active_layers": sorted(active_layer_names)},
            )
        )

    def _check_script_panel(self, index: int, state: Any, checks: list[BuildPlanPreflightCheck]) -> None:
        tab_names = {self._name(item) for item in (getattr(state, "workbench_tabs", None) or []) if self._name(item)}
        if not tab_names:
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"operation[{index}].script_panel_visibility",
                    status="warning",
                    summary="Current Maitu state did not expose workbench tabs; script panel must be verified before writing.",
                )
            )
            return
        if "直播脚本" in tab_names:
            checks.append(
                BuildPlanPreflightCheck(
                    name=f"operation[{index}].script_panel_visibility",
                    status="pass",
                    summary="直播脚本 workbench tab is available for script operation.",
                )
            )
            return
        checks.append(
            BuildPlanPreflightCheck(
                name=f"operation[{index}].script_panel_visibility",
                status="fail",
                summary="直播脚本 workbench tab is missing; refusing unattended script write.",
                details={"available_workbench_tabs": sorted(tab_names)},
            )
        )

    @staticmethod
    def _operation_scene_names(operations: list[Any]) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            scene_name = operation.get("scene_name")
            if scene_name and scene_name not in seen:
                names.append(str(scene_name))
                seen.add(str(scene_name))
        return names

    @staticmethod
    def _name(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("name") or item.get("scene_name") or "").strip()
        return str(getattr(item, "name", "") or "").strip()

    @staticmethod
    def _unsafe_go_live_instruction(instruction: str) -> bool:
        if "正式开播" not in instruction and "开播" not in instruction:
            return False
        safe_phrases = ("不点击正式开播", "默认不点击正式开播", "不要点击正式开播", "不允许点击正式开播")
        return not any(phrase in instruction for phrase in safe_phrases)

    @staticmethod
    def _finalize(
        build_plan_code: str | None,
        operation_count: int,
        checks: list[BuildPlanPreflightCheck],
    ) -> BuildPlanPreflightResult:
        failure_count = sum(1 for check in checks if check.status == "fail")
        warning_count = sum(1 for check in checks if check.status == "warning")
        skipped_count = sum(1 for check in checks if check.status == "skipped")
        if failure_count:
            status = "failed"
        elif warning_count or skipped_count:
            status = "warning"
        else:
            status = "passed"
        ready_to_execute = status == "passed"
        pass_count = sum(1 for check in checks if check.status == "pass")
        summary = (
            f"BuildPlan preflight {status}: {pass_count} passed, {warning_count} warning(s), "
            f"{failure_count} failure(s), {skipped_count} skipped."
        )
        return BuildPlanPreflightResult(
            status=status,
            ready_to_execute=ready_to_execute,
            summary=summary,
            build_plan_code=build_plan_code,
            operation_count=operation_count,
            checks=checks,
            failure_count=failure_count,
            warning_count=warning_count,
            skipped_count=skipped_count,
        )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BuildPlanDryRunOperation:
    index: int
    sort_order: int | None
    operation_type: str | None
    operation_name: str | None
    status: str | None
    safe_action: str
    scene_name: str | None = None
    layer_name: str | None = None
    replacement_policy: str | None = None
    script_block_code: str | None = None
    script_preview: str | None = None
    instruction: str | None = None
    safety_notes: list[str] | None = None


@dataclass(slots=True)
class BuildPlanDryRunResult:
    status: str
    ready_to_execute: bool
    summary: str
    build_plan_code: str | None
    blueprint_code: str | None
    reference_room_id: str | None
    reference_room_name: str | None
    operation_count: int
    planned_mutation_count: int
    manual_review_count: int
    safety_violation_count: int
    operations: list[BuildPlanDryRunOperation]


class BuildPlanDryRun:
    """Render a Maitu BuildPlan into a safe, non-mutating operation summary.

    This class is intentionally pure: it does not open Browser-use, click Maitu,
    upload assets, write scripts, save drafts, or start live streaming.
    """

    SUPPORTED_OPERATION_TYPES = {
        "preflight_build_plan",
        "select_scene",
        "replace_layer_asset",
        "add_script_block",
        "save_live_room",
    }

    def run(self, operation_plan: dict[str, Any]) -> BuildPlanDryRunResult:
        raw_operations = operation_plan.get("operations") or []
        operations = raw_operations if isinstance(raw_operations, list) else []
        rendered = [self._render_operation(index, operation) for index, operation in enumerate(operations)]
        safety_violation_count = sum(len(item.safety_notes or []) for item in rendered)
        planned_mutation_count = sum(
            1
            for item in rendered
            if item.safe_action in {"planned_layer_asset_replacement_not_executed", "planned_script_block_not_executed"}
        )
        manual_review_count = sum(1 for item in rendered if item.safe_action == "manual_review_save_not_executed")

        if not isinstance(raw_operations, list):
            safety_violation_count += 1
        elif not raw_operations:
            safety_violation_count += 1

        status = "failed" if safety_violation_count else "dry_run"
        if status == "failed":
            summary = (
                f"BuildPlan dry run found {safety_violation_count} safety issue(s); "
                "no Browser-use actions were executed."
            )
        else:
            summary = (
                f"BuildPlan dry run would render {len(rendered)} operation(s); "
                "no Browser-use actions were executed."
            )

        return BuildPlanDryRunResult(
            status=status,
            ready_to_execute=False,
            summary=summary,
            build_plan_code=operation_plan.get("build_plan_code"),
            blueprint_code=operation_plan.get("blueprint_code"),
            reference_room_id=operation_plan.get("reference_room_id"),
            reference_room_name=operation_plan.get("reference_room_name"),
            operation_count=len(rendered),
            planned_mutation_count=planned_mutation_count,
            manual_review_count=manual_review_count,
            safety_violation_count=safety_violation_count,
            operations=rendered,
        )

    def _render_operation(self, index: int, operation: Any) -> BuildPlanDryRunOperation:
        if not isinstance(operation, dict):
            return BuildPlanDryRunOperation(
                index=index,
                sort_order=None,
                operation_type=None,
                operation_name=None,
                status=None,
                safe_action="invalid_operation_not_executed",
                safety_notes=["Operation entry is not an object."],
            )

        operation_type = self._optional_string(operation.get("operation_type"))
        status = self._optional_string(operation.get("status"))
        instruction = self._optional_string(operation.get("instruction"))
        safe_action = self._safe_action(operation_type=operation_type, status=status)
        safety_notes = self._safety_notes(operation_type=operation_type, status=status, instruction=instruction)

        return BuildPlanDryRunOperation(
            index=index,
            sort_order=self._optional_int(operation.get("sort_order")),
            operation_type=operation_type,
            operation_name=self._optional_string(operation.get("operation_name")),
            status=status,
            safe_action=safe_action,
            scene_name=self._optional_string(operation.get("scene_name")),
            layer_name=self._optional_string(operation.get("layer_name")),
            replacement_policy=self._optional_string(operation.get("replacement_policy")),
            script_block_code=self._optional_string(operation.get("script_block_code")),
            script_preview=self._preview(operation.get("script_block_content")),
            instruction=instruction,
            safety_notes=safety_notes,
        )

    def _safe_action(self, *, operation_type: str | None, status: str | None) -> str:
        if operation_type == "preflight_build_plan":
            return "read_only_preflight"
        if operation_type == "select_scene":
            return "read_only_select_scene"
        if operation_type == "replace_layer_asset":
            return "planned_layer_asset_replacement_not_executed"
        if operation_type == "add_script_block":
            return "planned_script_block_not_executed"
        if operation_type == "save_live_room":
            if status == "manual_review":
                return "manual_review_save_not_executed"
            return "unsafe_save_not_executed"
        return "unsupported_operation_not_executed"

    def _safety_notes(self, *, operation_type: str | None, status: str | None, instruction: str | None) -> list[str]:
        notes: list[str] = []
        if not operation_type:
            notes.append("Operation is missing operation_type.")
        elif operation_type not in self.SUPPORTED_OPERATION_TYPES:
            notes.append(f"Operation type {operation_type} is not supported by BuildPlan dry-run.")
        if operation_type == "save_live_room" and status != "manual_review":
            notes.append("save_live_room must remain manual_review in dry-run/build phases.")
        if instruction and self._unsafe_go_live_instruction(instruction):
            notes.append("Operation instruction appears to start live streaming.")
        return notes

    @staticmethod
    def _unsafe_go_live_instruction(instruction: str) -> bool:
        normalized = instruction.replace(" ", "")
        safe_negations = ("不点击正式开播", "默认不点击正式开播", "不要点击正式开播", "禁止点击正式开播")
        if any(phrase in normalized for phrase in safe_negations):
            return False
        unsafe_phrases = ("点击正式开播", "正式开播", "开始直播", "开播")
        return any(phrase in normalized for phrase in unsafe_phrases)

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _preview(value: Any, *, limit: int = 80) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit - 1]}…"

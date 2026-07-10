from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class MaituLiveSceneFillSession(Protocol):
    def read_live_room(self, live_room_id: str) -> dict[str, Any]:
        """Read a Maitu live room through the authenticated browser context."""

    def rename_clip(self, clip_id: int, name: str) -> dict[str, Any]:
        """Rename a target clip/scene without clicking go-live."""

    def fill_clip_from_template(
        self,
        *,
        live_room_id: str,
        target_clip_id: int,
        reference_room_id: str,
        reference_clip_id: str,
        scene_name: str,
        component_operations: list[dict[str, Any]],
        script_content: str | None,
    ) -> dict[str, Any]:
        """Fill target clip from a reference template clip and return verification details."""


@dataclass(slots=True)
class LiveSceneFillActionResult:
    operation_index: int
    operation_type: str
    operation_name: str | None
    action_type: str
    status: str
    summary: str
    scene_name: str | None = None
    layer_name: str | None = None
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class LiveSceneFillResult:
    status: str
    build_plan_code: str | None
    target_live_room_id: str
    target_clip_id: int | None
    target_scene_name: str | None
    visual_count: int
    text_count: int
    action_count: int
    failure_count: int
    summary: str
    actions: list[LiveSceneFillActionResult]


class LiveSceneFillRunner:
    """Mutating, draft-only single-scene fill runner.

    This runner intentionally maps the first planned scene onto the room's
    existing default clip. It does not click or authorize 正式开播.
    """

    def __init__(self, *, session: MaituLiveSceneFillSession) -> None:
        self.session = session

    def run(self, operation_plan: dict[str, Any], *, target_live_room_id: str) -> LiveSceneFillResult:
        operations = operation_plan.get("operations") if isinstance(operation_plan.get("operations"), list) else []
        build_plan_code = self._optional_string(operation_plan.get("build_plan_code"))
        reference_room_id = self._optional_string(operation_plan.get("reference_room_id"))
        actions: list[LiveSceneFillActionResult] = []
        scene_operation = self._first_operation(operations, "create_scene_from_template")
        if scene_operation is None:
            return self._failed_result(build_plan_code, target_live_room_id, actions, "Missing create_scene_from_template operation.")
        scene_name = self._optional_string(scene_operation.get("scene_name"))
        reference_clip_id = self._optional_string((scene_operation.get("details") or {}).get("reference_clip_id"))
        if not scene_name or not reference_room_id or not reference_clip_id:
            return self._failed_result(
                build_plan_code,
                target_live_room_id,
                actions,
                "BuildPlan is missing scene_name, reference_room_id, or reference_clip_id.",
            )

        preflight_operation = self._first_operation(operations, "preflight_scene_build_plan") or self._first_operation(operations, "preflight_build_plan")
        if preflight_operation:
            actions.append(
                LiveSceneFillActionResult(
                    operation_index=operations.index(preflight_operation),
                    operation_type=self._optional_string(preflight_operation.get("operation_type")) or "preflight_scene_build_plan",
                    operation_name=self._optional_string(preflight_operation.get("operation_name")),
                    action_type="preflight_already_passed",
                    status="skipped",
                    summary="Live scene fill assumes preflight was already reviewed before mutation.",
                    details={"go_live_clicked": False},
                )
            )

        room = self.session.read_live_room(target_live_room_id)
        default_clip = self._default_clip(room)
        if default_clip is None:
            return self._failed_result(build_plan_code, target_live_room_id, actions, "Target room has no default clip to fill.")
        target_clip_id = int(default_clip["id"])

        scene_index = operations.index(scene_operation)
        rename_result = self.session.rename_clip(target_clip_id, scene_name)
        actions.append(
            LiveSceneFillActionResult(
                operation_index=scene_index,
                operation_type="create_scene_from_template",
                operation_name=self._optional_string(scene_operation.get("operation_name")),
                action_type="map_first_planned_scene_to_default_clip",
                status="completed",
                summary="Mapped first planned scene to the existing default clip and renamed it; no new scene was created.",
                scene_name=scene_name,
                details={
                    "target_live_room_id": target_live_room_id,
                    "target_clip_id": target_clip_id,
                    "previous_clip_name": default_clip.get("name"),
                    "rename_result": rename_result,
                    "go_live_clicked": False,
                },
            )
        )

        component_operations = [operation for operation in operations if operation.get("operation_type") == "insert_template_component"]
        script_operation = self._first_operation(operations, "add_script_block")
        script_content = self._optional_string(script_operation.get("script_block_content")) if script_operation else None
        fill_details = self.session.fill_clip_from_template(
            live_room_id=target_live_room_id,
            target_clip_id=target_clip_id,
            reference_room_id=reference_room_id,
            reference_clip_id=reference_clip_id,
            scene_name=scene_name,
            component_operations=component_operations,
            script_content=script_content,
        )

        for operation in component_operations:
            actions.append(
                LiveSceneFillActionResult(
                    operation_index=operations.index(operation),
                    operation_type="insert_template_component",
                    operation_name=self._optional_string(operation.get("operation_name")),
                    action_type="maitu_api_replace_clip_materials_cumulative",
                    status="completed",
                    summary="Inserted template component into the target clip with cumulative API verification.",
                    scene_name=self._optional_string(operation.get("scene_name")),
                    layer_name=self._optional_string(operation.get("layer_name")),
                    details={
                        "target_live_room_id": target_live_room_id,
                        "target_clip_id": target_clip_id,
                        "reference_clip_id": reference_clip_id,
                        "component_template_code": (operation.get("details") or {}).get("component_template_code"),
                        "expected_material_id": (operation.get("details") or {}).get("material_id"),
                        "go_live_clicked": False,
                    },
                )
            )
        if script_operation:
            actions.append(
                LiveSceneFillActionResult(
                    operation_index=operations.index(script_operation),
                    operation_type="add_script_block",
                    operation_name=self._optional_string(script_operation.get("operation_name")),
                    action_type="maitu_api_create_text_clip_material",
                    status="completed",
                    summary="Inserted script text into the target clip.",
                    scene_name=self._optional_string(script_operation.get("scene_name")),
                    details={
                        "target_live_room_id": target_live_room_id,
                        "target_clip_id": target_clip_id,
                        "script_length": len(script_content or ""),
                        "go_live_clicked": False,
                    },
                )
            )
        save_operation = self._first_operation(operations, "save_live_room")
        if save_operation:
            actions.append(
                LiveSceneFillActionResult(
                    operation_index=operations.index(save_operation),
                    operation_type="save_live_room",
                    operation_name=self._optional_string(save_operation.get("operation_name")),
                    action_type="manual_review_save_not_clicked",
                    status="skipped",
                    summary="save_live_room remains manual review; no save/go-live button was clicked.",
                    scene_name=self._optional_string(save_operation.get("scene_name")),
                    details={
                        "target_live_room_id": target_live_room_id,
                        "target_clip_id": target_clip_id,
                        "build_plan_status": save_operation.get("status"),
                        "go_live_clicked": False,
                    },
                )
            )

        visual_count = int(fill_details.get("visual_count") or len(component_operations))
        text_count = int(fill_details.get("text_count") or (1 if script_content else 0))
        failure_count = sum(1 for action in actions if action.status == "failed")
        status = "failed" if failure_count else "completed"
        return LiveSceneFillResult(
            status=status,
            build_plan_code=build_plan_code,
            target_live_room_id=target_live_room_id,
            target_clip_id=target_clip_id,
            target_scene_name=scene_name,
            visual_count=visual_count,
            text_count=text_count,
            action_count=len(actions),
            failure_count=failure_count,
            summary=(
                f"Live scene fill {status}: target clip {target_clip_id}, "
                f"{visual_count} visual component(s), {text_count} script block(s); go-live not clicked."
            ),
            actions=actions,
        )

    def _failed_result(
        self,
        build_plan_code: str | None,
        target_live_room_id: str,
        actions: list[LiveSceneFillActionResult],
        message: str,
    ) -> LiveSceneFillResult:
        return LiveSceneFillResult(
            status="failed",
            build_plan_code=build_plan_code,
            target_live_room_id=target_live_room_id,
            target_clip_id=None,
            target_scene_name=None,
            visual_count=0,
            text_count=0,
            action_count=len(actions),
            failure_count=1,
            summary=message,
            actions=actions,
        )

    @staticmethod
    def _first_operation(operations: list[dict[str, Any]], operation_type: str) -> dict[str, Any] | None:
        return next((operation for operation in operations if operation.get("operation_type") == operation_type), None)

    @staticmethod
    def _default_clip(room: dict[str, Any]) -> dict[str, Any] | None:
        topics = room.get("topics") if isinstance(room.get("topics"), list) else []
        clips: list[dict[str, Any]] = []
        for topic in topics:
            if isinstance(topic, dict) and isinstance(topic.get("clips"), list):
                clips.extend(clip for clip in topic["clips"] if isinstance(clip, dict) and clip.get("id") is not None)
        if not clips:
            return None
        return sorted(clips, key=lambda clip: int(clip.get("order_num") or 0))[0]

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None


def build_live_scene_fill_execution_payload(result: LiveSceneFillResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "executor": "browser_use",
        "execution_status": "completed" if result.status == "completed" else result.status,
        "mode": "live_scene_fill",
        "retryable": False,
        "result_summary": result.summary,
        "operation_results": [_action_to_operation_result(action) for action in result.actions],
    }
    if result.status == "failed":
        payload["failure_type"] = "live_scene_fill_failed"
        payload["error_message"] = result.summary
    return payload


def _action_to_operation_result(action: LiveSceneFillActionResult) -> dict[str, Any]:
    row: dict[str, Any] = {
        "operation_index": action.operation_index,
        "operation_type": action.operation_type,
        "operation_name": action.operation_name,
        "scene_name": action.scene_name,
        "layer_name": action.layer_name,
        "action_type": action.action_type,
        "status": action.status,
        "retryable": False,
        "details": {**(action.details or {}), "summary": action.summary},
    }
    if action.status == "failed":
        row["failure_type"] = "live_scene_fill_action_failed"
        row["error_message"] = action.summary
    return {key: value for key, value in row.items() if value is not None}

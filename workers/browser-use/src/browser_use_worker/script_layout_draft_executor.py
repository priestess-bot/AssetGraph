from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class MaituScriptLayoutDraftSession(Protocol):
    def read_live_room(self, live_room_id: str) -> dict[str, Any]:
        """Read the target Maitu live room draft."""

    def rename_clip(self, *, live_room_id: str, clip_id: int, name: str) -> dict[str, Any]:
        """Rename an existing clip/scene without clicking go-live."""

    def create_scene(self, *, live_room_id: str, scene_name: str, scene_index: int) -> dict[str, Any]:
        """Create a new draft scene/clip after the default first scene."""

    def insert_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict[str, Any]) -> dict[str, Any]:
        """Insert a selected asset layer into the target draft clip."""

    def position_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict[str, Any]) -> dict[str, Any]:
        """Apply the planned geometry for a previously inserted layer."""

    def write_script(self, *, live_room_id: str, clip_id: int, scene_name: str, script_text: str) -> dict[str, Any]:
        """Write the scene script into the target draft clip."""

    def verify_scene(self, *, live_room_id: str, clip_id: int, scene_name: str, operation: dict[str, Any]) -> dict[str, Any]:
        """Read back the draft scene after content operations."""


@dataclass(slots=True)
class ScriptLayoutDraftActionResult:
    operation_index: int
    operation_type: str | None
    operation_name: str | None
    action_type: str
    status: str
    summary: str
    scene_index: int | None = None
    scene_name: str | None = None
    clip_id: int | None = None
    layer_id: str | None = None
    layer_type: str | None = None
    asset_code: str | None = None
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class ScriptLayoutDraftResult:
    status: str
    target_live_room_id: str | None
    ready_for_go_live: bool
    manual_review_required: bool
    summary: str
    operation_count: int
    executed_action_count: int
    skipped_action_count: int
    placeholder_count: int
    failure_count: int
    actions: list[ScriptLayoutDraftActionResult]


class ScriptLayoutDraftCheckpointStore(Protocol):
    def begin_operation(self, operation_index: int, operation: dict[str, Any]) -> dict[str, Any]:
        """Return an execute/skip/reconcile decision before any operation side effect."""

    def dispatch_operation(self, operation_index: int, operation: dict[str, Any]) -> dict[str, Any]:
        """Persist the mutating dispatched boundary immediately before the external call."""

    def invalidate_operation(
        self,
        operation_index: int,
        operation: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Move stale completed evidence into reconcile_required under the active fence."""

    def complete_operation(
        self,
        operation_index: int,
        operation: dict[str, Any],
        action: ScriptLayoutDraftActionResult,
    ) -> dict[str, Any]:
        """Persist verified completion evidence idempotently."""


class ScriptLayoutDraftRunner:
    """Execute a content-driven layout BuildPlan into a safe Maitu draft.

    The runner deliberately keeps the final go-live gate closed. It may mutate a
    draft room (rename/create draft scenes, insert/position ready layers, write
    scripts) through the injected session, but it never clicks 正式开播 and it
    never treats placeholders as real assets.
    """

    SUPPORTED_OPERATION_TYPES = frozenset(
        {
            "preflight_content_build_plan",
            "fill_default_scene",
            "create_scene",
            "insert_asset_layer",
            "position_asset_layer",
            "placeholder_required",
            "write_script",
            "verify_scene",
            "save_draft",
        }
    )

    def __init__(
        self,
        *,
        session: MaituScriptLayoutDraftSession,
        checkpoint_store: ScriptLayoutDraftCheckpointStore | None = None,
    ) -> None:
        self.session = session
        self.checkpoint_store = checkpoint_store
        self._room_cache: dict[str, Any] | None = None
        self._clip_ids_by_scene: dict[int, int] = {}
        self._material_ids_by_layer: dict[tuple[int | None, str], int] = {}

    def run(self, operation_plan: dict[str, Any], *, target_live_room_id: str | None = None) -> ScriptLayoutDraftResult:
        self._room_cache = None
        self._clip_ids_by_scene.clear()
        self._material_ids_by_layer.clear()
        plan_status = self._optional_string(operation_plan.get("status"))
        operations = operation_plan.get("operations") if isinstance(operation_plan.get("operations"), list) else []
        plan_live_room_id = self._optional_string(operation_plan.get("target_live_room_id"))
        requested_live_room_id = self._optional_string(target_live_room_id)
        if plan_live_room_id and requested_live_room_id and plan_live_room_id != requested_live_room_id:
            return ScriptLayoutDraftResult(
                status="failed",
                target_live_room_id=requested_live_room_id,
                ready_for_go_live=False,
                manual_review_required=True,
                summary=(
                    f"Requested target live room {requested_live_room_id} does not match "
                    f"the BuildPlan target {plan_live_room_id}."
                ),
                operation_count=len(operations),
                executed_action_count=0,
                skipped_action_count=0,
                placeholder_count=0,
                failure_count=1,
                actions=[],
            )
        live_room_id = requested_live_room_id or plan_live_room_id
        if plan_status == "blocked_missing_required_assets":
            return ScriptLayoutDraftResult(
                status="blocked",
                target_live_room_id=live_room_id,
                ready_for_go_live=False,
                manual_review_required=True,
                summary="Script layout draft run blocked because upstream layout BuildPlan is blocked.",
                operation_count=len(operations),
                executed_action_count=0,
                skipped_action_count=0,
                placeholder_count=0,
                failure_count=0,
                actions=[],
            )
        if not live_room_id:
            return ScriptLayoutDraftResult(
                status="failed",
                target_live_room_id=None,
                ready_for_go_live=False,
                manual_review_required=True,
                summary="Script layout draft run failed: missing target_live_room_id.",
                operation_count=len(operations),
                executed_action_count=0,
                skipped_action_count=0,
                placeholder_count=0,
                failure_count=1,
                actions=[],
            )
        unsupported_operation_types = [
            operation.get("operation_type") if isinstance(operation, dict) else None
            for operation in operations
            if not isinstance(operation, dict)
            or operation.get("operation_type") not in self.SUPPORTED_OPERATION_TYPES
        ]
        if unsupported_operation_types:
            return ScriptLayoutDraftResult(
                status="failed",
                target_live_room_id=live_room_id,
                ready_for_go_live=False,
                manual_review_required=True,
                summary=f"Unsupported script-layout draft operation type(s): {unsupported_operation_types}",
                operation_count=len(operations),
                executed_action_count=0,
                skipped_action_count=0,
                placeholder_count=0,
                failure_count=1,
                actions=[],
            )
        first_operation = operations[0] if operations else None
        preflight_room_id = (
            self._optional_string(first_operation.get("target_live_room_id"))
            if isinstance(first_operation, dict)
            else None
        )
        if (
            not isinstance(first_operation, dict)
            or first_operation.get("operation_type") != "preflight_content_build_plan"
            or first_operation.get("status") != "ready"
            or (preflight_room_id is not None and preflight_room_id != live_room_id)
        ):
            return ScriptLayoutDraftResult(
                status="failed",
                target_live_room_id=live_room_id,
                ready_for_go_live=False,
                manual_review_required=True,
                summary=(
                    "Script layout draft requires the first operation to be a ready "
                    "preflight_content_build_plan bound to the target room."
                ),
                operation_count=len(operations),
                executed_action_count=0,
                skipped_action_count=0,
                placeholder_count=0,
                failure_count=1,
                actions=[],
            )

        actions: list[ScriptLayoutDraftActionResult] = []
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                actions.append(
                    ScriptLayoutDraftActionResult(
                        operation_index=index,
                        operation_type=None,
                        operation_name=None,
                        action_type="invalid_operation",
                        status="failed",
                        summary="Operation entry is not an object; refusing to execute it.",
                    )
                )
                break
            checkpoint: dict[str, Any] | None = None
            if self.checkpoint_store is not None:
                try:
                    checkpoint = self.checkpoint_store.begin_operation(index, operation)
                except Exception as exc:  # pragma: no cover - runtime boundary
                    actions.append(
                        self._failed_action(
                            index,
                            operation,
                            "checkpoint_begin",
                            f"checkpoint begin failed before side effect: {exc}",
                        )
                    )
                    break
                decision = self._optional_string(checkpoint.get("decision"))
                frozen_intent = checkpoint.get("intent_snapshot")
                if frozen_intent is None:
                    frozen_intent = operation
                if not isinstance(frozen_intent, dict):
                    actions.append(
                        self._failed_action(
                            index,
                            operation,
                            "checkpoint_manifest",
                            "checkpoint response omitted the backend-frozen operation intent",
                        )
                    )
                    break
                operation = frozen_intent
                if decision == "reconcile":
                    actions.append(
                        self._failed_action(
                            index,
                            operation,
                            "checkpoint_reconcile_required",
                            "operation has uncertain prior side effects; reconcile authoritative Maitu state before retry",
                        )
                    )
                    break
                if decision == "skip" and operation.get("operation_type") not in {
                    "preflight_content_build_plan",
                    "verify_scene",
                }:
                    if checkpoint.get("effect_class") == "mutating" and not self._checkpoint_evidence_matches_room(
                        live_room_id,
                        operation,
                        checkpoint,
                    ):
                        try:
                            self.checkpoint_store.invalidate_operation(
                                index,
                                operation,
                                {
                                    "reason": "authoritative_room_state_mismatch",
                                    "operation_applied": False,
                                    "go_live_clicked": False,
                                },
                            )
                            invalidation_summary = (
                                "completed checkpoint evidence no longer matches authoritative Maitu room state"
                            )
                        except Exception as exc:  # pragma: no cover - runtime boundary
                            invalidation_summary = f"checkpoint evidence mismatch and invalidation failed safely: {exc}"
                        actions.append(
                            self._failed_action(
                                index,
                                operation,
                                "checkpoint_reconcile_required",
                                invalidation_summary,
                            )
                        )
                        break
                    action = self._action_from_checkpoint(index, operation, checkpoint)
                    self._hydrate_checkpoint_dependencies(action, checkpoint)
                    actions.append(action)
                    continue

            if (
                self.checkpoint_store is not None
                and checkpoint is not None
                and checkpoint.get("effect_class") == "mutating"
            ):
                try:
                    checkpoint = self.checkpoint_store.dispatch_operation(index, operation)
                except Exception as exc:  # pragma: no cover - runtime boundary
                    actions.append(
                        self._failed_action(
                            index,
                            operation,
                            "checkpoint_dispatch",
                            f"checkpoint dispatch failed before side effect: {exc}",
                        )
                    )
                    break

            action = self._run_operation(index, operation, live_room_id)
            if action.status == "failed":
                actions.append(action)
                break
            if checkpoint is not None and checkpoint.get("decision") == "skip":
                self._hydrate_checkpoint_dependencies(action, checkpoint)
                actions.append(action)
                continue
            if self.checkpoint_store is not None:
                try:
                    self.checkpoint_store.complete_operation(index, operation, action)
                except Exception as exc:  # pragma: no cover - runtime boundary
                    actions.append(
                        self._failed_action(
                            index,
                            operation,
                            "checkpoint_complete",
                            f"side effect may have succeeded but checkpoint completion failed: {exc}",
                            scene_index=action.scene_index,
                            scene_name=action.scene_name,
                        )
                    )
                    break
            actions.append(action)

        executed_action_count = sum(1 for action in actions if action.status == "completed")
        skipped_action_count = sum(1 for action in actions if action.status == "skipped")
        placeholder_count = sum(1 for action in actions if action.operation_type == "placeholder_required")
        failure_count = sum(1 for action in actions if action.status == "failed")
        manual_review_required = bool(operation_plan.get("manual_review_required")) or placeholder_count > 0 or any(
            action.status == "skipped" or action.action_type == "manual_review_save_not_clicked" for action in actions
        )
        if failure_count:
            status = "failed"
            failed_action = next(action for action in actions if action.status == "failed")
            summary = failed_action.summary
        else:
            status = "completed_with_manual_review" if manual_review_required else "completed"
            summary = (
                f"Script layout draft run {status}: {executed_action_count} operation(s) executed, "
                f"{placeholder_count} placeholder(s) left for manual review; go-live not clicked."
            )
        return ScriptLayoutDraftResult(
            status=status,
            target_live_room_id=live_room_id,
            ready_for_go_live=False,
            manual_review_required=manual_review_required,
            summary=summary,
            operation_count=len(operations),
            executed_action_count=executed_action_count,
            skipped_action_count=skipped_action_count,
            placeholder_count=placeholder_count,
            failure_count=failure_count,
            actions=actions,
        )

    def _action_from_checkpoint(
        self,
        index: int,
        operation: dict[str, Any],
        checkpoint: dict[str, Any],
    ) -> ScriptLayoutDraftActionResult:
        evidence = checkpoint.get("completion_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        details = checkpoint.get("details")
        details = details if isinstance(details, dict) else {}
        summary = self._optional_string(details.get("summary")) or (
            f"Skipped already completed operation {operation.get('operation_type')} from verified checkpoint."
        )
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type=self._optional_string(checkpoint.get("operation_type"))
            or self._optional_string(operation.get("operation_type")),
            operation_name=self._optional_string(checkpoint.get("operation_name"))
            or self._optional_string(operation.get("operation_name")),
            action_type=self._optional_string(checkpoint.get("action_type")) or "checkpoint_skip",
            status=self._optional_string(checkpoint.get("status")) or "completed",
            summary=summary,
            scene_index=self._optional_int(evidence.get("scene_index"))
            if evidence.get("scene_index") is not None
            else self._optional_int(operation.get("scene_index")),
            scene_name=self._optional_string(checkpoint.get("scene_name"))
            or self._optional_string(operation.get("scene_name")),
            clip_id=self._optional_int(evidence.get("clip_id")),
            layer_id=self._optional_string(evidence.get("layer_id"))
            or self._optional_string(operation.get("layer_id")),
            layer_type=self._optional_string(evidence.get("layer_type"))
            or self._optional_string(operation.get("layer_type")),
            asset_code=self._optional_string(evidence.get("asset_code"))
            or self._optional_string(operation.get("asset_code")),
            details={**details, "checkpoint_skip": True, "completion_evidence": evidence},
        )

    def _checkpoint_evidence_matches_room(
        self,
        live_room_id: str,
        operation: dict[str, Any],
        checkpoint: dict[str, Any],
    ) -> bool:
        evidence = checkpoint.get("completion_evidence")
        if not isinstance(evidence, dict):
            return False
        if evidence.get("verified") is not True or evidence.get("operation_applied") is not True:
            return False
        if self._optional_string(evidence.get("target_live_room_id")) != live_room_id:
            return False
        try:
            room = self.session.read_live_room(live_room_id)
        except Exception:  # pragma: no cover - runtime boundary
            return False
        self._room_cache = room
        if (
            self._optional_string(room.get("id")) != live_room_id
            or room.get("_assetgraph_read_environment") != "working"
            or not self._room_is_confirmed_not_live(room)
        ):
            return False
        topics = room.get("topics") if isinstance(room.get("topics"), list) else []
        topic = topics[0] if topics and isinstance(topics[0], dict) else {}
        clips = topic.get("clips") if isinstance(topic.get("clips"), list) else []
        clip_id = self._optional_int(evidence.get("clip_id"))
        clip = next((item for item in clips if self._optional_int(item.get("id")) == clip_id), None)
        if clip is None:
            return False
        operation_type = self._optional_string(operation.get("operation_type"))
        if operation_type in {"fill_default_scene", "create_scene"}:
            expected_name = self._optional_string(operation.get("scene_name"))
            expected_index = self._optional_int(operation.get("scene_index"))
            return (
                self._optional_string(clip.get("name")) == expected_name
                and self._optional_int(clip.get("order_num")) == expected_index
            )
        materials = clip.get("clip_materials") if isinstance(clip.get("clip_materials"), list) else []
        if operation_type in {"insert_asset_layer", "position_asset_layer"}:
            material_id = self._optional_int(evidence.get("material_id"))
            if material_id is None:
                return False
            material = next(
                (
                    item
                    for item in materials
                    if self._optional_int(item.get("id")) == material_id
                ),
                None,
            )
            if material is None:
                return False
            expected_layer = self._optional_string(operation.get("layer_id"))
            if expected_layer and self._optional_string(material.get("name")) != expected_layer:
                return False
            expected_source_id = self._optional_int(operation.get("material_id") or operation.get("maitu_material_id"))
            expected_source_type = self._optional_string(operation.get("source_material_type"))
            if expected_source_type == "decorative_video":
                expected_source_type = "video"
            if expected_source_type == "digital_human":
                source_matches = (
                    self._optional_int(material.get("speaker_id")) == self._optional_int(operation.get("speaker_id"))
                    and self._optional_int(material.get("digital_human_image_id"))
                    == self._optional_int(operation.get("digital_human_image_id"))
                )
            else:
                source_matches = (
                    self._optional_int(material.get("material_id")) == expected_source_id
                    and self._optional_string(material.get("url"))
                    == self._optional_string(operation.get("source_material_url"))
                )
            if self._optional_string(material.get("type")) != expected_source_type or not source_matches:
                return False
            if operation_type == "insert_asset_layer":
                return True
            style = material.get("style_front")
            if isinstance(style, str):
                try:
                    style = json.loads(style)
                except json.JSONDecodeError:
                    return False
            style = style if isinstance(style, dict) else {}
            expected_values = {
                "left": operation.get("x"),
                "top": operation.get("y"),
                "width": operation.get("width"),
                "height": operation.get("height"),
                "zIndex": operation.get("z_index"),
            }
            return all(
                expected is None or self._optional_float(style.get(key)) == self._optional_float(expected)
                for key, expected in expected_values.items()
            )
        if operation_type == "write_script":
            script_text = self._optional_string(operation.get("script_text"))
            text_materials = [item for item in materials if item.get("type") == "text"]
            expected_text_material_id = self._optional_int(evidence.get("text_material_id"))
            return (
                len(text_materials) == 1
                and expected_text_material_id is not None
                and self._optional_int(text_materials[0].get("id")) == expected_text_material_id
                and self._optional_string(text_materials[0].get("content")) == script_text
            )
        return False

    def _hydrate_checkpoint_dependencies(
        self,
        action: ScriptLayoutDraftActionResult,
        checkpoint: dict[str, Any],
    ) -> None:
        evidence = checkpoint.get("completion_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        scene_index = self._optional_int(evidence.get("scene_index"))
        if scene_index is None:
            scene_index = action.scene_index
        clip_id = self._optional_int(evidence.get("clip_id"))
        if clip_id is None:
            clip_id = action.clip_id
        if scene_index is not None and clip_id is not None:
            self._clip_ids_by_scene[scene_index] = clip_id
        material_id = self._optional_int(evidence.get("material_id"))
        intent = checkpoint.get("intent_snapshot")
        intent = intent if isinstance(intent, dict) else {}
        layer_key = self._optional_string(evidence.get("layer_id")) or self._optional_string(intent.get("layer_id"))
        if material_id is not None and layer_key:
            self._material_ids_by_layer[(scene_index, layer_key)] = material_id

    def _run_operation(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        operation_type = self._optional_string(operation.get("operation_type"))
        operation_status = self._optional_string(operation.get("status"))
        if operation_type in {
            "preflight_content_build_plan",
            "fill_default_scene",
            "create_scene",
            "insert_asset_layer",
            "position_asset_layer",
            "write_script",
            "verify_scene",
        } and operation_status != "ready":
            return self._failed_action(
                index,
                operation,
                "operation_status_gate",
                f"operation status must be ready before execution, got {operation_status!r}",
            )
        if operation_type == "preflight_content_build_plan":
            return self._preflight(index, operation, live_room_id)
        if operation_type == "fill_default_scene":
            return self._fill_default_scene(index, operation, live_room_id)
        if operation_type == "create_scene":
            return self._create_scene(index, operation, live_room_id)
        if operation_type == "insert_asset_layer":
            return self._insert_asset_layer(index, operation, live_room_id)
        if operation_type == "position_asset_layer":
            return self._position_asset_layer(index, operation, live_room_id)
        if operation_type == "placeholder_required":
            return self._placeholder_required(index, operation)
        if operation_type == "write_script":
            return self._write_script(index, operation, live_room_id)
        if operation_type == "verify_scene":
            return self._verify_scene(index, operation, live_room_id)
        if operation_type == "save_draft":
            return self._save_draft(index, operation)
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type=operation_type,
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="unsupported_operation",
            status="failed",
            summary=f"Unsupported script-layout draft operation: {operation_type}",
            scene_index=self._optional_int(operation.get("scene_index")),
            scene_name=self._optional_string(operation.get("scene_name")),
        )

    def _preflight(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        try:
            room = self._read_room(live_room_id)
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "read_live_room", str(exc))
        authoritative_room_id = self._optional_string(room.get("id"))
        if authoritative_room_id != live_room_id:
            return self._failed_action(
                index,
                operation,
                "read_live_room",
                f"authoritative room id {authoritative_room_id!r} does not match requested room id {live_room_id!r}",
            )
        if room.get("_assetgraph_read_environment") != "working":
            return self._failed_action(
                index,
                operation,
                "read_live_room",
                "target room was not read from the authoritative working/draft environment",
            )
        if self._room_is_active_live(room):
            return self._failed_action(
                index,
                operation,
                "read_live_room",
                "target room is currently live; refusing to mutate an active live room",
            )
        if not self._room_is_confirmed_not_live(room):
            return self._failed_action(
                index,
                operation,
                "read_live_room",
                "target room has no explicit authoritative evidence that it is not live",
            )
        default_clip = self._default_clip(room)
        if default_clip is None:
            return ScriptLayoutDraftActionResult(
                operation_index=index,
                operation_type="preflight_content_build_plan",
                operation_name=self._optional_string(operation.get("operation_name")),
                action_type="read_live_room",
                status="failed",
                summary="Target room has no default clip for the first planned scene.",
                details={"target_live_room_id": live_room_id, "go_live_clicked": False},
            )
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="preflight_content_build_plan",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="read_live_room",
            status="completed",
            summary="Read target draft room and confirmed a default clip is available; go-live not clicked.",
            clip_id=self._optional_int(default_clip.get("id")),
            details={
                "target_live_room_id": live_room_id,
                "default_clip_name": default_clip.get("name"),
                "preflight_result": {
                    "verified": True,
                    "verification_source": "working_room_readback",
                    "live_room_id": live_room_id,
                    "environment": "working",
                    "not_live": True,
                    "default_clip_id": self._optional_int(default_clip.get("id")),
                    "default_clip_name": default_clip.get("name"),
                },
                "go_live_clicked": False,
            },
        )

    def _fill_default_scene(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        scene_index = self._optional_int(operation.get("scene_index")) or 0
        scene_name = self._optional_string(operation.get("scene_name")) or f"场景{scene_index + 1:02d}"
        try:
            default_clip = self._default_clip(self._read_room(live_room_id))
            if default_clip is None:
                raise RuntimeError("target room has no default clip")
            clip_id = int(default_clip["id"])
            result = self.session.rename_clip(live_room_id=live_room_id, clip_id=clip_id, name=scene_name)
            self._clip_ids_by_scene[scene_index] = clip_id
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "map_default_clip", str(exc), scene_index=scene_index, scene_name=scene_name)
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="fill_default_scene",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="map_first_planned_scene_to_default_clip",
            status="completed",
            summary="Mapped the first planned scene to the existing default clip and renamed it; no first-scene duplicate was created.",
            scene_index=scene_index,
            scene_name=scene_name,
            clip_id=clip_id,
            details={"rename_result": result, "go_live_clicked": False},
        )

    def _create_scene(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        scene_index = self._optional_int(operation.get("scene_index"))
        scene_name = self._optional_string(operation.get("scene_name")) or f"场景{(scene_index or 0) + 1:02d}"
        if scene_index is None:
            return self._failed_action(index, operation, "create_scene", "missing scene_index", scene_name=scene_name)
        try:
            result = self.session.create_scene(live_room_id=live_room_id, scene_name=scene_name, scene_index=scene_index)
            clip_id = self._optional_int(result.get("clip_id") or result.get("id"))
            if clip_id is None:
                raise RuntimeError("create_scene returned no clip_id")
            self._clip_ids_by_scene[scene_index] = clip_id
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "create_scene", str(exc), scene_index=scene_index, scene_name=scene_name)
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="create_scene",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="create_draft_scene",
            status="completed",
            summary=f"Created draft scene {scene_name}; go-live not clicked.",
            scene_index=scene_index,
            scene_name=scene_name,
            clip_id=clip_id,
            details={"create_result": result, "go_live_clicked": False},
        )

    def _insert_asset_layer(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        scene_index = self._optional_int(operation.get("scene_index"))
        asset_code = self._optional_string(operation.get("asset_code"))
        if not asset_code:
            return self._manual_required_action(index, operation, "insert_asset_layer", "missing asset_code; refusing to insert placeholder as real asset")
        clip_id = self._clip_id_for_scene(scene_index)
        if clip_id is None:
            return self._failed_action(index, operation, "insert_asset_layer", "scene has no mapped clip_id", scene_index=scene_index)
        try:
            result = self.session.insert_asset_layer(live_room_id=live_room_id, clip_id=clip_id, operation=operation)
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "insert_asset_layer", str(exc), scene_index=scene_index)
        if self._optional_string(result.get("status")) in {"manual_required", "skipped"}:
            return ScriptLayoutDraftActionResult(
                operation_index=index,
                operation_type="insert_asset_layer",
                operation_name=self._optional_string(operation.get("operation_name")),
                action_type="manual_required_asset_binding",
                status="skipped",
                summary="Selected AssetGraph asset is not yet bound to a Maitu material/source URL; no fake layer was inserted.",
                scene_index=scene_index,
                scene_name=self._optional_string(operation.get("scene_name")),
                clip_id=clip_id,
                layer_id=self._optional_string(operation.get("layer_id")),
                layer_type=self._optional_string(operation.get("layer_type")),
                asset_code=asset_code,
                details={"insert_result": result, "manual_required": True, "go_live_clicked": False},
            )
        material_id = self._optional_int(result.get("material_id"))
        layer_key = self._optional_string(operation.get("layer_id"))
        if material_id is None or not layer_key:
            return self._failed_action(
                index,
                operation,
                "insert_asset_layer",
                "authoritative insert readback omitted material identity",
                scene_index=scene_index,
            )
        self._material_ids_by_layer[(scene_index, layer_key)] = material_id
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="insert_asset_layer",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="insert_asset_layer",
            status="completed",
            summary=f"Inserted asset layer {operation.get('layer_id')} with AssetGraph asset {asset_code}.",
            scene_index=scene_index,
            scene_name=self._optional_string(operation.get("scene_name")),
            clip_id=clip_id,
            layer_id=self._optional_string(operation.get("layer_id")),
            layer_type=self._optional_string(operation.get("layer_type")),
            asset_code=asset_code,
            details={"insert_result": result, "go_live_clicked": False},
        )

    def _position_asset_layer(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        scene_index = self._optional_int(operation.get("scene_index"))
        clip_id = self._clip_id_for_scene(scene_index)
        if clip_id is None:
            return self._failed_action(index, operation, "position_asset_layer", "scene has no mapped clip_id", scene_index=scene_index)
        layer_key = self._optional_string(operation.get("layer_id"))
        material_id = self._material_ids_by_layer.get((scene_index, layer_key or ""))
        if material_id is None:
            return self._failed_action(
                index,
                operation,
                "position_asset_layer",
                "position requires the exact clip-material id produced by insert checkpoint",
                scene_index=scene_index,
            )
        positioned_operation = {**operation, "clip_material_id": material_id}
        try:
            result = self.session.position_asset_layer(
                live_room_id=live_room_id,
                clip_id=clip_id,
                operation=positioned_operation,
            )
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "position_asset_layer", str(exc), scene_index=scene_index)
        if self._optional_string(result.get("status")) in {"manual_required", "skipped"}:
            return ScriptLayoutDraftActionResult(
                operation_index=index,
                operation_type="position_asset_layer",
                operation_name=self._optional_string(operation.get("operation_name")),
                action_type="manual_required_position_binding",
                status="skipped",
                summary="Layer positioning skipped because the target Maitu material was not found or not yet inserted.",
                scene_index=scene_index,
                scene_name=self._optional_string(operation.get("scene_name")),
                clip_id=clip_id,
                layer_id=self._optional_string(operation.get("layer_id")),
                layer_type=self._optional_string(operation.get("layer_type")),
                asset_code=self._optional_string(operation.get("asset_code")),
                details={"position_result": result, "manual_required": True, "go_live_clicked": False},
            )
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="position_asset_layer",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="position_asset_layer",
            status="completed",
            summary=f"Positioned layer {operation.get('layer_id')} at x={operation.get('x')}, y={operation.get('y')}, z={operation.get('z_index')}.",
            scene_index=scene_index,
            scene_name=self._optional_string(operation.get("scene_name")),
            clip_id=clip_id,
            layer_id=self._optional_string(operation.get("layer_id")),
            layer_type=self._optional_string(operation.get("layer_type")),
            asset_code=self._optional_string(operation.get("asset_code")),
            details={"position_result": result, "go_live_clicked": False},
        )

    def _placeholder_required(self, index: int, operation: dict[str, Any]) -> ScriptLayoutDraftActionResult:
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="placeholder_required",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="manual_required_placeholder",
            status="skipped",
            summary="Missing asset placeholder left for manual review; no fake asset was inserted.",
            scene_index=self._optional_int(operation.get("scene_index")),
            scene_name=self._optional_string(operation.get("scene_name")),
            layer_id=self._optional_string(operation.get("layer_id")),
            layer_type=self._optional_string(operation.get("layer_type")),
            asset_code=None,
            details={
                "need_type": operation.get("need_type"),
                "required_category": operation.get("required_category"),
                "blocks_execution": bool(operation.get("blocks_execution", True)),
                "go_live_clicked": False,
            },
        )

    def _write_script(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        scene_index = self._optional_int(operation.get("scene_index"))
        scene_name = self._optional_string(operation.get("scene_name")) or f"场景{(scene_index or 0) + 1:02d}"
        script_text = self._optional_string(operation.get("script_text"))
        if not script_text:
            return self._manual_required_action(index, operation, "write_script", "missing script_text; manual script review required")
        clip_id = self._clip_id_for_scene(scene_index)
        if clip_id is None:
            return self._failed_action(index, operation, "write_script", "scene has no mapped clip_id", scene_index=scene_index, scene_name=scene_name)
        try:
            result = self.session.write_script(live_room_id=live_room_id, clip_id=clip_id, scene_name=scene_name, script_text=script_text)
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "write_script", str(exc), scene_index=scene_index, scene_name=scene_name)
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="write_script",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="write_script",
            status="completed",
            summary=f"Wrote script for scene {scene_name}; length={len(script_text)}.",
            scene_index=scene_index,
            scene_name=scene_name,
            clip_id=clip_id,
            details={"script_length": len(script_text), "write_result": result, "go_live_clicked": False},
        )

    def _verify_scene(self, index: int, operation: dict[str, Any], live_room_id: str) -> ScriptLayoutDraftActionResult:
        scene_index = self._optional_int(operation.get("scene_index"))
        scene_name = self._optional_string(operation.get("scene_name")) or f"场景{(scene_index or 0) + 1:02d}"
        clip_id = self._clip_id_for_scene(scene_index)
        if clip_id is None:
            return self._failed_action(index, operation, "verify_scene", "scene has no mapped clip_id", scene_index=scene_index, scene_name=scene_name)
        verified_operation = dict(operation)
        expected_layers = operation.get("expected_layers")
        if isinstance(expected_layers, list):
            dynamic_layers: list[dict[str, Any]] = []
            for layer in expected_layers:
                if not isinstance(layer, dict):
                    return self._failed_action(
                        index, operation, "verify_scene", "frozen expected layer is not an object", scene_index=scene_index
                    )
                layer_id = self._optional_string(layer.get("layer_id"))
                material_id = self._material_ids_by_layer.get((scene_index, layer_id or ""))
                if material_id is None:
                    return self._failed_action(
                        index,
                        operation,
                        "verify_scene",
                        "verify requires the exact clip-material id produced by insert checkpoint",
                        scene_index=scene_index,
                    )
                dynamic_layers.append({**layer, "material_id": material_id})
            verified_operation["expected_layers"] = dynamic_layers
        try:
            result = self.session.verify_scene(
                live_room_id=live_room_id,
                clip_id=clip_id,
                scene_name=scene_name,
                operation=verified_operation,
            )
        except Exception as exc:  # pragma: no cover - runtime boundary
            return self._failed_action(index, operation, "verify_scene", str(exc), scene_index=scene_index, scene_name=scene_name)
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="verify_scene",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="verify_scene",
            status="completed",
            summary=f"Verified draft scene {scene_name} after content operations.",
            scene_index=scene_index,
            scene_name=scene_name,
            clip_id=clip_id,
            details={"verify_result": result, "go_live_clicked": False},
        )

    def _save_draft(self, index: int, operation: dict[str, Any]) -> ScriptLayoutDraftActionResult:
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type="save_draft",
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type="manual_review_save_not_clicked",
            status="skipped",
            summary="save_draft remains an operator review gate; worker did not click save or go-live.",
            details={"operation_status": operation.get("status"), "go_live_clicked": False},
        )

    def _read_room(self, live_room_id: str) -> dict[str, Any]:
        if self._room_cache is None:
            self._room_cache = self.session.read_live_room(live_room_id)
        return self._room_cache

    def _clip_id_for_scene(self, scene_index: int | None) -> int | None:
        if scene_index is None:
            return None
        return self._clip_ids_by_scene.get(scene_index)

    def _failed_action(
        self,
        index: int,
        operation: dict[str, Any],
        action_type: str,
        message: str,
        *,
        scene_index: int | None = None,
        scene_name: str | None = None,
    ) -> ScriptLayoutDraftActionResult:
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type=self._optional_string(operation.get("operation_type")),
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type=action_type,
            status="failed",
            summary=f"Script layout draft action failed: {message}",
            scene_index=scene_index if scene_index is not None else self._optional_int(operation.get("scene_index")),
            scene_name=scene_name if scene_name is not None else self._optional_string(operation.get("scene_name")),
            layer_id=self._optional_string(operation.get("layer_id")),
            layer_type=self._optional_string(operation.get("layer_type")),
            asset_code=self._optional_string(operation.get("asset_code")),
            details={"error_message": message, "go_live_clicked": False},
        )

    def _manual_required_action(
        self,
        index: int,
        operation: dict[str, Any],
        action_type: str,
        message: str,
    ) -> ScriptLayoutDraftActionResult:
        return ScriptLayoutDraftActionResult(
            operation_index=index,
            operation_type=self._optional_string(operation.get("operation_type")),
            operation_name=self._optional_string(operation.get("operation_name")),
            action_type=action_type,
            status="skipped",
            summary=message,
            scene_index=self._optional_int(operation.get("scene_index")),
            scene_name=self._optional_string(operation.get("scene_name")),
            layer_id=self._optional_string(operation.get("layer_id")),
            layer_type=self._optional_string(operation.get("layer_type")),
            asset_code=self._optional_string(operation.get("asset_code")),
            details={"manual_required": True, "go_live_clicked": False},
        )

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
    def _room_is_active_live(room: dict[str, Any]) -> bool:
        active_values = {"1", "true", "yes", "live", "living", "on_air", "started", "running", "broadcasting"}
        return any(
            value is True or (value is not None and str(value).strip().lower() in active_values)
            for key in ("is_live", "living", "is_living", "status", "live_status", "room_status")
            if (value := room.get(key)) is not None
        )

    @staticmethod
    def _room_is_confirmed_not_live(room: dict[str, Any]) -> bool:
        false_values = {"0", "false", "no", "off", "offline", "stopped", "draft", "working", "idle", "pending", "not_live"}
        return any(
            value is False or (value is not None and str(value).strip().lower() in false_values)
            for key in ("is_live", "living", "is_living", "status", "live_status", "room_status")
            if (value := room.get(key)) is not None
        )

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
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class InMemoryScriptLayoutDraftSession:
    """Local no-browser session for smoke tests and dry-run CLI execution."""

    def __init__(self, *, live_room_id: str = "DRY-RUN-ROOM") -> None:
        self.live_room_id = live_room_id
        self.room: dict[str, Any] = {
            "id": live_room_id,
            "is_live": False,
            "_assetgraph_read_environment": "working",
            "topics": [{"id": 1, "clips": [{"id": 1, "name": "未命名", "order_num": 0, "clip_materials": []}]}],
        }
        self._next_clip_id = 2
        self._scripts_by_clip: dict[int, str] = {}

    def read_live_room(self, live_room_id: str) -> dict[str, Any]:
        return self.room

    def rename_clip(self, *, live_room_id: str, clip_id: int, name: str) -> dict[str, Any]:
        if str(live_room_id) != str(self.live_room_id):
            raise RuntimeError(f"live room mismatch: expected {self.live_room_id}, got {live_room_id}")
        clip = self._find_clip(clip_id)
        if clip is None:
            raise RuntimeError(f"clip not found: {clip_id}")
        previous = clip.get("name")
        clip["name"] = name
        return {"clip_id": clip_id, "previous_name": previous, "name": name, "verified": True, "dry_run": True}

    def create_scene(self, *, live_room_id: str, scene_name: str, scene_index: int) -> dict[str, Any]:
        clip = {"id": self._next_clip_id, "name": scene_name, "order_num": scene_index, "clip_materials": []}
        self._next_clip_id += 1
        self.room["topics"][0]["clips"].append(clip)
        return {"clip_id": clip["id"], "name": scene_name, "verified": True, "dry_run": True}

    def insert_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict[str, Any]) -> dict[str, Any]:
        clip = self._required_clip(clip_id)
        material = {
            "id": len(clip["clip_materials"]) + 1,
            "layer_id": operation.get("layer_id"),
            "layer_type": operation.get("layer_type"),
            "asset_code": operation.get("asset_code"),
            "asset_display_code": operation.get("asset_display_code"),
            "left": operation.get("x"),
            "top": operation.get("y"),
            "width": operation.get("width"),
            "height": operation.get("height"),
            "z_index": operation.get("z_index"),
        }
        clip["clip_materials"].append(material)
        return {
            "clip_id": clip_id,
            "material_id": material["id"],
            "material": material,
            "verified": True,
            "dry_run": True,
        }

    def position_asset_layer(self, *, live_room_id: str, clip_id: int, operation: dict[str, Any]) -> dict[str, Any]:
        clip = self._required_clip(clip_id)
        layer_id = operation.get("layer_id")
        for material in clip["clip_materials"]:
            if material.get("layer_id") == layer_id:
                material.update(
                    {
                        "left": operation.get("x"),
                        "top": operation.get("y"),
                        "width": operation.get("width"),
                        "height": operation.get("height"),
                        "z_index": operation.get("z_index"),
                    }
                )
                return {"clip_id": clip_id, "layer_id": layer_id, "verified": True, "dry_run": True}
        raise RuntimeError(f"layer not found for positioning: {layer_id}")

    def write_script(self, *, live_room_id: str, clip_id: int, scene_name: str, script_text: str) -> dict[str, Any]:
        self._required_clip(clip_id)
        self._scripts_by_clip[clip_id] = script_text
        return {"clip_id": clip_id, "script_length": len(script_text), "verified": True, "dry_run": True}

    def verify_scene(self, *, live_room_id: str, clip_id: int, scene_name: str, operation: dict[str, Any]) -> dict[str, Any]:
        clip = self._required_clip(clip_id)
        return {
            "clip_id": clip_id,
            "scene_name": clip.get("name") or scene_name,
            "visual_count": len(clip.get("clip_materials") or []),
            "script_present": bool(self._scripts_by_clip.get(clip_id)),
            "verified": True,
            "dry_run": True,
        }

    def _find_clip(self, clip_id: int) -> dict[str, Any] | None:
        clips = self.room["topics"][0]["clips"]
        return next((clip for clip in clips if int(clip.get("id") or 0) == int(clip_id)), None)

    def _required_clip(self, clip_id: int) -> dict[str, Any]:
        clip = self._find_clip(clip_id)
        if clip is None:
            raise RuntimeError(f"clip not found: {clip_id}")
        return clip


def build_script_layout_draft_execution_payload(result: ScriptLayoutDraftResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "executor": "browser_use",
        "execution_status": result.status,
        "mode": "script_layout_draft",
        "retryable": False,
        "result_summary": result.summary,
        "ready_for_go_live": result.ready_for_go_live,
        "manual_review_required": result.manual_review_required,
        "operation_results": [script_layout_action_to_operation_result(action) for action in result.actions],
    }
    if result.status == "blocked":
        payload["failure_type"] = "layout_build_plan_blocked"
    elif result.status == "failed":
        payload["failure_type"] = "script_layout_draft_action_failed"
    return payload


def script_layout_action_to_operation_result(action: ScriptLayoutDraftActionResult) -> dict[str, Any]:
    row: dict[str, Any] = {
        "operation_index": action.operation_index,
        "operation_type": action.operation_type or "unknown",
        "operation_name": action.operation_name,
        "scene_index": action.scene_index,
        "scene_name": action.scene_name,
        "clip_id": action.clip_id,
        "layer_id": action.layer_id,
        "layer_type": action.layer_type,
        "asset_code": action.asset_code,
        "action_type": action.action_type,
        "status": action.status,
        "retryable": False,
        "details": {**(action.details or {}), "summary": action.summary},
    }
    if action.status == "failed":
        row["failure_type"] = "script_layout_draft_action_failed"
        row["error_message"] = action.summary
    if action.operation_type == "placeholder_required":
        row["failure_type"] = "manual_required_placeholder"
    return {key: value for key, value in row.items() if value is not None}

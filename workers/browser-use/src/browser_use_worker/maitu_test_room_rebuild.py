from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Protocol


PROTECTED_REFERENCE_ROOM_IDS = frozenset({"38336", "38995"})


class MaituTestRoomRebuildSession(Protocol):
    def read_live_room(self, live_room_id: str) -> dict[str, Any]: ...

    def delete_clip(
        self,
        *,
        live_room_id: str,
        clip_id: int,
        expected_live_room_title: str,
    ) -> dict[str, Any]: ...

    def clear_clip_materials(
        self,
        *,
        live_room_id: str,
        clip_id: int,
        expected_live_room_title: str,
    ) -> dict[str, Any]: ...

    def rename_clip(
        self,
        *,
        live_room_id: str,
        clip_id: int,
        name: str,
        order_num: int | None = None,
        expected_live_room_title: str | None = None,
    ) -> dict[str, Any]: ...

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
        expected_live_room_title: str | None = None,
    ) -> dict[str, Any]: ...

    def create_scene(
        self,
        *,
        live_room_id: str,
        scene_name: str,
        scene_index: int,
        topic_id: int | None = None,
        expected_live_room_title: str | None = None,
    ) -> dict[str, Any]: ...

    def write_script(
        self,
        *,
        live_room_id: str,
        clip_id: int,
        scene_name: str,
        script_text: str,
        expected_live_room_title: str | None = None,
    ) -> dict[str, Any]: ...

    def verify_scene(
        self,
        *,
        live_room_id: str,
        clip_id: int,
        scene_name: str,
        operation: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(slots=True, frozen=True)
class MaituTestRoomSceneSpec:
    scene_name: str
    reference_clip_id: str
    component_operations: tuple[dict[str, Any], ...]
    script_text: str

    @property
    def visual_count(self) -> int:
        return len(self.component_operations)


@dataclass(slots=True, frozen=True)
class MaituTestRoomRebuildSpec:
    target_live_room_id: str
    expected_title: str
    reference_room_id: str
    scenes: tuple[MaituTestRoomSceneSpec, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MaituTestRoomRebuildSpec:
        if not isinstance(payload, dict):
            raise ValueError("test-room rebuild spec must be an object")
        target_live_room_id = _canonical_numeric_id(payload, "target_live_room_id")
        expected_title = _canonical_string(payload, "expected_title")
        reference_room_id = _canonical_numeric_id(payload, "reference_room_id")
        if target_live_room_id in PROTECTED_REFERENCE_ROOM_IDS:
            raise ValueError("target_live_room_id is a protected read-only reference room")
        if reference_room_id == target_live_room_id:
            raise ValueError("reference_room_id must be different from target_live_room_id")
        raw_scenes = payload.get("scenes")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ValueError("test-room rebuild spec requires at least one scene")

        scenes: list[MaituTestRoomSceneSpec] = []
        seen_names: set[str] = set()
        for index, raw_scene in enumerate(raw_scenes):
            if not isinstance(raw_scene, dict):
                raise ValueError(f"scenes[{index}] must be an object")
            scene_name = _canonical_string(raw_scene, "scene_name", prefix=f"scenes[{index}].")
            if scene_name in seen_names:
                raise ValueError(f"scene names must be unique: {scene_name!r}")
            seen_names.add(scene_name)
            reference_clip_id = _canonical_numeric_id(raw_scene, "reference_clip_id", prefix=f"scenes[{index}].")
            script_text = _canonical_string(raw_scene, "script_text", prefix=f"scenes[{index}].")
            raw_operations = raw_scene.get("component_operations")
            raw_visual_count = raw_scene.get("visual_count")
            if raw_operations is None:
                if isinstance(raw_visual_count, bool) or not isinstance(raw_visual_count, int) or raw_visual_count <= 0:
                    raise ValueError(
                        f"scenes[{index}] requires non-empty component_operations or a positive visual_count"
                    )
                operations = tuple(
                    {
                        "operation_type": "insert_template_component",
                        "component_index": component_index,
                        "z_index": component_index + 1,
                    }
                    for component_index in range(raw_visual_count)
                )
            else:
                if not isinstance(raw_operations, list) or not raw_operations:
                    raise ValueError(f"scenes[{index}].component_operations must be a non-empty list")
                if not all(isinstance(operation, dict) for operation in raw_operations):
                    raise ValueError(f"scenes[{index}].component_operations must contain only objects")
                normalized_operations: list[dict[str, Any]] = []
                for operation_index, operation in enumerate(raw_operations):
                    normalized = dict(operation)
                    component_index = normalized.get("component_index", operation_index)
                    if isinstance(component_index, bool) or not isinstance(component_index, int):
                        raise ValueError(
                            f"scenes[{index}].component_operations[{operation_index}].component_index "
                            "must be an integer"
                        )
                    normalized["component_index"] = component_index
                    normalized_operations.append(normalized)
                operations = tuple(normalized_operations)
                if raw_visual_count is not None and raw_visual_count != len(operations):
                    raise ValueError(f"scenes[{index}].visual_count does not match component_operations")
            component_indices = [operation["component_index"] for operation in operations]
            if sorted(component_indices) != list(range(len(operations))):
                raise ValueError(
                    f"scenes[{index}].component_operations must select every reference component exactly once"
                )
            planned_z = [operation.get("z_index") for operation in operations]
            if not any(value is not None for value in planned_z):
                operations = tuple(
                    {**operation, "z_index": position}
                    for position, operation in enumerate(operations, start=1)
                )
                planned_z = [operation["z_index"] for operation in operations]
            else:
                if any(isinstance(value, bool) or not isinstance(value, int) for value in planned_z):
                    raise ValueError(
                        f"scenes[{index}].component_operations z_index values must all be integers"
                    )
                if sorted(planned_z) != list(range(1, len(operations) + 1)):
                    raise ValueError(
                        f"scenes[{index}].component_operations z_index values must be unique and contiguous from one"
                    )
            scenes.append(
                MaituTestRoomSceneSpec(
                    scene_name=scene_name,
                    reference_clip_id=reference_clip_id,
                    component_operations=operations,
                    script_text=script_text,
                )
            )
        return cls(
            target_live_room_id=target_live_room_id,
            expected_title=expected_title,
            reference_room_id=reference_room_id,
            scenes=tuple(scenes),
        )


@dataclass(slots=True)
class MaituTestRoomRebuildAction:
    action_type: str
    status: str
    summary: str
    scene_name: str | None = None
    clip_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MaituTestRoomRebuildResult:
    status: str
    target_live_room_id: str
    expected_title: str
    keeper_clip_id: int | None
    scene_clip_ids: list[int]
    action_count: int
    failure_count: int
    summary: str
    actions: list[MaituTestRoomRebuildAction]
    ready_for_go_live: bool = False
    go_live_clicked: bool = False


class MaituTestRoomRebuildRunner:
    """Destructively resets one explicit offline test draft, then rebuilds it.

    There is deliberately no retry loop, save, scheduling, authorization, or
    go-live operation in this workflow.
    """

    def __init__(self, *, session: MaituTestRoomRebuildSession) -> None:
        self.session = session

    def run(self, spec: MaituTestRoomRebuildSpec) -> MaituTestRoomRebuildResult:
        actions: list[MaituTestRoomRebuildAction] = []
        keeper_clip_id: int | None = None
        keeper_topic_id: int | None = None
        scene_clip_ids: list[int] = []
        current_action = "preflight"
        current_scene: str | None = None
        current_clip_id: int | None = None
        try:
            room = self.session.read_live_room(spec.target_live_room_id)
            target_clips = self._validate_target_room(room, spec)
            keeper = target_clips[0]
            keeper_clip_id = self._positive_int(keeper.get("id"), "keeper clip id")
            keeper_topic_id = self._positive_int(keeper.get("_assetgraph_topic_id"), "keeper topic id")

            reference_room = self.session.read_live_room(spec.reference_room_id)
            reference_clips = self._validate_reference_room(reference_room, spec)
            reference_visuals = [
                self._visual_snapshot(reference_clips[scene.reference_clip_id])
                for scene in spec.scenes
            ]
            planned_visuals = [
                self._planned_visual_snapshot(reference_visuals[index], scene.component_operations)
                for index, scene in enumerate(spec.scenes)
            ]
            actions.append(
                MaituTestRoomRebuildAction(
                    action_type="preflight",
                    status="completed",
                    summary="Confirmed exact target id/title, working environment, explicit not-live state, and all reference clips.",
                    clip_id=keeper_clip_id,
                    details={
                        "target_live_room_id": spec.target_live_room_id,
                        "expected_title": spec.expected_title,
                        "initial_clip_ids": [self._positive_int(clip.get("id"), "clip id") for clip in target_clips],
                        "keeper_topic_id": keeper_topic_id,
                        "reference_room_id": spec.reference_room_id,
                        "reference_clip_ids": [scene.reference_clip_id for scene in spec.scenes],
                        "not_live": True,
                        "verification_source": "working_room_readback",
                        "go_live_clicked": False,
                    },
                )
            )

            for clip in target_clips[1:]:
                current_action = "delete_clip"
                current_clip_id = self._positive_int(clip.get("id"), "clip id")
                result = self.session.delete_clip(
                    live_room_id=spec.target_live_room_id,
                    clip_id=current_clip_id,
                    expected_live_room_title=spec.expected_title,
                )
                actions.append(
                    MaituTestRoomRebuildAction(
                        action_type=current_action,
                        status="completed",
                        summary="Deleted one non-keeper clip with authoritative readback.",
                        clip_id=current_clip_id,
                        details=result,
                    )
                )

            current_action = "clear_keeper_materials"
            current_clip_id = keeper_clip_id
            clear_result = self.session.clear_clip_materials(
                live_room_id=spec.target_live_room_id,
                clip_id=keeper_clip_id,
                expected_live_room_title=spec.expected_title,
            )
            actions.append(
                MaituTestRoomRebuildAction(
                    action_type=current_action,
                    status="completed",
                    summary="Cleared every material from the keeper clip with authoritative readback.",
                    clip_id=keeper_clip_id,
                    details=clear_result,
                )
            )

            current_action = "verify_empty_room"
            empty_room = self.session.read_live_room(spec.target_live_room_id)
            empty_clips = self._validate_target_room(empty_room, spec)
            if len(empty_clips) != 1 or self._positive_int(empty_clips[0].get("id"), "clip id") != keeper_clip_id:
                raise ValueError("room reset readback must contain exactly the original keeper clip")
            materials = empty_clips[0].get("clip_materials")
            if not isinstance(materials, list) or materials:
                raise ValueError("room reset readback must contain zero keeper materials")
            actions.append(
                MaituTestRoomRebuildAction(
                    action_type=current_action,
                    status="completed",
                    summary="Verified the reset room has exactly one clip and zero materials.",
                    clip_id=keeper_clip_id,
                    details={"clip_count": 1, "material_count": 0, "go_live_clicked": False},
                )
            )

            for scene_index, scene in enumerate(spec.scenes):
                current_scene = scene.scene_name
                self._validate_target_room(self.session.read_live_room(spec.target_live_room_id), spec)
                if scene_index == 0:
                    current_action = "rename_keeper_scene"
                    current_clip_id = keeper_clip_id
                    scene_result = self.session.rename_clip(
                        live_room_id=spec.target_live_room_id,
                        clip_id=keeper_clip_id,
                        name=scene.scene_name,
                        order_num=0,
                        expected_live_room_title=spec.expected_title,
                    )
                else:
                    current_action = "create_scene"
                    scene_result = self.session.create_scene(
                        live_room_id=spec.target_live_room_id,
                        scene_name=scene.scene_name,
                        scene_index=scene_index,
                        topic_id=keeper_topic_id,
                        expected_live_room_title=spec.expected_title,
                    )
                    current_clip_id = self._positive_int(scene_result.get("clip_id"), "created clip id")
                scene_clip_ids.append(current_clip_id)
                actions.append(
                    MaituTestRoomRebuildAction(
                        action_type=current_action,
                        status="completed",
                        summary="Mapped the scene to its target clip.",
                        scene_name=scene.scene_name,
                        clip_id=current_clip_id,
                        details=scene_result,
                    )
                )

                current_action = "fill_scene_from_template"
                current_reference_room = self.session.read_live_room(spec.reference_room_id)
                current_reference_clips = self._validate_reference_room(current_reference_room, spec)
                current_reference_visuals = self._visual_snapshot(
                    current_reference_clips[scene.reference_clip_id]
                )
                if current_reference_visuals != reference_visuals[scene_index]:
                    raise ValueError(f"reference clip {scene.reference_clip_id!r} drifted after preflight")
                fill_result = self.session.fill_clip_from_template(
                    live_room_id=spec.target_live_room_id,
                    target_clip_id=current_clip_id,
                    reference_room_id=spec.reference_room_id,
                    reference_clip_id=scene.reference_clip_id,
                    scene_name=scene.scene_name,
                    component_operations=[dict(operation) for operation in scene.component_operations],
                    script_content=None,
                    expected_live_room_title=spec.expected_title,
                )
                if int(fill_result.get("visual_count", -1)) != scene.visual_count:
                    raise ValueError(
                        f"scene {scene.scene_name!r} copied {fill_result.get('visual_count')!r} visuals; "
                        f"expected {scene.visual_count}"
                    )
                if int(fill_result.get("text_count", -1)) != 0:
                    raise ValueError(f"scene {scene.scene_name!r} template fill did not leave an empty script slot")
                actions.append(
                    MaituTestRoomRebuildAction(
                        action_type=current_action,
                        status="completed",
                        summary=f"Copied all {scene.visual_count} expected visual layers from the reference clip.",
                        scene_name=scene.scene_name,
                        clip_id=current_clip_id,
                        details=fill_result,
                    )
                )

                self._validate_target_room(self.session.read_live_room(spec.target_live_room_id), spec)
                current_action = "write_scene_script"
                script_result = self.session.write_script(
                    live_room_id=spec.target_live_room_id,
                    clip_id=current_clip_id,
                    scene_name=scene.scene_name,
                    script_text=scene.script_text,
                    expected_live_room_title=spec.expected_title,
                )
                actions.append(
                    MaituTestRoomRebuildAction(
                        action_type=current_action,
                        status="completed",
                        summary="Wrote the custom scene script with authoritative readback.",
                        scene_name=scene.scene_name,
                        clip_id=current_clip_id,
                        details=script_result,
                    )
                )

            current_action = "verify_rebuilt_room"
            verification_room = self.session.read_live_room(spec.target_live_room_id)
            verification_clips = self._validate_final_room(
                verification_room,
                spec,
                scene_clip_ids,
                planned_visuals,
            )
            for scene_index, (scene, clip, expected_visuals) in enumerate(
                zip(spec.scenes, verification_clips, planned_visuals, strict=True)
            ):
                current_scene = scene.scene_name
                current_clip_id = scene_clip_ids[scene_index]
                verify_result = self.session.verify_scene(
                    live_room_id=spec.target_live_room_id,
                    clip_id=current_clip_id,
                    scene_name=scene.scene_name,
                    operation=self._scene_verification_operation(scene_index, scene, clip, expected_visuals),
                )
                if verify_result.get("verified") is not True:
                    raise ValueError(f"scene {scene.scene_name!r} verification did not return verified=true")
                actions.append(
                    MaituTestRoomRebuildAction(
                        action_type="verify_scene",
                        status="completed",
                        summary="Verified scene name, complete visual snapshot, and unique script.",
                        scene_name=scene.scene_name,
                        clip_id=current_clip_id,
                        details=verify_result,
                    )
                )

            final_room = self.session.read_live_room(spec.target_live_room_id)
            final_clips = self._validate_final_room(final_room, spec, scene_clip_ids, planned_visuals)
            actions.append(
                MaituTestRoomRebuildAction(
                    action_type="final_readback",
                    status="completed",
                    summary="Final working-room readback matches the expected title, scene order, names, layers, and scripts.",
                    details={
                        "title": final_room.get("name"),
                        "scene_count": len(final_clips),
                        "scene_names": [clip.get("name") for clip in final_clips],
                        "scene_clip_ids": scene_clip_ids,
                        "visual_counts": [self._visual_count(clip) for clip in final_clips],
                        "verification_source": "working_room_readback",
                        "go_live_clicked": False,
                    },
                )
            )
        except Exception as exc:
            actions.append(
                MaituTestRoomRebuildAction(
                    action_type=current_action,
                    status="failed",
                    summary=f"Stopped after first failure: {type(exc).__name__}: {exc}",
                    scene_name=current_scene,
                    clip_id=current_clip_id,
                    details={"retry_attempted": False, "go_live_clicked": False},
                )
            )
            return MaituTestRoomRebuildResult(
                status="failed",
                target_live_room_id=spec.target_live_room_id,
                expected_title=spec.expected_title,
                keeper_clip_id=keeper_clip_id,
                scene_clip_ids=scene_clip_ids,
                action_count=len(actions),
                failure_count=1,
                summary="Test-room rebuild stopped after the first failure; reconcile the authoritative room before retrying.",
                actions=actions,
            )

        return MaituTestRoomRebuildResult(
            status="completed",
            target_live_room_id=spec.target_live_room_id,
            expected_title=spec.expected_title,
            keeper_clip_id=keeper_clip_id,
            scene_clip_ids=scene_clip_ids,
            action_count=len(actions),
            failure_count=0,
            summary="Test draft was reset and rebuilt; final authoritative readback passed and go-live was not clicked.",
            actions=actions,
        )

    @classmethod
    def _validate_target_room(
        cls,
        room: dict[str, Any],
        spec: MaituTestRoomRebuildSpec,
    ) -> list[dict[str, Any]]:
        if not isinstance(room, dict) or str(room.get("id")) != spec.target_live_room_id:
            raise ValueError("authoritative target room id does not match the explicit target_live_room_id")
        if room.get("name") != spec.expected_title:
            raise ValueError("authoritative target room title does not match expected_title")
        if room.get("_assetgraph_read_environment") != "working":
            raise ValueError("target room was not read from the authoritative working environment")
        if cls._room_is_active_live(room):
            raise ValueError("target room is currently live")
        if cls._room_has_live_trace(room):
            raise ValueError("target room has an authoritative live-session trace")
        if not cls._room_is_confirmed_not_live(room):
            raise ValueError("target room has no explicit authoritative not-live evidence")
        topics = room.get("topics")
        if not isinstance(topics, list) or not topics or not all(isinstance(topic, dict) for topic in topics):
            raise ValueError("target room must contain authoritative topics")
        clips: list[dict[str, Any]] = []
        for topic in topics:
            topic_id = cls._positive_int(topic.get("id"), "topic id")
            topic_clips = topic.get("clips")
            if not isinstance(topic_clips, list) or not all(isinstance(clip, dict) for clip in topic_clips):
                raise ValueError("target room topic has no authoritative clip list")
            clips.extend({**clip, "_assetgraph_topic_id": topic_id} for clip in topic_clips)
        if not clips:
            raise ValueError("target room must contain a non-empty authoritative clip list")
        clip_ids = [cls._positive_int(clip.get("id"), "clip id") for clip in clips]
        if len(set(clip_ids)) != len(clip_ids):
            raise ValueError("target room contains duplicate clip ids")
        return sorted(clips, key=cls._clip_order_key)

    @classmethod
    def _validate_reference_room(
        cls,
        room: dict[str, Any],
        spec: MaituTestRoomRebuildSpec,
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(room, dict) or str(room.get("id")) != spec.reference_room_id:
            raise ValueError("authoritative reference room id does not match reference_room_id")
        if room.get("_assetgraph_read_environment") != "working":
            raise ValueError("reference room was not read from the authoritative working environment")
        topics = room.get("topics")
        if not isinstance(topics, list):
            raise ValueError("reference room topics are not authoritative")
        clips = [
            clip
            for topic in topics
            if isinstance(topic, dict) and isinstance(topic.get("clips"), list)
            for clip in topic["clips"]
            if isinstance(clip, dict)
        ]
        by_id: dict[str, list[dict[str, Any]]] = {}
        for clip in clips:
            by_id.setdefault(str(clip.get("id")), []).append(clip)
        selected: dict[str, dict[str, Any]] = {}
        for scene in spec.scenes:
            matches = by_id.get(scene.reference_clip_id, [])
            if len(matches) != 1:
                raise ValueError(f"reference clip {scene.reference_clip_id!r} is missing or not unique")
            visual_count = cls._visual_count(matches[0])
            if visual_count != scene.visual_count:
                raise ValueError(
                    f"reference clip {scene.reference_clip_id!r} has {visual_count} visual layers; "
                    f"scene expects {scene.visual_count}"
                )
            selected[scene.reference_clip_id] = matches[0]
        return selected

    @classmethod
    def _validate_final_room(
        cls,
        room: dict[str, Any],
        spec: MaituTestRoomRebuildSpec,
        scene_clip_ids: list[int],
        reference_visuals: list[list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        clips = cls._validate_target_room(room, spec)
        if (
            len(clips) != len(spec.scenes)
            or len(scene_clip_ids) != len(spec.scenes)
            or len(reference_visuals) != len(spec.scenes)
        ):
            raise ValueError("final scene count does not match the rebuild spec")
        for index, (scene, clip) in enumerate(zip(spec.scenes, clips, strict=True)):
            if cls._positive_int(clip.get("id"), "clip id") != scene_clip_ids[index]:
                raise ValueError(f"final clip order drifted at scene {scene.scene_name!r}")
            if clip.get("name") != scene.scene_name:
                raise ValueError(f"final scene name mismatch at index {index}")
            if cls._visual_count(clip) != scene.visual_count:
                raise ValueError(f"final visual count mismatch for scene {scene.scene_name!r}")
            cls._assert_visuals_match_reference(clip, reference_visuals[index], scene.scene_name)
            materials = clip.get("clip_materials")
            texts = [material for material in materials if isinstance(material, dict) and material.get("type") == "text"]
            if len(texts) != 1 or texts[0].get("content") != scene.script_text:
                raise ValueError(f"final script mismatch for scene {scene.scene_name!r}")
        return clips

    @classmethod
    def _scene_verification_operation(
        cls,
        scene_index: int,
        scene: MaituTestRoomSceneSpec,
        clip: dict[str, Any],
        reference_visuals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        materials = clip.get("clip_materials")
        if not isinstance(materials, list):
            raise ValueError(f"scene {scene.scene_name!r} has no authoritative material list")
        target_visuals = [
            material
            for material in materials
            if isinstance(material, dict) and material.get("type") not in {"text", "audio"}
        ]
        cls._assert_visuals_match_reference(clip, reference_visuals, scene.scene_name)
        expected_layers = [
            {**expected, "material_id": cls._positive_int(target.get("id"), "visual material id")}
            for target, expected in zip(target_visuals, reference_visuals, strict=True)
        ]
        return {
            "scene_index": scene_index,
            "scene_name": scene.scene_name,
            "expected_visual_count": scene.visual_count,
            "expected_text_count": 1,
            "expected_script_text": scene.script_text,
            "expected_layers": expected_layers,
        }

    @classmethod
    def _assert_visuals_match_reference(
        cls,
        target_clip: dict[str, Any],
        reference_visuals: list[dict[str, Any]],
        scene_name: str,
    ) -> None:
        target_visuals = cls._visual_snapshot(target_clip)
        if target_visuals != reference_visuals:
            raise ValueError(f"scene {scene_name!r} visual identity/geometry differs from the preflight reference snapshot")

    @classmethod
    def _visual_snapshot(cls, clip: dict[str, Any]) -> list[dict[str, Any]]:
        materials = clip.get("clip_materials")
        if not isinstance(materials, list):
            raise ValueError("clip has no authoritative material list")
        snapshot: list[dict[str, Any]] = []
        for material in materials:
            if not isinstance(material, dict) or material.get("type") in {"text", "audio"}:
                continue
            layer_name = material.get("name")
            if not isinstance(layer_name, str):
                raise ValueError("reference visual material has no stable layer name")
            style = cls._material_style(material)
            expected: dict[str, Any] = {
                "layer_id": layer_name,
                "source_material_type": material.get("type"),
                "source_material_id": material.get("material_id"),
                "source_material_url": material.get("url"),
                "speaker_id": material.get("speaker_id"),
                "digital_human_image_id": material.get("digital_human_image_id"),
                "left": cls._required_number(material.get("left"), "layer left"),
                "top": cls._required_number(material.get("top"), "layer top"),
                "width": cls._required_number(material.get("width"), "layer width"),
                "height": cls._required_number(material.get("height"), "layer height"),
                "z_index": cls._required_number(material.get("layer_n"), "layer z-index"),
                "style_front": cls._normalized_json_value(style, "style_front"),
            }
            if "sound_enabled" in material:
                expected["sound_enabled"] = bool(material.get("sound_enabled"))
            snapshot.append(expected)
        return snapshot

    @classmethod
    def _planned_visual_snapshot(
        cls,
        reference_visuals: list[dict[str, Any]],
        operations: tuple[dict[str, Any], ...],
    ) -> list[dict[str, Any]]:
        planned: list[dict[str, Any]] = []
        for operation in operations:
            component_index = int(operation["component_index"])
            reference = reference_visuals[component_index]
            expected_layer = operation.get("expected_layer_id")
            if expected_layer is not None and reference["layer_id"] != expected_layer:
                raise ValueError(
                    f"reference component {component_index} layer identity differs from expected_layer_id"
                )
            expected_source = operation.get("expected_source_material_id")
            if expected_source is not None and str(reference["source_material_id"]) != str(expected_source):
                raise ValueError(
                    f"reference component {component_index} source material differs from expectation"
                )
            item = {
                **reference,
                "style_front": dict(reference.get("style_front") or {}),
            }
            if operation.get("z_index") is not None:
                item["z_index"] = float(operation["z_index"])
                item["style_front"]["zIndex"] = float(operation["z_index"])
            planned.append(item)
        return planned

    @staticmethod
    def _material_style(material: dict[str, Any]) -> dict[str, Any]:
        raw = material.get("style_front")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        return {}

    @classmethod
    def _normalized_json_value(cls, value: Any, label: str) -> Any:
        if value is None or isinstance(value, (str, bool)):
            return value
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                raise ValueError(f"{label} contains a non-finite number")
            return float(value)
        if isinstance(value, list):
            return [cls._normalized_json_value(item, label) for item in value]
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise ValueError(f"{label} contains a non-string object key")
            return {
                key: cls._normalized_json_value(value[key], label)
                for key in sorted(value)
            }
        raise ValueError(f"{label} contains an unsupported JSON value")

    @staticmethod
    def _clip_order_key(clip: dict[str, Any]) -> tuple[float, int]:
        order_num = MaituTestRoomRebuildRunner._required_number(clip.get("order_num"), "clip order_num")
        return order_num, MaituTestRoomRebuildRunner._positive_int(clip.get("id"), "clip id")

    @staticmethod
    def _positive_int(value: Any, label: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{label} must be a positive integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a positive integer") from exc
        if parsed <= 0 or str(value).strip() != str(parsed):
            raise ValueError(f"{label} must be a canonical positive integer")
        return parsed

    @staticmethod
    def _required_number(value: Any, label: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{label} must be numeric")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be numeric") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{label} must be finite")
        return parsed

    @staticmethod
    def _visual_count(clip: dict[str, Any]) -> int:
        materials = clip.get("clip_materials")
        if not isinstance(materials, list):
            raise ValueError("clip has no authoritative material list")
        return sum(
            1
            for material in materials
            if isinstance(material, dict) and material.get("type") not in {"text", "audio"}
        )

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
        inactive_values = {"0", "false", "no", "off", "offline", "stopped", "draft", "working", "idle", "pending", "not_live"}
        return any(
            value is False or (value is not None and str(value).strip().lower() in inactive_values)
            for key in ("is_live", "living", "is_living", "status", "live_status", "room_status")
            if (value := room.get(key)) is not None
        )

    @staticmethod
    def _room_has_live_trace(room: dict[str, Any]) -> bool:
        return any(
            value is not None and str(value).strip() not in {"", "0"}
            for key in ("live_session_id", "latest_live_time", "live_started_at", "live_start_time")
            if (value := room.get(key)) is not None
        )


def _canonical_string(payload: dict[str, Any], key: str, *, prefix: str = "") -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{prefix}{key} must be a non-empty canonical string")
    return value


def _canonical_numeric_id(payload: dict[str, Any], key: str, *, prefix: str = "") -> str:
    value = _canonical_string(payload, key, prefix=prefix)
    if not value.isdigit() or int(value) <= 0 or str(int(value)) != value:
        raise ValueError(f"{prefix}{key} must be a canonical positive numeric string")
    return value

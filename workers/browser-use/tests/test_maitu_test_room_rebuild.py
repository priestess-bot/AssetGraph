from __future__ import annotations

import copy
from typing import Any

import pytest

from browser_use_worker.maitu_test_room_rebuild import (
    MaituTestRoomRebuildRunner,
    MaituTestRoomRebuildSpec,
)


def visual(material_id: int, index: int) -> dict[str, Any]:
    return {
        "id": material_id,
        "type": "image",
        "name": f"模板层-{index:02d}",
        "material_id": 50000 + index,
        "url": f"https://cdn.example.test/material-{index}.png",
        "left": 106 + index * 10,
        "top": 464 + index * 20,
        "width": 1080,
        "height": 1920,
        "layer_n": index + 1,
        "sound_enabled": False,
        "style_front": {
            "left": 43.196 + index * 4,
            "top": 187.533 + index * 8,
            "width": 440,
            "height": 782,
            "zIndex": index + 1,
            "transform": {"scale": 1.0, "rotation": 0},
        },
    }


def reference_clip(clip_id: int, count: int) -> dict[str, Any]:
    return {
        "id": clip_id,
        "name": f"引用-{clip_id}",
        "order_num": 0,
        "clip_materials": [visual(clip_id * 100 + index, index) for index in range(count)],
    }


def rebuild_payload() -> dict[str, Any]:
    return {
        "target_live_room_id": "41172",
        "expected_title": "张裕品酒大师PRO测试直播间",
        "reference_room_id": "38336",
        "scenes": [
            {"scene_name": "开场介绍", "reference_clip_id": "390068", "visual_count": 8, "script_text": "欢迎来到直播间。"},
            {"scene_name": "产品讲解", "reference_clip_id": "390069", "visual_count": 9, "script_text": "现在介绍张裕品酒大师PRO。"},
            {"scene_name": "场景收束", "reference_clip_id": "390070", "visual_count": 8, "script_text": "欢迎留言了解更多。"},
        ],
    }


def test_visual_count_and_unordered_operations_compile_unique_contiguous_layer_order() -> None:
    payload = rebuild_payload()
    payload["scenes"] = [payload["scenes"][0]]

    visual_count_spec = MaituTestRoomRebuildSpec.from_dict(payload)
    assert [operation["z_index"] for operation in visual_count_spec.scenes[0].component_operations] == list(
        range(1, 9)
    )

    payload["scenes"][0].pop("visual_count")
    payload["scenes"][0]["component_operations"] = [
        {"component_index": 2},
        {"component_index": 0},
        {"component_index": 1},
    ]
    operation_spec = MaituTestRoomRebuildSpec.from_dict(payload)
    assert [operation["component_index"] for operation in operation_spec.scenes[0].component_operations] == [2, 0, 1]
    assert [operation["z_index"] for operation in operation_spec.scenes[0].component_operations] == [1, 2, 3]


class FakeRebuildSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | str]] = []
        self.next_clip_id = 9000
        self.next_material_id = 80000
        self.target = {
            "id": 41172,
            "name": "张裕品酒大师PRO测试直播间",
            "status": 0,
            "latest_live_time": None,
            "live_session_id": None,
            "_assetgraph_read_environment": "working",
            "topics": [
                {
                    "id": 101,
                    "clips": [
                        {"id": 7002, "name": "旧场景2", "order_num": 1, "clip_materials": [visual(70200, 0)]},
                        {"id": 7003, "name": "旧场景3", "order_num": 2, "clip_materials": [visual(70300, 0)]},
                    ],
                },
                {
                    "id": 102,
                    "clips": [
                        {"id": 7001, "name": "旧场景1", "order_num": 0, "clip_materials": [visual(70100, 0)]},
                    ],
                },
            ],
        }
        self.reference = {
            "id": 38336,
            "name": "只读参考直播间",
            "status": 1,
            "_assetgraph_read_environment": "working",
            "topics": [
                {"id": 201, "clips": []},
                {"id": 202, "clips": []},
                {"id": 203, "clips": []},
                {"id": 204, "clips": []},
                {
                    "id": 205,
                    "clips": [
                        reference_clip(390068, 8),
                        reference_clip(390069, 9),
                        reference_clip(390070, 8),
                    ],
                },
            ],
        }

    def read_live_room(self, live_room_id: str) -> dict[str, Any]:
        self.calls.append(("read_live_room", live_room_id))
        if live_room_id == "41172":
            return copy.deepcopy(self.target)
        if live_room_id == "38336":
            return copy.deepcopy(self.reference)
        raise AssertionError(f"unexpected room id {live_room_id}")

    def delete_clip(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_clip", dict(kwargs)))
        assert kwargs["expected_live_room_title"] == self.target["name"]
        for topic in self.target["topics"]:
            topic["clips"] = [clip for clip in topic["clips"] if clip["id"] != kwargs["clip_id"]]
        return {"verified": True, "clip_id": kwargs["clip_id"], "go_live_clicked": False}

    def clear_clip_materials(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("clear_clip_materials", dict(kwargs)))
        clip = self._target_clip(kwargs["clip_id"])
        deleted = [material["id"] for material in clip["clip_materials"]]
        clip["clip_materials"] = []
        return {"verified": True, "deleted_material_ids": deleted, "go_live_clicked": False}

    def rename_clip(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("rename_clip", dict(kwargs)))
        clip = self._target_clip(kwargs["clip_id"])
        clip["name"] = kwargs["name"]
        if kwargs.get("order_num") is not None:
            clip["order_num"] = kwargs["order_num"]
        return {"verified": True, "clip_id": clip["id"], "name": clip["name"], "go_live_clicked": False}

    def create_scene(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_scene", dict(kwargs)))
        topic = next(topic for topic in self.target["topics"] if topic["id"] == kwargs["topic_id"])
        clip = {
            "id": self.next_clip_id,
            "name": kwargs["scene_name"],
            "order_num": kwargs["scene_index"],
            "topic_id": topic["id"],
            "clip_materials": [],
        }
        self.next_clip_id += 1
        topic["clips"].append(clip)
        return {"verified": True, "clip_id": clip["id"], "name": clip["name"], "go_live_clicked": False}

    def fill_clip_from_template(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("fill_clip_from_template", dict(kwargs)))
        source = self._reference_clip(int(kwargs["reference_clip_id"]))
        target = self._target_clip(kwargs["target_clip_id"])
        assert kwargs["script_content"] is None
        target["clip_materials"] = []
        for operation in kwargs["component_operations"]:
            source_material = source["clip_materials"][operation["component_index"]]
            copied = copy.deepcopy(source_material)
            copied["id"] = self.next_material_id
            copied["clip_id"] = target["id"]
            if operation.get("z_index") is not None:
                copied["layer_n"] = operation["z_index"]
                copied["style_front"]["zIndex"] = operation["z_index"]
            self.next_material_id += 1
            target["clip_materials"].append(copied)
        return {"visual_count": len(target["clip_materials"]), "text_count": 0, "go_live_clicked": False}

    def write_script(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("write_script", dict(kwargs)))
        clip = self._target_clip(kwargs["clip_id"])
        clip["clip_materials"] = [material for material in clip["clip_materials"] if material["type"] != "text"]
        clip["clip_materials"].append(
            {"id": self.next_material_id, "type": "text", "content": kwargs["script_text"]}
        )
        self.next_material_id += 1
        return {"verified": True, "script_content_verified": True, "go_live_clicked": False}

    def verify_scene(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("verify_scene", dict(kwargs)))
        clip = self._target_clip(kwargs["clip_id"])
        operation = kwargs["operation"]
        assert clip["name"] == kwargs["scene_name"]
        assert len(operation["expected_layers"]) == operation["expected_visual_count"]
        assert next(material for material in clip["clip_materials"] if material["type"] == "text")["content"] == operation["expected_script_text"]
        return {"verified": True, "verification_source": "working_room_readback", "go_live_clicked": False}

    def _target_clip(self, clip_id: int) -> dict[str, Any]:
        return next(
            clip
            for topic in self.target["topics"]
            for clip in topic["clips"]
            if clip["id"] == clip_id
        )

    def _reference_clip(self, clip_id: int) -> dict[str, Any]:
        return next(
            clip
            for topic in self.reference["topics"]
            for clip in topic["clips"]
            if clip["id"] == clip_id
        )


def test_rebuild_resets_global_clips_and_rebuilds_8_9_8_layers_from_later_reference_topic() -> None:
    session = FakeRebuildSession()
    spec = MaituTestRoomRebuildSpec.from_dict(rebuild_payload())

    result = MaituTestRoomRebuildRunner(session=session).run(spec)

    assert result.status == "completed"
    assert result.failure_count == 0
    assert result.keeper_clip_id == 7001
    assert result.go_live_clicked is False
    assert result.ready_for_go_live is False
    assert [call[1]["clip_id"] for call in session.calls if call[0] == "delete_clip"] == [7002, 7003]
    create_calls = [call[1] for call in session.calls if call[0] == "create_scene"]
    assert [call["topic_id"] for call in create_calls] == [102, 102]
    fill_calls = [call[1] for call in session.calls if call[0] == "fill_clip_from_template"]
    assert [len(call["component_operations"]) for call in fill_calls] == [8, 9, 8]
    assert [call["reference_clip_id"] for call in fill_calls] == ["390068", "390069", "390070"]
    copied_visual = session.target["topics"][1]["clips"][0]["clip_materials"][0]
    assert copied_visual["left"] == 106
    assert copied_visual["style_front"]["left"] == 43.196
    first_verify = next(call[1] for call in session.calls if call[0] == "verify_scene")
    expected_layer = first_verify["operation"]["expected_layers"][0]
    assert expected_layer["left"] == 106.0
    assert expected_layer["style_front"]["left"] == 43.196
    assert expected_layer["style_front"]["transform"] == {"rotation": 0.0, "scale": 1.0}
    assert [clip["name"] for clip in sorted(session.target["topics"][1]["clips"], key=lambda item: item["order_num"])] == [
        "开场介绍",
        "产品讲解",
        "场景收束",
    ]
    assert all(action.details.get("go_live_clicked") is not True for action in result.actions)


def test_planned_component_order_overrides_bad_reference_stack_and_is_verified() -> None:
    payload = rebuild_payload()
    payload["scenes"] = [
        {
            "scene_name": "产品讲解",
            "reference_clip_id": "390069",
            "script_text": "现在介绍张裕品酒大师PRO。",
            "component_operations": [
                {
                    "component_index": component_index,
                    "z_index": z_index,
                    "expected_layer_id": f"模板层-{component_index:02d}",
                    "expected_source_material_id": 50000 + component_index,
                }
                for z_index, component_index in enumerate([0, 8, 1, 2, 3, 4, 5, 6, 7], start=1)
            ],
        }
    ]
    session = FakeRebuildSession()

    result = MaituTestRoomRebuildRunner(session=session).run(MaituTestRoomRebuildSpec.from_dict(payload))

    assert result.status == "completed"
    clip = session.target["topics"][1]["clips"][0]
    visuals = [material for material in clip["clip_materials"] if material["type"] != "text"]
    assert [material["name"] for material in visuals] == [
        "模板层-00",
        "模板层-08",
        "模板层-01",
        "模板层-02",
        "模板层-03",
        "模板层-04",
        "模板层-05",
        "模板层-06",
        "模板层-07",
    ]
    assert [material["layer_n"] for material in visuals] == list(range(1, 10))
    assert [material["style_front"]["zIndex"] for material in visuals] == list(range(1, 10))


def test_spec_rejects_duplicate_or_incomplete_planned_stack() -> None:
    payload = rebuild_payload()
    payload["scenes"][0].pop("visual_count")
    payload["scenes"][0]["component_operations"] = [
        {"component_index": 0, "z_index": 1},
        {"component_index": 0, "z_index": 1},
    ]

    with pytest.raises(ValueError, match="select every reference component exactly once"):
        MaituTestRoomRebuildSpec.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", 1, "currently live"),
        ("latest_live_time", "2026-07-31T10:00:00Z", "live-session trace"),
        ("name", "另一个房间", "expected_title"),
        ("_assetgraph_read_environment", "published", "working environment"),
    ],
)
def test_target_preflight_failure_causes_zero_mutations(field: str, value: Any, message: str) -> None:
    session = FakeRebuildSession()
    session.target[field] = value

    result = MaituTestRoomRebuildRunner(session=session).run(MaituTestRoomRebuildSpec.from_dict(rebuild_payload()))

    assert result.status == "failed"
    assert message in result.actions[-1].summary
    assert [name for name, _details in session.calls] == ["read_live_room"]


def test_missing_later_topic_reference_clip_blocks_before_any_delete() -> None:
    session = FakeRebuildSession()
    session.reference["topics"][4]["clips"] = session.reference["topics"][4]["clips"][:1]

    result = MaituTestRoomRebuildRunner(session=session).run(MaituTestRoomRebuildSpec.from_dict(rebuild_payload()))

    assert result.status == "failed"
    assert "reference clip '390069' is missing" in result.actions[-1].summary
    assert not any(name in {"delete_clip", "clear_clip_materials"} for name, _details in session.calls)


def test_reference_visual_count_mismatch_blocks_before_any_delete() -> None:
    session = FakeRebuildSession()
    session.reference["topics"][4]["clips"][1]["clip_materials"].pop()

    result = MaituTestRoomRebuildRunner(session=session).run(MaituTestRoomRebuildSpec.from_dict(rebuild_payload()))

    assert result.status == "failed"
    assert "has 8 visual layers; scene expects 9" in result.actions[-1].summary
    assert not any(name == "delete_clip" for name, _details in session.calls)


def test_first_delete_failure_stops_without_clear_fill_or_retry() -> None:
    class FailingDeleteSession(FakeRebuildSession):
        def delete_clip(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("delete_clip", dict(kwargs)))
            raise RuntimeError("simulated DELETE failure")

    session = FailingDeleteSession()

    result = MaituTestRoomRebuildRunner(session=session).run(MaituTestRoomRebuildSpec.from_dict(rebuild_payload()))

    assert result.status == "failed"
    assert result.actions[-1].details["retry_attempted"] is False
    assert [name for name, _details in session.calls].count("delete_clip") == 1
    assert not any(name in {"clear_clip_materials", "fill_clip_from_template"} for name, _details in session.calls)


def test_final_visual_drift_fails_against_preflight_reference_snapshot() -> None:
    class DriftingSession(FakeRebuildSession):
        def write_script(self, **kwargs: Any) -> dict[str, Any]:
            result = super().write_script(**kwargs)
            if kwargs["scene_name"] == "场景收束":
                self._target_clip(kwargs["clip_id"])["clip_materials"][0]["material_id"] = 999999
            return result

    result = MaituTestRoomRebuildRunner(session=DriftingSession()).run(
        MaituTestRoomRebuildSpec.from_dict(rebuild_payload())
    )

    assert result.status == "failed"
    assert "differs from the preflight reference snapshot" in result.actions[-1].summary


@pytest.mark.parametrize("drift_source", ["top_level", "style_front"])
def test_top_level_and_style_front_geometry_drift_fail_independently(drift_source: str) -> None:
    class GeometryDriftingSession(FakeRebuildSession):
        def write_script(self, **kwargs: Any) -> dict[str, Any]:
            result = super().write_script(**kwargs)
            if kwargs["scene_name"] == "场景收束":
                material = self._target_clip(kwargs["clip_id"])["clip_materials"][0]
                if drift_source == "top_level":
                    material["width"] += 1
                else:
                    material["style_front"]["width"] += 1
            return result

    result = MaituTestRoomRebuildRunner(session=GeometryDriftingSession()).run(
        MaituTestRoomRebuildSpec.from_dict(rebuild_payload())
    )

    assert result.status == "failed"
    assert "differs from the preflight reference snapshot" in result.actions[-1].summary


@pytest.mark.parametrize("protected_room_id", ["38336", "38995"])
def test_spec_rejects_protected_reference_room_as_target(protected_room_id: str) -> None:
    payload = rebuild_payload()
    payload["target_live_room_id"] = protected_room_id
    payload["reference_room_id"] = "40000"

    with pytest.raises(ValueError, match="protected"):
        MaituTestRoomRebuildSpec.from_dict(payload)


@pytest.mark.parametrize("missing_key", ["target_live_room_id", "expected_title", "reference_room_id"])
def test_spec_requires_explicit_canonical_room_identity(missing_key: str) -> None:
    payload = rebuild_payload()
    payload.pop(missing_key)

    with pytest.raises(ValueError, match=missing_key):
        MaituTestRoomRebuildSpec.from_dict(payload)

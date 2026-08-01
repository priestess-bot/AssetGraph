from __future__ import annotations

import copy

import pytest

from browser_use_worker.functional_test_draft import (
    enable_test_pending_rights_plan,
    reset_allowlisted_test_room,
    room_inspection_fingerprint,
)
from browser_use_worker.functional_draft_verification import verify_functional_draft
from browser_use_worker.room_inspection import inspect_working_room


class ResetSession:
    def __init__(self):
        self.room = {
            "id": 41172,
            "name": "asser测试",
            "status": 0,
            "live_session_id": None,
            "latest_live_time": None,
            "_assetgraph_read_environment": "working",
            "topics": [{"clips": [
                {"id": 10, "name": "一", "order_num": 0, "clip_materials": [{"id": 1}]},
                {"id": 11, "name": "二", "order_num": 1, "clip_materials": [{"id": 2}]},
            ]}],
        }

    def read_live_room(self, live_room_id: str):
        return copy.deepcopy(self.room)

    def delete_clip(self, *, live_room_id, clip_id, expected_live_room_title):
        self.room["topics"][0]["clips"] = [
            item for item in self.room["topics"][0]["clips"] if item["id"] != clip_id
        ]
        return {"verified": True}

    def clear_clip_materials(self, *, live_room_id, clip_id, expected_live_room_title):
        self.room["topics"][0]["clips"][0]["clip_materials"] = []
        return {
            "status": "cleared",
            "live_room_id": live_room_id,
            "clip_id": clip_id,
            "deleted_material_ids": [1],
            "remaining_material_count": 0,
            "verified": True,
            "verification_source": "working_room_readback",
            "not_live": True,
            "go_live_clicked": False,
            "responses": [
                {
                    "id": "99999999-9999-4999-8999-999999999999",
                    "url": "https://cdn.example/c0e43436b45ba39d9a6470221271142103b74a75.png",
                    "token": "must-not-persist",
                }
            ],
        }


def test_replace_mode_checks_fingerprint_then_keeps_one_empty_scene() -> None:
    session = ResetSession()
    inspection = inspect_working_room(
        session, target_live_room_id="41172", expected_title="asser测试"
    )
    stages = []
    evidence = reset_allowlisted_test_room(
        session,
        job_payload={
            "execution_mode": "replace_test_draft",
            "build_plan": {"target_live_room_id": "41172", "expected_title": "asser测试"},
            "expected_room_fingerprint": room_inspection_fingerprint(inspection),
            "confirmed_scene_ids": ["10", "11"],
        },
        progress=lambda *args: stages.append(args),
    )
    assert evidence["keeper_scene_id"] == "10"
    assert evidence["deleted_scene_ids"] == ["11"]
    assert evidence["clear_result"] == {
        "status": "cleared",
        "live_room_id": "41172",
        "clip_id": 10,
        "remaining_material_count": 0,
        "verified": True,
        "verification_source": "working_room_readback",
        "not_live": True,
        "go_live_clicked": False,
        "deleted_material_ids": [1],
    }
    assert "responses" not in evidence["clear_result"]
    assert session.room["topics"][0]["clips"][0]["clip_materials"] == []
    assert stages[0][0] == "clearing_draft"


def test_replace_mode_rejects_stale_fingerprint_before_mutation() -> None:
    session = ResetSession()
    with pytest.raises(ValueError, match="changed"):
        reset_allowlisted_test_room(
            session,
            job_payload={
                "build_plan": {"target_live_room_id": "41172", "expected_title": "asser测试"},
                "expected_room_fingerprint": "0" * 64,
                "confirmed_scene_ids": ["10", "11"],
            },
            progress=lambda *_args: None,
        )
    assert len(session.room["topics"][0]["clips"]) == 2


def test_test_rights_exception_never_waives_other_blockers() -> None:
    payload = {
        "execution_mode": "replace_test_draft",
        "test_use_acknowledged": True,
        "non_releasable": True,
    }
    normalized = enable_test_pending_rights_plan(
        {"status": "blocked", "can_execute": False, "blocked_reasons": ["asset_rights_not_approved:A:pending"]},
        job_payload=payload,
    )
    assert normalized["status"] == "ready"
    assert normalized["non_releasable"] is True
    with pytest.raises(ValueError, match="non-rights"):
        enable_test_pending_rights_plan(
            {"blocked_reasons": ["missing_material:A"]}, job_payload=payload
        )


def test_final_readback_requires_contiguous_layers_and_rejects_video_on_top() -> None:
    session = ResetSession()
    session.room["topics"][0]["clips"] = [
        {
            "id": 10,
            "name": "开场",
            "order_num": 0,
            "clip_materials": [
                {"id": 1, "name": "background", "type": "image", "material_id": 101, "url": "https://cdn.example/background.png?x-oss-process=style/max_width_1080", "layer_n": 1, "sound_enabled": False, "play_mode": None, "style_front": {"left": 0, "top": 0, "width": 1080, "height": 1920, "zIndex": 1, "fit": "cover", "transform": {"rotation": 0}}},
                {"id": 2, "name": "product", "type": "decorative_video", "material_id": 102, "url": "https://cdn.example/product.mp4", "layer_n": 2, "sound_enabled": False, "play_mode": "loop", "style_front": "{\"left\":100,\"top\":300,\"width\":800,\"height\":500,\"zIndex\":2,\"fit\":\"contain\",\"transform\":{\"rotation\":0}}"},
                {"id": 3, "name": "title", "type": "image", "material_id": 103, "url": "https://cdn.example/title.png", "layer_n": 3, "sound_enabled": False, "play_mode": None, "style_front": {"left": 100, "top": 20, "width": 800, "height": 200, "zIndex": 3, "fit": "contain", "transform": {"rotation": 0}}},
                {"id": 4, "type": "text", "content": "欢迎来到直播间"},
            ],
        }
    ]
    plan = {
        "operations": [
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "background",
                "layer_type": "background",
                "source_material_type": "image",
                "material_id": 101,
                "source_material_url": "https://cdn.example/background.png",
                "x": 0,
                "y": 0,
                "width": 1080,
                "height": 1920,
                "z_index": 1,
                "fit": "cover",
                "rotation": 0,
                "loop": False,
                "muted": True,
            },
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "product",
                "layer_type": "product_display",
                "source_material_type": "decorative_video",
                "material_id": 102,
                "source_material_url": "https://cdn.example/product.mp4",
                "x": 100,
                "y": 300,
                "width": 800,
                "height": 500,
                "z_index": 2,
                "fit": "contain",
                "rotation": 0,
                "loop": True,
                "muted": True,
            },
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "title",
                "layer_type": "brand_title",
                "source_material_type": "image",
                "material_id": 103,
                "source_material_url": "https://cdn.example/title.png",
                "x": 100,
                "y": 20,
                "width": 800,
                "height": 200,
                "z_index": 3,
                "fit": "contain",
                "rotation": 0,
                "loop": False,
                "muted": True,
            },
            {"operation_type": "write_script", "scene_index": 0, "script_text": "欢迎来到直播间"},
            {"operation_type": "verify_scene", "scene_index": 0, "scene_name": "开场"},
        ]
    }
    verification, layers = verify_functional_draft(
        session,
        operation_plan=plan,
        target_live_room_id="41172",
        expected_title="asser测试",
    )
    assert verification["matched"] is True
    assert layers["video_never_highest"] is True
    assert layers["exact_expected_order"] is True
    assert layers["exact_geometry_and_source"] is True

    background_style = session.room["topics"][0]["clips"][0]["clip_materials"][0][
        "style_front"
    ]
    background_style["left"] = 1
    with pytest.raises(ValueError, match="geometry mismatch"):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )
    background_style["left"] = 0

    session.room["topics"][0]["clips"][0]["clip_materials"][0]["layer_n"] = 2
    session.room["topics"][0]["clips"][0]["clip_materials"][1]["layer_n"] = 1
    with pytest.raises(ValueError, match="exact layer order mismatch"):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )
    session.room["topics"][0]["clips"][0]["clip_materials"][0]["layer_n"] = 1
    session.room["topics"][0]["clips"][0]["clip_materials"][1]["layer_n"] = 2

    session.room["topics"][0]["clips"][0]["clip_materials"][2]["material_id"] = 999
    with pytest.raises(ValueError, match="source id mismatch"):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )
    session.room["topics"][0]["clips"][0]["clip_materials"][2]["material_id"] = 103

    session.room["topics"][0]["clips"][0]["clip_materials"][2]["type"] = "decorative_video"
    plan["operations"][2]["layer_type"] = "decoration_foreground"
    plan["operations"][2]["source_material_type"] = "decorative_video"
    with pytest.raises(ValueError, match="video at the highest"):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sound_enabled", True, "mute mismatch"),
        ("play_mode", "loop", "loop mismatch"),
    ],
)
def test_final_readback_rejects_audio_policy_drift(
    field: str,
    value: object,
    message: str,
) -> None:
    session = ResetSession()
    session.room["topics"][0]["clips"] = [
        {
            "id": 10,
            "name": "开场",
            "order_num": 0,
            "clip_materials": [
                {
                    "id": 1,
                    "name": "background",
                    "type": "image",
                    "material_id": 101,
                    "url": "https://cdn.example/background.png",
                    "layer_n": 1,
                    "sound_enabled": False,
                    "play_mode": None,
                    "style_front": {"left": 0, "top": 0, "width": 1080, "height": 1920, "zIndex": 1, "fit": "cover", "transform": {"rotation": 0}},
                },
                {"id": 2, "type": "text", "content": "测试"},
            ],
        }
    ]
    session.room["topics"][0]["clips"][0]["clip_materials"][0][field] = value
    plan = {
        "operations": [
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "background",
                "layer_type": "background",
                "source_material_type": "image",
                "material_id": 101,
                "source_material_url": "https://cdn.example/background.png",
                "x": 0,
                "y": 0,
                "width": 1080,
                "height": 1920,
                "z_index": 1,
                "fit": "cover",
                "rotation": 0,
                "loop": False,
                "muted": True,
            },
            {
                "operation_type": "write_script",
                "scene_index": 0,
                "script_text": "测试",
            },
            {
                "operation_type": "verify_scene",
                "scene_index": 0,
                "scene_name": "开场",
            },
        ]
    }

    with pytest.raises(ValueError, match=message):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )


def test_final_readback_requires_complete_digital_human_source_identity() -> None:
    session = ResetSession()
    session.room["topics"][0]["clips"] = [
        {
            "id": 10,
            "name": "开场",
            "order_num": 0,
            "clip_materials": [
                {
                    "id": 1,
                    "name": "host",
                    "type": "digital_human",
                    "material_id": 37200,
                    "url": "https://mtc.maituai.com/image/20260520_011010_cover.png",
                    "speaker_id": 3760,
                    "digital_human_image_id": 7717,
                    "layer_n": 1,
                    "sound_enabled": False,
                    "play_mode": None,
                    "style_front": {
                        "left": 100,
                        "top": 300,
                        "width": 800,
                        "height": 1400,
                        "zIndex": 1,
                        "fit": "contain",
                        "transform": {"rotation": 0},
                    },
                },
                {"id": 2, "type": "text", "content": "测试"},
            ],
        }
    ]
    plan = {
        "operations": [
            {
                "operation_type": "insert_asset_layer",
                "scene_index": 0,
                "layer_id": "host",
                "layer_type": "digital_human",
                "source_material_type": "digital_human",
                "material_id": None,
                "maitu_source_material_id": 37200,
                "source_cover_url": "https://mtc.maituai.com/image/20260520_011010_cover.png",
                "speaker_id": 3760,
                "digital_human_image_id": 7717,
                "x": 100,
                "y": 300,
                "width": 800,
                "height": 1400,
                "z_index": 1,
                "fit": "contain",
                "rotation": 0,
                "loop": False,
                "muted": True,
            },
            {
                "operation_type": "write_script",
                "scene_index": 0,
                "script_text": "测试",
            },
            {
                "operation_type": "verify_scene",
                "scene_index": 0,
                "scene_name": "开场",
            },
        ]
    }

    verification, _layers = verify_functional_draft(
        session,
        operation_plan=plan,
        target_live_room_id="41172",
        expected_title="asser测试",
    )
    assert verification["matched"] is True

    session.room["topics"][0]["clips"][0]["clip_materials"][0]["speaker_id"] = 9999
    with pytest.raises(ValueError, match="speaker_id mismatch"):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )

    material = session.room["topics"][0]["clips"][0]["clip_materials"][0]
    material["speaker_id"] = 3760
    material["material_id"] = 99999
    with pytest.raises(ValueError, match="digital-human source id mismatch"):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )

    material["material_id"] = 37200
    material["url"] = "https://mtc.maituai.com/image/other.png"
    with pytest.raises(ValueError, match="digital-human source URL mismatch"):
        verify_functional_draft(
            session,
            operation_plan=plan,
            target_live_room_id="41172",
            expected_title="asser测试",
        )

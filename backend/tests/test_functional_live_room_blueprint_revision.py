from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.errors import DomainValidationError
from app.services.functional_live_rooms import FunctionalLiveRoomService


def _detail() -> dict:
    return {
        "script": {
            "blocks": [
                {"block_code": "BLOCK-A", "content": "原始开场"},
                {"block_code": "BLOCK-B", "content": "原始讲解"},
            ]
        },
        "shot_list": {
            "shots": [
                {
                    "shot_code": "SHOT-A",
                    "shot_goal": "开场",
                    "script_block_codes": ["BLOCK-A"],
                    "material_role_requirements": ["background"],
                    "estimated_duration_ms": 1_000,
                },
                {
                    "shot_code": "SHOT-B",
                    "shot_goal": "讲解",
                    "script_block_codes": ["BLOCK-B"],
                    "material_role_requirements": ["background"],
                    "estimated_duration_ms": 2_000,
                },
            ]
        },
    }


def _assets() -> list[dict]:
    return [
        {
            "asset_code": "AG-BG-A",
            "material_roles": ["background"],
            "execution_capability": "maitu_bound",
            "constraint_profile_ref": None,
            "qualified_effect_refs": [],
        },
        {
            "asset_code": "AG-BG-B",
            "material_roles": ["background"],
            "execution_capability": "maitu_bound",
            "qualified_effect_refs": [],
            "constraint_profile_ref": {
                "constraints": [
                    {
                        "kind": "size_range",
                        "hard": True,
                        "parameters": {
                            "min_width": 0.1,
                            "max_width": 0.3,
                            "min_height": 0.1,
                            "max_height": 0.5,
                        },
                    }
                ]
            },
        },
    ]


def _scene_overrides() -> list[dict]:
    return [
        {
            "shot_code": "SHOT-B",
            "sort_order": 0,
            "title": "先讲核心价值",
            "script": "调整后的讲解话术",
            "layers": [
                {
                    "role": "background",
                    "asset_code": "AG-BG-B",
                    "geometry": {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.3},
                    "z_order": 20,
                }
            ],
        },
        {
            "shot_code": "SHOT-A",
            "sort_order": 1,
            "title": "再做开场承接",
            "script": "调整后的开场话术",
            "layers": [
                {
                    "role": "background",
                    "asset_code": "AG-BG-A",
                    "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                    "z_order": -10,
                }
            ],
        },
    ]


def test_blueprint_revision_reorders_and_recompiles_scene_inputs() -> None:
    blueprint, build_plan, blocked = FunctionalLiveRoomService._compile(
        _detail(),
        _assets(),
        {
            "target_live_room_id": "room-1",
            "expected_title": "调整后的直播间",
            "scene_overrides": _scene_overrides(),
        },
        variant_code="VARIANT-REVISION",
    )

    assert blocked == []
    assert [scene["shot_code"] for scene in blueprint["scenes"]] == ["SHOT-B", "SHOT-A"]
    assert [scene["script"] for scene in blueprint["scenes"]] == [
        "调整后的讲解话术",
        "调整后的开场话术",
    ]
    assert blueprint["scenes"][0]["layers"][0]["asset_code"] == "AG-BG-B"
    assert blueprint["scenes"][0]["layers"][0]["normalized_geometry"] == {
        "x": 0.1,
        "y": 0.2,
        "width": 0.3,
        "height": 0.3,
    }
    assert blueprint["scenes"][0]["layers"][0]["z_order"] == 20
    assert build_plan["go_live"] is False
    write_operations = [
        operation
        for operation in build_plan["operations"]
        if operation["kind"] == "write_script"
    ]
    assert [operation["script_block_codes"] for operation in write_operations] == [
        ["BLOCK-B"],
        ["BLOCK-A"],
    ]


def test_blueprint_revision_requires_the_complete_source_shot_set() -> None:
    overrides = _scene_overrides()[:1]

    with pytest.raises(DomainValidationError) as invalid:
        FunctionalLiveRoomService._compile(
            _detail(),
            _assets(),
            {
                "target_live_room_id": "room-1",
                "expected_title": "不完整调整",
                "scene_overrides": overrides,
            },
            variant_code="VARIANT-INCOMPLETE",
        )

    assert invalid.value.code == "LIVE_ROOM_BLUEPRINT_SCENE_SET_MISMATCH"
    assert invalid.value.details["missing_shot_codes"] == ["SHOT-A"]


def test_blueprint_revision_rejects_an_asset_outside_the_role_candidates() -> None:
    overrides = _scene_overrides()
    overrides[0]["layers"][0]["asset_code"] = "AG-NOT-SELECTED"

    with pytest.raises(DomainValidationError) as invalid:
        FunctionalLiveRoomService._compile(
            _detail(),
            _assets(),
            {
                "target_live_room_id": "room-1",
                "expected_title": "错误素材调整",
                "scene_overrides": overrides,
            },
            variant_code="VARIANT-ASSET-INVALID",
        )

    assert invalid.value.code == "LIVE_ROOM_MATERIAL_OVERRIDE_INVALID"


def test_blueprint_revision_migration_keeps_source_and_revision_metadata() -> None:
    sql = (
        Path(__file__).parents[1]
        / "migrations"
        / "101_functional_live_room_blueprint_revisions.sql"
    ).read_text(encoding="utf-8")

    assert "revised_from_plan_code" in sql
    assert "revision_context" in sql
    assert "REFERENCES functional_live_room_plans(plan_code)" in sql


def test_recompile_payload_keeps_branch_gap_waivers() -> None:
    source = {
        "project_code": "PROJECT-1",
        "primary_template_code": None,
        "secondary_template_codes": [],
        "selected_asset_codes": ["AG-BG-A"],
        "selected_group_codes": [],
        "selected_material_pack_codes": [],
        "quality_report": {},
        "build_plan": {
            "inventory_snapshot": {
                "asset_gap_refs": [{"gap_code": "GAP-1"}],
                "asset_gap_waivers": {"GAP-1": "本分支采用人工准备素材"},
            }
        },
    }

    payload = FunctionalLiveRoomService._recompile_payload_from_plan(
        source,
        target_live_room_id="room-2",
        expected_title="复制后的直播间",
    )

    assert payload["asset_gap_codes"] == ["GAP-1"]
    assert payload["asset_gap_waivers"] == {"GAP-1": "本分支采用人工准备素材"}


def test_persisted_build_plan_uses_only_draft_actions_and_fixed_asset_codes() -> None:
    class MaituRepositoryStub:
        def create_script_layout_build_plan(
            self, payload: dict, *, plan_name: str
        ) -> dict:
            assert plan_name
            return {**payload, "build_plan_code": "MT-BUILD-TEST"}

    service = object.__new__(FunctionalLiveRoomService)
    service.maitu = MaituRepositoryStub()
    build_plan = service._persist_build_plan(
        detail={"project_code": "CONTENT-1", "revision_number": 3, "title": "测试内容"},
        variant={"variant_code": "VARIANT-1", "revision_number": 2},
        configuration={
            "configuration_code": "CONFIG-1",
            "revision_number": 4,
            "target_live_room_id": "empty-room-1",
            "expected_title": "草稿直播间",
        },
        inventory_snapshot={"asset_codes": ["AG-BG-A"]},
        blueprint={
            "schema_version": "maitu-scene-blueprint.functional.v2",
            "scenes": [
                {
                    "scene_code": "MSB-1",
                    "script": "测试话术",
                    "layers": [
                        {
                            "layer_blueprint_code": "LYR-1",
                            "material_role": "background",
                            "asset_code": "AG-BG-A",
                            "normalized_geometry": {
                                "x": 0.0,
                                "y": 0.0,
                                "width": 1.0,
                                "height": 1.0,
                            },
                            "z_order": 1,
                        }
                    ],
                }
            ],
        },
        blocked_reasons=[],
    )

    allowed = {
        "preflight_content_build_plan",
        "fill_default_scene",
        "create_scene",
        "insert_asset_layer",
        "position_asset_layer",
        "write_script",
        "verify_scene",
        "save_draft",
    }
    assert build_plan["go_live"] is False
    assert {operation["operation_type"] for operation in build_plan["operations"]} <= allowed
    insert = next(
        operation
        for operation in build_plan["operations"]
        if operation["operation_type"] == "insert_asset_layer"
    )
    assert insert["asset_code"] == "AG-BG-A"
    assert insert["layer_id"] == "LYR-1"
    assert build_plan["inventory_snapshot"] == {"asset_codes": ["AG-BG-A"]}

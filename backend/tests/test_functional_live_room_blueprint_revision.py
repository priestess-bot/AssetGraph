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


def _host_asset() -> dict:
    return {
        "asset_code": "AG-HOST-37200",
        "media_kind": "video",
        "material_roles": ["digital_human", "voice"],
        "execution_capability": "maitu_bound",
        "constraint_profile_ref": None,
        "qualified_effect_refs": [],
        "maitu_material_id": None,
        "maitu_source_material_id": 37200,
        "source_material_type": "digital_human",
        "source_material_url": None,
        "source_cover_url": None,
        "speaker_id": 3760,
        "digital_human_image_id": 7717,
    }


def _host_binding() -> dict:
    return {
        "live_room_id": "room-1",
        "material_id": 37200,
        "speaker_id": 3760,
        "digital_human_image_id": 7717,
        "scene_ids": ["1", "2"],
        "scene_names": ["场景 1", "场景 2"],
        "fingerprint_sha256": "a" * 64,
        "asset_code": "AG-HOST-37200",
        "system_managed": True,
    }


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
    assert blueprint["scenes"][0]["layers"][0]["z_order"] == 1
    assert blueprint["scenes"][0]["layers"][0]["constraint_evidence"]["stacking"] == {
        "schema_version": "layer-stacking.v1",
        "policy": "bottom_band_then_relative_dag_then_top_band",
        "stack_position": 1,
        "resolved_z_order": 1,
        "pin_band": "normal",
        "forbid_layer_top": False,
        "hard_predecessors": [],
        "conditional_relations_not_applicable": [],
        "soft_rule_deviations": [],
    }
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


def test_system_host_is_compiled_into_every_scene_and_cannot_be_replaced() -> None:
    payload = {
        "target_live_room_id": "room-1",
        "expected_title": "系统主播测试",
        "system_host_binding": _host_binding(),
    }
    blueprint, _, blocked = FunctionalLiveRoomService._compile(
        _detail(),
        [*_assets(), _host_asset()],
        payload,
        variant_code="VARIANT-SYSTEM-HOST",
    )

    assert blocked == []
    assert blueprint["system_host_binding"]["asset_code"] == "AG-HOST-37200"
    for scene in blueprint["scenes"]:
        host_layers = [
            layer for layer in scene["layers"] if layer.get("system_managed") is True
        ]
        assert len(host_layers) == 1
        assert host_layers[0]["asset_code"] == "AG-HOST-37200"
        assert host_layers[0]["maitu_source_material_id"] == 37200
        assert host_layers[0]["speaker_id"] == 3760
        assert host_layers[0]["digital_human_image_id"] == 7717

    overrides = [
        {
            "shot_code": scene["shot_code"],
            "sort_order": index,
            "title": scene["title"],
            "script": scene["script"],
            "layers": [
                {
                    "role": layer["role"],
                    "asset_code": layer["asset_code"],
                    "geometry": layer["normalized_geometry"],
                    "z_order": layer["z_order"],
                }
                for layer in scene["layers"]
            ],
        }
        for index, scene in enumerate(blueprint["scenes"])
    ]
    host_override = next(
        layer for layer in overrides[0]["layers"] if layer["role"] == "digital_human"
    )
    host_override["asset_code"] = "AG-BG-A"

    with pytest.raises(DomainValidationError) as invalid:
        FunctionalLiveRoomService._compile(
            _detail(),
            [*_assets(), _host_asset()],
            {**payload, "scene_overrides": overrides},
            variant_code="VARIANT-SYSTEM-HOST-REVISED",
        )

    assert invalid.value.code == "LIVE_ROOM_SYSTEM_HOST_LAYER_LOCKED"


def test_system_host_geometry_is_locked_during_blueprint_revision() -> None:
    payload = {
        "target_live_room_id": "room-1",
        "expected_title": "系统主播测试",
        "system_host_binding": _host_binding(),
    }
    blueprint, _, _ = FunctionalLiveRoomService._compile(
        _detail(),
        [*_assets(), _host_asset()],
        payload,
        variant_code="VARIANT-SYSTEM-HOST-GEOMETRY",
    )
    overrides = [
        {
            "shot_code": scene["shot_code"],
            "sort_order": index,
            "title": scene["title"],
            "script": scene["script"],
            "layers": [
                {
                    "role": layer["role"],
                    "asset_code": layer["asset_code"],
                    "geometry": layer["normalized_geometry"],
                    "z_order": layer["z_order"],
                }
                for layer in scene["layers"]
            ],
        }
        for index, scene in enumerate(blueprint["scenes"])
    ]
    host_override = next(
        layer for layer in overrides[0]["layers"] if layer["role"] == "digital_human"
    )
    host_override["geometry"] = {
        **host_override["geometry"],
        "x": host_override["geometry"]["x"] + 0.01,
    }

    with pytest.raises(DomainValidationError) as invalid:
        FunctionalLiveRoomService._compile(
            _detail(),
            [*_assets(), _host_asset()],
            {**payload, "scene_overrides": overrides},
            variant_code="VARIANT-SYSTEM-HOST-GEOMETRY-REVISED",
        )

    assert invalid.value.code == "LIVE_ROOM_SYSTEM_HOST_LAYER_LOCKED"


def test_system_host_is_injected_when_legacy_revision_omits_locked_layer() -> None:
    overrides = _scene_overrides()
    blueprint, _, blocked = FunctionalLiveRoomService._compile(
        _detail(),
        [*_assets(), _host_asset()],
        {
            "target_live_room_id": "room-1",
            "expected_title": "旧分镜迁移",
            "system_host_binding": _host_binding(),
            "scene_overrides": overrides,
        },
        variant_code="VARIANT-LEGACY-HOST-MIGRATION",
    )

    assert blocked == []
    assert all(
        len([layer for layer in scene["layers"] if layer.get("system_managed")]) == 1
        for scene in blueprint["scenes"]
    )


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
                            "visual_properties": {
                                "crop_policy": "cover",
                                "rotation_policy": "locked",
                            },
                            "audio_properties": {
                                "loop_policy": "disabled",
                                "mute_policy": "muted",
                            },
                            "constraint_rules": [
                                {
                                    "kind": "preserve_aspect_ratio",
                                    "hard": True,
                                    "parameters": {},
                                },
                                {
                                    "kind": "crop_policy",
                                    "hard": True,
                                    "parameters": {"policy": "cover"},
                                },
                            ],
                            "constraint_evidence": {"asset_code": "AG-BG-A"},
                        },
                        {
                            "layer_blueprint_code": "LYR-TABLE",
                            "material_role": "set_surface",
                            "asset_code": "AG-TABLE",
                            "normalized_geometry": {
                                "x": 0.0,
                                "y": 0.45,
                                "width": 1.0,
                                "height": 0.55,
                            },
                            "z_order": 2,
                            "constraint_rules": [
                                {
                                    "kind": "provide_named_region",
                                    "hard": True,
                                    "parameters": {
                                        "region": "table_surface",
                                        "rect": [0.0, 0.45, 1.0, 0.55],
                                    },
                                }
                            ],
                        },
                        {
                            "layer_blueprint_code": "LYR-PRODUCT",
                            "material_role": "product_display",
                            "asset_code": "AG-PRODUCT",
                            "normalized_geometry": {
                                "x": 0.3,
                                "y": 0.6,
                                "width": 0.4,
                                "height": 0.4,
                            },
                            "z_order": 3,
                            "constraint_rules": [
                                {
                                    "kind": "require_named_region",
                                    "hard": True,
                                    "parameters": {"region": "table_surface"},
                                }
                            ],
                            "constraint_evidence": {"media_kind": "video"},
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
        "verify_draft_persisted",
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
    assert insert["fit"] == "cover"
    assert insert["preserve_aspect_ratio"] is True
    assert insert["rotation"] == 0.0
    assert insert["loop"] is False
    assert insert["muted"] is True
    assert insert["constraint_evidence"]["maitu_render_contract"] == {
        "schema_version": "maitu-layer-render-contract.v1",
        "material_role": "background",
        "requested_crop_policy": "cover",
        "resolved_fit": "cover",
        "preserve_aspect_ratio": True,
        "rotation_policy": "locked",
        "rotation_degrees": 0.0,
        "loop_policy": "disabled",
        "mute_policy": "muted",
    }
    product_insert = next(
        operation
        for operation in build_plan["operations"]
        if operation["operation_type"] == "insert_asset_layer"
        and operation["layer_id"] == "LYR-PRODUCT"
    )
    product_position = next(
        operation
        for operation in build_plan["operations"]
        if operation["operation_type"] == "position_asset_layer"
        and operation["layer_id"] == "LYR-PRODUCT"
    )
    assert product_insert["fit"] == "contain"
    assert product_insert["loop"] is True
    assert product_insert["muted"] is True
    assert (product_position["x"], product_position["y"]) == (324.0, 1152.0)
    assert product_position["z_index"] == 3
    assert build_plan["inventory_snapshot"] == {"asset_codes": ["AG-BG-A"]}


def test_persisted_build_plan_freezes_system_host_native_identity() -> None:
    class MaituRepositoryStub:
        def create_script_layout_build_plan(
            self, payload: dict, *, plan_name: str
        ) -> dict:
            assert plan_name
            return {**payload, "build_plan_code": "MT-BUILD-HOST"}

    service = object.__new__(FunctionalLiveRoomService)
    service.maitu = MaituRepositoryStub()
    build_plan = service._persist_build_plan(
        detail={"project_code": "CONTENT-1", "revision_number": 1, "title": "测试"},
        variant={"variant_code": "VARIANT-1", "revision_number": 1},
        configuration={
            "configuration_code": "CONFIG-1",
            "revision_number": 1,
            "target_live_room_id": "room-1",
            "expected_title": "asser测试",
        },
        inventory_snapshot={
            "asset_codes": ["AG-HOST-37200"],
            "assets": [_host_asset()],
            "system_host_binding": _host_binding(),
        },
        blueprint={
            "schema_version": "maitu-scene-blueprint.functional.v2",
            "scenes": [
                {
                    "scene_code": "MSB-HOST-1",
                    "script": "测试话术",
                    "layers": [
                        {
                            "layer_blueprint_code": "LYR-HOST-1",
                            "material_role": "digital_human",
                            "asset_code": "AG-HOST-37200",
                            "normalized_geometry": {
                                "x": 0.08,
                                "y": 0.18,
                                "width": 0.36,
                                "height": 0.64,
                            },
                            "z_order": 1,
                            "constraint_evidence": {
                                "media_kind": "video",
                                "system_managed": True,
                            },
                        }
                    ],
                }
            ],
        },
        blocked_reasons=[],
    )

    insert = next(
        operation
        for operation in build_plan["operations"]
        if operation["operation_type"] == "insert_asset_layer"
    )
    assert insert["asset_code"] == "AG-HOST-37200"
    assert insert["maitu_material_id"] is None
    assert insert["maitu_source_material_id"] == 37200
    assert insert["material_id"] is None
    assert insert["source_material_type"] == "digital_human"
    assert insert["speaker_id"] == 3760
    assert insert["digital_human_image_id"] == 7717

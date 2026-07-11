from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.routes import maitu
from app.main import app
from app.repositories.maitu import (
    MaituMaterialSlotRepository,
    RetryCheckpointConflictError,
    RetryExecutionConflictError,
    RetryLeaseConflictError,
)


class FakeMaituMaterialSlotRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.executions: dict[str, dict[str, Any]] = {}
        self.retry_tasks: dict[str, dict[str, Any]] = {}
        self.retry_execution_receipts: dict[str, dict[str, Any]] = {}
        self.retry_operation_checkpoints: dict[tuple[str, str], dict[str, Any]] = {}
        self.retry_operation_reconciliations: dict[str, dict[str, Any]] = {}
        self.blueprints: dict[str, dict[str, Any]] = {}
        self.template_scenes: dict[str, dict[str, Any]] = {}
        self.template_components: dict[str, list[dict[str, Any]]] = {}
        self.build_plans: dict[str, dict[str, Any]] = {}
        self.build_plan_executions: dict[str, dict[str, Any]] = {}
        self.jd_metric_sessions: dict[str, dict[str, Any]] = {}
        self.jd_metric_samples: dict[str, list[dict[str, Any]]] = {}
        self.layout_adjustments: dict[str, dict[str, Any]] = {}
        self.assets: list[dict[str, Any]] = [
            {
                "asset_code": "AG-IMG-20260707-000001",
                "asset_type": "IMG",
                "title": "胶原蛋白商品主图-白底款",
                "original_filename": "collagen-main.png",
                "display_code": "MT-IMG-0001",
                "local_file_code": "MT-IMG-0001",
                "browser_use_hint": "用于麦兔图片素材选择：胶原蛋白商品主图",
                "local_relative_path": "图片/MT-IMG-0001_胶原蛋白商品主图.png",
                "maitu_category": "product_image",
                "maitu_project_code": "MT-PROJ-20260707-000001",
                "maitu_scene_name": "京东空白直播间",
                "maitu_layer_name": "layer_8",
                "maitu_slot_name": "商品主图",
                "maitu_slot_code": "MT-SLOT-20260707-000001",
                "layer_width": 460,
                "layer_height": 460,
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-IMG-20260707-000002",
                "asset_type": "IMG",
                "title": "通用商品图",
                "original_filename": "product-generic.png",
                "maitu_category": "product_image",
                "maitu_project_code": None,
                "maitu_scene_name": None,
                "maitu_layer_name": None,
                "maitu_slot_name": None,
                "maitu_slot_code": None,
                "layer_width": None,
                "layer_height": None,
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-IMG-20260710-000101",
                "asset_type": "IMG",
                "title": "龙谕龙8商品主图-整箱瓶身",
                "original_filename": "longyu-long8-product.png",
                "display_code": "MT-IMG-LONGYU8",
                "local_file_code": "MT-IMG-LONGYU8",
                "browser_use_hint": "用于麦兔商品图素材选择：龙谕龙8 瓶身和整箱主图",
                "local_relative_path": "图片/MT-IMG-LONGYU8_龙谕龙8商品主图.png",
                "maitu_category": "product_image",
                "subject": "龙谕龙8",
                "usage": "商品主图",
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-IMG-20260710-000102",
                "asset_type": "IMG",
                "title": "宁夏贺兰山东麓葡萄园产区背景",
                "original_filename": "ningxia-helan-vineyard-bg.png",
                "display_code": "MT-BG-HELANS",
                "local_file_code": "MT-BG-HELANS",
                "browser_use_hint": "用于麦兔背景素材选择：宁夏贺兰山东麓葡萄园产区背景",
                "local_relative_path": "背景/MT-BG-HELANS_宁夏贺兰山东麓葡萄园.png",
                "maitu_category": "background_image",
                "maitu_type": "背景",
                "subject": "宁夏 贺兰山东麓 葡萄园",
                "usage": "产区背景",
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-IMG-20260710-000103",
                "asset_type": "IMG",
                "title": "商品卡优惠下单提示贴片",
                "original_filename": "promo-product-card.png",
                "display_code": "MT-STICKER-PROMO",
                "local_file_code": "MT-STICKER-PROMO",
                "browser_use_hint": "用于麦兔贴片素材选择：优惠 商品卡 下单提示",
                "local_relative_path": "贴片/MT-STICKER-PROMO_商品卡优惠.png",
                "maitu_category": "floating_sticker",
                "maitu_type": "贴片",
                "subject": "优惠 商品卡 下单",
                "usage": "促单贴片",
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-VID-20260710-000104",
                "asset_type": "VID",
                "title": "龙谕龙8酒体倒酒品鉴视频",
                "original_filename": "longyu-long8-tasting.mp4",
                "display_code": "MT-VID-LONGYU8",
                "local_file_code": "MT-VID-LONGYU8",
                "browser_use_hint": "用于麦兔视频素材选择：龙谕龙8 酒体 倒酒 品鉴",
                "local_relative_path": "视频/MT-VID-LONGYU8_龙谕龙8品鉴.mp4",
                "maitu_category": "product_video",
                "subject": "龙谕龙8 酒体 口感",
                "usage": "品鉴视频",
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-VID-20260710-000105",
                "asset_type": "VID",
                "title": "张裕主播数字人",
                "original_filename": "changyu-host-avatar.mp4",
                "display_code": "MT-DH-CHANGYU",
                "local_file_code": "MT-DH-CHANGYU",
                "browser_use_hint": "用于麦兔数字人素材选择：张裕主播数字人",
                "local_relative_path": "数字人/MT-DH-CHANGYU_张裕主播.mp4",
                "maitu_category": "digital_human_video",
                "subject": "张裕 主播 数字人",
                "usage": "主播讲解",
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-VID-20260709-000052",
                "asset_type": "VID",
                "title": "视频 - 商品讲解视频 - 品酒大师PRO",
                "original_filename": "MT-VID-0024_品酒大师PRO.mp4",
                "display_code": "MT-VID-0024",
                "local_file_code": "MT-VID-0024",
                "browser_use_hint": "用于麦兔视频素材选择：品酒大师PRO 商品讲解视频",
                "local_relative_path": "视频/MT-VID-0024_品酒大师PRO.mp4",
                "maitu_category": "product_video",
                "maitu_project_code": None,
                "maitu_scene_name": None,
                "maitu_layer_name": None,
                "maitu_slot_name": None,
                "maitu_slot_code": None,
                "layer_width": None,
                "layer_height": None,
                "replacement_policy": "keep_layout",
                "match_score": 0.94,
                "match_reasons": ["maitu_category matches required_category: product_video", "script context mentions 品酒大师PRO"],
            },
            {
                "asset_code": "AG-IMG-20260709-000041",
                "asset_type": "IMG",
                "title": "模板 - 模板预览 - 张裕618背景_preview",
                "original_filename": "MT-TPL-0001_模板_模板预览_张裕618背景_preview.png",
                "display_code": "MT-TPL-0001",
                "local_file_code": "MT-TPL-0001",
                "browser_use_hint": "模板预览图，只能作为风格索引，不能直接作为直播间图层素材",
                "local_relative_path": "模板/302_张裕618背景/MT-TPL-0001_模板_模板预览_张裕618背景_preview.png",
                "maitu_category": "background_image",
                "maitu_type": "模板",
                "usage": "模板预览",
                "subject": "张裕618背景_preview",
                "replacement_policy": "keep_layout",
            },
            {
                "asset_code": "AG-IMG-20260709-000070",
                "asset_type": "IMG",
                "title": "背景 - 张裕品酒大师主视觉背景",
                "original_filename": "MT-BG-0001_张裕品酒大师主视觉背景.png",
                "display_code": "MT-BG-0001",
                "local_file_code": "MT-BG-0001",
                "browser_use_hint": "用于麦兔背景素材选择：张裕品酒大师主视觉背景",
                "local_relative_path": "背景/MT-BG-0001_张裕品酒大师主视觉背景.png",
                "maitu_category": "background_image",
                "maitu_type": "背景",
                "usage": "直播背景",
                "subject": "张裕品酒大师",
                "replacement_policy": "keep_layout",
            },
        ]

    @staticmethod
    def _is_direct_layer_forbidden_template_asset(asset: dict[str, Any], layer: dict[str, Any]) -> bool:
        layer_role = str(layer.get("layer_role") or "").lower()
        required_category = str(layer.get("required_category") or "").lower()
        if "template" in layer_role or required_category in {"template", "template_style", "template_index"}:
            return False
        marker_text = " ".join(
            str(asset.get(field) or "")
            for field in ("display_code", "local_file_code", "maitu_type", "usage", "title", "original_filename", "local_relative_path")
        ).lower()
        return "mt-tpl" in marker_text or "模板" in marker_text and "预览" in marker_text

    def import_reference_blueprint(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = payload["reference_profile"]
        blueprint = payload["blueprint"]
        code = blueprint["blueprint_code"]
        row = {
            "id": f"86000000-0000-0000-0000-{len(self.blueprints) + 1:012d}",
            "blueprint_code": code,
            "reference_profile_code": profile["profile_code"],
            "title": blueprint["title"],
            "platform": blueprint.get("platform"),
            "room_type": blueprint.get("room_type", "reference_rebuild"),
            "reference_room_id": blueprint.get("reference_room_id") or profile.get("reference_room_id"),
            "reference_room_name": blueprint.get("reference_room_name") or profile.get("reference_room_name"),
            "status": blueprint.get("status", "draft"),
            "description": blueprint.get("description"),
            "scenes": blueprint.get("scenes", []),
            "script_blocks": blueprint.get("script_blocks", []),
            "material_tabs": blueprint.get("material_tabs", []),
            "workbench_tabs": blueprint.get("workbench_tabs", []),
            "safety_rules": blueprint.get("safety_rules", []),
            "template_library_code": blueprint.get("template_library_code"),
            "reference_profile": profile,
            "created_at": None,
            "updated_at": None,
        }
        self.blueprints[code] = row
        self._rebuild_template_index(row)
        return row

    def list_live_room_blueprints(
        self,
        *,
        reference_room_id: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.blueprints.values())
        if reference_room_id is not None:
            rows = [row for row in rows if row.get("reference_room_id") == reference_room_id]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        if q:
            needle = q.lower()

            def matches(row: dict[str, Any]) -> bool:
                haystack = "\n".join(
                    str(part)
                    for part in (
                        row.get("blueprint_code"),
                        row.get("title"),
                        row.get("reference_room_id"),
                        row.get("reference_room_name"),
                        row.get("description"),
                        json.dumps(row.get("scenes") or [], ensure_ascii=False),
                        json.dumps(row.get("script_blocks") or [], ensure_ascii=False),
                        json.dumps(row.get("reference_profile") or {}, ensure_ascii=False),
                    )
                    if part is not None
                ).lower()
                return needle in haystack

            rows = [row for row in rows if matches(row)]
        return rows[offset : offset + limit]

    def list_live_room_template_scenes(
        self,
        *,
        blueprint_code: str | None = None,
        reference_room_id: str | None = None,
        template_library_code: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.template_scenes.values())
        if blueprint_code is not None:
            rows = [row for row in rows if row["blueprint_code"] == blueprint_code]
        if reference_room_id is not None:
            rows = [row for row in rows if self.blueprints[row["blueprint_code"]].get("reference_room_id") == reference_room_id]
        if template_library_code is not None:
            rows = [row for row in rows if row.get("template_library_code") == template_library_code]
        if status is not None:
            rows = [row for row in rows if self.blueprints[row["blueprint_code"]].get("status") == status]
        if q:
            needle = q.lower()
            rows = [
                row
                for row in rows
                if needle
                in "\n".join(
                    str(part)
                    for part in (
                        row.get("scene_template_code"),
                        row.get("scene_name"),
                        row.get("reference_product_name"),
                        row.get("script_content"),
                    )
                    if part is not None
                ).lower()
            ]
        rows.sort(key=lambda row: (row.get("sort_order") or 999999, row["scene_template_code"]))
        return rows[offset : offset + limit]

    def list_live_room_template_scene_components(self, scene_template_code: str) -> list[dict[str, Any]] | None:
        if scene_template_code not in self.template_scenes:
            return None
        rows = list(self.template_components.get(scene_template_code, []))
        rows.sort(key=lambda row: (row.get("sort_order") or 999999, row.get("z_index") or 999999, row["component_template_code"]))
        return rows

    def _rebuild_template_index(self, blueprint: dict[str, Any]) -> None:
        blueprint_code = blueprint["blueprint_code"]
        for scene_code in [code for code, row in self.template_scenes.items() if row["blueprint_code"] == blueprint_code]:
            self.template_scenes.pop(scene_code, None)
            self.template_components.pop(scene_code, None)
        template_library_code = blueprint.get("template_library_code") or blueprint.get("reference_profile", {}).get("template_library_code")
        script_blocks_by_scene = {
            str(block.get("scene_name")): block
            for block in blueprint.get("script_blocks", [])
            if block.get("scene_name")
        }
        for scene_index, scene in enumerate(blueprint.get("scenes", [])):
            scene_template_code = str(scene.get("scene_code") or f"{blueprint_code}-SCENE-{scene_index + 1:03d}")
            scene_name = str(scene.get("scene_name") or f"场景{scene_index + 1:02d}")
            script_block = script_blocks_by_scene.get(scene_name, {})
            layers = scene.get("layers", [])
            scene_row = {
                "id": f"86100000-0000-0000-0000-{len(self.template_scenes) + 1:012d}",
                "blueprint_code": blueprint_code,
                "template_library_code": template_library_code,
                "scene_template_code": scene_template_code,
                "scene_code": scene.get("scene_code") or scene_template_code,
                "scene_name": scene_name,
                "scene_type": scene.get("scene_type"),
                "sort_order": scene.get("sort_order") if scene.get("sort_order") is not None else scene_index + 1,
                "reference_product_name": scene.get("reference_product_name"),
                "reference_item_id": scene.get("reference_item_id"),
                "reference_clip_id": scene.get("reference_clip_id"),
                "script_block_code": script_block.get("script_block_code"),
                "script_sort_order": script_block.get("sort_order"),
                "script_content": script_block.get("content"),
                "component_count": len(layers),
                "created_at": None,
                "updated_at": None,
            }
            self.template_scenes[scene_template_code] = scene_row
            self.template_components[scene_template_code] = []
            for layer_index, layer in enumerate(layers):
                component_template_code = str(layer.get("layer_code") or f"{scene_template_code}-COMP-{layer_index + 1:03d}")
                self.template_components[scene_template_code].append(
                    {
                        "id": f"86200000-0000-0000-0000-{len(self.template_components[scene_template_code]) + 1:012d}",
                        "blueprint_code": blueprint_code,
                        "template_library_code": template_library_code,
                        "scene_template_code": scene_template_code,
                        "component_template_code": component_template_code,
                        "scene_code": scene.get("scene_code") or scene_template_code,
                        "scene_name": scene_name,
                        "scene_type": scene.get("scene_type"),
                        "reference_product_name": scene.get("reference_product_name"),
                        "reference_item_id": scene.get("reference_item_id"),
                        "reference_clip_id": scene.get("reference_clip_id"),
                        "component_name": layer.get("component_name") or layer.get("layer_name"),
                        "component_type": layer.get("component_type") or layer.get("source_material_type"),
                        "component_role": layer.get("component_role") or layer.get("layer_role"),
                        "layer_code": layer.get("layer_code") or component_template_code,
                        "layer_name": layer.get("layer_name"),
                        "layer_role": layer.get("layer_role"),
                        "material_id": layer.get("material_id"),
                        "material_tab": layer.get("material_tab"),
                        "source_material_type": layer.get("source_material_type"),
                        "required_category": layer.get("required_category"),
                        "accepted_asset_types": layer.get("accepted_asset_types", []),
                        "replacement_policy": layer.get("replacement_policy"),
                        "geometry": {
                            "left": layer.get("left_position"),
                            "top": layer.get("top_position"),
                            "width": layer.get("width"),
                            "height": layer.get("height"),
                            "scale": layer.get("scale"),
                        },
                        "z_index": layer.get("z_index"),
                        "speaker_id": layer.get("speaker_id"),
                        "digital_human_image_id": layer.get("digital_human_image_id"),
                        "source_material_url": layer.get("source_material_url"),
                        "source_cover_url": layer.get("source_cover_url"),
                        "sort_order": layer.get("sort_order") if layer.get("sort_order") is not None else layer_index + 1,
                        "created_at": None,
                        "updated_at": None,
                    }
                )

    def search_live_room_scene_components_by_script(
        self,
        *,
        q: str,
        reference_room_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self.list_live_room_template_scenes(
            reference_room_id=reference_room_id,
            status=status,
            q=q,
            limit=limit,
            offset=offset,
        )
        results: list[dict[str, Any]] = []
        for scene in rows:
            if q.lower() not in str(scene.get("script_content") or "").lower():
                continue
            blueprint = self.blueprints[scene["blueprint_code"]]
            placements = []
            components: dict[tuple[Any, ...], dict[str, Any]] = {}
            for component_row in self.list_live_room_template_scene_components(scene["scene_template_code"]) or []:
                placement = {
                    "scene_template_code": component_row.get("scene_template_code"),
                    "component_template_code": component_row.get("component_template_code"),
                    "scene_name": component_row.get("scene_name"),
                    "scene_type": component_row.get("scene_type"),
                    "reference_product_name": component_row.get("reference_product_name"),
                    "reference_item_id": component_row.get("reference_item_id"),
                    "reference_clip_id": component_row.get("reference_clip_id"),
                    "layer_code": component_row.get("layer_code"),
                    "layer_name": component_row.get("layer_name"),
                    "layer_role": component_row.get("layer_role"),
                    "material_id": component_row.get("material_id"),
                    "material_tab": component_row.get("material_tab"),
                    "source_material_type": component_row.get("source_material_type"),
                    "required_category": component_row.get("required_category"),
                    "accepted_asset_types": component_row.get("accepted_asset_types", []),
                    "replacement_policy": component_row.get("replacement_policy"),
                    "geometry": component_row.get("geometry", {}),
                    "z_index": component_row.get("z_index"),
                    "speaker_id": component_row.get("speaker_id"),
                    "digital_human_image_id": component_row.get("digital_human_image_id"),
                    "source_material_url": component_row.get("source_material_url"),
                    "source_cover_url": component_row.get("source_cover_url"),
                }
                placements.append(placement)
                key = (
                    placement.get("layer_name"),
                    placement.get("material_id"),
                    placement.get("source_material_type"),
                    placement.get("layer_role"),
                )
                component = components.setdefault(
                    key,
                    {
                        "component_name": placement.get("layer_name"),
                        "component_type": placement.get("source_material_type"),
                        "component_role": placement.get("layer_role"),
                        "material_id": placement.get("material_id"),
                        "required_category": placement.get("required_category"),
                        "material_tab": placement.get("material_tab"),
                        "source_material_type": placement.get("source_material_type"),
                        "source_material_url": placement.get("source_material_url"),
                        "source_cover_url": placement.get("source_cover_url"),
                        "placements": 0,
                        "scene_names": [],
                        "geometry_examples": [],
                    },
                )
                component["placements"] += 1
                if placement["scene_name"] not in component["scene_names"]:
                    component["scene_names"].append(placement["scene_name"])
                component["geometry_examples"].append(placement.get("geometry", {}))
            results.append(
                {
                    "blueprint_code": blueprint["blueprint_code"],
                    "title": blueprint["title"],
                    "reference_room_id": blueprint.get("reference_room_id"),
                    "reference_room_name": blueprint.get("reference_room_name"),
                    "platform": blueprint.get("platform"),
                    "status": blueprint["status"],
                    "room_type": blueprint["room_type"],
                    "template_library_code": scene.get("template_library_code"),
                    "component_index_source": "template_component_index",
                    "matched_script_blocks": [
                        {
                            "script_block_code": scene.get("script_block_code"),
                            "scene_name": scene.get("scene_name"),
                            "sort_order": scene.get("script_sort_order"),
                            "content": scene.get("script_content") or "",
                        }
                    ],
                    "matched_scene_names": [scene["scene_name"]],
                    "matched_scene_count": 1,
                    "scene_count": 1,
                    "script_block_count": 1,
                    "unique_component_count": len(components),
                    "component_placement_count": len(placements),
                    "components": list(components.values()),
                    "component_placements": placements,
                }
            )
        return results

    def get_live_room_blueprint_by_code(self, blueprint_code: str) -> dict[str, Any] | None:
        return self.blueprints.get(blueprint_code)

    def create_live_room_build_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        blueprint = self.blueprints.get(payload["blueprint_code"])
        if blueprint is None:
            return None
        code = f"MT-BUILD-20260709-{len(self.build_plans) + 1:06d}"
        operations: list[dict[str, Any]] = [
            {
                "operation_type": "preflight_build_plan",
                "operation_name": "只读预检直播间蓝图",
                "sort_order": 1,
                "status": "ready",
                "instruction": f"预检蓝图 {blueprint['blueprint_code']}：确认当前麦兔页面、登录态、直播间和场景仍匹配，不点击正式开播。",
            }
        ]
        script_context = "；".join(
            str(part)
            for part in [
                blueprint.get("title"),
                blueprint.get("description"),
                *[block.get("content") for block in blueprint.get("script_blocks", [])],
            ]
            if part
        )
        sort_order = 10
        for scene in blueprint.get("scenes", []):
            operations.append(
                {
                    "operation_type": "select_scene",
                    "operation_name": f"选择场景 {scene.get('scene_name')}",
                    "sort_order": sort_order,
                    "status": "ready",
                    "scene_name": scene.get("scene_name"),
                    "instruction": f"在麦兔直播间 {blueprint.get('reference_room_id')} 中选择场景 {scene.get('scene_name')}，只做定位不保存。",
                }
            )
            sort_order += 10
            for layer in scene.get("layers", []):
                operation = {
                    "operation_type": "replace_layer_asset",
                    "operation_name": f"规划图层 {layer.get('layer_name')}",
                    "sort_order": sort_order,
                    "status": "planned",
                    "scene_name": scene.get("scene_name"),
                    "layer_name": layer.get("layer_name"),
                    "layer_role": layer.get("layer_role"),
                    "required_category": layer.get("required_category"),
                    "accepted_asset_types": layer.get("accepted_asset_types", []),
                    "replacement_policy": layer.get("replacement_policy", "keep_layout"),
                    "instruction": f"在场景 {scene.get('scene_name')} 定位图层 {layer.get('layer_name')}，后续按 {layer.get('replacement_policy', 'keep_layout')} 策略匹配素材并保持原布局。",
                }
                if payload.get("auto_select_assets") or payload.get("strategy") == "script_context_best_match":
                    candidate = self.select_asset_for_template_component(layer, scene, script_context)
                    if candidate:
                        operation.update(
                            {
                                "status": "asset_selected",
                                "selected_asset_code": candidate.get("asset_code"),
                                "selected_asset_title": candidate.get("title"),
                                "selected_asset_display_code": candidate.get("display_code"),
                                "selected_asset_local_file_code": candidate.get("local_file_code"),
                                "selected_asset_original_filename": candidate.get("original_filename"),
                                "selected_asset_local_relative_path": candidate.get("local_relative_path"),
                                "selected_asset_browser_use_hint": candidate.get("browser_use_hint"),
                                "match_score": candidate.get("match_score", 0.9),
                                "match_reasons": candidate.get("match_reasons", []),
                                "selection_source": "script_context_rule_filter",
                                "instruction": (
                                    f"在场景 {scene.get('scene_name')} 定位图层 {layer.get('layer_name')}，计划替换为 "
                                    f"{candidate.get('display_code') or candidate.get('local_file_code')}（{candidate.get('title')}；"
                                    f"AssetGraph编号 {candidate.get('asset_code')}），替换策略为 {layer.get('replacement_policy', 'keep_layout')}；保持原图层位置和尺寸不变。"
                                ),
                            }
                        )
                operations.append(operation)
                sort_order += 10
        for block in blueprint.get("script_blocks", []):
            operations.append(
                {
                    "operation_type": "add_script_block",
                    "operation_name": f"写入脚本块 {block.get('script_block_code')}",
                    "sort_order": sort_order,
                    "status": "planned",
                    "scene_name": block.get("scene_name"),
                    "script_block_code": block.get("script_block_code"),
                    "script_block_content": block.get("content"),
                    "instruction": f"在场景 {block.get('scene_name')} 的直播脚本区域写入脚本块 {block.get('script_block_code')}，写入后需要重新 Observe 验证。",
                }
            )
            sort_order += 10
        operations.append(
            {
                "operation_type": "save_live_room",
                "operation_name": "保存直播间草稿",
                "sort_order": 999,
                "status": "manual_review",
                "instruction": "仅在所有前置操作验证通过后保存直播间草稿；默认不点击正式开播。",
            }
        )
        plan = {
            "id": f"87000000-0000-0000-0000-{len(self.build_plans) + 1:012d}",
            "build_plan_code": code,
            "blueprint_code": blueprint["blueprint_code"],
            "plan_name": payload.get("plan_name") or f"{blueprint['title']} BuildPlan",
            "target_app": "maitu",
            "executor": "browser_use",
            "status": "draft",
            "strategy": payload.get("strategy", "reference_rebuild_dry_run"),
            "operations": operations,
            "created_at": None,
            "updated_at": None,
        }
        self.build_plans[code] = plan
        return plan

    def create_live_room_scene_build_plan(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        scenes = self.list_live_room_template_scenes(
            blueprint_code=payload.get("blueprint_code"),
            reference_room_id=payload.get("reference_room_id"),
            template_library_code=payload.get("template_library_code"),
            status=payload.get("status"),
            q=payload["script_query"],
            limit=1,
            offset=0,
        )
        if not scenes:
            return None
        scene = scenes[0]
        components = self.list_live_room_template_scene_components(scene["scene_template_code"]) or []
        code = f"MT-BUILD-20260709-{len(self.build_plans) + 1:06d}"
        operations: list[dict[str, Any]] = [
            {
                "operation_type": "preflight_scene_build_plan",
                "operation_name": "只读预检单场景搭建计划",
                "sort_order": 1,
                "status": "ready",
                "instruction": "预检单场景模板和禁开播规则；此计划为 dry-run，不直接操作麦兔。",
                "details": {
                    "safety_gate": True,
                    "target_live_room_id": payload.get("target_live_room_id"),
                    "scene_template_code": scene["scene_template_code"],
                    "template_library_code": scene.get("template_library_code"),
                    "script_query": payload["script_query"],
                },
            },
            {
                "operation_type": "create_scene_from_template",
                "operation_name": f"按模板创建单场景 {scene['scene_name']}",
                "sort_order": 10,
                "status": "planned",
                "scene_name": scene["scene_name"],
                "instruction": f"按模板场景 {scene['scene_name']} 复刻结构；只生成计划，不点击正式开播。",
                "details": {
                    "scene_template_code": scene["scene_template_code"],
                    "template_library_code": scene.get("template_library_code"),
                    "scene_type": scene.get("scene_type"),
                    "reference_product_name": scene.get("reference_product_name"),
                    "reference_item_id": scene.get("reference_item_id"),
                    "reference_clip_id": scene.get("reference_clip_id"),
                    "component_count": len(components),
                },
            },
        ]
        sort_order = 20
        for component in components:
            component_name = component.get("component_name") or component.get("layer_name")
            operations.append(
                {
                    "operation_type": "insert_template_component",
                    "operation_name": f"插入模板组件 {component_name}",
                    "sort_order": sort_order,
                    "status": "planned",
                    "scene_name": scene["scene_name"],
                    "layer_name": component.get("layer_name") or component_name,
                    "layer_role": component.get("layer_role") or component.get("component_role"),
                    "required_category": component.get("required_category"),
                    "accepted_asset_types": component.get("accepted_asset_types", []),
                    "replacement_policy": component.get("replacement_policy", "keep_layout"),
                    "instruction": f"在单场景 {scene['scene_name']} 中插入/配置组件 {component_name}，保持模板坐标、尺寸和层级。",
                    "details": {
                        "scene_template_code": scene["scene_template_code"],
                        "component_template_code": component.get("component_template_code"),
                        "component_type": component.get("component_type"),
                        "component_role": component.get("component_role"),
                        "material_id": component.get("material_id"),
                        "material_tab": component.get("material_tab"),
                        "source_material_type": component.get("source_material_type"),
                        "geometry": component.get("geometry", {}),
                        "z_index": component.get("z_index"),
                        "speaker_id": component.get("speaker_id"),
                        "digital_human_image_id": component.get("digital_human_image_id"),
                        "source_material_url": component.get("source_material_url"),
                        "source_cover_url": component.get("source_cover_url"),
                    },
                }
            )
            sort_order += 10
        operations.append(
            {
                "operation_type": "add_script_block",
                "operation_name": f"写入单场景脚本 {scene.get('script_block_code')}",
                "sort_order": sort_order,
                "status": "planned",
                "scene_name": scene["scene_name"],
                "script_block_code": scene.get("script_block_code"),
                "script_block_content": payload.get("target_script_content") or scene.get("script_content") or payload["script_query"],
                "instruction": f"在单场景 {scene['scene_name']} 的直播脚本区域写入目标脚本，并回读确认文本一致。",
                "details": {
                    "scene_template_code": scene["scene_template_code"],
                    "script_query": payload["script_query"],
                    "source_template_script_content": scene.get("script_content"),
                    "script_sort_order": scene.get("script_sort_order"),
                },
            }
        )
        operations.append(
            {
                "operation_type": "save_live_room",
                "operation_name": "保存单场景直播间草稿",
                "sort_order": 999,
                "status": "manual_review",
                "scene_name": scene["scene_name"],
                "instruction": "只在组件和脚本回读验证通过后保存草稿；禁止点击正式开播。",
                "details": {"requires_human_or_preflight_pass": True, "scene_template_code": scene["scene_template_code"]},
            }
        )
        plan = {
            "id": f"87000000-0000-0000-0000-{len(self.build_plans) + 1:012d}",
            "build_plan_code": code,
            "blueprint_code": scene["blueprint_code"],
            "plan_name": payload.get("plan_name") or f"{scene['scene_name']} SceneBuildPlan dry-run",
            "target_app": "maitu",
            "executor": "browser_use",
            "status": "draft",
            "strategy": payload.get("strategy", "template_scene_dry_run"),
            "description": payload.get("description"),
            "operations": operations,
            "created_at": None,
            "updated_at": None,
        }
        self.build_plans[code] = plan
        return plan

    def get_live_room_build_plan_by_code(self, build_plan_code: str) -> dict[str, Any] | None:
        return self.build_plans.get(build_plan_code)

    def get_live_room_build_plan_operations(self, build_plan_code: str) -> dict[str, Any] | None:
        plan = self.build_plans.get(build_plan_code)
        if plan is None:
            return None
        preflight_details = plan["operations"][0].get("details") or {}
        return {
            "build_plan_code": plan["build_plan_code"],
            "blueprint_code": plan["blueprint_code"],
            "reference_room_id": self.blueprints[plan["blueprint_code"]].get("reference_room_id"),
            "reference_room_name": self.blueprints[plan["blueprint_code"]].get("reference_room_name"),
            "target_live_room_id": preflight_details.get("target_live_room_id"),
            "executor": plan["executor"],
            "target_app": plan["target_app"],
            "operations": plan["operations"],
        }

    def create_live_room_build_plan_execution_result(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        plan = self.build_plans.get(build_plan_code)
        if plan is None:
            return None
        execution_code = f"MT-EXEC-20260709-{len(self.build_plan_executions) + 1:06d}"
        operation_results = []
        for sort_order, operation in enumerate(payload.get("operation_results", [])):
            operation_results.append(
                {
                    "id": f"89000000-0000-0000-0000-{sort_order + 1:012d}",
                    "operation_index": operation.get("operation_index", sort_order),
                    "operation_type": operation["operation_type"],
                    "operation_name": operation.get("operation_name"),
                    "scene_name": operation.get("scene_name"),
                    "layer_name": operation.get("layer_name"),
                    "action_type": operation.get("action_type"),
                    "status": operation["status"],
                    "failure_type": operation.get("failure_type"),
                    "retryable": operation.get("retryable", False),
                    "retry_instruction": operation.get("retry_instruction"),
                    "error_message": operation.get("error_message"),
                    "screenshot_asset_code": operation.get("screenshot_asset_code"),
                    "dom_snapshot_asset_code": operation.get("dom_snapshot_asset_code"),
                    "details": operation.get("details", {}),
                    "sort_order": sort_order,
                }
            )
        execution = {
            "id": f"89100000-0000-0000-0000-{len(self.build_plan_executions) + 1:012d}",
            "execution_code": execution_code,
            "build_plan_code": build_plan_code,
            "blueprint_code": plan["blueprint_code"],
            "executor": payload.get("executor", "browser_use"),
            "execution_status": payload["execution_status"],
            "mode": payload.get("mode", "non_destructive"),
            "failure_type": payload.get("failure_type"),
            "retryable": payload.get("retryable", False),
            "retry_instruction": payload.get("retry_instruction"),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "error_message": payload.get("error_message"),
            "screenshot_asset_code": payload.get("screenshot_asset_code"),
            "dom_snapshot_asset_code": payload.get("dom_snapshot_asset_code"),
            "result_summary": payload.get("result_summary"),
            "operation_results": operation_results,
            "created_at": None,
            "updated_at": None,
        }
        self.build_plan_executions[execution_code] = execution
        plan["status"] = "execution_reported"
        return execution

    def list_live_room_build_plan_execution_results(
        self,
        build_plan_code: str,
        *,
        executor: str | None = None,
        execution_status: str | None = None,
        mode: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        if build_plan_code not in self.build_plans:
            return None
        rows = [row for row in self.build_plan_executions.values() if row["build_plan_code"] == build_plan_code]
        if executor is not None:
            rows = [row for row in rows if row["executor"] == executor]
        if execution_status is not None:
            rows = [row for row in rows if row["execution_status"] == execution_status]
        if mode is not None:
            rows = [row for row in rows if row["mode"] == mode]
        return rows[offset : offset + limit]

    def get_live_room_build_plan_execution_result_by_code(self, build_plan_code: str, execution_code: str) -> dict[str, Any] | None:
        row = self.build_plan_executions.get(execution_code)
        if row is None or row["build_plan_code"] != build_plan_code:
            return None
        return row

    def create_layout_adjustment(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.layout_adjustment import LayerGeometry, plan_layout_adjustment

        code = f"MT-ADJ-20260709-{len(self.layout_adjustments) + 1:06d}"
        plan = plan_layout_adjustment(
            user_instruction=payload["user_instruction"],
            before_geometry=LayerGeometry(**payload["before_geometry"]),
            canvas_width=payload["canvas_width"],
            canvas_height=payload["canvas_height"],
            safe_margin=payload.get("safe_margin", 20),
        )
        row = {
            "id": f"88000000-0000-0000-0000-{len(self.layout_adjustments) + 1:012d}",
            "adjustment_code": code,
            "build_plan_code": payload.get("build_plan_code"),
            "scene_name": payload.get("scene_name"),
            "layer_name": payload.get("layer_name"),
            "user_instruction": payload["user_instruction"],
            "status": plan.status,
            "before_geometry": payload["before_geometry"],
            "target_geometry": plan.operation["target_geometry"],
            "operation": plan.operation,
            "checks": plan.checks,
            "created_at": None,
            "updated_at": None,
        }
        self.layout_adjustments[code] = row
        return row

    def get_layout_adjustment_by_code(self, adjustment_code: str) -> dict[str, Any] | None:
        return self.layout_adjustments.get(adjustment_code)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = f"MT-SLOT-20260707-{len(self.rows) + 1:06d}"
        row = {
            "id": "81000000-0000-0000-0000-000000000001",
            "slot_code": code,
            "slot_name": payload["slot_name"],
            "maitu_project_code": payload.get("maitu_project_code"),
            "scene_name": payload.get("scene_name"),
            "scene_index": payload.get("scene_index"),
            "layer_name": payload.get("layer_name"),
            "layer_index": payload.get("layer_index"),
            "required_category": payload["required_category"],
            "accepted_asset_types": payload.get("accepted_asset_types", []),
            "aspect_ratio": payload.get("aspect_ratio"),
            "left_position": payload.get("left_position"),
            "top_position": payload.get("top_position"),
            "width": payload.get("width"),
            "height": payload.get("height"),
            "z_index": payload.get("z_index"),
            "replacement_policy": payload.get("replacement_policy", "keep_layout"),
            "description": payload.get("description"),
        }
        self.rows[code] = row
        return row

    def list(
        self,
        *,
        maitu_project_code: str | None = None,
        scene_name: str | None = None,
        required_category: str | None = None,
        slot_name: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.rows.values())
        if maitu_project_code is not None:
            rows = [row for row in rows if row.get("maitu_project_code") == maitu_project_code]
        if scene_name is not None:
            rows = [row for row in rows if row.get("scene_name") == scene_name]
        if required_category is not None:
            rows = [row for row in rows if row.get("required_category") == required_category]
        if slot_name is not None:
            rows = [row for row in rows if row.get("slot_name") == slot_name]
        if q:
            rows = [
                row
                for row in rows
                if q in row["slot_code"]
                or q in row["slot_name"]
                or q in (row.get("scene_name") or "")
                or q in (row.get("layer_name") or "")
                or q in (row.get("description") or "")
            ]
        return rows[offset : offset + limit]

    def get_by_code(self, slot_code: str) -> dict[str, Any] | None:
        return self.rows.get(slot_code)

    def update(self, slot_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.rows.get(slot_code)
        if row is None:
            return None
        if any(
            task.get("slot_code") == slot_code and task.get("status") == "in_progress"
            for task in self.retry_tasks.values()
        ):
            raise RetryLeaseConflictError(
                "slot authoritative intent cannot change while a related retry worker lease is active"
            )
        row.update(payload)
        return row

    def soft_delete(self, slot_code: str) -> bool:
        if any(
            task.get("slot_code") == slot_code and task.get("status") == "in_progress"
            for task in self.retry_tasks.values()
        ):
            raise RetryLeaseConflictError(
                "slot authoritative intent cannot change while a related retry worker lease is active"
            )
        return self.rows.pop(slot_code, None) is not None

    def list_candidate_assets(self, slot_code: str, *, limit: int = 20, offset: int = 0) -> dict[str, Any] | None:
        slot = self.rows.get(slot_code)
        if slot is None:
            return None
        assets = []
        for asset in self.assets:
            if asset["maitu_category"] != slot["required_category"]:
                continue
            if slot.get("accepted_asset_types") and asset["asset_type"] not in slot["accepted_asset_types"]:
                continue
            score = 0.5
            reasons = [f"maitu_category matches required_category: {slot['required_category']}"]
            if asset["asset_type"] in slot.get("accepted_asset_types", []):
                score += 0.2
                reasons.append(f"asset_type accepted: {asset['asset_type']}")
            if asset.get("maitu_project_code") == slot.get("maitu_project_code"):
                score += 0.1
                reasons.append(f"maitu_project_code matches: {slot['maitu_project_code']}")
            if asset.get("maitu_scene_name") == slot.get("scene_name"):
                score += 0.1
                reasons.append(f"scene_name matches: {slot['scene_name']}")
            if asset.get("maitu_slot_code") == slot_code:
                score += 0.1
                reasons.append(f"maitu_slot_code matches: {slot_code}")
            assets.append({**asset, "match_score": round(score, 4), "match_reasons": reasons})
        assets.sort(key=lambda row: row["match_score"], reverse=True)
        return {
            "slot_code": slot_code,
            "required_category": slot["required_category"],
            "accepted_asset_types": slot.get("accepted_asset_types", []),
            "assets": assets[offset : offset + limit],
        }

    def select_asset_for_template_component(
        self,
        component: dict[str, Any],
        template_scene: dict[str, Any],
        script_context: str,
    ) -> dict[str, Any] | None:
        required_category = component.get("required_category")
        if not required_category:
            return None
        accepted_asset_types = component.get("accepted_asset_types") or []
        candidates = []
        for asset in self.assets:
            if asset.get("maitu_category") != required_category:
                continue
            if accepted_asset_types and asset.get("asset_type") not in accepted_asset_types:
                continue
            if self._is_direct_layer_forbidden_template_asset(asset, component):
                continue
            score = 0.55
            reasons = [f"maitu_category matches required_category: {required_category}"]
            if not accepted_asset_types or asset.get("asset_type") in accepted_asset_types:
                score += 0.2
                reasons.append(f"asset_type accepted: {asset.get('asset_type')}")
            asset_text = " ".join(
                str(asset.get(field) or "")
                for field in ("title", "original_filename", "display_code", "local_file_code", "browser_use_hint", "subject", "usage")
            )
            for token in ("品酒大师PRO", "品酒大师", "张裕", "龙谕龙8", "龙谕", "夏日"):
                if token in script_context and token in asset_text:
                    score += 0.15
                    reasons.append(f"script context mentions {token}")
                    break
            if template_scene.get("scene_name") and asset.get("maitu_scene_name") == template_scene.get("scene_name"):
                score += 0.05
                reasons.append(f"scene_name matches: {template_scene.get('scene_name')}")
            candidates.append({**asset, "match_score": round(min(score, 1.0), 4), "match_reasons": reasons})
        candidates.sort(key=lambda row: (row["match_score"], row.get("asset_code") or ""), reverse=True)
        return candidates[0] if candidates else None

    def select_assets_for_script_asset_need(
        self,
        need: dict[str, Any],
        scene: dict[str, Any],
        *,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        required_category = need.get("required_category")
        if not required_category:
            return []
        accepted_asset_types = [item for item in (need.get("accepted_asset_types") or []) if item != "TEXT"]
        candidates = []
        for asset in self.assets:
            if asset.get("maitu_category") != required_category:
                continue
            if accepted_asset_types and asset.get("asset_type") not in accepted_asset_types:
                continue
            if self._is_direct_layer_forbidden_template_asset(asset, need):
                continue
            score = 0.55
            reasons = [f"maitu_category matches required_category: {required_category}"]
            if not accepted_asset_types or asset.get("asset_type") in accepted_asset_types:
                score += 0.2
                reasons.append(f"asset_type accepted: {asset.get('asset_type')}")
            asset_text = " ".join(
                str(asset.get(field) or "")
                for field in ("title", "original_filename", "display_code", "local_file_code", "browser_use_hint", "subject", "usage")
            )
            keyword_hits = []
            for keyword in need.get("keywords") or []:
                token = str(keyword)
                if token and token in asset_text:
                    keyword_hits.append(token)
            for keyword in keyword_hits[:3]:
                score += 0.1
                reasons.append(f"keyword matches asset: {keyword}")
            if need.get("priority") == "high":
                score += 0.02
            candidates.append({**asset, "match_score": round(min(score, 1.0), 4), "match_reasons": reasons})
        candidates.sort(key=lambda row: (row["match_score"], row.get("asset_code") or ""), reverse=True)
        return candidates[:limit]

    def resolve_plan_slots(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        slot_codes = payload.get("slot_codes") or list(self.rows.keys())
        return [self.rows[slot_code] for slot_code in slot_codes if slot_code in self.rows]

    def create_replacement_plan(
        self,
        payload: dict[str, Any],
        slot_candidates: list[tuple[dict[str, Any], dict[str, Any] | None]] | None = None,
    ) -> dict[str, Any]:
        code = f"MT-PLAN-20260707-{len(self.plans) + 1:06d}"
        if slot_candidates is None:
            slots = self.resolve_plan_slots(payload)
            slot_candidates = []
            for slot in slots:
                candidates = self.list_candidate_assets(slot["slot_code"], limit=1)
                candidate = candidates["assets"][0] if candidates and candidates["assets"] else None
                slot_candidates.append((slot, candidate))
        items = []
        for sort_order, (slot, candidate) in enumerate(slot_candidates):
            items.append(
                {
                    "slot_code": slot["slot_code"],
                    "slot_name": slot.get("slot_name"),
                    "required_category": slot.get("required_category"),
                    "selected_asset_code": candidate.get("asset_code") if candidate else None,
                    "selected_asset_title": candidate.get("title") if candidate else None,
                    "match_score": candidate.get("match_score") if candidate else None,
                    "match_reasons": candidate.get("match_reasons", []) if candidate else [],
                    "replacement_policy": candidate.get("replacement_policy") if candidate else slot.get("replacement_policy"),
                    "sort_order": sort_order,
                    "status": "selected" if candidate else "missing",
                }
            )
        plan = {
            "id": "82000000-0000-0000-0000-000000000001",
            "plan_code": code,
            "plan_name": payload["plan_name"],
            "maitu_project_code": payload.get("maitu_project_code"),
            "scene_name": payload.get("scene_name"),
            "status": "draft",
            "strategy": payload.get("strategy", "best_match"),
            "description": payload.get("description"),
            "items": items,
        }
        self.plans[code] = plan
        return plan

    def list_replacement_plans(
        self,
        *,
        maitu_project_code: str | None = None,
        scene_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.plans.values())
        if maitu_project_code is not None:
            rows = [row for row in rows if row.get("maitu_project_code") == maitu_project_code]
        if scene_name is not None:
            rows = [row for row in rows if row.get("scene_name") == scene_name]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    def get_replacement_plan_by_code(self, plan_code: str) -> dict[str, Any] | None:
        return self.plans.get(plan_code)

    def get_browser_use_operation_plan(self, plan_code: str) -> dict[str, Any] | None:
        plan = self.plans.get(plan_code)
        if plan is None:
            return None
        operations = []
        for item in plan.get("items", []):
            slot = self.rows.get(item["slot_code"], {})
            if item.get("selected_asset_code"):
                asset = next((row for row in self.assets if row["asset_code"] == item.get("selected_asset_code")), {})
                asset_display_code = asset.get("display_code") or asset.get("local_file_code") or item["selected_asset_code"]
                asset_title = asset.get("title") or item.get("selected_asset_title")
                instruction = (
                    f"进入麦兔项目 {plan.get('maitu_project_code')} 的“{slot.get('scene_name')}”场景，"
                    f"找到目标图层/槽位 {slot.get('layer_name')}，将素材替换为 "
                    f"{asset_display_code}（{asset_title}；AssetGraph编号 {item['selected_asset_code']}），"
                    f"替换策略为 {item.get('replacement_policy')}；保持原图层位置和尺寸不变"
                )
                if asset.get("original_filename"):
                    instruction += f"；素材文件名：{asset['original_filename']}"
                if asset.get("browser_use_hint"):
                    instruction += f"；选择提示：{asset['browser_use_hint']}"
                instruction += "，替换后保存项目。"
                operations.append(
                    {
                        "operation_type": "replace_layer_asset",
                        "slot_code": item["slot_code"],
                        "slot_name": item.get("slot_name"),
                        "scene_name": slot.get("scene_name"),
                        "layer_name": slot.get("layer_name"),
                        "asset_code": item.get("selected_asset_code"),
                        "asset_title": asset_title,
                        "asset_display_code": asset.get("display_code"),
                        "asset_local_file_code": asset.get("local_file_code"),
                        "asset_original_filename": asset.get("original_filename"),
                        "asset_local_relative_path": asset.get("local_relative_path"),
                        "asset_browser_use_hint": asset.get("browser_use_hint"),
                        "replacement_policy": item.get("replacement_policy"),
                        "status": "ready",
                        "instruction": instruction,
                    }
                )
        return {
            "plan_code": plan_code,
            "executor": "browser_use",
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "scene_name": plan.get("scene_name"),
            "operations": operations,
        }

    def create_execution_result(self, plan_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        plan = self.plans.get(plan_code)
        if plan is None:
            return None
        execution_code = f"MT-EXEC-20260707-{len(self.executions) + 1:06d}"
        operation_results = []
        for sort_order, operation in enumerate(payload.get("operation_results", [])):
            operation_results.append(
                {
                    "id": f"83000000-0000-0000-0000-{sort_order + 1:012d}",
                    "slot_code": operation["slot_code"],
                    "operation_type": operation.get("operation_type", "replace_layer_asset"),
                    "asset_code": operation.get("asset_code"),
                    "status": operation["status"],
                    "failure_type": operation.get("failure_type"),
                    "retryable": operation.get("retryable", False),
                    "retry_instruction": operation.get("retry_instruction"),
                    "error_message": operation.get("error_message"),
                    "screenshot_asset_code": operation.get("screenshot_asset_code"),
                    "details": operation.get("details", {}),
                    "sort_order": sort_order,
                }
            )
        execution = {
            "id": "84000000-0000-0000-0000-000000000001",
            "execution_code": execution_code,
            "plan_code": plan_code,
            "executor": payload.get("executor", "browser_use"),
            "execution_status": payload["execution_status"],
            "failure_type": payload.get("failure_type"),
            "retryable": payload.get("retryable", False),
            "retry_instruction": payload.get("retry_instruction"),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "error_message": payload.get("error_message"),
            "screenshot_asset_code": payload.get("screenshot_asset_code"),
            "result_summary": payload.get("result_summary"),
            "operation_results": operation_results,
            "created_at": None,
        }
        plan["status"] = "executed" if payload["execution_status"] == "succeeded" else "execution_failed"
        self.executions[execution_code] = execution
        self._create_retry_tasks_for_execution(execution)
        return execution

    def list_execution_results(
        self,
        plan_code: str,
        *,
        executor: str | None = None,
        execution_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        if plan_code not in self.plans:
            return None
        rows = [row for row in self.executions.values() if row["plan_code"] == plan_code]
        if executor is not None:
            rows = [row for row in rows if row["executor"] == executor]
        if execution_status is not None:
            rows = [row for row in rows if row["execution_status"] == execution_status]
        return rows[offset : offset + limit]

    def get_execution_result_by_code(self, plan_code: str, execution_code: str) -> dict[str, Any] | None:
        execution = self.executions.get(execution_code)
        if execution is None or execution["plan_code"] != plan_code:
            return None
        return execution

    def list_retry_tasks(
        self,
        *,
        plan_code: str | None = None,
        execution_code: str | None = None,
        status: str | None = None,
        failure_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.retry_tasks.values())
        if plan_code is not None:
            rows = [row for row in rows if row["plan_code"] == plan_code]
        if execution_code is not None:
            rows = [row for row in rows if row["execution_code"] == execution_code]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        if failure_type is not None:
            rows = [row for row in rows if row["failure_type"] == failure_type]
        return rows[offset : offset + limit]

    def list_retry_queue(
        self,
        *,
        status: str | None = "pending",
        failure_type: str | None = None,
        maitu_project_code: str | None = None,
        scene_name: str | None = None,
        max_attempts: int = 3,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = []
        for task in self.retry_tasks.values():
            if not task.get("retryable") or task.get("retry_attempt_count", 0) >= max_attempts:
                continue
            if status is not None and task.get("status") != status:
                continue
            if failure_type is not None and task.get("failure_type") != failure_type:
                continue
            plan = self.plans.get(task["plan_code"], {})
            slot = self.rows.get(task.get("slot_code"), {}) if task.get("slot_code") else {}
            project_code = slot.get("maitu_project_code") or plan.get("maitu_project_code")
            task_scene_name = slot.get("scene_name") or plan.get("scene_name")
            if maitu_project_code is not None and project_code != maitu_project_code:
                continue
            if scene_name is not None and task_scene_name != scene_name:
                continue
            rows.append(
                {
                    **task,
                    "maitu_project_code": project_code,
                    "scene_name": task_scene_name,
                    "slot_name": slot.get("slot_name"),
                    "layer_name": slot.get("layer_name"),
                    "next_operation_type": {
                        "missing_layer": "retry_replace_layer_asset",
                        "selector_changed": "retry_replace_layer_asset",
                        "asset_upload_failed": "retry_asset_upload_and_replace",
                        "save_failed": "retry_save_project",
                        "login_expired": "recover_login_then_retry",
                    }.get(task.get("failure_type"), "retry_browser_use_operation"),
                    "browser_use_operations_url": f"/api/maitu/retry-tasks/{task['retry_task_code']}/browser-use-operations",
                }
            )
        rows.sort(key=lambda row: (row["retry_attempt_count"], row["retry_task_code"]))
        return rows[offset : offset + limit]

    def claim_next_retry_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        rows = self.list_retry_queue(
            failure_type=payload.get("failure_type"),
            maitu_project_code=payload.get("maitu_project_code"),
            scene_name=payload.get("scene_name"),
            max_attempts=payload.get("max_attempts", 3),
            limit=1,
        )
        if not rows:
            return None
        task = self.retry_tasks[rows[0]["retry_task_code"]]
        lease_version = int(task.get("lease_version", 0)) + 1
        task["status"] = "in_progress"
        task["claimed_by"] = payload["claimed_by"]
        task["claimed_at"] = "2026-07-07T09:00:00Z"
        task["claim_expires_at"] = "2026-07-07T09:15:00Z"
        task["claim_token"] = f"c1a1d000-0000-4000-8000-{lease_version:012d}"
        task["lease_version"] = lease_version
        task["lease_expired"] = False
        return {**rows[0], **task}

    @staticmethod
    def _assert_retry_lease(task: dict[str, Any], payload: dict[str, Any]) -> None:
        if (
            task.get("status") != "in_progress"
            or task.get("lease_expired") is True
            or task.get("claimed_by") != payload.get("claimed_by")
            or task.get("claim_token") != str(payload.get("claim_token"))
            or task.get("lease_version") != payload.get("lease_version")
        ):
            raise RetryLeaseConflictError("retry task lease is no longer owned by this worker")

    def heartbeat_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        self._assert_retry_lease(task, payload)
        task["claim_expires_at"] = "2026-07-07T09:30:00Z"
        return task

    def reclaim_expired_retry_tasks(self) -> dict[str, Any]:
        reclaimed_codes = []
        for task in self.retry_tasks.values():
            if task.get("status") == "in_progress" and task.get("claim_expires_at") is not None:
                for (task_code, _operation_key), checkpoint in self.retry_operation_checkpoints.items():
                    if task_code == task["retry_task_code"] and checkpoint.get("state") == "begun":
                        checkpoint["state"] = "reconcile_required"
                task["status"] = "pending"
                task["claimed_by"] = None
                task["claimed_at"] = None
                task["claim_expires_at"] = None
                task["claim_token"] = None
                reclaimed_codes.append(task["retry_task_code"])
        return {"reclaimed_count": len(reclaimed_codes), "retry_task_codes": reclaimed_codes}

    def get_retry_worker_next(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        reclaim_result = self.reclaim_expired_retry_tasks()
        retry_task = self.claim_next_retry_task(payload)
        if retry_task is None:
            return None
        operation_plan = self.get_retry_task_browser_use_operation_plan(retry_task["retry_task_code"])
        return {
            "reclaimed_count": reclaim_result["reclaimed_count"],
            "reclaimed_retry_task_codes": reclaim_result["retry_task_codes"],
            "retry_task": retry_task,
            "operation_plan": operation_plan,
        }

    def release_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        self._assert_retry_lease(task, payload)
        for (task_code, _operation_key), checkpoint in self.retry_operation_checkpoints.items():
            if (
                task_code == retry_task_code
                and checkpoint.get("state") == "begun"
                and checkpoint.get("begun_by") == payload["claimed_by"]
                and checkpoint.get("begun_lease_version") == payload["lease_version"]
            ):
                checkpoint["state"] = "reconcile_required"
        task["status"] = payload.get("status", "pending")
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["claim_expires_at"] = None
        task["claim_token"] = None
        if payload.get("result_summary") is not None:
            task["result_summary"] = payload["result_summary"]
        return task

    def get_retry_task_by_code(self, retry_task_code: str) -> dict[str, Any] | None:
        return self.retry_tasks.get(retry_task_code)

    def update_retry_task(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        if task.get("status") == "in_progress":
            raise RetryLeaseConflictError("retry task metadata cannot change while a worker lease is active")
        task.update(payload)
        return task

    def get_retry_task_browser_use_operation_plan(self, retry_task_code: str) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        plan = self.plans.get(task["plan_code"], {})
        slot = self.rows.get(task.get("slot_code"), {}) if task.get("slot_code") else {}
        plan_item = next(
            (item for item in plan.get("items", []) if item.get("slot_code") == task.get("slot_code")),
            {},
        )
        scene_name = slot.get("scene_name") or plan.get("scene_name")
        operations = MaituMaterialSlotRepository._build_retry_operations(task, plan, slot, plan_item)
        return {
            "retry_task_code": retry_task_code,
            "plan_code": task["plan_code"],
            "execution_code": task["execution_code"],
            "executor": task.get("executor", "browser_use"),
            "target_app": "maitu",
            "maitu_project_code": plan.get("maitu_project_code"),
            "scene_name": scene_name,
            "operations": operations,
        }

    def list_retry_operation_checkpoints(self, retry_task_code: str) -> list[dict[str, Any]] | None:
        if retry_task_code not in self.retry_tasks:
            return None
        return [
            {**checkpoint, "decision": None}
            for (task_code, _operation_key), checkpoint in sorted(self.retry_operation_checkpoints.items())
            if task_code == retry_task_code
        ]

    def begin_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        self._assert_retry_lease(task, payload)
        plan = self.get_retry_task_browser_use_operation_plan(retry_task_code) or {}
        operation = next(
            (item for item in plan.get("operations", []) if item["operation_key"] == operation_key),
            None,
        )
        if operation is None or operation["operation_fingerprint"] != payload["operation_fingerprint"]:
            raise RetryCheckpointConflictError("operation differs from authoritative intent")
        key = (retry_task_code, operation_key)
        checkpoint = self.retry_operation_checkpoints.get(key)
        if checkpoint is None:
            checkpoint = {
                "retry_task_code": retry_task_code,
                "operation_key": operation_key,
                "operation_fingerprint": operation["operation_fingerprint"],
                "state": "begun",
                "attempt_id": str(payload["attempt_id"]),
                "begun_by": payload["claimed_by"],
                "begun_lease_version": payload["lease_version"],
                "completion_id": None,
                "completion_fingerprint": None,
                "completed_by": None,
                "completed_lease_version": None,
                "evidence": {},
            }
            self.retry_operation_checkpoints[key] = checkpoint
            decision = "execute"
        elif checkpoint["operation_fingerprint"] != operation["operation_fingerprint"]:
            raise RetryCheckpointConflictError("stored checkpoint differs from authoritative intent")
        elif checkpoint["state"] == "retry_authorized":
            checkpoint.update(
                {
                    "state": "begun",
                    "attempt_id": str(payload["attempt_id"]),
                    "begun_by": payload["claimed_by"],
                    "begun_lease_version": payload["lease_version"],
                }
            )
            decision = "execute"
        elif checkpoint["state"] == "completed":
            decision = "skip"
        elif (
            checkpoint["state"] == "begun"
            and checkpoint["attempt_id"] == str(payload["attempt_id"])
            and checkpoint["begun_by"] == payload["claimed_by"]
            and checkpoint["begun_lease_version"] == payload["lease_version"]
        ):
            decision = "execute"
        else:
            decision = "reconcile"
        return {**checkpoint, "decision": decision}

    def complete_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        self._assert_retry_lease(task, payload)
        MaituMaterialSlotRepository._assert_verified_secret_free_evidence(
            payload.get("evidence", {}),
            payload["claim_token"],
        )
        completion_fingerprint = MaituMaterialSlotRepository._completion_payload_fingerprint(payload)
        checkpoint = self.retry_operation_checkpoints.get((retry_task_code, operation_key))
        if checkpoint is None:
            raise RetryCheckpointConflictError("operation checkpoint was not begun")
        if (
            checkpoint["state"] == "completed"
            and checkpoint["completion_id"] == str(payload["completion_id"])
            and checkpoint["completion_fingerprint"] == completion_fingerprint
            and checkpoint["attempt_id"] == str(payload["attempt_id"])
        ):
            return {**checkpoint, "decision": "skip"}
        if (
            checkpoint["state"] != "begun"
            or checkpoint["attempt_id"] != str(payload["attempt_id"])
            or checkpoint["begun_by"] != payload["claimed_by"]
            or checkpoint["begun_lease_version"] != payload["lease_version"]
            or checkpoint["operation_fingerprint"] != payload["operation_fingerprint"]
        ):
            raise RetryCheckpointConflictError("checkpoint requires reconciliation or belongs to another attempt")
        checkpoint.update(
            {
                "state": "completed",
                "completion_id": str(payload["completion_id"]),
                "completion_fingerprint": completion_fingerprint,
                "completed_by": payload["claimed_by"],
                "completed_lease_version": payload["lease_version"],
                "completion_source": "worker",
                "completion_reconciliation_id": None,
                "evidence": payload.get("evidence", {}),
            }
        )
        return {**checkpoint, "decision": "skip"}

    def reconcile_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        MaituMaterialSlotRepository._assert_reconciliation_evidence(payload)
        result_fingerprint = MaituMaterialSlotRepository._reconciliation_payload_fingerprint(payload)
        reconciliation_id = str(payload["reconciliation_id"])
        receipt = self.retry_operation_reconciliations.get(reconciliation_id)
        if receipt is not None:
            if (
                receipt["retry_task_code"] == retry_task_code
                and receipt["operation_key"] == operation_key
                and receipt["result_fingerprint"] == result_fingerprint
            ):
                return receipt
            raise RetryCheckpointConflictError("reconciliation_id was reused with different content")
        if task.get("status") == "in_progress":
            raise RetryLeaseConflictError("operation reconciliation is forbidden while a worker lease is active")
        if task.get("status") not in {"pending", "manual_required"}:
            raise RetryCheckpointConflictError("retry task is not awaiting operation reconciliation")
        plan = self.get_retry_task_browser_use_operation_plan(retry_task_code) or {}
        operation = next(
            (item for item in plan.get("operations", []) if item["operation_key"] == operation_key),
            None,
        )
        checkpoint = self.retry_operation_checkpoints.get((retry_task_code, operation_key))
        if (
            operation is None
            or operation["operation_fingerprint"] != payload["operation_fingerprint"]
            or checkpoint is None
            or checkpoint.get("state") != "reconcile_required"
            or checkpoint.get("operation_fingerprint") != operation["operation_fingerprint"]
            or checkpoint.get("attempt_id") != str(payload["expected_attempt_id"])
        ):
            raise RetryCheckpointConflictError("operation checkpoint is not awaiting authoritative reconciliation")
        receipt = {
            **payload,
            "reconciliation_id": reconciliation_id,
            "retry_task_code": retry_task_code,
            "operation_key": operation_key,
            "reconciled_attempt_id": str(payload["expected_attempt_id"]),
            "resulting_state": (
                "completed" if payload["resolution"] == "confirmed_completed" else "retry_authorized"
            ),
            "result_fingerprint": result_fingerprint,
        }
        self.retry_operation_reconciliations[reconciliation_id] = receipt
        if payload["resolution"] == "confirmed_completed":
            checkpoint.update(
                {
                    "state": "completed",
                    "completion_id": reconciliation_id,
                    "completion_fingerprint": result_fingerprint,
                    "completed_by": payload["resolved_by"],
                    "completed_lease_version": None,
                    "evidence": payload["evidence"],
                    "completion_source": "reconciliation",
                    "completion_reconciliation_id": reconciliation_id,
                }
            )
        else:
            checkpoint.update({"state": "retry_authorized", "evidence": {}})
        task.update({"status": "pending"})
        return receipt

    def create_retry_task_execution_result(self, retry_task_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        MaituMaterialSlotRepository._assert_retry_execution_payload_token_free(payload)
        task = self.retry_tasks.get(retry_task_code)
        if task is None:
            return None
        retry_execution_id = str(payload["retry_execution_id"])
        fingerprint = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True)
        receipt = self.retry_execution_receipts.get(retry_execution_id)
        if receipt is not None:
            if receipt["retry_task_code"] == retry_task_code and receipt["fingerprint"] == fingerprint:
                return task
            raise RetryExecutionConflictError("retry_execution_id was reused with different content")
        self._assert_retry_lease(task, payload)
        if payload["retry_execution_status"] == "succeeded":
            plan = self.get_retry_task_browser_use_operation_plan(retry_task_code) or {}
            operations = {operation["operation_key"]: operation for operation in plan.get("operations", [])}
            completed = {
                operation_key: checkpoint
                for (task_code, operation_key), checkpoint in self.retry_operation_checkpoints.items()
                if task_code == retry_task_code and checkpoint.get("state") == "completed"
            }
            if set(completed) != set(operations):
                raise RetryCheckpointConflictError(
                    "all authoritative retry operation checkpoints must be completed before success"
                )
            for operation_key, operation in operations.items():
                checkpoint = completed[operation_key]
                if checkpoint.get("operation_fingerprint") != operation["operation_fingerprint"]:
                    raise RetryCheckpointConflictError(
                        f"completed checkpoint fingerprint drifted for operation {operation_key}"
                    )
                MaituMaterialSlotRepository._assert_verified_secret_free_evidence(
                    checkpoint.get("evidence", {}),
                    payload["claim_token"],
                )
                if checkpoint.get("completion_source") == "reconciliation":
                    reconciliation = self.retry_operation_reconciliations.get(
                        str(checkpoint.get("completion_reconciliation_id"))
                    )
                    if (
                        reconciliation is None
                        or reconciliation.get("retry_task_code") != retry_task_code
                        or reconciliation.get("operation_key") != operation_key
                        or reconciliation.get("reconciled_attempt_id") != checkpoint.get("attempt_id")
                        or reconciliation.get("resolution") != "confirmed_completed"
                        or reconciliation.get("resulting_state") != "completed"
                        or reconciliation.get("evidence") != checkpoint.get("evidence")
                    ):
                        raise RetryCheckpointConflictError("reconciliation receipt does not prove checkpoint completion")
                elif checkpoint.get("completion_source") != "worker":
                    raise RetryCheckpointConflictError("checkpoint completion source is missing or unsupported")
        else:
            for (task_code, _operation_key), checkpoint in self.retry_operation_checkpoints.items():
                if (
                    task_code == retry_task_code
                    and checkpoint.get("state") == "begun"
                    and checkpoint.get("begun_by") == payload["claimed_by"]
                    and checkpoint.get("begun_lease_version") == payload["lease_version"]
                ):
                    checkpoint["state"] = "reconcile_required"
        status_map = {
            "succeeded": "succeeded",
            "failed": "failed",
            "manual_required": "manual_required",
            "released": "pending",
        }
        task["status"] = status_map.get(payload["retry_execution_status"], payload["retry_execution_status"])
        if payload["retry_execution_status"] != "released":
            task["retry_attempt_count"] += 1
        task["last_retry_execution_id"] = retry_execution_id
        task["claimed_by"] = None
        task["claimed_at"] = None
        task["claim_expires_at"] = None
        task["claim_token"] = None
        if payload.get("last_retry_execution_code") is not None:
            task["last_retry_execution_code"] = payload["last_retry_execution_code"]
        if payload.get("result_summary") is not None:
            task["result_summary"] = payload["result_summary"]
        if payload.get("error_message") is not None:
            task["error_message"] = payload["error_message"]
        if payload.get("screenshot_asset_code") is not None:
            task["screenshot_asset_code"] = payload["screenshot_asset_code"]
        if payload.get("retry_instruction") is not None:
            task["retry_instruction"] = payload["retry_instruction"]
        self.retry_execution_receipts[retry_execution_id] = {
            "retry_task_code": retry_task_code,
            "fingerprint": fingerprint,
        }
        return task

    def _create_retry_tasks_for_execution(self, execution: dict[str, Any]) -> None:
        retryable_operations = [operation for operation in execution["operation_results"] if operation.get("retryable")]
        if retryable_operations:
            for operation in retryable_operations:
                self._create_retry_task(execution, operation)
            return
        if execution.get("retryable"):
            self._create_retry_task(execution, None)

    def _create_retry_task(self, execution: dict[str, Any], operation: dict[str, Any] | None) -> None:
        code = f"MT-RETRY-20260707-{len(self.retry_tasks) + 1:06d}"
        source = operation or execution
        task = {
            "id": f"85000000-0000-0000-0000-{len(self.retry_tasks) + 1:012d}",
            "retry_task_code": code,
            "plan_code": execution["plan_code"],
            "execution_code": execution["execution_code"],
            "slot_code": operation.get("slot_code") if operation else None,
            "asset_code": operation.get("asset_code") if operation else None,
            "executor": execution["executor"],
            "failure_type": source.get("failure_type"),
            "retryable": True,
            "retry_instruction": source.get("retry_instruction"),
            "status": "pending",
            "error_message": source.get("error_message"),
            "screenshot_asset_code": source.get("screenshot_asset_code"),
            "retry_attempt_count": 0,
            "last_retry_execution_code": None,
            "result_summary": None,
            "claimed_by": None,
            "claimed_at": None,
            "claim_expires_at": None,
            "claim_token": None,
            "lease_version": 0,
            "last_retry_execution_id": None,
            "created_at": None,
            "updated_at": None,
        }
        self.retry_tasks[code] = task

    def create_jd_live_metric_session(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        build_plan_code = payload.get("build_plan_code")
        if build_plan_code and build_plan_code not in self.build_plans:
            return None
        code = f"JD-METRIC-20260710-{len(self.jd_metric_sessions) + 1:06d}"
        row = {
            "id": f"89700000-0000-0000-0000-{len(self.jd_metric_sessions) + 1:012d}",
            "capture_session_code": code,
            "build_plan_code": build_plan_code,
            "frontend_execution_code": payload.get("frontend_execution_code"),
            "live_room_id": payload.get("live_room_id"),
            "jd_live_id": payload.get("jd_live_id"),
            "jd_shop_name": payload.get("jd_shop_name"),
            "dashboard_url": payload.get("dashboard_url"),
            "status": payload.get("status", "planned"),
            "capture_interval_seconds": payload.get("capture_interval_seconds", 30),
            "sync_start_mode": payload.get("sync_start_mode", "with_frontend_agent"),
            "current_scene_name": payload.get("current_scene_name"),
            "current_scene_index": payload.get("current_scene_index"),
            "metric_names": payload.get("metric_names")
            or [
                "online_viewers",
                "average_stay_seconds",
                "product_click_rate",
                "product_conversion_rate",
                "gmv",
                "uv_value",
                "product_exposures",
                "product_clicks",
                "transaction_count",
                "transaction_amount",
                "traffic_sources",
                "interaction_data",
            ],
            "scene_schedule": payload.get("scene_schedule", []),
            "config": payload.get("config", {}),
            "started_at": payload.get("started_at"),
            "finished_at": None,
            "result_summary": payload.get("result_summary"),
            "error_message": None,
            "created_at": None,
            "updated_at": None,
        }
        self.jd_metric_sessions[code] = row
        self.jd_metric_samples[code] = []
        return row

    def list_jd_live_metric_sessions(
        self,
        *,
        build_plan_code: str | None = None,
        frontend_execution_code: str | None = None,
        live_room_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = list(self.jd_metric_sessions.values())
        if build_plan_code is not None:
            rows = [row for row in rows if row.get("build_plan_code") == build_plan_code]
        if frontend_execution_code is not None:
            rows = [row for row in rows if row.get("frontend_execution_code") == frontend_execution_code]
        if live_room_id is not None:
            rows = [row for row in rows if row.get("live_room_id") == live_room_id]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    def get_jd_live_metric_session_by_code(self, capture_session_code: str) -> dict[str, Any] | None:
        return self.jd_metric_sessions.get(capture_session_code)

    def update_jd_live_metric_session(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.jd_metric_sessions.get(capture_session_code)
        if row is None:
            return None
        row.update(payload)
        return row

    def create_jd_live_metric_sample(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if capture_session_code not in self.jd_metric_sessions:
            return None
        sample_index = len(self.jd_metric_samples[capture_session_code])
        row = {
            "id": f"89800000-0000-0000-0000-{sample_index + 1:012d}",
            "capture_session_code": capture_session_code,
            "sample_index": sample_index,
            "sampled_at": payload.get("sampled_at"),
            "scene_name": payload.get("scene_name"),
            "scene_index": payload.get("scene_index"),
            "frontend_event_code": payload.get("frontend_event_code"),
            "live_elapsed_seconds": payload.get("live_elapsed_seconds"),
            "online_viewers": payload.get("online_viewers"),
            "average_stay_seconds": payload.get("average_stay_seconds"),
            "product_click_rate": payload.get("product_click_rate"),
            "product_conversion_rate": payload.get("product_conversion_rate"),
            "gmv": payload.get("gmv"),
            "uv_value": payload.get("uv_value"),
            "product_exposures": payload.get("product_exposures"),
            "product_clicks": payload.get("product_clicks"),
            "transaction_count": payload.get("transaction_count"),
            "transaction_amount": payload.get("transaction_amount"),
            "traffic_sources": payload.get("traffic_sources", {}),
            "interaction_data": payload.get("interaction_data", {}),
            "raw_metrics": payload.get("raw_metrics", {}),
            "screenshot_asset_code": payload.get("screenshot_asset_code"),
            "dom_snapshot_asset_code": payload.get("dom_snapshot_asset_code"),
            "status": payload.get("status", "captured"),
            "created_at": None,
            "updated_at": None,
        }
        self.jd_metric_samples[capture_session_code].append(row)
        return row

    def list_jd_live_metric_samples(
        self,
        capture_session_code: str,
        *,
        scene_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        if capture_session_code not in self.jd_metric_sessions:
            return None
        rows = list(self.jd_metric_samples[capture_session_code])
        if scene_name is not None:
            rows = [row for row in rows if row.get("scene_name") == scene_name]
        return rows[offset : offset + limit]


@pytest.fixture
def repository() -> FakeMaituMaterialSlotRepository:
    return FakeMaituMaterialSlotRepository()


@pytest.fixture
def client(repository: FakeMaituMaterialSlotRepository, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(maitu.settings, "maitu_reconciliation_operator_token", SecretStr("test-only-operator-key"))
    monkeypatch.setattr(maitu.settings, "maitu_reconciliation_operator_id", "test-operator")
    app.dependency_overrides[maitu.get_maitu_slot_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_script_scene_plan_splits_full_script_into_ordered_scenes(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-scene-plans",
        json={
            "script_text": """
            开场：大家好，欢迎来到张裕直播间，今天先用夏日主题带大家看龙谕龙8。

            产品亮点：龙谕龙8来自宁夏贺兰山东麓，适合宴请送礼，口感饱满。

            促单：现在下单有组合优惠，喜欢干红的朋友可以先点商品卡。
            """,
            "target_scene_count": 3,
            "default_scene_duration_seconds": 45,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["scene_count"] == 3
    assert body["source"] == "rule_based_v1"
    assert [scene["scene_index"] for scene in body["scenes"]] == [0, 1, 2]
    assert body["scenes"][0]["scene_goal"] == "opening"
    assert body["scenes"][1]["scene_goal"] == "product_explanation"
    assert body["scenes"][2]["scene_goal"] == "conversion"
    assert body["scenes"][0]["duration_seconds"] == 45
    assert "龙谕龙8" in body["scenes"][1]["script"]
    assert "贺兰山东麓" in body["scenes"][1]["keywords"]
    assert body["manual_review_required"] is False


def test_create_script_scene_plan_marks_ambiguous_short_script_for_review(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-scene-plans",
        json={"script_text": "今天讲一款酒。", "target_scene_count": 4},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["scene_count"] == 1
    assert body["manual_review_required"] is True
    assert body["scenes"][0]["manual_review"] is True
    assert "too_short" in body["scenes"][0]["review_reasons"]


def test_create_script_asset_needs_extracts_content_driven_needs_from_script_scenes(client: TestClient) -> None:
    scene_response = client.post(
        "/api/maitu/script-scene-plans",
        json={
            "script_text": """
            开场：大家好，欢迎来到张裕直播间，今天先用夏日主题带大家看龙谕龙8。

            产品亮点：龙谕龙8来自宁夏贺兰山东麓，有贺兰山挡风沙、黄河滋养葡萄，口感饱满。

            促单：现在下单有组合优惠，喜欢干红的朋友可以先点商品卡。
            """,
            "target_scene_count": 3,
            "default_scene_duration_seconds": 45,
        },
    )
    assert scene_response.status_code == 201
    scenes = scene_response.json()["scenes"]

    response = client.post("/api/maitu/script-asset-needs", json={"scenes": scenes})

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "script_content_asset_need_rule_v1"
    assert body["scene_count"] == 3
    assert body["manual_review_required"] is False

    product_scene = body["scenes"][1]
    needs_by_type = {need["need_type"]: need for need in product_scene["asset_needs"]}
    assert needs_by_type["product_image"]["required_category"] == "product_image"
    assert needs_by_type["product_image"]["accepted_asset_types"] == ["IMG"]
    assert "龙谕龙8" in needs_by_type["product_image"]["keywords"]
    assert needs_by_type["product_image"]["priority"] == "high"

    assert needs_by_type["background_image"]["required_category"] == "background_image"
    assert {"宁夏", "贺兰山东麓", "葡萄园"}.issubset(set(needs_by_type["background_image"]["keywords"]))
    assert "产区" in needs_by_type["background_image"]["description"]

    assert needs_by_type["supporting_visual"]["required_category"] == "floating_sticker"
    assert {"贺兰山", "黄河"}.issubset(set(needs_by_type["supporting_visual"]["keywords"]))
    assert needs_by_type["script_text"]["required_category"] == "script_text"
    assert needs_by_type["digital_human"]["required_category"] == "digital_human_video"

    conversion_scene = body["scenes"][2]
    conversion_needs = {need["need_type"]: need for need in conversion_scene["asset_needs"]}
    assert conversion_needs["promotion_sticker"]["required_category"] == "floating_sticker"
    assert {"优惠", "商品卡"}.issubset(set(conversion_needs["promotion_sticker"]["keywords"]))


def test_create_script_asset_needs_marks_sparse_scene_for_review(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-asset-needs",
        json={
            "scenes": [
                {
                    "scene_index": 0,
                    "scene_name": "场景01",
                    "scene_goal": "explanation",
                    "duration_seconds": 30,
                    "script": "今天继续聊。",
                    "keywords": [],
                    "manual_review": False,
                    "review_reasons": [],
                }
            ]
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["manual_review_required"] is True
    assert body["scenes"][0]["manual_review"] is True
    assert "insufficient_content_for_asset_needs" in body["scenes"][0]["review_reasons"]
    assert body["scenes"][0]["asset_needs"][0]["need_type"] == "script_text"


def test_create_script_asset_selections_selects_assets_for_content_needs(client: TestClient) -> None:
    scene_response = client.post(
        "/api/maitu/script-scene-plans",
        json={
            "script_text": """
            开场：大家好，欢迎来到张裕直播间，今天先用夏日主题带大家看龙谕龙8。

            产品亮点：龙谕龙8来自宁夏贺兰山东麓，有贺兰山挡风沙、黄河滋养葡萄，入口口感饱满。

            促单：现在下单有组合优惠，喜欢干红的朋友可以先点商品卡。
            """,
            "target_scene_count": 3,
            "default_scene_duration_seconds": 45,
        },
    )
    assert scene_response.status_code == 201
    needs_response = client.post("/api/maitu/script-asset-needs", json={"scenes": scene_response.json()["scenes"]})
    assert needs_response.status_code == 201

    response = client.post("/api/maitu/script-asset-selections", json={"scenes": needs_response.json()["scenes"]})

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "script_content_asset_selection_rule_v1"
    assert body["scene_count"] == 3
    assert body["missing_count"] == 0
    assert body["manual_review_required"] is False

    product_scene = body["scenes"][1]
    selections_by_need = {selection["need_type"]: selection for selection in product_scene["asset_selections"]}
    assert selections_by_need["product_image"]["status"] == "selected"
    assert selections_by_need["product_image"]["selected_asset_code"] == "AG-IMG-20260710-000101"
    assert selections_by_need["product_image"]["selected_asset_display_code"] == "MT-IMG-LONGYU8"
    assert "keyword matches asset: 龙谕龙8" in selections_by_need["product_image"]["match_reasons"]

    assert selections_by_need["background_image"]["selected_asset_code"] == "AG-IMG-20260710-000102"
    assert selections_by_need["background_image"]["selected_asset_local_file_code"] == "MT-BG-HELANS"
    assert any("贺兰山东麓" in reason for reason in selections_by_need["background_image"]["match_reasons"])

    assert selections_by_need["product_video"]["selected_asset_code"] == "AG-VID-20260710-000104"
    assert selections_by_need["script_text"]["status"] == "generated_content"

    conversion_scene = body["scenes"][2]
    conversion_selections = {selection["need_type"]: selection for selection in conversion_scene["asset_selections"]}
    assert conversion_selections["promotion_sticker"]["selected_asset_code"] == "AG-IMG-20260710-000103"
    assert conversion_selections["digital_human"]["selected_asset_code"] == "AG-VID-20260710-000105"


def test_create_script_asset_selections_marks_missing_assets_for_manual_review(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-asset-selections",
        json={
            "scenes": [
                {
                    "scene_index": 0,
                    "scene_name": "虚拟场景",
                    "scene_goal": "explanation",
                    "duration_seconds": 30,
                    "script": "这里需要一个仓库里不存在的特殊三维包装素材。",
                    "keywords": ["特殊三维包装"],
                    "asset_needs": [
                        {
                            "need_type": "special_3d_packshot",
                            "required_category": "special_3d_packshot",
                            "accepted_asset_types": ["VID"],
                            "description": "特殊三维包装旋转视频",
                            "keywords": ["特殊三维包装"],
                            "priority": "high",
                            "suggested_layer_role": "supporting_visual",
                            "reason": "测试缺口报告",
                        }
                    ],
                    "manual_review": False,
                    "review_reasons": [],
                }
            ]
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["manual_review_required"] is True
    assert body["missing_count"] == 1
    scene = body["scenes"][0]
    assert scene["manual_review"] is True
    assert "missing_asset:special_3d_packshot" in scene["review_reasons"]
    assert scene["asset_selections"][0]["status"] == "missing_asset"
    assert scene["missing_asset_needs"][0]["need_type"] == "special_3d_packshot"


def test_create_script_asset_gap_report_aggregates_missing_needs_and_blocks_auto_build(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-asset-gap-report",
        json={
            "scenes": [
                {
                    "scene_index": 0,
                    "scene_name": "开场",
                    "scene_goal": "opening",
                    "duration_seconds": 45,
                    "script": "开场展示龙谕龙8。",
                    "keywords": ["龙谕龙8"],
                    "asset_selections": [
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "龙谕龙8商品主图或瓶身图",
                            "keywords": ["龙谕龙8", "瓶身"],
                            "priority": "high",
                            "status": "missing_asset",
                        }
                    ],
                    "selected_count": 0,
                    "missing_count": 1,
                    "missing_asset_needs": [
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "龙谕龙8商品主图或瓶身图",
                            "keywords": ["龙谕龙8", "瓶身"],
                            "priority": "high",
                            "suggested_layer_role": "product_image",
                        }
                    ],
                    "manual_review": True,
                    "review_reasons": ["missing_asset:product_image"],
                },
                {
                    "scene_index": 1,
                    "scene_name": "产品亮点",
                    "scene_goal": "product_explanation",
                    "duration_seconds": 45,
                    "script": "讲解龙谕龙8整箱装。",
                    "keywords": ["龙谕龙8", "整箱"],
                    "asset_selections": [
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "龙谕龙8整箱商品图",
                            "keywords": ["龙谕龙8", "整箱"],
                            "priority": "high",
                            "status": "missing_asset",
                        }
                    ],
                    "selected_count": 0,
                    "missing_count": 1,
                    "missing_asset_needs": [
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "龙谕龙8整箱商品图",
                            "keywords": ["龙谕龙8", "整箱"],
                            "priority": "high",
                            "suggested_layer_role": "product_image",
                        }
                    ],
                    "manual_review": True,
                    "review_reasons": ["missing_asset:product_image"],
                },
            ]
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "script_content_asset_gap_report_rule_v1"
    assert body["gap_count"] == 1
    assert body["total_missing_occurrences"] == 2
    assert body["blocking_gap_count"] == 1
    assert body["can_build_with_fallback"] is False
    gap = body["gaps"][0]
    assert gap["need_type"] == "product_image"
    assert gap["required_category"] == "product_image"
    assert gap["priority"] == "high"
    assert gap["blocks_auto_build"] is True
    assert gap["affected_scene_indexes"] == [0, 1]
    assert gap["affected_scene_names"] == ["开场", "产品亮点"]
    assert {"龙谕龙8", "瓶身", "整箱"}.issubset(set(gap["keywords"]))
    assert gap["recommended_asset_specs"][0]["required_category"] == "product_image"
    assert gap["recommended_asset_specs"][0]["accepted_asset_types"] == ["IMG"]
    assert "龙谕龙8" in gap["recommended_asset_specs"][0]["suggested_filename_keywords"]
    assert "不要用无关素材硬替换" in gap["fallback_strategy"]


def test_create_script_asset_gap_report_allows_build_when_no_missing_assets(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-asset-gap-report",
        json={
            "scenes": [
                {
                    "scene_index": 0,
                    "scene_name": "开场",
                    "scene_goal": "opening",
                    "duration_seconds": 45,
                    "script": "开场展示张裕。",
                    "keywords": ["张裕"],
                    "asset_selections": [
                        {
                            "need_type": "script_text",
                            "required_category": "script_text",
                            "accepted_asset_types": ["TEXT"],
                            "description": "开场话术",
                            "keywords": ["张裕"],
                            "priority": "high",
                            "status": "generated_content",
                            "match_score": 1.0,
                        },
                        {
                            "need_type": "background_image",
                            "required_category": "background_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "品牌背景",
                            "keywords": ["张裕"],
                            "priority": "high",
                            "status": "selected",
                            "selected_asset_code": "AG-IMG-OK",
                            "match_score": 0.9,
                        },
                    ],
                    "selected_count": 1,
                    "missing_count": 0,
                    "missing_asset_needs": [],
                    "manual_review": False,
                    "review_reasons": [],
                }
            ]
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["gap_count"] == 0
    assert body["blocking_gap_count"] == 0
    assert body["can_build_with_fallback"] is True
    assert body["readiness_status"] == "ready_for_layout"


def test_create_script_layout_plan_strict_blocks_when_required_asset_is_missing(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-layout-plans",
        json={
            "build_mode": "strict",
            "scenes": [
                {
                    "scene_index": 0,
                    "scene_name": "产品亮点",
                    "scene_goal": "product_explanation",
                    "duration_seconds": 45,
                    "script": "龙谕龙8来自宁夏贺兰山东麓。",
                    "keywords": ["龙谕龙8", "贺兰山东麓"],
                    "asset_selections": [
                        {
                            "need_type": "script_text",
                            "required_category": "script_text",
                            "accepted_asset_types": ["TEXT"],
                            "description": "产品亮点话术",
                            "keywords": ["龙谕龙8"],
                            "priority": "high",
                            "status": "generated_content",
                            "match_score": 1.0,
                        },
                        {
                            "need_type": "background_image",
                            "required_category": "background_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "贺兰山东麓背景",
                            "keywords": ["贺兰山东麓"],
                            "priority": "high",
                            "status": "selected",
                            "selected_asset_code": "AG-IMG-BG",
                            "selected_asset_display_code": "MT-BG-HELANS",
                            "selected_asset_local_file_code": "MT-BG-HELANS",
                            "match_score": 0.92,
                        },
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "龙谕龙8商品主图",
                            "keywords": ["龙谕龙8"],
                            "priority": "high",
                            "status": "missing_asset",
                        },
                    ],
                    "selected_count": 1,
                    "missing_count": 1,
                    "missing_asset_needs": [
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "龙谕龙8商品主图",
                            "keywords": ["龙谕龙8"],
                            "priority": "high",
                            "suggested_layer_role": "product_image",
                        }
                    ],
                    "manual_review": True,
                    "review_reasons": ["missing_asset:product_image"],
                }
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "script_content_layout_plan_rule_v1"
    assert body["build_mode"] == "strict"
    assert body["status"] == "blocked_missing_required_assets"
    assert body["can_generate_layout"] is False
    assert body["can_generate_executable_build_plan"] is False
    assert body["blocking_gap_count"] == 1
    scene = body["scenes"][0]
    assert scene["status"] == "blocked_missing_required_assets"
    assert scene["script_block"]["text"] == "龙谕龙8来自宁夏贺兰山东麓。"
    assert [layer["layer_type"] for layer in scene["layers"]] == ["background_image"]
    assert scene["missing_placeholders"][0]["need_type"] == "product_image"


def test_create_script_layout_plan_placeholder_mode_adds_manual_placeholder_layer(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-layout-plans",
        json={
            "build_mode": "draft_with_placeholders",
            "scenes": [
                {
                    "scene_index": 0,
                    "scene_name": "促单",
                    "scene_goal": "conversion",
                    "duration_seconds": 45,
                    "script": "现在下单有组合优惠，点击商品卡。",
                    "keywords": ["优惠", "商品卡"],
                    "asset_selections": [
                        {
                            "need_type": "script_text",
                            "required_category": "script_text",
                            "accepted_asset_types": ["TEXT"],
                            "description": "促单话术",
                            "keywords": ["优惠"],
                            "priority": "high",
                            "status": "generated_content",
                            "match_score": 1.0,
                        },
                        {
                            "need_type": "digital_human",
                            "required_category": "digital_human_video",
                            "accepted_asset_types": ["VID"],
                            "description": "主播数字人",
                            "keywords": ["主播"],
                            "priority": "high",
                            "status": "selected",
                            "selected_asset_code": "AG-VID-HOST",
                            "selected_asset_display_code": "DH-HOST",
                            "selected_asset_local_file_code": "DH-HOST",
                            "match_score": 0.9,
                        },
                        {
                            "need_type": "promotion_sticker",
                            "required_category": "floating_sticker",
                            "accepted_asset_types": ["IMG"],
                            "description": "优惠商品卡贴片",
                            "keywords": ["优惠", "商品卡"],
                            "priority": "high",
                            "status": "selected",
                            "selected_asset_code": "AG-IMG-PROMO",
                            "selected_asset_display_code": "MT-STICKER-PROMO",
                            "selected_asset_local_file_code": "MT-STICKER-PROMO",
                            "selected_asset_original_filename": "promo.png",
                            "selected_asset_local_relative_path": "贴片/promo.png",
                            "selected_asset_browser_use_hint": "用于麦兔贴片素材选择：优惠 商品卡",
                            "selected_asset_maitu_material_id": 990103,
                            "selected_asset_source_material_type": "image",
                            "selected_asset_source_material_url": "https://static.maituai.example/materials/promo.png",
                            "selected_asset_source_cover_url": "https://static.maituai.example/materials/promo-cover.png",
                            "match_score": 0.88,
                        },
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "商品主图",
                            "keywords": ["龙谕龙8"],
                            "priority": "high",
                            "status": "missing_asset",
                        },
                    ],
                    "selected_count": 2,
                    "missing_count": 1,
                    "missing_asset_needs": [
                        {
                            "need_type": "product_image",
                            "required_category": "product_image",
                            "accepted_asset_types": ["IMG"],
                            "description": "商品主图",
                            "keywords": ["龙谕龙8"],
                            "priority": "high",
                            "suggested_layer_role": "product_image",
                        }
                    ],
                    "manual_review": True,
                    "review_reasons": ["missing_asset:product_image"],
                }
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["build_mode"] == "draft_with_placeholders"
    assert body["status"] == "draft_with_placeholders"
    assert body["can_generate_layout"] is True
    assert body["can_generate_executable_build_plan"] is False
    assert body["manual_review_required"] is True
    scene = body["scenes"][0]
    assert scene["status"] == "manual_review_required"
    layer_types = [layer["layer_type"] for layer in scene["layers"]]
    assert layer_types == ["digital_human", "product_image", "promotion_sticker"]
    product_layer = next(layer for layer in scene["layers"] if layer["layer_type"] == "product_image")
    assert product_layer["status"] == "placeholder_required"
    assert product_layer["asset_code"] is None
    assert product_layer["x"] == 720
    assert product_layer["y"] == 980
    assert product_layer["z_index"] == 5
    promo_layer = next(layer for layer in scene["layers"] if layer["layer_type"] == "promotion_sticker")
    assert promo_layer["asset_code"] == "AG-IMG-PROMO"
    assert promo_layer["asset_local_relative_path"] == "贴片/promo.png"
    assert promo_layer["asset_browser_use_hint"] == "用于麦兔贴片素材选择：优惠 商品卡"
    assert promo_layer["maitu_material_id"] == 990103
    assert promo_layer["source_material_url"].endswith("promo.png")
    assert promo_layer["source_cover_url"].endswith("promo-cover.png")
    assert promo_layer["x"] == 80
    assert promo_layer["y"] == 1240
    assert scene["script_block"]["status"] == "ready"


def test_create_script_layout_build_plan_strict_returns_blocked_without_operations(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-layout-build-plans",
        json={
            "target_live_room_id": "47000001",
            "layout_plan": {
                "source": "script_content_layout_plan_rule_v1",
                "build_mode": "strict",
                "status": "blocked_missing_required_assets",
                "scene_count": 1,
                "blocking_gap_count": 1,
                "can_generate_layout": False,
                "can_generate_executable_build_plan": False,
                "manual_review_required": True,
                "scenes": [
                    {
                        "scene_index": 0,
                        "scene_name": "产品亮点",
                        "scene_goal": "product_explanation",
                        "status": "blocked_missing_required_assets",
                        "canvas": {"width": 1080, "height": 1920},
                        "layers": [
                            {
                                "layer_id": "scene-00-background_image",
                                "layer_type": "background_image",
                                "need_type": "background_image",
                                "status": "ready",
                                "required_category": "background_image",
                                "asset_code": "AG-IMG-BG",
                                "asset_display_code": "MT-BG-HELANS",
                                "asset_local_file_code": "MT-BG-HELANS",
                                "asset_original_filename": "helan-bg.png",
                                "asset_local_relative_path": "背景/helan-bg.png",
                                "asset_browser_use_hint": "用于麦兔背景素材选择：贺兰山",
                                "maitu_material_id": 990102,
                                "source_material_type": "image",
                                "source_material_url": "https://static.maituai.example/materials/helan-bg.png",
                                "source_cover_url": "https://static.maituai.example/materials/helan-bg-cover.png",
                                "x": 0,
                                "y": 0,
                                "width": 1080,
                                "height": 1920,
                                "z_index": 1,
                            }
                        ],
                        "script_block": {"status": "ready", "target": "maitu_script_panel", "text": "龙谕龙8来自宁夏贺兰山东麓。"},
                        "missing_placeholders": [
                            {
                                "layer_id": "scene-00-product_image",
                                "layer_type": "product_image",
                                "need_type": "product_image",
                                "status": "placeholder_required",
                                "required_category": "product_image",
                                "asset_code": None,
                                "x": 720,
                                "y": 980,
                                "width": 280,
                                "height": 280,
                                "z_index": 5,
                            }
                        ],
                        "review_reasons": ["missing_asset:product_image"],
                    }
                ],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "script_content_layout_build_plan_rule_v1"
    assert body["status"] == "blocked_missing_required_assets"
    assert body["can_execute"] is False
    assert body["manual_review_required"] is True
    assert body["operation_count"] == 0
    assert body["operations"] == []
    assert "layout_plan_blocked" in body["blocked_reasons"]


def test_create_script_layout_build_plan_placeholder_generates_safe_draft_operations(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-layout-build-plans",
        json={
            "target_live_room_id": "47000002",
            "layout_plan": {
                "source": "script_content_layout_plan_rule_v1",
                "build_mode": "draft_with_placeholders",
                "status": "draft_with_placeholders",
                "scene_count": 2,
                "blocking_gap_count": 1,
                "can_generate_layout": True,
                "can_generate_executable_build_plan": False,
                "manual_review_required": True,
                "scenes": [
                    {
                        "scene_index": 0,
                        "scene_name": "开场",
                        "scene_goal": "opening",
                        "status": "manual_review_required",
                        "canvas": {"width": 1080, "height": 1920},
                        "layers": [
                            {
                                "layer_id": "scene-00-background_image",
                                "layer_type": "background_image",
                                "need_type": "background_image",
                                "status": "ready",
                                "required_category": "background_image",
                                "asset_code": "AG-IMG-BG",
                                "asset_display_code": "MT-BG-HELANS",
                                "asset_local_file_code": "MT-BG-HELANS",
                                "asset_original_filename": "helan-bg.png",
                                "asset_local_relative_path": "背景/helan-bg.png",
                                "asset_browser_use_hint": "用于麦兔背景素材选择：贺兰山",
                                "maitu_material_id": 990102,
                                "source_material_type": "image",
                                "source_material_url": "https://static.maituai.example/materials/helan-bg.png",
                                "source_cover_url": "https://static.maituai.example/materials/helan-bg-cover.png",
                                "x": 0,
                                "y": 0,
                                "width": 1080,
                                "height": 1920,
                                "z_index": 1,
                            },
                            {
                                "layer_id": "scene-00-product_image",
                                "layer_type": "product_image",
                                "need_type": "product_image",
                                "status": "placeholder_required",
                                "required_category": "product_image",
                                "asset_code": None,
                                "x": 720,
                                "y": 980,
                                "width": 280,
                                "height": 280,
                                "z_index": 5,
                            },
                        ],
                        "script_block": {"status": "ready", "target": "maitu_script_panel", "text": "欢迎来到张裕直播间。"},
                        "missing_placeholders": [],
                        "review_reasons": ["missing_asset:product_image"],
                    },
                    {
                        "scene_index": 1,
                        "scene_name": "促单",
                        "scene_goal": "conversion",
                        "status": "ready",
                        "canvas": {"width": 1080, "height": 1920},
                        "layers": [
                            {
                                "layer_id": "scene-01-digital_human",
                                "layer_type": "digital_human",
                                "need_type": "digital_human",
                                "status": "ready",
                                "required_category": "digital_human_video",
                                "asset_code": "AG-VID-HOST",
                                "asset_display_code": "DH-HOST",
                                "asset_local_file_code": "DH-HOST",
                                "x": 160,
                                "y": 520,
                                "width": 760,
                                "height": 1300,
                                "z_index": 3,
                            }
                        ],
                        "script_block": {"status": "ready", "target": "maitu_script_panel", "text": "现在下单有组合优惠。"},
                        "missing_placeholders": [],
                        "review_reasons": [],
                    },
                ],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft_with_placeholders"
    assert body["target_live_room_id"] == "47000002"
    assert body["can_execute"] is False
    assert body["manual_review_required"] is True
    operation_types = [operation["operation_type"] for operation in body["operations"]]
    assert operation_types[:2] == ["preflight_content_build_plan", "fill_default_scene"]
    assert "create_scene" in operation_types
    assert "insert_asset_layer" in operation_types
    assert "position_asset_layer" in operation_types
    assert "placeholder_required" in operation_types
    assert operation_types.count("write_script") == 2
    assert operation_types[-1] == "save_draft"

    fill_default = next(operation for operation in body["operations"] if operation["operation_type"] == "fill_default_scene")
    assert fill_default["scene_index"] == 0
    assert fill_default["status"] == "ready"

    create_scene = next(operation for operation in body["operations"] if operation["operation_type"] == "create_scene")
    assert create_scene["scene_index"] == 1
    assert create_scene["status"] == "ready"

    insert_bg = next(
        operation
        for operation in body["operations"]
        if operation["operation_type"] == "insert_asset_layer" and operation["asset_code"] == "AG-IMG-BG"
    )
    assert insert_bg["scene_index"] == 0
    assert insert_bg["asset_local_relative_path"] == "背景/helan-bg.png"
    assert insert_bg["asset_browser_use_hint"] == "用于麦兔背景素材选择：贺兰山"
    assert insert_bg["material_id"] == 990102
    assert insert_bg["source_material_url"].endswith("helan-bg.png")
    assert insert_bg["source_cover_url"].endswith("helan-bg-cover.png")
    assert insert_bg["x"] == 0
    assert insert_bg["y"] == 0
    assert insert_bg["z_index"] == 1

    placeholder = next(operation for operation in body["operations"] if operation["operation_type"] == "placeholder_required")
    assert placeholder["need_type"] == "product_image"
    assert placeholder["status"] == "manual_required"
    assert placeholder["asset_code"] is None
    assert placeholder["blocks_execution"] is True

    script_ops = [operation for operation in body["operations"] if operation["operation_type"] == "write_script"]
    assert script_ops[0]["script_text"] == "欢迎来到张裕直播间。"
    assert script_ops[1]["script_text"] == "现在下单有组合优惠。"
    assert body["operations"][-1]["status"] == "manual_review"


def test_create_script_scene_template_matches_maps_each_script_scene_to_one_template_and_assets(client: TestClient) -> None:
    import_response = client.post(
        "/api/maitu/live-room-blueprints/import-reference",
        json={
            "reference_profile": {
                "profile_code": "MT-REF-20260710-STAGE3",
                "source": "browser_use_observe",
                "reference_room_id": "39829",
                "reference_room_name": "张裕多场景模板库",
                "platform": "京东",
                "active_scene_name": "开场留人",
            },
            "blueprint": {
                "blueprint_code": "MT-BP-20260710-STAGE3",
                "reference_profile_code": "MT-REF-20260710-STAGE3",
                "template_library_code": "MT-TPL-LIB-20260710-STAGE3",
                "title": "张裕多场景模板库",
                "platform": "京东",
                "room_type": "reference_rebuild",
                "reference_room_id": "39829",
                "reference_room_name": "张裕多场景模板库",
                "status": "draft",
                "scenes": [
                    {
                        "scene_code": "MT-SCENE-STAGE3-OPENING",
                        "scene_name": "开场留人",
                        "scene_type": "opening",
                        "sort_order": 1,
                        "layers": [
                            {
                                "layer_code": "MT-LAYER-STAGE3-BG",
                                "layer_name": "夏日背景",
                                "layer_role": "background",
                                "required_category": "background_image",
                                "accepted_asset_types": ["IMG"],
                                "replacement_policy": "keep_layout",
                            }
                        ],
                    },
                    {
                        "scene_code": "MT-SCENE-STAGE3-PRODUCT",
                        "scene_name": "产品讲解",
                        "scene_type": "product_explanation",
                        "sort_order": 2,
                        "layers": [
                            {
                                "layer_code": "MT-LAYER-STAGE3-VIDEO",
                                "layer_name": "商品讲解视频",
                                "layer_role": "product_video",
                                "required_category": "product_video",
                                "accepted_asset_types": ["VID"],
                                "replacement_policy": "keep_layout",
                            }
                        ],
                    },
                    {
                        "scene_code": "MT-SCENE-STAGE3-CONVERSION",
                        "scene_name": "促单转化",
                        "scene_type": "conversion",
                        "sort_order": 3,
                        "layers": [
                            {
                                "layer_code": "MT-LAYER-STAGE3-PRODUCT-IMAGE",
                                "layer_name": "商品主图",
                                "layer_role": "product_image",
                                "required_category": "product_image",
                                "accepted_asset_types": ["IMG"],
                                "replacement_policy": "keep_layout",
                            }
                        ],
                    },
                ],
                "script_blocks": [
                    {
                        "script_block_code": "MT-SCRIPT-STAGE3-OPENING",
                        "scene_name": "开场留人",
                        "sort_order": 1,
                        "content": "欢迎来到张裕直播间，夏日主题开场先留住新进来的朋友。",
                    },
                    {
                        "script_block_code": "MT-SCRIPT-STAGE3-PRODUCT",
                        "scene_name": "产品讲解",
                        "sort_order": 2,
                        "content": "产品亮点是龙谕龙8，来自宁夏贺兰山东麓，讲清楚风土和口感。",
                    },
                    {
                        "script_block_code": "MT-SCRIPT-STAGE3-CONVERSION",
                        "scene_name": "促单转化",
                        "sort_order": 3,
                        "content": "促单阶段提醒大家点商品卡，下单享受优惠福利。",
                    },
                ],
                "safety_rules": ["默认不点击正式开播"],
            },
        },
    )
    assert import_response.status_code == 201

    plan_response = client.post(
        "/api/maitu/script-scene-plans",
        json={
            "script_text": """
            开场：大家好，欢迎来到张裕直播间，今天先用夏日主题带大家看龙谕龙8。

            产品亮点：龙谕龙8来自宁夏贺兰山东麓，适合宴请送礼，口感饱满。

            促单：现在下单有组合优惠，喜欢干红的朋友可以先点商品卡。
            """,
            "target_scene_count": 3,
            "default_scene_duration_seconds": 45,
        },
    )
    assert plan_response.status_code == 201
    scenes = plan_response.json()["scenes"]

    match_response = client.post(
        "/api/maitu/script-scene-template-matches",
        json={
            "scenes": scenes,
            "blueprint_code": "MT-BP-20260710-STAGE3",
            "auto_select_assets": True,
        },
    )

    assert match_response.status_code == 201
    body = match_response.json()
    assert body["source"] == "rule_based_template_component_match_v1"
    assert body["scene_count"] == 3
    assert body["matched_scene_count"] == 3
    assert body["manual_review_required"] is False
    assert [match["matched_template_scene_code"] for match in body["matches"]] == [
        "MT-SCENE-STAGE3-OPENING",
        "MT-SCENE-STAGE3-PRODUCT",
        "MT-SCENE-STAGE3-CONVERSION",
    ]
    assert all(match["component_count"] == 1 for match in body["matches"])
    assert all(match["confidence"] >= 0.35 for match in body["matches"])

    product_match = body["matches"][1]
    assert product_match["scene_index"] == 1
    assert product_match["matched_template_scene_name"] == "产品讲解"
    assert product_match["component_selections"][0]["component_template_code"] == "MT-LAYER-STAGE3-VIDEO"
    assert product_match["component_selections"][0]["status"] == "selected"
    assert product_match["component_selections"][0]["selected_asset_code"] == "AG-VID-20260710-000104"
    assert product_match["component_selections"][0]["selected_asset_display_code"] == "MT-VID-LONGYU8"

    opening_selection = body["matches"][0]["component_selections"][0]
    assert opening_selection["selected_asset_code"] == "AG-IMG-20260709-000070"
    assert opening_selection["selected_asset_local_file_code"] == "MT-BG-0001"
    assert "MT-TPL" not in opening_selection["selected_asset_local_file_code"]


def test_script_scene_template_matches_marks_low_confidence_scene_for_manual_review(client: TestClient) -> None:
    import_response = client.post(
        "/api/maitu/live-room-blueprints/import-reference",
        json={
            "reference_profile": {
                "profile_code": "MT-REF-20260710-LOWCONF",
                "source": "browser_use_observe",
                "reference_room_id": "39830",
                "reference_room_name": "低置信度模板库",
                "platform": "京东",
            },
            "blueprint": {
                "blueprint_code": "MT-BP-20260710-LOWCONF",
                "reference_profile_code": "MT-REF-20260710-LOWCONF",
                "title": "低置信度模板库",
                "platform": "京东",
                "room_type": "reference_rebuild",
                "reference_room_id": "39830",
                "status": "draft",
                "scenes": [
                    {
                        "scene_code": "MT-SCENE-LOWCONF-PRODUCT",
                        "scene_name": "产品讲解",
                        "scene_type": "product_explanation",
                        "sort_order": 1,
                        "layers": [],
                    }
                ],
                "script_blocks": [
                    {
                        "script_block_code": "MT-SCRIPT-LOWCONF-PRODUCT",
                        "scene_name": "产品讲解",
                        "content": "讲清楚商品卖点和口感。",
                    }
                ],
            },
        },
    )
    assert import_response.status_code == 201

    match_response = client.post(
        "/api/maitu/script-scene-template-matches",
        json={
            "scenes": [
                {
                    "scene_index": 0,
                    "scene_name": "抽奖互动",
                    "scene_goal": "interaction",
                    "duration_seconds": 30,
                    "script": "我们马上做一轮评论区抽奖，关注主播并回复口令。",
                    "keywords": [],
                    "manual_review": False,
                    "review_reasons": [],
                }
            ],
            "blueprint_code": "MT-BP-20260710-LOWCONF",
            "min_confidence_for_auto_match": 0.3,
        },
    )

    assert match_response.status_code == 201
    body = match_response.json()
    assert body["manual_review_required"] is True
    assert body["matches"][0]["manual_review"] is True
    assert "low_confidence_template_match" in body["matches"][0]["review_reasons"]


def test_create_jd_live_metric_session_and_samples(client: TestClient) -> None:
    create_response = client.post(
        "/api/maitu/jd-live-metric-sessions",
        json={
            "live_room_id": "40173",
            "jd_live_id": "JD-LIVE-40173",
            "jd_shop_name": "张裕京东旗舰店",
            "dashboard_url": "https://example.jd.com/live-data",
            "status": "running",
            "capture_interval_seconds": 15,
            "frontend_execution_code": "MT-EXEC-20260710-000010",
            "current_scene_name": "商品01-场景01",
            "current_scene_index": 0,
            "scene_schedule": [
                {"scene_index": 0, "scene_name": "商品01-场景01", "start_offset_seconds": 0, "end_offset_seconds": 60}
            ],
        },
    )

    assert create_response.status_code == 201
    session = create_response.json()
    assert session["capture_session_code"] == "JD-METRIC-20260710-000001"
    assert session["sync_start_mode"] == "with_frontend_agent"
    assert session["capture_interval_seconds"] == 15
    assert "online_viewers" in session["metric_names"]
    assert "gmv" in session["metric_names"]

    sample_response = client.post(
        f"/api/maitu/jd-live-metric-sessions/{session['capture_session_code']}/samples",
        json={
            "scene_name": "商品01-场景01",
            "scene_index": 0,
            "live_elapsed_seconds": 30,
            "online_viewers": 128,
            "average_stay_seconds": 42.5,
            "product_click_rate": 0.18,
            "product_conversion_rate": 0.031,
            "gmv": 9865.5,
            "uv_value": 12.34,
            "product_exposures": 1200,
            "product_clicks": 216,
            "transaction_count": 11,
            "transaction_amount": 9865.5,
            "traffic_sources": {"推荐": 80, "店铺": 48},
            "interaction_data": {"comments": 14, "likes": 266},
            "raw_metrics": {"source": "browser_use_jd_dashboard"},
        },
    )

    assert sample_response.status_code == 201
    sample = sample_response.json()
    assert sample["sample_index"] == 0
    assert sample["online_viewers"] == 128
    assert sample["traffic_sources"]["推荐"] == 80

    list_response = client.get(
        f"/api/maitu/jd-live-metric-sessions/{session['capture_session_code']}/samples",
        params={"scene_name": "商品01-场景01"},
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["gmv"] == 9865.5

    update_response = client.patch(
        f"/api/maitu/jd-live-metric-sessions/{session['capture_session_code']}",
        json={"status": "completed", "result_summary": "同步抓取完成"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "completed"


def test_create_list_get_update_and_delete_maitu_slot(client: TestClient) -> None:
    create_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "scene_index": 0,
            "layer_name": "layer_8",
            "layer_index": 8,
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
            "aspect_ratio": "1:1",
            "left_position": 840,
            "top_position": 180,
            "width": 460,
            "height": 460,
            "z_index": 8,
            "replacement_policy": "keep_layout",
            "description": "麦兔直播间中的商品主图槽位，只替换素材，不改布局。",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["slot_code"] == "MT-SLOT-20260707-000001"
    assert created["required_category"] == "product_image"
    assert created["accepted_asset_types"] == ["IMG"]
    assert created["replacement_policy"] == "keep_layout"

    list_response = client.get(
        "/api/maitu/slots",
        params={
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "required_category": "product_image",
            "slot_name": "商品主图",
            "q": "商品主图",
        },
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["slot_code"] == created["slot_code"]

    get_response = client.get(f"/api/maitu/slots/{created['slot_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["layer_name"] == "layer_8"

    update_response = client.patch(
        f"/api/maitu/slots/{created['slot_code']}",
        json={"replacement_policy": "fit_contain", "description": "商品主图允许等比适配。"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["replacement_policy"] == "fit_contain"

    candidates_response = client.get(f"/api/maitu/slots/{created['slot_code']}/candidate-assets")
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert candidates["slot_code"] == created["slot_code"]
    assert candidates["required_category"] == "product_image"
    assert candidates["accepted_asset_types"] == ["IMG"]
    assert candidates["assets"][0]["asset_code"] == "AG-IMG-20260707-000001"
    assert candidates["assets"][0]["match_score"] == 1.0
    assert "maitu_slot_code matches" in candidates["assets"][0]["match_reasons"][-1]

    delete_response = client.delete(f"/api/maitu/slots/{created['slot_code']}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/api/maitu/slots/{created['slot_code']}")
    assert missing_response.status_code == 404


def test_get_missing_maitu_slot_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/slots/MT-SLOT-20260707-999999")

    assert response.status_code == 404


def test_create_list_and_get_replacement_plan(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]

    create_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "京东空白直播间商品素材替换方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
            "strategy": "best_match",
            "description": "自动为麦兔模板选择商品主图素材。",
        },
    )

    assert create_response.status_code == 201
    plan = create_response.json()
    assert plan["plan_code"] == "MT-PLAN-20260707-000001"
    assert plan["items"][0]["slot_code"] == slot_code
    assert plan["items"][0]["selected_asset_code"] == "AG-IMG-20260707-000001"
    assert plan["items"][0]["status"] == "selected"

    list_response = client.get(
        "/api/maitu/replacement-plans",
        params={"maitu_project_code": "MT-PROJ-20260707-000001", "status": "draft"},
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["plan_code"] == plan["plan_code"]

    get_response = client.get(f"/api/maitu/replacement-plans/{plan['plan_code']}")
    assert get_response.status_code == 200
    assert get_response.json()["items"][0]["match_score"] == 1.0

    operations_response = client.get(f"/api/maitu/replacement-plans/{plan['plan_code']}/browser-use-operations")
    assert operations_response.status_code == 200
    operations = operations_response.json()
    operation = operations["operations"][0]
    assert operations["executor"] == "browser_use"
    assert operations["target_app"] == "maitu"
    assert operation["operation_type"] == "replace_layer_asset"
    assert operation["asset_code"] == "AG-IMG-20260707-000001"
    assert operation["asset_display_code"] == "MT-IMG-0001"
    assert operation["asset_local_file_code"] == "MT-IMG-0001"
    assert operation["asset_original_filename"] == "collagen-main.png"
    assert operation["asset_browser_use_hint"] == "用于麦兔图片素材选择：胶原蛋白商品主图"
    assert "Browser" not in operation["instruction"]
    assert "MT-IMG-0001" in operation["instruction"]
    assert "保持原图层位置和尺寸不变" in operation["instruction"]


def test_create_list_and_get_browser_use_execution_result(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]

    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "京东空白直播间商品素材替换方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    plan_code = plan_response.json()["plan_code"]

    create_response = client.post(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "succeeded",
            "started_at": "2026-07-07T09:00:00Z",
            "finished_at": "2026-07-07T09:02:00Z",
            "screenshot_asset_code": "AG-IMG-20260707-000099",
            "result_summary": "Browser use 已在麦兔中完成商品主图替换并保存项目。",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "succeeded",
                    "screenshot_asset_code": "AG-IMG-20260707-000099",
                    "details": {"layer_name": "layer_8", "saved": True},
                }
            ],
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["execution_code"] == "MT-EXEC-20260707-000001"
    assert created["executor"] == "browser_use"
    assert created["execution_status"] == "succeeded"
    assert created["operation_results"][0]["slot_code"] == slot_code
    assert created["operation_results"][0]["status"] == "succeeded"
    assert created["operation_results"][0]["details"]["saved"] is True

    list_response = client.get(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        params={"executor": "browser_use", "execution_status": "succeeded"},
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["execution_code"] == created["execution_code"]

    get_response = client.get(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results/{created['execution_code']}"
    )
    assert get_response.status_code == 200
    assert get_response.json()["result_summary"].startswith("Browser use 已在麦兔中完成")

    refreshed_plan_response = client.get(f"/api/maitu/replacement-plans/{plan_code}")
    assert refreshed_plan_response.status_code == 200
    assert refreshed_plan_response.json()["status"] == "executed"


def test_failed_browser_use_execution_classifies_failure_and_creates_retry_task(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={"plan_name": "失败可重试方案", "slot_codes": [slot_code]},
    )
    plan_code = plan_response.json()["plan_code"]

    create_response = client.post(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "failure_type": "missing_layer",
            "retryable": True,
            "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后只重试该槽位。",
            "result_summary": "商品主图图层未定位成功，其他步骤跳过。",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                    "details": {"layer_name": "layer_8", "selector": None},
                }
            ],
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["execution_status"] == "partial_failed"
    assert created["failure_type"] == "missing_layer"
    assert created["retryable"] is True
    assert "重新扫描麦兔场景图层树" in created["retry_instruction"]
    assert created["operation_results"][0]["failure_type"] == "missing_layer"
    assert created["operation_results"][0]["retryable"] is True

    retry_list_response = client.get(
        "/api/maitu/retry-tasks",
        params={"plan_code": plan_code, "status": "pending", "failure_type": "missing_layer"},
    )
    assert retry_list_response.status_code == 200
    retry_task = retry_list_response.json()[0]
    assert retry_task["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert retry_task["plan_code"] == plan_code
    assert retry_task["execution_code"] == created["execution_code"]
    assert retry_task["slot_code"] == slot_code
    assert retry_task["failure_type"] == "missing_layer"
    assert retry_task["retryable"] is True
    assert retry_task["status"] == "pending"
    assert "定位 layer_8" in retry_task["retry_instruction"]

    get_retry_response = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}")
    assert get_retry_response.status_code == 200
    assert get_retry_response.json()["error_message"] == "Browser use 未找到 layer_8。"

    update_retry_response = client.patch(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}",
        json={"result_summary": "准备交给 Browser use 重新定位 layer_8。"},
    )
    assert update_retry_response.status_code == 200
    assert update_retry_response.json()["status"] == "pending"
    assert update_retry_response.json()["retry_attempt_count"] == 0

    claim_response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={"claimed_by": "worker-1", "lock_ttl_seconds": 120},
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["status"] == "in_progress"
    assert claim_response.json()["retry_attempt_count"] == 0


def test_retry_task_browser_use_operations_plan_contains_minimal_retry_steps(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "商品主图重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    plan_code = plan_response.json()["plan_code"]
    execution_response = client.post(
        f"/api/maitu/replacement-plans/{plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    retry_task = client.get(
        "/api/maitu/retry-tasks",
        params={"execution_code": execution_response.json()["execution_code"]},
    ).json()[0]

    response = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/browser-use-operations")

    assert response.status_code == 200
    operation_plan = response.json()
    assert operation_plan["retry_task_code"] == retry_task["retry_task_code"]
    assert operation_plan["plan_code"] == plan_code
    assert operation_plan["execution_code"] == execution_response.json()["execution_code"]
    assert operation_plan["executor"] == "browser_use"
    assert operation_plan["target_app"] == "maitu"
    operation = operation_plan["operations"][0]
    assert operation["operation_type"] == "retry_replace_layer_asset"
    assert operation["slot_code"] == slot_code
    assert operation["layer_name"] == "layer_8"
    assert operation["asset_code"] == "AG-IMG-20260707-000001"
    assert operation["asset_title"] == "胶原蛋白商品主图-白底款"
    assert operation["failure_type"] == "missing_layer"
    assert operation["status"] == "ready"
    assert "重试任务" in operation["instruction"]
    assert "只重试槽位" in operation["instruction"]
    assert "保持原图层位置和尺寸不变" in operation["instruction"]


def _create_retry_task(client: TestClient, *, plan_name: str = "商品主图重试结果方案") -> dict[str, Any]:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={"plan_name": plan_name, "slot_codes": [slot_code]},
    )
    execution_response = client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    return client.get(
        "/api/maitu/retry-tasks",
        params={"execution_code": execution_response.json()["execution_code"]},
    ).json()[0]


def _claim_retry_task(client: TestClient, *, claimed_by: str = "browser-use-worker-1") -> dict[str, Any]:
    response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={"claimed_by": claimed_by, "lock_ttl_seconds": 900, "max_attempts": 3},
    )
    assert response.status_code == 200
    return response.json()


def _lease_payload(claimed: dict[str, Any]) -> dict[str, Any]:
    return {
        "claimed_by": claimed["claimed_by"],
        "claim_token": claimed["claim_token"],
        "lease_version": claimed["lease_version"],
    }


def test_retry_operation_checkpoint_begin_and_complete_are_lease_fenced_and_token_free(client: TestClient) -> None:
    retry_task = _create_retry_task(client, plan_name="checkpoint route plan")
    claimed = _claim_retry_task(client)
    operation_plan = client.get(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/browser-use-operations"
    ).json()
    operation = operation_plan["operations"][0]
    path = (
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}"
        f"/operations/{operation['operation_key']}"
    )
    attempt_id = "87715675-af7c-4b75-9d4c-14f9c45e20f4"
    begin_payload = {
        **_lease_payload(claimed),
        "attempt_id": attempt_id,
        "operation_fingerprint": operation["operation_fingerprint"],
    }

    begun = client.post(f"{path}/begin", json=begin_payload)
    duplicate_begin = client.post(f"{path}/begin", json=begin_payload)
    completed = client.post(
        f"{path}/complete",
        json={
            **begin_payload,
            "completion_id": "f8e2ad75-270d-4190-8255-7334399f7c8d",
            "evidence": {"verified": True, "material_id": 41043},
        },
    )

    assert begun.status_code == 200
    assert duplicate_begin.status_code == 200
    assert begun.json()["decision"] == "execute"
    assert duplicate_begin.json()["attempt_id"] == attempt_id
    assert completed.status_code == 200
    assert completed.json()["state"] == "completed"
    assert completed.json()["decision"] == "skip"
    assert "claim_token" not in completed.json()
    assert "claim_token" not in json.dumps(completed.json())


def test_retry_operation_checkpoint_rejects_stale_lease_and_fingerprint_drift(client: TestClient) -> None:
    retry_task = _create_retry_task(client, plan_name="checkpoint conflict plan")
    claimed = _claim_retry_task(client)
    operation = client.get(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/browser-use-operations"
    ).json()["operations"][0]
    path = (
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}"
        f"/operations/{operation['operation_key']}/begin"
    )
    base_payload = {
        **_lease_payload(claimed),
        "attempt_id": "87715675-af7c-4b75-9d4c-14f9c45e20f4",
        "operation_fingerprint": operation["operation_fingerprint"],
    }

    stale = client.post(path, json={**base_payload, "lease_version": claimed["lease_version"] + 1})
    drift = client.post(path, json={**base_payload, "operation_fingerprint": "f" * 64})

    assert stale.status_code == 409
    assert drift.status_code == 409


def test_active_retry_lease_freezes_slot_and_explicit_release_requires_reconciliation(client: TestClient) -> None:
    retry_task = _create_retry_task(client, plan_name="frozen authoritative intent")
    claimed = _claim_retry_task(client)
    operation = client.get(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/browser-use-operations"
    ).json()["operations"][0]
    begin_payload = {
        **_lease_payload(claimed),
        "attempt_id": "87715675-af7c-4b75-9d4c-14f9c45e20f4",
        "operation_fingerprint": operation["operation_fingerprint"],
    }
    checkpoint_path = (
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}"
        f"/operations/{operation['operation_key']}"
    )
    assert client.post(f"{checkpoint_path}/begin", json=begin_payload).status_code == 200

    slot_code = retry_task["slot_code"]
    assert client.patch(f"/api/maitu/slots/{slot_code}", json={"layer_name": "unsafe-layer"}).status_code == 409
    assert client.delete(f"/api/maitu/slots/{slot_code}").status_code == 409

    released = client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/release",
        json={**_lease_payload(claimed), "status": "pending"},
    )
    assert released.status_code == 200
    reclaimed = _claim_retry_task(client)
    reconcile = client.post(
        f"{checkpoint_path}/begin",
        json={
            **_lease_payload(reclaimed),
            "attempt_id": "98826786-af7c-4b75-9d4c-14f9c45e20f4",
            "operation_fingerprint": operation["operation_fingerprint"],
        },
    )
    assert reconcile.status_code == 200
    assert reconcile.json()["decision"] == "reconcile"


def test_retry_operation_reconciliation_is_audited_idempotent_and_one_shot(client: TestClient) -> None:
    retry_task = _create_retry_task(client, plan_name="reconciliation route plan")
    claimed = _claim_retry_task(client)
    operation = client.get(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/browser-use-operations"
    ).json()["operations"][0]
    checkpoint_path = (
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}"
        f"/operations/{operation['operation_key']}"
    )
    begin_payload = {
        **_lease_payload(claimed),
        "attempt_id": "87715675-af7c-4b75-9d4c-14f9c45e20f4",
        "operation_fingerprint": operation["operation_fingerprint"],
    }
    assert client.post(f"{checkpoint_path}/begin", json=begin_payload).status_code == 200

    reconciliation_payload = {
        "reconciliation_id": "d8f7a0e1-6c2e-4fd0-86e0-9999d0010001",
        "expected_attempt_id": begin_payload["attempt_id"],
        "operation_fingerprint": operation["operation_fingerprint"],
        "resolution": "confirmed_not_applied",
        "resolution_summary": "麦兔权威读回确认该操作未生效",
        "evidence": {"verified": True, "operation_applied": False, "readback": "layer unchanged"},
    }
    operator_headers = {"Authorization": "Bearer test-only-operator-key"}
    assert client.post(f"{checkpoint_path}/reconcile", json=reconciliation_payload).status_code == 401
    assert client.post(
        f"{checkpoint_path}/reconcile",
        json=reconciliation_payload,
        headers=operator_headers,
    ).status_code == 409
    assert client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/release",
        json={**_lease_payload(claimed), "status": "pending"},
    ).status_code == 200
    audit_path = f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/operation-checkpoints"
    assert client.get(audit_path).status_code == 401
    checkpoint_audit = client.get(audit_path, headers=operator_headers)
    assert checkpoint_audit.status_code == 200
    assert checkpoint_audit.json()[0]["state"] == "reconcile_required"
    reconciliation_payload["expected_attempt_id"] = checkpoint_audit.json()[0]["attempt_id"]

    reflected_bearer = "Bearer reflected-" + "x" * 32
    bearer_rejection = client.post(
        f"{checkpoint_path}/reconcile",
        json={
            **reconciliation_payload,
            "evidence": {
                **reconciliation_payload["evidence"],
                "readback": reflected_bearer,
            },
        },
        headers=operator_headers,
    )
    assert bearer_rejection.status_code == 422
    assert reflected_bearer not in bearer_rejection.text

    reflected_provider_token = "github_pat_" + "x" * 32
    provider_rejection = client.post(
        f"{checkpoint_path}/reconcile",
        json={
            **reconciliation_payload,
            "evidence": {
                **reconciliation_payload["evidence"],
                "readback": reflected_provider_token,
            },
        },
        headers=operator_headers,
    )
    assert provider_rejection.status_code == 422
    assert reflected_provider_token not in provider_rejection.text

    reflected_extra_key = "github_pat_" + "y" * 32
    extra_key_rejection = client.post(
        f"{checkpoint_path}/reconcile",
        json={
            **reconciliation_payload,
            reflected_extra_key: "must-not-reflect",
        },
        headers=operator_headers,
    )
    assert extra_key_rejection.status_code == 422
    assert reflected_extra_key not in extra_key_rejection.text

    secret_payloads = [
        {**reconciliation_payload, "resolution_summary": "test-only-operator-key"},
        {
            **reconciliation_payload,
            "evidence": {
                **reconciliation_payload["evidence"],
                "readback": "value includes test-only-operator-key",
            },
        },
        {
            **reconciliation_payload,
            "evidence": {
                **reconciliation_payload["evidence"],
                "test-only-operator-key": "must-not-persist",
            },
        },
    ]
    for secret_payload in secret_payloads:
        rejected = client.post(
            f"{checkpoint_path}/reconcile",
            json=secret_payload,
            headers=operator_headers,
        )
        assert rejected.status_code == 422

    reconciled = client.post(
        f"{checkpoint_path}/reconcile", json=reconciliation_payload, headers=operator_headers
    )
    duplicate = client.post(
        f"{checkpoint_path}/reconcile", json=reconciliation_payload, headers=operator_headers
    )
    assert reconciled.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json() == reconciled.json()
    assert reconciled.json()["resolved_by"] == "test-operator"
    assert "claim_token" not in json.dumps(reconciled.json())
    conflict = client.post(
        f"{checkpoint_path}/reconcile",
        json={**reconciliation_payload, "resolution_summary": "different content"},
        headers=operator_headers,
    )
    assert conflict.status_code == 409

    reclaimed = _claim_retry_task(client)
    retry_begin = client.post(
        f"{checkpoint_path}/begin",
        json={
            **_lease_payload(reclaimed),
            "attempt_id": "98826786-af7c-4b75-9d4c-14f9c45e20f4",
            "operation_fingerprint": operation["operation_fingerprint"],
        },
    )
    assert retry_begin.status_code == 200
    assert retry_begin.json()["decision"] == "execute"
    second_attempt = client.post(
        f"{checkpoint_path}/reconcile", json=reconciliation_payload, headers=operator_headers
    )
    assert second_attempt.status_code == 200
    assert client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/release",
        json={**_lease_payload(reclaimed), "status": "pending"},
    ).status_code == 200
    stale_attempt = client.post(
        f"{checkpoint_path}/reconcile",
        json={
            **reconciliation_payload,
            "reconciliation_id": "e9f8b1f2-7d3f-4ae1-97f1-9999d0010002",
        },
        headers=operator_headers,
    )
    assert stale_attempt.status_code == 409


def test_retry_task_execution_result_is_owned_and_idempotent(client: TestClient) -> None:
    retry_task = _create_retry_task(client)
    claimed = _claim_retry_task(client)
    result_payload = {
        **_lease_payload(claimed),
        "retry_execution_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
        "retry_execution_status": "succeeded",
        "last_retry_execution_code": "MT-EXEC-20260707-000002",
        "result_summary": "Browser use 重新定位 layer_8 后已完成商品主图替换并保存项目。",
        "screenshot_asset_code": "AG-IMG-20260707-000199",
    }

    blocked_response = client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/execution-results",
        json=result_payload,
    )
    assert blocked_response.status_code == 409

    operation_plan = client.get(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/browser-use-operations"
    ).json()
    for index, operation in enumerate(operation_plan["operations"], start=1):
        attempt_id = f"aaaaaaaa-0000-4000-8000-{index:012d}"
        completion_id = f"bbbbbbbb-0000-4000-8000-{index:012d}"
        checkpoint_path = (
            f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}"
            f"/operations/{operation['operation_key']}"
        )
        begin_payload = {
            **_lease_payload(claimed),
            "attempt_id": attempt_id,
            "operation_fingerprint": operation["operation_fingerprint"],
        }
        assert client.post(f"{checkpoint_path}/begin", json=begin_payload).status_code == 200
        assert client.post(
            f"{checkpoint_path}/complete",
            json={
                **begin_payload,
                "completion_id": completion_id,
                "evidence": {"verified": True, "operation_key": operation["operation_key"]},
            },
        ).status_code == 200

    callback_response = client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/execution-results",
        json=result_payload,
    )
    duplicate_response = client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/execution-results",
        json=result_payload,
    )

    assert callback_response.status_code == 200
    assert duplicate_response.status_code == 200
    updated = duplicate_response.json()
    assert updated["retry_task_code"] == retry_task["retry_task_code"]
    assert updated["status"] == "succeeded"
    assert updated["retry_attempt_count"] == 1
    assert updated["last_retry_execution_id"] == result_payload["retry_execution_id"]
    assert updated["last_retry_execution_code"] == "MT-EXEC-20260707-000002"
    assert updated["result_summary"].startswith("Browser use 重新定位")
    assert updated["screenshot_asset_code"] == "AG-IMG-20260707-000199"
    assert updated["claimed_by"] is None


def test_recoverable_release_execution_result_is_idempotent_without_consuming_attempt(client: TestClient) -> None:
    retry_task = _create_retry_task(client)
    claimed = _claim_retry_task(client)
    payload = {
        **_lease_payload(claimed),
        "retry_execution_id": "4413b514-bdf1-4319-ac39-efabc6b16f76",
        "retry_execution_status": "released",
        "result_summary": "temporary browser transport failure",
        "retry_instruction": "reclaim with a fresh lease",
    }
    path = f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/execution-results"

    first = client.post(path, json=payload)
    duplicate = client.post(path, json=payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    updated = duplicate.json()
    assert updated["status"] == "pending"
    assert updated["retry_attempt_count"] == 0
    assert updated["last_retry_execution_id"] == payload["retry_execution_id"]
    assert updated["claimed_by"] is None


def test_claim_token_is_only_returned_by_claim_endpoints(client: TestClient) -> None:
    retry_task = _create_retry_task(client)
    claimed = _claim_retry_task(client)
    assert claimed["claim_token"]

    get_response = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}")
    list_response = client.get("/api/maitu/retry-tasks")

    assert get_response.status_code == 200
    assert "claim_token" not in get_response.json()
    assert all("claim_token" not in item for item in list_response.json())


def test_retry_execution_result_rejects_claim_token_in_durable_text(client: TestClient) -> None:
    retry_task = _create_retry_task(client)
    claimed = _claim_retry_task(client)
    response = client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/execution-results",
        json={
            **_lease_payload(claimed),
            "retry_execution_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
            "retry_execution_status": "released",
            "result_summary": f"unsafe {claimed['claim_token']} value",
        },
    )

    assert response.status_code == 422
    task = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}").json()
    assert task["status"] == "in_progress"
    assert task["last_retry_execution_id"] is None


def test_retry_execution_id_reuse_with_different_payload_returns_conflict(client: TestClient) -> None:
    retry_task = _create_retry_task(client)
    claimed = _claim_retry_task(client)
    path = f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/execution-results"
    payload = {
        **_lease_payload(claimed),
        "retry_execution_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
        "retry_execution_status": "released",
        "result_summary": "done",
    }

    assert client.post(path, json=payload).status_code == 200
    conflict_response = client.post(path, json={**payload, "result_summary": "different result"})

    assert conflict_response.status_code == 409
    assert "idempotency" in conflict_response.json()["detail"].lower()


def test_retry_heartbeat_requires_current_unexpired_lease(
    client: TestClient,
    repository: FakeMaituMaterialSlotRepository,
) -> None:
    retry_task = _create_retry_task(client)
    claimed = _claim_retry_task(client)
    path = f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/heartbeat"

    heartbeat_response = client.post(path, json={**_lease_payload(claimed), "lock_ttl_seconds": 120})
    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json()["claim_expires_at"] == "2026-07-07T09:30:00Z"

    repository.retry_tasks[retry_task["retry_task_code"]]["lease_expired"] = True
    expired_response = client.post(path, json={**_lease_payload(claimed), "lock_ttl_seconds": 120})

    assert expired_response.status_code == 409
    assert "lease" in expired_response.json()["detail"].lower()


@pytest.mark.parametrize(
    ("suffix", "payload"),
    [
        ("heartbeat", {"lock_ttl_seconds": 120}),
        ("release", {"status": "pending"}),
        (
            "execution-results",
            {
                "retry_execution_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
                "retry_execution_status": "succeeded",
            },
        ),
    ],
)
def test_retry_mutations_reject_missing_lease_identity(
    client: TestClient,
    suffix: str,
    payload: dict[str, Any],
) -> None:
    retry_task = _create_retry_task(client)
    response = client.post(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}/{suffix}",
        json=payload,
    )

    assert response.status_code == 422
    unchanged = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}").json()
    assert unchanged["status"] == "pending"
    assert unchanged["retry_attempt_count"] == 0


def test_retry_queue_lists_only_pending_retryable_tasks_with_context(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "待重试队列方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    execution_response = client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    execution_code = execution_response.json()["execution_code"]

    queue_response = client.get(
        "/api/maitu/retry-queue",
        params={
            "failure_type": "missing_layer",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "max_attempts": 3,
        },
    )

    assert queue_response.status_code == 200
    queue = queue_response.json()
    assert len(queue) == 1
    item = queue[0]
    assert item["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert item["execution_code"] == execution_code
    assert item["status"] == "pending"
    assert item["retryable"] is True
    assert item["failure_type"] == "missing_layer"
    assert item["maitu_project_code"] == "MT-PROJ-20260707-000001"
    assert item["scene_name"] == "京东空白直播间"
    assert item["slot_name"] == "商品主图"
    assert item["layer_name"] == "layer_8"
    assert item["next_operation_type"] == "retry_replace_layer_asset"
    assert item["browser_use_operations_url"].endswith("/browser-use-operations")

    claim_response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={"claimed_by": "worker-1", "lock_ttl_seconds": 120, "max_attempts": 3},
    )
    assert claim_response.status_code == 200
    empty_queue_response = client.get("/api/maitu/retry-queue", params={"max_attempts": 3})
    assert empty_queue_response.status_code == 200
    assert empty_queue_response.json() == []


def test_retry_queue_claim_next_locks_task_and_release_unlocks_it(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "待领取重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )

    claim_response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={
            "claimed_by": "browser-use-worker-1",
            "lock_ttl_seconds": 900,
            "failure_type": "missing_layer",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "max_attempts": 3,
        },
    )

    assert claim_response.status_code == 200
    claimed = claim_response.json()
    assert claimed["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert claimed["status"] == "in_progress"
    assert claimed["claimed_by"] == "browser-use-worker-1"
    assert claimed["claimed_at"] is not None
    assert claimed["claim_expires_at"] is not None
    assert claimed["claim_token"]
    assert claimed["lease_version"] == 1
    assert claimed["next_operation_type"] == "retry_replace_layer_asset"

    queue_after_claim = client.get("/api/maitu/retry-queue")
    assert queue_after_claim.status_code == 200
    assert queue_after_claim.json() == []

    release_response = client.post(
        f"/api/maitu/retry-tasks/{claimed['retry_task_code']}/release",
        json={
            **_lease_payload(claimed),
            "status": "pending",
            "result_summary": "worker heartbeat lost; release back to queue",
        },
    )
    assert release_response.status_code == 200
    released = release_response.json()
    assert released["status"] == "pending"
    assert released["claimed_by"] is None
    assert released["claimed_at"] is None
    assert released["claim_expires_at"] is None
    assert released["lease_version"] == 1
    assert released["result_summary"] == "worker heartbeat lost; release back to queue"

    reclaimed = _claim_retry_task(client)
    assert reclaimed["lease_version"] == 2
    assert reclaimed["claim_token"] != claimed["claim_token"]
    stale_release = client.post(
        f"/api/maitu/retry-tasks/{claimed['retry_task_code']}/release",
        json={**_lease_payload(claimed), "status": "pending"},
    )
    assert stale_release.status_code == 409


def test_retry_queue_reclaim_expired_unlocks_in_progress_tasks(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "过期领取重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )
    claim_response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={"claimed_by": "browser-use-worker-1", "lock_ttl_seconds": 900, "max_attempts": 3},
    )
    retry_task_code = claim_response.json()["retry_task_code"]

    reclaim_response = client.post("/api/maitu/retry-queue/reclaim-expired")

    assert reclaim_response.status_code == 200
    payload = reclaim_response.json()
    assert payload["reclaimed_count"] == 1
    assert payload["retry_task_codes"] == [retry_task_code]

    task_response = client.get(f"/api/maitu/retry-tasks/{retry_task_code}")
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["status"] == "pending"
    assert task["claimed_by"] is None
    assert task["claimed_at"] is None
    assert task["claim_expires_at"] is None


def test_retry_worker_next_reclaims_claims_and_returns_operation_plan(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品主图",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "layer_8",
            "required_category": "product_image",
            "accepted_asset_types": ["IMG"],
        },
    )
    slot_code = slot_response.json()["slot_code"]
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={
            "plan_name": "worker next 重试方案",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "slot_codes": [slot_code],
        },
    )
    client.post(
        f"/api/maitu/replacement-plans/{plan_response.json()['plan_code']}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "partial_failed",
            "operation_results": [
                {
                    "slot_code": slot_code,
                    "operation_type": "replace_layer_asset",
                    "asset_code": "AG-IMG-20260707-000001",
                    "status": "failed",
                    "failure_type": "missing_layer",
                    "retryable": True,
                    "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
                    "error_message": "Browser use 未找到 layer_8。",
                }
            ],
        },
    )

    response = client.post(
        "/api/maitu/retry-worker/next",
        json={
            "claimed_by": "browser-use-worker-1",
            "lock_ttl_seconds": 900,
            "failure_type": "missing_layer",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "max_attempts": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reclaimed_count"] == 0
    assert payload["reclaimed_retry_task_codes"] == []
    assert payload["retry_task"]["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert payload["retry_task"]["status"] == "in_progress"
    assert payload["retry_task"]["claimed_by"] == "browser-use-worker-1"
    assert payload["retry_task"]["claim_token"]
    assert payload["retry_task"]["lease_version"] == 1
    assert payload["operation_plan"]["retry_task_code"] == "MT-RETRY-20260707-000001"
    assert payload["operation_plan"]["operations"][0]["operation_type"] == "retry_replace_layer_asset"
    assert "只重试槽位" in payload["operation_plan"]["operations"][0]["instruction"]


@pytest.mark.parametrize("path", ["/api/maitu/retry-worker/next"])
def test_retry_worker_next_returns_404_when_no_task_available(client: TestClient, path: str) -> None:
    response = client.post(path, json={"claimed_by": "browser-use-worker-1"})

    assert response.status_code == 404


def test_release_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/retry-tasks/MT-RETRY-20260707-999999/release",
        json={
            "status": "pending",
            "claimed_by": "worker-1",
            "claim_token": "c1a1d000-0000-4000-8000-000000000001",
            "lease_version": 1,
        },
    )

    assert response.status_code == 404


def test_create_execution_result_for_missing_plan_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/replacement-plans/MT-PLAN-20260707-999999/execution-results",
        json={"execution_status": "failed", "error_message": "plan not found"},
    )

    assert response.status_code == 404


def test_get_missing_execution_result_returns_404(client: TestClient) -> None:
    slot_response = client.post(
        "/api/maitu/slots",
        json={"slot_name": "商品主图", "required_category": "product_image", "accepted_asset_types": ["IMG"]},
    )
    plan_response = client.post(
        "/api/maitu/replacement-plans",
        json={"plan_name": "测试方案", "slot_codes": [slot_response.json()["slot_code"]]},
    )
    plan_code = plan_response.json()["plan_code"]

    response = client.get(f"/api/maitu/replacement-plans/{plan_code}/execution-results/MT-EXEC-20260707-999999")

    assert response.status_code == 404


def test_list_execution_results_for_missing_plan_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/replacement-plans/MT-PLAN-20260707-999999/execution-results")

    assert response.status_code == 404


def test_get_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/retry-tasks/MT-RETRY-20260707-999999")

    assert response.status_code == 404


def test_retry_task_patch_rejects_lease_owned_state_fields(client: TestClient) -> None:
    retry_task = _create_retry_task(client)

    response = client.patch(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}",
        json={"status": "succeeded", "retry_attempt_count": 99},
    )

    assert response.status_code == 422
    unchanged = client.get(f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}").json()
    assert unchanged["status"] == "pending"
    assert unchanged["retry_attempt_count"] == 0


def test_retry_task_patch_rejects_metadata_change_while_claimed(client: TestClient) -> None:
    retry_task = _create_retry_task(client)
    claim_response = client.post(
        "/api/maitu/retry-queue/claim-next",
        json={"claimed_by": "worker-1", "lock_ttl_seconds": 120},
    )
    assert claim_response.status_code == 200

    response = client.patch(
        f"/api/maitu/retry-tasks/{retry_task['retry_task_code']}",
        json={"result_summary": "manual note"},
    )

    assert response.status_code == 409
    assert "lease" in response.json()["detail"].lower()


def test_update_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/api/maitu/retry-tasks/MT-RETRY-20260707-999999",
        json={"result_summary": "manual note"},
    )

    assert response.status_code == 404


def test_get_browser_use_operations_for_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/retry-tasks/MT-RETRY-20260707-999999/browser-use-operations")

    assert response.status_code == 404


def test_create_execution_result_for_missing_retry_task_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/retry-tasks/MT-RETRY-20260707-999999/execution-results",
        json={
            "retry_execution_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
            "retry_execution_status": "failed",
            "claimed_by": "worker-1",
            "claim_token": "c1a1d000-0000-4000-8000-000000000001",
            "lease_version": 1,
            "error_message": "retry task not found",
        },
    )

    assert response.status_code == 404


def test_get_missing_replacement_plan_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/replacement-plans/MT-PLAN-20260707-999999")

    assert response.status_code == 404


def test_get_browser_use_operations_for_missing_plan_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/replacement-plans/MT-PLAN-20260707-999999/browser-use-operations")

    assert response.status_code == 404


def test_candidate_assets_for_missing_slot_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/slots/MT-SLOT-20260707-999999/candidate-assets")

    assert response.status_code == 404


def test_import_reference_live_room_blueprint_and_get_it(client: TestClient) -> None:
    payload = {
        "reference_profile": {
            "profile_code": "MT-REF-20260709-39826",
            "source": "browser_use_observe",
            "source_url": "https://live2.maituai.com/LiveRoom?liveRoomId=39826",
            "reference_room_id": "39826",
            "reference_room_name": "京东空白直播间-0707-1352",
            "platform": "京东",
            "active_scene_name": "场景01",
            "scenes": [
                {"scene_name": "场景01", "scene_type": "讲品", "status": "已激活", "active": True, "sort_order": 1},
                {"scene_name": "场景02", "scene_type": "讲品", "status": "已激活", "active": False, "sort_order": 2},
            ],
            "active_scene_layers": [
                {
                    "layer_name": "微信图片_20260618221607_11_15",
                    "layer_role": "background",
                    "required_category": "background_image",
                    "accepted_asset_types": ["IMG"],
                    "replacement_policy": "keep_layout",
                    "sort_order": 1,
                }
            ],
            "script_texts": ["大家好，今天给大家介绍张裕解百纳品酒大师系列。"],
        },
        "blueprint": {
            "blueprint_code": "MT-BP-20260709-39826",
            "reference_profile_code": "MT-REF-20260709-39826",
            "title": "京东空白直播间-0707-1352 重建蓝图",
            "platform": "京东",
            "room_type": "reference_rebuild",
            "reference_room_id": "39826",
            "reference_room_name": "京东空白直播间-0707-1352",
            "status": "draft",
            "description": "由 Browser-use Observe 现场状态自动抽取的 LiveRoomBlueprint 初稿。",
            "scenes": [
                {
                    "scene_code": "MT-SCENE-20260709-000001",
                    "scene_name": "场景01",
                    "scene_type": "讲品",
                    "status": "已激活",
                    "sort_order": 1,
                    "goal": "第1段产品讲解",
                    "reference_active": True,
                    "layers": [
                        {
                            "layer_code": "MT-LAYER-20260709-000001",
                            "layer_name": "微信图片_20260618221607_11_15",
                            "layer_role": "background",
                            "required_category": "background_image",
                            "accepted_asset_types": ["IMG"],
                            "replacement_policy": "keep_layout",
                        }
                    ],
                }
            ],
            "script_blocks": [
                {
                    "script_block_code": "MT-SCRIPT-BLOCK-20260709-000001",
                    "scene_name": "场景01",
                    "sort_order": 1,
                    "content": "大家好，今天给大家介绍张裕解百纳品酒大师系列。",
                    "source": "reference_room_profile",
                }
            ],
            "safety_rules": ["默认不点击正式开播", "真实执行前必须通过 Browser-use preflight"],
        },
    }

    create_response = client.post("/api/maitu/live-room-blueprints/import-reference", json=payload)

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["blueprint_code"] == "MT-BP-20260709-39826"
    assert created["reference_profile_code"] == "MT-REF-20260709-39826"
    assert created["reference_room_id"] == "39826"
    assert created["room_type"] == "reference_rebuild"
    assert created["status"] == "draft"
    assert created["scenes"][0]["layers"][0]["required_category"] == "background_image"
    assert created["script_blocks"][0]["scene_name"] == "场景01"
    assert created["reference_profile"]["active_scene_name"] == "场景01"

    list_response = client.get(
        "/api/maitu/live-room-blueprints",
        params={"reference_room_id": "39826", "status": "draft"},
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["blueprint_code"] == "MT-BP-20260709-39826"

    get_response = client.get("/api/maitu/live-room-blueprints/MT-BP-20260709-39826")
    assert get_response.status_code == 200
    assert get_response.json()["reference_room_name"] == "京东空白直播间-0707-1352"


def test_get_missing_live_room_blueprint_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/live-room-blueprints/MT-BP-20260709-999999")

    assert response.status_code == 404


def test_list_live_room_blueprints_can_search_by_script_text(client: TestClient) -> None:
    first_payload = {
        "reference_profile": {
            "profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "source": "maitu_template_library_readonly_observe",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "platform": "京东",
        },
        "blueprint": {
            "blueprint_code": "MT-BP-20260709-38336-TEMPLATE",
            "reference_profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "title": "张裕夏日主题 模板库基准蓝图",
            "platform": "京东",
            "room_type": "template_library_baseline",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "status": "template_baseline",
            "scenes": [],
            "script_blocks": [
                {
                    "script_block_code": "MT-TPL-SCRIPT-38336-001",
                    "scene_name": "商品01-场景01",
                    "sort_order": 1,
                    "content": "龙谕的葡萄园，在宁夏贺兰山东麓。那里有父亲山贺兰山，也有母亲河黄河。",
                }
            ],
        },
    }
    second_payload = {
        "reference_profile": {
            "profile_code": "MT-REF-20260709-39826",
            "source": "browser_use_observe",
            "reference_room_id": "39826",
            "reference_room_name": "京东空白直播间-0707-1352",
            "platform": "京东",
        },
        "blueprint": {
            "blueprint_code": "MT-BP-20260709-39826",
            "reference_profile_code": "MT-REF-20260709-39826",
            "title": "京东空白直播间-0707-1352 重建蓝图",
            "platform": "京东",
            "room_type": "reference_rebuild",
            "reference_room_id": "39826",
            "reference_room_name": "京东空白直播间-0707-1352",
            "status": "draft",
            "scenes": [],
            "script_blocks": [
                {
                    "script_block_code": "MT-SCRIPT-BLOCK-20260709-000001",
                    "scene_name": "场景01",
                    "sort_order": 1,
                    "content": "大家好，今天给大家介绍张裕解百纳品酒大师系列。",
                }
            ],
        },
    }
    assert client.post("/api/maitu/live-room-blueprints/import-reference", json=first_payload).status_code == 201
    assert client.post("/api/maitu/live-room-blueprints/import-reference", json=second_payload).status_code == 201

    response = client.get("/api/maitu/live-room-blueprints", params={"q": "贺兰山东麓"})

    assert response.status_code == 200
    rows = response.json()
    assert [row["blueprint_code"] for row in rows] == ["MT-BP-20260709-38336-TEMPLATE"]
    assert rows[0]["reference_room_id"] == "38336"
    assert rows[0]["script_blocks"][0]["content"].startswith("龙谕的葡萄园")


def test_search_scene_components_by_script_returns_only_matched_scene_components(client: TestClient) -> None:
    payload = {
        "reference_profile": {
            "profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "source": "maitu_template_library_readonly_observe",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "platform": "京东",
        },
        "blueprint": {
            "blueprint_code": "MT-BP-20260709-38336-TEMPLATE",
            "reference_profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "title": "张裕夏日主题 模板库基准蓝图",
            "platform": "京东",
            "room_type": "template_library_baseline",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "status": "template_baseline",
            "scenes": [
                {
                    "scene_code": "MT-TPL-SCENE-38336-001",
                    "scene_name": "商品01-场景01",
                    "scene_type": "讲品",
                    "reference_product_name": "龙谕 龙8 干红葡萄酒 750ml*4瓶 整箱装",
                    "reference_item_id": "100029295221",
                    "reference_clip_id": "390051",
                    "layers": [
                        {
                            "layer_code": "MT-TPL-LAYER-38336-001-01",
                            "layer_name": "微信图片_20260618221607_11_15",
                            "layer_role": "background",
                            "required_category": "background_image",
                            "accepted_asset_types": ["IMG"],
                            "material_tab": "背景",
                            "source_material_type": "image",
                            "material_id": 40131,
                            "left_position": 0,
                            "top_position": 0,
                            "width": 1080,
                            "height": 1919,
                            "z_index": 1,
                            "replacement_policy": "keep_layout",
                        },
                        {
                            "layer_code": "MT-TPL-LAYER-38336-001-02",
                            "layer_name": "张裕定制形象260519",
                            "layer_role": "digital_human",
                            "required_category": "digital_human_video",
                            "accepted_asset_types": ["IMG", "VID"],
                            "material_tab": "数字分身",
                            "source_material_type": "digital_human",
                            "material_id": 37200,
                            "left_position": 106,
                            "top_position": 464,
                            "width": 856,
                            "height": 1540,
                            "z_index": 3,
                            "speaker_id": 3760,
                            "digital_human_image_id": 7717,
                            "replacement_policy": "keep_layout",
                        },
                    ],
                },
                {
                    "scene_code": "MT-TPL-SCENE-38336-002",
                    "scene_name": "商品01-场景02",
                    "scene_type": "特写",
                    "layers": [
                        {
                            "layer_code": "MT-TPL-LAYER-38336-002-01",
                            "layer_name": "不应返回的特写视频",
                            "layer_role": "product_video",
                            "required_category": "product_video",
                            "accepted_asset_types": ["VID"],
                            "source_material_type": "decorative_video",
                            "material_id": 37318,
                            "left_position": 0,
                            "top_position": 0,
                            "width": 1086,
                            "height": 1926,
                        }
                    ],
                },
            ],
            "script_blocks": [
                {
                    "script_block_code": "MT-TPL-SCRIPT-38336-001",
                    "scene_name": "商品01-场景01",
                    "sort_order": 1,
                    "content": "龙谕的葡萄园，在宁夏贺兰山东麓。那里有父亲山贺兰山，也有母亲河黄河。",
                },
                {
                    "script_block_code": "MT-TPL-SCRIPT-38336-002",
                    "scene_name": "商品01-场景02",
                    "sort_order": 2,
                    "content": "这是一段商品细节特写，不包含查询关键词。",
                },
            ],
            "template_library_code": "MT-TEMPLATE-38336-ZHANGYU-SUMMER",
        },
    }
    assert client.post("/api/maitu/live-room-blueprints/import-reference", json=payload).status_code == 201

    response = client.get(
        "/api/maitu/live-room-blueprints/scene-components/by-script",
        params={"q": "贺兰山东麓"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    result = rows[0]
    assert result["component_index_source"] == "template_component_index"
    assert result["blueprint_code"] == "MT-BP-20260709-38336-TEMPLATE"
    assert result["matched_scene_names"] == ["商品01-场景01"]
    assert result["scene_count"] == 1
    assert result["script_block_count"] == 1
    assert result["unique_component_count"] == 2
    assert result["component_placement_count"] == 2
    component_names = {component["component_name"] for component in result["components"]}
    assert component_names == {"微信图片_20260618221607_11_15", "张裕定制形象260519"}
    assert "不应返回的特写视频" not in component_names
    digital_human = next(component for component in result["components"] if component["component_role"] == "digital_human")
    assert digital_human["material_id"] == 37200
    assert digital_human["geometry_examples"][0]["left"] == 106
    background_placement = next(
        placement for placement in result["component_placements"] if placement["layer_role"] == "background"
    )
    assert background_placement["scene_template_code"] == "MT-TPL-SCENE-38336-001"
    assert background_placement["component_template_code"] == "MT-TPL-LAYER-38336-001-01"


def test_template_scene_component_index_can_be_queried_as_first_class_resources(client: TestClient) -> None:
    payload = {
        "reference_profile": {
            "profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "source": "maitu_template_library_readonly_observe",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "platform": "京东",
        },
        "blueprint": {
            "blueprint_code": "MT-BP-20260709-38336-TEMPLATE",
            "reference_profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "title": "张裕夏日主题 模板库基准蓝图",
            "platform": "京东",
            "room_type": "template_library_baseline",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "status": "template_baseline",
            "template_library_code": "MT-TEMPLATE-38336-ZHANGYU-SUMMER",
            "scenes": [
                {
                    "scene_code": "MT-TPL-SCENE-38336-001",
                    "scene_name": "商品01-场景01",
                    "scene_type": "讲品",
                    "sort_order": 1,
                    "reference_product_name": "龙谕 龙8 干红葡萄酒 750ml*4瓶 整箱装",
                    "reference_item_id": "100029295221",
                    "reference_clip_id": "390051",
                    "layers": [
                        {
                            "layer_code": "MT-TPL-LAYER-38336-001-01",
                            "layer_name": "微信图片_20260618221607_11_15",
                            "layer_role": "background",
                            "required_category": "background_image",
                            "accepted_asset_types": ["IMG"],
                            "material_tab": "背景",
                            "source_material_type": "image",
                            "material_id": 40131,
                            "left_position": 0,
                            "top_position": 0,
                            "width": 1080,
                            "height": 1919,
                            "z_index": 1,
                            "replacement_policy": "keep_layout",
                        },
                        {
                            "layer_code": "MT-TPL-LAYER-38336-001-02",
                            "layer_name": "张裕定制形象260519",
                            "layer_role": "digital_human",
                            "required_category": "digital_human_video",
                            "accepted_asset_types": ["IMG", "VID"],
                            "material_tab": "数字分身",
                            "source_material_type": "digital_human",
                            "material_id": 37200,
                            "left_position": 106,
                            "top_position": 464,
                            "width": 856,
                            "height": 1540,
                            "z_index": 3,
                            "speaker_id": 3760,
                            "digital_human_image_id": 7717,
                            "replacement_policy": "keep_layout",
                        },
                    ],
                }
            ],
            "script_blocks": [
                {
                    "script_block_code": "MT-TPL-SCRIPT-38336-001",
                    "scene_name": "商品01-场景01",
                    "sort_order": 1,
                    "content": "龙谕的葡萄园，在宁夏贺兰山东麓。那里有父亲山贺兰山，也有母亲河黄河。",
                }
            ],
        },
    }
    assert client.post("/api/maitu/live-room-blueprints/import-reference", json=payload).status_code == 201

    scenes_response = client.get(
        "/api/maitu/live-room-template-scenes",
        params={"reference_room_id": "38336", "q": "贺兰山东麓"},
    )

    assert scenes_response.status_code == 200
    scenes = scenes_response.json()
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene["scene_template_code"] == "MT-TPL-SCENE-38336-001"
    assert scene["template_library_code"] == "MT-TEMPLATE-38336-ZHANGYU-SUMMER"
    assert scene["scene_name"] == "商品01-场景01"
    assert scene["script_block_code"] == "MT-TPL-SCRIPT-38336-001"
    assert scene["script_content"].startswith("龙谕的葡萄园")
    assert scene["component_count"] == 2

    components_response = client.get(
        "/api/maitu/live-room-template-scenes/MT-TPL-SCENE-38336-001/components"
    )

    assert components_response.status_code == 200
    components = components_response.json()
    assert [component["component_template_code"] for component in components] == [
        "MT-TPL-LAYER-38336-001-01",
        "MT-TPL-LAYER-38336-001-02",
    ]
    assert components[0]["component_role"] == "background"
    assert components[0]["geometry"] == {"left": 0, "top": 0, "width": 1080, "height": 1919, "scale": None}
    assert components[1]["speaker_id"] == 3760


def test_create_single_scene_build_plan_from_script_uses_template_component_index(client: TestClient) -> None:
    payload = {
        "reference_profile": {
            "profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "source": "maitu_template_library_readonly_observe",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "platform": "京东",
        },
        "blueprint": {
            "blueprint_code": "MT-BP-20260709-38336-TEMPLATE",
            "reference_profile_code": "MT-REF-20260709-38336-TEMPLATE",
            "title": "张裕夏日主题 模板库基准蓝图",
            "platform": "京东",
            "room_type": "template_library_baseline",
            "reference_room_id": "38336",
            "reference_room_name": "张裕夏日主题",
            "status": "template_baseline",
            "template_library_code": "MT-TEMPLATE-38336-ZHANGYU-SUMMER",
            "scenes": [
                {
                    "scene_code": "MT-TPL-SCENE-38336-001",
                    "scene_name": "商品01-场景01",
                    "scene_type": "讲品",
                    "sort_order": 1,
                    "reference_product_name": "龙谕 龙8 干红葡萄酒 750ml*4瓶 整箱装",
                    "reference_item_id": "100029295221",
                    "reference_clip_id": "390051",
                    "layers": [
                        {
                            "layer_code": "MT-TPL-LAYER-38336-001-01",
                            "layer_name": "微信图片_20260618221607_11_15",
                            "layer_role": "background",
                            "required_category": "background_image",
                            "accepted_asset_types": ["IMG"],
                            "material_tab": "背景",
                            "source_material_type": "image",
                            "material_id": 40131,
                            "left_position": 0,
                            "top_position": 0,
                            "width": 1080,
                            "height": 1919,
                            "z_index": 1,
                            "replacement_policy": "keep_layout",
                        },
                        {
                            "layer_code": "MT-TPL-LAYER-38336-001-02",
                            "layer_name": "张裕定制形象260519",
                            "layer_role": "digital_human",
                            "required_category": "digital_human_video",
                            "accepted_asset_types": ["IMG", "VID"],
                            "material_tab": "数字分身",
                            "source_material_type": "digital_human",
                            "material_id": 37200,
                            "left_position": 106,
                            "top_position": 464,
                            "width": 856,
                            "height": 1540,
                            "z_index": 3,
                            "speaker_id": 3760,
                            "digital_human_image_id": 7717,
                            "replacement_policy": "keep_layout",
                        },
                    ],
                },
                {
                    "scene_code": "MT-TPL-SCENE-38336-002",
                    "scene_name": "商品01-场景02",
                    "scene_type": "特写",
                    "layers": [
                        {
                            "layer_code": "MT-TPL-LAYER-38336-002-01",
                            "layer_name": "不应进入计划的特写视频",
                            "layer_role": "product_video",
                            "required_category": "product_video",
                            "accepted_asset_types": ["VID"],
                            "source_material_type": "decorative_video",
                            "material_id": 37318,
                        }
                    ],
                },
            ],
            "script_blocks": [
                {
                    "script_block_code": "MT-TPL-SCRIPT-38336-001",
                    "scene_name": "商品01-场景01",
                    "sort_order": 1,
                    "content": "龙谕的葡萄园，在宁夏贺兰山东麓。那里有父亲山贺兰山，也有母亲河黄河。",
                },
                {
                    "script_block_code": "MT-TPL-SCRIPT-38336-002",
                    "scene_name": "商品01-场景02",
                    "sort_order": 2,
                    "content": "这是一段商品细节特写，不包含查询关键词。",
                },
            ],
        },
    }
    assert client.post("/api/maitu/live-room-blueprints/import-reference", json=payload).status_code == 201

    create_response = client.post(
        "/api/maitu/live-room-scene-build-plans",
        json={
            "reference_room_id": "38336",
            "script_query": "龙谕的葡萄园，在宁夏贺兰山东麓",
            "target_script_content": "今天我们用张裕夏日主题的结构讲龙谕龙8，突出贺兰山东麓风土。",
            "target_live_room_id": "40173",
            "plan_name": "龙谕龙8 单场景复刻 dry-run",
        },
    )

    assert create_response.status_code == 201
    plan = create_response.json()
    assert plan["build_plan_code"] == "MT-BUILD-20260709-000001"
    assert plan["blueprint_code"] == "MT-BP-20260709-38336-TEMPLATE"
    assert plan["strategy"] == "template_scene_dry_run"
    operation_types = [operation["operation_type"] for operation in plan["operations"]]
    assert operation_types == [
        "preflight_scene_build_plan",
        "create_scene_from_template",
        "insert_template_component",
        "insert_template_component",
        "add_script_block",
        "save_live_room",
    ]
    assert plan["operations"][0]["details"]["target_live_room_id"] == "40173"
    assert all(operation.get("scene_name") in {None, "商品01-场景01"} for operation in plan["operations"])
    assert "不应进入计划的特写视频" not in json.dumps(plan["operations"], ensure_ascii=False)
    background_operation = next(
        operation for operation in plan["operations"] if operation.get("layer_role") == "background"
    )
    assert background_operation["layer_name"] == "微信图片_20260618221607_11_15"
    assert background_operation["details"]["scene_template_code"] == "MT-TPL-SCENE-38336-001"
    assert background_operation["details"]["component_template_code"] == "MT-TPL-LAYER-38336-001-01"
    assert background_operation["details"]["geometry"] == {"left": 0, "top": 0, "width": 1080, "height": 1919, "scale": None}
    script_operation = next(operation for operation in plan["operations"] if operation["operation_type"] == "add_script_block")
    assert script_operation["script_block_code"] == "MT-TPL-SCRIPT-38336-001"
    assert script_operation["script_block_content"] == "今天我们用张裕夏日主题的结构讲龙谕龙8，突出贺兰山东麓风土。"
    assert script_operation["details"]["source_template_script_content"].startswith("龙谕的葡萄园")

    operations_response = client.get(
        "/api/maitu/live-room-build-plans/MT-BUILD-20260709-000001/browser-use-operations"
    )
    assert operations_response.status_code == 200
    operation_plan = operations_response.json()
    assert operation_plan["target_live_room_id"] == "40173"
    operations = operation_plan["operations"]
    assert operations[1]["details"]["scene_template_code"] == "MT-TPL-SCENE-38336-001"
    assert operations[-1]["status"] == "manual_review"



def test_create_live_room_build_plan_from_blueprint_and_get_browser_use_operations(client: TestClient) -> None:
    import_response = client.post(
        "/api/maitu/live-room-blueprints/import-reference",
        json={
            "reference_profile": {
                "profile_code": "MT-REF-20260709-39826",
                "source": "browser_use_observe",
                "reference_room_id": "39826",
                "reference_room_name": "京东空白直播间-0707-1352",
                "platform": "京东",
                "active_scene_name": "场景01",
            },
            "blueprint": {
                "blueprint_code": "MT-BP-20260709-39826",
                "reference_profile_code": "MT-REF-20260709-39826",
                "title": "京东空白直播间-0707-1352 重建蓝图",
                "platform": "京东",
                "room_type": "reference_rebuild",
                "reference_room_id": "39826",
                "reference_room_name": "京东空白直播间-0707-1352",
                "status": "draft",
                "scenes": [
                    {
                        "scene_code": "MT-SCENE-20260709-000001",
                        "scene_name": "场景01",
                        "scene_type": "讲品",
                        "sort_order": 1,
                        "reference_active": True,
                        "layers": [
                            {
                                "layer_code": "MT-LAYER-20260709-000001",
                                "layer_name": "微信图片_20260618221607_11_15",
                                "layer_role": "background",
                                "required_category": "background_image",
                                "accepted_asset_types": ["IMG"],
                                "replacement_policy": "keep_layout",
                            }
                        ],
                    }
                ],
                "script_blocks": [
                    {
                        "script_block_code": "MT-SCRIPT-BLOCK-20260709-000001",
                        "scene_name": "场景01",
                        "sort_order": 1,
                        "content": "大家好，今天给大家介绍张裕解百纳品酒大师系列。",
                    }
                ],
                "safety_rules": ["默认不点击正式开播", "真实执行前必须通过 Browser-use preflight"],
            },
        },
    )
    assert import_response.status_code == 201

    create_response = client.post(
        "/api/maitu/live-room-build-plans",
        json={
            "blueprint_code": "MT-BP-20260709-39826",
            "plan_name": "39826 参考直播间 BuildPlan dry-run",
            "strategy": "reference_rebuild_dry_run",
        },
    )

    assert create_response.status_code == 201
    plan = create_response.json()
    assert plan["build_plan_code"] == "MT-BUILD-20260709-000001"
    assert plan["blueprint_code"] == "MT-BP-20260709-39826"
    assert plan["executor"] == "browser_use"
    assert plan["target_app"] == "maitu"
    assert plan["status"] == "draft"
    operation_types = [operation["operation_type"] for operation in plan["operations"]]
    assert operation_types == [
        "preflight_build_plan",
        "select_scene",
        "replace_layer_asset",
        "add_script_block",
        "save_live_room",
    ]
    assert plan["operations"][2]["layer_name"] == "微信图片_20260618221607_11_15"
    assert plan["operations"][2]["required_category"] == "background_image"
    assert plan["operations"][2]["replacement_policy"] == "keep_layout"
    assert plan["operations"][-1]["status"] == "manual_review"
    assert all("开播" not in operation["instruction"].replace("不点击正式开播", "") for operation in plan["operations"])

    get_response = client.get("/api/maitu/live-room-build-plans/MT-BUILD-20260709-000001")
    assert get_response.status_code == 200
    assert get_response.json()["operations"][3]["script_block_code"] == "MT-SCRIPT-BLOCK-20260709-000001"

    operations_response = client.get(
        "/api/maitu/live-room-build-plans/MT-BUILD-20260709-000001/browser-use-operations"
    )
    assert operations_response.status_code == 200
    operations = operations_response.json()
    assert operations["build_plan_code"] == "MT-BUILD-20260709-000001"
    assert operations["blueprint_code"] == "MT-BP-20260709-39826"
    assert operations["reference_room_id"] == "39826"
    assert operations["reference_room_name"] == "京东空白直播间-0707-1352"
    assert operations["operations"][0]["operation_type"] == "preflight_build_plan"
    assert operations["operations"][-1]["operation_type"] == "save_live_room"


def test_create_live_room_build_plan_with_script_context_selects_assets_for_layer_operations(client: TestClient) -> None:
    import_response = client.post(
        "/api/maitu/live-room-blueprints/import-reference",
        json={
            "reference_profile": {
                "profile_code": "MT-REF-20260709-39827",
                "source": "browser_use_observe",
                "reference_room_id": "39827",
                "reference_room_name": "品酒大师PRO测试直播间",
                "platform": "京东",
                "active_scene_name": "场景01",
            },
            "blueprint": {
                "blueprint_code": "MT-BP-20260709-39827",
                "reference_profile_code": "MT-REF-20260709-39827",
                "title": "品酒大师PRO测试直播间 重建蓝图",
                "platform": "京东",
                "room_type": "reference_rebuild",
                "reference_room_id": "39827",
                "reference_room_name": "品酒大师PRO测试直播间",
                "status": "draft",
                "scenes": [
                    {
                        "scene_code": "MT-SCENE-20260709-000001",
                        "scene_name": "场景01",
                        "scene_type": "讲品",
                        "sort_order": 1,
                        "layers": [
                            {
                                "layer_code": "MT-LAYER-20260709-000009",
                                "layer_name": "商品讲解视频",
                                "layer_role": "product_video",
                                "required_category": "product_video",
                                "accepted_asset_types": ["VID"],
                                "replacement_policy": "keep_layout",
                            }
                        ],
                    }
                ],
                "script_blocks": [
                    {
                        "script_block_code": "MT-SCRIPT-BLOCK-20260709-000009",
                        "scene_name": "场景01",
                        "sort_order": 1,
                        "content": "大家好，今天给大家介绍张裕解百纳品酒大师PRO，入口柔顺，适合新手。",
                    }
                ],
                "safety_rules": ["默认不点击正式开播"],
            },
        },
    )
    assert import_response.status_code == 201

    create_response = client.post(
        "/api/maitu/live-room-build-plans",
        json={
            "blueprint_code": "MT-BP-20260709-39827",
            "plan_name": "品酒大师PRO BuildPlan script selection",
            "strategy": "script_context_best_match",
            "auto_select_assets": True,
        },
    )

    assert create_response.status_code == 201
    plan = create_response.json()
    layer_operation = next(operation for operation in plan["operations"] if operation["operation_type"] == "replace_layer_asset")
    assert layer_operation["status"] == "asset_selected"
    assert layer_operation["selected_asset_code"] == "AG-VID-20260709-000052"
    assert layer_operation["selected_asset_title"] == "视频 - 商品讲解视频 - 品酒大师PRO"
    assert layer_operation["selected_asset_display_code"] == "MT-VID-0024"
    assert layer_operation["selected_asset_local_file_code"] == "MT-VID-0024"
    assert layer_operation["match_score"] >= 0.9
    assert "script context mentions 品酒大师PRO" in layer_operation["match_reasons"]
    assert "AG-VID-20260709-000052" in layer_operation["instruction"]

    operations_response = client.get(
        f"/api/maitu/live-room-build-plans/{plan['build_plan_code']}/browser-use-operations"
    )
    assert operations_response.status_code == 200
    operation_plan = operations_response.json()
    operation = next(item for item in operation_plan["operations"] if item["operation_type"] == "replace_layer_asset")
    assert operation["selected_asset_code"] == "AG-VID-20260709-000052"
    assert operation["selected_asset_local_relative_path"] == "视频/MT-VID-0024_品酒大师PRO.mp4"


def test_script_context_build_plan_does_not_use_template_preview_as_direct_layer_asset(client: TestClient) -> None:
    import_response = client.post(
        "/api/maitu/live-room-blueprints/import-reference",
        json={
            "reference_profile": {
                "profile_code": "MT-REF-20260709-39828",
                "source": "browser_use_observe",
                "reference_room_id": "39828",
                "reference_room_name": "模板索引测试直播间",
                "platform": "京东",
                "active_scene_name": "场景01",
            },
            "blueprint": {
                "blueprint_code": "MT-BP-20260709-39828",
                "reference_profile_code": "MT-REF-20260709-39828",
                "title": "张裕618背景风格直播间",
                "platform": "京东",
                "room_type": "reference_rebuild",
                "reference_room_id": "39828",
                "reference_room_name": "模板索引测试直播间",
                "status": "draft",
                "scenes": [
                    {
                        "scene_code": "MT-SCENE-20260709-000001",
                        "scene_name": "场景01",
                        "scene_type": "讲品",
                        "layers": [
                            {
                                "layer_code": "MT-LAYER-20260709-000010",
                                "layer_name": "背景图层",
                                "layer_role": "background",
                                "required_category": "background_image",
                                "accepted_asset_types": ["IMG"],
                                "replacement_policy": "keep_layout",
                            }
                        ],
                    }
                ],
                "script_blocks": [
                    {
                        "script_block_code": "MT-SCRIPT-BLOCK-20260709-000010",
                        "scene_name": "场景01",
                        "content": "张裕618背景风格，品酒大师PRO讲解。",
                    }
                ],
                "safety_rules": ["模板只作为风格索引，不能直接插入直播间"],
            },
        },
    )
    assert import_response.status_code == 201

    create_response = client.post(
        "/api/maitu/live-room-build-plans",
        json={
            "blueprint_code": "MT-BP-20260709-39828",
            "plan_name": "模板索引不能直接选材",
            "strategy": "script_context_best_match",
            "auto_select_assets": True,
        },
    )

    assert create_response.status_code == 201
    plan = create_response.json()
    operation = next(item for item in plan["operations"] if item["operation_type"] == "replace_layer_asset")
    assert operation["selected_asset_code"] == "AG-IMG-20260709-000070"
    assert operation["selected_asset_local_file_code"] == "MT-BG-0001"
    assert operation["selection_source"] == "script_context_rule_filter"
    assert "MT-TPL" not in operation["selected_asset_local_file_code"]
    assert all("模板预览" not in reason for reason in operation["match_reasons"])


def test_create_live_room_build_plan_execution_result_and_list_evidence(client: TestClient) -> None:
    import_response = client.post(
        "/api/maitu/live-room-blueprints/import-reference",
        json={
            "reference_profile": {
                "profile_code": "MT-REF-20260709-39826",
                "source": "browser_use_observe",
                "reference_room_id": "39826",
                "reference_room_name": "京东空白直播间-0707-1352",
                "platform": "京东",
                "active_scene_name": "场景01",
            },
            "blueprint": {
                "blueprint_code": "MT-BP-20260709-39826",
                "reference_profile_code": "MT-REF-20260709-39826",
                "title": "京东空白直播间-0707-1352 重建蓝图",
                "platform": "京东",
                "room_type": "reference_rebuild",
                "reference_room_id": "39826",
                "reference_room_name": "京东空白直播间-0707-1352",
                "status": "draft",
                "scenes": [{"scene_code": "MT-SCENE-20260709-000001", "scene_name": "场景01", "layers": []}],
                "script_blocks": [],
            },
        },
    )
    assert import_response.status_code == 201
    plan_response = client.post(
        "/api/maitu/live-room-build-plans",
        json={"blueprint_code": "MT-BP-20260709-39826", "plan_name": "non destructive evidence test"},
    )
    build_plan_code = plan_response.json()["build_plan_code"]

    create_response = client.post(
        f"/api/maitu/live-room-build-plans/{build_plan_code}/execution-results",
        json={
            "executor": "browser_use",
            "execution_status": "blocked",
            "mode": "non_destructive",
            "failure_type": "preflight_not_green",
            "retryable": False,
            "result_summary": "Preflight was not green; no UI navigation was executed.",
            "dom_snapshot_asset_code": "AG-DOM-20260709-000001",
            "operation_results": [
                {
                    "operation_index": 0,
                    "operation_type": "preflight_build_plan",
                    "operation_name": "只读预检直播间蓝图",
                    "action_type": "preflight_gate",
                    "status": "blocked",
                    "failure_type": "login_required",
                    "retryable": False,
                    "error_message": "Maitu login page is visible.",
                    "details": {"ready_to_execute": False, "allowed_action_count": 0},
                }
            ],
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["execution_code"] == "MT-EXEC-20260709-000001"
    assert created["build_plan_code"] == build_plan_code
    assert created["blueprint_code"] == "MT-BP-20260709-39826"
    assert created["execution_status"] == "blocked"
    assert created["mode"] == "non_destructive"
    assert created["dom_snapshot_asset_code"] == "AG-DOM-20260709-000001"
    assert created["operation_results"][0]["operation_index"] == 0
    assert created["operation_results"][0]["action_type"] == "preflight_gate"
    assert created["operation_results"][0]["details"]["allowed_action_count"] == 0

    list_response = client.get(
        f"/api/maitu/live-room-build-plans/{build_plan_code}/execution-results",
        params={"executor": "browser_use", "execution_status": "blocked", "mode": "non_destructive"},
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["execution_code"] == created["execution_code"]

    get_response = client.get(
        f"/api/maitu/live-room-build-plans/{build_plan_code}/execution-results/{created['execution_code']}"
    )
    assert get_response.status_code == 200
    assert get_response.json()["operation_results"][0]["failure_type"] == "login_required"


def test_create_live_room_build_plan_execution_result_for_missing_plan_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/live-room-build-plans/MT-BUILD-20260709-999999/execution-results",
        json={"execution_status": "blocked", "mode": "non_destructive", "result_summary": "missing"},
    )

    assert response.status_code == 404


def test_create_live_room_build_plan_for_missing_blueprint_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/live-room-build-plans",
        json={"blueprint_code": "MT-BP-20260709-999999", "plan_name": "missing"},
    )

    assert response.status_code == 404


def test_create_and_get_natural_language_layout_adjustment(client: TestClient) -> None:
    create_response = client.post(
        "/api/maitu/layout-adjustments",
        json={
            "build_plan_code": "MT-BUILD-20260709-000001",
            "scene_name": "场景01",
            "layer_name": "商品图",
            "user_instruction": "商品图往右下挪一点，缩小一点，别挡主播",
            "before_geometry": {"x": 100, "y": 200, "width": 400, "height": 300},
            "canvas_width": 1080,
            "canvas_height": 1920,
        },
    )

    assert create_response.status_code == 201
    adjustment = create_response.json()
    assert adjustment["adjustment_code"] == "MT-ADJ-20260709-000001"
    assert adjustment["status"] == "planned"
    assert adjustment["target_geometry"] == {"x": 130.0, "y": 230.0, "width": 380.0, "height": 285.0, "rotation": 0.0, "z_index": None}
    assert adjustment["operation"]["operation_type"] == "set_layer_transform"
    assert adjustment["operation"]["details"]["tolerance_px"] == 5
    assert adjustment["checks"][-1]["name"] == "within_canvas"

    get_response = client.get("/api/maitu/layout-adjustments/MT-ADJ-20260709-000001")
    assert get_response.status_code == 200
    assert get_response.json()["layer_name"] == "商品图"


def test_get_missing_layout_adjustment_returns_404(client: TestClient) -> None:
    response = client.get("/api/maitu/layout-adjustments/MT-ADJ-20260709-999999")

    assert response.status_code == 404


class FakeSlotCandidateQwen3Client:
    embedding_model = "qwen3-embedding-4b-local"
    rerank_model = "qwen3-reranker-4b-local"

    def embed_texts(self, texts: list[str], *, is_query: bool = False, instruction: str | None = None, dimensions: int | None = None) -> list[list[float]]:
        assert is_query is True
        assert "商品讲解视频" in texts[0]
        assert "product_video" in texts[0]
        return [[1.0, 0.0, 0.0]]

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
        instruction: str | None = None,
        max_length: int | None = None,
        return_documents: bool = True,
    ) -> list[dict[str, Any]]:
        return []


def test_semantic_candidate_assets_for_slot_use_slot_context_and_retrieval_index(client: TestClient) -> None:
    from app.services.asset_candidates import AssetRetrievalIndex

    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品讲解视频",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "视频图层",
            "required_category": "product_video",
            "accepted_asset_types": ["VID"],
            "replacement_policy": "keep_layout",
            "description": "用于品酒大师商品讲解片段。",
        },
    )
    slot_code = slot_response.json()["slot_code"]
    index = AssetRetrievalIndex(
        entries=[
            {
                "document_id": "asset:AG-VID-20260709-000052:retrieval",
                "asset_code": "AG-VID-20260709-000052",
                "display_code": "MT-VID-0024",
                "local_file_code": "MT-VID-0024",
                "title": "视频 - 商品讲解视频 - 品酒大师PRO",
                "content": "品酒大师 商品讲解 视频 PRO",
                "content_hash": "hash-video",
                "metadata": {
                    "asset_type": "VID",
                    "maitu_category": "product_video",
                    "usage": "商品讲解视频",
                    "subject": "品酒大师PRO",
                    "local_relative_path": "视频/MT-VID-0024.mp4",
                },
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [1.0, 0.0, 0.0],
            },
            {
                "document_id": "asset:AG-IMG-20260709-000001:retrieval",
                "asset_code": "AG-IMG-20260709-000001",
                "display_code": "MT-IMG-0001",
                "local_file_code": "MT-IMG-0001",
                "title": "图片 - 商品主图 - 品酒大师PRO",
                "content": "品酒大师 商品主图 图片",
                "content_hash": "hash-image",
                "metadata": {
                    "asset_type": "IMG",
                    "maitu_category": "product_image",
                    "usage": "商品主图",
                    "subject": "品酒大师PRO",
                    "local_relative_path": "图片/MT-IMG-0001.png",
                },
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [0.0, 1.0, 0.0],
            },
        ]
    )
    app.dependency_overrides[maitu.get_slot_asset_retrieval_index_factory] = lambda: lambda: index
    app.dependency_overrides[maitu.get_slot_candidate_qwen3_client_factory] = lambda: lambda: FakeSlotCandidateQwen3Client()
    try:
        response = client.get(
            f"/api/maitu/slots/{slot_code}/candidate-assets",
            params={"semantic": True, "limit": 1},
        )
    finally:
        app.dependency_overrides.pop(maitu.get_slot_asset_retrieval_index_factory, None)
        app.dependency_overrides.pop(maitu.get_slot_candidate_qwen3_client_factory, None)

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "semantic_retrieval"
    assert body["semantic_query"]
    assert body["embedding_model"] == "qwen3-embedding-4b-local"
    assert body["assets"][0]["asset_code"] == "AG-VID-20260709-000052"
    assert body["assets"][0]["display_code"] == "MT-VID-0024"
    assert body["assets"][0]["original_filename"] == "MT-VID-0024.mp4"
    assert body["assets"][0]["retrieval_score"] == 1.0
    assert "maitu_category matches required_category: product_video" in body["assets"][0]["match_reasons"]


def test_semantic_best_match_replacement_plan_uses_semantic_slot_candidates(client: TestClient) -> None:
    from app.services.asset_candidates import AssetRetrievalIndex

    slot_response = client.post(
        "/api/maitu/slots",
        json={
            "slot_name": "商品讲解视频",
            "maitu_project_code": "MT-PROJ-20260707-000001",
            "scene_name": "京东空白直播间",
            "layer_name": "视频图层",
            "required_category": "product_video",
            "accepted_asset_types": ["VID"],
            "replacement_policy": "keep_layout",
            "description": "用于品酒大师商品讲解片段。",
        },
    )
    slot_code = slot_response.json()["slot_code"]
    index = AssetRetrievalIndex(
        entries=[
            {
                "document_id": "asset:AG-VID-20260709-000052:retrieval",
                "asset_code": "AG-VID-20260709-000052",
                "display_code": "MT-VID-0024",
                "local_file_code": "MT-VID-0024",
                "title": "视频 - 商品讲解视频 - 品酒大师PRO",
                "content": "品酒大师 商品讲解 视频 PRO",
                "content_hash": "hash-video",
                "metadata": {
                    "asset_type": "VID",
                    "maitu_category": "product_video",
                    "usage": "商品讲解视频",
                    "subject": "品酒大师PRO",
                    "local_relative_path": "视频/MT-VID-0024.mp4",
                },
                "model": "qwen3-embedding-4b-local",
                "dimension": 3,
                "vector": [1.0, 0.0, 0.0],
            }
        ]
    )
    app.dependency_overrides[maitu.get_slot_asset_retrieval_index_factory] = lambda: lambda: index
    app.dependency_overrides[maitu.get_slot_candidate_qwen3_client_factory] = lambda: lambda: FakeSlotCandidateQwen3Client()
    try:
        response = client.post(
            "/api/maitu/replacement-plans",
            json={
                "plan_name": "语义自动选材方案",
                "maitu_project_code": "MT-PROJ-20260707-000001",
                "scene_name": "京东空白直播间",
                "slot_codes": [slot_code],
                "strategy": "semantic_best_match",
                "description": "使用槽位语义检索自动选择素材。",
            },
        )
    finally:
        app.dependency_overrides.pop(maitu.get_slot_asset_retrieval_index_factory, None)
        app.dependency_overrides.pop(maitu.get_slot_candidate_qwen3_client_factory, None)

    assert response.status_code == 201
    plan = response.json()
    assert plan["strategy"] == "semantic_best_match"
    assert plan["items"][0]["selected_asset_code"] == "AG-VID-20260709-000052"
    assert plan["items"][0]["match_score"] == 1.0
    assert "semantic retrieval matched slot context" in plan["items"][0]["match_reasons"]

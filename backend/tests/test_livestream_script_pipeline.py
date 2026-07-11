from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import maitu
from app.main import app


class FakeScriptPipelineAssetRepository:
    def select_assets_for_script_asset_need(
        self,
        need: dict[str, Any],
        scene: dict[str, Any],
        *,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        asset_type = (need.get("accepted_asset_types") or ["IMG"])[0]
        category = str(need.get("required_category") or "asset")
        index = int(scene.get("scene_index") or 0) + 1
        return [
            {
                "asset_code": f"AG-{asset_type}-20260711-{index:06d}",
                "asset_type": asset_type,
                "title": f"{scene.get('scene_name')} {category}",
                "display_code": f"MT-{category.upper()}-{index:04d}",
                "local_file_code": f"LOCAL-{index:04d}",
                "original_filename": f"{category}-{index}.png",
                "local_relative_path": f"测试素材/{category}-{index}.png",
                "browser_use_hint": f"按 {category} 查找素材",
                "match_score": 0.95,
                "match_reasons": ["test fixture matches generated script asset need"],
            }
        ][:limit]


@pytest.fixture
def client() -> TestClient:
    repository = FakeScriptPipelineAssetRepository()
    app.dependency_overrides[maitu.get_maitu_slot_repository] = lambda: repository
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _product(
    name: str,
    *,
    positioning: str,
    facts: list[str],
    tasting: list[str],
    scenarios: list[str],
    asset_keywords: list[str],
) -> dict[str, Any]:
    return {
        "product_name": name,
        "positioning": positioning,
        "verified_facts": facts,
        "tasting_notes": tasting,
        "scenarios": scenarios,
        "selection_guidance": f"喜欢{positioning}的朋友可以重点看{name}",
        "objection_response": "先按口味选择，不按等级盲目上探",
        "asset_keywords": asset_keywords,
        "verified_promotion_claims": [],
        "unverified_promotion_claims": ["前二十名赠送礼品"],
    }


def test_generate_livestream_script_draft_is_scope_safe_and_refuses_duration_padding(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "今天八款商品内部版本",
            "platform": "京东",
            "target_duration_minutes": 30,
            "always_on_24h": True,
            "catalog_total_verified": False,
            "host_persona": "懂酒但不卖弄，替观众缩小选择",
            "products": [
                _product(
                    "龙谕龙8",
                    positioning="圆润的宁夏风格",
                    facts=["来自宁夏贺兰山东麓", "采用赤霞珠与美乐混酿"],
                    tasting=["黑樱桃", "香草", "入口圆润"],
                    scenarios=["烤肉搭配", "第一次尝试宁夏葡萄酒"],
                    asset_keywords=["龙谕龙8", "宁夏", "贺兰山东麓", "葡萄园"],
                )
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "jd_wine_livestream_script_rule_v1"
    assert body["quality_report"]["catalog_scope_safe"] is True
    assert body["quality_report"]["time_neutral"] is True
    assert body["quality_report"]["padding_free"] is True
    assert body["quality_report"]["fresh_draft_from_structured_sources"] is True
    assert body["quality_report"]["material_sufficiency_status"] == "insufficient_verified_material_for_target_duration"
    assert body["manual_review_required"] is True
    assert "直播间这1款" not in body["spoken_script"]
    assert "所有商品" not in body["spoken_script"]
    assert "今天八款商品内部版本" not in body["spoken_script"]
    assert "前二十名赠送礼品" not in body["spoken_script"]
    assert body["quality_report"]["dropped_unverified_claims"] == ["前二十名赠送礼品"]
    assert body["sections"][1]["information_owner"] == "product:龙谕龙8"
    assert body["scene_plan_payload"]["scenes"][1]["script"] == body["sections"][1]["script"]


def test_unverified_promotion_is_removed_even_if_duplicated_in_spoken_fields(client: TestClient) -> None:
    product = _product(
        "龙谕龙8",
        positioning="圆润的宁夏风格",
        facts=["来自宁夏贺兰山东麓", "采用赤霞珠与美乐混酿"],
        tasting=["黑樱桃", "香草"],
        scenarios=["烤肉搭配"],
        asset_keywords=["龙谕龙8", "宁夏", "前二十名赠送礼品"],
    )
    product["selection_guidance"] = "前二十名赠送礼品"
    response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "促销隔离测试",
            "target_duration_minutes": 1,
            "catalog_total_verified": False,
            "products": [product],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "前二十名赠送礼品" not in body["spoken_script"]
    assert all(
        "前二十名赠送礼品" not in keyword
        for section in body["sections"]
        for keyword in section["keywords"]
    )
    assert body["quality_report"]["removed_unverified_claim_sentences"] == ["前二十名赠送礼品。"]
    assert "unverified_promotion_claim_removed_from_spoken_content" in body["review_reasons"]


def test_promotion_semantics_in_non_promotion_fields_require_verified_claim_ownership(client: TestClient) -> None:
    product = _product(
        "龙谕龙8",
        positioning="圆润的宁夏风格",
        facts=["来自宁夏贺兰山东麓", "采用赤霞珠与美乐混酿"],
        tasting=["黑樱桃", "香草"],
        scenarios=["烤肉搭配"],
        asset_keywords=["龙谕龙8", "宁夏"],
    )
    product["unverified_promotion_claims"] = []
    product["objection_response"] = "前二十名赠礼"
    response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "促销语义归属测试",
            "target_duration_minutes": 1,
            "catalog_total_verified": False,
            "products": [product],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "前二十名赠礼" not in body["spoken_script"]
    assert body["quality_report"]["removed_unverified_claim_sentences"] == ["前二十名赠礼。"]
    assert "unverified_promotion_claim_removed_from_spoken_content" in body["review_reasons"]


def test_verified_promotion_claim_is_allowed_from_verified_field(client: TestClient) -> None:
    product = _product(
        "龙谕龙8",
        positioning="圆润的宁夏风格",
        facts=["来自宁夏贺兰山东麓", "采用赤霞珠与美乐混酿"],
        tasting=["黑樱桃", "香草"],
        scenarios=["烤肉搭配"],
        asset_keywords=["龙谕龙8", "宁夏"],
    )
    product["unverified_promotion_claims"] = []
    product["verified_promotion_claims"] = ["前二十名赠礼"]
    response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "已核验促销测试",
            "target_duration_minutes": 1,
            "catalog_total_verified": False,
            "products": [product],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "前二十名赠礼" in body["spoken_script"]
    assert body["quality_report"]["removed_unverified_claim_sentences"] == []


@pytest.mark.parametrize(
    "time_claim",
    ["明天20:00结束", "3小时后恢复原价", "24小时内有效", "稍后结束"],
)
def test_always_on_script_marks_relative_and_numeric_time_claims_for_review(
    client: TestClient,
    time_claim: str,
) -> None:
    product = _product(
        "龙谕龙8",
        positioning="圆润的宁夏风格",
        facts=["来自宁夏贺兰山东麓", "采用赤霞珠与美乐混酿"],
        tasting=["黑樱桃", "香草"],
        scenarios=["烤肉搭配"],
        asset_keywords=["龙谕龙8", "宁夏"],
    )
    product["verified_promotion_claims"] = [time_claim]
    response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "时间门禁测试",
            "target_duration_minutes": 1,
            "always_on_24h": True,
            "catalog_total_verified": False,
            "products": [product],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert time_claim in body["spoken_script"]
    assert body["quality_report"]["time_neutral"] is False
    assert body["manual_review_required"] is True
    assert "time_dependent_spoken_language" in body["review_reasons"]


@pytest.mark.parametrize(
    "scope_claim",
    ["本场共有8款商品", "直播间共八个商品"],
)
def test_unknown_catalog_total_blocks_numeric_scope_claims(
    client: TestClient,
    scope_claim: str,
) -> None:
    product = _product(
        "龙谕龙8",
        positioning="圆润的宁夏风格",
        facts=[scope_claim, "来自宁夏贺兰山东麓"],
        tasting=["黑樱桃", "香草"],
        scenarios=["烤肉搭配"],
        asset_keywords=["龙谕龙8", "宁夏"],
    )
    response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "范围门禁测试",
            "target_duration_minutes": 1,
            "always_on_24h": True,
            "catalog_total_verified": False,
            "products": [product],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert scope_claim in body["spoken_script"]
    assert body["quality_report"]["catalog_scope_safe"] is False
    assert body["manual_review_required"] is True
    assert "catalog_scope_assumption" in body["review_reasons"]


def test_clause_level_repetition_is_removed_before_duration_estimation(client: TestClient) -> None:
    product = _product(
        "龙谕龙8",
        positioning="圆润的宁夏风格",
        facts=["口感圆润；口感圆润；口感圆润", "来自宁夏贺兰山东麓"],
        tasting=["黑樱桃", "香草"],
        scenarios=["烤肉搭配"],
        asset_keywords=["龙谕龙8", "宁夏"],
    )
    response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "重复门禁测试",
            "target_duration_minutes": 1,
            "catalog_total_verified": False,
            "products": [product],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["spoken_script"].count("口感圆润") == 1
    assert body["quality_report"]["padding_free"] is True
    assert body["quality_report"]["removed_duplicate_sentences"]
    assert body["quality_report"]["chinese_character_count"] == len(
        re.findall(r"[\u4e00-\u9fff]", body["spoken_script"])
    )


def test_script_driven_build_pipeline_uses_generated_script_for_assets_layout_and_build_plan(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-driven-build-pipelines",
        json={
            "script_request": {
                "title": "张裕双品循环直播稿",
                "platform": "京东",
                "target_duration_minutes": 1,
                "always_on_24h": True,
                "catalog_total_verified": False,
                "host_persona": "判断直接、口语自然",
                "products": [
                    _product(
                        "品酒大师PRO",
                        positioning="花果香和清爽酸度",
                        facts=["使用蛇龙珠酿造", "橡木桶贮藏九个月以上"],
                        tasting=["紫罗兰", "成熟樱桃", "清凉草本气息"],
                        scenarios=["搭配烤鸭", "搭配有油脂的肉菜"],
                        asset_keywords=["品酒大师PRO", "蛇龙珠", "紫罗兰"],
                    ),
                    _product(
                        "龙谕龙12",
                        positioning="成熟黑果和紧实结构",
                        facts=["使用赤霞珠酿造", "来自宁夏贺兰山东麓"],
                        tasting=["黑莓", "黑樱桃", "烘烤气息"],
                        scenarios=["正式宴请", "搭配牛排"],
                        asset_keywords=["龙谕龙12", "宁夏", "贺兰山东麓", "牛排"],
                    ),
                ],
            },
            "build_mode": "strict",
            "target_live_room_id": "draft-room-001",
            "include_default_host": True,
            "max_candidates_per_need": 1,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "script_driven_build_pipeline_v1"
    assert body["status"] == "ready_for_draft_build"
    assert body["ready_for_go_live"] is False
    assert body["script_draft"]["quality_report"]["material_sufficiency_status"] == "sufficient"
    assert body["script_draft"]["sections"][0]["script"].startswith("选酒先")
    assert body["script_draft"]["spoken_script"].count("先按口味选择，不按等级盲目上探") == 1
    assert body["scene_plan"]["scene_count"] == len(body["script_draft"]["sections"])
    assert body["asset_need_plan"]["scene_count"] == body["scene_plan"]["scene_count"]
    asset_needs_by_goal = {
        scene["scene_goal"]: {need["need_type"] for need in scene["asset_needs"]}
        for scene in body["asset_need_plan"]["scenes"]
    }
    assert "product_image" not in asset_needs_by_goal["opening"]
    assert "product_image" not in asset_needs_by_goal["transition"]
    assert "product_image" in asset_needs_by_goal["product_explanation"]
    assert body["asset_selection_plan"]["missing_count"] == 0
    assert body["gap_report"]["blocking_gap_count"] == 0
    assert body["layout_plan"]["status"] == "ready_for_build_plan"
    assert body["build_plan"]["can_execute"] is True
    operations = body["build_plan"]["operations"]
    assert operations[1]["operation_type"] == "fill_default_scene"
    assert any(operation["operation_type"] == "create_scene" for operation in operations)
    written_scripts = [operation["script_text"] for operation in operations if operation["operation_type"] == "write_script"]
    assert written_scripts == [section["script"] for section in body["script_draft"]["sections"]]
    assert all("正式开播" not in operation.get("instruction", "") or "不点击正式开播" in operation.get("instruction", "") for operation in operations)


def test_script_quality_review_survives_standalone_stage_handoff(client: TestClient) -> None:
    draft_response = client.post(
        "/api/maitu/livestream-script-drafts",
        json={
            "title": "长稿素材不足",
            "target_duration_minutes": 30,
            "catalog_total_verified": False,
            "products": [
                _product(
                    "品酒大师PLUS",
                    positioning="圆润果香",
                    facts=["使用蛇龙珠酿造"],
                    tasting=["成熟浆果"],
                    scenarios=["家庭聚餐"],
                    asset_keywords=["品酒大师PLUS"],
                )
            ],
        },
    )
    assert draft_response.status_code == 201
    scenes = draft_response.json()["scene_plan_payload"]["scenes"]
    assert all(scene["manual_review"] is True for scene in scenes)

    needs_response = client.post("/api/maitu/script-asset-needs", json={"scenes": scenes})
    assert needs_response.status_code == 201
    selection_response = client.post(
        "/api/maitu/script-asset-selections",
        json={"scenes": needs_response.json()["scenes"]},
    )
    assert selection_response.status_code == 201
    layout_response = client.post(
        "/api/maitu/script-layout-plans",
        json={"build_mode": "strict", "scenes": selection_response.json()["scenes"]},
    )
    assert layout_response.status_code == 201
    layout = layout_response.json()
    assert layout["status"] == "manual_review_required"
    assert layout["can_generate_executable_build_plan"] is False

    build_response = client.post(
        "/api/maitu/script-layout-build-plans",
        json={"layout_plan": layout},
    )
    assert build_response.status_code == 201
    assert build_response.json()["can_execute"] is False


def test_script_quality_review_blocks_executable_pipeline_but_keeps_reviewable_artifacts(client: TestClient) -> None:
    response = client.post(
        "/api/maitu/script-driven-build-pipelines",
        json={
            "script_request": {
                "title": "资料不足的长循环稿",
                "target_duration_minutes": 30,
                "catalog_total_verified": False,
                "products": [
                    _product(
                        "品酒大师PLUS",
                        positioning="圆润果香",
                        facts=["使用蛇龙珠酿造"],
                        tasting=["成熟浆果"],
                        scenarios=["家庭聚餐"],
                        asset_keywords=["品酒大师PLUS"],
                    )
                ],
            },
            "build_mode": "draft_with_placeholders",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["script_draft"]["manual_review_required"] is True
    assert body["status"] == "script_quality_review_required"
    assert body["build_plan"]["can_execute"] is False
    assert body["build_plan"]["manual_review_required"] is True
    assert "script_quality_review_required" in body["build_plan"]["blocked_reasons"]
    assert body["build_plan"]["operation_count"] > 0
    blocked_operation_types = {
        "fill_default_scene",
        "create_scene",
        "insert_asset_layer",
        "position_asset_layer",
        "write_script",
        "save_draft",
    }
    assert all(
        operation["status"] == "blocked_script_quality"
        for operation in body["build_plan"]["operations"]
        if operation["operation_type"] in blocked_operation_types
    )
    assert body["ready_for_go_live"] is False

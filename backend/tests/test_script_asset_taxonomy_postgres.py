from __future__ import annotations

import os

import psycopg
import pytest

from app.repositories.maitu import MaituMaterialSlotRepository

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_product_image_need_selects_native_product_sticker_but_not_promotion_sticker() -> None:
    product_asset_code = "AG-IMG-TAX-PRO-1"
    other_product_asset_code = "AG-IMG-TAX-OTHER-1"
    promotion_asset_code = "AG-IMG-TAX-PROMO-1"
    codes = (product_asset_code, other_product_asset_code, promotion_asset_code)

    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM assets WHERE asset_code = ANY(%s)", (list(codes),))
            cursor.executemany(
                """
                INSERT INTO assets (
                    asset_code, asset_type, title, original_filename, status,
                    maitu_category, maitu_type, usage, subject, source_system,
                    local_file_code, display_code, local_relative_path
                )
                VALUES (%s, 'IMG', %s, %s, 'stored', 'floating_sticker', '装饰', %s, %s, 'maitu', %s, %s, %s)
                """,
                (
                    (
                        product_asset_code,
                        "装饰 - 商品贴片 - PhaseB-PRO",
                        "phase-b-product.png",
                        "商品贴片",
                        "PhaseB-PRO",
                        "MT-DEC-TAX-PRO",
                        "MT-DEC-TAX-PRO",
                        "装饰/phase-b-product.png",
                    ),
                    (
                        other_product_asset_code,
                        "装饰 - 商品贴片 - PhaseB-OTHER",
                        "phase-b-other-product.png",
                        "商品贴片",
                        "PhaseB-OTHER",
                        "MT-DEC-TAX-OTHER",
                        "MT-DEC-TAX-OTHER",
                        "装饰/phase-b-other-product.png",
                    ),
                    (
                        promotion_asset_code,
                        "装饰 - 买赠贴片 - PhaseB-PRO",
                        "phase-b-promotion.png",
                        "买赠贴片",
                        "PhaseB-PRO",
                        "MT-DEC-TAX-PROMO",
                        "MT-DEC-TAX-PROMO",
                        "装饰/phase-b-promotion.png",
                    ),
                ),
            )
        connection.commit()
        repository = MaituMaterialSlotRepository(connection)
        need = {
            "need_type": "product_image",
            "required_category": " product_image ",
            "accepted_asset_types": ["IMG"],
            "keywords": ["PhaseB-PRO"],
            "priority": "high",
        }
        scene = {
            "scene_name": "Phase B 商品讲解",
            "script": "现在看 PhaseB-PRO 的商品贴片。",
            "keywords": ["PhaseB-PRO"],
        }
        try:
            candidates = repository.select_assets_for_script_asset_need(need, scene, limit=10)

            candidate_codes = [candidate["asset_code"] for candidate in candidates]
            assert candidate_codes == [product_asset_code]
            assert promotion_asset_code not in candidate_codes
            assert all(candidate["usage"] in {"商品贴片", "商品主图", "瓶身图", "整箱图"} for candidate in candidates)
            assert candidates[0]["maitu_category"] == "floating_sticker"
            assert candidates[0]["usage"] == "商品贴片"
            assert any("product_image" in reason for reason in candidates[0]["match_reasons"])

            component = {
                "required_category": " product_image ",
                "accepted_asset_types": ["IMG"],
                "layer_role": "product",
                "layer_name": "商品主图",
            }
            selected = repository.select_asset_for_template_component(
                component,
                {"scene_name": "Phase B 模板场景"},
                "当前商品是 PhaseB-OTHER",
            )
            assert selected is not None
            assert selected["asset_code"] == other_product_asset_code
            assert (
                repository.select_asset_for_template_component(
                    component,
                    {"scene_name": "Phase B 模板场景"},
                    "当前商品是 PhaseB-MISSING",
                )
                is None
            )
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM assets WHERE asset_code = ANY(%s)", (list(codes),))
            connection.commit()

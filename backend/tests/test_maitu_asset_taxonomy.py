from __future__ import annotations

from app.services.maitu_asset_taxonomy import (
    asset_matches_product_identity,
    asset_matches_required_category,
    product_identity_keywords,
    required_category_variants,
)


def test_product_image_maps_to_canonical_and_native_maitu_product_sticker_taxonomy() -> None:
    variants = required_category_variants("product_image")

    assert {variant.maitu_category for variant in variants} == {"product_image", "floating_sticker"}
    assert asset_matches_required_category(
        {
            "maitu_category": "floating_sticker",
            "maitu_type": "装饰",
            "usage": "商品贴片",
        },
        "product_image",
    )
    assert asset_matches_required_category(
        {"maitu_category": "product_image", "maitu_type": "图片", "usage": "商品主图"},
        "product_image",
    )


def test_product_image_mapping_rejects_unrelated_decorations_and_promotions() -> None:
    for asset in (
        {"maitu_category": "floating_sticker", "maitu_type": "装饰", "usage": "装饰"},
        {"maitu_category": "floating_sticker", "maitu_type": "装饰", "usage": "买赠贴片"},
        {"maitu_category": "floating_sticker", "maitu_type": "背景", "usage": "商品贴片"},
    ):
        assert not asset_matches_required_category(asset, "product_image")


def test_unmapped_required_category_remains_an_exact_category_match() -> None:
    assert asset_matches_required_category(
        {"maitu_category": "background_image", "maitu_type": "背景", "usage": "直播背景"},
        "background_image",
    )
    assert not asset_matches_required_category(
        {"maitu_category": "floating_sticker", "maitu_type": "装饰", "usage": "装饰"},
        "background_image",
    )


def test_product_image_requires_specific_product_identity_not_generic_wine_terms() -> None:
    keywords = product_identity_keywords(["品酒大师PRO", "张裕", "750ml", "整箱", "礼盒"])

    assert keywords == ("品酒大师PRO",)
    assert product_identity_keywords(["龙谕龙12", "龙谕"]) == ("龙谕龙12",)
    split_keywords = product_identity_keywords(["龙谕", "龙12"])
    assert split_keywords == ("龙谕", "龙12")
    assert asset_matches_product_identity(
        {"subject": "龙谕龙12", "title": "商品贴片"},
        split_keywords,
    )
    assert not asset_matches_product_identity(
        {"subject": "龙谕龙8", "title": "商品贴片"},
        split_keywords,
    )
    assert not asset_matches_product_identity(
        {"subject": "龙谕龙8", "title": "商品贴片"},
        product_identity_keywords(["龙谕龙12", "龙谕"]),
    )
    assert asset_matches_product_identity(
        {"subject": "品酒大师PRO", "title": "商品贴片"},
        keywords,
    )
    assert not asset_matches_product_identity(
        {"subject": "龙谕龙12", "title": "张裕750ml整箱礼盒"},
        keywords,
    )
    assert not asset_matches_product_identity(
        {"subject": "品酒大师PRO", "title": "商品贴片"},
        product_identity_keywords(["张裕", "750ml", "整箱", "礼盒"]),
    )

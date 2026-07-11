from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RequiredCategoryVariant:
    """One safe native Maitu taxonomy variant for a semantic asset requirement."""

    maitu_category: str
    maitu_type: str | None = None
    usages: tuple[str, ...] = ()


_PRODUCT_IMAGE_NATIVE_USAGES = (
    "商品贴片",
    "商品主图",
    "瓶身图",
    "整箱图",
)

_REQUIRED_CATEGORY_VARIANTS: dict[str, tuple[RequiredCategoryVariant, ...]] = {
    "product_image": (
        RequiredCategoryVariant(maitu_category="product_image"),
        RequiredCategoryVariant(
            maitu_category="floating_sticker",
            maitu_type="装饰",
            usages=_PRODUCT_IMAGE_NATIVE_USAGES,
        ),
    ),
}


_GENERIC_PRODUCT_IMAGE_KEYWORDS = {
    "商品",
    "商品图",
    "商品主图",
    "商品贴片",
    "主图",
    "瓶身",
    "瓶身图",
    "整箱",
    "整箱图",
    "礼盒",
    "750ml",
    "葡萄酒",
    "红酒",
    "干红",
    "张裕",
}


def product_identity_keywords(keywords: list[Any] | tuple[Any, ...]) -> tuple[str, ...]:
    """Keep only product-specific identity tokens suitable for automatic image binding."""
    result: list[str] = []
    seen: set[str] = set()
    generic = {keyword.casefold() for keyword in _GENERIC_PRODUCT_IMAGE_KEYWORDS}
    for keyword in keywords:
        text = str(keyword or "").strip()
        normalized = text.casefold()
        if not text or normalized in generic or normalized in seen:
            continue
        result.append(text)
        seen.add(normalized)
    return tuple(
        keyword
        for keyword in result
        if not any(
            keyword.casefold() != other.casefold()
            and keyword.casefold() in other.casefold()
            for other in result
        )
    )


def asset_matches_product_identity(
    asset: dict[str, Any],
    identity_keywords: tuple[str, ...],
) -> bool:
    """Require a concrete product identity; an empty/generic-only need fails closed."""
    if not identity_keywords:
        return False
    identity_text = " ".join(
        str(asset.get(field) or "")
        for field in (
            "title",
            "original_filename",
            "display_code",
            "local_file_code",
            "subject",
            "description",
        )
    ).casefold()
    return all(keyword.casefold() in identity_text for keyword in identity_keywords)


def asset_product_identity_mentioned_in_text(asset: dict[str, Any], text: str) -> bool:
    """Require the candidate's own specific subject identity to appear in context."""
    subject_keywords = product_identity_keywords([asset.get("subject")])
    if not subject_keywords:
        return False
    normalized_text = str(text or "").casefold()
    return all(keyword.casefold() in normalized_text for keyword in subject_keywords)


def required_category_variants(required_category: str) -> tuple[RequiredCategoryVariant, ...]:
    """Return exact-or-explicit-native variants; unknown categories stay exact."""
    category = str(required_category or "").strip()
    if not category:
        return ()
    return _REQUIRED_CATEGORY_VARIANTS.get(
        category,
        (RequiredCategoryVariant(maitu_category=category),),
    )


def asset_matches_required_category(asset: dict[str, Any], required_category: str) -> bool:
    """Match a semantic requirement without broadening to unrelated Maitu decorations."""
    for variant in required_category_variants(required_category):
        if asset.get("maitu_category") != variant.maitu_category:
            continue
        if variant.maitu_type is not None and asset.get("maitu_type") != variant.maitu_type:
            continue
        if variant.usages and asset.get("usage") not in variant.usages:
            continue
        return True
    return False

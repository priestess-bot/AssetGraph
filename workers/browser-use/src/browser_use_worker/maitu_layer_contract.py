from __future__ import annotations

from typing import Any


# Business roles stay intact in the BuildPlan. This matrix is the only boundary
# that translates them into concrete Maitu clip-material media types.
LAYER_SOURCE_TYPES: dict[str, frozenset[str]] = {
    "background": frozenset({"image", "video"}),
    "set_surface": frozenset({"image"}),
    "product_display": frozenset({"image", "video"}),
    "digital_human": frozenset({"digital_human"}),
    "brand_title": frozenset({"image"}),
    "promotion_text": frozenset({"image"}),
    "decoration_foreground": frozenset({"image", "video"}),
    "supporting_video": frozenset({"video"}),
    # Legacy BuildPlan vocabulary remains supported while persisted plans age out.
    "background_image": frozenset({"image"}),
    "product_image": frozenset({"image"}),
    "promotion_sticker": frozenset({"image"}),
    "brand_logo_title": frozenset({"image"}),
    "supporting_visual": frozenset({"image", "video"}),
    "product_video": frozenset({"video"}),
}


def normalize_maitu_material_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"video", "decorative_video"}:
        return "video"
    if normalized in {"image", "digital_human"}:
        return normalized
    return None


def maitu_payload_type_for_layer(layer_type: Any, source_material_type: Any) -> str | None:
    role = str(layer_type or "").strip().lower()
    source_type = normalize_maitu_material_type(source_material_type)
    allowed = LAYER_SOURCE_TYPES.get(role)
    if source_type is None or allowed is None or source_type not in allowed:
        return None
    return source_type


def layer_media_kind(layer_type: Any) -> str | None:
    allowed = LAYER_SOURCE_TYPES.get(str(layer_type or "").strip().lower())
    if allowed is None:
        return None
    if allowed == frozenset({"image"}):
        return "image"
    if allowed == frozenset({"video"}):
        return "video"
    if allowed == frozenset({"digital_human"}):
        return "digital_human"
    if allowed == frozenset({"image", "video"}):
        return "visual"
    return None

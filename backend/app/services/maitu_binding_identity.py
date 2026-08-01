from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit


def canonical_maitu_binding_identity(
    asset_code: str,
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the stable material identity shared by receipt and checkpoint code."""

    return {
        "asset_code": asset_code,
        "maitu_material_id": binding.get("maitu_material_id"),
        "maitu_source_material_id": binding.get("maitu_source_material_id"),
        "source_material_type": binding.get("source_material_type"),
        "source_material_url": _stable_public_url(binding.get("source_material_url")),
        "source_cover_url": _stable_public_url(binding.get("source_cover_url")),
        "speaker_id": binding.get("speaker_id"),
        "digital_human_image_id": binding.get("digital_human_image_id"),
    }


def _stable_public_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        return "!invalid"
    return parsed._replace(query="", fragment="").geturl()

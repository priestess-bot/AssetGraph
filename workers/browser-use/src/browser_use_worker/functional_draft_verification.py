from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .maitu_layer_contract import maitu_payload_type_for_layer, normalize_maitu_material_type
from .room_inspection import inspect_working_room


def verify_functional_draft(
    session: Any,
    *,
    operation_plan: dict[str, Any],
    target_live_room_id: str,
    expected_title: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    inspection = inspect_working_room(
        session,
        target_live_room_id=target_live_room_id,
        expected_title=expected_title,
    )
    if (
        inspection["actual_title"] != expected_title
        or inspection["is_live"] is not False
        or inspection["has_live_trace"] is not False
    ):
        raise ValueError("final room identity or offline state does not match the execution contract")
    room = session.read_live_room(target_live_room_id)
    clips = [
        clip
        for topic in room.get("topics") or []
        if isinstance(topic, dict)
        for clip in topic.get("clips") or []
        if isinstance(clip, dict)
    ]
    clips.sort(key=lambda clip: (float(clip.get("order_num") or 0), int(clip.get("id") or 0)))
    operations = [item for item in operation_plan.get("operations") or [] if isinstance(item, dict)]
    scene_operations = [item for item in operations if item.get("operation_type") == "verify_scene"]
    scripts = {
        int(item["scene_index"]): str(item.get("script_text") or "")
        for item in operations
        if item.get("operation_type") == "write_script" and item.get("scene_index") is not None
    }
    position_by_layer: dict[tuple[int, str], dict[str, Any]] = {}
    for item in operations:
        if item.get("operation_type") != "position_asset_layer" or item.get("scene_index") is None:
            continue
        position_by_layer[(int(item["scene_index"]), str(item.get("layer_id") or ""))] = item
    layers_by_scene: dict[int, list[dict[str, Any]]] = {}
    for item in operations:
        if item.get("operation_type") == "insert_asset_layer" and item.get("scene_index") is not None:
            scene_index = int(item["scene_index"])
            position = position_by_layer.get((scene_index, str(item.get("layer_id") or ""))) or {}
            layers_by_scene.setdefault(scene_index, []).append({**item, **position})
    if len(clips) != len(scene_operations):
        raise ValueError(
            f"final scene count mismatch: expected {len(scene_operations)}, observed {len(clips)}"
        )
    scene_results: list[dict[str, Any]] = []
    for index, (clip, expected) in enumerate(zip(clips, scene_operations, strict=True)):
        expected_name = str(expected.get("scene_name") or "")
        if str(clip.get("name") or "") != expected_name:
            raise ValueError(f"final scene name mismatch at index {index}")
        materials = clip.get("clip_materials")
        if not isinstance(materials, list):
            raise ValueError(f"scene {expected_name!r} has no authoritative material list")
        visuals = [
            material
            for material in materials
            if isinstance(material, dict) and material.get("type") not in {"text", "audio"}
        ]
        expected_layers = layers_by_scene.get(index, [])
        if len(visuals) != len(expected_layers):
            raise ValueError(f"scene {expected_name!r} visual layer count mismatch")
        observed_by_layer = {
            str(material.get("name") or ""): material
            for material in visuals
            if str(material.get("name") or "")
        }
        if len(observed_by_layer) != len(visuals):
            raise ValueError(f"scene {expected_name!r} has missing or duplicate layer identities")
        expected_order = [
            str(layer.get("layer_id") or "")
            for layer in sorted(
                expected_layers,
                key=lambda layer: _positive_layer(layer.get("z_index"), expected_name),
            )
        ]
        observed_order = [
            str(layer.get("name") or "")
            for layer in sorted(
                visuals,
                key=lambda layer: _positive_layer(layer.get("layer_n"), expected_name),
            )
        ]
        if observed_order != expected_order:
            raise ValueError(f"scene {expected_name!r} exact layer order mismatch")
        for expected_layer in expected_layers:
            layer_id = str(expected_layer.get("layer_id") or "")
            observed_layer = observed_by_layer.get(layer_id)
            expected_type = maitu_payload_type_for_layer(
                expected_layer.get("layer_type"),
                expected_layer.get("source_material_type"),
            )
            if not layer_id or observed_layer is None or expected_type is None:
                raise ValueError(
                    f"scene {expected_name!r} layer role or identity is not executable"
                )
            if normalize_maitu_material_type(observed_layer.get("type")) != expected_type:
                raise ValueError(f"scene {expected_name!r} layer {layer_id!r} type mismatch")
            if expected_type == "digital_human":
                for field in ("speaker_id", "digital_human_image_id"):
                    expected_value = expected_layer.get(field)
                    if expected_value is None or str(observed_layer.get(field) or "") != str(
                        expected_value
                    ):
                        raise ValueError(
                            f"scene {expected_name!r} layer {layer_id!r} {field} mismatch"
                        )
                expected_source_id = expected_layer.get("maitu_source_material_id")
                if expected_source_id is None:
                    raise ValueError(
                        f"scene {expected_name!r} layer {layer_id!r} has no digital-human source id"
                    )
                if str(observed_layer.get("material_id") or "") != str(expected_source_id):
                    raise ValueError(
                        f"scene {expected_name!r} layer {layer_id!r} digital-human source id mismatch"
                    )
                expected_source_url = str(
                    expected_layer.get("source_material_url")
                    or expected_layer.get("source_cover_url")
                    or ""
                )
                if expected_source_url and _canonical_source_url(
                    observed_layer.get("url")
                ) != _canonical_source_url(expected_source_url):
                    raise ValueError(
                        f"scene {expected_name!r} layer {layer_id!r} digital-human source URL mismatch"
                    )
            else:
                expected_material_id = expected_layer.get("material_id") or expected_layer.get(
                    "maitu_material_id"
                )
                if expected_material_id is None:
                    raise ValueError(
                        f"scene {expected_name!r} layer {layer_id!r} has no source id"
                    )
                if str(observed_layer.get("material_id") or "") != str(expected_material_id):
                    raise ValueError(
                        f"scene {expected_name!r} layer {layer_id!r} source id mismatch"
                    )
                expected_url = str(expected_layer.get("source_material_url") or "")
                if not expected_url or _canonical_source_url(
                    observed_layer.get("url")
                ) != _canonical_source_url(expected_url):
                    raise ValueError(
                        f"scene {expected_name!r} layer {layer_id!r} source URL mismatch"
                    )
            style = _material_style(observed_layer)
            expected_fit = str(expected_layer.get("fit") or "contain")
            if str(style.get("fit") or "") != expected_fit:
                raise ValueError(f"scene {expected_name!r} layer {layer_id!r} fit mismatch")
            transform = style.get("transform") if isinstance(style.get("transform"), dict) else {}
            if float(transform.get("rotation", 0.0)) != float(expected_layer.get("rotation", 0.0)):
                raise ValueError(f"scene {expected_name!r} layer {layer_id!r} rotation mismatch")
            for observed_field, expected_field in (
                ("left", "x"),
                ("top", "y"),
                ("width", "width"),
                ("height", "height"),
            ):
                if not _numbers_equal(
                    style.get(observed_field), expected_layer.get(expected_field)
                ):
                    raise ValueError(
                        f"scene {expected_name!r} layer {layer_id!r} geometry mismatch"
                    )
            expected_z = _positive_layer(expected_layer.get("z_index"), expected_name)
            if (
                _positive_layer(observed_layer.get("layer_n"), expected_name) != expected_z
                or _positive_layer(style.get("zIndex"), expected_name) != expected_z
            ):
                raise ValueError(f"scene {expected_name!r} layer {layer_id!r} z-index mismatch")
            expected_muted = bool(expected_layer.get("muted", True))
            if bool(observed_layer.get("sound_enabled")) is not (not expected_muted):
                raise ValueError(f"scene {expected_name!r} layer {layer_id!r} mute mismatch")
            expected_loop = bool(expected_layer.get("loop", False))
            observed_loop = str(observed_layer.get("play_mode") or "").strip().lower() in {
                "loop",
                "repeat",
                "continuous",
            }
            if observed_loop is not expected_loop:
                raise ValueError(f"scene {expected_name!r} layer {layer_id!r} loop mismatch")
        layer_numbers = [_positive_layer(material.get("layer_n"), expected_name) for material in visuals]
        if sorted(layer_numbers) != list(range(1, len(layer_numbers) + 1)):
            raise ValueError(f"scene {expected_name!r} layer numbers are not unique and contiguous")
        highest = max(visuals, key=lambda material: _positive_layer(material.get("layer_n"), expected_name))
        if "video" in str(highest.get("type") or "").lower():
            raise ValueError(f"scene {expected_name!r} has a video at the highest visual layer")
        texts = [
            str(material.get("content") or "")
            for material in materials
            if isinstance(material, dict) and material.get("type") == "text"
        ]
        expected_script = scripts.get(index, "")
        if len(texts) != 1 or texts[0] != expected_script:
            raise ValueError(f"scene {expected_name!r} script readback mismatch")
        scene_results.append(
            {
                "scene_index": index,
                "scene_id": str(clip.get("id")),
                "scene_name": expected_name,
                "visual_count": len(visuals),
                "layer_numbers": layer_numbers,
                "highest_layer_type": highest.get("type"),
                "expected_layer_order": expected_order,
                "observed_layer_order": observed_order,
                "exact_expected_order": True,
                "script_matched": True,
            }
        )
    return (
        {
            "matched": True,
            "scene_count": len(scene_results),
            "scenes": scene_results,
            "verification_source": "refreshed_working_room_readback",
        },
        {
            "passed": True,
            "continuous_from_one": True,
            "exact_expected_order": True,
            "exact_geometry_and_source": True,
            "video_never_highest": True,
            "scenes": scene_results,
        },
    )


def _positive_layer(value: Any, scene_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"scene {scene_name!r} has a non-integer layer number")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"scene {scene_name!r} has a non-integer layer number") from exc
    if parsed <= 0 or float(value) != parsed:
        raise ValueError(f"scene {scene_name!r} has a non-positive layer number")
    return parsed


def _material_style(material: dict[str, Any]) -> dict[str, Any]:
    value = material.get("style_front")
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _numbers_equal(observed: Any, expected: Any) -> bool:
    if expected is None:
        return False
    try:
        return abs(float(observed) - float(expected)) <= 1e-6
    except (TypeError, ValueError):
        return False


def _canonical_source_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.material_library import AssetClassificationUpdate, AssetConstraintProfileWrite
from app.services.functional_live_rooms import FunctionalLiveRoomService
from app.services.layer_stacking import compile_layer_stack
from app.services.material_bootstrap import (
    MaterialClassification,
    MaterialBootstrapError,
    build_bootstrap_plan,
    build_report,
    constraints_for,
    fingerprint,
    infer_classification,
    probe_local_media,
)


def test_local_media_probe_decodes_ffprobe_json_as_utf8(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def run_ffprobe(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout='{"format":{"filename":"背景.png"},"streams":[]}',
            stderr="",
        )

    monkeypatch.setattr("app.services.material_bootstrap.subprocess.run", run_ffprobe)

    result = probe_local_media(tmp_path / "背景.png")

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert result["schema_version"] == "local-material-probe-v1"


def test_deterministic_roles_keep_ambiguous_assets_for_review() -> None:
    background = infer_classification(
        {"media_kind": "image", "relative_path": "背景/MT-BG-0001_背景_直播背景_背景-3.png"}
    )
    table = infer_classification(
        {"media_kind": "image", "relative_path": "装饰/MT-DEC-0004_装饰_装饰底图_底图.png"}
    )
    product = infer_classification(
        {"media_kind": "image", "relative_path": "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png"}
    )
    ambiguous = infer_classification(
        {"media_kind": "image", "relative_path": "装饰/MT-DEC-0006_装饰_装饰_png.png"}
    )

    assert background.roles == ("background",)
    assert table.roles == ("set_surface",)
    assert product.roles == ("product_display",)
    assert ambiguous.roles == ()
    assert ambiguous.review_status == "review_required"


def test_visual_review_overrides_misleading_or_ambiguous_names() -> None:
    product = infer_classification(
        {
            "file_code": "39598_100029295227",
            "media_kind": "image",
            "relative_path": "背景/39598_100029295227.png",
        }
    )
    executable_background_alias = infer_classification(
        {
            "file_code": "42419_MT-TPL-0001_模版_模板预览_张裕618背景_preview",
            "media_kind": "image",
            "usage": "图片",
            "relative_path": "背景/42419_MT-TPL-0001_模版_模板预览_张裕618背景_preview.png",
        }
    )

    assert product.roles == ("product_display",)
    assert product.rule_id == "visual_product_cutout"
    assert executable_background_alias.roles == ("background",)
    assert executable_background_alias.media_kind == "image"


def test_video_constraints_preserve_content_and_forbid_top_layer() -> None:
    classification = infer_classification(
        {"media_kind": "video", "relative_path": "视频/MT-VID-0016_视频_酒体视频_品酒大师PRO_酒体.mov"}
    )

    constraints = constraints_for(classification)

    assert {rule["kind"] for rule in constraints} >= {
        "preserve_aspect_ratio",
        "crop_policy",
        "above_role",
        "below_role",
        "forbid_layer_top",
    }
    assert next(rule for rule in constraints if rule["kind"] == "crop_policy")["parameters"]["policy"] == "contain"
    assert {rule["parameters"].get("role") for rule in constraints if rule["kind"] == "below_role"} >= {
        "digital_human",
        "brand_title",
        "decoration_foreground",
    }
    assert all(
        rule["parameters"].get("when_present") is True
        for rule in constraints
        if rule["kind"] in {"above_role", "below_role"}
    )


def test_bootstrap_constraints_compile_without_requiring_every_optional_role() -> None:
    layers = []
    for code, classification in (
        (
            "BACKGROUND",
            infer_classification(
                {"media_kind": "image", "relative_path": "背景/MT-BG-0001_背景_直播背景_背景-3.png"}
            ),
        ),
        (
            "VIDEO",
            infer_classification(
                {"media_kind": "video", "relative_path": "视频/MT-VID-0016_视频_酒体视频_品酒大师PRO_酒体.mov"}
            ),
        ),
        (
            "HOST",
            MaterialClassification(
                "image",
                ("digital_human",),
                "confirmed",
                1.0,
                "native_inventory",
                "测试数字人。",
            ),
        ),
    ):
        layers.append(
            {
                "asset_code": code,
                "role": classification.roles[0],
                "z_order": 99 if code == "VIDEO" else 1,
                "constraint_rules": list(constraints_for(classification)),
            }
        )

    assert compile_layer_stack(layers) == []
    assert [layer["asset_code"] for layer in layers] == ["BACKGROUND", "VIDEO", "HOST"]


def test_table_surface_constraint_provides_a_valid_named_region() -> None:
    classification = infer_classification(
        {"media_kind": "image", "relative_path": "装饰/MT-DEC-0004_装饰_装饰底图_底图.png"}
    )
    assets = [
        {
            "asset_code": "TABLE",
            "constraint_profile_ref": {"constraints": list(constraints_for(classification))},
        }
    ]

    regions, table_surfaces, failures = FunctionalLiveRoomService._named_regions(assets)

    assert failures == []
    assert regions == {"table_surface": {"x": 0.0, "y": 0.45, "width": 1.0, "height": 0.55}}
    assert table_surfaces == {
        "table_surface": {
            "product_role": "product_display",
            "product_anchor": "bottom_center",
            "hard": True,
        }
    }


def test_bootstrap_table_surface_places_product_fully_inside_the_surface() -> None:
    surface_classification = infer_classification(
        {"media_kind": "image", "relative_path": "装饰/MT-DEC-0004_装饰_装饰底图_底图.png"}
    )
    product_classification = infer_classification(
        {"media_kind": "image", "relative_path": "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png"}
    )
    surface = {
        "asset_code": "TABLE",
        "constraint_profile_ref": {
            "constraints": list(constraints_for(surface_classification))
        },
    }
    product = {
        "asset_code": "PRODUCT",
        "constraint_profile_ref": {
            "constraints": list(constraints_for(product_classification))
        },
    }

    regions, table_surfaces, failures = FunctionalLiveRoomService._named_regions(
        [surface, product]
    )
    geometry, _, _, _, evidence, layer_failures = (
        FunctionalLiveRoomService._resolve_layer_constraints(
            asset=product,
            role="product_display",
            named_regions=regions,
            table_surfaces=table_surfaces,
        )
    )

    assert failures == []
    assert layer_failures == []
    assert geometry == {
        "x": pytest.approx(0.3),
        "y": pytest.approx(0.6),
        "width": pytest.approx(0.4),
        "height": pytest.approx(0.4),
    }
    assert geometry["y"] >= regions["table_surface"]["y"]
    assert geometry["y"] + geometry["height"] <= 1.0 + 1e-9
    assert any(
        item["kind"] == "table_surface_placement"
        for item in evidence["applied_rules"]
    )
    layers = [
        {
            "asset_code": "TABLE",
            "role": "set_surface",
            "z_order": 99,
            "constraint_rules": list(constraints_for(surface_classification)),
        },
        {
            "asset_code": "PRODUCT",
            "role": "product_display",
            "z_order": 1,
            "constraint_rules": list(constraints_for(product_classification)),
        },
    ]
    assert compile_layer_stack(layers) == []
    assert [layer["asset_code"] for layer in layers] == ["TABLE", "PRODUCT"]


def test_manual_classification_cannot_claim_verified_maitu_binding() -> None:
    with pytest.raises(ValidationError, match="verified Maitu inventory binding"):
        AssetClassificationUpdate(
            media_kind="image",
            material_roles=["background"],
            execution_capability="maitu_bound",
        )


def test_constraint_schema_rejects_top_and_forbid_top_together() -> None:
    with pytest.raises(ValidationError, match="forbidden from the top"):
        AssetConstraintProfileWrite.model_validate(
            {
                "constraints": [
                    {"kind": "pin_layer_top", "hard": True, "parameters": {}},
                    {"kind": "forbid_layer_top", "hard": True, "parameters": {}},
                ]
            }
        )


def test_63_asset_plan_requires_unique_checksum_matched_inventory_evidence(tmp_path: Path) -> None:
    catalog: list[dict] = []
    assets: list[dict] = []
    inventory: list[dict] = []
    for index in range(63):
        code = f"MT-VID-{index + 1:04d}"
        relative = f"视频/{code}_视频_商品讲解视频_素材{index + 1}.mp4"
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(f"material-{index}".encode())
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        catalog.append(
            {
                "file_code": code,
                "media_kind": "video" if index < 62 else "image",
                "relative_path": relative,
                "sha256": checksum,
                "file_size": source.stat().st_size,
                "mime_type": "video/mp4",
                "maitu_type": "模版" if index == 62 else "视频",
                "usage": "模板预览" if index == 62 else "商品讲解视频",
            }
        )
        assets.append(
            {
                "id": f"asset-{index}",
                "asset_code": f"AG-VID-TEST-{index:06d}",
                "local_file_code": code,
                "checksum_sha256": checksum,
                "rights_status": "pending",
            }
        )
        inventory.append(
            {
                "item_key": f"maitu:{index}",
                "material_id": None if index == 62 else str(50_000 + index),
                "material_type": "template" if index == 62 else "decorative_video",
                "checksum_sha256": checksum,
                "metadata": {"local_file_code": code},
                "source_material_url": None if index == 62 else f"https://example.invalid/{index}.mp4",
                "source_cover_url": None,
            }
        )
        if index == 62:
            inventory.append(
                {
                    "item_key": "maitu:image:template-preview-alias",
                    "material_id": "99999",
                    "material_type": "image",
                    "checksum_sha256": checksum,
                    "metadata": {"local_file_code": code},
                    "source_material_url": "https://example.invalid/template-preview.png",
                }
            )
    inventory.append(
        {
            "item_key": "maitu:digital_human:37200",
            "material_id": "37200",
            "material_type": "digital_human",
            "title": "张裕定制形象260519",
            "speaker_id": 3760,
            "digital_human_image_id": 7717,
            "source_material_url": "https://example.invalid/digital-human.png",
            "source_cover_url": None,
            "metadata": {},
        }
    )
    observation = {
        "schema_version": "maitu-inventory-observation-v1",
        "quality_status": "complete",
        "captured_at": "2026-07-31T00:00:00+00:00",
        "items": inventory,
        "source_revision": fingerprint(inventory),
    }

    plan = build_bootstrap_plan(
        catalog_assets=catalog,
        database_assets=assets,
        observation=observation,
        observation_path=tmp_path / "inventory.json",
        assets_root=tmp_path,
        probe=lambda _path: {"width": 1080, "height": 1920, "duration_seconds": 10},
    )
    report = build_report(plan, mode="dry_run")

    assert report["summary"] == {
        "catalog_count": 63,
        "asset_match_count": 63,
        "inventory_evidence_match_count": 63,
        "executable_binding_count": 62,
        "reference_only_count": 1,
        "review_required_count": 0,
        "digital_human_binding_count": 1,
        "ambiguous_count": 0,
        "unmatched_count": 0,
    }
    assert {item["rights_status_unchanged"] for item in report["items"]} == {"pending"}
    assert len(report["input_fingerprint"]) == 64
    assert "observation_path" not in report["input_manifest"]
    assert all("before" in item and "after" in item for item in report["items"])
    assert all(
        item["before"]["rights_status"] == item["after"]["rights_status"] == "pending"
        for item in report["items"]
    )
    assert all(len(item["constraint_fingerprint"]) == 64 for item in report["items"])

    plan.items[0].asset["classification_confidence"] = Decimal("0.96")
    assert build_report(plan, mode="dry_run")["items"][0]["before"][
        "classification_confidence"
    ] == 0.96
    assert report["digital_human"] == {
        "asset_code": None,
        "maitu_source_material_id": 37200,
        "digital_human_image_id": 7717,
        "speaker_id": 3760,
        "inventory_item_fingerprint": fingerprint(inventory[-1]),
    }

    duplicate_observation = {**observation, "items": [*inventory, dict(inventory[0])]}
    duplicate_observation["source_revision"] = fingerprint(duplicate_observation["items"])
    with pytest.raises(MaterialBootstrapError, match="ambiguous"):
        build_bootstrap_plan(
            catalog_assets=catalog,
            database_assets=assets,
            observation=duplicate_observation,
            observation_path=tmp_path / "inventory.json",
            assets_root=tmp_path,
            probe=lambda _path: {},
        )


def test_bootstrap_rejects_cache_paths_before_reading_files(tmp_path: Path) -> None:
    item = {
        "file_code": "CACHE-1",
        "media_kind": "image",
        "relative_path": ".asset-preview-cache/cache.png",
        "sha256": "a" * 64,
        "file_size": 1,
    }
    inventory = [
        {
            "item_key": "maitu:image:1",
            "material_id": "1",
            "material_type": "image",
            "checksum_sha256": "a" * 64,
            "metadata": {"local_file_code": "CACHE-1"},
        },
        {
            "item_key": "maitu:digital_human:37200",
            "material_id": "37200",
            "material_type": "digital_human",
            "speaker_id": 3760,
            "digital_human_image_id": 7717,
            "metadata": {},
        },
    ]
    observation = {
        "schema_version": "maitu-inventory-observation-v1",
        "quality_status": "complete",
        "items": inventory,
        "source_revision": fingerprint(inventory),
    }

    with pytest.raises(MaterialBootstrapError, match="cache path"):
        build_bootstrap_plan(
            catalog_assets=[item],
            database_assets=[
                {
                    "id": "asset-1",
                    "asset_code": "AG-IMG-1",
                    "local_file_code": "CACHE-1",
                    "checksum_sha256": "a" * 64,
                }
            ],
            observation=observation,
            observation_path=tmp_path / "inventory.json",
            assets_root=tmp_path,
            expected_count=1,
        )

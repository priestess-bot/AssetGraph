from __future__ import annotations

import pytest

from app.services.functional_live_rooms import FunctionalLiveRoomService


def _asset(asset_code: str, role: str, constraints: list[dict[str, object]]) -> dict[str, object]:
    return {
        "asset_code": asset_code,
        "material_roles": [role],
        "constraint_profile_ref": {"constraints": constraints},
    }


def test_table_surface_places_product_without_duplicate_product_constraint() -> None:
    background = _asset(
        "ASSET-BACKGROUND",
        "background",
        [
            {
                "kind": "table_surface",
                "hard": True,
                "parameters": {
                    "name": "counter",
                    "x": 0.1,
                    "y": 0.6,
                    "width": 0.8,
                    "height": 0.3,
                    "product_role": "product_display",
                    "product_anchor": "bottom_center",
                },
            }
        ],
    )
    product = _asset("ASSET-PRODUCT", "product_display", [])

    named_regions, table_surfaces, failures = FunctionalLiveRoomService._named_regions([background, product])
    geometry, _, _, _, evidence, layer_failures = FunctionalLiveRoomService._resolve_layer_constraints(
        asset=product,
        role="product_display",
        named_regions=named_regions,
        table_surfaces=table_surfaces,
    )

    assert failures == []
    assert layer_failures == []
    assert geometry == {
        "x": pytest.approx(0.3),
        "y": pytest.approx(0.6),
        "width": pytest.approx(0.4),
        "height": pytest.approx(0.3),
    }
    assert evidence["table_surfaces_available"]["counter"]["product_role"] == "product_display"
    assert evidence["applied_rules"][-1]["kind"] == "table_surface_placement"


def test_named_region_accepts_legacy_region_field() -> None:
    legacy_surface = _asset(
        "ASSET-LEGACY",
        "background",
        [
            {
                "kind": "table_surface",
                "hard": True,
                "parameters": {"region": "legacy_counter", "rect": [0.2, 0.6, 0.6, 0.2]},
            }
        ],
    )

    named_regions, table_surfaces, failures = FunctionalLiveRoomService._named_regions([legacy_surface])

    assert failures == []
    assert named_regions["legacy_counter"] == {"x": 0.2, "y": 0.6, "width": 0.6, "height": 0.2}
    assert table_surfaces["legacy_counter"]["product_anchor"] == "bottom_center"

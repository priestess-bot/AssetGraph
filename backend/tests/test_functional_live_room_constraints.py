from __future__ import annotations

import pytest

from app.domain.errors import DomainValidationError
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


def test_room_private_override_is_snapshotted_and_global_hard_constraints_still_apply() -> None:
    asset = _asset(
        "ASSET-PRODUCT",
        "product_display",
        [
            {
                "kind": "allowed_region",
                "hard": True,
                "parameters": {"x": 0.2, "y": 0.25, "width": 0.5, "height": 0.4},
            }
        ],
    )
    asset["room_constraint_override"] = {
        "reason": "适配本直播间的商品陈列区域",
        "geometry": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
        "z_order": 42,
        "actor_id": "operator-1",
    }

    geometry, z_order, _, _, evidence, failures = FunctionalLiveRoomService._resolve_layer_constraints(
        asset=asset,
        role="product_display",
        named_regions={},
        table_surfaces={},
    )

    assert failures == []
    assert geometry == {
        "x": pytest.approx(0.2),
        "y": pytest.approx(0.25),
        "width": pytest.approx(0.5),
        "height": pytest.approx(0.4),
    }
    assert z_order == 42
    assert evidence["room_constraint_override"]["actor_id"] == "operator-1"
    assert evidence["applied_rules"][0]["kind"] == "room_private_override"
    assert evidence["applied_rules"][1]["kind"] == "allowed_region"


def test_room_private_override_requires_selected_asset_and_reason() -> None:
    selected = [_asset("ASSET-PRODUCT", "product_display", [])]

    with pytest.raises(DomainValidationError) as not_selected:
        FunctionalLiveRoomService._validate_room_constraint_overrides(
            {
                "ASSET-OTHER": {
                    "reason": "无效",
                    "geometry": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                }
            },
            selected,
            actor_id="operator-1",
        )
    assert not_selected.value.code == "LIVE_ROOM_CONSTRAINT_OVERRIDE_NOT_SELECTED"

    with pytest.raises(DomainValidationError) as no_reason:
        FunctionalLiveRoomService._validate_room_constraint_overrides(
            {
                "ASSET-PRODUCT": {
                    "geometry": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                }
            },
            selected,
            actor_id="operator-1",
        )
    assert no_reason.value.code == "LIVE_ROOM_CONSTRAINT_OVERRIDE_REASON_REQUIRED"

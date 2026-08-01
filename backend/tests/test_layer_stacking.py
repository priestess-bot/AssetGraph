from __future__ import annotations

from hypothesis import given, settings, strategies as st

from app.services.layer_stacking import compile_layer_stack, stack_is_contiguous


def _layer(
    code: str,
    role: str,
    z_order: int,
    *rules: dict[str, object],
) -> dict[str, object]:
    return {
        "layer_id": code,
        "asset_code": code,
        "role": role,
        "z_order": z_order,
        "constraint_rules": list(rules),
        "constraint_evidence": {},
    }


def test_hard_top_and_bottom_create_strict_bands_with_unique_platform_order() -> None:
    layers = [
        _layer("VIDEO", "supporting_video", 99),
        _layer("TITLE", "brand_title", 1, {"kind": "pin_layer_top", "hard": True}),
        _layer("BACKGROUND", "background", 50, {"kind": "pin_layer_bottom", "hard": True}),
        _layer("HOST", "digital_human", 2),
    ]

    failures = compile_layer_stack(layers)

    assert failures == []
    assert [layer["asset_code"] for layer in layers] == ["BACKGROUND", "HOST", "VIDEO", "TITLE"]
    assert [layer["z_order"] for layer in layers] == [1, 2, 3, 4]
    assert stack_is_contiguous(layers)
    assert layers[0]["constraint_evidence"]["stacking"]["pin_band"] == "bottom"
    assert layers[-1]["constraint_evidence"]["stacking"]["pin_band"] == "top"


def test_relative_rules_place_full_screen_video_between_background_and_host() -> None:
    layers = [
        _layer("HOST", "digital_human", 1),
        _layer(
            "VIDEO",
            "supporting_video",
            9,
            {"kind": "above_role", "hard": True, "parameters": {"role": "background"}},
            {"kind": "below_role", "hard": True, "parameters": {"role": "digital_human"}},
        ),
        _layer("BACKGROUND", "background", 8),
    ]

    assert compile_layer_stack(layers) == []
    assert [layer["asset_code"] for layer in layers] == ["BACKGROUND", "VIDEO", "HOST"]


def test_legacy_z_index_is_rewritten_to_the_resolved_platform_order() -> None:
    layers = [
        {
            "layer_id": "VIDEO",
            "asset_code": "VIDEO",
            "role": "supporting_video",
            "z_index": 99,
            "constraint_rules": [
                {"kind": "above_role", "hard": True, "parameters": {"role": "background"}},
                {"kind": "below_role", "hard": True, "parameters": {"role": "digital_human"}},
            ],
        },
        {
            "layer_id": "HOST",
            "asset_code": "HOST",
            "role": "digital_human",
            "z_index": 1,
            "constraint_rules": [],
        },
        {
            "layer_id": "BACKGROUND",
            "asset_code": "BACKGROUND",
            "role": "background",
            "z_index": 50,
            "constraint_rules": [{"kind": "pin_layer_bottom", "hard": True}],
        },
    ]

    assert compile_layer_stack(layers) == []
    assert [layer["asset_code"] for layer in layers] == ["BACKGROUND", "VIDEO", "HOST"]
    assert [layer["z_index"] for layer in layers] == [1, 2, 3]
    assert [layer["z_order"] for layer in layers] == [1, 2, 3]
    assert stack_is_contiguous(layers)


def test_hard_pin_conflict_and_relative_cycle_block_compilation() -> None:
    pinned = _layer(
        "IMPOSSIBLE",
        "brand_title",
        1,
        {"kind": "pin_layer_top", "hard": True},
        {"kind": "pin_layer_bottom", "hard": True},
    )
    other = _layer("OTHER", "background", 2)

    failures = compile_layer_stack([pinned, other])

    assert "constraint_layer_pin_conflict:IMPOSSIBLE" in failures
    assert any(reason.startswith("constraint_layer_order_cycle:") for reason in failures)


def test_hard_relation_that_breaks_top_band_is_rejected() -> None:
    title = _layer(
        "TITLE",
        "brand_title",
        1,
        {"kind": "pin_layer_top", "hard": True},
        {"kind": "below_role", "hard": True, "parameters": {"role": "background"}},
    )
    background = _layer("BACKGROUND", "background", 2)

    failures = compile_layer_stack([title, background])

    assert any(reason.startswith("constraint_layer_order_cycle:") for reason in failures)


def test_legacy_soft_pin_is_blocked_instead_of_becoming_a_best_effort_order() -> None:
    layers = [
        _layer("TITLE", "brand_title", 1, {"kind": "pin_layer_top", "hard": False}),
        _layer("BACKGROUND", "background", 2),
    ]

    failures = compile_layer_stack(layers)

    assert failures == ["constraint_layer_pin_must_be_hard:TITLE"]


def test_forbid_top_keeps_product_video_below_an_available_normal_layer() -> None:
    layers = [
        _layer(
            "VIDEO",
            "supporting_video",
            99,
            {"kind": "forbid_layer_top", "hard": True},
            {"kind": "above_role", "hard": True, "parameters": {"role": "background"}},
        ),
        _layer("BACKGROUND", "background", 1, {"kind": "pin_layer_bottom", "hard": True}),
        _layer("HOST", "digital_human", 2),
    ]

    assert compile_layer_stack(layers) == []
    assert [layer["asset_code"] for layer in layers] == ["BACKGROUND", "VIDEO", "HOST"]
    assert layers[1]["constraint_evidence"]["stacking"]["forbid_layer_top"] is True


def test_forbid_top_blocks_a_scene_when_no_layer_can_be_above() -> None:
    layers = [
        _layer(
            "VIDEO",
            "supporting_video",
            1,
            {"kind": "forbid_layer_top", "hard": True},
        )
    ]

    assert compile_layer_stack(layers) == ["constraint_layer_top_forbidden:VIDEO"]


def test_top_pin_and_forbid_top_on_the_same_layer_is_a_hard_conflict() -> None:
    layers = [
        _layer(
            "VIDEO",
            "supporting_video",
            1,
            {"kind": "pin_layer_top", "hard": True},
            {"kind": "forbid_layer_top", "hard": True},
        ),
        _layer("BACKGROUND", "background", 2),
    ]

    failures = compile_layer_stack(layers)

    assert "constraint_layer_top_forbidden_conflict:VIDEO" in failures
    assert "constraint_layer_top_forbidden:VIDEO" in failures


def test_hard_relative_rule_can_be_conditional_on_target_presence() -> None:
    layers = [
        _layer(
            "VIDEO",
            "supporting_video",
            4,
            {
                "kind": "below_role",
                "hard": True,
                "parameters": {"role": "digital_human", "when_present": True},
            },
        ),
        _layer("TITLE", "brand_title", 8),
    ]

    assert compile_layer_stack(layers) == []
    stacking = layers[0]["constraint_evidence"]["stacking"]
    assert stacking["conditional_relations_not_applicable"] == [
        {"kind": "below_role", "role": "digital_human"}
    ]
    assert stacking["soft_rule_deviations"] == []


_PROPERTY_LAYER_CODES = (
    "BACKGROUND",
    "SURFACE",
    "PRODUCT",
    "VIDEO",
    "HOST",
    "TITLE",
)


@settings(max_examples=100, deadline=None)
@given(
    input_order=st.permutations(_PROPERTY_LAYER_CODES),
    legacy_z_orders=st.tuples(
        *(st.integers(min_value=-10_000, max_value=10_000) for _ in _PROPERTY_LAYER_CODES)
    ),
    legacy_z_indexes=st.tuples(
        *(st.integers(min_value=-10_000, max_value=10_000) for _ in _PROPERTY_LAYER_CODES)
    ),
)
def test_hard_constraint_topology_is_invariant_to_input_order_and_legacy_z_values(
    input_order: list[str],
    legacy_z_orders: tuple[int, ...],
    legacy_z_indexes: tuple[int, ...],
) -> None:
    rules_by_code: dict[str, tuple[str, tuple[dict[str, object], ...]]] = {
        "BACKGROUND": (
            "background",
            ({"kind": "pin_layer_bottom", "hard": True},),
        ),
        "SURFACE": (
            "set_surface",
            (
                {"kind": "above_role", "hard": True, "parameters": {"role": "background"}},
                {
                    "kind": "below_role",
                    "hard": True,
                    "parameters": {"role": "product_display"},
                },
            ),
        ),
        "PRODUCT": (
            "product_display",
            (
                {
                    "kind": "above_role",
                    "hard": True,
                    "parameters": {"role": "set_surface"},
                },
                {
                    "kind": "below_role",
                    "hard": True,
                    "parameters": {"role": "supporting_video"},
                },
            ),
        ),
        "VIDEO": (
            "supporting_video",
            (
                {"kind": "forbid_layer_top", "hard": True},
                {
                    "kind": "above_role",
                    "hard": True,
                    "parameters": {"role": "product_display"},
                },
                {
                    "kind": "below_role",
                    "hard": True,
                    "parameters": {"role": "digital_human"},
                },
            ),
        ),
        "HOST": (
            "digital_human",
            (
                {
                    "kind": "above_role",
                    "hard": True,
                    "parameters": {"role": "supporting_video"},
                },
                {
                    "kind": "below_role",
                    "hard": True,
                    "parameters": {"role": "brand_title"},
                },
            ),
        ),
        "TITLE": (
            "brand_title",
            ({"kind": "pin_layer_top", "hard": True},),
        ),
    }
    old_order_by_code = dict(zip(_PROPERTY_LAYER_CODES, legacy_z_orders, strict=True))
    old_index_by_code = dict(zip(_PROPERTY_LAYER_CODES, legacy_z_indexes, strict=True))
    layers = []
    for code in input_order:
        role, rules = rules_by_code[code]
        layer = _layer(code, role, old_order_by_code[code], *rules)
        layer["z_index"] = old_index_by_code[code]
        layers.append(layer)

    failures = compile_layer_stack(layers)

    assert failures == []
    assert [layer["asset_code"] for layer in layers] == list(_PROPERTY_LAYER_CODES)
    assert [layer["z_order"] for layer in layers] == list(range(1, 7))
    assert [layer["z_index"] for layer in layers] == list(range(1, 7))
    assert stack_is_contiguous(layers)
    assert layers[0]["constraint_evidence"]["stacking"]["pin_band"] == "bottom"
    assert layers[-1]["constraint_evidence"]["stacking"]["pin_band"] == "top"
    video = next(layer for layer in layers if layer["role"] == "supporting_video")
    assert video["constraint_evidence"]["stacking"]["forbid_layer_top"] is True
    assert layers[-1]["role"] != "supporting_video"

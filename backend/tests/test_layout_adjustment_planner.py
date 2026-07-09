from __future__ import annotations

from app.services.layout_adjustment import LayerGeometry, plan_layout_adjustment


def test_plan_moves_right_down_and_scales_down_from_natural_language() -> None:
    result = plan_layout_adjustment(
        user_instruction="商品图往右下挪一点，缩小一点，别挡主播",
        before_geometry=LayerGeometry(x=100, y=200, width=400, height=300),
        canvas_width=1080,
        canvas_height=1920,
    )

    assert result.status == "planned"
    assert result.target_geometry.x == 130
    assert result.target_geometry.y == 230
    assert result.target_geometry.width == 380
    assert result.target_geometry.height == 285
    assert result.operation["operation_type"] == "set_layer_transform"
    assert "dx=30" in result.operation["instruction"]
    assert "scale=0.95" in result.operation["instruction"]
    assert any(check["name"] == "within_canvas" and check["status"] == "passed" for check in result.checks)


def test_plan_uses_explicit_pixel_delta_and_clamps_to_canvas() -> None:
    result = plan_layout_adjustment(
        user_instruction="往左50px，再往上30px",
        before_geometry=LayerGeometry(x=20, y=10, width=200, height=100),
        canvas_width=1080,
        canvas_height=1920,
    )

    assert result.target_geometry.x == 0
    assert result.target_geometry.y == 0
    assert any(check["name"] == "clamped_to_canvas" and check["status"] == "warning" for check in result.checks)


def test_plan_centers_layer_horizontally() -> None:
    result = plan_layout_adjustment(
        user_instruction="这个图层水平居中",
        before_geometry=LayerGeometry(x=20, y=100, width=300, height=200),
        canvas_width=1080,
        canvas_height=1920,
    )

    assert result.target_geometry.x == 390
    assert result.target_geometry.y == 100
    assert result.operation["details"]["actions"] == ["center_x"]


def test_plan_anchors_layer_to_bottom_right_safe_area() -> None:
    result = plan_layout_adjustment(
        user_instruction="放到右下角，留点边距",
        before_geometry=LayerGeometry(x=20, y=100, width=300, height=200),
        canvas_width=1080,
        canvas_height=1920,
        safe_margin=24,
    )

    assert result.target_geometry.x == 756
    assert result.target_geometry.y == 1696
    assert result.operation["details"]["actions"] == ["anchor_right", "anchor_bottom"]


def test_plan_requires_manual_review_for_ambiguous_instruction() -> None:
    result = plan_layout_adjustment(
        user_instruction="这个位置不太对，调好看点",
        before_geometry=LayerGeometry(x=20, y=100, width=300, height=200),
        canvas_width=1080,
        canvas_height=1920,
    )

    assert result.status == "manual_required"
    assert result.target_geometry == result.before_geometry
    assert result.operation["operation_type"] == "manual_layout_review"
    assert any(check["name"] == "instruction_parse" and check["status"] == "warning" for check in result.checks)

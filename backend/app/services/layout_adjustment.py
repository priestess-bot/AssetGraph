from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LayerGeometry:
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0
    z_index: int | None = None


@dataclass(frozen=True, slots=True)
class LayoutAdjustmentPlan:
    status: str
    before_geometry: LayerGeometry
    target_geometry: LayerGeometry
    operation: dict[str, Any]
    checks: list[dict[str, Any]]


_STEP_PX = 30
_SMALL_SCALE_DOWN = 0.95
_SMALL_SCALE_UP = 1.05


def plan_layout_adjustment(
    *,
    user_instruction: str,
    before_geometry: LayerGeometry,
    canvas_width: float,
    canvas_height: float,
    safe_margin: float = 20,
) -> LayoutAdjustmentPlan:
    """Convert a constrained Chinese natural-language layout tweak into geometry.

    This is intentionally conservative: only explicit directions, alignment, anchor,
    and small scale phrases are converted. Ambiguous aesthetic-only feedback returns
    a manual review operation instead of guessing.
    """

    instruction = user_instruction.strip()
    checks: list[dict[str, Any]] = []
    actions: list[str] = []
    dx = _parse_axis_delta(instruction, axis="x")
    dy = _parse_axis_delta(instruction, axis="y")
    scale = _parse_scale(instruction)

    x = before_geometry.x
    y = before_geometry.y
    width = before_geometry.width
    height = before_geometry.height

    if _wants_center_x(instruction):
        x = (canvas_width - width) / 2
        actions.append("center_x")
    if _wants_anchor_right(instruction):
        x = canvas_width - width - safe_margin
        actions.append("anchor_right")
    if _wants_anchor_bottom(instruction):
        y = canvas_height - height - safe_margin
        actions.append("anchor_bottom")

    if dx:
        x += dx
        actions.append(f"move_x:{dx:g}")
    if dy:
        y += dy
        actions.append(f"move_y:{dy:g}")
    if scale != 1.0:
        width = round(width * scale, 6)
        height = round(height * scale, 6)
        actions.append(f"scale:{scale:g}")

    if not actions:
        checks.append(
            {
                "name": "instruction_parse",
                "status": "warning",
                "summary": "Instruction is ambiguous; manual layout review is required before moving the layer.",
                "details": {"user_instruction": user_instruction},
            }
        )
        return LayoutAdjustmentPlan(
            status="manual_required",
            before_geometry=before_geometry,
            target_geometry=before_geometry,
            operation={
                "operation_type": "manual_layout_review",
                "status": "manual_required",
                "instruction": f"用户反馈“{user_instruction}”缺少明确方向/尺寸/对齐约束，请生成候选调整方案或请用户补充。",
                "details": {"actions": []},
            },
            checks=checks,
        )

    target, clamp_warning = _clamp_to_canvas(
        LayerGeometry(
            x=round(x, 6),
            y=round(y, 6),
            width=round(width, 6),
            height=round(height, 6),
            rotation=before_geometry.rotation,
            z_index=before_geometry.z_index,
        ),
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )
    if clamp_warning is not None:
        checks.append(clamp_warning)
    checks.append(
        {
            "name": "within_canvas",
            "status": "passed",
            "summary": "Target geometry is inside the canvas after planning.",
            "details": {
                "canvas_width": canvas_width,
                "canvas_height": canvas_height,
                "target_geometry": asdict(target),
            },
        }
    )

    operation = {
        "operation_type": "set_layer_transform",
        "status": "planned",
        "before_geometry": asdict(before_geometry),
        "target_geometry": asdict(target),
        "instruction": (
            f"根据用户反馈“{user_instruction}”执行图层微调："
            f"dx={target.x - before_geometry.x:g}, dy={target.y - before_geometry.y:g}, "
            f"scale={target.width / before_geometry.width:g}；执行后必须重新 Observe 并校验误差。"
        ),
        "details": {
            "actions": actions,
            "canvas_width": canvas_width,
            "canvas_height": canvas_height,
            "safe_margin": safe_margin,
            "tolerance_px": 5,
        },
    }
    return LayoutAdjustmentPlan(
        status="planned",
        before_geometry=before_geometry,
        target_geometry=target,
        operation=operation,
        checks=checks,
    )


def _parse_axis_delta(instruction: str, *, axis: str) -> float:
    explicit = _parse_explicit_px(instruction, axis=axis)
    if explicit is not None:
        return explicit

    amount = _STEP_PX
    if any(token in instruction for token in ("一点点", "稍微", "微调")):
        amount = 15
    if any(token in instruction for token in ("多一点", "大一点", "再多")):
        amount = 60

    if axis == "x":
        if "往右" in instruction or "右移" in instruction or "向右" in instruction:
            return amount
        if "往左" in instruction or "左移" in instruction or "向左" in instruction:
            return -amount
    if axis == "y":
        if (
            "往下" in instruction
            or "下移" in instruction
            or "向下" in instruction
            or "往右下" in instruction
            or "向右下" in instruction
            or "右下挪" in instruction
            or "往左下" in instruction
            or "向左下" in instruction
            or "左下挪" in instruction
        ):
            return amount
        if (
            "往上" in instruction
            or "上移" in instruction
            or "向上" in instruction
            or "往右上" in instruction
            or "向右上" in instruction
            or "右上挪" in instruction
            or "往左上" in instruction
            or "向左上" in instruction
            or "左上挪" in instruction
        ):
            return -amount
    return 0.0


def _parse_explicit_px(instruction: str, *, axis: str) -> float | None:
    patterns = {
        "x": [
            (r"(?:往右|右移|向右)\s*(\d+(?:\.\d+)?)\s*(?:px|像素)?", 1),
            (r"(?:往左|左移|向左)\s*(\d+(?:\.\d+)?)\s*(?:px|像素)?", -1),
        ],
        "y": [
            (r"(?:往下|下移|向下)\s*(\d+(?:\.\d+)?)\s*(?:px|像素)?", 1),
            (r"(?:往上|上移|向上)\s*(\d+(?:\.\d+)?)\s*(?:px|像素)?", -1),
        ],
    }
    for pattern, sign in patterns[axis]:
        match = re.search(pattern, instruction)
        if match:
            return sign * float(match.group(1))
    return None


def _parse_scale(instruction: str) -> float:
    match = re.search(r"(?:缩小|放小)\s*(\d+(?:\.\d+)?)\s*%", instruction)
    if match:
        return max(0.01, 1 - float(match.group(1)) / 100)
    match = re.search(r"(?:放大|放宽|变大)\s*(\d+(?:\.\d+)?)\s*%", instruction)
    if match:
        return 1 + float(match.group(1)) / 100
    if any(token in instruction for token in ("缩小一点", "小一点", "缩一点")):
        return _SMALL_SCALE_DOWN
    if any(token in instruction for token in ("放大一点", "大一点", "大点")):
        return _SMALL_SCALE_UP
    return 1.0


def _wants_center_x(instruction: str) -> bool:
    return "水平居中" in instruction or "横向居中" in instruction or ("居中" in instruction and "右下" not in instruction)


def _wants_anchor_right(instruction: str) -> bool:
    return "右下角" in instruction or "靠右" in instruction or "贴右" in instruction


def _wants_anchor_bottom(instruction: str) -> bool:
    return "右下角" in instruction or "靠下" in instruction or "贴底" in instruction or "底部" in instruction


def _clamp_to_canvas(geometry: LayerGeometry, *, canvas_width: float, canvas_height: float) -> tuple[LayerGeometry, dict[str, Any] | None]:
    x = min(max(geometry.x, 0), max(canvas_width - geometry.width, 0))
    y = min(max(geometry.y, 0), max(canvas_height - geometry.height, 0))
    clamped = LayerGeometry(
        x=round(x, 6),
        y=round(y, 6),
        width=geometry.width,
        height=geometry.height,
        rotation=geometry.rotation,
        z_index=geometry.z_index,
    )
    if clamped == geometry:
        return clamped, None
    return clamped, {
        "name": "clamped_to_canvas",
        "status": "warning",
        "summary": "Requested adjustment would move the layer outside the canvas, so it was clamped.",
        "details": {"requested_geometry": asdict(geometry), "clamped_geometry": asdict(clamped)},
    }

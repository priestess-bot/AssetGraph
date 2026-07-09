#!/usr/bin/env python3
"""Extract a Maitu ReferenceRoomProfile and LiveRoomBlueprint from Browser-use Observe JSON.

This script is intentionally artifact-first: it converts the read-only
`browser_use_worker --observe-maitu` output into durable JSON/Markdown files
before any mutating Browser-use operation is attempted.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse


@dataclass(slots=True)
class ExtractOptions:
    observed_state_path: Path
    output_dir: Path = Path("docs/asset-numbering")
    date_stamp: str | None = None
    profile_output: Path | None = None
    blueprint_output: Path | None = None
    markdown_output: Path | None = None


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def today_stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def load_observed_state(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("observed state JSON must be an object")
    return data


def room_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    return clean(parse_qs(parsed.query).get("liveRoomId", [""])[0])


def infer_room_id(state: dict[str, Any]) -> str:
    room_id = clean(state.get("live_room_id")) or room_id_from_url(clean(state.get("url")))
    if not room_id:
        raise ValueError("live_room_id is required; run browser_use_worker --observe-maitu on a real LiveRoom URL")
    return room_id


def infer_platform(state: dict[str, Any]) -> str | None:
    platform = clean(state.get("platform"))
    room_name = clean(state.get("live_room_name"))
    text = clean(state.get("text"))
    source = " ".join(part for part in [platform, room_name, text] if part)
    if "京东" in source:
        return "京东"
    if "淘宝" in source or "天猫" in source:
        return "淘宝"
    if "抖音" in source:
        return "抖音"
    if platform:
        return platform.removesuffix("版")
    return None


def normalize_tabs(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    tabs: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = clean(row.get("name"))
        if not name:
            continue
        tabs.append({"name": name, "active": bool(row.get("active")), "sort_order": index})
    return tabs


def normalize_scenes(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    scenes: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = clean(row.get("name"))
        if not name:
            continue
        scenes.append(
            {
                "scene_name": name,
                "scene_type": clean(row.get("scene_type")) or None,
                "status": clean(row.get("status")) or None,
                "active": bool(row.get("active")),
                "sort_order": index,
            }
        )
    return scenes


def classify_layer(layer_name: str) -> dict[str, Any]:
    lower_name = layer_name.lower()
    if "背景" in layer_name or layer_name.startswith("微信图片"):
        return {
            "layer_role": "background",
            "required_category": "background_image",
            "accepted_asset_types": ["IMG"],
            "material_tab": "背景",
        }
    if any(marker in layer_name for marker in ["珠珠", "品酒大师", "分身", "主播", "模特"]):
        return {
            "layer_role": "digital_human",
            "required_category": "digital_human_video",
            "accepted_asset_types": ["IMG", "VID"],
            "material_tab": "数字分身",
        }
    if "标题" in layer_name or "logo" in lower_name:
        return {
            "layer_role": "logo_title",
            "required_category": "floating_sticker",
            "accepted_asset_types": ["IMG"],
            "material_tab": "装饰",
        }
    if "前景" in layer_name:
        return {
            "layer_role": "foreground_frame",
            "required_category": "floating_sticker",
            "accepted_asset_types": ["IMG"],
            "material_tab": "装饰",
        }
    if "gif" in lower_name:
        return {
            "layer_role": "animated_sticker",
            "required_category": "floating_sticker",
            "accepted_asset_types": ["IMG"],
            "material_tab": "装饰",
        }
    if "视频" in layer_name or lower_name.endswith(".mp4"):
        return {
            "layer_role": "product_video",
            "required_category": "product_video",
            "accepted_asset_types": ["VID"],
            "material_tab": "视频",
        }
    if "文本" in layer_name:
        return {
            "layer_role": "text",
            "required_category": "text_overlay",
            "accepted_asset_types": [],
            "material_tab": "文本",
        }
    return {
        "layer_role": "decoration",
        "required_category": "floating_sticker",
        "accepted_asset_types": ["IMG"],
        "material_tab": "装饰",
    }


def normalize_layers(rows: Any, *, date_stamp: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    layers: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = clean(row.get("name"))
        if not name:
            continue
        classified = classify_layer(name)
        layer: dict[str, Any] = {
            "layer_name": name,
            "active": bool(row.get("active")),
            "sort_order": index,
            "layer_index": index - 1,
            **classified,
            "replacement_policy": "keep_layout",
        }
        if date_stamp:
            layer["layer_code"] = f"MT-LAYER-{date_stamp}-{index:06d}"
        layers.append(layer)
    return layers


def infer_scene_goal(scene_type: str | None, sort_order: int) -> str:
    if scene_type == "讲品":
        return f"第{sort_order}段产品讲解"
    if scene_type == "特写":
        return f"第{sort_order}段商品细节特写"
    if scene_type == "问答":
        return f"第{sort_order}段互动问答"
    if scene_type == "过渡":
        return f"第{sort_order}段直播过渡"
    return f"第{sort_order}段参考场景"


def safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-")
    return cleaned or "room"


def build_reference_profile(state: dict[str, Any], *, date_stamp: str, room_id: str) -> dict[str, Any]:
    scenes = normalize_scenes(state.get("scenes"))
    active_scene_name = clean(state.get("active_scene_name")) or next(
        (scene["scene_name"] for scene in scenes if scene.get("active")), ""
    )
    layers = normalize_layers(state.get("layers"))
    return {
        "profile_code": f"MT-REF-{date_stamp}-{safe_slug(room_id)}",
        "source": "browser_use_observe",
        "source_url": clean(state.get("url")),
        "page_title": clean(state.get("title")),
        "reference_room_id": room_id,
        "reference_room_name": clean(state.get("live_room_name")),
        "platform": infer_platform(state),
        "logged_in": bool(state.get("logged_in")),
        "login_required": bool(state.get("login_required")),
        "active_scene_name": active_scene_name or None,
        "scenes": scenes,
        "active_scene_layers": layers,
        "material_tabs": normalize_tabs(state.get("material_tabs")),
        "active_material_tab": clean(state.get("active_material_tab")) or None,
        "workbench_tabs": normalize_tabs(state.get("workbench_tabs")),
        "active_workbench_tab": clean(state.get("active_workbench_tab")) or None,
        "script_texts": [clean(text) for text in state.get("script_texts", []) if clean(text)]
        if isinstance(state.get("script_texts"), list)
        else [],
        "raw_observe_summary": {
            "scene_count": len(scenes),
            "active_scene_layer_count": len(layers),
            "material_tab_count": len(normalize_tabs(state.get("material_tabs"))),
            "workbench_tab_count": len(normalize_tabs(state.get("workbench_tabs"))),
        },
    }


def build_blueprint(profile: dict[str, Any], *, date_stamp: str, room_id: str) -> dict[str, Any]:
    active_scene_name = clean(profile.get("active_scene_name"))
    script_texts = profile.get("script_texts") if isinstance(profile.get("script_texts"), list) else []
    script_blocks = [
        {
            "script_block_code": f"MT-SCRIPT-BLOCK-{date_stamp}-{index:06d}",
            "scene_name": active_scene_name or None,
            "sort_order": index,
            "content": clean(text),
            "source": "reference_room_profile",
        }
        for index, text in enumerate(script_texts, start=1)
        if clean(text)
    ]

    scene_blueprints: list[dict[str, Any]] = []
    for scene in profile.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        sort_order = int(scene.get("sort_order") or len(scene_blueprints) + 1)
        scene_name = clean(scene.get("scene_name"))
        scene_type = clean(scene.get("scene_type")) or None
        scene_layers = []
        if active_scene_name and scene_name == active_scene_name:
            for layer_index, layer in enumerate(profile.get("active_scene_layers", []), start=1):
                if not isinstance(layer, dict):
                    continue
                layer_copy = dict(layer)
                layer_copy.setdefault("layer_code", f"MT-LAYER-{date_stamp}-{layer_index:06d}")
                layer_copy["scene_name"] = scene_name
                scene_layers.append(layer_copy)
        scene_blueprints.append(
            {
                "scene_code": f"MT-SCENE-{date_stamp}-{sort_order:06d}",
                "scene_name": scene_name,
                "scene_type": scene_type,
                "status": scene.get("status"),
                "sort_order": sort_order,
                "goal": infer_scene_goal(scene_type, sort_order),
                "estimated_duration_seconds": 30 if scene_type == "讲品" else None,
                "reference_active": bool(scene.get("active")),
                "layers": scene_layers,
            }
        )

    room_name = clean(profile.get("reference_room_name"))
    return {
        "blueprint_code": f"MT-BP-{date_stamp}-{safe_slug(room_id)}",
        "reference_profile_code": profile["profile_code"],
        "title": f"{room_name} 重建蓝图" if room_name else f"参考直播间 {room_id} 重建蓝图",
        "platform": profile.get("platform"),
        "room_type": "reference_rebuild",
        "reference_room_id": room_id,
        "reference_room_name": room_name,
        "status": "draft",
        "description": "由 Browser-use Observe 现场状态自动抽取的 LiveRoomBlueprint 初稿；仅用于规划，不会点击保存或开播。",
        "scenes": scene_blueprints,
        "script_blocks": script_blocks,
        "material_tabs": profile.get("material_tabs", []),
        "workbench_tabs": profile.get("workbench_tabs", []),
        "safety_rules": [
            "默认不点击正式开播",
            "真实执行前必须通过 Browser-use preflight 校验当前 URL、直播间、场景和图层",
            "每次只执行一个小而可验证的 UI 操作，并回写截图或页面状态证据",
        ],
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(clean(value) if value is not None else "" for value in row) + " |")
    return "\n".join(lines)


def render_markdown(profile: dict[str, Any], blueprint: dict[str, Any]) -> str:
    room_name = clean(profile.get("reference_room_name")) or clean(profile.get("reference_room_id"))
    scene_rows = []
    for scene in blueprint.get("scenes", []):
        scene_rows.append(
            [
                scene.get("scene_name"),
                scene.get("scene_type"),
                scene.get("status"),
                "是" if scene.get("reference_active") else "否",
                len(scene.get("layers") or []),
            ]
        )
    active_layers = []
    for scene in blueprint.get("scenes", []):
        active_layers.extend(scene.get("layers") or [])
    layer_rows = [
        [
            layer.get("layer_name"),
            layer.get("layer_role"),
            layer.get("required_category"),
            ", ".join(layer.get("accepted_asset_types") or []),
            layer.get("replacement_policy"),
        ]
        for layer in active_layers
    ]
    script_rows = [
        [block.get("sort_order"), block.get("scene_name"), clean(block.get("content"))[:80]]
        for block in blueprint.get("script_blocks", [])
    ]

    return f"""# 麦兔参考直播间蓝图初稿：{room_name}

## ReferenceRoomProfile

- profile_code: `{profile['profile_code']}`
- source: `{profile['source']}`
- URL: `{profile.get('source_url')}`
- liveRoomId: `{profile.get('reference_room_id')}`
- room_name: `{profile.get('reference_room_name')}`
- platform: `{profile.get('platform') or ''}`
- active_scene: `{profile.get('active_scene_name') or ''}`
- logged_in: `{profile.get('logged_in')}`

## LiveRoomBlueprint

- blueprint_code: `{blueprint['blueprint_code']}`
- room_type: `{blueprint['room_type']}`
- status: `{blueprint['status']}`
- reference_profile_code: `{blueprint['reference_profile_code']}`

## 场景蓝图

{markdown_table(['场景', '类型', '状态', '参考页激活', '已观测图层数'], scene_rows)}

## 当前激活场景图层蓝图

{markdown_table(['图层', '角色', '所需分类', '接受类型', '替换策略'], layer_rows) if layer_rows else '当前 Observe 输出没有图层。'}

## 脚本块

{markdown_table(['序号', '场景', '内容预览'], script_rows) if script_rows else '当前 Observe 输出没有脚本文本。'}

## 安全规则

""" + "\n".join(f"- {rule}" for rule in blueprint.get("safety_rules", [])) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_extract(options: ExtractOptions) -> dict[str, Any]:
    date_stamp = options.date_stamp or today_stamp()
    state = load_observed_state(options.observed_state_path)
    room_id = infer_room_id(state)
    profile = build_reference_profile(state, date_stamp=date_stamp, room_id=room_id)
    blueprint = build_blueprint(profile, date_stamp=date_stamp, room_id=room_id)

    output_dir = options.output_dir
    profile_output = options.profile_output or output_dir / f"reference_room_profile_{room_id}_{date_stamp}.json"
    blueprint_output = options.blueprint_output or output_dir / f"live_room_blueprint_{room_id}_{date_stamp}.json"
    markdown_output = options.markdown_output or output_dir / f"live_room_blueprint_{room_id}_{date_stamp}.md"

    write_json(profile_output, profile)
    write_json(blueprint_output, blueprint)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(render_markdown(profile, blueprint), encoding="utf-8")

    active_layers = profile.get("active_scene_layers", []) if isinstance(profile.get("active_scene_layers"), list) else []
    script_blocks = blueprint.get("script_blocks", []) if isinstance(blueprint.get("script_blocks"), list) else []
    return {
        "reference_room_id": room_id,
        "reference_room_name": profile.get("reference_room_name"),
        "profile_code": profile.get("profile_code"),
        "blueprint_code": blueprint.get("blueprint_code"),
        "scene_count": len(profile.get("scenes", [])),
        "active_scene_layer_count": len(active_layers),
        "script_block_count": len(script_blocks),
        "profile_output": str(profile_output),
        "blueprint_output": str(blueprint_output),
        "markdown_output": str(markdown_output),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Maitu ReferenceRoomProfile and LiveRoomBlueprint from Observe JSON.")
    parser.add_argument("--observed-state", required=True, type=Path, help="Path to browser_use_worker --observe-maitu JSON output")
    parser.add_argument("--output-dir", type=Path, default=Path("docs/asset-numbering"))
    parser.add_argument("--date-stamp", default=None, help="YYYYMMDD stamp for stable artifact codes")
    parser.add_argument("--profile-output", type=Path, default=None)
    parser.add_argument("--blueprint-output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_extract(
        ExtractOptions(
            observed_state_path=args.observed_state,
            output_dir=args.output_dir,
            date_stamp=args.date_stamp,
            profile_output=args.profile_output,
            blueprint_output=args.blueprint_output,
            markdown_output=args.markdown_output,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

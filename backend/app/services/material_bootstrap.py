from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.repositories.assets import AssetRepository


BOOTSTRAP_VERSION = "material-bootstrap-v1"
DIGITAL_HUMAN_LOCAL_CODE = "MAITU-DH-37200"
IGNORED_DIRECTORY_NAMES = frozenset(
    {".asset-preview-cache", ".object-store", "analysis-cache", "__pycache__"}
)
VISUALLY_REVIEWED_CLASSIFICATIONS: dict[str, tuple[str, tuple[str, ...], str, str]] = {
    "MT-DEC-0005": (
        "image",
        ("promotion_text", "decoration_foreground"),
        "visual_promotion_overlay",
        "画面为购物车抽奖促销贴片，应保持完整并位于前景层。",
    ),
    "MT-DEC-0006": (
        "image",
        ("promotion_text", "decoration_foreground"),
        "visual_product_promotion_overlay",
        "画面为品酒大师系列买赠促销贴片，应保持完整并位于前景层。",
    ),
    "MT-DEC-0026": (
        "image",
        ("product_display",),
        "visual_product_cutout",
        "画面为绿幕酒瓶商品主体，应完整放置在桌面区域。",
    ),
    "39598_100029295227": (
        "image",
        ("product_display",),
        "visual_product_cutout",
        "画面为龙谕酒瓶商品主体；虽然文件位于背景目录，但不能误作背景。",
    ),
    "42419_MT-TPL-0001_模版_模板预览_张裕618背景_preview": (
        "image",
        ("background",),
        "visual_composite_background",
        "画面为完整竖屏直播背景合成图，可作为麦兔图片背景执行。",
    ),
}


class MaterialBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MaterialClassification:
    media_kind: str
    roles: tuple[str, ...]
    review_status: str
    confidence: float
    rule_id: str
    explanation: str


@dataclass(frozen=True, slots=True)
class MaterialBootstrapItem:
    asset: dict[str, Any]
    catalog: dict[str, Any]
    source_path: Path
    technical: dict[str, Any]
    classification: MaterialClassification
    constraints: tuple[dict[str, Any], ...]
    inventory_item: dict[str, Any]
    inventory_item_fingerprint: str
    execution_capability: str


@dataclass(frozen=True, slots=True)
class MaterialBootstrapPlan:
    source_revision: str
    observation_path: str
    captured_at: str
    items: tuple[MaterialBootstrapItem, ...]
    digital_human: dict[str, Any]

    @property
    def report_summary(self) -> dict[str, Any]:
        return {
            "catalog_count": len(self.items),
            "asset_match_count": len(self.items),
            "inventory_evidence_match_count": len(self.items),
            "executable_binding_count": sum(
                item.execution_capability == "maitu_bound" for item in self.items
            ),
            "reference_only_count": sum(
                item.execution_capability == "reference_only" for item in self.items
            ),
            "review_required_count": sum(
                item.classification.review_status == "review_required" for item in self.items
            ),
            "digital_human_binding_count": 1,
            "ambiguous_count": 0,
            "unmatched_count": 0,
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_local_media(path: Path, *, timeout_seconds: float = 120.0) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise MaterialBootstrapError(f"ffprobe failed for {path.name}: {result.stderr[-300:]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MaterialBootstrapError(f"ffprobe returned invalid JSON for {path.name}") from exc
    streams = [item for item in payload.get("streams") or [] if isinstance(item, dict)]
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio_count = sum(item.get("codec_type") == "audio" for item in streams)
    format_payload = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration = _optional_positive_float(format_payload.get("duration"))
    if duration is None and video is not None:
        duration = _optional_positive_float(video.get("duration"))
    width = _optional_positive_int(video.get("width")) if video else None
    height = _optional_positive_int(video.get("height")) if video else None
    return {
        "schema_version": "local-material-probe-v1",
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 6) if width and height else None,
        "duration_seconds": round(duration, 6) if duration else None,
        "average_frame_rate": str(video.get("avg_frame_rate") or "") or None if video else None,
        "audio_track_count": audio_count,
        "format_name": str(format_payload.get("format_name") or "") or None,
    }


def infer_classification(catalog: dict[str, Any]) -> MaterialClassification:
    declared_media = str(catalog.get("media_kind") or "").strip().lower()
    local_code = str(catalog.get("file_code") or "").strip()
    visual_review = VISUALLY_REVIEWED_CLASSIFICATIONS.get(local_code)
    if visual_review is not None:
        media_kind, roles, rule_id, explanation = visual_review
        return MaterialClassification(media_kind, roles, "inferred", 0.98, rule_id, explanation)
    text = " ".join(
        str(catalog.get(key) or "")
        for key in ("relative_path", "title", "usage", "subject", "file_role", "maitu_type")
    ).lower()
    if (
        str(catalog.get("maitu_type") or "").strip() == "模版"
        or str(catalog.get("usage") or "").strip() == "模板预览"
        or str(catalog.get("file_role") or "").strip() == "模板预览"
        or "template_preview" in text
    ):
        return MaterialClassification(
            "template_preview", (), "inferred", 0.99, "template_preview", "名称明确标注为模板预览，仅供参考。"
        )
    if declared_media == "video":
        return MaterialClassification(
            "video",
            ("supporting_video",),
            "inferred",
            0.98,
            "product_or_wine_video",
            "视频目录与名称明确标注商品、酒体、开箱、讲解或品牌视频。",
        )
    if "直播背景" in text or "背景-3" in text or "微信图片" in text:
        return MaterialClassification(
            "image", ("background",), "inferred", 0.96, "full_background", "名称明确标注为直播背景。"
        )
    if any(signal in text for signal in ("底部背景", "底背景", "装饰底图", "_底图", "39157_底")):
        return MaterialClassification(
            "image", ("set_surface",), "inferred", 0.94, "set_surface", "名称明确标注为底图、桌面或底部承托面。"
        )
    if any(signal in text for signal in ("品牌logo", "标题+logo", "标题动图", "张裕百年", "头部1")):
        return MaterialClassification(
            "image", ("brand_title",), "inferred", 0.93, "brand_title", "名称明确标注为品牌、Logo、标题或头部。"
        )
    if any(signal in text for signal in ("商品贴片", "礼盒装饰")):
        return MaterialClassification(
            "image", ("product_display",), "inferred", 0.95, "product_display", "名称明确标注为商品贴片或商品礼盒。"
        )
    if any(signal in text for signal in ("买赠贴片", "抽奖", "转盘")):
        return MaterialClassification(
            "image",
            ("promotion_text", "decoration_foreground"),
            "inferred",
            0.90,
            "promotion_overlay",
            "名称明确标注为买赠、抽奖或活动转盘。",
        )
    if "前景框" in text:
        return MaterialClassification(
            "image",
            ("decoration_foreground",),
            "inferred",
            0.96,
            "foreground_frame",
            "名称明确标注为前景框。",
        )
    if "ai贴片" in text or "图标" in text:
        return MaterialClassification(
            "image",
            ("decoration_foreground",),
            "inferred",
            0.78,
            "generic_overlay",
            "名称表明其为图标或贴片，但具体构图仍建议人工确认。",
        )
    return MaterialClassification(
        "image" if declared_media == "image" else declared_media or "image",
        (),
        "review_required",
        0.35,
        "ambiguous_visual",
        "仅凭名称和目录无法可靠判断画面用途，未生成角色和图层猜测。",
    )


def constraints_for(classification: MaterialClassification) -> tuple[dict[str, Any], ...]:
    roles = set(classification.roles)
    preserve = {"kind": "preserve_aspect_ratio", "hard": True, "parameters": {}}
    if "background" in roles:
        return (
            {"kind": "allowed_region", "hard": True, "parameters": {"rect": [0, 0, 1, 1]}},
            preserve,
            {"kind": "crop_policy", "hard": True, "parameters": {"policy": "cover"}},
            {"kind": "pin_layer_bottom", "hard": True, "parameters": {}},
        )
    if "set_surface" in roles:
        return (
            {"kind": "allowed_region", "hard": True, "parameters": {"rect": [0, 0.45, 1, 0.55]}},
            preserve,
            {"kind": "crop_policy", "hard": True, "parameters": {"policy": "contain"}},
            {
                "kind": "provide_named_region",
                "hard": True,
                "parameters": {"region": "table_surface", "rect": [0, 0.45, 1, 0.55]},
            },
            _above("background"),
            _below("product_display"),
            _below("supporting_video"),
            _below("digital_human"),
            _below("brand_title"),
            _below("decoration_foreground"),
        )
    if "supporting_video" in roles:
        return (
            {"kind": "allowed_region", "hard": True, "parameters": {"rect": [0, 0, 1, 1]}},
            preserve,
            {"kind": "crop_policy", "hard": True, "parameters": {"policy": "contain"}},
            _above("background"),
            _above("set_surface"),
            _below("digital_human"),
            _below("brand_title"),
            _below("promotion_text"),
            _below("decoration_foreground"),
            {"kind": "forbid_layer_top", "hard": True, "parameters": {}},
        )
    if "product_display" in roles:
        return (
            {"kind": "allowed_region", "hard": True, "parameters": {"rect": [0.05, 0.40, 0.90, 0.55]}},
            preserve,
            {"kind": "crop_policy", "hard": True, "parameters": {"policy": "contain"}},
            {"kind": "require_named_region", "hard": True, "parameters": {"region": "table_surface"}},
            _above("background"),
            _above("set_surface"),
            _below("digital_human"),
            _below("brand_title"),
            _below("decoration_foreground"),
        )
    if "digital_human" in roles:
        return (
            {"kind": "allowed_region", "hard": True, "parameters": {"rect": [0, 0.08, 1, 0.92]}},
            preserve,
            _above("background"),
            _above("set_surface"),
            _above("supporting_video"),
            _above("product_display"),
            _below("brand_title"),
            _below("promotion_text"),
            _below("decoration_foreground"),
        )
    if roles.intersection({"brand_title", "promotion_text", "decoration_foreground"}):
        return (
            {"kind": "allowed_region", "hard": True, "parameters": {"rect": [0, 0, 1, 1]}},
            preserve,
            {"kind": "crop_policy", "hard": True, "parameters": {"policy": "contain"}},
            {"kind": "pin_layer_top", "hard": True, "parameters": {}},
        )
    return (preserve,) if classification.media_kind in {"image", "video"} else ()


def build_bootstrap_plan(
    *,
    catalog_assets: Iterable[dict[str, Any]],
    database_assets: Iterable[dict[str, Any]],
    observation: dict[str, Any],
    observation_path: Path,
    assets_root: Path,
    probe: Callable[[Path], dict[str, Any]] = probe_local_media,
    checksum: Callable[[Path], str] = sha256_file,
    expected_count: int = 63,
) -> MaterialBootstrapPlan:
    catalog = [dict(item) for item in catalog_assets]
    if len(catalog) != expected_count:
        raise MaterialBootstrapError(f"expected {expected_count} catalog assets, found {len(catalog)}")
    _validate_observation(observation)
    inventory_items = [dict(item) for item in observation["items"]]
    inventory_by_code: dict[str, list[dict[str, Any]]] = {}
    inventory_by_checksum: dict[str, list[dict[str, Any]]] = {}
    for item in inventory_items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        code = str(metadata.get("local_file_code") or "").strip()
        if code:
            inventory_by_code.setdefault(code, []).append(item)
        checksum_value = str(item.get("checksum_sha256") or "").strip().lower()
        if len(checksum_value) == 64:
            inventory_by_checksum.setdefault(checksum_value, []).append(item)
    db_by_code: dict[str, list[dict[str, Any]]] = {}
    for asset in database_assets:
        code = str(asset.get("local_file_code") or "").strip()
        if code:
            db_by_code.setdefault(code, []).append(dict(asset))

    base_rows: list[tuple[dict[str, Any], dict[str, Any], Path, dict[str, Any], MaterialClassification, dict[str, Any]]] = []
    root = assets_root.expanduser().resolve()
    for item in catalog:
        code = str(item.get("file_code") or "").strip()
        if not code:
            raise MaterialBootstrapError("catalog asset has no file_code")
        asset_matches = db_by_code.get(code, [])
        if len(asset_matches) != 1:
            raise MaterialBootstrapError(f"asset identity for {code} is {'missing' if not asset_matches else 'ambiguous'}")
        expected_checksum = str(item.get("sha256") or "").lower()
        inventory_matches = inventory_by_code.get(code, [])
        is_template_preview = (
            str(item.get("maitu_type") or "").strip() == "模版"
            or "模板预览" in str(item.get("usage") or "")
            or "template_preview" in str(item.get("file_role") or "").lower()
        )
        inventory_matches = [
            match
            for match in inventory_matches
            if (str(match.get("material_type") or "") == "template") == is_template_preview
        ]
        if not inventory_matches and len(expected_checksum) == 64:
            inventory_matches = [
                match
                for match in inventory_by_checksum.get(expected_checksum, [])
                if (str(match.get("material_type") or "") == "template") == is_template_preview
            ]
        if len(inventory_matches) != 1:
            raise MaterialBootstrapError(
                f"inventory evidence for {code} is {'missing' if not inventory_matches else 'ambiguous'}"
            )
        relative = _safe_relative_path(item.get("relative_path"))
        source_path = (root / Path(*relative.parts)).resolve()
        try:
            source_path.relative_to(root)
        except ValueError as exc:
            raise MaterialBootstrapError(f"catalog path escapes assets root for {code}") from exc
        if not source_path.is_file():
            raise MaterialBootstrapError(f"local source file is missing for {code}")
        actual_checksum = checksum(source_path)
        asset_checksum = str(asset_matches[0].get("checksum_sha256") or "").lower()
        evidence_checksum = str(inventory_matches[0].get("checksum_sha256") or "").lower()
        if not expected_checksum or len(expected_checksum) != 64:
            raise MaterialBootstrapError(f"catalog checksum is missing for {code}")
        if actual_checksum != expected_checksum or asset_checksum != expected_checksum:
            raise MaterialBootstrapError(f"local/database checksum mismatch for {code}")
        if evidence_checksum and evidence_checksum != expected_checksum:
            raise MaterialBootstrapError(f"inventory evidence checksum mismatch for {code}")
        technical = probe(source_path)
        base_rows.append(
            (
                asset_matches[0],
                item,
                source_path,
                technical,
                infer_classification(item),
                inventory_matches[0],
            )
        )

    confident_by_checksum: dict[str, MaterialClassification] = {}
    for _asset, catalog_item, _path, _technical, classification, _inventory in base_rows:
        if classification.review_status != "review_required":
            confident_by_checksum.setdefault(str(catalog_item["sha256"]), classification)

    planned: list[MaterialBootstrapItem] = []
    for asset, catalog_item, source_path, technical, classification, inventory_item in base_rows:
        alias = confident_by_checksum.get(str(catalog_item["sha256"]))
        if classification.review_status == "review_required" and alias is not None:
            classification = MaterialClassification(
                alias.media_kind,
                alias.roles,
                "inferred",
                min(alias.confidence, 0.90),
                f"checksum_alias:{alias.rule_id}",
                "文件 checksum 与已明确分类的素材完全一致，沿用其用途；仍保留推断证据。",
            )
        material_type = str(inventory_item.get("material_type") or "")
        capability = "reference_only" if material_type == "template" else "maitu_bound"
        if capability == "maitu_bound" and material_type not in {"image", "video", "decorative_video"}:
            raise MaterialBootstrapError(
                f"inventory evidence for {catalog_item['file_code']} has unsupported type {material_type}"
            )
        planned.append(
            MaterialBootstrapItem(
                asset=asset,
                catalog=catalog_item,
                source_path=source_path,
                technical=technical,
                classification=classification,
                constraints=constraints_for(classification),
                inventory_item=inventory_item,
                inventory_item_fingerprint=fingerprint(inventory_item),
                execution_capability=capability,
            )
        )

    digital_human = _find_digital_human(inventory_items, material_id=37200, image_id=7717, speaker_id=3760)
    return MaterialBootstrapPlan(
        source_revision=str(observation["source_revision"]),
        observation_path=str(observation_path.expanduser().resolve()),
        captured_at=str(observation.get("captured_at") or datetime.now(UTC).isoformat()),
        items=tuple(sorted(planned, key=lambda value: str(value.asset["asset_code"]))),
        digital_human=digital_human,
    )


def apply_bootstrap_plan(connection: Connection, plan: MaterialBootstrapPlan) -> dict[str, Any]:
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            for item in plan.items:
                _apply_material_item(cursor, item, plan)
            digital_human_asset_code = _apply_digital_human(cursor, connection, plan)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return build_report(plan, mode="apply", digital_human_asset_code=digital_human_asset_code)


def build_report(
    plan: MaterialBootstrapPlan,
    *,
    mode: str,
    digital_human_asset_code: str | None = None,
) -> dict[str, Any]:
    input_manifest = {
        "bootstrap_version": BOOTSTRAP_VERSION,
        "source_revision": plan.source_revision,
        "digital_human_inventory_fingerprint": fingerprint(plan.digital_human),
        "materials": [
            {
                "asset_code": str(item.asset["asset_code"]),
                "local_file_code": str(item.catalog["file_code"]),
                "checksum_sha256": str(item.catalog["sha256"]),
                "inventory_item_fingerprint": item.inventory_item_fingerprint,
            }
            for item in plan.items
        ],
    }
    return {
        "schema_version": "material-bootstrap-report-v1",
        "mode": mode,
        "bootstrap_version": BOOTSTRAP_VERSION,
        # Deliberately excludes timestamps and host-local paths so another worker can
        # reproduce the same identity from the same catalog and inventory evidence.
        "input_fingerprint": fingerprint(input_manifest),
        "input_manifest": input_manifest,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_revision": plan.source_revision,
        "observation_path": plan.observation_path,
        "summary": plan.report_summary,
        "digital_human": {
            "asset_code": digital_human_asset_code,
            "maitu_source_material_id": int(plan.digital_human["material_id"]),
            "digital_human_image_id": int(plan.digital_human["digital_human_image_id"]),
            "speaker_id": int(plan.digital_human["speaker_id"]),
            "inventory_item_fingerprint": fingerprint(plan.digital_human),
        },
        "items": [
            {
                "asset_code": str(item.asset["asset_code"]),
                "local_file_code": str(item.catalog["file_code"]),
                "relative_path": str(item.catalog["relative_path"]),
                "checksum_sha256": str(item.catalog["sha256"]),
                "media_kind": item.classification.media_kind,
                "material_roles": list(item.classification.roles),
                "classification_review_status": item.classification.review_status,
                "classification_confidence": item.classification.confidence,
                "classification_rule": item.classification.rule_id,
                "classification_explanation": item.classification.explanation,
                "execution_capability": item.execution_capability,
                "maitu_material_id": _optional_positive_int(item.inventory_item.get("material_id")),
                "inventory_item_fingerprint": item.inventory_item_fingerprint,
                "technical": item.technical,
                "constraint_count": len(item.constraints),
                "constraint_fingerprint": fingerprint(list(item.constraints)),
                "rights_status_unchanged": str(item.asset.get("rights_status") or "pending"),
                "before": _material_state_before(item),
                "after": _material_state_after(item),
            }
            for item in plan.items
        ],
    }


def _material_state_before(item: MaterialBootstrapItem) -> dict[str, Any]:
    return {
        "media_kind": item.asset.get("media_kind"),
        "material_roles": list(item.asset.get("material_roles") or []),
        "classification_review_status": item.asset.get("classification_review_status"),
        "classification_confidence": (
            float(item.asset["classification_confidence"])
            if item.asset.get("classification_confidence") is not None
            else None
        ),
        "classification_fingerprint": item.asset.get("classification_fingerprint"),
        "execution_capability": item.asset.get("execution_capability"),
        "rights_status": str(item.asset.get("rights_status") or "pending"),
        "maitu_material_id": _optional_positive_int(item.asset.get("maitu_material_id")),
        "maitu_source_material_id": _optional_positive_int(
            item.asset.get("maitu_source_material_id")
        ),
        "maitu_binding_verification_source": item.asset.get(
            "maitu_binding_verification_source"
        ),
        "maitu_binding_inventory_fingerprint": item.asset.get(
            "maitu_binding_inventory_fingerprint"
        ),
    }


def _material_state_after(item: MaterialBootstrapItem) -> dict[str, Any]:
    material_id = _optional_positive_int(item.inventory_item.get("material_id"))
    return {
        "media_kind": item.classification.media_kind,
        "material_roles": list(item.classification.roles),
        "classification_review_status": item.classification.review_status,
        "classification_confidence": item.classification.confidence,
        "execution_capability": item.execution_capability,
        "rights_status": str(item.asset.get("rights_status") or "pending"),
        "maitu_material_id": material_id,
        "maitu_source_material_id": material_id,
        "maitu_binding_verification_source": (
            "worker_maitu_inventory_readback" if material_id else None
        ),
        "maitu_binding_inventory_fingerprint": (
            item.inventory_item_fingerprint if material_id else None
        ),
        "constraint_fingerprint": fingerprint(list(item.constraints)),
    }


def load_catalog(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise MaterialBootstrapError("material catalog has an invalid schema")
    return [dict(row) for row in rows]


def load_inventory_observation(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise MaterialBootstrapError("inventory observation must be a regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MaterialBootstrapError("inventory observation is not an object")
    _validate_observation(payload)
    return payload


def list_database_material_assets(connection: Connection) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT * FROM assets
               WHERE local_file_code IS NOT NULL AND deleted_at IS NULL
               ORDER BY asset_code"""
        )
        return [dict(row) for row in cursor.fetchall()]


def _apply_material_item(cursor: Any, item: MaterialBootstrapItem, plan: MaterialBootstrapPlan) -> None:
    classification_evidence = {
        "source": "deterministic_local_bootstrap",
        "bootstrap_version": BOOTSTRAP_VERSION,
        "rule_id": item.classification.rule_id,
        "explanation": item.classification.explanation,
        "local_file_code": item.catalog["file_code"],
        "relative_path": item.catalog["relative_path"],
        "checksum_sha256": item.catalog["sha256"],
        "technical": item.technical,
    }
    classification_fingerprint = fingerprint(
        {
            "media_kind": item.classification.media_kind,
            "material_roles": item.classification.roles,
            "review_status": item.classification.review_status,
            "confidence": item.classification.confidence,
            "evidence": classification_evidence,
        }
    )
    inventory = item.inventory_item
    inventory_metadata = (
        inventory.get("metadata") if isinstance(inventory.get("metadata"), dict) else {}
    )
    matched_by = ["checksum_sha256", "material_type"]
    if str(inventory_metadata.get("local_file_code") or "").strip() == str(
        item.catalog["file_code"]
    ):
        matched_by.insert(0, "local_file_code")
    binding_evidence = {
        "source": "worker_maitu_inventory_readback",
        "observation_path": plan.observation_path,
        "source_revision": plan.source_revision,
        "captured_at": plan.captured_at,
        "item_key": inventory.get("item_key"),
        "item_fingerprint": item.inventory_item_fingerprint,
        "matched_by": matched_by,
    }
    material_id = _optional_positive_int(inventory.get("material_id"))
    cursor.execute(
        """UPDATE assets
           SET media_kind = %s, material_roles = %s,
               classification_review_status = %s, classification_confidence = %s,
               classification_evidence = %s, classification_fingerprint = %s,
               execution_capability = %s,
               maitu_material_id = %s, maitu_source_material_id = %s,
               source_material_type = %s, source_material_url = %s, source_cover_url = %s,
               speaker_id = NULL, digital_human_image_id = NULL,
               maitu_binding_verification_source = %s, maitu_binding_verified_at = %s,
               maitu_binding_scope = %s, maitu_binding_inventory_fingerprint = %s,
               maitu_binding_readback_nonce = NULL, maitu_binding_attestation = NULL,
               maitu_binding_evidence = %s, updated_at = now()
           WHERE id = %s AND deleted_at IS NULL""",
        (
            item.classification.media_kind,
            Jsonb(list(item.classification.roles)),
            item.classification.review_status,
            item.classification.confidence,
            Jsonb(classification_evidence),
            classification_fingerprint,
            item.execution_capability,
            material_id,
            material_id,
            None if item.execution_capability == "reference_only" else inventory.get("material_type"),
            inventory.get("source_material_url"),
            inventory.get("source_cover_url"),
            "worker_maitu_inventory_readback" if material_id else None,
            plan.captured_at if material_id else None,
            "assetgraph_test_draft_material_binding_v1" if material_id else None,
            item.inventory_item_fingerprint if material_id else None,
            Jsonb(binding_evidence if material_id else {}),
            item.asset["id"],
        ),
    )
    if cursor.rowcount != 1:
        raise MaterialBootstrapError(f"asset disappeared while applying {item.asset['asset_code']}")
    cursor.execute(
        """INSERT INTO asset_files
           (asset_id, asset_code, file_role, bucket_name, object_key, mime_type,
            file_size, checksum_sha256, width, height, duration_seconds,
            source_relative_path, local_file_code, storage_status)
           VALUES (%s, %s, 'original', 'local-materials', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'local_reference')
           ON CONFLICT (asset_id, file_role) DO UPDATE SET
             bucket_name = EXCLUDED.bucket_name, object_key = EXCLUDED.object_key,
             mime_type = EXCLUDED.mime_type, file_size = EXCLUDED.file_size,
             checksum_sha256 = EXCLUDED.checksum_sha256, width = EXCLUDED.width,
             height = EXCLUDED.height, duration_seconds = EXCLUDED.duration_seconds,
             source_relative_path = EXCLUDED.source_relative_path,
             local_file_code = EXCLUDED.local_file_code,
             storage_status = EXCLUDED.storage_status""",
        (
            item.asset["id"],
            item.asset["asset_code"],
            item.catalog["relative_path"],
            item.catalog.get("mime_type"),
            int(item.catalog["file_size"]),
            item.catalog["sha256"],
            item.technical.get("width"),
            item.technical.get("height"),
            item.technical.get("duration_seconds"),
            item.catalog["relative_path"],
            item.catalog["file_code"],
        ),
    )
    _upsert_constraint_profile(cursor, item.asset, item.constraints)


def _apply_digital_human(cursor: Any, connection: Connection, plan: MaterialBootstrapPlan) -> str:
    cursor.execute(
        """SELECT * FROM assets
           WHERE source_system = 'maitu_inventory' AND local_file_code = %s
             AND deleted_at IS NULL FOR UPDATE""",
        (DIGITAL_HUMAN_LOCAL_CODE,),
    )
    asset = cursor.fetchone()
    if asset is None:
        repository = AssetRepository(connection)
        asset = repository.create(
            {
                "asset_type": "VID",
                "title": str(plan.digital_human.get("title") or "张裕数字人"),
                "original_filename": "maitu-native-digital-human-37200",
                "status": "stored",
                "media_kind": "digital_human",
                "material_roles": ["digital_human", "voice"],
                "execution_capability": "local_only",
                "rights_status": "pending",
                "classification_review_status": "inferred",
                "classification_confidence": 1.0,
                "classification_evidence": {"source": "worker_maitu_inventory_readback"},
                "display_code": DIGITAL_HUMAN_LOCAL_CODE,
                "local_file_code": DIGITAL_HUMAN_LOCAL_CODE,
                "entity_code": "MAITU-DH-37200",
                "source_system": "maitu_inventory",
                "source_type": "maitu_native_digital_human",
                "maitu_category": "digital_human_video",
            },
            commit=False,
        )
    digital_fingerprint = fingerprint(plan.digital_human)
    source_material_id = int(plan.digital_human["material_id"])
    evidence = {
        "source": "worker_maitu_inventory_readback",
        "observation_path": plan.observation_path,
        "source_revision": plan.source_revision,
        "captured_at": plan.captured_at,
        "item_key": plan.digital_human["item_key"],
        "item_fingerprint": digital_fingerprint,
        "matched_by": ["material_id", "digital_human_image_id", "speaker_id"],
    }
    classification_evidence = {
        "source": "worker_maitu_inventory_readback",
        "explanation": "麦兔 inventory 明确返回数字人、形象和音色的复合身份。",
        **evidence,
    }
    cursor.execute(
        """UPDATE assets
           SET media_kind = 'digital_human', material_roles = %s,
               classification_review_status = 'inferred', classification_confidence = 1,
               classification_evidence = %s, classification_fingerprint = %s,
               execution_capability = 'maitu_bound', maitu_material_id = NULL,
               maitu_source_material_id = %s, source_material_type = 'digital_human',
               source_material_url = NULL, source_cover_url = %s,
               speaker_id = %s, digital_human_image_id = %s,
               maitu_binding_verification_source = 'worker_maitu_inventory_readback',
               maitu_binding_verified_at = %s,
               maitu_binding_scope = 'assetgraph_test_draft_material_binding_v1',
               maitu_binding_inventory_fingerprint = %s,
               maitu_binding_readback_nonce = NULL, maitu_binding_attestation = NULL,
               maitu_binding_evidence = %s, updated_at = now()
           WHERE id = %s""",
        (
            Jsonb(["digital_human", "voice"]),
            Jsonb(classification_evidence),
            fingerprint(
                {
                    "media_kind": "digital_human",
                    "material_roles": ["digital_human", "voice"],
                    "review_status": "inferred",
                    "confidence": 1.0,
                    "evidence": classification_evidence,
                }
            ),
            source_material_id,
            plan.digital_human.get("source_cover_url") or plan.digital_human.get("source_material_url"),
            int(plan.digital_human["speaker_id"]),
            int(plan.digital_human["digital_human_image_id"]),
            plan.captured_at,
            digital_fingerprint,
            Jsonb(evidence),
            asset["id"],
        ),
    )
    _upsert_constraint_profile(
        cursor,
        asset,
        constraints_for(
            MaterialClassification(
                "digital_human", ("digital_human", "voice"), "inferred", 1.0, "maitu_digital_human", ""
            )
        ),
    )
    return str(asset["asset_code"])


def _upsert_constraint_profile(
    cursor: Any,
    asset: dict[str, Any],
    constraints: tuple[dict[str, Any], ...],
) -> None:
    canonical = canonical_json(list(constraints))
    rules_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    profile_code = f"AG-CP-{asset['asset_code']}"
    cursor.execute(
        """INSERT INTO asset_constraint_profiles
           (profile_code, asset_id, asset_code, current_revision)
           VALUES (%s, %s, %s, 0)
           ON CONFLICT (asset_id) DO NOTHING""",
        (profile_code, asset["id"], asset["asset_code"]),
    )
    cursor.execute(
        "SELECT * FROM asset_constraint_profiles WHERE asset_id = %s FOR UPDATE",
        (asset["id"],),
    )
    profile = cursor.fetchone()
    current_revision = int(profile["current_revision"])
    if current_revision:
        cursor.execute(
            """SELECT fingerprint_sha256 FROM asset_constraint_profile_revisions
               WHERE profile_id = %s AND revision_number = %s""",
            (profile["id"], current_revision),
        )
        current = cursor.fetchone()
        if current and str(current["fingerprint_sha256"]) == rules_fingerprint:
            return
    next_revision = current_revision + 1
    cursor.execute(
        """INSERT INTO asset_constraint_profile_revisions
           (profile_id, revision_number, constraints, fingerprint_sha256, created_by, change_reason)
           VALUES (%s, %s, %s, %s, 'material-bootstrap', %s)""",
        (
            profile["id"],
            next_revision,
            Jsonb(list(constraints)),
            rules_fingerprint,
            f"{BOOTSTRAP_VERSION}: deterministic material role constraints",
        ),
    )
    cursor.execute(
        "UPDATE asset_constraint_profiles SET current_revision = %s, updated_at = now() WHERE id = %s",
        (next_revision, profile["id"]),
    )


def _validate_observation(observation: dict[str, Any]) -> None:
    if observation.get("schema_version") != "maitu-inventory-observation-v1":
        raise MaterialBootstrapError("unsupported inventory observation schema")
    if observation.get("quality_status") != "complete":
        raise MaterialBootstrapError("inventory observation is not complete")
    items = observation.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise MaterialBootstrapError("inventory observation items are invalid")
    actual_revision = fingerprint(items)
    if str(observation.get("source_revision") or "") != actual_revision:
        raise MaterialBootstrapError("inventory observation source revision does not match its items")


def _find_digital_human(
    items: Iterable[dict[str, Any]],
    *,
    material_id: int,
    image_id: int,
    speaker_id: int,
) -> dict[str, Any]:
    matches = [
        item
        for item in items
        if str(item.get("material_type") or "") == "digital_human"
        and _optional_positive_int(item.get("material_id")) == material_id
        and _optional_positive_int(item.get("digital_human_image_id")) == image_id
        and _optional_positive_int(item.get("speaker_id")) == speaker_id
    ]
    if len(matches) != 1:
        raise MaterialBootstrapError("digital-human inventory identity is missing or ambiguous")
    return dict(matches[0])


def _safe_relative_path(value: Any) -> PurePosixPath:
    relative = PurePosixPath(str(value or "").replace("\\", "/"))
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or any(part in IGNORED_DIRECTORY_NAMES or part.startswith(".asset-") for part in relative.parts)
    ):
        raise MaterialBootstrapError("catalog contains an unsafe or cache path")
    return relative


def _above(role: str) -> dict[str, Any]:
    return {
        "kind": "above_role",
        "hard": True,
        "parameters": {"role": role, "when_present": True},
    }


def _below(role: str) -> dict[str, Any]:
    return {
        "kind": "below_role",
        "hard": True,
        "parameters": {"role": role, "when_present": True},
    }


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

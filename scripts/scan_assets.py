#!/usr/bin/env python3
"""Scan local Maitu media files into an AssetGraph import inventory.

The scanner is intentionally filesystem-first: it does not mutate files and does
not require database access.  It turns the Browser-use-friendly local naming
scheme into structured metadata that can later be imported into AssetGraph.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
DOCUMENT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".docx", ".pdf", ".srt", ".ass", ".vtt"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
IGNORED_DIR_NAMES = {"_非素材文件归档", "__pycache__"}

DH_CODE_RE = re.compile(r"^(?P<file_code>DH-(?P<entity>AVT|MDL|VOI)-(?P<seq>\d{4})-F(?P<file_seq>\d{3}))_")
MT_CODE_RE = re.compile(r"^(?P<file_code>MT-(?P<entity>BG|DEC|VID|TPL)-(?P<seq>\d{4}))_")

DH_KNOWN_ROLES = (
    "成品预览视频",
    "训练素材封面",
    "完整预览视频",
    "口型对比视频",
    "训练合成视频",
    "成品封面",
    "模特封面",
    "分段封面",
    "训练素材",
    "预览视频",
    "音色封面",
    "试听音频",
    "训练音频",
)

MT_PREFIX_TO_TYPE = {
    "BG": "背景",
    "DEC": "装饰",
    "VID": "视频",
    "TPL": "模版",
}

DH_PREFIX_TO_SUBTYPE = {
    "AVT": "数字分身成品",
    "MDL": "模特",
    "VOI": "音色",
}

MAITU_TYPE_TO_CATEGORY = {
    ("背景", "image"): "background_image",
    ("背景", "video"): "background_video",
    ("装饰", "image"): "floating_sticker",
    ("装饰", "video"): "floating_sticker",
    ("装饰", "audio"): None,
    ("视频", "video"): "product_video",
    ("视频", "image"): "product_image",
    ("模版", "image"): "background_image",
    ("模版", "video"): "background_video",
    ("数字分身", "video"): "digital_human_video",
    ("数字分身", "image"): "digital_human_video",
    ("数字分身", "audio"): "voice_audio",
}

PRODUCT_KEYWORDS = (
    "品酒大师",
    "PRO",
    "MASTER",
    "SUPER",
    "PLUS",
    "张裕",
    "解百纳",
    "龙谕",
    "龙8",
    "龙12",
    "N158",
    "1937",
    "多名利",
    "单一园",
    "礼盒",
    "明月",
)

CSV_COLUMNS = [
    "file_code",
    "entity_code",
    "asset_type",
    "media_kind",
    "maitu_type",
    "maitu_subtype",
    "maitu_category",
    "usage",
    "subject",
    "file_role",
    "title",
    "relative_path",
    "filename",
    "file_ext",
    "mime_type",
    "file_size",
    "sha256",
    "tags",
    "browser_use_hint",
    "duplicate_group",
    "duplicate_rank",
    "duplicate_count",
    "duplicate_primary_relative_path",
    "is_duplicate_primary",
    "parse_status",
    "parse_issue",
]


@dataclass(slots=True)
class AssetInventoryItem:
    file_code: str
    entity_code: str | None
    asset_type: str
    media_kind: str
    maitu_type: str | None
    maitu_subtype: str | None
    maitu_category: str | None
    usage: str | None
    subject: str | None
    file_role: str | None
    title: str
    relative_path: str
    absolute_path: str
    filename: str
    file_ext: str
    mime_type: str | None
    file_size: int
    sha256: str
    tags: list[str]
    browser_use_hint: str
    source_type: str
    replacement_policy: str
    duplicate_group: str | None = None
    duplicate_rank: int | None = None
    duplicate_count: int | None = None
    duplicate_primary_relative_path: str | None = None
    is_duplicate_primary: bool = False
    parse_status: str = "parsed"
    parse_issue: str | None = None

    def to_asset_create_payload(self) -> dict[str, object]:
        description_parts = [
            f"local_file_code={self.file_code}",
            f"maitu_type={self.maitu_type or ''}",
            f"usage={self.usage or ''}",
            f"subject={self.subject or ''}",
            f"file_role={self.file_role or ''}",
            f"relative_path={self.relative_path}",
        ]
        payload: dict[str, object] = {
            "asset_type": self.asset_type,
            "title": self.title,
            "original_filename": self.filename,
            "file_ext": self.file_ext,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "checksum_sha256": self.sha256,
            "status": "stored",
            "source_type": self.source_type,
            "description": "; ".join(description_parts),
            "replacement_policy": self.replacement_policy,
        }
        if self.maitu_category is not None:
            payload["maitu_category"] = self.maitu_category
        return payload

    def to_json_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["asset_create_payload"] = self.to_asset_create_payload()
        return data

    def to_csv_row(self) -> dict[str, object]:
        data = asdict(self)
        data["tags"] = ",".join(self.tags)
        return {column: data.get(column) for column in CSV_COLUMNS}


def media_kind_for_extension(extension: str) -> str:
    ext = extension.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "other"


def asset_type_for_media_kind(media_kind: str) -> str:
    return {
        "image": "IMG",
        "video": "VID",
        "audio": "AUD",
        "document": "DOC",
    }.get(media_kind, "OTH")


def stable_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def should_ignore(path: Path) -> bool:
    return any(part in IGNORED_DIR_NAMES for part in path.parts)


def iter_media_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in MEDIA_EXTENSIONS
            and not should_ignore(path)
        ),
        key=lambda item: item.as_posix().casefold(),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dh_stem(stem: str) -> tuple[str, str, str | None, str | None, str | None, str, str | None]:
    match = DH_CODE_RE.match(stem)
    if not match:
        return stem, "", None, None, None, "unparsed", "missing DH code prefix"

    file_code = match.group("file_code")
    entity_code = file_code.rsplit("-F", 1)[0]
    maitu_subtype = DH_PREFIX_TO_SUBTYPE[match.group("entity")]
    rest = stem[len(file_code) + 1 :]
    parts = rest.split("_")
    if not parts or parts[0] != maitu_subtype:
        return file_code, entity_code, "数字分身", maitu_subtype, None, "partial", "DH subtype segment mismatch"

    subject_and_role = "_".join(parts[1:])
    role = None
    subject = subject_and_role or None
    for candidate in sorted(DH_KNOWN_ROLES, key=len, reverse=True):
        suffix = f"_{candidate}"
        if subject_and_role.endswith(suffix):
            role = candidate
            subject = subject_and_role[: -len(suffix)] or None
            break
        if subject_and_role == candidate:
            role = candidate
            subject = None
            break
    if role is None and len(parts) >= 3:
        role = parts[-1]
        subject = "_".join(parts[1:-1]) or None

    return file_code, entity_code, "数字分身", maitu_subtype, subject, "parsed", None


def parse_mt_stem(stem: str) -> tuple[str, str | None, str | None, str | None, str | None, str, str | None]:
    match = MT_CODE_RE.match(stem)
    if not match:
        return stem, None, None, None, None, "unparsed", "missing MT code prefix"

    file_code = match.group("file_code")
    maitu_type = MT_PREFIX_TO_TYPE[match.group("entity")]
    rest = stem[len(file_code) + 1 :]
    parts = rest.split("_")
    if len(parts) < 3:
        return file_code, None, maitu_type, None, None, "partial", "MT filename needs type_usage_subject"
    if parts[0] != maitu_type:
        return file_code, None, maitu_type, parts[1] if len(parts) > 1 else None, None, "partial", "MT type segment mismatch"
    usage = parts[1]
    subject = "_".join(parts[2:]) or None
    return file_code, None, maitu_type, usage, subject, "parsed", None


def parse_filename(path: Path, media_kind: str) -> dict[str, str | None]:
    stem = path.stem
    if stem.startswith("DH-"):
        file_code, entity_code, maitu_type, maitu_subtype, subject, status, issue = parse_dh_stem(stem)
        file_role = None
        for candidate in sorted(DH_KNOWN_ROLES, key=len, reverse=True):
            if stem.endswith(f"_{candidate}") or stem == candidate:
                file_role = candidate
                break
        if file_role is None:
            parts = stem.split("_")
            file_role = parts[-1] if len(parts) >= 4 else None
        return {
            "file_code": file_code,
            "entity_code": entity_code,
            "maitu_type": maitu_type,
            "maitu_subtype": maitu_subtype,
            "usage": media_kind_to_chinese(media_kind),
            "subject": subject,
            "file_role": file_role,
            "parse_status": status,
            "parse_issue": issue,
        }
    if stem.startswith("MT-"):
        file_code, entity_code, maitu_type, usage, subject, status, issue = parse_mt_stem(stem)
        return {
            "file_code": file_code,
            "entity_code": entity_code,
            "maitu_type": maitu_type,
            "maitu_subtype": None,
            "usage": usage,
            "subject": subject,
            "file_role": usage,
            "parse_status": status,
            "parse_issue": issue,
        }
    return {
        "file_code": stem,
        "entity_code": None,
        "maitu_type": None,
        "maitu_subtype": None,
        "usage": media_kind_to_chinese(media_kind),
        "subject": stem,
        "file_role": None,
        "parse_status": "unparsed",
        "parse_issue": "unknown code prefix",
    }


def media_kind_to_chinese(media_kind: str) -> str:
    return {"image": "图片", "video": "视频", "audio": "音频", "document": "文档"}.get(media_kind, "其他")


def category_for(maitu_type: str | None, media_kind: str, usage: str | None, file_role: str | None) -> str | None:
    if maitu_type == "数字分身" and (usage == "音频" or file_role in {"试听音频", "训练音频"}):
        return "voice_audio"
    return MAITU_TYPE_TO_CATEGORY.get((maitu_type or "", media_kind))


def build_tags(*values: str | None) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        for token in re.split(r"[\s_,，/\\\-()（）]+", value):
            token = token.strip()
            if not token:
                continue
            if token not in seen:
                tags.append(token)
                seen.add(token)
    combined = " ".join(value for value in values if value)
    for keyword in PRODUCT_KEYWORDS:
        if keyword in combined and keyword not in seen:
            tags.append(keyword)
            seen.add(keyword)
    return tags


def build_title(maitu_type: str | None, usage: str | None, subject: str | None, file_role: str | None) -> str:
    components = [component for component in (maitu_type, usage, subject, file_role) if component]
    if not components:
        return "未解析素材"
    compact: list[str] = []
    for component in components:
        if component not in compact:
            compact.append(component)
    return " - ".join(compact)


def build_browser_use_hint(maitu_type: str | None, usage: str | None, subject: str | None, file_role: str | None) -> str:
    if maitu_type == "数字分身":
        subtype = file_role or usage or "素材"
        return f"用于麦兔数字分身相关选择：{subject or '未命名主体'}，角色：{subtype}"
    if maitu_type:
        return f"用于麦兔{maitu_type}素材选择：{subject or '未命名主体'}，用途：{usage or '未标注用途'}"
    return f"未解析素材，可按文件名人工复核：{subject or ''}"


def scan_assets(root: Path | str) -> list[AssetInventoryItem]:
    assets_root = Path(root).resolve()
    if not assets_root.exists():
        raise FileNotFoundError(f"assets root does not exist: {assets_root}")

    items: list[AssetInventoryItem] = []
    for path in iter_media_files(assets_root):
        relative_path = stable_relative_path(path, assets_root)
        extension = path.suffix.lower()
        media_kind = media_kind_for_extension(extension)
        asset_type = asset_type_for_media_kind(media_kind)
        parsed = parse_filename(path, media_kind)
        maitu_type = parsed["maitu_type"]
        usage = parsed["usage"]
        subject = parsed["subject"]
        file_role = parsed["file_role"]
        maitu_category = category_for(maitu_type, media_kind, usage, file_role)
        title = build_title(maitu_type, usage, subject, file_role)
        tags = build_tags(maitu_type, parsed["maitu_subtype"], usage, subject, file_role)
        mime_type = mimetypes.guess_type(path.name)[0]
        item = AssetInventoryItem(
            file_code=parsed["file_code"] or path.stem,
            entity_code=parsed["entity_code"],
            asset_type=asset_type,
            media_kind=media_kind,
            maitu_type=maitu_type,
            maitu_subtype=parsed["maitu_subtype"],
            maitu_category=maitu_category,
            usage=usage,
            subject=subject,
            file_role=file_role,
            title=title,
            relative_path=relative_path,
            absolute_path=path.as_posix(),
            filename=path.name,
            file_ext=extension,
            mime_type=mime_type,
            file_size=path.stat().st_size,
            sha256=sha256_file(path),
            tags=tags,
            browser_use_hint=build_browser_use_hint(maitu_type, usage, subject, file_role),
            source_type="maitu_local_material",
            replacement_policy="keep_layout",
            parse_status=parsed["parse_status"] or "unparsed",
            parse_issue=parsed["parse_issue"],
        )
        items.append(item)

    annotate_duplicates(items)
    return items


def annotate_duplicates(items: Sequence[AssetInventoryItem]) -> None:
    by_hash: dict[str, list[AssetInventoryItem]] = defaultdict(list)
    for item in items:
        by_hash[item.sha256].append(item)

    duplicate_groups = [group for group in by_hash.values() if len(group) > 1]
    duplicate_groups.sort(key=lambda group: min(item.relative_path.casefold() for item in group))
    for index, group in enumerate(duplicate_groups, start=1):
        group.sort(key=lambda item: item.relative_path.casefold())
        duplicate_group = f"DUP-{index:03d}"
        primary_path = group[0].relative_path
        for rank, item in enumerate(group, start=1):
            item.duplicate_group = duplicate_group
            item.duplicate_rank = rank
            item.duplicate_count = len(group)
            item.duplicate_primary_relative_path = primary_path
            item.is_duplicate_primary = rank == 1


def summarize(items: Sequence[AssetInventoryItem], assets_root: Path) -> dict[str, object]:
    duplicate_items = [item for item in items if item.duplicate_group]
    duplicate_groups = {item.duplicate_group for item in duplicate_items if item.duplicate_group}
    parse_status_counts = Counter(item.parse_status for item in items)
    return {
        "schema_version": "asset_inventory.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "assets_root": assets_root.resolve().as_posix(),
        "asset_count": len(items),
        "asset_type_counts": dict(Counter(item.asset_type for item in items)),
        "media_kind_counts": dict(Counter(item.media_kind for item in items)),
        "maitu_type_counts": dict(Counter(item.maitu_type or "unknown" for item in items)),
        "maitu_category_counts": dict(Counter(item.maitu_category or "unmapped" for item in items)),
        "parse_status_counts": dict(parse_status_counts),
        "parse_issue_count": sum(1 for item in items if item.parse_issue),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_file_count": len(duplicate_items),
    }


def build_inventory_document(items: Sequence[AssetInventoryItem], assets_root: Path) -> dict[str, object]:
    summary = summarize(items, assets_root)
    return {**summary, "assets": [item.to_json_dict() for item in items]}


def write_json_inventory(path: Path, inventory: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv_inventory(path: Path, items: Sequence[AssetInventoryItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow(item.to_csv_row())


def write_markdown_summary(path: Path, inventory: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AssetGraph 本地素材扫描结果",
        "",
        f"生成时间：{inventory['generated_at']}",
        "",
        "## 扫描范围",
        "",
        "```text",
        str(inventory["assets_root"]),
        "```",
        "",
        "## 总体统计",
        "",
        f"- 素材文件数：{inventory['asset_count']}",
        f"- 解析异常数：{inventory['parse_issue_count']}",
        f"- 重复素材组：{inventory['duplicate_group_count']}",
        f"- 重复素材文件数：{inventory['duplicate_file_count']}",
        "",
        "## 文件类型统计",
        "",
    ]
    for key, value in sorted(dict(inventory["asset_type_counts"]).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## 麦兔类型统计", ""])
    for key, value in sorted(dict(inventory["maitu_type_counts"]).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## 麦兔分类统计", ""])
    for key, value in sorted(dict(inventory["maitu_category_counts"]).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## 后续用途",
            "",
            "本清单用于把 `D:/AssetGraph/素材` 中的本地麦兔素材导入 AssetGraph：",
            "",
            "```text",
            "本地素材文件 -> asset_inventory.json/csv -> assets / asset_files -> 候选素材推荐 -> 麦兔替换方案",
            "```",
            "",
            "JSON 中每个素材都带有 `asset_create_payload`，可直接作为后续导入 `POST /api/assets` 或 CLI 导入的基础数据。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan local Maitu assets into AssetGraph inventory files.")
    parser.add_argument("--assets-root", type=Path, default=Path("素材"), help="Path to local assets root")
    parser.add_argument("--json-output", type=Path, help="Inventory JSON output path")
    parser.add_argument("--csv-output", type=Path, help="Inventory CSV output path")
    parser.add_argument("--summary-output", type=Path, help="Markdown summary output path")
    parser.add_argument("--expected-count", type=int, help="Fail if scanned media count differs from this number")
    parser.add_argument("--quiet", action="store_true", help="Only print errors")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    items = scan_assets(args.assets_root)
    if args.expected_count is not None and len(items) != args.expected_count:
        raise SystemExit(f"expected {args.expected_count} assets, scanned {len(items)}")

    inventory = build_inventory_document(items, args.assets_root)
    if args.json_output:
        write_json_inventory(args.json_output, inventory)
    if args.csv_output:
        write_csv_inventory(args.csv_output, items)
    if args.summary_output:
        write_markdown_summary(args.summary_output, inventory)

    if not args.quiet:
        print(
            json.dumps(
                {key: inventory[key] for key in inventory if key != "assets"},
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

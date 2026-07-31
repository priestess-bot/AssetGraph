from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import unquote, urlparse
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[4]


class MaituInventorySession(Protocol):
    def list_maitu_materials(self) -> list[dict[str, Any]]:
        """Return the authenticated Maitu inventory."""


class MaituInventorySyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MaituInventoryCollection:
    source_revision: str
    captured_at: str
    quality_status: str
    summary: dict[str, Any]
    items: tuple[dict[str, Any], ...]
    observation_path: str


class MaituInventoryCollector:
    """Collect Maitu truth and reconcile it with the local `/DATA` mirror."""

    def __init__(
        self,
        *,
        session: MaituInventorySession,
        mirror_root: Path,
        local_catalog_path: Path | None = None,
        local_import_path: Path | None = None,
        legacy_mapping_path: Path | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
        max_download_bytes: int = 20 * 1024**3,
    ) -> None:
        self.session = session
        self.mirror_root = mirror_root
        self.local_catalog_path = local_catalog_path
        self.local_import_path = local_import_path or (
            local_catalog_path.with_name("current_asset_import.json")
            if local_catalog_path is not None
            else None
        )
        self.legacy_mapping_path = legacy_mapping_path or (
            REPO_ROOT / "docs/asset-numbering/asset_rename_plan_20260709_v3_browser_use.json"
        )
        self.opener = opener
        self.max_download_bytes = max_download_bytes

    def collect(self, *, download_missing: bool = False) -> MaituInventoryCollection:
        rows = self.session.list_maitu_materials()
        if not isinstance(rows, list):
            raise MaituInventorySyncError("Maitu inventory must be a list")
        captured_at = datetime.now(UTC).isoformat()
        local_assets = self._load_local_catalog()
        by_name = self._catalog_by_name(local_assets)
        by_material_id = {
            str(asset["maitu_material_id"]): asset
            for asset in local_assets
            if asset.get("maitu_material_id")
        }
        items: dict[str, dict[str, Any]] = {}
        duplicate_rows = 0
        downloaded = 0
        for raw in rows:
            item = self._normalize_remote_item(
                raw,
                by_name=by_name,
                by_material_id=by_material_id,
                download_missing=download_missing,
            )
            key = item["item_key"]
            if key in items:
                if self._fingerprint(items[key]) != self._fingerprint(item):
                    raise MaituInventorySyncError(f"Maitu returned conflicting rows for {key}")
                duplicate_rows += 1
                continue
            if item["metadata"].get("mirror_downloaded") is True:
                downloaded += 1
            items[key] = item

        remote_names = {
            self._name_key(str(item.get("title") or ""))
            for item in items.values()
            if item.get("title")
        }
        reference_items = 0
        for asset in local_assets:
            if str(asset.get("maitu_type") or "") != "模版":
                continue
            if self._name_key(str(asset.get("subject") or asset.get("title") or "")) in remote_names:
                continue
            item = self._normalize_reference_template(asset)
            items[item["item_key"]] = item
            reference_items += 1

        ordered = tuple(items[key] for key in sorted(items))
        source_revision = self._fingerprint(list(ordered))
        summary = {
            "remote_row_count": len(rows),
            "item_count": len(ordered),
            "duplicate_row_count": duplicate_rows,
            "reference_template_count": reference_items,
            "downloaded_count": downloaded,
            "category_counts": self._counts(ordered, "category"),
            "material_type_counts": self._counts(ordered, "material_type"),
        }
        observation = {
            "schema_version": "maitu-inventory-observation-v1",
            "source_revision": source_revision,
            "captured_at": captured_at,
            "quality_status": "complete",
            "summary": summary,
            "items": ordered,
        }
        observation_path = self._write_observation(observation)
        return MaituInventoryCollection(
            source_revision=source_revision,
            captured_at=captured_at,
            quality_status="complete",
            summary=summary,
            items=ordered,
            observation_path=str(observation_path),
        )

    def _normalize_remote_item(
        self,
        raw: dict[str, Any],
        *,
        by_name: dict[str, dict[str, Any]],
        by_material_id: dict[str, dict[str, Any]],
        download_missing: bool,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise MaituInventorySyncError("Maitu inventory rows must be objects")
        material_type = str(raw.get("type") or "unknown").strip().lower()
        material_id = str(raw.get("id") or "").strip()
        if not material_id or material_type not in {"image", "video", "decorative_video", "digital_human"}:
            raise MaituInventorySyncError("Maitu inventory row has no stable id/type")
        title = str(raw.get("name") or f"{material_type}-{material_id}").strip()
        category = self._category(raw)
        source_url = self._https_url(raw.get("url"))
        cover_url = self._https_url(raw.get("cover_url"))
        local = by_material_id.get(material_id) or by_name.get(self._name_key(title))
        checksum = str((local or {}).get("sha256") or "") or None
        local_relative_path = str((local or {}).get("relative_path") or "") or None
        mirror_downloaded = False
        if download_missing and source_url and not local_relative_path and material_type != "digital_human":
            path, checksum = self._download(material_id=material_id, title=title, source_url=source_url)
            local_relative_path = str(path.relative_to(self.mirror_root))
            mirror_downloaded = True
        metadata = {
            "source": "authenticated_maitu_inventory",
            "tags": raw.get("tags"),
            "duration": raw.get("duration"),
            "sound_enabled": raw.get("sound_enabled"),
            "local_relative_path": local_relative_path,
            "local_file_code": (local or {}).get("file_code"),
            "mirror_downloaded": mirror_downloaded,
            "reference_only": False,
            "reconstruction_fidelity": "authoritative_material",
        }
        return {
            "item_key": f"maitu:{material_type}:{material_id}",
            "material_id": material_id,
            "asset_code": (local or {}).get("asset_code"),
            "title": title,
            "material_type": material_type,
            "category": category,
            "subtype": str(raw.get("subtype") or "") or None,
            "availability_status": "available",
            "checksum_sha256": checksum,
            "source_material_url": self._durable_https_url(source_url),
            "source_cover_url": self._durable_https_url(cover_url),
            "speaker_id": self._positive_int(raw.get("speaker_id")),
            "digital_human_image_id": self._positive_int(raw.get("digital_human_image_id")),
            "metadata": metadata,
        }

    def _normalize_reference_template(self, asset: dict[str, Any]) -> dict[str, Any]:
        file_code = str(asset.get("file_code") or "template").strip()
        return {
            "item_key": f"local-template:{file_code}",
            "material_id": None,
            "asset_code": asset.get("asset_code"),
            "title": str(asset.get("title") or file_code),
            "material_type": "template",
            "category": "模版",
            "subtype": str(asset.get("usage") or "") or None,
            "availability_status": "available",
            "checksum_sha256": str(asset.get("sha256") or "") or None,
            "source_material_url": None,
            "source_cover_url": None,
            "speaker_id": None,
            "digital_human_image_id": None,
            "metadata": {
                "source": "local_authorized_mirror",
                "local_relative_path": asset.get("relative_path"),
                "local_file_code": file_code,
                "reference_only": True,
                "reconstruction_fidelity": "approximate",
            },
        }

    def _download(self, *, material_id: str, title: str, source_url: str) -> tuple[Path, str]:
        parsed = urlparse(source_url)
        suffix = Path(unquote(parsed.path)).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            suffix = ".bin"
        safe_title = re.sub(r"[^A-Za-z0-9._\u3400-\u9fff-]+", "_", title).strip("._")[:120]
        destination = self.mirror_root / "objects" / material_id[:2] / f"{material_id}_{safe_title}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        if destination.is_file():
            return destination, self._sha256_file(destination)
        temporary = destination.with_suffix(destination.suffix + ".part")
        request = urllib.request.Request(source_url, headers={"User-Agent": "AssetGraph-Maitu-Mirror/1"})
        digest = hashlib.sha256()
        size = 0
        try:
            with self.opener(request, timeout=180) as response, temporary.open("wb") as target:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > self.max_download_bytes:
                        raise MaituInventorySyncError("Maitu material exceeds the per-file mirror limit")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if size == 0:
                raise MaituInventorySyncError("Maitu material download was empty")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            return destination, digest.hexdigest()
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _write_observation(self, payload: dict[str, Any]) -> Path:
        destination = self.mirror_root / "inventory-observations" / f"{payload['source_revision']}.json"
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.mirror_root, 0o700)
        os.chmod(destination.parent, 0o700)
        if destination.exists():
            self._assert_existing_observation(destination, payload)
            return destination
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as target:
                json.dump(payload, target, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                self._assert_existing_observation(destination, payload)
            else:
                os.chmod(destination, 0o600)
                directory_flag = getattr(os, "O_DIRECTORY", None)
                if directory_flag is not None:
                    directory_fd = os.open(destination.parent, os.O_RDONLY | directory_flag)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    @classmethod
    def _assert_existing_observation(cls, path: Path, payload: dict[str, Any]) -> None:
        if path.is_symlink() or not path.is_file():
            raise MaituInventorySyncError("inventory observation destination is not a regular file")
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MaituInventorySyncError("existing inventory observation is unreadable") from exc
        immutable_fields = ("schema_version", "source_revision", "quality_status", "summary", "items")
        if any(existing.get(field) != cls._json_value(payload.get(field)) for field in immutable_fields):
            raise MaituInventorySyncError("inventory observation revision already has different content")
        if os.name != "nt" and (path.stat().st_mode & 0o777) != 0o600:
            raise MaituInventorySyncError("existing inventory observation must have mode 0600")

    @staticmethod
    def _json_value(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def _load_local_catalog(self) -> list[dict[str, Any]]:
        if self.local_catalog_path is None or not self.local_catalog_path.is_file():
            return []
        payload = json.loads(self.local_catalog_path.read_text(encoding="utf-8"))
        rows = payload.get("assets") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise MaituInventorySyncError("local asset catalog has an invalid schema")
        import_by_file_code: dict[str, str] = {}
        if self.local_import_path is not None and self.local_import_path.is_file():
            imported = json.loads(self.local_import_path.read_text(encoding="utf-8"))
            import_rows = imported.get("items") if isinstance(imported, dict) else None
            if not isinstance(import_rows, list):
                raise MaituInventorySyncError("local asset import receipt has an invalid schema")
            for row in import_rows:
                if not isinstance(row, dict):
                    continue
                file_code = str(row.get("local_file_code") or "").strip()
                asset_code = str(row.get("asset_code") or "").strip()
                if file_code and asset_code:
                    import_by_file_code[file_code] = asset_code
        material_by_file_code: dict[str, str] = {}
        if self.legacy_mapping_path.is_file():
            mapping = json.loads(self.legacy_mapping_path.read_text(encoding="utf-8"))
            mapping_rows = mapping.get("rows") if isinstance(mapping, dict) else None
            if not isinstance(mapping_rows, list):
                raise MaituInventorySyncError("legacy material mapping has an invalid schema")
            for row in mapping_rows:
                if not isinstance(row, dict):
                    continue
                file_code = str(row.get("file_code") or "").strip()
                material_id = str(row.get("maitu_material_id_guess") or "").strip()
                if file_code and material_id:
                    material_by_file_code[file_code] = material_id
        return [
            {
                **row,
                "asset_code": row.get("asset_code")
                or import_by_file_code.get(str(row.get("file_code") or "")),
                "maitu_material_id": row.get("maitu_material_id")
                or material_by_file_code.get(str(row.get("file_code") or "")),
            }
            for row in rows
        ]

    @classmethod
    def _catalog_by_name(cls, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            for value in (row.get("filename"), row.get("subject"), row.get("title")):
                text = str(value or "")
                keys = {
                    cls._name_key(text),
                    cls._name_key(re.sub(r"^\d+_", "", Path(text).name)),
                }
                for key in keys:
                    if key:
                        result.setdefault(key, row)
        return result

    @staticmethod
    def _category(raw: dict[str, Any]) -> str:
        if raw.get("type") in {"video", "decorative_video"}:
            return "视频"
        if raw.get("type") == "digital_human":
            return "数字分身"
        tags = str(raw.get("tags") or "")
        return "背景" if "背景" in tags else "装饰"

    @staticmethod
    def _https_url(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        parsed = urlparse(text)
        if parsed.scheme != "https" or not parsed.netloc:
            raise MaituInventorySyncError("Maitu inventory contains a non-HTTPS material URL")
        return text

    @staticmethod
    def _durable_https_url(value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        return parsed._replace(params="", query="", fragment="").geturl()

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _name_key(value: str) -> str:
        stem = Path(unquote(value)).stem.lower()
        return "".join(character for character in stem if character.isalnum())

    @staticmethod
    def _fingerprint(payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _counts(items: tuple[dict[str, Any], ...], field: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in items:
            key = str(item.get(field) or "unknown")
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items()))

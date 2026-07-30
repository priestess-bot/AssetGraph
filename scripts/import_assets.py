#!/usr/bin/env python3
"""Import scanned local AssetGraph materials through the backend API.

This importer is intentionally API-first. It reads the read-only inventory emitted
by scripts/scan_assets.py, validates local files, and then calls AssetGraph API
endpoints to create assets and optionally upload original files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence


class ImportClient(Protocol):
    def get_asset_by_local_file_code(self, source_system: str, local_file_code: str) -> dict[str, Any] | None: ...

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def upload_asset_file(
        self,
        *,
        asset_code: str,
        path: Path,
        file_role: str,
        local_file_code: str,
        source_relative_path: str,
        checksum_sha256: str,
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class ImportOptions:
    inventory: Path
    assets_root: Path
    api_base_url: str = "http://127.0.0.1:8000"
    dry_run: bool = False
    expected_count: int | None = None
    limit: int | None = None
    local_file_codes: tuple[str, ...] = ()
    skip_existing: bool = True
    upload_files: bool = False
    write_tags: bool = True
    report_output: Path | None = None


class AssetGraphImportClient:
    def __init__(self, api_base_url: str, timeout_seconds: float = 120.0) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_asset_by_local_file_code(self, source_system: str, local_file_code: str) -> dict[str, Any] | None:
        query = urllib.parse.urlencode({"local_file_code": local_file_code, "limit": 50})
        rows = self._request_json("GET", f"/api/assets?{query}")
        if not isinstance(rows, list):
            raise RuntimeError("GET /api/assets did not return a list")
        for row in rows:
            if row.get("source_system") == source_system and row.get("local_file_code") == local_file_code:
                return row
        return None

    def create_asset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "/api/assets", payload)

    def upload_asset_file(
        self,
        *,
        asset_code: str,
        path: Path,
        file_role: str,
        local_file_code: str,
        source_relative_path: str,
        checksum_sha256: str,
    ) -> dict[str, Any]:
        fields = {
            "file_role": file_role,
            "local_file_code": local_file_code,
            "source_relative_path": source_relative_path,
            "checksum_sha256": checksum_sha256,
        }
        return self._multipart_upload(f"/api/assets/{urllib.parse.quote(asset_code)}/files", path=path, fields=fields)

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.api_base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
        if not content:
            return {}
        return json.loads(content.decode("utf-8"))

    def _multipart_upload(self, path_url: str, *, path: Path, fields: dict[str, str]) -> dict[str, Any]:
        boundary = "----assetgraph-import-boundary"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(
            f"{self.api_base_url}{path_url}",
            data=b"".join(chunks),
            headers={"Accept": "application/json", "Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {path_url}: {detail}") from exc
        return json.loads(content.decode("utf-8")) if content else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_inventory(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assets = document.get("assets")
    if not isinstance(assets, list):
        raise ValueError("inventory must contain an assets list")
    return [item for item in assets if isinstance(item, dict)]


def selected_items(items: list[dict[str, Any]], options: ImportOptions) -> list[dict[str, Any]]:
    selected = items
    if options.local_file_codes:
        wanted = set(options.local_file_codes)
        selected = [item for item in selected if item_local_file_code(item) in wanted]
    if options.limit is not None:
        selected = selected[: options.limit]
    return selected


def item_payload(item: dict[str, Any], *, write_tags: bool) -> dict[str, Any]:
    payload = dict(item.get("asset_create_payload") or {})
    # Older inventories predate the functional material-library dimensions.
    # Preserve those inventories while making local files immediately usable in
    # the workbench: previews and local production need an explicit media kind,
    # capability, and a useful first-pass role.
    payload.setdefault("media_kind", item.get("media_kind"))
    payload.setdefault("execution_capability", "local_only")
    category_roles = {
        "background_image": ["background"],
        "background_video": ["background"],
        "digital_human_video": ["digital_human"],
        "product_image": ["product_display"],
        "product_video": ["supporting_video"],
        "floating_sticker": ["decoration_foreground"],
        "voice_audio": ["voice"],
    }
    if not payload.get("material_roles"):
        category = str(payload.get("maitu_category") or item.get("maitu_category") or "")
        payload["material_roles"] = category_roles.get(category, [])
    if write_tags:
        payload["tags"] = list(item.get("tags") or [])
    return payload


def item_local_file_code(item: dict[str, Any]) -> str | None:
    payload = item.get("asset_create_payload") or {}
    return payload.get("local_file_code") or item.get("file_code")


def validate_item(item: dict[str, Any], assets_root: Path) -> tuple[bool, str | None, Path | None, dict[str, Any]]:
    payload = item_payload(item, write_tags=True)
    required = ("asset_type", "original_filename", "checksum_sha256", "local_file_code", "source_system", "local_relative_path")
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return False, f"missing required fields: {', '.join(missing)}", None, payload

    relative_path = str(payload.get("local_relative_path") or item.get("relative_path") or "")
    path = assets_root / relative_path
    if not path.exists() or not path.is_file():
        return False, f"file missing: {relative_path}", path, payload

    expected_size = int(item.get("file_size") or payload.get("file_size") or -1)
    actual_size = path.stat().st_size
    if expected_size >= 0 and actual_size != expected_size:
        return False, f"file_size mismatch: expected {expected_size}, got {actual_size}", path, payload

    expected_checksum = str(item.get("sha256") or payload.get("checksum_sha256"))
    actual_checksum = sha256_file(path)
    if actual_checksum != expected_checksum:
        return False, f"checksum mismatch for {relative_path}", path, payload
    payload["checksum_sha256"] = actual_checksum
    payload["file_size"] = actual_size
    return True, None, path, payload


def empty_report(options: ImportOptions) -> dict[str, Any]:
    return {
        "mode": "dry_run" if options.dry_run else "import",
        "planned_count": 0,
        "invalid_count": 0,
        "create_count": 0,
        "skip_count": 0,
        "fail_count": 0,
        "file_upload_count": 0,
        "items": [],
    }


def run_import(options: ImportOptions, *, client: ImportClient | None = None) -> dict[str, Any]:
    all_items = load_inventory(options.inventory)
    if options.expected_count is not None and len(all_items) != options.expected_count:
        raise ValueError(f"expected {options.expected_count} inventory assets, found {len(all_items)}")
    items = selected_items(all_items, options)
    client = client or AssetGraphImportClient(options.api_base_url)
    report = empty_report(options)

    for item in items:
        valid, reason, path, payload_with_tags = validate_item(item, options.assets_root)
        payload = item_payload(item, write_tags=options.write_tags)
        payload.update({key: payload_with_tags[key] for key in ("checksum_sha256", "file_size") if key in payload_with_tags})
        local_file_code = str(payload.get("local_file_code") or item_local_file_code(item) or "")
        source_system = str(payload.get("source_system") or "")
        source_relative_path = str(payload.get("local_relative_path") or item.get("relative_path") or "")
        report_item: dict[str, Any] = {"local_file_code": local_file_code, "relative_path": source_relative_path}

        if not valid or path is None:
            report["invalid_count"] += 1
            report_item.update({"operation": "invalid", "reason": reason})
            report["items"].append(report_item)
            continue

        report["planned_count"] += 1
        if options.dry_run:
            report_item.update({"operation": "planned", "reason": "dry-run"})
            report["items"].append(report_item)
            continue

        try:
            existing = client.get_asset_by_local_file_code(source_system, local_file_code)
            if existing and options.skip_existing:
                report["skip_count"] += 1
                asset_code = str(existing.get("asset_code"))
                report_item.update({"operation": "skipped", "reason": "existing-local-file-code", "asset_code": asset_code})
            else:
                created = client.create_asset(payload)
                report["create_count"] += 1
                asset_code = str(created["asset_code"])
                report_item.update({"operation": "created", "reason": "created", "asset_code": asset_code})

            if options.upload_files and not existing:
                client.upload_asset_file(
                    asset_code=asset_code,
                    path=path,
                    file_role="original",
                    local_file_code=local_file_code,
                    source_relative_path=source_relative_path,
                    checksum_sha256=str(payload["checksum_sha256"]),
                )
                report["file_upload_count"] += 1
        except Exception as exc:  # pragma: no cover - defensive command boundary
            report["fail_count"] += 1
            report_item.update({"operation": "failed", "reason": str(exc)})
        report["items"].append(report_item)

    if options.report_output:
        options.report_output.parent.mkdir(parents=True, exist_ok=True)
        options.report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import AssetGraph scanned materials through the backend API.")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--assets-root", type=Path, required=True)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--local-file-code", dest="local_file_codes", action="append", default=[])
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--upload-files", action="store_true")
    parser.add_argument("--write-tags", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--report-output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_import(
        ImportOptions(
            inventory=args.inventory,
            assets_root=args.assets_root,
            api_base_url=args.api_base_url,
            dry_run=args.dry_run,
            expected_count=args.expected_count,
            limit=args.limit,
            local_file_codes=tuple(args.local_file_codes),
            skip_existing=args.skip_existing,
            upload_files=args.upload_files,
            write_tags=args.write_tags,
            report_output=args.report_output,
        )
    )
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False, indent=2))
    return 1 if report["invalid_count"] or report["fail_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import tarfile
from pathlib import Path
from typing import Any
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "docs" / "asset-numbering" / "asset_inventory_20260709.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe relative asset path: {value}")
    return path


def load_inventory(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("inventory must contain an assets list")
    return payload


def verify_asset(path: Path, item: dict[str, Any]) -> None:
    relative = item["relative_path"]
    if not path.is_file():
        raise ValueError(f"asset missing: {relative}")
    expected_size = int(item["file_size"])
    if path.stat().st_size != expected_size:
        raise ValueError(f"size mismatch: {relative}")
    expected_hash = str(item["sha256"])
    if sha256_file(path) != expected_hash:
        raise ValueError(f"hash mismatch: {relative}")


def create_bundle(inventory_path: Path, assets_root: Path, archive_path: Path) -> int:
    inventory = load_inventory(inventory_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    partial = archive_path.with_name(f"{archive_path.name}.partial")
    partial.unlink(missing_ok=True)
    try:
        with tarfile.open(partial, mode="w", format=tarfile.PAX_FORMAT) as archive:
            inventory_bytes = json.dumps(inventory, ensure_ascii=False, sort_keys=True).encode("utf-8")
            inventory_info = tarfile.TarInfo("asset_inventory.json")
            inventory_info.size = len(inventory_bytes)
            inventory_info.mode = 0o644
            archive.addfile(inventory_info, io.BytesIO(inventory_bytes))
            for raw_item in inventory["assets"]:
                item = dict(raw_item)
                relative = safe_relative(str(item["relative_path"]))
                source = assets_root / relative
                verify_asset(source, item)
                archive.add(source, arcname=(Path("assets") / relative).as_posix(), recursive=False)
        partial.replace(archive_path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return len(inventory["assets"])


def restore_bundle(archive_path: Path, assets_root: Path, trusted_inventory_path: Path = DEFAULT_INVENTORY) -> int:
    trusted_inventory = load_inventory(trusted_inventory_path)
    assets_root.parent.mkdir(parents=True, exist_ok=True)
    staging = assets_root.parent / f".{assets_root.name}.restore-{uuid4().hex}"
    backup = assets_root.parent / f".{assets_root.name}.backup-{uuid4().hex}"
    staging.mkdir()
    resolved_staging = staging.resolve()
    try:
        with tarfile.open(archive_path, mode="r") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if names.count("asset_inventory.json") != 1:
                raise ValueError("bundle must contain exactly one asset_inventory.json")
            inventory_stream = archive.extractfile("asset_inventory.json")
            if inventory_stream is None:
                raise ValueError("bundle inventory is unreadable")
            inventory = json.loads(inventory_stream.read().decode("utf-8"))
            if inventory != trusted_inventory:
                raise ValueError("bundle inventory does not match trusted repository inventory")
            expected_members: set[str] = set()
            for raw_item in trusted_inventory["assets"]:
                item = dict(raw_item)
                relative = safe_relative(str(item["relative_path"]))
                member_name = (Path("assets") / relative).as_posix()
                expected_members.add(member_name)
                if names.count(member_name) != 1:
                    raise ValueError(f"bundle asset entry missing or duplicated: {member_name}")
                member = archive.getmember(member_name)
                if not member.isfile():
                    raise ValueError(f"bundle asset entry is not a regular file: {member_name}")
                if member.size != int(item["file_size"]):
                    raise ValueError(f"bundle asset entry size mismatch: {member_name}")
                destination = (staging / relative).resolve()
                try:
                    destination.relative_to(resolved_staging)
                except ValueError as exc:
                    raise ValueError(f"bundle path escapes asset root: {member_name}") from exc
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"bundle asset is unreadable: {member_name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                verify_asset(destination, item)
            unexpected = {
                member.name
                for member in members
                if member.name != "asset_inventory.json" and member.name not in expected_members
            }
            if unexpected:
                raise ValueError(f"bundle contains unexpected entries: {sorted(unexpected)}")

        if assets_root.exists():
            os.replace(assets_root, backup)
            try:
                os.replace(staging, assets_root)
            except Exception:
                os.replace(backup, assets_root)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(staging, assets_root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and not assets_root.exists():
            os.replace(backup, assets_root)
        raise
    return len(trusted_inventory["assets"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or restore a hash-verified private AssetGraph asset corpus bundle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    create.add_argument("--assets-root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--assets-root", type=Path, required=True)
    restore.add_argument("--trusted-inventory", type=Path, default=DEFAULT_INVENTORY)

    args = parser.parse_args(argv)
    if args.command == "create":
        count = create_bundle(args.inventory, args.assets_root, args.output)
        print(f"bundle={args.output} assets={count}")
    else:
        count = restore_bundle(args.bundle, args.assets_root, args.trusted_inventory)
        print(f"assets_root={args.assets_root} assets={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

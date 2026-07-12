from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_bundle_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "asset_corpus_bundle.py"
    spec = importlib.util.spec_from_file_location("assetgraph_asset_bundle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_asset_corpus_bundle_roundtrip_is_hash_verified(tmp_path: Path) -> None:
    bundle = load_bundle_module()
    source = tmp_path / "source"
    source.mkdir()
    first = source / "images" / "a.bin"
    second = source / "videos" / "b.bin"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"asset-a")
    second.write_bytes(b"asset-b" * 1024)

    def item(path: Path) -> dict[str, object]:
        relative = path.relative_to(source).as_posix()
        payload = path.read_bytes()
        return {
            "relative_path": relative,
            "file_size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"assets": [item(first), item(second)]}), encoding="utf-8")
    archive = tmp_path / "asset-corpus.tar"
    restored = tmp_path / "restored"

    assert bundle.create_bundle(inventory, source, archive) == 2
    assert bundle.restore_bundle(archive, restored, inventory) == 2
    assert (restored / "images" / "a.bin").read_bytes() == b"asset-a"
    assert (restored / "videos" / "b.bin").read_bytes() == b"asset-b" * 1024


def test_asset_corpus_bundle_rejects_untrusted_embedded_inventory(tmp_path: Path) -> None:
    bundle = load_bundle_module()
    source = tmp_path / "source"
    source.mkdir()
    payload = source / "a.bin"
    payload.write_bytes(b"substituted")
    substituted_inventory = tmp_path / "substituted.json"
    substituted_inventory.write_text(
        json.dumps({"assets": [{
            "relative_path": "a.bin",
            "file_size": len(b"substituted"),
            "sha256": hashlib.sha256(b"substituted").hexdigest(),
        }]}),
        encoding="utf-8",
    )
    trusted_inventory = tmp_path / "trusted.json"
    trusted_inventory.write_text(
        json.dumps({"assets": [{
            "relative_path": "a.bin",
            "file_size": len(b"trusted"),
            "sha256": hashlib.sha256(b"trusted").hexdigest(),
        }]}),
        encoding="utf-8",
    )
    archive = tmp_path / "substituted.tar"
    bundle.create_bundle(substituted_inventory, source, archive)

    try:
        bundle.restore_bundle(archive, tmp_path / "restored", trusted_inventory)
    except ValueError as exc:
        assert "trusted repository inventory" in str(exc)
    else:
        raise AssertionError("substituted inventory must fail closed")


def test_asset_corpus_bundle_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    bundle = load_bundle_module()
    source = tmp_path / "source"
    source.mkdir()
    payload = source / "bad.bin"
    payload.write_bytes(b"unexpected")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "relative_path": "bad.bin",
                        "file_size": len(b"unexpected"),
                        "sha256": hashlib.sha256(b"expected").hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        bundle.create_bundle(inventory, source, tmp_path / "bad.tar")
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("hash mismatch must fail closed")

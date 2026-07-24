from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_text_sha256(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _load_manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "reproducibility.lock.json").read_text(encoding="utf-8"))


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    required = [
        "reproducibility.lock.json",
        "backend/uv.lock",
        "workers/browser-use/uv.lock",
        "scripts/bootstrap_reproducible.py",
        "scripts/apply_migrations.py",
        "scripts/rehearse_migrations.py",
        "scripts/rehearse_disaster_recovery.py",
        "scripts/audit_legacy_compatibility.py",
        "scripts/measure_capacity_baseline.py",
        "scripts/assemble_phase0_acceptance.py",
        "scripts/verify_reproducibility.py",
        "docs/operations/database-migration-rehearsal.md",
        "docs/operations/disaster-recovery-baseline-runbook.md",
        "docs/operations/legacy-compatibility-audit.md",
        "docs/operations/capacity-baseline-input.v1.example.json",
        "docs/operations/capacity-baseline-measurement-2026-07-23.md",
        "docs/operations/phase-owner-register.v1.example.json",
        "docs/operations/phase-0-acceptance-signoff.v1.example.json",
        "docs/operations/phase-0-acceptance-package.md",
        "docs/operations/phase-0-migration-invariants.v1.json",
        "docs/evidence/phase-0-disaster-recovery-validation-2026-07-23.md",
        "docs/evidence/phase-0-disaster-recovery-baseline-2026-07-23-attempt-4.json",
        "docs/evidence/phase-0-legacy-compatibility-validation-2026-07-23.md",
        "docs/evidence/phase-0-legacy-compatibility-audit-2026-07-23.json",
        "docs/evidence/phase-0-capacity-baseline-integration-2026-07-23.json",
        "docs/evidence/phase-0-regression-2026-07-23.json",
        "docs/evidence/phase-0-acceptance-package-preparation-2026-07-23.json",
        ".github/workflows/reproducibility.yml",
        "services/qwen3/qwen3_shared_server.py",
        "services/qwen3/pyproject.toml",
        "services/qwen3/uv.lock",
        "services/qwen3/README.md",
        "workers/video-production/src/assetgraph_tts/server.py",
        "workers/video-production/pyproject.toml",
        "workers/video-production/uv.lock",
        "workers/video-production/README.md",
        "workers/live-research/src/assetgraph_live_research/main.py",
        "workers/live-research/pyproject.toml",
        "workers/live-research/uv.lock",
        "workers/live-research/README.md",
        "workers/live-research/streamcap-requirements.lock.txt",
        "frontend/package.json",
        "frontend/package-lock.json",
    ]
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")

    if errors and not (root / "reproducibility.lock.json").is_file():
        return errors

    manifest = _load_manifest(root)
    skill = manifest["script_skill"]
    skill_root = root / skill["path"]
    expected_skill_files = {Path(relative).as_posix() for relative in skill["files"]}
    actual_skill_files = (
        {
            path.relative_to(skill_root).as_posix()
            for path in skill_root.rglob("*")
            if path.is_file()
        }
        if skill_root.is_dir()
        else set()
    )
    if actual_skill_files != expected_skill_files:
        errors.append(
            "script skill file set mismatch: "
            f"missing={sorted(expected_skill_files - actual_skill_files)}, "
            f"extra={sorted(actual_skill_files - expected_skill_files)}"
        )
    for relative, expected_hash in skill["files"].items():
        path = skill_root / relative
        if not path.is_file():
            errors.append(f"missing script skill file: {path.relative_to(root)}")
        elif _canonical_text_sha256(path) != expected_hash:
            errors.append(f"script skill hash mismatch: {path.relative_to(root)}")

    skill_path = skill_root / "SKILL.md"
    if skill_path.is_file():
        content = skill_path.read_text(encoding="utf-8")
        if (
            not content.startswith("---\n")
            or "name: jd-wine-livestream-scriptwriting" not in content
        ):
            errors.append("script skill frontmatter is invalid")
        for relative in re.findall(
            r"\]\((references/[^)]+|templates/[^)]+)\)", content
        ):
            if not (skill_root / relative).is_file():
                errors.append(f"script skill link is broken: {relative}")

    asset_contract = manifest["asset_inventory"]
    inventory_path = root / asset_contract["manifest"]
    if not inventory_path.is_file():
        errors.append(f"asset inventory manifest missing: {asset_contract['manifest']}")
    else:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        if len(inventory.get("assets", [])) != asset_contract["expected_files"]:
            errors.append("asset inventory count does not match reproducibility lock")
    transfer_tool = root / asset_contract["transfer_tool"]
    if not transfer_tool.is_file():
        errors.append(
            f"private asset corpus transfer tool missing: {asset_contract['transfer_tool']}"
        )

    migrations = sorted((root / "backend" / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
    numbers = [int(path.name[:3]) for path in migrations]
    if numbers != list(range(1, len(numbers) + 1)):
        errors.append(f"migration sequence is not contiguous: {numbers}")

    backend_pyproject = root / "backend" / "pyproject.toml"
    if (
        backend_pyproject.is_file()
        and '"httpx2>=2.5.0"' not in backend_pyproject.read_text(encoding="utf-8")
    ):
        errors.append("backend dev dependency is missing the Starlette httpx2 adapter")

    hardcoded = re.compile(r"(?i)(?:[a-z]:[/\\](?:assetgraph|browser-use|ai-models))")
    source_roots = [
        root / "backend" / "app",
        root / "workers" / "browser-use" / "src",
        root / "scripts",
        root / "services" / "qwen3",
        root / "workers" / "video-production" / "src",
        root / "workers" / "live-research" / "src",
    ]
    for source_root in source_roots:
        if not source_root.exists():
            continue
        for path in source_root.rglob("*"):
            if path.suffix not in {".py", ".sh", ".ps1"} or not path.is_file():
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if hardcoded.search(line):
                    errors.append(
                        f"machine-specific executable path: {path.relative_to(root)}:{line_number}"
                    )
    return errors


def validate_external(root: Path, *, verify_asset_hashes: bool = False) -> list[str]:
    root = root.resolve()
    manifest = _load_manifest(root)
    errors: list[str] = []

    browser_path = Path(
        os.getenv("BROWSER_USE_REPO", root / manifest["browser_use"]["default_path"])
    )
    if not browser_path.is_dir():
        errors.append(f"browser-use checkout missing: {browser_path}")
    else:
        completed = subprocess.run(
            ["git", "-C", str(browser_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        actual = completed.stdout.strip()
        if completed.returncode != 0 or actual != manifest["browser_use"]["commit"]:
            errors.append(
                f"browser-use revision mismatch: expected {manifest['browser_use']['commit']}, got {actual or 'unreadable'}"
            )

    for key, label in (("streamcap", "StreamCap"), ("douyin_live", "douyinLive")):
        item = manifest["live_research"][key]
        checkout = root / item["default_path"]
        if not checkout.is_dir():
            errors.append(f"{label} checkout missing: {checkout}")
            continue
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        actual = completed.stdout.strip()
        if completed.returncode != 0 or actual != item["commit"]:
            errors.append(
                f"{label} revision mismatch: expected {item['commit']}, got {actual or 'unreadable'}"
            )
    douyin = manifest["live_research"]["douyin_live"]
    binary = root / douyin["default_binary_path"]
    if not binary.is_file():
        errors.append(f"douyinLive binary missing: {binary}")
    else:
        completed = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        version_text = completed.stdout + completed.stderr
        if (
            completed.returncode != 0
            or douyin["tag"] not in version_text
            or douyin["commit"][:12] not in version_text
        ):
            errors.append(
                "douyinLive binary version does not match the reproducibility lock"
            )

    model_root = root / ".external" / "models" / "qwen3-4b"
    embedding = Path(
        os.getenv("QWEN3_EMBEDDING_PATH", model_root / "Qwen3-Embedding-4B")
    )
    reranker = Path(os.getenv("QWEN3_RERANKER_PATH", model_root / "Qwen3-Reranker-4B"))
    for label, path in (("embedding", embedding), ("reranker", reranker)):
        if not (path / "config.json").is_file():
            errors.append(f"Qwen3 {label} model missing: {path}")

    errors.extend(validate_video_demo(root, verify_asset_hashes=verify_asset_hashes))

    assets_root = Path(os.getenv("ASSETGRAPH_ASSETS_ROOT", root / "素材"))
    inventory_path = root / manifest["asset_inventory"]["manifest"]
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    missing_assets: list[str] = []
    mismatched_assets: list[str] = []
    for item in inventory["assets"]:
        path = assets_root / Path(item["relative_path"])
        if not path.is_file():
            missing_assets.append(item["relative_path"])
        elif path.stat().st_size != item["file_size"]:
            mismatched_assets.append(item["relative_path"])
        elif verify_asset_hashes and _sha256(path) != item["sha256"]:
            mismatched_assets.append(item["relative_path"])
    if missing_assets:
        errors.append(
            f"asset inventory missing {len(missing_assets)} files under {assets_root}"
        )
    if mismatched_assets:
        errors.append(
            f"asset inventory mismatch for {len(mismatched_assets)} files under {assets_root}"
        )
    return errors


def validate_video_demo(root: Path, *, verify_asset_hashes: bool = True) -> list[str]:
    root = root.resolve()
    manifest = _load_manifest(root)
    errors: list[str] = []
    contract = manifest["video_demo"]
    for command in contract["required_commands"]:
        if shutil.which(command) is None:
            errors.append(f"video demo command missing: {command}")

    if shutil.which("fc-match") is not None:
        completed = subprocess.run(
            ["fc-match", "-f", "%{family}", contract["required_font"]],
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            completed.returncode != 0
            or contract["required_font"] not in completed.stdout
        ):
            errors.append(f"video demo font missing: {contract['required_font']}")

    video_tts = manifest["video_tts"]
    kokoro_root = Path(
        os.getenv("ASSETGRAPH_KOKORO_MODEL_ROOT", root / video_tts["default_path"])
    )
    snapshot = (
        kokoro_root
        / "models--hexgrad--Kokoro-82M"
        / "snapshots"
        / video_tts["revision"]
    )
    pinned_files = (
        (video_tts["model_file"], video_tts["model_sha256"]),
        (video_tts["config_file"], video_tts["config_sha256"]),
        (video_tts["voice_file"], video_tts["voice_sha256"]),
    )
    for relative_path, expected_sha256 in pinned_files:
        path = snapshot / relative_path
        if not path.is_file():
            errors.append(f"Kokoro file missing: {path}")
        elif _sha256(path) != expected_sha256:
            errors.append(f"Kokoro file hash mismatch: {path}")

    assets_root = Path(os.getenv("ASSETGRAPH_ASSETS_ROOT", root / "素材"))
    for item in contract["assets"]:
        path = assets_root / item["relative_path"]
        if not path.is_file():
            errors.append(f"video demo asset missing: {path}")
        elif path.stat().st_size != item["file_size"]:
            errors.append(f"video demo asset size mismatch: {path}")
        elif verify_asset_hashes and _sha256(path) != item["sha256"]:
            errors.append(f"video demo asset hash mismatch: {path}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify AssetGraph reproducibility contract"
    )
    parser.add_argument(
        "--external",
        action="store_true",
        help="also verify browser-use, Qwen3 models, and asset inventory",
    )
    parser.add_argument(
        "--video-demo",
        action="store_true",
        help="verify only the video Demo runtime, model, and five fixed assets",
    )
    parser.add_argument(
        "--verify-asset-hashes",
        action="store_true",
        help="hash every inventory asset; implies --external and may be slow",
    )
    args = parser.parse_args(argv)

    errors = validate_repository(REPO_ROOT)
    if args.external or args.verify_asset_hashes:
        errors.extend(
            validate_external(
                REPO_ROOT,
                verify_asset_hashes=args.verify_asset_hashes or args.video_demo,
            )
        )
    elif args.video_demo:
        errors.extend(validate_video_demo(REPO_ROOT, verify_asset_hashes=True))
    if errors:
        print(
            json.dumps(
                {"status": "failed", "errors": errors}, ensure_ascii=False, indent=2
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "repository": str(REPO_ROOT),
                "external_checked": bool(args.external or args.verify_asset_hashes),
                "video_demo_checked": bool(args.video_demo),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

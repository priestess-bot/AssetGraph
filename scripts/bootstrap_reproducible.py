from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = {
    "ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN",
    "ASSETGRAPH_MAITU_RECONCILIATION_OPERATOR_TOKEN",
    "ASSETGRAPH_MAITU_AUTHORITY_TOKEN",
    "ASSETGRAPH_MAITU_READBACK_ATTESTATION_KEY",
}

WINDOWS_ENV_DEFAULTS = {
    "ASSETGRAPH_MAITU_MIRROR_ROOT": (
        "/DATA/Downloads/AssetGraph/maitu-mirror",
        "data/maitu-mirror",
    ),
    "ASSETGRAPH_MATERIAL_ANALYSIS_ROOT": (
        "/DATA/Downloads/AssetGraph/material-analysis",
        "data/material-analysis",
    ),
    "ASSETGRAPH_LIVE_RESEARCH_ROOT": (
        "/DATA/Downloads/AssetGraph/live-research",
        "data/live-research",
    ),
    "ASSETGRAPH_VIDEO_PRODUCTION_ROOT": (
        "/DATA/Downloads/AssetGraph/video-productions",
        "data/video-productions",
    ),
    "ASSETGRAPH_STREAMCAP_CHECKOUT": (
        ".external/StreamCap",
        ".external/StreamCap",
    ),
    "ASSETGRAPH_STREAMCAP_PYTHON": (
        ".external/streamcap-venv/bin/python",
        ".external/streamcap-venv/Scripts/python.exe",
    ),
    "ASSETGRAPH_DOUYINLIVE_BINARY": (
        ".external/bin/douyinLive",
        ".external/bin/douyinLive.exe",
    ),
}


def _load_manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "reproducibility.lock.json").read_text(encoding="utf-8"))


def _restrict_private_permissions(
    path: Path,
    *,
    platform_name: str | None = None,
    windows_user: str | None = None,
) -> None:
    platform_name = platform_name or os.name
    if platform_name == "nt":
        user = windows_user or os.getenv("USERNAME") or getpass.getuser()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        os.chmod(path, 0o600)


def _write_private_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _restrict_private_permissions(temporary)
        os.replace(temporary, path)
        _restrict_private_permissions(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _windows_environment_value(root: Path, key: str, value: str) -> str:
    if key == "BROWSER_USE_SESSION_NAME" and value == "assetgraph-maitu-vnc":
        return "assetgraph-maitu-windows"
    default = WINDOWS_ENV_DEFAULTS.get(key)
    if default is None or value != default[0]:
        return value
    return (root / default[1]).resolve().as_posix()


def ensure_environment(root: Path, *, platform_name: str | None = None) -> Path:
    platform_name = platform_name or os.name
    example = root / ".env.example"
    target = root / ".env"
    source = target if target.exists() else example
    lines: list[str] = []
    seen_keys: set[str] = set()
    for line in source.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            seen_keys.add(key)
            if key in SECRET_KEYS and not value.strip():
                value = secrets.token_urlsafe(48)
            if platform_name == "nt":
                value = _windows_environment_value(root, key, value)
            line = f"{key}={value}"
        lines.append(line)
    for key in sorted(SECRET_KEYS - seen_keys):
        lines.append(f"{key}={secrets.token_urlsafe(48)}")
    _write_private_text(target, "\n".join(lines) + "\n")
    return target


def _run(command: list[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _venv_python(project: Path) -> Path:
    windows = project / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else project / ".venv" / "bin" / "python"


def default_hermes_home() -> Path:
    explicit = os.getenv("HERMES_HOME")
    if explicit:
        return Path(explicit)
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def _canonical_text_hash(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _skill_integrity_errors(path: Path, expected_hashes: dict[str, str]) -> list[str]:
    errors: list[str] = []
    expected_files = {Path(relative).as_posix() for relative in expected_hashes}
    actual_files = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    } if path.is_dir() else set()
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        errors.append(f"file set mismatch (missing={missing}, extra={extra})")
    for relative, expected in expected_hashes.items():
        candidate = path / relative
        if candidate.is_file():
            actual = _canonical_text_hash(candidate)
            if actual != expected:
                errors.append(f"hash mismatch: {relative}")
    return errors


def install_skill(root: Path, *, force: bool = False) -> Path:
    manifest = _load_manifest(root)
    skill_manifest = manifest["script_skill"]
    source = root / skill_manifest["path"]
    expected_hashes = skill_manifest["files"]
    bundled_errors = _skill_integrity_errors(source, expected_hashes)
    if bundled_errors:
        raise RuntimeError(f"Bundled Hermes skill does not match reproducibility lock: {bundled_errors}")
    hermes_home = default_hermes_home()
    target = hermes_home / "skills" / "creative" / skill_manifest["name"]
    if target.exists():
        if not force:
            existing_errors = _skill_integrity_errors(target, expected_hashes)
            if existing_errors:
                raise RuntimeError(
                    f"Hermes skill already exists with different content: {target}; "
                    f"details={existing_errors}; use --force-skill"
                )
            return target
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    installed_errors = _skill_integrity_errors(target, expected_hashes)
    if installed_errors:
        raise RuntimeError(f"Installed Hermes skill failed integrity verification: {installed_errors}")
    return target


def install_browser_use(root: Path) -> Path:
    manifest = _load_manifest(root)["browser_use"]
    target = Path(os.getenv("BROWSER_USE_REPO", root / manifest["default_path"]))
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", manifest["repository"], str(target)], cwd=root)
    _run(["git", "fetch", "origin", manifest["commit"]], cwd=target)
    _run(["git", "checkout", "--detach", manifest["commit"]], cwd=target)
    sync_command = ["uv", "sync", "--extra", "cli", "--extra", "core"]
    if (target / "uv.lock").is_file():
        sync_command.append("--frozen")
    _run(sync_command, cwd=target)
    return target


def install_live_research_tools(root: Path) -> tuple[Path, Path]:
    manifest = _load_manifest(root)["live_research"]
    installed: list[Path] = []
    for key in ("streamcap", "douyin_live"):
        item = manifest[key]
        target = root / item["default_path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "clone", "--filter=blob:none", "--no-checkout", item["repository"], str(target)], cwd=root)
        _run(["git", "fetch", "--depth", "1", "origin", item["commit"]], cwd=target)
        _run(["git", "checkout", "--detach", item["commit"]], cwd=target)
        installed.append(target)
    streamcap_venv = root / ".external" / "streamcap-venv"
    _run(["uv", "venv", "--python", "3.12", str(streamcap_venv)], cwd=root)
    streamcap_python = (
        streamcap_venv / "Scripts" / "python.exe"
        if os.name == "nt"
        else streamcap_venv / "bin" / "python"
    )
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(streamcap_python),
            "-r",
            str(root / "workers" / "live-research" / "streamcap-requirements.lock.txt"),
        ],
        cwd=root,
    )
    _run(["uv", "sync", "--frozen"], cwd=root / "workers" / "live-research")

    douyin = manifest["douyin_live"]
    if "linux_amd64_url" in douyin:
        binary = root / douyin["default_binary_path"]
        if not binary.is_file():
            download_root = root / ".external" / "downloads"
            download_root.mkdir(parents=True, exist_ok=True)
            archive = download_root / douyin["linux_amd64_asset"]
            urllib.request.urlretrieve(douyin["linux_amd64_url"], archive)
            actual = hashlib.sha256(archive.read_bytes()).hexdigest()
            if actual != douyin["linux_amd64_sha256"]:
                archive.unlink(missing_ok=True)
                raise RuntimeError("douyinLive release archive checksum mismatch")
            binary.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive, "r:gz") as source:
                member = source.getmember("douyinLive")
                extracted = source.extractfile(member)
                if extracted is None or not member.isfile():
                    raise RuntimeError("douyinLive release archive has no executable")
                with binary.open("wb") as target:
                    shutil.copyfileobj(extracted, target)
            os.chmod(binary, 0o755)
    return installed[0], installed[1]


def download_qwen_models(root: Path) -> tuple[Path, Path]:
    manifest = _load_manifest(root)["qwen3"]
    if shutil.which("hf") is None:
        raise RuntimeError("hf CLI is required for --with-qwen-models")
    model_root = root / ".external" / "models" / "qwen3-4b"
    model_root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for key, directory_name in (("embedding", "Qwen3-Embedding-4B"), ("reranker", "Qwen3-Reranker-4B")):
        item = manifest[key]
        target = model_root / directory_name
        _run(["hf", "download", item["repository"], "--revision", item["revision"], "--local-dir", str(target)], cwd=root)
        paths.append(target)
    _run(["uv", "sync", "--python", "3.12", "--frozen"], cwd=root / "services" / "qwen3")
    return paths[0], paths[1]


def install_video_demo(root: Path) -> Path:
    worker_root = root / "workers" / "video-production"
    frontend_root = root / "frontend"
    missing_commands = [
        command
        for command in ("npm", "ffmpeg", "ffprobe", "fc-match")
        if shutil.which(command) is None
    ]
    if missing_commands:
        raise RuntimeError(
            f"missing commands required for --with-video-demo: {', '.join(missing_commands)}"
        )
    _run(["uv", "sync", "--python", "3.12", "--frozen"], cwd=worker_root)
    _run(
        [
            str(_venv_python(worker_root)),
            "-c",
            "from assetgraph_tts.server import engine; engine.load()",
        ],
        cwd=worker_root,
    )
    _run(["npm", "ci"], cwd=frontend_root)
    _run(["npm", "run", "build"], cwd=frontend_root)
    return Path(
        os.environ.get(
            "ASSETGRAPH_KOKORO_MODEL_ROOT",
            root / ".external" / "models" / "kokoro",
        )
    )


def wait_for_postgres(root: Path, timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    command = ["docker", "compose", "-f", "infra/docker-compose.yml", "exec", "-T", "postgres", "pg_isready", "-U", "assetgraph", "-d", "assetgraph"]
    while time.monotonic() < deadline:
        if subprocess.run(command, cwd=root, capture_output=True).returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("PostgreSQL did not become ready before timeout")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a reproducible AssetGraph checkout")
    parser.add_argument("--skip-dependencies", action="store_true")
    parser.add_argument("--skip-skill", action="store_true")
    parser.add_argument("--force-skill", action="store_true")
    parser.add_argument("--with-browser-use", action="store_true")
    parser.add_argument("--with-live-research-tools", action="store_true")
    parser.add_argument("--with-qwen-models", action="store_true")
    parser.add_argument("--with-video-demo", action="store_true")
    parser.add_argument("--with-infra", action="store_true")
    args = parser.parse_args(argv)

    if not (3, 11) <= sys.version_info[:2] < (3, 15):
        raise SystemExit("Python >=3.11,<3.15 is required")
    if shutil.which("uv") is None and not args.skip_dependencies:
        raise SystemExit("uv is required: https://docs.astral.sh/uv/getting-started/installation/")

    env_path = ensure_environment(REPO_ROOT)
    print(f"environment={env_path}")
    if not args.skip_dependencies:
        _run(["uv", "sync", "--frozen", "--extra", "dev"], cwd=REPO_ROOT / "backend")
        _run(["uv", "sync", "--frozen", "--extra", "dev"], cwd=REPO_ROOT / "workers" / "browser-use")
    if not args.skip_skill:
        print(f"skill={install_skill(REPO_ROOT, force=args.force_skill)}")
    if args.with_browser_use:
        print(f"browser_use={install_browser_use(REPO_ROOT)}")
    if args.with_live_research_tools:
        streamcap, douyin_live = install_live_research_tools(REPO_ROOT)
        print(f"streamcap={streamcap}")
        print(f"douyin_live={douyin_live}")
    if args.with_qwen_models:
        print(f"qwen_models={download_qwen_models(REPO_ROOT)}")
    if args.with_video_demo:
        print(f"video_demo_model={install_video_demo(REPO_ROOT)}")
    if args.with_infra:
        _run(["docker", "compose", "-f", "infra/docker-compose.yml", "up", "-d"], cwd=REPO_ROOT)
        wait_for_postgres(REPO_ROOT)
        _run([str(_venv_python(REPO_ROOT / "backend")), str(REPO_ROOT / "scripts" / "apply_migrations.py")], cwd=REPO_ROOT)
    _run([sys.executable, str(REPO_ROOT / "scripts" / "verify_reproducibility.py")], cwd=REPO_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

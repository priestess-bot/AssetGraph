from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from threading import Lock


class AssetPreviewError(RuntimeError):
    pass


_CACHE_LOCK = Lock()


def _cache_path(
    root: Path,
    *,
    asset_code: str,
    checksum: str | None,
    variant: str,
) -> Path:
    identity = checksum or asset_code
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    safe_code = "".join(char if char.isalnum() or char in "-_" else "_" for char in asset_code)
    suffix = {
        "poster": ".jpg",
        "hover": ".mp4",
        "thumbnail": ".webp",
    }.get(variant)
    if suffix is None:
        raise AssetPreviewError(f"unsupported preview variant: {variant}")
    return root / ".asset-preview-cache" / f"{safe_code}-{digest}-{variant}{suffix}"


def cached_preview_path(
    root: Path,
    *,
    asset_code: str,
    checksum: str | None,
    variant: str,
) -> Path:
    return _cache_path(root, asset_code=asset_code, checksum=checksum, variant=variant)


def build_video_preview(
    source: Path,
    destination: Path,
    *,
    variant: str,
) -> Path:
    if variant not in {"poster", "hover"}:
        raise AssetPreviewError(f"unsupported preview variant: {variant}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep the target suffix so FFmpeg can select the output muxer.
    temporary = destination.with_name(f".{destination.stem}.{os.getpid()}{destination.suffix}")
    if temporary.exists():
        temporary.unlink(missing_ok=True)
    if variant == "poster":
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "0",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-2",
            "-q:v",
            "4",
            str(temporary),
        ]
        timeout = 45
    else:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-t",
            "6",
            "-an",
            "-vf",
            "scale=480:-2,fps=12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "34",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        timeout = 90
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=timeout)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise AssetPreviewError("ffmpeg produced an empty preview")
        temporary.replace(destination)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        temporary.unlink(missing_ok=True)
        raise AssetPreviewError("unable to build local asset preview") from exc
    return destination


def build_image_thumbnail(source: Path, destination: Path) -> Path:
    """Create a compact first-frame image for grid and picker previews."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{os.getpid()}{destination.suffix}")
    if temporary.exists():
        temporary.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        "scale=480:480:force_original_aspect_ratio=decrease",
        "-c:v",
        "libwebp",
        "-quality",
        "72",
        "-compression_level",
        "4",
        str(temporary),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=45)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise AssetPreviewError("ffmpeg produced an empty thumbnail")
        temporary.replace(destination)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        temporary.unlink(missing_ok=True)
        raise AssetPreviewError("unable to build image thumbnail") from exc
    return destination


def ensure_video_preview(
    source: Path,
    root: Path,
    *,
    asset_code: str,
    checksum: str | None,
    variant: str,
) -> Path:
    destination = cached_preview_path(
        root,
        asset_code=asset_code,
        checksum=checksum,
        variant=variant,
    )
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    with _CACHE_LOCK:
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        return build_video_preview(source, destination, variant=variant)


def ensure_image_thumbnail(
    source: Path,
    root: Path,
    *,
    asset_code: str,
    checksum: str | None,
) -> Path:
    destination = cached_preview_path(
        root,
        asset_code=asset_code,
        checksum=checksum,
        variant="thumbnail",
    )
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    with _CACHE_LOCK:
        if destination.is_file() and destination.stat().st_size > 0:
            return destination
        return build_image_thumbnail(source, destination)

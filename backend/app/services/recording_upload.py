from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Any

from app.services.material_analysis import MaterialAnalysisError, probe_media


ALLOWED_RECORDING_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_RECORDING_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
    "application/octet-stream",
}


class RecordingUploadError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class StoredRecording:
    original_name: str
    relative_path: str
    file_size: int
    checksum_sha256: str
    content_type: str
    container_format: str
    duration_seconds: float
    media_probe: dict[str, Any]


def store_recording_upload(
    source: BinaryIO,
    *,
    filename: str,
    content_type: str | None,
    root: Path,
    max_bytes: int,
) -> StoredRecording:
    safe_name = Path(filename or "recording.mp4").name
    suffix = Path(safe_name).suffix.lower()
    normalized_content_type = (content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if suffix not in ALLOWED_RECORDING_SUFFIXES:
        raise RecordingUploadError(
            "RECORDING_FILE_TYPE_UNSUPPORTED",
            "仅支持 MP4、MOV、MKV 或 WebM 直播录屏",
        )
    if normalized_content_type not in ALLOWED_RECORDING_CONTENT_TYPES and not normalized_content_type.startswith("video/"):
        raise RecordingUploadError(
            "RECORDING_CONTENT_TYPE_UNSUPPORTED",
            "上传文件不是可识别的视频格式",
        )

    resolved_root = root.expanduser().resolve()
    staging = resolved_root / ".upload-staging"
    staging.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256()
    size = 0
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=staging, suffix=suffix, delete=False) as target:
            temporary_path = Path(target.name)
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise RecordingUploadError(
                        "RECORDING_FILE_TOO_LARGE",
                        f"录屏超过当前 {max_bytes // (1024 * 1024)} MB 上传上限",
                        status_code=413,
                    )
                digest.update(chunk)
                target.write(chunk)
        if size == 0:
            raise RecordingUploadError("RECORDING_FILE_EMPTY", "上传的录屏文件为空")
        try:
            probe = probe_media(temporary_path)
        except (MaterialAnalysisError, OSError) as exc:
            raise RecordingUploadError(
                "RECORDING_MEDIA_INVALID",
                "无法读取该录屏，请确认文件完整且包含视频轨道",
            ) from exc
        video = probe.get("video")
        if not isinstance(video, dict) or not video.get("width") or not video.get("height"):
            raise RecordingUploadError("RECORDING_VIDEO_STREAM_MISSING", "录屏中没有可用的视频轨道")

        checksum = digest.hexdigest()
        destination = resolved_root / "uploads" / checksum[:2] / f"{checksum}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            if destination.stat().st_size != size:
                raise RecordingUploadError("RECORDING_STORAGE_CONFLICT", "录屏存储校验冲突")
            temporary_path.unlink(missing_ok=True)
        else:
            os.replace(temporary_path, destination)
        temporary_path = None
        return StoredRecording(
            original_name=safe_name,
            relative_path=destination.relative_to(resolved_root).as_posix(),
            file_size=size,
            checksum_sha256=checksum,
            content_type=normalized_content_type,
            container_format=_container_format(suffix),
            duration_seconds=float(probe["duration_seconds"]),
            media_probe={key: value for key, value in probe.items() if key != "raw"},
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _container_format(suffix: str) -> str:
    if suffix in {".mkv", ".webm"}:
        return "matroska"
    return "mp4"

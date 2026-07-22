from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class VideoProductionStage(StrEnum):
    BRIEF_GENERATION = "brief_generation"
    SCRIPT_GENERATION = "script_generation"
    SHOT_PLANNING = "shot_planning"
    ASSET_SELECTION = "asset_selection"
    VOICE_SYNTHESIS = "voice_synthesis"
    SUBTITLE_GENERATION = "subtitle_generation"
    RENDERING = "rendering"
    QUALITY_CHECK = "quality_check"


VIDEO_PRODUCTION_STAGES = tuple(VideoProductionStage)


class VideoProductionError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_key: str
    relative_path: str
    mime_type: str
    file_size: int
    checksum_sha256: str
    metadata: dict[str, Any]

    def as_repository_payload(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "checksum_sha256": self.checksum_sha256,
            "metadata": self.metadata,
        }


class ArtifactStore:
    """Write production artifacts atomically below a single trusted root."""

    SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    def __init__(self, output_root: Path, job_code: str, attempt: int) -> None:
        self.output_root = output_root.resolve()
        if not self.SAFE_COMPONENT.fullmatch(job_code):
            raise VideoProductionError("INVALID_JOB_CODE", "job_code is not safe for a filesystem path")
        if attempt < 1:
            raise VideoProductionError("INVALID_ATTEMPT", "attempt must be at least 1")
        self.job_code = job_code
        self.attempt = attempt
        self.job_root = self.output_root / job_code / f"attempt-{attempt}"
        self.job_root.mkdir(parents=True, exist_ok=True)
        self._assert_below_root(self.job_root)

    def path(self, relative_path: str | Path) -> Path:
        path = self.job_root / relative_path
        self._assert_below_root(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def relative_to_output_root(self, path: Path) -> str:
        self._assert_below_root(path)
        return path.resolve().relative_to(self.output_root).as_posix()

    def write_json(
        self,
        artifact_key: str,
        relative_path: str | Path,
        document: Any,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        content = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        return self.write_bytes(
            artifact_key,
            relative_path,
            content,
            mime_type="application/json",
            metadata=metadata,
        )

    def write_text(
        self,
        artifact_key: str,
        relative_path: str | Path,
        content: str,
        *,
        mime_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        return self.write_bytes(
            artifact_key,
            relative_path,
            content.encode("utf-8"),
            mime_type=mime_type,
            metadata=metadata,
        )

    def write_bytes(
        self,
        artifact_key: str,
        relative_path: str | Path,
        content: bytes,
        *,
        mime_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        destination = self.path(relative_path)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
        try:
            with temporary.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return self.describe(artifact_key, destination, mime_type=mime_type, metadata=metadata)

    def describe(
        self,
        artifact_key: str,
        path: Path,
        *,
        mime_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        self._assert_below_root(path)
        if not path.is_file():
            raise VideoProductionError("ARTIFACT_MISSING", f"artifact does not exist: {path.name}")
        return Artifact(
            artifact_key=artifact_key,
            relative_path=self.relative_to_output_root(path),
            mime_type=mime_type,
            file_size=path.stat().st_size,
            checksum_sha256=sha256_file(path),
            metadata=dict(metadata or {}),
        )

    def find_previous(self, relative_path: str | Path) -> Path | None:
        for attempt in range(self.attempt - 1, 0, -1):
            candidate = self.output_root / self.job_code / f"attempt-{attempt}" / relative_path
            self._assert_below_root(candidate)
            if candidate.is_file():
                return candidate
        return None

    def _assert_below_root(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.output_root)
        except ValueError as exc:
            raise VideoProductionError("UNSAFE_ARTIFACT_PATH", "artifact path escapes output root") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

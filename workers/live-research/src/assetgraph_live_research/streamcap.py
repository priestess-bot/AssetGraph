from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .pins import STREAMCAP_COMMIT, STREAMCAP_VERSION
from .storage import SecureStorage, StorageBoundaryError


class CommandRunner(Protocol):
    def run(self, arguments: list[str], *, timeout_seconds: int) -> str: ...


class SubprocessCommandRunner:
    def run(self, arguments: list[str], *, timeout_seconds: int) -> str:
        completed = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if completed.returncode:
            error = completed.stderr.strip()[-2000:]
            raise RuntimeError(f"command failed with exit {completed.returncode}: {error}")
        return completed.stdout


@dataclass(frozen=True, slots=True)
class SegmentListEntry:
    filename: str
    source_start_seconds: float
    source_end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.source_end_seconds - self.source_start_seconds


class StreamCapChunkAdapter:
    """Finalizes closed StreamCap TS parts into AssetGraph's immutable store.

    StreamCap resets timestamps for each segment, so the optional segment-list
    start/end values are kept separately and never inferred from the filename.
    """

    def __init__(
        self,
        *,
        streamcap_root: Path,
        storage: SecureStorage,
        settle_seconds: float = 10.0,
        runner: CommandRunner | None = None,
        clock: Any = time.monotonic,
    ):
        if settle_seconds < 1:
            raise ValueError("settle_seconds must be at least one second")
        self.streamcap_root = streamcap_root.expanduser().resolve()
        self.storage = storage
        self.settle_seconds = settle_seconds
        self.runner = runner or SubprocessCommandRunner()
        self.clock = clock
        self._observations: dict[Path, tuple[int, int, float]] = {}

    def scan_ready(self) -> list[Path]:
        now = float(self.clock())
        ready: list[Path] = []
        if not self.streamcap_root.is_dir():
            return ready
        seen: set[Path] = set()
        candidates = (
            path
            for path in self.streamcap_root.rglob("*")
            if path.suffix.lower() == ".ts"
        )
        for path in sorted(candidates):
            resolved = path.resolve()
            if not resolved.is_relative_to(self.streamcap_root) or path.is_symlink() or not path.is_file():
                continue
            seen.add(resolved)
            stat_result = resolved.stat()
            current = (stat_result.st_size, stat_result.st_mtime_ns)
            previous = self._observations.get(resolved)
            if previous and previous[:2] == current and now - previous[2] >= self.settle_seconds:
                ready.append(resolved)
            elif previous is None or previous[:2] != current:
                self._observations[resolved] = (*current, now)
        for missing in set(self._observations) - seen:
            self._observations.pop(missing, None)
        return ready

    def finalize(
        self,
        *,
        source: Path,
        session_code: str,
        part_index: int,
        capture_started_at: datetime,
        capture_ended_at: datetime,
        segment_entry: SegmentListEntry | None = None,
        discontinuity_kind: str = "none",
        discontinuity_milliseconds: int = 0,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session_code):
            raise ValueError("session_code must be a safe path component")
        supplied_source = source
        source = source.resolve()
        if (
            not source.is_relative_to(self.streamcap_root)
            or not source.is_file()
            or supplied_source.is_symlink()
        ):
            raise StorageBoundaryError("StreamCap source is outside the staging root")
        if source not in self.scan_ready():
            raise RuntimeError("StreamCap chunk has not reached close/stability quorum")
        if part_index < 0:
            raise ValueError("part_index must be non-negative")
        if capture_ended_at < capture_started_at:
            raise ValueError("capture end cannot precede capture start")

        probe = self.probe(source)
        video_stream = _require_720p_video(probe)
        format_data = probe.get("format") or {}
        duration = float(format_data.get("duration") or 0)
        if duration <= 0:
            raise RuntimeError("ffprobe did not report a positive decoded duration")
        checksum = _sha256_file(source)
        relative_path = f"raw-recordings/{session_code}/chunks/chunk-{part_index:08d}.ts"
        destination = self.storage.resolve(relative_path, create_parent=True)
        if destination.exists():
            if (
                destination.is_symlink()
                or not destination.is_file()
                or destination.stat().st_size != source.stat().st_size
                or _sha256_file(destination) != checksum
            ):
                raise RuntimeError("immutable capture destination already has different content")
        else:
            self._copy_atomic_private(source, destination)
        if destination.stat().st_size != source.stat().st_size or _sha256_file(destination) != checksum:
            destination.unlink(missing_ok=True)
            raise RuntimeError("finalized StreamCap chunk failed size/checksum verification")
        source.unlink()
        self._observations.pop(source, None)

        source_start = segment_entry.source_start_seconds if segment_entry else None
        source_end = segment_entry.source_end_seconds if segment_entry else None
        return {
            "part_index": part_index,
            "relative_path": relative_path,
            "container_format": "mpegts",
            "file_size": destination.stat().st_size,
            "checksum_sha256": checksum,
            "capture_started_at": _utc_text(capture_started_at),
            "capture_ended_at": _utc_text(capture_ended_at),
            "source_start_seconds": source_start,
            "source_end_seconds": source_end,
            "decoded_duration_seconds": duration,
            "stream_timing": _stream_timing(probe),
            "media_probe": {
                "format_name": format_data.get("format_name"),
                "bit_rate": format_data.get("bit_rate"),
                "probe_score": format_data.get("probe_score"),
                "stream_count": len(probe.get("streams") or []),
                "quality_contract": "exact_720p",
                "observed_video_width": int(video_stream["width"]),
                "observed_video_height": int(video_stream["height"]),
                "recorder_version": STREAMCAP_VERSION,
                "recorder_build_fingerprint": STREAMCAP_COMMIT,
                "ffprobe_version": self.ffprobe_version(),
            },
            "discontinuity_kind": discontinuity_kind,
            "discontinuity_milliseconds": discontinuity_milliseconds,
        }

    def probe(self, path: Path) -> dict[str, Any]:
        output = self.runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            timeout_seconds=120,
        )
        value = json.loads(output)
        if not isinstance(value, dict) or not isinstance(value.get("streams"), list):
            raise RuntimeError("ffprobe returned an invalid media document")
        return value

    def ffprobe_version(self) -> str:
        output = self.runner.run(["ffprobe", "-version"], timeout_seconds=10)
        return output.splitlines()[0].strip()[:128]

    def quarantine_orphan(self, source: Path, *, target_code: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", target_code):
            raise ValueError("target_code must be a safe path component")
        supplied = source
        source = source.resolve()
        if (
            not source.is_relative_to(self.streamcap_root)
            or not source.is_file()
            or supplied.is_symlink()
        ):
            raise StorageBoundaryError("orphaned StreamCap part is outside the staging root")
        original_relative = str(source.relative_to(self.streamcap_root))
        original_size = source.stat().st_size
        original_checksum = _sha256_file(source)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source.name)
        relative_path = (
            f"raw-recordings/quarantine/{target_code}/"
            f"{timestamp}-{uuid4().hex}-{safe_name}"
        )
        destination = self.storage.resolve(relative_path, create_parent=True)
        self._copy_atomic_private(source, destination)
        if (
            source.stat().st_size != original_size
            or _sha256_file(source) != original_checksum
            or destination.stat().st_size != original_size
            or _sha256_file(destination) != original_checksum
        ):
            destination.unlink(missing_ok=True)
            raise RuntimeError("orphaned StreamCap part changed during quarantine")
        source.unlink()
        self._observations.pop(source, None)
        return {
            "original_relative_path": original_relative,
            "quarantine_relative_path": relative_path,
            "file_size": original_size,
            "checksum_sha256": original_checksum,
            "reason": "preexisting_staging_part",
        }

    @staticmethod
    def parse_segment_list(path: Path) -> dict[str, SegmentListEntry]:
        entries: dict[str, SegmentListEntry] = {}
        with path.open("r", encoding="utf-8", newline="") as source:
            for row in csv.reader(source):
                if len(row) != 3:
                    raise ValueError("StreamCap segment list must use CSV filename,start,end rows")
                filename, start_text, end_text = row
                if Path(filename).name != filename:
                    raise ValueError("segment-list filenames cannot contain directories")
                start = float(start_text)
                end = float(end_text)
                if start < 0 or end <= start:
                    raise ValueError("segment-list source interval is invalid")
                if filename in entries:
                    raise ValueError("segment-list filename is duplicated")
                entries[filename] = SegmentListEntry(filename, start, end)
        return entries

    @staticmethod
    def _copy_atomic_private(source: Path, destination: Path) -> None:
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with source.open("rb") as input_file, os.fdopen(descriptor, "wb") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise RuntimeError("immutable capture destination already exists") from exc
            temporary.unlink()
            os.chmod(destination, 0o600)
        finally:
            temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_timing(probe: dict[str, Any]) -> dict[str, Any]:
    streams: list[dict[str, Any]] = []
    for stream in probe.get("streams") or []:
        streams.append(
            {
                "index": stream.get("index"),
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "time_base": stream.get("time_base"),
                "start_pts": stream.get("start_pts"),
                "start_time": stream.get("start_time"),
                "duration_ts": stream.get("duration_ts"),
                "duration": stream.get("duration"),
                "average_frame_rate": stream.get("avg_frame_rate"),
                "sample_rate": stream.get("sample_rate"),
                "channels": stream.get("channels"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "tags": stream.get("tags") if isinstance(stream.get("tags"), dict) else {},
            }
        )
    return {"timestamp_policy": "streamcap_reset_timestamps_1", "streams": streams}


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("capture timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_720p_video(probe: dict[str, Any]) -> dict[str, Any]:
    videos = [
        stream
        for stream in probe.get("streams") or []
        if stream.get("codec_type") == "video"
    ]
    if len(videos) != 1:
        raise RuntimeError("capture chunk must contain exactly one video stream")
    video = videos[0]
    try:
        width = int(video["width"])
        height = int(video["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("capture video dimensions are unavailable") from exc
    if sorted((width, height)) != [720, 1280]:
        raise RuntimeError(f"capture resolution {width}x{height} violates exact 720p contract")
    return video

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .permissions import restrict_private_permissions
from .storage import SecureStorage
from .streamcap import CommandRunner, SubprocessCommandRunner


class FFmpegClipper:
    def __init__(self, storage: SecureStorage, runner: CommandRunner | None = None):
        self.storage = storage
        self.runner = runner or SubprocessCommandRunner()

    def execute(self, job: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        chunks = sorted(session.get("chunks") or [], key=lambda item: int(item["part_index"]))
        timeline = sorted(session.get("timeline") or [], key=lambda item: int(item["span_index"]))
        if not chunks or not timeline:
            raise RuntimeError("clip source has no normalized chunks")
        expected_fingerprint = hashlib.sha256(
            "".join(str(chunk.get("checksum_sha256") or "") for chunk in chunks).encode("ascii")
        ).hexdigest()
        if expected_fingerprint != job.get("source_fingerprint"):
            raise RuntimeError("clip source fingerprint changed after the job was created")
        by_code = {str(chunk["chunk_code"]): chunk for chunk in chunks}
        requested_start = float(job["requested_start_seconds"])
        requested_end = float(job["requested_end_seconds"])
        selected = [
            span
            for span in timeline
            if float(span["global_end_seconds"]) > requested_start
            and float(span["global_start_seconds"]) < requested_end
        ]
        if not selected:
            raise RuntimeError("clip request does not intersect the normalized timeline")
        self._require_contiguous(selected, requested_start, requested_end)
        source_paths: list[Path] = []
        for span in selected:
            chunk = by_code.get(str(span["chunk_code"]))
            if chunk is None or chunk.get("status") not in {"finalized", "delete_candidate"}:
                raise RuntimeError("clip source chunk is unavailable")
            source = self.storage.resolve(str(chunk["relative_path"]))
            if not source.is_file() or source.is_symlink():
                raise RuntimeError("clip source file is unavailable")
            if _sha256_file(source) != chunk.get("checksum_sha256"):
                raise RuntimeError("clip source checksum changed")
            source_paths.append(source)

        job_code = str(job["clip_job_code"])
        session_code = str(job["session_code"])
        recipe_path = f"clips/{session_code}/{job_code}/inputs.ffconcat"
        recipe = "ffconcat version 1.0\n" + "".join(
            f"file '{_ffconcat_path(path)}'\n" for path in source_paths
        )
        recipe_file = self.storage.atomic_write(recipe_path, recipe.encode("utf-8"), mode=0o600)
        output_relative = f"clips/{session_code}/{job_code}/clip.mp4"
        output = self.storage.resolve(output_relative, create_parent=True)
        temporary = output.with_name(".clip.mp4.part")
        temporary.unlink(missing_ok=True)

        first = selected[0]
        local_start = requested_start - float(first["global_start_seconds"])
        cut_mode = str(job["cut_mode"])
        actual_start = requested_start
        if cut_mode == "keyframe_copy":
            keyframe = self._previous_keyframe(source_paths[0], local_start)
            actual_start = float(first["global_start_seconds"]) + keyframe
            local_start = keyframe
        duration = requested_end - actual_start
        if duration <= 0:
            raise RuntimeError("clip interval is empty after keyframe alignment")
        arguments = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-protocol_whitelist",
            "file,crypto,data",
            "-i",
            str(recipe_file),
            "-ss",
            f"{local_start:.6f}",
            "-t",
            f"{duration:.6f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
        ]
        if cut_mode == "keyframe_copy":
            arguments.extend(["-c", "copy", "-avoid_negative_ts", "make_zero"])
        else:
            arguments.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "48000",
                    "-movflags",
                    "+faststart",
                ]
            )
        arguments.extend(["-f", "mp4", str(temporary)])
        try:
            self.runner.run(arguments, timeout_seconds=1800)
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise RuntimeError("ffmpeg did not produce a clip")
            restrict_private_permissions(temporary, 0o600)
            os.replace(temporary, output)
            restrict_private_permissions(output, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
        probe = self._probe(output)
        output_duration = float((probe.get("format") or {}).get("duration") or 0)
        if output_duration <= 0:
            output.unlink(missing_ok=True)
            raise RuntimeError("rendered clip has no positive duration")
        return {
            "actual_start_seconds": round(actual_start, 6),
            "actual_end_seconds": round(actual_start + output_duration, 6),
            "output_relative_path": output_relative,
            "output_file_size": output.stat().st_size,
            "output_checksum_sha256": _sha256_file(output),
            "ffmpeg_version": self.runner.run(["ffmpeg", "-version"], timeout_seconds=10)
            .splitlines()[0][:128],
            "ffmpeg_arguments": arguments,
        }

    def _previous_keyframe(self, source: Path, local_start: float) -> float:
        output = self.runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-skip_frame",
                "nokey",
                "-show_frames",
                "-show_entries",
                "frame=best_effort_timestamp_time",
                "-of",
                "json",
                str(source),
            ],
            timeout_seconds=120,
        )
        frames = json.loads(output).get("frames") or []
        timestamps = [
            float(frame["best_effort_timestamp_time"])
            for frame in frames
            if frame.get("best_effort_timestamp_time") is not None
            and float(frame["best_effort_timestamp_time"]) <= local_start
        ]
        return max(timestamps, default=0.0)

    def _probe(self, source: Path) -> dict[str, Any]:
        output = self.runner.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],
            timeout_seconds=120,
        )
        value = json.loads(output)
        if not isinstance(value, dict):
            raise RuntimeError("ffprobe returned an invalid clip document")
        return value

    @staticmethod
    def _require_contiguous(
        spans: list[dict[str, Any]], requested_start: float, requested_end: float
    ) -> None:
        if float(spans[0]["global_start_seconds"]) > requested_start + 0.001:
            raise RuntimeError("clip starts in an unrecorded timeline gap")
        if float(spans[-1]["global_end_seconds"]) + 0.001 < requested_end:
            raise RuntimeError("clip ends in an unrecorded timeline gap")
        previous_end: float | None = None
        for span in spans:
            if float(span.get("chunk_start_seconds") or 0) != 0:
                raise RuntimeError("clip across a deduplicated overlap requires a normalized proxy")
            start = float(span["global_start_seconds"])
            if previous_end is not None and start > previous_end + 0.001:
                raise RuntimeError("clip crosses an unrecorded timeline gap")
            previous_end = float(span["global_end_seconds"])


def _ffconcat_path(path: Path) -> str:
    value = str(path)
    if "\n" in value or "\r" in value or "'" in value:
        raise RuntimeError("ffconcat path contains unsupported characters")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

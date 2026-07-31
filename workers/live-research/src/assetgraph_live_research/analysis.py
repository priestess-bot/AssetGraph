from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

from .permissions import restrict_private_permissions
from .providers import ProviderResult
from .storage import SecureStorage
from .streamcap import CommandRunner, SubprocessCommandRunner


class ASRProvider(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        *,
        strategy_revision: str,
        parameters: dict[str, Any],
        processor_call_audit_code: str,
    ) -> ProviderResult: ...


class LayoutProvider(Protocol):
    def analyze(
        self,
        *,
        run_type: str,
        source_path: Path | None,
        session: dict[str, Any],
        strategy_revision: str,
        parameters: dict[str, Any],
        processor_call_audit_code: str,
    ) -> ProviderResult: ...


class LiveMediaAnalysisExecutor:
    def __init__(
        self,
        *,
        storage: SecureStorage,
        asr_provider: ASRProvider | None = None,
        layout_provider: LayoutProvider | None = None,
        runner: CommandRunner | None = None,
    ):
        self.storage = storage
        self.asr_provider = asr_provider
        self.layout_provider = layout_provider
        self.runner = runner or SubprocessCommandRunner()

    def execute(self, run: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        run_type = str(run["analysis_type"])
        source = self._source_chunk(run, session)
        if run_type == "frame_sampling":
            if source is None:
                raise RuntimeError("frame sampling requires a source chunk")
            return self._sample_frames(run, source)
        if run_type == "asr":
            if source is None:
                raise RuntimeError("ASR requires a source chunk")
            if self.asr_provider is None:
                raise RuntimeError(
                    "OPENAI_API_KEY/ASSETGRAPH_OPENAI_API_KEY is required for ASR analysis"
                )
            return self._transcribe(run, source)
        if run_type in {"ocr", "layout_inference", "template_aggregation"}:
            if self.layout_provider is None:
                raise RuntimeError("no versioned frame/layout provider is configured")
            invocation = self.layout_provider.analyze(
                run_type=run_type,
                source_path=source,
                session=session,
                strategy_revision=str(run["strategy_revision"]),
                parameters=dict(run.get("parameters") or {}),
                processor_call_audit_code=self._processor_audit(run),
            )
            completion = self._write_json_result(run, invocation.content)
            completion["provider_invocation_evidence"] = invocation.evidence
            return completion
        raise RuntimeError(f"unsupported live analysis type: {run_type}")

    def _sample_frames(self, run: dict[str, Any], source: Path) -> dict[str, Any]:
        parameters = dict(run.get("parameters") or {})
        interval = float(parameters.get("interval_seconds", 5.0))
        max_frames = int(parameters.get("max_frames", 720))
        if not 0.5 <= interval <= 60:
            raise ValueError("frame interval must be between 0.5 and 60 seconds")
        if not 1 <= max_frames <= 5000:
            raise ValueError("max_frames must be between 1 and 5000")
        run_root = f"templates/analysis/{run['session_code']}/{run['analysis_run_code']}"
        frames_directory = self.storage.resolve(f"{run_root}/frames", create_parent=True)
        output_pattern = frames_directory / "frame-%08d.jpg"
        self.runner.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-i",
                str(source),
                "-vf",
                f"fps=1/{interval:.6f}",
                "-frames:v",
                str(max_frames),
                "-q:v",
                "2",
                str(output_pattern),
            ],
            timeout_seconds=1800,
        )
        frames: list[dict[str, Any]] = []
        for index, path in enumerate(sorted(frames_directory.glob("frame-*.jpg"))):
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("frame sampler produced an unsafe path")
            restrict_private_permissions(path, 0o600)
            relative = str(path.relative_to(self.storage.root))
            frames.append(
                {
                    "frame_index": index,
                    "timeline_seconds": round(index * interval, 6),
                    "relative_path": relative,
                    "checksum_sha256": _sha256_file(path),
                    "file_size": path.stat().st_size,
                }
            )
        if not frames:
            raise RuntimeError("frame sampler produced no frames")
        result = {
            "contract_version": "frame-observations.v1",
            "sampling_interval_seconds": interval,
            "frame_count": len(frames),
            "frames": frames,
        }
        return self._write_json_result(run, result)

    def _transcribe(self, run: dict[str, Any], source: Path) -> dict[str, Any]:
        run_root = f"templates/analysis/{run['session_code']}/{run['analysis_run_code']}"
        audio_relative = f"{run_root}/audio-16k-mono.wav"
        audio = self.storage.resolve(audio_relative, create_parent=True)
        temporary = audio.with_name(".audio-16k-mono.wav.part")
        temporary.unlink(missing_ok=True)
        try:
            self.runner.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "wav",
                    str(temporary),
                ],
                timeout_seconds=1800,
            )
            if not temporary.is_file() or temporary.stat().st_size <= 44:
                raise RuntimeError("audio extraction produced no usable samples")
            restrict_private_permissions(temporary, 0o600)
            os.replace(temporary, audio)
            restrict_private_permissions(audio, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
        invocation = self.asr_provider.transcribe(
            audio,
            strategy_revision=str(run["strategy_revision"]),
            parameters=dict(run.get("parameters") or {}),
            processor_call_audit_code=self._processor_audit(run),
        )
        result = {
            "contract_version": "asr-observations.v1",
            "audio_relative_path": audio_relative,
            "audio_checksum_sha256": _sha256_file(audio),
            **invocation.content,
        }
        completion = self._write_json_result(run, result)
        completion["provider_invocation_evidence"] = invocation.evidence
        return completion

    def _write_json_result(
        self, run: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        relative = (
            f"templates/analysis/{run['session_code']}/{run['analysis_run_code']}/result.json"
        )
        content = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        path = self.storage.atomic_write(relative, content, mode=0o600)
        return {
            "output_payload": result,
            "output_relative_path": relative,
            "output_checksum_sha256": _sha256_file(path),
        }

    def _source_chunk(
        self, run: dict[str, Any], session: dict[str, Any]
    ) -> Path | None:
        chunk_code = run.get("chunk_code")
        if not chunk_code:
            return None
        chunk = next(
            (
                item
                for item in session.get("chunks") or []
                if item.get("chunk_code") == chunk_code
            ),
            None,
        )
        if chunk is None or chunk.get("status") not in {"finalized", "delete_candidate"}:
            raise RuntimeError("analysis source chunk is unavailable")
        source = self.storage.resolve(str(chunk["relative_path"]))
        if not source.is_file() or source.is_symlink():
            raise RuntimeError("analysis source file is unavailable")
        if _sha256_file(source) != chunk.get("checksum_sha256"):
            raise RuntimeError("analysis source checksum changed")
        return source

    @staticmethod
    def _processor_audit(run: dict[str, Any]) -> str:
        audit_code = str(run.get("_processor_call_audit_code") or "")
        if not audit_code:
            raise RuntimeError("external analysis has no processor authorization audit")
        return audit_code


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

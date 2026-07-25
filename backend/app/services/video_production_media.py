from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from app.services.video_production_models import ArtifactStore, VideoProductionError, sha256_file


ASSET_PATHS = {
    "MT-VID-0016": "视频/MT-VID-0016_视频_酒体视频_品酒大师PRO_酒体.mov",
    "MT-VID-0024": "视频/MT-VID-0024_视频_商品讲解视频_品酒大师PRO.mp4",
    "MT-VID-0027": "视频/MT-VID-0027_视频_品牌TVC_品酒大师_TVC.mp4",
    "MT-DEC-0003": "装饰/MT-DEC-0003_装饰_品牌Logo_logo.png",
    "MT-DEC-0024": "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png",
}

NARRATION_AUDIO_FILTER = (
    "acompressor=threshold=0.063:ratio=6:attack=5:release=120:makeup=4,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


@dataclass(slots=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


@dataclass(slots=True)
class SubprocessRunner:
    heartbeat: Callable[[], None] | None = None
    poll_seconds: float = 1.0
    records: list[dict[str, Any]] = field(default_factory=list)

    def run(
        self,
        args: Sequence[str | Path],
        *,
        timeout_seconds: float = 900.0,
        error_code: str = "MEDIA_COMMAND_FAILED",
    ) -> CommandResult:
        command = [str(value) for value in args]
        if not command or any("\x00" in value for value in command):
            raise VideoProductionError("INVALID_MEDIA_COMMAND", "media command contains an invalid argument")
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout = ""
        stderr = ""
        try:
            while True:
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise VideoProductionError(
                        "MEDIA_COMMAND_TIMEOUT",
                        f"media command timed out after {timeout_seconds:.0f}s: {command[0]}",
                    )
                try:
                    stdout, stderr = process.communicate(timeout=min(self.poll_seconds, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if self.heartbeat is not None:
                        self.heartbeat()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        elapsed = time.monotonic() - started
        result = CommandResult(command, int(process.returncode or 0), stdout, stderr, elapsed)
        self.records.append(
            {
                "args": command,
                "returncode": result.returncode,
                "elapsed_seconds": round(elapsed, 3),
                "stderr_tail": stderr[-2000:],
            }
        )
        if result.returncode != 0:
            detail = stderr[-1200:].strip() or stdout[-1200:].strip() or "no diagnostic output"
            raise VideoProductionError(error_code, f"{Path(command[0]).name} failed: {detail}")
        return result


class AssetSelector:
    def __init__(self, assets_root: Path, runner: SubprocessRunner) -> None:
        self.assets_root = assets_root.resolve()
        self.runner = runner

    def select(self, shot_list: dict[str, Any]) -> dict[str, Any]:
        brand_logo = self._brand_logo(shot_list)
        product_sticker = self._product_sticker(shot_list)
        shot_sources: dict[str, dict[str, str]] = {}
        for shot in shot_list.get("shots") or []:
            asset_code = str(shot["asset_code"])
            relative_path = str(shot.get("asset_relative_path") or "").strip()
            expected_checksum = str(shot.get("asset_expected_checksum") or "").strip()
            if not relative_path:
                continue
            source = {"relative_path": relative_path, "expected_checksum": expected_checksum}
            existing = shot_sources.setdefault(asset_code, source)
            if existing != source:
                raise VideoProductionError(
                    "VISUAL_ASSET_SOURCE_CONFLICT",
                    f"asset {asset_code} resolves to conflicting material sources",
                )
        selected_codes = {str(shot["asset_code"]) for shot in shot_list.get("shots") or []}
        if brand_logo is None:
            selected_codes.add("MT-DEC-0003")
        if product_sticker is None:
            selected_codes.add("MT-DEC-0024")
        assets: list[dict[str, Any]] = []
        for asset_code in sorted(selected_codes):
            source = shot_sources.get(asset_code)
            relative_path = source["relative_path"] if source else ASSET_PATHS.get(asset_code)
            if relative_path is None:
                raise VideoProductionError("UNKNOWN_VISUAL_ASSET", f"no local source was selected for asset {asset_code}")
            path = self.resolve(relative_path)
            checksum = sha256_file(path)
            if source and source["expected_checksum"] and checksum != source["expected_checksum"]:
                raise VideoProductionError(
                    "SOURCE_ASSET_CHECKSUM_MISMATCH",
                    f"selected source asset checksum changed: {asset_code}",
                )
            item: dict[str, Any] = {
                "asset_code": asset_code,
                "relative_path": relative_path,
                "file_size": path.stat().st_size,
                "checksum_sha256": checksum,
            }
            if asset_code in shot_sources or asset_code.startswith("MT-VID-"):
                probe = probe_media(path, self.runner)
                item.update(_video_summary(probe))
            else:
                item["media_type"] = "image"
            assets.append(item)

        background_music = self._background_music(shot_list)
        sound_effect = self._sound_effect(shot_list)
        if brand_logo is not None:
            assets.append(
                {
                    "asset_code": brand_logo["asset_code"],
                    "relative_path": brand_logo["relative_path"],
                    "file_size": brand_logo["file_size"],
                    "checksum_sha256": brand_logo["checksum_sha256"],
                    "media_type": "image",
                }
            )
        if product_sticker is not None:
            assets.append(
                {
                    "asset_code": product_sticker["asset_code"],
                    "relative_path": product_sticker["relative_path"],
                    "file_size": product_sticker["file_size"],
                    "checksum_sha256": product_sticker["checksum_sha256"],
                    "media_type": "image",
                }
            )
        if background_music is not None:
            assets.append(
                {
                    "asset_code": background_music["asset_code"],
                    "relative_path": background_music["relative_path"],
                    "file_size": background_music["file_size"],
                    "checksum_sha256": background_music["checksum_sha256"],
                    "media_type": "audio",
                    "duration_seconds": background_music["duration_seconds"],
                }
            )
        if sound_effect is not None:
            assets.append(
                {
                    "asset_code": sound_effect["asset_code"],
                    "relative_path": sound_effect["relative_path"],
                    "file_size": sound_effect["file_size"],
                    "checksum_sha256": sound_effect["checksum_sha256"],
                    "media_type": "audio",
                    "duration_seconds": sound_effect["duration_seconds"],
                }
            )

        by_code = {asset["asset_code"]: asset for asset in assets}
        for shot in shot_list.get("shots") or []:
            source = by_code[str(shot["asset_code"])]
            duration = float(source.get("duration_seconds") or 0)
            source_start = float(shot["source_start_seconds"])
            source_end = float(shot["source_end_seconds"])
            playback_rate = float(shot.get("playback_rate", 1.0))
            if source_start < 0 or source_end <= source_start:
                raise VideoProductionError(
                    "SOURCE_RANGE_INVALID",
                    f"{shot['shot_code']} has an invalid source range",
                )
            if not math.isfinite(playback_rate) or not 0.5 <= playback_rate <= 2:
                raise VideoProductionError(
                    "PLAYBACK_RATE_INVALID",
                    f"{shot['shot_code']} has an invalid playback rate",
                )
            if source_end > duration + 0.15:
                raise VideoProductionError(
                    "SOURCE_RANGE_OUT_OF_BOUNDS",
                    f"{shot['shot_code']} ends at {source_end:.3f}s but {shot['asset_code']} is {duration:.3f}s",
                )
        return {
            "source": (
                "asset_library_local_video_asset_plan_v1"
                if shot_sources
                else "asset_library_local_audio_asset_plan_v1"
                if background_music is not None or sound_effect is not None
                else "asset_library_local_overlay_asset_plan_v1"
                if brand_logo is not None or product_sticker is not None
                else "fixed_maitu_asset_plan_v1"
            ),
            "assets_root_label": "maitu_materials",
            "asset_count": len(assets),
            "assets": assets,
            "shot_assets": [
                {
                    "shot_index": int(shot["shot_index"]),
                    "asset_code": shot["asset_code"],
                    "relative_path": by_code[str(shot["asset_code"])]["relative_path"],
                    "source_start_seconds": shot["source_start_seconds"],
                    "source_end_seconds": shot["source_end_seconds"],
                    "fit": shot["fit"],
                    "crop_x": shot.get("crop_x", 0.5),
                    "crop_y": shot.get("crop_y", 0.5),
                    "playback_rate": float(shot.get("playback_rate", 1.0)),
                    "overlay_roles": [
                        str(role)
                        for role in shot.get("overlay_roles") or []
                        if str(role) in {"brand_logo", "product_sticker"}
                    ],
                    "product_sticker_layout": shot.get("product_sticker_layout"),
                    "product_sticker_layout_suggestion": shot.get(
                        "product_sticker_layout_suggestion"
                    ),
                    "selection_reason": "operator-selected material-library video" if str(shot.get("visual_role")) == "selected_library_video" else f"preset role: {shot['visual_role']}",
                }
                for shot in shot_list.get("shots") or []
            ],
            "overlays": {
                "brand_logo": (
                    brand_logo["relative_path"]
                    if brand_logo is not None
                    else ASSET_PATHS["MT-DEC-0003"]
                ),
                "product_sticker": (
                    product_sticker["relative_path"]
                    if product_sticker is not None
                    else ASSET_PATHS["MT-DEC-0024"]
                ),
            },
            "brand_logo": brand_logo,
            "product_sticker": product_sticker,
            "background_music": background_music,
            "sound_effect": sound_effect,
        }

    def _brand_logo(self, shot_list: dict[str, Any]) -> dict[str, Any] | None:
        candidate = shot_list.get("brand_logo")
        if candidate is None:
            return None
        if not isinstance(candidate, dict):
            raise VideoProductionError(
                "BRAND_LOGO_INVALID",
                "brand logo selection must be an object",
            )
        asset_code = str(candidate.get("asset_code") or "").strip()
        relative_path = str(candidate.get("asset_relative_path") or "").strip()
        expected_checksum = str(candidate.get("asset_expected_checksum") or "").strip()
        if not asset_code or not relative_path:
            raise VideoProductionError(
                "BRAND_LOGO_INVALID",
                "brand logo must include an asset code and local path",
            )
        path = self.resolve(relative_path)
        checksum = sha256_file(path)
        if not expected_checksum or checksum != expected_checksum:
            raise VideoProductionError(
                "BRAND_LOGO_CHECKSUM_MISMATCH",
                f"selected brand logo checksum changed: {asset_code}",
            )
        return {
            "asset_code": asset_code,
            "relative_path": relative_path,
            "file_size": path.stat().st_size,
            "checksum_sha256": checksum,
        }

    def _product_sticker(self, shot_list: dict[str, Any]) -> dict[str, Any] | None:
        candidate = shot_list.get("product_sticker")
        if candidate is None:
            return None
        if not isinstance(candidate, dict):
            raise VideoProductionError(
                "PRODUCT_STICKER_INVALID",
                "product sticker selection must be an object",
            )
        asset_code = str(candidate.get("asset_code") or "").strip()
        relative_path = str(candidate.get("asset_relative_path") or "").strip()
        expected_checksum = str(candidate.get("asset_expected_checksum") or "").strip()
        if not asset_code or not relative_path:
            raise VideoProductionError(
                "PRODUCT_STICKER_INVALID",
                "product sticker must include an asset code and local path",
            )
        path = self.resolve(relative_path)
        checksum = sha256_file(path)
        if not expected_checksum or checksum != expected_checksum:
            raise VideoProductionError(
                "PRODUCT_STICKER_CHECKSUM_MISMATCH",
                f"selected product sticker checksum changed: {asset_code}",
            )
        return {
            "asset_code": asset_code,
            "relative_path": relative_path,
            "file_size": path.stat().st_size,
            "checksum_sha256": checksum,
        }

    def _background_music(self, shot_list: dict[str, Any]) -> dict[str, Any] | None:
        candidate = shot_list.get("background_music")
        if candidate is None:
            return None
        if not isinstance(candidate, dict):
            raise VideoProductionError(
                "BACKGROUND_MUSIC_INVALID",
                "background music selection must be an object",
            )
        asset_code = str(candidate.get("asset_code") or "").strip()
        relative_path = str(candidate.get("asset_relative_path") or "").strip()
        expected_checksum = str(candidate.get("asset_expected_checksum") or "").strip()
        try:
            gain_db = float(candidate.get("gain_db"))
        except (TypeError, ValueError) as exc:
            raise VideoProductionError(
                "BACKGROUND_MUSIC_GAIN_INVALID",
                "background music gain must be numeric",
            ) from exc
        if not asset_code or not relative_path:
            raise VideoProductionError(
                "BACKGROUND_MUSIC_INVALID",
                "background music must include an asset code and local path",
            )
        if not -36 <= gain_db <= -6:
            raise VideoProductionError(
                "BACKGROUND_MUSIC_GAIN_INVALID",
                "background music gain must remain between -36 dB and -6 dB",
            )
        path = self.resolve(relative_path)
        checksum = sha256_file(path)
        if not expected_checksum or checksum != expected_checksum:
            raise VideoProductionError(
                "BACKGROUND_MUSIC_CHECKSUM_MISMATCH",
                f"selected background music checksum changed: {asset_code}",
            )
        probe = probe_media(path, self.runner)
        streams = list(probe.get("streams") or [])
        if not any(str(stream.get("codec_type") or "") == "audio" for stream in streams):
            raise VideoProductionError(
                "BACKGROUND_MUSIC_AUDIO_STREAM_MISSING",
                f"selected background music has no audio stream: {asset_code}",
            )
        duration = float((probe.get("format") or {}).get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise VideoProductionError(
                "BACKGROUND_MUSIC_DURATION_INVALID",
                f"selected background music has no usable duration: {asset_code}",
            )
        return {
            "asset_code": asset_code,
            "relative_path": relative_path,
            "file_size": path.stat().st_size,
            "checksum_sha256": checksum,
            "duration_seconds": round(duration, 3),
            "gain_db": gain_db,
        }

    def _sound_effect(self, shot_list: dict[str, Any]) -> dict[str, Any] | None:
        candidate = shot_list.get("sound_effect")
        if candidate is None:
            return None
        if not isinstance(candidate, dict):
            raise VideoProductionError(
                "SOUND_EFFECT_INVALID",
                "sound effect selection must be an object",
            )
        asset_code = str(candidate.get("asset_code") or "").strip()
        relative_path = str(candidate.get("asset_relative_path") or "").strip()
        expected_checksum = str(candidate.get("asset_expected_checksum") or "").strip()
        try:
            gain_db = float(candidate.get("gain_db"))
        except (TypeError, ValueError) as exc:
            raise VideoProductionError(
                "SOUND_EFFECT_GAIN_INVALID",
                "sound effect gain must be numeric",
            ) from exc
        if not asset_code or not relative_path:
            raise VideoProductionError(
                "SOUND_EFFECT_INVALID",
                "sound effect must include an asset code and local path",
            )
        if not -24 <= gain_db <= 6:
            raise VideoProductionError(
                "SOUND_EFFECT_GAIN_INVALID",
                "sound effect gain must remain between -24 dB and 6 dB",
            )
        path = self.resolve(relative_path)
        checksum = sha256_file(path)
        if not expected_checksum or checksum != expected_checksum:
            raise VideoProductionError(
                "SOUND_EFFECT_CHECKSUM_MISMATCH",
                f"selected sound effect checksum changed: {asset_code}",
            )
        probe = probe_media(path, self.runner)
        streams = list(probe.get("streams") or [])
        if not any(str(stream.get("codec_type") or "") == "audio" for stream in streams):
            raise VideoProductionError(
                "SOUND_EFFECT_AUDIO_STREAM_MISSING",
                f"selected sound effect has no audio stream: {asset_code}",
            )
        duration = float((probe.get("format") or {}).get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise VideoProductionError(
                "SOUND_EFFECT_DURATION_INVALID",
                f"selected sound effect has no usable duration: {asset_code}",
            )
        return {
            "asset_code": asset_code,
            "relative_path": relative_path,
            "file_size": path.stat().st_size,
            "checksum_sha256": checksum,
            "duration_seconds": round(duration, 3),
            "gain_db": gain_db,
        }

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.assets_root / relative_path).resolve()
        try:
            candidate.relative_to(self.assets_root)
        except ValueError as exc:
            raise VideoProductionError("UNSAFE_ASSET_PATH", "asset path escapes configured root") from exc
        if not candidate.is_file():
            raise VideoProductionError("SOURCE_ASSET_MISSING", f"source asset is missing: {relative_path}")
        return candidate


def probe_media(path: Path, runner: SubprocessRunner) -> dict[str, Any]:
    result = runner.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            path,
        ],
        timeout_seconds=120,
        error_code="FFPROBE_FAILED",
    )
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoProductionError("FFPROBE_INVALID_JSON", f"ffprobe returned invalid JSON for {path.name}") from exc
    if not isinstance(document, dict):
        raise VideoProductionError("FFPROBE_INVALID_JSON", f"ffprobe returned no document for {path.name}")
    return document


def _video_summary(probe: dict[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise VideoProductionError("VIDEO_STREAM_MISSING", "source media has no video stream")
    duration = float((probe.get("format") or {}).get("duration") or video.get("duration") or 0)
    return {
        "media_type": "video",
        "duration_seconds": round(duration, 3),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "codec_name": video.get("codec_name"),
    }


class AudioProcessor:
    def __init__(self, runner: SubprocessRunner) -> None:
        self.runner = runner

    def fit_to_duration(
        self,
        source: Path,
        destination: Path,
        duration_seconds: float,
        *,
        gain_db: float = 0.0,
    ) -> dict[str, Any]:
        probe = probe_media(source, self.runner)
        source_duration = float((probe.get("format") or {}).get("duration") or 0)
        if source_duration <= 0:
            raise VideoProductionError("VOICE_DURATION_INVALID", f"voice audio has no duration: {source.name}")
        tempo = max(1.0, source_duration / duration_seconds)
        speech_duration = min(duration_seconds, source_duration / tempo)
        if not math.isfinite(gain_db) or not -24 <= gain_db <= 12:
            raise VideoProductionError("VOICE_GAIN_INVALID", "voice gain must remain between -24 dB and 12 dB")
        filters = [] if math.isclose(tempo, 1.0, abs_tol=0.0001) else _atempo_filters(tempo)
        if not math.isclose(gain_db, 0.0, abs_tol=0.0001):
            filters.append(f"volume={gain_db:.3f}dB")
        filters.extend([f"apad=pad_dur={duration_seconds:.3f}", f"atrim=0:{duration_seconds:.3f}"])
        temporary = _temporary_media_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
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
                    source,
                    "-af",
                    ",".join(filters),
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s16le",
                    temporary,
                ],
                timeout_seconds=180,
                error_code="VOICE_NORMALIZATION_FAILED",
            )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "source_duration_seconds": round(source_duration, 3),
            "target_duration_seconds": round(duration_seconds, 3),
            "tempo_factor": round(tempo, 4),
            "speech_duration_seconds": round(speech_duration, 3),
            "gain_db": round(gain_db, 3),
        }


def _atempo_filters(factor: float) -> list[str]:
    if not math.isfinite(factor) or factor <= 0:
        raise VideoProductionError("VOICE_TEMPO_INVALID", "voice tempo factor is invalid")
    filters: list[str] = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return filters


def _source_range_filter(
    source_window_seconds: float,
    output_duration_seconds: float,
    playback_rate: float = 1.0,
) -> str:
    """Constrain a source window and loop only that selected window when needed."""
    if not math.isfinite(source_window_seconds) or source_window_seconds <= 0:
        raise VideoProductionError("SOURCE_RANGE_INVALID", "source range duration must be positive")
    if not math.isfinite(output_duration_seconds) or output_duration_seconds <= 0:
        raise VideoProductionError("SHOT_DURATION_INVALID", "rendered shot duration must be positive")
    if not math.isfinite(playback_rate) or not 0.5 <= playback_rate <= 2:
        raise VideoProductionError("PLAYBACK_RATE_INVALID", "playback rate must be between 0.5 and 2")
    required_source_duration = output_duration_seconds * playback_rate
    selected = f"fps=30,trim=duration={source_window_seconds:.3f},setpts=PTS-STARTPTS"
    if required_source_duration > source_window_seconds + 0.01:
        frame_count = max(1, round(source_window_seconds * 30))
        selected = (
            f"{selected},loop=loop=-1:size={frame_count}:start=0,"
            f"trim=duration={required_source_duration:.3f}"
        )
    else:
        selected = f"{selected},trim=duration={required_source_duration:.3f}"
    if playback_rate != 1:
        return (
            f"{selected},setpts=PTS/{playback_rate:.6f},fps=30,"
            f"trim=duration={output_duration_seconds:.3f},setpts=PTS-STARTPTS,setsar=1"
        )
    return f"{selected},setpts=PTS-STARTPTS,setsar=1"


class FFmpegRenderer:
    def __init__(self, assets_root: Path, runner: SubprocessRunner) -> None:
        self.selector = AssetSelector(assets_root, runner)
        self.runner = runner

    def render(
        self,
        *,
        shot_list: dict[str, Any],
        asset_plan: dict[str, Any],
        voice_manifest: dict[str, Any],
        subtitles_path: Path,
        store: ArtifactStore,
    ) -> tuple[Path, dict[str, Any]]:
        shot_paths: list[Path] = []
        logo = self.selector.resolve(str(asset_plan["overlays"]["brand_logo"]))
        sticker = self.selector.resolve(str(asset_plan["overlays"]["product_sticker"]))
        by_shot = {int(item["shot_index"]): item for item in asset_plan["shot_assets"]}
        for shot in shot_list["shots"]:
            shot_index = int(shot["shot_index"])
            source = self.selector.resolve(str(by_shot[shot_index]["relative_path"]))
            output = store.path(f"render/shots/shot-{shot_index + 1:02d}.mp4")
            self._render_shot(source, logo, sticker, shot, output)
            shot_paths.append(output)

        concat_list = store.path("render/video-concat.txt")
        _write_concat_list(concat_list, shot_paths)
        silent_video = store.path("render/silent-video.mp4")
        self._concat_video(concat_list, silent_video)

        voice_paths = [store.output_root / str(item["relative_path"]) for item in voice_manifest["segments"]]
        for path in voice_paths:
            store._assert_below_root(path)
            if not path.is_file():
                raise VideoProductionError("VOICE_ARTIFACT_MISSING", f"voice segment is missing: {path.name}")
        audio_concat_list = store.path("render/audio-concat.txt")
        _write_concat_list(audio_concat_list, voice_paths)
        narration = store.path("render/narration.wav")
        self._concat_audio(audio_concat_list, narration)

        mixed_audio = narration
        background_music = asset_plan.get("background_music")
        sound_effect = asset_plan.get("sound_effect")
        sound_effect_starts = [
            float(shot["start_seconds"])
            for shot in shot_list.get("shots") or []
            if "sound_effect" in (shot.get("audio_roles") or [])
        ]
        if isinstance(background_music, dict) and not (
            isinstance(sound_effect, dict) and sound_effect_starts
        ):
            music = self.selector.resolve(str(background_music["relative_path"]))
            mixed_audio = store.path("render/mixed-audio.wav")
            self._mix_background_music(
                narration,
                music,
                mixed_audio,
                duration_seconds=float(shot_list["duration_seconds"]),
                gain_db=float(background_music["gain_db"]),
            )
        elif isinstance(sound_effect, dict) and sound_effect_starts:
            mixed_audio = store.path("render/mixed-audio.wav")
            self._mix_audio_layers(
                narration,
                mixed_audio,
                duration_seconds=float(shot_list["duration_seconds"]),
                background_music=(
                    (
                        self.selector.resolve(str(background_music["relative_path"])),
                        float(background_music["gain_db"]),
                    )
                    if isinstance(background_music, dict)
                    else None
                ),
                sound_effect=(
                    self.selector.resolve(str(sound_effect["relative_path"])),
                    float(sound_effect["gain_db"]),
                    sound_effect_starts,
                ),
            )

        final_video = store.path("final.mp4")
        self._mux_and_burn_subtitles(silent_video, mixed_audio, subtitles_path, final_video)
        probe = probe_media(final_video, self.runner)
        return final_video, {
            "source": "ffmpeg_render_v1",
            "shot_count": len(shot_paths),
            "video": _video_summary(probe),
            "encoding": {
                "video_codec": "h264",
                "pixel_format": "yuv420p",
                "audio_codec": "aac",
                "audio_sample_rate": 48000,
                "audio_bitrate": "192k",
                "loudness_target_lufs": -16,
                "true_peak_target_db": -1.5,
            },
            "background_music": (
                {
                    "asset_code": str(background_music["asset_code"]),
                    "checksum_sha256": str(background_music["checksum_sha256"]),
                    "gain_db": float(background_music["gain_db"]),
                }
                if isinstance(background_music, dict)
                else None
            ),
            "sound_effect": (
                {
                    "asset_code": str(sound_effect["asset_code"]),
                    "checksum_sha256": str(sound_effect["checksum_sha256"]),
                    "gain_db": float(sound_effect["gain_db"]),
                    "shot_starts_seconds": sound_effect_starts,
                }
                if isinstance(sound_effect, dict) and sound_effect_starts
                else None
            ),
        }

    def _mix_audio_layers(
        self,
        narration: Path,
        destination: Path,
        *,
        duration_seconds: float,
        background_music: tuple[Path, float] | None,
        sound_effect: tuple[Path, float, list[float]] | None,
    ) -> None:
        if not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise VideoProductionError(
                "SOUND_EFFECT_DURATION_INVALID",
                "audio layer mix requires a positive final duration",
            )
        inputs: list[str | Path] = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            narration,
        ]
        filter_parts = [
            f"[0:a]atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[voice]"
        ]
        labels = ["[voice]"]
        next_input = 1
        if background_music is not None:
            music, gain_db = background_music
            if not -36 <= gain_db <= -6:
                raise VideoProductionError(
                    "BACKGROUND_MUSIC_GAIN_INVALID",
                    "background music gain must remain between -36 dB and -6 dB",
                )
            inputs.extend(["-stream_loop", "-1", "-i", music])
            filter_parts.append(
                f"[{next_input}:a]atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS,"
                f"volume={gain_db:.3f}dB[bgm]"
            )
            labels.append("[bgm]")
            next_input += 1
        if sound_effect is not None:
            effect, gain_db, starts = sound_effect
            if not -24 <= gain_db <= 6:
                raise VideoProductionError(
                    "SOUND_EFFECT_GAIN_INVALID",
                    "sound effect gain must remain between -24 dB and 6 dB",
                )
            for index, start_seconds in enumerate(starts):
                if not math.isfinite(start_seconds) or not 0 <= start_seconds < duration_seconds:
                    raise VideoProductionError(
                        "SOUND_EFFECT_TIMING_INVALID",
                        "sound effect must start inside the final timeline",
                    )
                delay_ms = round(start_seconds * 1_000)
                inputs.extend(["-i", effect])
                label = f"[sfx{index}]"
                filter_parts.append(
                    f"[{next_input}:a]asetpts=PTS-STARTPTS,volume={gain_db:.3f}dB,"
                    f"adelay={delay_ms}:all=1,atrim=duration={duration_seconds:.3f}{label}"
                )
                labels.append(label)
                next_input += 1
        if len(labels) < 2:
            raise VideoProductionError("SOUND_EFFECT_MIX_INVALID", "audio layer mix needs at least one overlay")
        filter_parts.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[mixed]"
        )
        temporary = _temporary_media_path(destination)
        temporary.unlink(missing_ok=True)
        try:
            self.runner.run(
                [
                    *inputs,
                    "-filter_complex",
                    ";".join(filter_parts),
                    "-map",
                    "[mixed]",
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s16le",
                    temporary,
                ],
                timeout_seconds=600,
                error_code="SOUND_EFFECT_MIX_FAILED",
            )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _mix_background_music(
        self,
        narration: Path,
        music: Path,
        destination: Path,
        *,
        duration_seconds: float,
        gain_db: float,
    ) -> None:
        if not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise VideoProductionError(
                "BACKGROUND_MUSIC_DURATION_INVALID",
                "background music mix requires a positive final duration",
            )
        if not math.isfinite(gain_db) or not -36 <= gain_db <= -6:
            raise VideoProductionError(
                "BACKGROUND_MUSIC_GAIN_INVALID",
                "background music gain must remain between -36 dB and -6 dB",
            )
        temporary = _temporary_media_path(destination)
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
                    narration,
                    "-stream_loop",
                    "-1",
                    "-i",
                    music,
                    "-filter_complex",
                    (
                        f"[0:a]atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[voice];"
                        f"[1:a]atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS,"
                        f"volume={gain_db:.3f}dB[bgm];"
                        "[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed]"
                    ),
                    "-map",
                    "[mixed]",
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s16le",
                    temporary,
                ],
                timeout_seconds=600,
                error_code="BACKGROUND_MUSIC_MIX_FAILED",
            )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _render_shot(
        self,
        source: Path,
        logo: Path,
        sticker: Path,
        shot: dict[str, Any],
        destination: Path,
    ) -> None:
        duration = float(shot["duration_seconds"])
        source_start = float(shot["source_start_seconds"])
        source_end = float(shot["source_end_seconds"])
        source_window = source_end - source_start
        if source_start < 0 or source_window <= 0:
            raise VideoProductionError(
                "SOURCE_RANGE_INVALID",
                "rendered shot source range must have a non-negative start and positive duration",
            )
        crop_x = float(shot.get("crop_x", 0.5))
        crop_y = float(shot.get("crop_y", 0.5))
        if not 0 <= crop_x <= 1 or not 0 <= crop_y <= 1:
            raise VideoProductionError(
                "CROP_POSITION_INVALID",
                "rendered shot crop position must be normalized between zero and one",
            )
        temporary = _temporary_media_path(destination)
        temporary.unlink(missing_ok=True)
        args: list[str | Path] = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
        ]
        args.extend(
            [
                "-ss",
                f"{source_start:.3f}",
                "-i",
                source,
            ]
        )

        has_logo = "brand_logo" in (shot.get("overlay_roles") or [])
        has_sticker = "product_sticker" in (shot.get("overlay_roles") or [])
        logo_input_index: int | None = None
        sticker_input_index: int | None = None
        next_input_index = 1
        if has_logo:
            logo_input_index = next_input_index
            next_input_index += 1
            args.extend(["-loop", "1", "-framerate", "30", "-i", logo])
        if has_sticker:
            sticker_input_index = next_input_index
            args.extend(["-loop", "1", "-framerate", "30", "-i", sticker])

        source_filter = _source_range_filter(source_window, duration, float(shot.get("playback_rate", 1.0)))
        filter_parts: list[str] = []
        if (shot.get("fit") or "cover") == "contain":
            filter_parts.extend(
                [
                    f"[0:v]{source_filter},split=2[bgsrc][fgsrc]",
                    "[bgsrc]scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,gblur=sigma=24:steps=2,"
                    "eq=saturation=0.55:brightness=-0.14[bg]",
                    "[fgsrc]scale=1080:1920:force_original_aspect_ratio=decrease[fg]",
                    "[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1[base]",
                ]
            )
        else:
            filter_parts.append(
                f"[0:v]{source_filter},scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920:x=(in_w-out_w)*{crop_x:.3f}:y=(in_h-out_h)*{crop_y:.3f}[base]"
            )

        presentation_filters = ["format=yuv420p"]
        transition = str(shot.get("transition") or "cut")
        fade_duration = min(0.3, duration / 2 if transition == "fade" else duration)
        if transition == "fade":
            presentation_filters.extend(
                [
                    f"fade=t=in:st=0:d={fade_duration:.3f}",
                    f"fade=t=out:st={max(0.0, duration - fade_duration):.3f}:d={fade_duration:.3f}",
                ]
            )
        elif transition == "fade_out":
            presentation_filters.append(
                f"fade=t=out:st={max(0.0, duration - fade_duration):.3f}:d={fade_duration:.3f}"
            )
        presented_label = "presented"
        filter_parts.append(f"[base]{','.join(presentation_filters)}[{presented_label}]")
        current_label = presented_label
        if has_logo:
            assert logo_input_index is not None
            filter_parts.extend(
                [
                    f"[{logo_input_index}:v]scale=108:108:force_original_aspect_ratio=decrease,"
                    "format=rgba,colorchannelmixer=aa=0.96[logo]",
                    f"[{current_label}][logo]overlay=x=54:y=54:shortest=1[with_logo]",
                ]
            )
            current_label = "with_logo"
        if has_sticker:
            assert sticker_input_index is not None
            sticker_layout = shot.get("product_sticker_layout")
            if sticker_layout is None:
                sticker_width = 640
                sticker_x_expression = "(W-w)/2"
                sticker_y_expression = "1020"
            elif isinstance(sticker_layout, dict):
                try:
                    sticker_x = float(sticker_layout["x"])
                    sticker_y = float(sticker_layout["y"])
                    sticker_width_ratio = float(sticker_layout["width_ratio"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise VideoProductionError(
                        "PRODUCT_STICKER_LAYOUT_INVALID",
                        "Product sticker layout must provide normalized x, y and width ratio",
                    ) from exc
                if (
                    not math.isfinite(sticker_x)
                    or not math.isfinite(sticker_y)
                    or not math.isfinite(sticker_width_ratio)
                    or not 0 <= sticker_x <= 1
                    or not 0 <= sticker_y <= 1
                    or not 0.1 <= sticker_width_ratio <= 1
                ):
                    raise VideoProductionError(
                        "PRODUCT_STICKER_LAYOUT_INVALID",
                        "Product sticker layout must stay inside the canvas",
                    )
                sticker_width = max(1, round(1080 * sticker_width_ratio))
                sticker_x_expression = f"(W-w)*{sticker_x:.3f}"
                sticker_y_expression = f"(H-h)*{sticker_y:.3f}"
            else:
                raise VideoProductionError(
                    "PRODUCT_STICKER_LAYOUT_INVALID",
                    "Product sticker layout must be an object",
                )
            filter_parts.extend(
                [
                    f"[{sticker_input_index}:v]scale={sticker_width}:{sticker_width}:force_original_aspect_ratio=decrease,"
                    "format=rgba[sticker]",
                    f"[{current_label}][sticker]overlay=x={sticker_x_expression}:y={sticker_y_expression}:shortest=1[with_sticker]",
                ]
            )
            current_label = "with_sticker"
        filter_parts.append(f"[{current_label}]null[v]")
        args.extend(["-filter_complex", ";".join(filter_parts), "-map", "[v]"])
        args.extend(
            [
                "-t",
                f"{duration:.3f}",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                temporary,
            ]
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.runner.run(args, timeout_seconds=1200, error_code="SHOT_RENDER_FAILED")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _concat_video(self, concat_list: Path, destination: Path) -> None:
        temporary = _temporary_media_path(destination)
        try:
            self.runner.run(
                [
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
                    "-i",
                    concat_list,
                    "-c",
                    "copy",
                    temporary,
                ],
                timeout_seconds=300,
                error_code="VIDEO_CONCAT_FAILED",
            )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _concat_audio(self, concat_list: Path, destination: Path) -> None:
        temporary = _temporary_media_path(destination)
        try:
            self.runner.run(
                [
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
                    "-i",
                    concat_list,
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s16le",
                    temporary,
                ],
                timeout_seconds=300,
                error_code="AUDIO_CONCAT_FAILED",
            )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _mux_and_burn_subtitles(
        self,
        video: Path,
        audio: Path,
        subtitles: Path,
        destination: Path,
    ) -> None:
        temporary = _temporary_media_path(destination)
        ass_filter = f"ass=filename='{_escape_filter_path(subtitles)}'"
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
                    video,
                    "-i",
                    audio,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-vf",
                    ass_filter,
                    "-af",
                    NARRATION_AUDIO_FILTER,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
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
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    temporary,
                ],
                timeout_seconds=1800,
                error_code="FINAL_RENDER_FAILED",
            )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


class VideoQualityInspector:
    def __init__(self, runner: SubprocessRunner) -> None:
        self.runner = runner

    def inspect(
        self,
        video: Path,
        *,
        target_duration_seconds: float,
        enforce_demo_duration: bool = True,
    ) -> dict[str, Any]:
        probe = probe_media(video, self.runner)
        streams = probe.get("streams") or []
        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        duration = float((probe.get("format") or {}).get("duration") or video_stream.get("duration") or 0)
        black_segments = self._black_segments(video)
        silence_segments = self._silence_segments(video, duration)
        freeze_segments = self._freeze_segments(video, duration)
        loudness = self._loudness(video)
        checks = {
            "duration_matches_plan": abs(duration - target_duration_seconds) <= 1.0,
            "duration_in_demo_range": (30 <= duration <= 120) if enforce_demo_duration else duration > 0,
            "resolution_1080x1920": int(video_stream.get("width") or 0) == 1080
            and int(video_stream.get("height") or 0) == 1920,
            "video_codec_h264": video_stream.get("codec_name") == "h264",
            "audio_codec_aac": audio_stream.get("codec_name") == "aac",
            "audio_present": bool(audio_stream),
            "no_long_black_frame": not any(float(item.get("duration_seconds") or 0) >= 2 for item in black_segments),
            "no_long_silence": not any(float(item.get("duration_seconds") or 0) >= 4 for item in silence_segments),
            "no_long_freeze": not any(float(item.get("duration_seconds") or 0) >= 2 for item in freeze_segments),
            "loudness_target_met": _loudness_passes(loudness),
        }
        return {
            "source": "ffmpeg_quality_gate_v1",
            "passed": all(checks.values()),
            "checks": checks,
            "media": {
                "duration_seconds": round(duration, 3),
                "width": int(video_stream.get("width") or 0),
                "height": int(video_stream.get("height") or 0),
                "video_codec": video_stream.get("codec_name"),
                "pixel_format": video_stream.get("pix_fmt"),
                "audio_codec": audio_stream.get("codec_name"),
                "audio_sample_rate": int(audio_stream.get("sample_rate") or 0),
            },
            "black_segments": black_segments,
            "silence_segments": silence_segments,
            "freeze_segments": freeze_segments,
            "loudness": loudness,
        }

    def _black_segments(self, video: Path) -> list[dict[str, float]]:
        result = self.runner.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                video,
                "-an",
                "-vf",
                "blackdetect=d=0.5:pix_th=0.10",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=600,
            error_code="BLACK_FRAME_CHECK_FAILED",
        )
        return [
            {
                "start_seconds": float(match.group(1)),
                "end_seconds": float(match.group(2)),
                "duration_seconds": float(match.group(3)),
            }
            for match in re.finditer(
                r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)",
                result.stderr,
            )
        ]

    def _silence_segments(self, video: Path, duration: float) -> list[dict[str, float]]:
        result = self.runner.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                video,
                "-vn",
                "-af",
                "silencedetect=noise=-45dB:d=2",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=600,
            error_code="SILENCE_CHECK_FAILED",
        )
        starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", result.stderr)]
        ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", result.stderr)]
        segments: list[dict[str, float]] = []
        for index, start in enumerate(starts):
            end = ends[index] if index < len(ends) else duration
            segments.append(
                {
                    "start_seconds": start,
                    "end_seconds": end,
                    "duration_seconds": max(0.0, end - start),
                }
            )
        return segments

    def _freeze_segments(self, video: Path, duration: float) -> list[dict[str, float]]:
        result = self.runner.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                video,
                "-an",
                "-vf",
                "freezedetect=n=-50dB:d=2",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=600,
            error_code="FREEZE_FRAME_CHECK_FAILED",
        )
        starts = [
            float(value)
            for value in re.findall(r"freezedetect\.freeze_start:\s*([0-9.]+)", result.stderr)
        ]
        ends = [
            float(value)
            for value in re.findall(r"freezedetect\.freeze_end:\s*([0-9.]+)", result.stderr)
        ]
        durations = [
            float(value)
            for value in re.findall(r"freezedetect\.freeze_duration:\s*([0-9.]+)", result.stderr)
        ]
        segments: list[dict[str, float]] = []
        for index, start in enumerate(starts):
            end = ends[index] if index < len(ends) else duration
            freeze_duration = durations[index] if index < len(durations) else max(0.0, end - start)
            segments.append(
                {
                    "start_seconds": start,
                    "end_seconds": end,
                    "duration_seconds": freeze_duration,
                }
            )
        return segments

    def _loudness(self, video: Path) -> dict[str, float | None]:
        result = self.runner.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-i",
                video,
                "-vn",
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=600,
            error_code="LOUDNESS_CHECK_FAILED",
        )
        matches = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, flags=re.S)
        if not matches:
            return {"integrated_lufs": None, "true_peak_db": None, "lra": None}
        try:
            document = json.loads(matches[-1])
            return {
                "integrated_lufs": float(document["input_i"]),
                "true_peak_db": float(document["input_tp"]),
                "lra": float(document["input_lra"]),
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {"integrated_lufs": None, "true_peak_db": None, "lra": None}


def _loudness_passes(loudness: dict[str, float | None]) -> bool:
    integrated = loudness.get("integrated_lufs")
    true_peak = loudness.get("true_peak_db")
    return integrated is not None and true_peak is not None and -18 <= integrated <= -14 and true_peak <= -1.0


def _temporary_media_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.stem}.{os.getpid()}.part{destination.suffix}")


def _write_concat_list(destination: Path, paths: list[Path]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"file '{_escape_concat_path(path.resolve())}'\n" for path in paths)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _escape_concat_path(path: Path) -> str:
    value = str(path)
    if "\n" in value or "\r" in value:
        raise VideoProductionError("UNSAFE_MEDIA_PATH", "media path contains a newline")
    return value.replace("'", "'\\''")


def _escape_filter_path(path: Path) -> str:
    value = str(path.resolve())
    if "\n" in value or "\r" in value:
        raise VideoProductionError("UNSAFE_MEDIA_PATH", "subtitle path contains a newline")
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

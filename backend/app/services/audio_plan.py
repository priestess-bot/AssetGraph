from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AudioPlanError(ValueError):
    """Raised when a scene cannot satisfy the live-room audio policy."""


@dataclass(frozen=True, slots=True)
class AudioInterval:
    layer_id: str
    lane: str
    start_seconds: float
    end_seconds: float


class AudioPlanValidator:
    """Normalize and validate the one-speech plus one-BGM policy."""

    AUDIO_SOURCE_TYPES = frozenset({"audio", "video", "decorative_video", "digital_human"})
    ENABLED_ROLES = frozenset({"speech", "bgm", "original_audio"})
    CLASSIFIED_AUDIO = frozenset({"speech", "music"})

    def normalize_scenes(self, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for scene in scenes:
            item = dict(scene)
            scene_duration = self._number(scene.get("duration_seconds"))
            layers = [
                self.normalize_layer(layer, scene_duration=scene_duration)
                for layer in (scene.get("layers") or [])
                if isinstance(layer, dict)
            ]
            self._validate_intervals(layers)
            item["layers"] = layers
            normalized.append(item)
        return normalized

    def normalize_layer(self, layer: dict[str, Any], *, scene_duration: float | None = None) -> dict[str, Any]:
        item = dict(layer)
        source_type = str(item.get("source_material_type") or "").strip().lower()
        requested_enabled = item.get("sound_enabled") is True
        role = str(item.get("audio_role") or "muted").strip().lower()
        classification = str(item.get("audio_classification_status") or "unknown").strip().lower()
        audio_class = str(item.get("audio_class") or "unknown").strip().lower()

        if source_type not in self.AUDIO_SOURCE_TYPES:
            requested_enabled = False
            role = "muted"
        if not requested_enabled:
            role = "muted"
        elif role not in self.ENABLED_ROLES:
            raise AudioPlanError(f"layer {self._layer_id(item)!r} enables sound without a supported audio role")
        elif role == "original_audio":
            if classification != "classified" or audio_class not in self.CLASSIFIED_AUDIO:
                raise AudioPlanError(
                    f"layer {self._layer_id(item)!r} original audio must be classified as speech or music"
                )

        start = self._number(item.get("audio_start_seconds")) or 0.0
        end = self._number(item.get("audio_end_seconds"))
        if end is None:
            end = scene_duration if scene_duration and scene_duration > 0 else start + 1.0
        if start < 0 or end <= start:
            raise AudioPlanError(f"layer {self._layer_id(item)!r} has an invalid audio interval")

        item.update(
            {
                "sound_enabled": requested_enabled,
                "audio_role": role,
                "audio_classification_status": classification,
                "audio_class": audio_class,
                "audio_start_seconds": start,
                "audio_end_seconds": end,
            }
        )
        return item

    def _validate_intervals(self, layers: list[dict[str, Any]]) -> None:
        intervals: list[AudioInterval] = []
        for layer in layers:
            if layer.get("sound_enabled") is not True:
                continue
            role = str(layer.get("audio_role") or "")
            audio_class = str(layer.get("audio_class") or "unknown")
            lane = "speech" if role == "speech" or (role == "original_audio" and audio_class == "speech") else "bgm"
            intervals.append(
                AudioInterval(
                    layer_id=self._layer_id(layer),
                    lane=lane,
                    start_seconds=float(layer["audio_start_seconds"]),
                    end_seconds=float(layer["audio_end_seconds"]),
                )
            )

        for lane in ("speech", "bgm"):
            lane_intervals = sorted(
                (interval for interval in intervals if interval.lane == lane),
                key=lambda interval: (interval.start_seconds, interval.end_seconds, interval.layer_id),
            )
            for previous, current in zip(lane_intervals, lane_intervals[1:], strict=False):
                if current.start_seconds < previous.end_seconds:
                    raise AudioPlanError(
                        f"audio lane {lane!r} overlaps between {previous.layer_id!r} and {current.layer_id!r}"
                    )

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise AudioPlanError("audio interval values must be numeric") from exc

    @staticmethod
    def _layer_id(layer: dict[str, Any]) -> str:
        return str(layer.get("layer_id") or layer.get("layer_type") or "unknown-layer")

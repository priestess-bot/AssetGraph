from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TimelineAssembler:
    tolerance_seconds: float = 0.001
    spans: list[dict[str, Any]] = field(default_factory=list)

    def append(self, chunk: dict[str, Any]) -> dict[str, Any]:
        duration = float(chunk["decoded_duration_seconds"])
        if duration <= 0:
            raise ValueError("chunk duration must be positive")
        span_index = len(self.spans)
        previous_end = float(self.spans[-1]["global_end_seconds"]) if self.spans else 0.0
        kind = str(chunk.get("discontinuity_kind") or "none")
        discontinuity_ms = int(chunk.get("discontinuity_milliseconds") or 0)
        gap_seconds = 0.0
        chunk_start = 0.0
        if kind in {"gap", "reconnect", "unknown"} and discontinuity_ms > 0:
            gap_seconds = discontinuity_ms / 1000.0
        elif kind == "overlap" and discontinuity_ms:
            chunk_start = min(abs(discontinuity_ms) / 1000.0, max(0.0, duration - 0.001))
        global_start = previous_end + gap_seconds
        mapped_duration = duration - chunk_start
        global_end = global_start + mapped_duration
        if mapped_duration <= 0:
            raise ValueError("overlap consumes the complete chunk")

        has_source_clock = (
            chunk.get("source_start_seconds") is not None
            and chunk.get("source_end_seconds") is not None
        )
        confidence = 1.0 if has_source_clock else 0.95
        if kind in {"reconnect", "unknown"}:
            confidence = min(confidence, 0.75)
        span = {
            "chunk_code": chunk["chunk_code"],
            "span_index": span_index,
            "contract_version": "media-timeline.v1",
            "global_start_seconds": round(global_start, 6),
            "global_end_seconds": round(global_end, 6),
            "chunk_start_seconds": round(chunk_start, 6),
            "chunk_end_seconds": round(duration, 6),
            "wall_start_at": chunk.get("capture_started_at"),
            "wall_end_at": chunk.get("capture_ended_at"),
            "mapping_slope": 1.0,
            "confidence": confidence,
            "discontinuity_before": kind,
            "mapping": {
                "source_start_seconds": chunk.get("source_start_seconds"),
                "source_end_seconds": chunk.get("source_end_seconds"),
                "timestamp_policy": "streamcap_reset_timestamps_1",
                "mapping_basis": "segment_source_clock"
                if has_source_clock
                else "decoded_duration_and_order",
                "discontinuity_milliseconds": discontinuity_ms,
                "overlap_trimmed_seconds": round(chunk_start, 6),
                "gap_preserved_seconds": round(gap_seconds, 6),
            },
        }
        self.spans.append(span)
        return span


def channel_payloads(stream_timing: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    type_indexes: dict[str, int] = {}
    for stream in stream_timing.get("streams") or []:
        media_kind = str(stream.get("codec_type") or "data")
        if media_kind not in {"video", "audio", "data"}:
            media_kind = "data"
        stream_index = type_indexes.get(media_kind, 0)
        type_indexes[media_kind] = stream_index + 1
        payloads.append(
            {
                "channel_key": f"{media_kind}:{stream_index}",
                "media_kind": media_kind,
                "stream_index": stream_index,
                "codec_name": stream.get("codec_name"),
                "time_base": stream.get("time_base"),
                "sample_rate": _positive_int(stream.get("sample_rate")),
                "channels": _positive_int(stream.get("channels")),
                "width": _positive_int(stream.get("width")),
                "height": _positive_int(stream.get("height")),
                "language": (stream.get("tags") or {}).get("language"),
                "average_frame_rate": stream.get("average_frame_rate"),
                "metadata": {"source_stream_index": stream.get("index")},
            }
        )
    return payloads


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

from __future__ import annotations

from assetgraph_live_research.timeline import TimelineAssembler, channel_payloads


def _chunk(code: str, duration: float, kind: str = "none", milliseconds: int = 0):
    return {
        "chunk_code": code,
        "decoded_duration_seconds": duration,
        "discontinuity_kind": kind,
        "discontinuity_milliseconds": milliseconds,
        "capture_started_at": "2026-07-20T00:00:00Z",
        "capture_ended_at": "2026-07-20T00:10:00Z",
    }


def test_timeline_preserves_gap_and_trims_overlap() -> None:
    timeline = TimelineAssembler()
    first = timeline.append(_chunk("chunk_1", 600))
    second = timeline.append(_chunk("chunk_2", 600, "gap", 2500))
    third = timeline.append(_chunk("chunk_3", 600, "overlap", -1250))

    assert first["confidence"] == 0.95
    assert second["global_start_seconds"] == 602.5
    assert second["mapping"]["gap_preserved_seconds"] == 2.5
    assert third["chunk_start_seconds"] == 1.25
    assert third["global_start_seconds"] == second["global_end_seconds"]


def test_channel_payloads_preserve_probe_geometry_and_audio_shape() -> None:
    payloads = channel_payloads(
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 720,
                    "height": 1280,
                    "avg_frame_rate": "30/1",
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "tags": {"language": "zho"},
                },
            ]
        }
    )

    assert payloads[0]["width"] == 720
    assert payloads[0]["height"] == 1280
    assert payloads[1]["sample_rate"] == 48000
    assert payloads[1]["channels"] == 2
    assert payloads[1]["language"] == "zho"

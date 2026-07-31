from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from assetgraph_live_research.sidecars import StreamCapTargetConfig
from assetgraph_live_research.storage import SecureStorage
from assetgraph_live_research.streamcap import StreamCapChunkAdapter


class _Runner:
    def __init__(self, width: int = 720, height: int = 1280):
        self.width = width
        self.height = height

    def run(self, arguments: list[str], *, timeout_seconds: int) -> str:
        del timeout_seconds
        if arguments[:2] == ["ffprobe", "-version"]:
            return "ffprobe version 7.1\n"
        return json.dumps(
            {
                "format": {"duration": "10.0", "format_name": "mpegts"},
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": self.width,
                        "height": self.height,
                        "time_base": "1/90000",
                        "avg_frame_rate": "30/1",
                    },
                    {
                        "index": 1,
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channels": 2,
                    },
                ],
            }
        )


def test_streamcap_target_config_is_exact_single_720p_ts_target(tmp_path: Path) -> None:
    path = tmp_path / "recordings.json"
    StreamCapTargetConfig(path).write_single_target(
        {
            "target_code": "target_1",
            "room_url": "https://live.douyin.com/123456",
            "display_name": "research room",
        }
    )

    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["quality"] == "HD"
    assert rows[0]["record_format"] == "TS"
    assert rows[0]["segment_record"] is True
    assert rows[0]["segment_time"] == "600"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_streamcap_adapter_accepts_uppercase_ts_and_enforces_720p(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "part_000.TS"
    source.write_bytes(b"transport-stream")
    clock = [0.0]
    adapter = StreamCapChunkAdapter(
        streamcap_root=staging,
        storage=SecureStorage(tmp_path / "store"),
        settle_seconds=1,
        runner=_Runner(),
        clock=lambda: clock[0],
    )
    assert adapter.scan_ready() == []
    clock[0] = 2
    assert adapter.scan_ready() == [source.resolve()]
    started = datetime.now(UTC) - timedelta(seconds=10)
    manifest = adapter.finalize(
        source=source,
        session_code="capture_1",
        part_index=0,
        capture_started_at=started,
        capture_ended_at=started + timedelta(seconds=10),
    )

    assert manifest["media_probe"]["quality_contract"] == "exact_720p"
    assert manifest["stream_timing"]["streams"][0]["width"] == 720
    assert not source.exists()


def test_streamcap_adapter_rejects_non_720p_source(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "part.ts"
    source.write_bytes(b"transport-stream")
    clock = [0.0]
    adapter = StreamCapChunkAdapter(
        streamcap_root=staging,
        storage=SecureStorage(tmp_path / "store"),
        settle_seconds=1,
        runner=_Runner(1080, 1920),
        clock=lambda: clock[0],
    )
    adapter.scan_ready()
    clock[0] = 2
    with pytest.raises(RuntimeError, match="exact 720p"):
        adapter.finalize(
            source=source,
            session_code="capture_1",
            part_index=0,
            capture_started_at=datetime.now(UTC) - timedelta(seconds=10),
            capture_ended_at=datetime.now(UTC),
        )
    assert source.exists()


def test_streamcap_adapter_quarantines_preexisting_part_without_ingesting_it(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    source = staging / "old-room.TS"
    source.write_bytes(b"old-room-fragment")
    storage = SecureStorage(tmp_path / "store")
    adapter = StreamCapChunkAdapter(
        streamcap_root=staging,
        storage=storage,
        settle_seconds=1,
        runner=_Runner(),
    )

    manifest = adapter.quarantine_orphan(source, target_code="target_1")

    assert not source.exists()
    quarantined = storage.resolve(manifest["quarantine_relative_path"])
    assert quarantined.read_bytes() == b"old-room-fragment"
    if os.name != "nt":
        assert stat.S_IMODE(quarantined.stat().st_mode) == 0o600
    assert manifest["reason"] == "preexisting_staging_part"

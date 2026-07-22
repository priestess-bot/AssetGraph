from __future__ import annotations

import gzip
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from assetgraph_live_research.storage import (
    RawEventBatchWriter,
    SecureStorage,
    StorageBoundaryError,
)


def test_private_files_are_immutable_and_mode_0600(tmp_path: Path) -> None:
    storage = SecureStorage(tmp_path / "root")
    path = storage.atomic_write("events/session/file.bin", b"first")

    assert path.read_bytes() == b"first"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert storage.atomic_write("events/session/file.bin", b"first") == path
    with pytest.raises(StorageBoundaryError, match="different content"):
        storage.atomic_write("events/session/file.bin", b"second")


def test_internal_symlink_component_is_rejected(tmp_path: Path) -> None:
    storage = SecureStorage(tmp_path / "root")
    real = storage.root / "real"
    real.mkdir(mode=0o700)
    (storage.root / "alias").symlink_to(real, target_is_directory=True)

    with pytest.raises(StorageBoundaryError, match="symlinked"):
        storage.atomic_write("alias/file.bin", b"private")


def test_raw_event_batch_is_deterministic_private_gzip(tmp_path: Path) -> None:
    storage = SecureStorage(tmp_path / "root")
    writer = RawEventBatchWriter(storage)
    finalized = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    events = [
        {
            "event_type": "WebcastChatMessage",
            "received_at": "2026-07-20T11:59:59Z",
            "payload": {"content": "hello"},
        }
    ]

    first = writer.write(
        session_code="capture_000001",
        batch_index=0,
        events=events,
        finalized_at=finalized,
    )
    second = writer.write(
        session_code="capture_000001",
        batch_index=0,
        events=events,
        finalized_at=finalized,
    )

    assert first == second
    assert first["relative_path"] == "events/capture_000001/events-00000000.jsonl.gz"
    assert first["file_mode"] == 0o600
    path = storage.resolve(first["relative_path"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with gzip.open(path, "rt", encoding="utf-8") as source:
        row = json.loads(source.readline())
    assert row["event_type"] == "WebcastChatMessage"

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from app.services.recording_upload import RecordingUploadError, store_recording_upload


def test_recording_upload_is_content_addressed_and_excludes_raw_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.recording_upload.probe_media",
        lambda path: {
            "schema_version": "file-truth-v1",
            "duration_seconds": 42.25,
            "video": {"codec": "h264", "width": 1080, "height": 1920},
            "audio": [{"codec": "aac", "channels": 2}],
            "raw": {"machine_specific": str(path)},
        },
    )
    stored = store_recording_upload(
        BytesIO(b"valid-video-fixture"),
        filename="customer-room.mp4",
        content_type="video/mp4",
        root=tmp_path,
        max_bytes=1024,
    )

    assert stored.file_size == len(b"valid-video-fixture")
    assert stored.relative_path == (
        f"uploads/{stored.checksum_sha256[:2]}/{stored.checksum_sha256}.mp4"
    )
    assert (tmp_path / stored.relative_path).read_bytes() == b"valid-video-fixture"
    assert "raw" not in stored.media_probe


def test_recording_upload_rejects_unsupported_empty_and_oversized_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RecordingUploadError, match="仅支持"):
        store_recording_upload(
            BytesIO(b"data"),
            filename="recording.txt",
            content_type="text/plain",
            root=tmp_path,
            max_bytes=1024,
        )
    with pytest.raises(RecordingUploadError, match="为空"):
        store_recording_upload(
            BytesIO(b""),
            filename="recording.mp4",
            content_type="video/mp4",
            root=tmp_path,
            max_bytes=1024,
        )
    monkeypatch.setattr("app.services.recording_upload.probe_media", lambda _path: {})
    with pytest.raises(RecordingUploadError, match="上传上限") as raised:
        store_recording_upload(
            BytesIO(b"too-large"),
            filename="recording.mp4",
            content_type="video/mp4",
            root=tmp_path,
            max_bytes=4,
        )
    assert raised.value.status_code == 413

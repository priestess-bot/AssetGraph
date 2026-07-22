from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .pins import DOUYINLIVE_COMMIT, DOUYINLIVE_VERSION, STREAMCAP_COMMIT, STREAMCAP_VERSION


REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True, slots=True)
class InstalledSidecars:
    streamcap_checkout: Path = Path(
        os.environ.get("ASSETGRAPH_STREAMCAP_CHECKOUT", REPO_ROOT / ".external/StreamCap")
    )
    streamcap_python: Path = Path(
        os.environ.get(
            "ASSETGRAPH_STREAMCAP_PYTHON",
            REPO_ROOT / ".external/streamcap-venv/bin/python",
        )
    )
    douyinlive_binary: Path = Path(
        os.environ.get("ASSETGRAPH_DOUYINLIVE_BINARY", REPO_ROOT / ".external/bin/douyinLive")
    )

    def verify(self) -> dict[str, str]:
        streamcap_commit = _run(
            ["git", "-C", str(self.streamcap_checkout), "rev-parse", "HEAD"]
        ).strip()
        if streamcap_commit != STREAMCAP_COMMIT:
            raise RuntimeError(
                f"StreamCap checkout is not pinned to {STREAMCAP_VERSION}/{STREAMCAP_COMMIT}"
            )
        if not self.streamcap_python.is_file():
            raise RuntimeError("pinned StreamCap Python environment is missing")
        douyin_version = _run([str(self.douyinlive_binary), "--version"]).strip()
        if f"tag={DOUYINLIVE_VERSION}" not in douyin_version or DOUYINLIVE_COMMIT[:12] not in douyin_version:
            raise RuntimeError(
                f"douyinLive binary is not pinned to {DOUYINLIVE_VERSION}/{DOUYINLIVE_COMMIT}"
            )
        return {
            "streamcap_version": STREAMCAP_VERSION,
            "streamcap_commit": streamcap_commit,
            "streamcap_python": str(self.streamcap_python.resolve()),
            "douyinlive_version": DOUYINLIVE_VERSION,
            "douyinlive_commit": DOUYINLIVE_COMMIT,
            "douyinlive_build": douyin_version,
        }


class StreamCapTargetConfig:
    def __init__(self, recordings_path: Path):
        self.recordings_path = recordings_path.expanduser().resolve()

    def write_single_target(self, target: dict[str, Any]) -> None:
        room_url = str(target["room_url"])
        if not room_url.startswith("https://live.douyin.com/"):
            raise ValueError("StreamCap target must use a canonical HTTPS Douyin live URL")
        target_code = str(target["target_code"])
        row = {
            "rec_id": str(uuid5(NAMESPACE_URL, f"assetgraph:{target_code}")),
            "url": room_url,
            "streamer_name": str(target["display_name"]),
            "record_format": "TS",
            "quality": "HD",
            "segment_record": True,
            "segment_time": "600",
            "monitor_status": True,
            "scheduled_recording": False,
            "scheduled_start_time": None,
            "monitor_hours": None,
            "recording_dir": None,
            "enabled_message_push": False,
            "platform": "抖音直播",
            "platform_key": "douyin",
            "only_notify_no_record": False,
            "flv_use_direct_download": False,
        }
        content = json.dumps([row], ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        self.recordings_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.recordings_path.with_suffix(".json.part")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.recordings_path)
            os.chmod(self.recordings_path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)


def _run(arguments: list[str]) -> str:
    completed = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode:
        raise RuntimeError(f"sidecar verification failed: {completed.stderr.strip()[-1000:]}")
    return completed.stdout or completed.stderr

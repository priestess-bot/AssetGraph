from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from typing import Any

import pytest

from app.services.video_production_models import VideoProductionError
from app.services.video_production_tts import KokoroTTSClient


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 240)
    return output.getvalue()


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.content


def test_kokoro_client_checks_health_and_writes_wav_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        requests.append(request)
        if request.full_url.endswith("/health"):
            return FakeResponse(json.dumps({"status": "ok", "voice": "zm_yunyang"}).encode())
        return FakeResponse(_wav_bytes())

    monkeypatch.setattr("app.services.video_production_tts.urllib.request.urlopen", fake_urlopen)
    client = KokoroTTSClient(base_url="http://127.0.0.1:8020/")
    output = tmp_path / "voice.wav"

    assert client.health()["status"] == "ok"
    assert client.synthesize("品酒大师 P R O", output) == output
    assert output.read_bytes()[:4] == b"RIFF"
    assert not list(tmp_path.glob("*.part"))
    request_payload = json.loads(requests[1].data)
    assert request_payload["voice"] == "zm_yunyang"
    assert request_payload["response_format"] == "wav"


def test_kokoro_client_rejects_non_wav_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "app.services.video_production_tts.urllib.request.urlopen",
        lambda request, timeout: FakeResponse(b'{"detail":"warming"}'),
    )
    client = KokoroTTSClient()

    with pytest.raises(VideoProductionError) as error:
        client.synthesize("测试", tmp_path / "bad.wav")

    assert error.value.error_code == "TTS_INVALID_AUDIO"
    assert not (tmp_path / "bad.wav").exists()

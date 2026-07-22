from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.video_production_models import VideoProductionError


class TTSProvider(Protocol):
    voice: str

    def health(self) -> dict[str, Any]: ...

    def synthesize(self, text: str, destination: Path, *, speed: float = 1.0) -> Path: ...


@dataclass(slots=True)
class KokoroTTSClient:
    base_url: str = "http://127.0.0.1:8020"
    model: str = "hexgrad/Kokoro-82M"
    voice: str = "zm_yunyang"
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        content = self._open(request, path="/health")
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VideoProductionError("TTS_INVALID_RESPONSE", "TTS health response is not JSON") from exc
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise VideoProductionError("TTS_NOT_READY", "TTS service is not ready")
        return payload

    def synthesize(self, text: str, destination: Path, *, speed: float = 1.0) -> Path:
        normalized = " ".join(text.split()).strip()
        if not normalized:
            raise VideoProductionError("TTS_EMPTY_INPUT", "TTS input must not be empty")
        if len(normalized) > 1000:
            raise VideoProductionError("TTS_INPUT_TOO_LONG", "TTS input exceeds 1000 characters")
        if not 0.5 <= speed <= 2.0:
            raise VideoProductionError("TTS_INVALID_SPEED", "TTS speed must be between 0.5 and 2.0")
        payload = json.dumps(
            {
                "model": self.model,
                "voice": self.voice,
                "input": normalized,
                "response_format": "wav",
                "speed": speed,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/audio/speech",
            data=payload,
            headers={"Accept": "audio/wav", "Content-Type": "application/json"},
            method="POST",
        )
        content = self._open(request, path="/v1/audio/speech")
        if len(content) < 44 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
            raise VideoProductionError("TTS_INVALID_AUDIO", "TTS response is not a valid WAV container")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
        try:
            with temporary.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _open(self, request: urllib.request.Request, *, path: str) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise VideoProductionError("TTS_HTTP_ERROR", f"TTS HTTP {exc.code} {path}: {detail}") from exc
        except TimeoutError as exc:
            raise VideoProductionError("TTS_TIMEOUT", f"TTS request timed out: {path}") from exc
        except urllib.error.URLError as exc:
            raise VideoProductionError("TTS_UNAVAILABLE", f"TTS request failed: {path}: {exc.reason}") from exc

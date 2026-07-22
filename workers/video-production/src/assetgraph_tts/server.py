from __future__ import annotations

import hashlib
import io
import os
import threading
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Response
from huggingface_hub import snapshot_download
from pydantic import BaseModel, ConfigDict, Field


MODEL_ID = "hexgrad/Kokoro-82M"
MODEL_REVISION = "10319fe511be37815a2116fca92006000d38151e"
MODEL_FILENAME = "kokoro-v1_0.pth"
MODEL_SHA256 = "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
CONFIG_SHA256 = "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f"
DEFAULT_VOICE = "zm_yunyang"
VOICE_SHA256 = "5238ac22e0c7f8b6cdd2eddd6e444b8a700b73c4674d9a047d59a94ff96379a2"
SAMPLE_RATE = 24000
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MODEL_ROOT = REPO_ROOT / ".external" / "models" / "kokoro"


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = MODEL_ID
    voice: str = Field(default=DEFAULT_VOICE, pattern=r"^zm_[a-z0-9_]+$")
    input: str = Field(..., min_length=1, max_length=1000)
    response_format: Literal["wav"] = "wav"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class KokoroEngine:
    def __init__(self) -> None:
        self._pipeline = None
        self._voice_path: Path | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    def load(self) -> None:
        if self._pipeline is not None:
            return
        with self._lock:
            if self._pipeline is not None:
                return
            from kokoro import KModel, KPipeline

            cache_root = Path(
                os.environ.get(
                    "ASSETGRAPH_KOKORO_MODEL_ROOT",
                    str(DEFAULT_MODEL_ROOT),
                )
            ).expanduser()
            cache_root.mkdir(parents=True, exist_ok=True)
            snapshot = Path(
                snapshot_download(
                    repo_id=MODEL_ID,
                    revision=MODEL_REVISION,
                    cache_dir=cache_root,
                    allow_patterns=["config.json", MODEL_FILENAME, f"voices/{DEFAULT_VOICE}.pt"],
                )
            )
            model_path = snapshot / MODEL_FILENAME
            if _sha256(model_path) != MODEL_SHA256:
                raise RuntimeError("Kokoro model checksum does not match the pinned v1.0 release")
            config_path = snapshot / "config.json"
            voice_path = snapshot / "voices" / f"{DEFAULT_VOICE}.pt"
            if _sha256(config_path) != CONFIG_SHA256:
                raise RuntimeError("Kokoro config checksum does not match the pinned v1.0 release")
            if _sha256(voice_path) != VOICE_SHA256:
                raise RuntimeError("Kokoro voice checksum does not match the pinned Mandarin voice")
            model = KModel(
                repo_id=MODEL_ID,
                config=str(config_path),
                model=str(model_path),
            ).to("cpu").eval()
            self._pipeline = KPipeline(lang_code="z", repo_id=MODEL_ID, model=model, device="cpu")
            self._voice_path = voice_path

    def synthesize(self, text: str, *, voice: str, speed: float) -> bytes:
        if voice != DEFAULT_VOICE:
            raise ValueError(f"unsupported voice: {voice}")
        self.load()
        assert self._pipeline is not None
        assert self._voice_path is not None
        with self._lock:
            chunks = [
                np.asarray(result.audio, dtype=np.float32)
                for result in self._pipeline(
                    text.strip(),
                    voice=str(self._voice_path),
                    speed=speed,
                    split_pattern=r"\n+",
                )
                if result.audio is not None
            ]
        if not chunks:
            raise RuntimeError("Kokoro returned no audio")
        separator = np.zeros(round(SAMPLE_RATE * 0.12), dtype=np.float32)
        audio_parts: list[np.ndarray] = []
        for index, chunk in enumerate(chunks):
            if index:
                audio_parts.append(separator)
            audio_parts.append(chunk)
        output = io.BytesIO()
        sf.write(output, np.concatenate(audio_parts), SAMPLE_RATE, format="WAV", subtype="PCM_16")
        return output.getvalue()


engine = KokoroEngine()
app = FastAPI(title="AssetGraph Kokoro TTS", version="0.1.0")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA256,
        "config_sha256": CONFIG_SHA256,
        "voice": DEFAULT_VOICE,
        "voice_sha256": VOICE_SHA256,
        "model_loaded": engine.loaded,
        "device": "cpu",
    }


@app.post("/v1/audio/speech")
def speech(payload: SpeechRequest) -> Response:
    if payload.model != MODEL_ID:
        raise HTTPException(status_code=422, detail=f"unsupported model: {payload.model}")
    try:
        content = engine.synthesize(payload.input, voice=payload.voice, speed=payload.speed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Kokoro synthesis failed: {type(exc).__name__}") from exc
    return Response(content=content, media_type="audio/wav")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "assetgraph_tts.server:app",
        host=os.environ.get("ASSETGRAPH_TTS_HOST", "127.0.0.1"),
        port=int(os.environ.get("ASSETGRAPH_TTS_PORT", "8020")),
        workers=1,
    )


if __name__ == "__main__":
    main()

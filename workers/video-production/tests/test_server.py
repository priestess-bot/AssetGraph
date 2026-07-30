from __future__ import annotations

from fastapi.testclient import TestClient

from assetgraph_tts import server


def test_health_exposes_pinned_model_identity_without_loading_model() -> None:
    response = TestClient(server.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model": server.MODEL_ID,
        "model_revision": server.MODEL_REVISION,
        "model_sha256": server.MODEL_SHA256,
        "config_sha256": server.CONFIG_SHA256,
        "voice": server.DEFAULT_VOICE,
        "voice_sha256": server.VOICE_SHA256,
        "model_loaded": False,
        "device": "cpu",
    }


def test_speech_returns_wav_from_the_local_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        server.engine,
        "synthesize",
        lambda text, *, voice, speed: b"RIFF-local-wav",
    )

    response = TestClient(server.app).post(
        "/v1/audio/speech",
        json={"model": server.MODEL_ID, "voice": server.DEFAULT_VOICE, "input": "测试语音"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF-local-wav"


def test_speech_rejects_unknown_model_before_loading_engine(monkeypatch) -> None:
    called = False

    def synthesize(*args, **kwargs):  # pragma: no cover - must remain unreachable
        nonlocal called
        called = True
        return b""

    monkeypatch.setattr(server.engine, "synthesize", synthesize)
    response = TestClient(server.app).post(
        "/v1/audio/speech",
        json={"model": "unknown/model", "input": "测试语音"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported model: unknown/model"
    assert called is False


def test_speech_reports_engine_failure_without_leaking_details(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("machine-local secret")

    monkeypatch.setattr(server.engine, "synthesize", fail)
    response = TestClient(server.app).post(
        "/v1/audio/speech",
        json={"model": server.MODEL_ID, "input": "测试语音"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Kokoro synthesis failed: RuntimeError"
    assert "machine-local secret" not in response.text

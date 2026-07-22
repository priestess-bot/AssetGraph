from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from assetgraph_live_research.providers import (
    DeepSeekTemplateProvider,
    ModelProviderError,
    OpenAITranscriptionProvider,
    OpenAIVisionProvider,
    RoutedLayoutProvider,
)
from assetgraph_live_research.storage import SecureStorage


def test_openai_transcription_records_actual_model_and_fingerprint(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF" + b"\0" * 100)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["Authorization"] == "Bearer key"
        return httpx.Response(
            200,
            json={"id": "tx_1", "model": "gpt-4o-transcribe", "text": "hello"},
        )

    provider = OpenAITranscriptionProvider(
        api_key="key",
        transport=httpx.MockTransport(handler),
    )
    result = provider.transcribe(
        audio,
        model_version="gpt-4o-transcribe",
        parameters={"language": "zh"},
    )

    assert result["actual_model"] == "gpt-4o-transcribe"
    assert len(result["input_audio_sha256"]) == 64
    assert result["transcript"]["text"] == "hello"


def test_deepseek_aggregation_returns_versioned_template() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        return httpx.Response(
            200,
            json={
                "id": "chat_1",
                "model": "deepseek-chat",
                "choices": [{"message": {"content": '{"canvas":{"width":1080}}'}}],
            },
        )

    provider = DeepSeekTemplateProvider(
        api_key="key",
        transport=httpx.MockTransport(handler),
    )
    result = provider.analyze(
        run_type="template_aggregation",
        source_path=None,
        session={"session_code": "capture_1", "channels": []},
        model_version="deepseek-chat",
        parameters={"observations": [{"kind": "host"}]},
    )

    assert result["contract_version"] == "live-template-aggregation.v1"
    assert result["template"]["canvas"]["width"] == 1080


class _FrameRunner:
    def run(self, arguments: list[str], *, timeout_seconds: int) -> str:
        del timeout_seconds
        Path(arguments[-1]).write_bytes(b"jpeg-frame")
        return ""


def test_openai_vision_samples_frames_and_parses_structured_observations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.ts"
    source.write_bytes(b"video")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert any(
            item.get("type") == "input_image"
            for item in body["input"][0]["content"]
        )
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "vision-v1",
                "output_text": json.dumps(
                    {
                        "summary": "host and product panel",
                        "observations": [
                            {
                                "kind": "host",
                                "label": "host",
                                "bbox": {
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.5,
                                    "height": 0.7,
                                },
                                "confidence": 0.9,
                                "text": None,
                            }
                        ],
                    }
                ),
            },
        )

    provider = OpenAIVisionProvider(
        api_key="key",
        storage=SecureStorage(tmp_path / "store"),
        transport=httpx.MockTransport(handler),
        runner=_FrameRunner(),
    )
    result = provider.analyze(
        run_type="layout_inference",
        source_path=source,
        session={"session_code": "capture-1"},
        model_version="vision-v1",
        parameters={"sample_times_seconds": [0]},
    )

    assert result["contract_version"] == "live-vision-observations.v1"
    assert result["observations"][0]["kind"] == "host"
    assert result["frame_manifest"][0]["sha256"]


def test_provider_marks_5xx_as_retryable(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF" + b"\0" * 100)
    provider = OpenAITranscriptionProvider(
        api_key="key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )

    with pytest.raises(ModelProviderError) as captured:
        provider.transcribe(
            audio,
            model_version="gpt-4o-transcribe",
            parameters={},
        )
    assert captured.value.retryable is True


def test_routed_provider_fails_explicitly_without_credentials() -> None:
    provider = RoutedLayoutProvider(vision=None, aggregation=None)
    with pytest.raises(ModelProviderError, match="OPENAI_API_KEY"):
        provider.analyze(
            run_type="ocr",
            source_path=Path("source.ts"),
            session={},
            model_version="vision-model",
            parameters={},
        )
    with pytest.raises(ModelProviderError, match="DEEPSEEK_API_KEY"):
        provider.analyze(
            run_type="template_aggregation",
            source_path=None,
            session={},
            model_version="deepseek-chat",
            parameters={"observations": [{}]},
        )

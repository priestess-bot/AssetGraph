from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.services.online_models import OnlineModelError, OpenAICompatibleChatClient, OpenAIResponsesClient


def test_deepseek_compatible_client_returns_audited_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-pro"
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "deepseek-v4-pro-202607",
                "choices": [{"message": {"content": '{"title":"draft"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    client = OpenAICompatibleChatClient(
        api_key="secret",
        base_url="https://api.example.test",
        timeout_seconds=2,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    )
    result = client.generate_json(
        provider="deepseek",
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "generate"}],
        thinking=False,
    )

    assert result.content == {"title": "draft"}
    assert result.actual_model == "deepseek-v4-pro-202607"
    assert len(result.input_fingerprint) == 64
    assert len(result.output_fingerprint) == 64


def test_online_client_fails_closed_on_non_retryable_http_error() -> None:
    client = OpenAICompatibleChatClient(
        api_key="secret",
        base_url="https://api.example.test",
        timeout_seconds=2,
        max_attempts=3,
        transport=httpx.MockTransport(lambda _request: httpx.Response(401, json={"error": "bad key"})),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(OnlineModelError) as error:
        client.generate_json(provider="deepseek", model="model", messages=[{"role": "user", "content": "x"}])

    assert error.value.status_code == 401
    assert error.value.retryable is False
    assert "bad key" not in str(error.value)


def test_openai_responses_client_sends_images_and_parses_structured_output(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nframe")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        parts = body["input"][0]["content"]
        assert parts[1]["type"] == "input_image"
        assert parts[1]["image_url"].startswith("data:image/png;base64,")
        return httpx.Response(
            200,
            json={"id": "resp-1", "model": "gpt-5.6-sol", "output_text": '{"summary":"frame"}'},
        )

    client = OpenAIResponsesClient(
        api_key="secret",
        base_url="https://api.openai.test/v1",
        timeout_seconds=2,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    )
    result = client.analyze_images(
        model="gpt-5.6-sol",
        prompt="analyze",
        image_paths=[image],
        schema_name="frame",
        schema={"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
    )

    assert result.content == {"summary": "frame"}


def test_openai_diarized_transcription_requests_automatic_chunking(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF-audio")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="ignore")
        assert 'name="model"' in body and "gpt-4o-transcribe-diarize" in body
        assert 'name="response_format"' in body and "diarized_json" in body
        assert 'name="chunking_strategy"' in body and "auto" in body
        return httpx.Response(200, json={"text": "hello", "segments": []})

    client = OpenAIResponsesClient(
        api_key="secret",
        base_url="https://api.openai.test/v1",
        timeout_seconds=2,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    )

    result = client.transcribe(model="gpt-4o-transcribe-diarize", audio_path=audio)

    assert result.content["text"] == "hello"

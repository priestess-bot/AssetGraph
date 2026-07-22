from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx


class OnlineModelError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    provider: str
    requested_model: str
    actual_model: str
    response_id: str | None
    content: dict[str, Any]
    usage: dict[str, Any]
    input_fingerprint: str
    output_fingerprint: str
    latency_ms: int


def canonical_json_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _RetryingJSONClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        max_attempts: int,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise OnlineModelError("online model API key is not configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.transport = transport
        self.sleep = sleep

    def _post_json(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        started = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = client.post(
                        f"{self.base_url}{path}",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=payload,
                    )
                if response.status_code >= 400:
                    retryable = response.status_code == 429 or response.status_code >= 500
                    error = OnlineModelError(
                        f"online model HTTP {response.status_code} {path}",
                        retryable=retryable,
                        status_code=response.status_code,
                    )
                    if not retryable or attempt == self.max_attempts:
                        raise error
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 2 ** (attempt - 1)
                    self.sleep(delay + random.random() * 0.1)
                    last_error = error
                    continue
                try:
                    data = response.json()
                except ValueError as exc:
                    raise OnlineModelError("online model returned invalid JSON") from exc
                if not isinstance(data, dict):
                    raise OnlineModelError("online model returned a non-object response")
                return data, int((time.monotonic() - started) * 1000)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    raise OnlineModelError(f"online model request failed: {exc}", retryable=True) from exc
                self.sleep((2 ** (attempt - 1)) + random.random() * 0.1)
        raise OnlineModelError(f"online model request failed: {last_error}", retryable=True)


class OpenAICompatibleChatClient(_RetryingJSONClient):
    """Small, auditable client for DeepSeek's OpenAI-compatible Chat API."""

    def generate_json(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> ModelInvocation:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        data, latency_ms = self._post_json("/chat/completions", payload)
        choices = data.get("choices")
        content = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
        if not isinstance(content, str):
            raise OnlineModelError("chat response did not contain message content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OnlineModelError("chat response content was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OnlineModelError("chat response JSON must be an object")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        actual_model = str(data.get("model") or model)
        return ModelInvocation(
            provider=provider,
            requested_model=model,
            actual_model=actual_model,
            response_id=str(data.get("id")) if data.get("id") else None,
            content=parsed,
            usage=dict(usage),
            input_fingerprint=canonical_json_fingerprint(payload),
            output_fingerprint=canonical_json_fingerprint(parsed),
            latency_ms=latency_ms,
        )


class OpenAIResponsesClient(_RetryingJSONClient):
    def analyze_images(
        self,
        *,
        model: str,
        prompt: str,
        image_paths: list[Path],
        schema_name: str,
        schema: dict[str, Any],
        reasoning_effort: str = "medium",
    ) -> ModelInvocation:
        if not image_paths:
            raise OnlineModelError("image analysis requires at least one image")
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        image_manifest: list[dict[str, Any]] = []
        for path in image_paths:
            data = path.read_bytes()
            mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
            digest = hashlib.sha256(data).hexdigest()
            image_manifest.append({"name": path.name, "sha256": digest, "size": len(data)})
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}",
                    "detail": "high",
                }
            )
        payload = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "reasoning": {"effort": reasoning_effort},
            "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
        }
        fingerprint_payload = {**payload, "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], "images": image_manifest}
        data, latency_ms = self._post_json("/responses", payload)
        output_text = data.get("output_text")
        if not isinstance(output_text, str):
            for item in data.get("output") or []:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                for part in item.get("content") or []:
                    if isinstance(part, dict) and part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                        output_text = part["text"]
                        break
        if not isinstance(output_text, str):
            raise OnlineModelError("Responses API result did not contain output text")
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OnlineModelError("Responses API output was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OnlineModelError("Responses API JSON must be an object")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return ModelInvocation(
            provider="openai",
            requested_model=model,
            actual_model=str(data.get("model") or model),
            response_id=str(data.get("id")) if data.get("id") else None,
            content=parsed,
            usage=dict(usage),
            input_fingerprint=canonical_json_fingerprint(fingerprint_payload),
            output_fingerprint=canonical_json_fingerprint(parsed),
            latency_ms=latency_ms,
        )

    def transcribe(self, *, model: str, audio_path: Path) -> ModelInvocation:
        if not audio_path.is_file():
            raise OnlineModelError(f"audio input does not exist: {audio_path.name}")
        started = time.monotonic()
        file_sha = hashlib.sha256()
        with audio_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                file_sha.update(chunk)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with audio_path.open("rb") as source, httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        data={
                            "model": model,
                            "response_format": "diarized_json",
                            "chunking_strategy": "auto",
                        },
                        files={"file": (audio_path.name, source, "application/octet-stream")},
                    )
                if response.status_code >= 400:
                    retryable = response.status_code == 429 or response.status_code >= 500
                    if not retryable or attempt == self.max_attempts:
                        raise OnlineModelError(
                            f"OpenAI transcription HTTP {response.status_code}",
                            retryable=retryable,
                            status_code=response.status_code,
                        )
                    self.sleep(2 ** (attempt - 1))
                    continue
                data = response.json()
                if not isinstance(data, dict):
                    raise OnlineModelError("transcription response must be an object")
                return ModelInvocation(
                    provider="openai",
                    requested_model=model,
                    actual_model=str(data.get("model") or model),
                    response_id=str(data.get("id")) if data.get("id") else None,
                    content=data,
                    usage=dict(data.get("usage") or {}) if isinstance(data.get("usage"), dict) else {},
                    input_fingerprint=canonical_json_fingerprint({"model": model, "file_sha256": file_sha.hexdigest()}),
                    output_fingerprint=canonical_json_fingerprint(data),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    raise OnlineModelError(f"transcription request failed: {exc}", retryable=True) from exc
                self.sleep(2 ** (attempt - 1))
        raise OnlineModelError(f"transcription request failed: {last_error}", retryable=True)

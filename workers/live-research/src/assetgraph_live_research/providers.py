from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .permissions import restrict_private_permissions
from .storage import SecureStorage
from .streamcap import CommandRunner, SubprocessCommandRunner


class ModelProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ProviderResult:
    content: dict[str, Any]
    evidence: dict[str, Any]


class OpenAITranscriptionProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 600,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = _require_api_key(api_key, "OPENAI_API_KEY")
        self.model = _require_model_version(model)
        self.base_url = _validated_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def transcribe(
        self,
        audio_path: Path,
        *,
        strategy_revision: str,
        parameters: dict[str, Any],
        processor_call_audit_code: str,
    ) -> ProviderResult:
        if not audio_path.is_file() or audio_path.is_symlink():
            raise ModelProviderError("ASR input must be a regular file")
        request_fields: dict[str, str] = {
            "model": self.model,
            "response_format": "diarized_json",
            "chunking_strategy": "auto",
        }
        for name in ("language", "prompt"):
            value = parameters.get(name)
            if value is not None:
                request_fields[name] = str(value)
        started = time.monotonic()
        try:
            with audio_path.open("rb") as source, httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=request_fields,
                    files={"file": (audio_path.name, source, "audio/wav")},
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ModelProviderError(
                "OpenAI transcription request failed",
                retryable=True,
            ) from exc
        data = _response_json(response, "OpenAI transcription")
        transcript = {
            key: value
            for key, value in data.items()
            if key not in {"id", "model", "usage"}
        }
        content = {
            "input_audio_sha256": _sha256_file(audio_path),
            "transcript": transcript,
        }
        return ProviderResult(
            content=content,
            evidence=_provider_evidence(
                provider_adapter="openai-transcription.v1",
                requested_model=self.model,
                actual_model=str(data.get("model") or self.model),
                provider_response_id=str(data["id"]) if data.get("id") else None,
                capability="speech_to_text",
                strategy_revision=strategy_revision,
                input_value={
                    "audio_sha256": content["input_audio_sha256"],
                    "parameters": parameters,
                },
                output_value=content,
                usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
                latency_ms=int((time.monotonic() - started) * 1000),
                processor_call_audit_code=processor_call_audit_code,
            ),
        )


class OpenAIVisionProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        storage: SecureStorage,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 600,
        transport: httpx.BaseTransport | None = None,
        runner: CommandRunner | None = None,
    ):
        self.api_key = _require_api_key(api_key, "OPENAI_API_KEY")
        self.model = _require_model_version(model)
        self.storage = storage
        self.base_url = _validated_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.runner = runner or SubprocessCommandRunner()

    def analyze(
        self,
        *,
        run_type: str,
        source_path: Path | None,
        session: dict[str, Any],
        strategy_revision: str,
        parameters: dict[str, Any],
        processor_call_audit_code: str,
    ) -> ProviderResult:
        if run_type not in {"ocr", "layout_inference"}:
            raise ModelProviderError(f"OpenAI vision does not handle {run_type}")
        if source_path is None:
            raise ModelProviderError(f"{run_type} requires a source chunk")
        model = self.model
        sample_times = _sample_times(parameters)
        frame_root = self.storage.resolve(
            "templates/runtime/vision/.runtime",
            create_parent=True,
        ).parent
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="vision-", dir=frame_root) as temporary_name:
            temporary = Path(temporary_name)
            restrict_private_permissions(temporary, 0o700)
            frames = self._extract_frames(source_path, temporary, sample_times)
            content: list[dict[str, Any]] = [
                {
                    "type": "input_text",
                    "text": _vision_prompt(run_type, session, sample_times),
                }
            ]
            frame_manifest: list[dict[str, Any]] = []
            for frame in frames:
                data = frame.read_bytes()
                if len(data) > 8 * 1024 * 1024:
                    raise ModelProviderError("vision frame exceeds the 8 MiB safety limit")
                mime_type = mimetypes.guess_type(frame.name)[0] or "image/jpeg"
                frame_manifest.append(
                    {
                        "name": frame.name,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
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
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "live_room_observations",
                        "strict": True,
                        "schema": _VISION_SCHEMA,
                    }
                },
            }
            try:
                with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = client.post(
                        f"{self.base_url}/responses",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise ModelProviderError(
                    "OpenAI vision request failed",
                    retryable=True,
                ) from exc
            data = _response_json(response, "OpenAI vision")
        observations = _parse_responses_output(data)
        content = {
            "contract_version": "live-vision-observations.v1",
            "frame_manifest": frame_manifest,
            **observations,
        }
        return ProviderResult(
            content=content,
            evidence=_provider_evidence(
                provider_adapter="openai-responses-vision.v1",
                requested_model=model,
                actual_model=str(data.get("model") or model),
                provider_response_id=str(data["id"]) if data.get("id") else None,
                capability=(
                    "optical_character_recognition"
                    if run_type == "ocr"
                    else "image_understanding"
                ),
                strategy_revision=strategy_revision,
                input_value={
                    "run_type": run_type,
                    "frame_manifest": frame_manifest,
                    "parameters": parameters,
                },
                output_value=content,
                usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
                latency_ms=int((time.monotonic() - started) * 1000),
                processor_call_audit_code=processor_call_audit_code,
            ),
        )

    def _extract_frames(
        self, source: Path, destination: Path, sample_times: list[float]
    ) -> list[Path]:
        frames: list[Path] = []
        for index, sample_time in enumerate(sample_times):
            output = destination / f"frame-{index:03d}.jpg"
            self.runner.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-y",
                    "-ss",
                    f"{sample_time:.6f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale='min(1280,iw)':-2",
                    "-q:v",
                    "2",
                    str(output),
                ],
                timeout_seconds=120,
            )
            if output.is_file() and not output.is_symlink() and output.stat().st_size > 0:
                restrict_private_permissions(output, 0o600)
                frames.append(output)
        if not frames:
            raise ModelProviderError("vision sampling produced no frames")
        return frames


class DeepSeekTemplateProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 300,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = _require_api_key(api_key, "DEEPSEEK_API_KEY")
        self.model = _require_model_version(model)
        self.base_url = _validated_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def analyze(
        self,
        *,
        run_type: str,
        source_path: Path | None,
        session: dict[str, Any],
        strategy_revision: str,
        parameters: dict[str, Any],
        processor_call_audit_code: str,
    ) -> ProviderResult:
        del source_path
        if run_type != "template_aggregation":
            raise ModelProviderError(f"DeepSeek aggregation does not handle {run_type}")
        observations = parameters.get("observations")
        if not isinstance(observations, list) or not observations:
            raise ModelProviderError("template aggregation requires non-empty observations")
        context = {
            "session_code": session.get("session_code"),
            "target_code": session.get("target_code"),
            "timeline_duration_seconds": session.get("timeline_duration_seconds"),
            "channels": session.get("channels") or [],
            "observations": observations,
        }
        encoded_context = json.dumps(
            context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(encoded_context.encode("utf-8")) > 1024 * 1024:
            raise ModelProviderError("template aggregation input exceeds 1 MiB")
        model = self.model
        payload = {
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Infer a reusable live-room template from verified observations. "
                        "Return JSON with canvas, scenes, components, audio_policy, "
                        "source_session_codes, confidence, and evidence. Never invent asset IDs."
                    ),
                },
                {"role": "user", "content": encoded_context},
            ],
        }
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ModelProviderError(
                "DeepSeek aggregation request failed",
                retryable=True,
            ) from exc
        data = _response_json(response, "DeepSeek aggregation")
        choices = data.get("choices")
        content: Any = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
        if not isinstance(content, str):
            raise ModelProviderError("DeepSeek response did not contain message content")
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelProviderError("DeepSeek response was not valid JSON") from exc
        if not isinstance(result, dict):
            raise ModelProviderError("DeepSeek template result must be an object")
        output = {
            "contract_version": "live-template-aggregation.v1",
            "template": result,
        }
        return ProviderResult(
            content=output,
            evidence=_provider_evidence(
                provider_adapter="deepseek-openai-compatible-chat.v1",
                requested_model=model,
                actual_model=str(data.get("model") or model),
                provider_response_id=str(data["id"]) if data.get("id") else None,
                capability="structured_generation",
                strategy_revision=strategy_revision,
                input_value=context,
                output_value=output,
                usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
                latency_ms=int((time.monotonic() - started) * 1000),
                processor_call_audit_code=processor_call_audit_code,
            ),
        )


class RoutedLayoutProvider:
    def __init__(
        self,
        *,
        vision: OpenAIVisionProvider | None,
        aggregation: DeepSeekTemplateProvider | None,
    ):
        self.vision = vision
        self.aggregation = aggregation

    def analyze(self, **arguments: Any) -> dict[str, Any]:
        run_type = str(arguments["run_type"])
        if run_type in {"ocr", "layout_inference"}:
            if self.vision is None:
                raise ModelProviderError(
                    "OPENAI_API_KEY/ASSETGRAPH_OPENAI_API_KEY is required for vision analysis"
                )
            return self.vision.analyze(**arguments)
        if run_type == "template_aggregation":
            if self.aggregation is None:
                raise ModelProviderError(
                    "DEEPSEEK_API_KEY/ASSETGRAPH_DEEPSEEK_API_KEY is required for template aggregation"
                )
            return self.aggregation.analyze(**arguments)
        raise ModelProviderError(f"unsupported routed analysis type: {run_type}")


def _require_api_key(value: str, name: str) -> str:
    key = value.strip()
    if not key:
        raise ModelProviderError(f"{name} is not configured")
    return key


def _require_model_version(value: str) -> str:
    model = str(value).strip()
    if not model or len(model) > 128:
        raise ModelProviderError("model_version must contain 1 to 128 characters")
    return model


def _validated_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModelProviderError("model base URL must be HTTP(S)")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ModelProviderError("model credentials cannot be sent over remote plain HTTP")
    return value.rstrip("/")


def _response_json(response: httpx.Response, operation: str) -> dict[str, Any]:
    if response.status_code >= 400:
        raise ModelProviderError(
            f"{operation} failed with HTTP {response.status_code}",
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ModelProviderError(f"{operation} returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ModelProviderError(f"{operation} returned a non-object response")
    return data


def _sample_times(parameters: dict[str, Any]) -> list[float]:
    supplied = parameters.get("sample_times_seconds", [0, 5, 15, 30])
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= 8:
        raise ModelProviderError("sample_times_seconds must contain 1 to 8 values")
    times = sorted({float(value) for value in supplied})
    if any(value < 0 or value > 600 for value in times):
        raise ModelProviderError("vision sample times must be between 0 and 600 seconds")
    return times


def _vision_prompt(run_type: str, session: dict[str, Any], sample_times: list[float]) -> str:
    return (
        f"Analyze these ordered frames for {run_type}. Coordinates must be normalized to [0,1]. "
        "Report only visible evidence and use null text when no text is readable. "
        f"session_code={session.get('session_code')}; sample_times_seconds={sample_times}"
    )


def _parse_responses_output(data: dict[str, Any]) -> dict[str, Any]:
    output_text = data.get("output_text")
    if not isinstance(output_text, str):
        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    output_text = part["text"]
                    break
    if not isinstance(output_text, str):
        raise ModelProviderError("OpenAI vision response did not contain output text")
    try:
        result = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ModelProviderError("OpenAI vision output was not valid JSON") from exc
    if not isinstance(result, dict):
        raise ModelProviderError("OpenAI vision output must be an object")
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provider_evidence(
    *,
    provider_adapter: str,
    requested_model: str,
    actual_model: str,
    provider_response_id: str | None,
    capability: str,
    strategy_revision: str,
    input_value: dict[str, Any],
    output_value: dict[str, Any],
    usage: dict[str, Any],
    latency_ms: int,
    processor_call_audit_code: str,
) -> dict[str, Any]:
    return {
        "schema_version": "provider-invocation-evidence.v1",
        "provider_adapter": provider_adapter,
        "requested_model": requested_model,
        "actual_model": actual_model,
        "provider_response_id": provider_response_id,
        "capability": capability,
        "strategy_revision": strategy_revision,
        "input_fingerprint": _canonical_fingerprint(input_value),
        "output_fingerprint": _canonical_fingerprint(output_value),
        "usage": usage,
        "latency_ms": latency_ms,
        "traceparent": None,
        "redaction_policy_ref": "baseline-sensitive-field-redaction@1",
        "input_redaction_count": 0,
        "output_redaction_count": 0,
        "processor_call_audit_code": processor_call_audit_code,
    }


def _canonical_fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string"},
                    "label": {"type": "string"},
                    "bbox": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "x": {"type": "number", "minimum": 0, "maximum": 1},
                            "y": {"type": "number", "minimum": 0, "maximum": 1},
                            "width": {"type": "number", "minimum": 0, "maximum": 1},
                            "height": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["x", "y", "width", "height"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "text": {"type": ["string", "null"]},
                },
                "required": ["kind", "label", "bbox", "confidence", "text"],
            },
        },
    },
    "required": ["summary", "observations"],
}

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.errors import DomainValidationError
from app.services.online_models import OpenAICompatibleChatClient, OpenAIResponsesClient
from app.services.providers.contracts import (
    ModelCapability,
    ProviderInvocationOutput,
)


class OpenAICompatibleStructuredAdapter:
    capabilities = frozenset({ModelCapability.STRUCTURED_GENERATION})

    def __init__(
        self,
        client: OpenAICompatibleChatClient,
        *,
        adapter_code: str,
        provider_code: str,
    ) -> None:
        self.client = client
        self.adapter_code = adapter_code
        self.provider_code = provider_code

    def invoke(
        self,
        *,
        capability: ModelCapability,
        model: str,
        inputs: dict[str, Any],
        output_json_schema: dict[str, Any],
        trace_context: Any,
        random_seed: int | None,
    ) -> ProviderInvocationOutput:
        del output_json_schema, trace_context, random_seed
        if capability is not ModelCapability.STRUCTURED_GENERATION:
            raise DomainValidationError(
                "MODEL_ADAPTER_CAPABILITY_MISMATCH",
                "Structured-generation adapter received an unsupported capability",
            )
        messages = inputs.get("messages")
        if messages is None:
            instructions = inputs.get("instructions")
            user_payload = inputs.get("user_payload")
            if not isinstance(instructions, str) or not isinstance(user_payload, dict):
                raise DomainValidationError(
                    "MODEL_ADAPTER_INPUT_INVALID",
                    "Structured generation requires instructions and a user payload",
                )
            messages = [
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": json.dumps(
                        user_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ]
        if not isinstance(messages, list) or not messages:
            raise DomainValidationError(
                "MODEL_ADAPTER_INPUT_INVALID",
                "Structured generation requires non-empty messages",
            )
        thinking = inputs.get("thinking")
        if thinking is not None and not isinstance(thinking, bool):
            raise DomainValidationError(
                "MODEL_ADAPTER_INPUT_INVALID",
                "Structured generation thinking control must be boolean",
            )
        invocation = self.client.generate_json(
            provider=self.provider_code,
            model=model,
            messages=messages,
            temperature=float(inputs.get("temperature", 0.2)),
            max_tokens=(
                int(inputs["max_tokens"])
                if inputs.get("max_tokens") is not None
                else None
            ),
            thinking=thinking,
        )
        return ProviderInvocationOutput(
            content=invocation.content,
            provider_response_id=invocation.response_id,
            actual_model=invocation.actual_model,
            usage=invocation.usage,
            latency_ms=invocation.latency_ms,
        )


class OpenAIResponsesImageAdapter:
    capabilities = frozenset(
        {
            ModelCapability.OPTICAL_CHARACTER_RECOGNITION,
            ModelCapability.IMAGE_UNDERSTANDING,
        }
    )

    def __init__(
        self,
        client: OpenAIResponsesClient,
        *,
        adapter_code: str,
    ) -> None:
        self.client = client
        self.adapter_code = adapter_code

    def invoke(
        self,
        *,
        capability: ModelCapability,
        model: str,
        inputs: dict[str, Any],
        output_json_schema: dict[str, Any],
        trace_context: Any,
        random_seed: int | None,
    ) -> ProviderInvocationOutput:
        del trace_context, random_seed
        if capability not in self.capabilities:
            raise DomainValidationError(
                "MODEL_ADAPTER_CAPABILITY_MISMATCH",
                "Image adapter received an unsupported capability",
            )
        raw_paths = inputs.get("image_paths")
        prompt = inputs.get("prompt")
        if not isinstance(raw_paths, list) or not raw_paths or not isinstance(prompt, str):
            raise DomainValidationError(
                "MODEL_ADAPTER_INPUT_INVALID",
                "Image understanding requires a prompt and non-empty image paths",
            )
        invocation = self.client.analyze_images(
            model=model,
            prompt=prompt,
            image_paths=[Path(str(value)) for value in raw_paths],
            schema_name=str(inputs.get("schema_name") or "structured_observation"),
            schema=output_json_schema,
            reasoning_effort=str(inputs.get("reasoning_effort") or "medium"),
        )
        return ProviderInvocationOutput(
            content=invocation.content,
            provider_response_id=invocation.response_id,
            actual_model=invocation.actual_model,
            usage=invocation.usage,
            latency_ms=invocation.latency_ms,
        )


class OpenAITranscriptionAdapter:
    capabilities = frozenset({ModelCapability.SPEECH_TO_TEXT})

    def __init__(self, client: OpenAIResponsesClient, *, adapter_code: str) -> None:
        self.client = client
        self.adapter_code = adapter_code

    def invoke(
        self,
        *,
        capability: ModelCapability,
        model: str,
        inputs: dict[str, Any],
        output_json_schema: dict[str, Any],
        trace_context: Any,
        random_seed: int | None,
    ) -> ProviderInvocationOutput:
        del output_json_schema, trace_context, random_seed
        if capability is not ModelCapability.SPEECH_TO_TEXT:
            raise DomainValidationError(
                "MODEL_ADAPTER_CAPABILITY_MISMATCH",
                "Transcription adapter received an unsupported capability",
            )
        audio_path = Path(str(inputs.get("audio_path") or ""))
        invocation = self.client.transcribe(model=model, audio_path=audio_path)
        return ProviderInvocationOutput(
            content=invocation.content,
            provider_response_id=invocation.response_id,
            actual_model=invocation.actual_model,
            usage=invocation.usage,
            latency_ms=invocation.latency_ms,
        )

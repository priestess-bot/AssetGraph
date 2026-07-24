from __future__ import annotations

import httpx
from opentelemetry import trace

from app import main
from app.core.telemetry import inject_current_trace, trace_context_from_current, use_remote_traceparent
from app.services.online_models import OpenAICompatibleChatClient


def test_remote_traceparent_creates_child_context_with_same_trace() -> None:
    assert main.app is not None
    parent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    tracer = trace.get_tracer("assetgraph.tests")

    with use_remote_traceparent(parent), tracer.start_as_current_span("worker-step"):
        current = trace_context_from_current()

    assert current is not None
    assert current.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert current.span_id != "00f067aa0ba902b7"


def test_trace_is_injected_into_carrier_and_external_adapter_request() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "model": "test-model",
                "choices": [{"message": {"content": '{"ok":true}'}}],
            },
        )

    tracer = trace.get_tracer("assetgraph.tests")
    with tracer.start_as_current_span("external-adapter"):
        current = trace_context_from_current()
        carrier: dict[str, str] = {}
        inject_current_trace(carrier)
        client = OpenAICompatibleChatClient(
            api_key="test-api-key",
            base_url="https://provider.invalid",
            timeout_seconds=5,
            max_attempts=1,
            transport=httpx.MockTransport(handler),
            sleep=lambda _seconds: None,
        )
        invocation = client.generate_json(
            provider="internal-test-provider",
            model="test-model",
            messages=[{"role": "user", "content": "return JSON"}],
        )

    assert current is not None
    assert invocation.content == {"ok": True}
    assert carrier["traceparent"].split("-")[1] == current.trace_id
    assert seen_headers["traceparent"].split("-")[1] == current.trace_id

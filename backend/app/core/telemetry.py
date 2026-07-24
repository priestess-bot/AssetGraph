from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, MutableMapping

from fastapi import FastAPI, Request
from opentelemetry import context, propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.services.lineage import TraceContext


_configured = False


def configure_telemetry(
    app: FastAPI,
    *,
    service_name: str,
    environment: str,
    exporter_endpoint: str | None,
) -> None:
    global _configured
    if _configured:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "deployment.environment.name": environment,
            }
        )
    )
    if exporter_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=exporter_endpoint.rstrip("/") + "/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls="/health")
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    @app.middleware("http")
    async def expose_traceparent(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        current = trace_context_from_current()
        if current is not None:
            response.headers["traceparent"] = current.as_traceparent()
        return response

    _configured = True


def trace_context_from_current() -> TraceContext | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return TraceContext(
        trace_id=f"{span_context.trace_id:032x}",
        span_id=f"{span_context.span_id:016x}",
        trace_flags=f"{int(span_context.trace_flags):02x}",
    )


def inject_current_trace(carrier: MutableMapping[str, str]) -> MutableMapping[str, str]:
    propagate.inject(carrier)
    return carrier


@contextmanager
def use_remote_traceparent(traceparent: str | None) -> Iterator[None]:
    if not traceparent:
        yield
        return
    parsed = TraceContext.parse(traceparent)
    carrier = {"traceparent": parsed.as_traceparent()}
    token = context.attach(propagate.extract(carrier))
    try:
        yield
    finally:
        context.detach(token)

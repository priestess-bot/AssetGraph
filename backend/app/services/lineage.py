from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    span_id: str
    trace_flags: str = "01"

    @classmethod
    def parse(cls, traceparent: str) -> "TraceContext":
        parts = traceparent.strip().split("-")
        if len(parts) != 4 or parts[0] != "00":
            raise DomainValidationError("TRACEPARENT_INVALID", "Unsupported traceparent format")
        trace_id, span_id, flags = parts[1:]
        if (
            len(trace_id) != 32
            or len(span_id) != 16
            or len(flags) != 2
            or any(character not in "0123456789abcdef" for character in trace_id + span_id + flags)
            or set(trace_id) == {"0"}
            or set(span_id) == {"0"}
        ):
            raise DomainValidationError("TRACEPARENT_INVALID", "traceparent identifiers are invalid")
        return cls(trace_id=trace_id, span_id=span_id, trace_flags=flags)

    def as_traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"


def openlineage_run_event(edge: dict[str, Any], *, event_type: str = "COMPLETE") -> dict[str, Any]:
    required = {
        "run_code",
        "source_namespace",
        "source_name",
        "source_version",
        "target_namespace",
        "target_name",
        "target_version",
        "relation_type",
    }
    missing = sorted(required - edge.keys())
    if missing:
        raise DomainValidationError(
            "LINEAGE_EDGE_INCOMPLETE",
            "Lineage edge cannot be projected to OpenLineage",
            details={"missing": missing},
        )
    return {
        "eventType": event_type,
        "run": {"runId": edge["run_code"]},
        "job": {
            "namespace": "assetgraph",
            "name": f"{edge['relation_type']}:{edge['target_name']}",
        },
        "inputs": [
            {
                "namespace": edge["source_namespace"],
                "name": edge["source_name"],
                "facets": {"version": {"_producer": "assetgraph", "version": edge["source_version"]}},
            }
        ],
        "outputs": [
            {
                "namespace": edge["target_namespace"],
                "name": edge["target_name"],
                "facets": {"version": {"_producer": "assetgraph", "version": edge["target_version"]}},
            }
        ],
        "producer": "https://assetgraph.local/openlineage/v1",
        "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
    }


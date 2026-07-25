from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import functional_knowledge


NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _projection(**overrides: Any) -> dict[str, Any]:
    return {
        "projection_code": "GRAPH-001",
        "revision_number": 1,
        "status": "completed",
        "ontology_version": "knowledge-lineage.v1",
        "embedding_version": None,
        "source_watermark": {"source_fingerprint": "a" * 64, "node_count": 2, "edge_count": 1},
        "current_source_watermark": {"source_fingerprint": "a" * 64, "node_count": 2, "edge_count": 1},
        "snapshot_fingerprint_sha256": "b" * 64,
        "node_count": 2,
        "edge_count": 1,
        "created_by": "console_operator",
        "created_at": NOW,
        "is_stale": False,
        "nodes": [{
            "node_type": "source_evidence", "node_code": "EVIDENCE-001", "revision_number": 0,
            "status": "approved", "properties": {"title": "Product sheet"},
            "source_fingerprint_sha256": "c" * 64, "created_at": NOW,
        }],
        "edges": [],
        **overrides,
    }


class FakeGraphProjectionService:
    def __init__(self) -> None:
        self.actor: str | None = None

    @staticmethod
    def current() -> dict[str, Any] | None:
        return None

    def rebuild(self, actor: str) -> dict[str, Any]:
        self.actor = actor
        return _projection(created_by=actor)

    @staticmethod
    def get(code: str) -> dict[str, Any] | None:
        return _projection(projection_code=code) if code == "GRAPH-001" else None


def _client(service: FakeGraphProjectionService) -> TestClient:
    app = FastAPI()
    app.include_router(functional_knowledge.router, prefix="/api")
    app.dependency_overrides[functional_knowledge.graph_svc] = lambda: service
    return TestClient(app)


def test_graph_projection_routes_expose_empty_current_and_rebuild_actor() -> None:
    service = FakeGraphProjectionService()
    client = _client(service)

    assert client.get("/api/functional-knowledge/graph-projections/current").json() is None
    response = client.post("/api/functional-knowledge/graph-projections/rebuild", json={"actor": "  graph_operator  "})

    assert response.status_code == 201
    assert response.json()["projection_code"] == "GRAPH-001"
    assert service.actor == "graph_operator"


def test_graph_projection_route_returns_not_found_for_unknown_projection() -> None:
    response = _client(FakeGraphProjectionService()).get("/api/functional-knowledge/graph-projections/missing")

    assert response.status_code == 404

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import data_governance
from app.main import app


NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _metric(*, revision: int = 1) -> dict[str, Any]:
    return {
        "metric_code": "orders",
        "revision_number": revision,
        "status": "active",
        "owner_principal": "data-owner",
        "metric_status": "active",
        "name": "Orders",
        "description": "Completed orders after the configured refund window",
        "grain": "live_session",
        "unit": "order",
        "currency": None,
        "value_type": "integer",
        "aggregation": "count",
        "numerator_expression": None,
        "denominator_expression": None,
        "dimensions": ["live_session_code"],
        "event_contract_refs": [{"code": "commerce-orders", "revision": 1}],
        "event_time_field": "event_time",
        "timezone": "Asia/Shanghai",
        "business_day_boundary": "04:00",
        "deduplication_keys": ["order_id"],
        "refund_window_days": 14,
        "null_rule": {"order_id": "reject"},
        "outlier_rule": {},
        "schema_compatibility": {"minimum": "commerce-event.v1"},
        "quality_slo": {"completeness": 0.99},
        "fingerprint_sha256": "a" * 64,
        "effective_at": None,
        "created_at": NOW,
    }


def _contract(*, revision: int = 1) -> dict[str, Any]:
    return {
        "contract_code": "commerce-orders",
        "revision_number": revision,
        "status": "active",
        "owner_principal": "data-owner",
        "source_system": "commerce-platform",
        "schema_version": "commerce-event.v1",
        "json_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
        "event_id_path": "/event_id",
        "event_time_path": "/event_time",
        "operation_path": "/operation",
        "primary_key_paths": ["/order_id"],
        "upsert_delete_semantics": {"allowed_operations": ["insert", "upsert", "delete"]},
        "lateness_policy": {"max_lateness_seconds": 3600},
        "compatibility_window": {"accepted_revisions": [1]},
        "enum_mappings": {},
        "field_classifications": {"order_id": "confidential"},
        "expected_volume": {"events_per_hour": 1000},
        "quality_slo": {"completeness": 0.99},
        "fingerprint_sha256": "b" * 64,
        "created_at": NOW,
    }


class FakeDataGovernanceService:
    def __init__(self) -> None:
        self.metric_write: dict[str, Any] | None = None
        self.contract_write: dict[str, Any] | None = None

    def list_metrics(self) -> list[dict[str, Any]]:
        return [_metric()]

    def list_metric_revisions(self, metric_code: str) -> list[dict[str, Any]]:
        return [_metric(revision=2), _metric()] if metric_code == "orders" else []

    def put_metric_revision(self, **kwargs: Any) -> dict[str, Any]:
        self.metric_write = kwargs
        return _metric(revision=kwargs["expected_revision"] + 1)

    def list_contracts(self) -> list[dict[str, Any]]:
        return [_contract()]

    def list_contract_revisions(self, contract_code: str) -> list[dict[str, Any]]:
        return [_contract(revision=2), _contract()] if contract_code == "commerce-orders" else []

    def list_contract_consumers(self, contract_code: str) -> list[dict[str, Any]]:
        return [
            {
                "metric_code": "orders",
                "revision_number": 1,
                "status": "active",
                "owner_principal": "data-owner",
                "name": "Orders",
                "event_contract_refs": [{"code": contract_code, "revision": 1}],
            }
        ]

    def put_contract(self, **kwargs: Any) -> dict[str, Any]:
        self.contract_write = kwargs
        return _contract(revision=kwargs["revision_number"])

    def list_quality_batches(self) -> list[dict[str, Any]]:
        return [self._batch()]

    def ingest_event_batch(self, payload: Any) -> dict[str, Any]:
        result = self._batch()
        result["source_batch_id"] = payload.source_batch_id
        result["row_count"] = len(payload.rows)
        return result

    @staticmethod
    def _batch() -> dict[str, Any]:
        return {
            "batch_code": "DQB-20260725-000001",
            "contract_code": "commerce-orders",
            "contract_revision": 1,
            "source_batch_id": "export-001",
            "source_checksum": "c" * 64,
            "status": "accepted",
            "row_count": 1,
            "accepted_count": 1,
            "quarantined_count": 0,
            "rejected_count": 0,
            "quality_summary": {},
            "source_watermark": NOW,
            "validated_at": NOW,
            "created_at": NOW,
            "replayed": False,
        }


@pytest.fixture
def client() -> tuple[TestClient, FakeDataGovernanceService]:
    service = FakeDataGovernanceService()
    app.dependency_overrides[data_governance.get_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service
    app.dependency_overrides.pop(data_governance.get_service, None)


def _metric_write() -> dict[str, Any]:
    return {
        "owner_principal": "data-owner",
        "expected_revision": 1,
        "activate": True,
        "definition": {
            "name": "Orders",
            "description": "Completed orders after the configured refund window",
            "grain": "live_session",
            "unit": "order",
            "value_type": "integer",
            "aggregation": "count",
            "event_time_field": "event_time",
            "timezone": "Asia/Shanghai",
            "deduplication_keys": ["order_id"],
            "null_rule": {"order_id": "reject"},
            "outlier_rule": {},
            "event_contract_refs": [{"code": "commerce-orders", "revision": 1}],
            "schema_compatibility": {"minimum": "commerce-event.v1"},
            "quality_slo": {"completeness": 0.99},
        },
    }


def _batch_write() -> dict[str, Any]:
    return {
        "contract_code": "commerce-orders",
        "contract_revision": 1,
        "source_batch_id": "export-20260725-001",
        "rows": [
            {
                "entity_type": "live_session",
                "entity_id": "OPS-001",
                "envelope": {
                    "event_id": "4b6d5675-7a11-4628-82e0-8b7c60d934c5",
                    "source_system": "commerce-platform",
                    "source_event_id": "order-001",
                    "schema_version": "commerce-event.v1",
                    "operation": "upsert",
                    "event_time": "2026-07-25T00:00:00Z",
                    "processing_time": "2026-07-25T00:01:00Z",
                    "payload": {"order_id": "order-001"},
                },
            }
        ],
    }


def _contract_write() -> dict[str, Any]:
    return {
        "owner_principal": "data-owner",
        "activate": True,
        "definition": {
            "source_system": "commerce-platform",
            "schema_version": "commerce-event.v1",
            "json_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
            "event_id_path": "/event_id",
            "event_time_path": "/event_time",
            "operation_path": "/operation",
            "primary_key_paths": ["/order_id"],
            "upsert_delete_semantics": {"allowed_operations": ["insert", "upsert", "delete"]},
            "lateness_policy": {"max_lateness_seconds": 3600},
            "compatibility_window": {"accepted_revisions": [1]},
            "expected_volume": {"events_per_hour": 1000},
            "quality_slo": {"completeness": 0.99},
        },
    }


def test_catalog_routes_expose_revisions_and_contract_consumers(
    client: tuple[TestClient, FakeDataGovernanceService],
) -> None:
    test_client, _service = client

    assert test_client.get("/api/data-governance/metrics").json()[0]["metric_code"] == "orders"
    assert len(test_client.get("/api/data-governance/metrics/orders/revisions").json()) == 2
    assert test_client.get("/api/data-governance/metrics/missing/revisions").status_code == 404
    assert test_client.get("/api/data-governance/contracts").json()[0]["contract_code"] == "commerce-orders"
    assert len(test_client.get("/api/data-governance/contracts/commerce-orders/revisions").json()) == 2
    assert test_client.get("/api/data-governance/contracts/commerce-orders/consumers").json()[0]["metric_code"] == "orders"


def test_catalog_write_routes_delegate_typed_new_revisions(
    client: tuple[TestClient, FakeDataGovernanceService],
) -> None:
    test_client, service = client

    metric = test_client.post("/api/data-governance/metrics/orders/revisions", json=_metric_write())
    contract = test_client.post(
        "/api/data-governance/contracts/commerce-orders/revisions/2",
        json=_contract_write(),
    )

    assert metric.status_code == 201
    assert metric.json()["revision_number"] == 2
    assert service.metric_write is not None
    assert service.metric_write["expected_revision"] == 1
    assert contract.status_code == 201
    assert contract.json()["revision_number"] == 2
    assert service.contract_write is not None
    assert service.contract_write["definition"].schema_version == "commerce-event.v1"


def test_quality_batch_routes_list_and_delegate_typed_event_rows(
    client: tuple[TestClient, FakeDataGovernanceService],
) -> None:
    test_client, _service = client

    listed = test_client.get("/api/data-governance/batches")
    created = test_client.post("/api/data-governance/batches", json=_batch_write())

    assert listed.status_code == 200
    assert listed.json()[0]["batch_code"] == "DQB-20260725-000001"
    assert created.status_code == 201
    assert created.json()["source_batch_id"] == "export-20260725-001"
    assert created.json()["row_count"] == 1

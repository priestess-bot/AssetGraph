from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import functional_knowledge


NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _source(**overrides: Any) -> dict[str, Any]:
    return {
        "evidence_code": "EVIDENCE-001",
        "source_type": "document",
        "title": "Approved product sheet",
        "source_url": "https://example.test/product-sheet",
        "excerpt": "The product has a verified 12-month warranty.",
        "content_sha256": "a" * 64,
        "captured_at": NOW,
        "access_scope": "internal",
        "status": "draft",
        "created_by": "author",
        "approved_by": None,
        "approved_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
    }


def _claim(**overrides: Any) -> dict[str, Any]:
    return {
        "claim_code": "CLAIM-001",
        "fact_code": "FACT-001",
        "fact_title": "Warranty",
        "source_evidence_code": "EVIDENCE-001",
        "source_title": "Approved product sheet",
        "source_status": "approved",
        "field_path": "warranty",
        "claim": "The product has a 12-month warranty.",
        "citation_excerpt": "The product has a verified 12-month warranty.",
        "valid_from": None,
        "valid_until": None,
        "status": "draft",
        "created_by": "author",
        "approved_by": None,
        "approved_at": None,
        "fingerprint_sha256": "b" * 64,
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
    }


def _rule(**overrides: Any) -> dict[str, Any]:
    return {
        "rule_code": "RULE-001",
        "rule_kind": "expression_ban",
        "directive": "must_avoid",
        "title": "No unsupported price claim",
        "rule_text": "Do not promise an unverified price.",
        "scope": {"platforms": ["douyin"]},
        "source_evidence_code": "EVIDENCE-001",
        "source_title": "Approved product sheet",
        "source_status": "approved",
        "source_content_sha256": "a" * 64,
        "valid_from": None,
        "valid_until": None,
        "status": "draft",
        "created_by": "author",
        "approved_by": None,
        "approved_at": None,
        "revoked_by": None,
        "revoked_at": None,
        "revoked_reason": None,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "fingerprint_sha256": "c" * 64,
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
    }


class FakeFunctionalKnowledgeService:
    def __init__(self) -> None:
        self.source_payload: dict[str, Any] | None = None
        self.claim_payload: dict[str, Any] | None = None
        self.source_revocation: tuple[str, str, str] | None = None
        self.claim_revocation: tuple[str, str, str] | None = None
        self.source_rejection: tuple[str, str, str] | None = None
        self.claim_rejection: tuple[str, str, str] | None = None
        self.rule_payload: dict[str, Any] | None = None
        self.rule_rejection: tuple[str, str, str] | None = None
        self.rule_revocation: tuple[str, str, str] | None = None

    def create_source_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.source_payload = payload
        return _source(**payload)

    @staticmethod
    def list_source_evidences() -> list[dict[str, Any]]:
        return [_source(status="approved", approved_by="reviewer", approved_at=NOW)]

    @staticmethod
    def list_source_extraction_runs(code: str) -> list[dict[str, Any]] | None:
        if code == "missing":
            return None
        return [
            {
                "extraction_run_code": "EXTRACT-001",
                "evidence_code": code,
                "extractor_strategy_ref": "manual_excerpt.v1",
                "input_fingerprint_sha256": "a" * 64,
                "output_checksum_sha256": "b" * 64,
                "extraction_metadata": {"capture_mode": "manual"},
                "created_by": "author",
                "created_at": NOW,
            }
        ]

    @staticmethod
    def approve_source_evidence(code: str, approved_by: str) -> dict[str, Any] | None:
        return _source(evidence_code=code, status="approved", approved_by=approved_by, approved_at=NOW)

    def revoke_source_evidence(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.source_revocation = (code, actor, reason)
        return _source(
            evidence_code=code,
            status="revoked",
            revoked_by=actor,
            revoked_at=NOW,
            revoked_reason=reason,
        )

    def reject_source_evidence(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.source_rejection = (code, actor, reason)
        return _source(
            evidence_code=code,
            status="rejected",
            rejected_by=actor,
            rejected_at=NOW,
            rejection_reason=reason,
        )

    def create_fact_claim(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.claim_payload = payload
        return _claim(**payload)

    def create_content_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.rule_payload = payload
        return _rule(**payload)

    @staticmethod
    def list_content_rules(q: str | None = None) -> list[dict[str, Any]]:
        return [_rule()] if q != "none" else []

    @staticmethod
    def approve_content_rule(code: str, approved_by: str) -> dict[str, Any] | None:
        return _rule(rule_code=code, status="approved", approved_by=approved_by, approved_at=NOW)

    def reject_content_rule(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.rule_rejection = (code, actor, reason)
        return _rule(rule_code=code, status="rejected", rejected_by=actor, rejected_at=NOW, rejection_reason=reason)

    def revoke_content_rule(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.rule_revocation = (code, actor, reason)
        return _rule(rule_code=code, status="revoked", revoked_by=actor, revoked_at=NOW, revoked_reason=reason)

    @staticmethod
    def list_fact_claims(q: str | None = None) -> list[dict[str, Any]]:
        return [_claim()] if q != "none" else []

    @staticmethod
    def get_fact_claim_lineage(code: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        return {
            "claim_code": code,
            "fact_code": "FACT-001",
            "fact_title": "Warranty",
            "claim_status": "approved",
            "fact_status": "approved",
            "source_evidence_code": "EVIDENCE-001",
            "source_title": "Approved product sheet",
            "source_status": "approved",
            "uses": [
                {
                    "relation_type": "pins_fact_claim",
                    "object_type": "content_project",
                    "object_code": "CONTENT-001",
                    "revision_number": 2,
                    "status": "confirmed",
                    "created_at": NOW,
                }
            ],
        }

    @staticmethod
    def approve_fact_claim(code: str, approved_by: str) -> dict[str, Any] | None:
        return _claim(claim_code=code, status="approved", approved_by=approved_by, approved_at=NOW)

    def revoke_fact_claim(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.claim_revocation = (code, actor, reason)
        return _claim(
            claim_code=code,
            status="revoked",
            revoked_by=actor,
            revoked_at=NOW,
            revoked_reason=reason,
        )

    def reject_fact_claim(self, code: str, actor: str, reason: str) -> dict[str, Any] | None:
        if code == "missing":
            return None
        self.claim_rejection = (code, actor, reason)
        return _claim(
            claim_code=code,
            status="rejected",
            rejected_by=actor,
            rejected_at=NOW,
            rejection_reason=reason,
        )


@pytest.fixture
def client() -> tuple[TestClient, FakeFunctionalKnowledgeService]:
    service = FakeFunctionalKnowledgeService()
    app = FastAPI()
    app.include_router(functional_knowledge.router, prefix="/api")
    app.dependency_overrides[functional_knowledge.svc] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service


def test_source_evidence_and_fact_claim_routes_keep_citation_explicit(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, service = client
    source = test_client.post(
        "/api/functional-knowledge/source-evidences",
        json={
            "source_type": "document",
            "title": "Approved product sheet",
            "source_url": "https://example.test/product-sheet",
            "excerpt": "The product has a verified 12-month warranty.",
            "access_scope": "internal",
            "created_by": "author",
        },
    )
    approved = test_client.post(
        "/api/functional-knowledge/source-evidences/EVIDENCE-001/approve",
        json={"approved_by": "reviewer"},
    )
    claim = test_client.post(
        "/api/functional-knowledge/fact-claims",
        json={
            "fact_title": "Warranty",
            "claim": "The product has a 12-month warranty.",
            "source_evidence_code": "EVIDENCE-001",
            "citation_excerpt": "The product has a verified 12-month warranty.",
            "field_path": "warranty",
            "created_by": "author",
        },
    )
    claim_approved = test_client.post(
        "/api/functional-knowledge/fact-claims/CLAIM-001/approve",
        json={"approved_by": "reviewer"},
    )

    assert source.status_code == 201
    assert service.source_payload is not None
    assert approved.json()["status"] == "approved"
    assert claim.status_code == 201
    assert service.claim_payload is not None
    assert service.claim_payload["citation_excerpt"] == "The product has a verified 12-month warranty."
    assert claim_approved.json()["approved_by"] == "reviewer"


def test_source_extraction_run_route_keeps_capture_fingerprints_explicit(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, _service = client

    response = test_client.get(
        "/api/functional-knowledge/source-evidences/EVIDENCE-001/extraction-runs"
    )
    missing = test_client.get(
        "/api/functional-knowledge/source-evidences/missing/extraction-runs"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "extraction_run_code": "EXTRACT-001",
            "evidence_code": "EVIDENCE-001",
            "extractor_strategy_ref": "manual_excerpt.v1",
            "input_fingerprint_sha256": "a" * 64,
            "output_checksum_sha256": "b" * 64,
            "extraction_metadata": {"capture_mode": "manual"},
            "created_by": "author",
            "created_at": "2026-07-25T00:00:00Z",
        }
    ]
    assert missing.status_code == 404


def test_fact_claim_route_rejects_naive_datetimes(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, _service = client
    result = test_client.post(
        "/api/functional-knowledge/fact-claims",
        json={
            "fact_title": "Warranty",
            "claim": "The product has a 12-month warranty.",
            "source_evidence_code": "EVIDENCE-001",
            "citation_excerpt": "The product has a verified 12-month warranty.",
            "valid_from": "2026-07-25T12:00:00",
        },
    )
    assert result.status_code == 422


def test_fact_claim_route_requires_a_complete_citation_interval_when_supplied(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, service = client
    created = test_client.post(
        "/api/functional-knowledge/fact-claims",
        json={
            "fact_title": "Warranty",
            "claim": "The product has a 12-month warranty.",
            "source_evidence_code": "EVIDENCE-001",
            "citation_excerpt": "The product has a verified 12-month warranty.",
            "citation_start_offset": 4,
            "citation_end_offset": 48,
        },
    )
    incomplete = test_client.post(
        "/api/functional-knowledge/fact-claims",
        json={
            "fact_title": "Warranty",
            "claim": "The product has a 12-month warranty.",
            "source_evidence_code": "EVIDENCE-001",
            "citation_excerpt": "The product has a verified 12-month warranty.",
            "citation_start_offset": 4,
        },
    )

    assert created.status_code == 201
    assert service.claim_payload is not None
    assert service.claim_payload["citation_start_offset"] == 4
    assert service.claim_payload["citation_end_offset"] == 48
    assert incomplete.status_code == 422


def test_content_rule_routes_keep_compliance_separate_and_reviewed(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, service = client
    created = test_client.post(
        "/api/functional-knowledge/content-rules",
        json={
            "rule_kind": "expression_ban",
            "directive": "must_avoid",
            "title": "No unsupported price claim",
            "rule_text": "Do not promise an unverified price.",
            "scope": {"platforms": ["douyin"]},
            "source_evidence_code": "EVIDENCE-001",
            "created_by": "author",
        },
    )
    approved = test_client.post(
        "/api/functional-knowledge/content-rules/RULE-001/approve",
        json={"approved_by": "reviewer"},
    )
    rejected = test_client.post(
        "/api/functional-knowledge/content-rules/RULE-001/reject",
        json={"actor": "reviewer", "reason": "Rule wording is incomplete."},
    )
    revoked = test_client.post(
        "/api/functional-knowledge/content-rules/RULE-001/revoke",
        json={"actor": "reviewer", "reason": "Rule was replaced."},
    )
    invalid = test_client.post(
        "/api/functional-knowledge/content-rules",
        json={
            "rule_kind": "expression_ban",
            "directive": "guidance",
            "title": "Bad rule",
            "rule_text": "Do not use this.",
            "source_evidence_code": "EVIDENCE-001",
        },
    )

    assert created.status_code == 201
    assert service.rule_payload is not None
    assert service.rule_payload["rule_kind"] == "expression_ban"
    assert approved.json()["approved_by"] == "reviewer"
    assert rejected.json()["rejection_reason"] == "Rule wording is incomplete."
    assert revoked.json()["revoked_reason"] == "Rule was replaced."
    assert service.rule_rejection == ("RULE-001", "reviewer", "Rule wording is incomplete.")
    assert service.rule_revocation == ("RULE-001", "reviewer", "Rule was replaced.")
    assert invalid.status_code == 422


def test_fact_claim_lineage_keeps_statuses_and_fixed_usage_explicit(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, _service = client

    lineage = test_client.get("/api/functional-knowledge/fact-claims/CLAIM-001/lineage")
    missing = test_client.get("/api/functional-knowledge/fact-claims/missing/lineage")

    assert lineage.status_code == 200
    assert lineage.json() == {
        "claim_code": "CLAIM-001",
        "fact_code": "FACT-001",
        "fact_title": "Warranty",
        "claim_status": "approved",
        "fact_status": "approved",
        "source_evidence_code": "EVIDENCE-001",
        "source_title": "Approved product sheet",
        "source_status": "approved",
        "uses": [
            {
                "relation_type": "pins_fact_claim",
                "object_type": "content_project",
                "object_code": "CONTENT-001",
                "revision_number": 2,
                "status": "confirmed",
                "created_at": "2026-07-25T00:00:00Z",
            }
        ],
    }
    assert missing.status_code == 404


def test_evidence_and_claim_revocation_require_attributed_reasons(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, service = client

    source = test_client.post(
        "/api/functional-knowledge/source-evidences/EVIDENCE-001/revoke",
        json={"actor": "reviewer", "reason": "Source specification was corrected."},
    )
    claim = test_client.post(
        "/api/functional-knowledge/fact-claims/CLAIM-001/revoke",
        json={"actor": "reviewer", "reason": "The warranty claim is no longer valid."},
    )
    blank_reason = test_client.post(
        "/api/functional-knowledge/fact-claims/CLAIM-001/revoke",
        json={"actor": "reviewer", "reason": "   "},
    )
    missing = test_client.post(
        "/api/functional-knowledge/source-evidences/missing/revoke",
        json={"actor": "reviewer", "reason": "Missing source."},
    )

    assert source.status_code == 200
    assert source.json()["revoked_reason"] == "Source specification was corrected."
    assert claim.status_code == 200
    assert claim.json()["revoked_by"] == "reviewer"
    assert service.source_revocation == (
        "EVIDENCE-001",
        "reviewer",
        "Source specification was corrected.",
    )
    assert service.claim_revocation == (
        "CLAIM-001",
        "reviewer",
        "The warranty claim is no longer valid.",
    )
    assert blank_reason.status_code == 422
    assert missing.status_code == 404


def test_evidence_and_claim_rejection_require_attributed_reasons(
    client: tuple[TestClient, FakeFunctionalKnowledgeService],
) -> None:
    test_client, service = client

    source = test_client.post(
        "/api/functional-knowledge/source-evidences/EVIDENCE-001/reject",
        json={"actor": "reviewer", "reason": "The document is incomplete."},
    )
    claim = test_client.post(
        "/api/functional-knowledge/fact-claims/CLAIM-001/reject",
        json={"actor": "reviewer", "reason": "The citation does not support the claim."},
    )
    blank_reason = test_client.post(
        "/api/functional-knowledge/source-evidences/EVIDENCE-001/reject",
        json={"actor": "reviewer", "reason": "   "},
    )
    missing = test_client.post(
        "/api/functional-knowledge/fact-claims/missing/reject",
        json={"actor": "reviewer", "reason": "Missing claim."},
    )

    assert source.status_code == 200
    assert source.json()["status"] == "rejected"
    assert source.json()["rejection_reason"] == "The document is incomplete."
    assert claim.status_code == 200
    assert claim.json()["rejected_by"] == "reviewer"
    assert service.source_rejection == (
        "EVIDENCE-001",
        "reviewer",
        "The document is incomplete.",
    )
    assert service.claim_rejection == (
        "CLAIM-001",
        "reviewer",
        "The citation does not support the claim.",
    )
    assert blank_reason.status_code == 422
    assert missing.status_code == 404

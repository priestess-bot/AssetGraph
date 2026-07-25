from __future__ import annotations
import os
import psycopg
import pytest
from app.services.functional_knowledge import FunctionalKnowledgeService

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def test_knowledge_search_and_impact() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        s = FunctionalKnowledgeService(c)
        first = s.create(
            {"title": "Product fact", "claim": "A verified fact", "related_codes": []}
        )
        second = s.create(
            {
                "title": "Related fact",
                "claim": "Uses product fact",
                "related_codes": [first["fact_code"]],
            }
        )
        assert any(x["fact_code"] == first["fact_code"] for x in s.list("verified"))
        assert {x["fact_code"] for x in s.impact(first["fact_code"])} >= {
            first["fact_code"],
            second["fact_code"],
        }


def test_source_evidence_must_be_approved_before_a_claim_can_be_approved() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        service = FunctionalKnowledgeService(c)
        source = service.create_source_evidence(
            {
                "source_type": "document",
                "title": "Approved spec",
                "source_url": "https://example.test/spec",
                "excerpt": "The device includes a verified 12-month warranty.",
                "access_scope": "internal",
                "created_by": "author",
            }
        )
        with pytest.raises(RuntimeError, match="approved source evidence"):
            service.create_fact_claim(
                {
                    "fact_title": "Warranty",
                    "claim": "The device includes a 12-month warranty.",
                    "source_evidence_code": source["evidence_code"],
                    "citation_excerpt": "The device includes a verified 12-month warranty.",
                }
            )
        service.approve_source_evidence(source["evidence_code"], "reviewer")
        claim = service.create_fact_claim(
            {
                "fact_title": "Warranty",
                "claim": "The device includes a 12-month warranty.",
                "source_evidence_code": source["evidence_code"],
                "citation_excerpt": "The device includes a verified 12-month warranty.",
                "field_path": "product.warranty",
                "created_by": "author",
            }
        )
        assert claim is not None
        approved = service.approve_fact_claim(claim["claim_code"], "reviewer")
        assert approved is not None
        assert approved["status"] == "approved"
        assert approved["source_evidence_code"] == source["evidence_code"]


def test_knowledge_evidence_revocation_stops_future_claim_resolution() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        service = FunctionalKnowledgeService(c)
        source = service.create_source_evidence(
            {
                "source_type": "document",
                "title": "Corrected product specification",
                "source_url": "https://example.test/corrected-spec",
                "excerpt": "The product has a verified 12-month warranty.",
                "access_scope": "internal",
                "created_by": "author",
            }
        )
        service.approve_source_evidence(source["evidence_code"], "reviewer")
        claim = service.create_fact_claim(
            {
                "fact_title": "Warranty",
                "claim": "The product has a 12-month warranty.",
                "source_evidence_code": source["evidence_code"],
                "citation_excerpt": "The product has a verified 12-month warranty.",
                "created_by": "author",
            }
        )
        assert claim is not None
        approved = service.approve_fact_claim(claim["claim_code"], "reviewer")
        assert approved is not None
        assert service.resolve_approved_fact_claim(claim["claim_code"]) is not None

        revoked_source = service.revoke_source_evidence(
            source["evidence_code"], "reviewer", "The source specification was superseded."
        )
        assert revoked_source is not None
        assert revoked_source["status"] == "revoked"
        assert revoked_source["revoked_by"] == "reviewer"
        assert service.resolve_approved_fact_claim(claim["claim_code"]) is None
        assert service.revoke_source_evidence(
            source["evidence_code"], "other-reviewer", "A later callback."
        )["revoked_reason"] == "The source specification was superseded."

        replacement = service.create_source_evidence(
            {
                "source_type": "document",
                "title": "Replacement product specification",
                "excerpt": "The product has a verified 24-month warranty.",
                "access_scope": "internal",
                "created_by": "author",
            }
        )
        service.approve_source_evidence(replacement["evidence_code"], "reviewer")
        replacement_claim = service.create_fact_claim(
            {
                "fact_title": "Replacement warranty",
                "claim": "The product has a 24-month warranty.",
                "source_evidence_code": replacement["evidence_code"],
                "citation_excerpt": "The product has a verified 24-month warranty.",
                "created_by": "author",
            }
        )
        assert replacement_claim is not None
        service.approve_fact_claim(replacement_claim["claim_code"], "reviewer")
        revoked_claim = service.revoke_fact_claim(
            replacement_claim["claim_code"], "reviewer", "The warranty terms changed again."
        )
        assert revoked_claim is not None
        assert revoked_claim["status"] == "revoked"
        assert revoked_claim["revoked_reason"] == "The warranty terms changed again."
        assert service.resolve_approved_fact_claim(replacement_claim["claim_code"]) is None
        with c.cursor() as cur:
            cur.execute(
                "SELECT status FROM functional_knowledge_facts WHERE fact_code = %s",
                (replacement_claim["fact_code"],),
            )
            assert cur.fetchone()[0] == "revoked"


def test_knowledge_evidence_rejection_preserves_draft_review_history() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        service = FunctionalKnowledgeService(c)
        source = service.create_source_evidence(
            {
                "source_type": "document",
                "title": "Incomplete product specification",
                "excerpt": "The product warranty wording is incomplete.",
                "access_scope": "internal",
                "created_by": "author",
            }
        )
        rejected_source = service.reject_source_evidence(
            source["evidence_code"], "reviewer", "The document is incomplete."
        )
        assert rejected_source is not None
        assert rejected_source["status"] == "rejected"
        assert rejected_source["rejected_by"] == "reviewer"
        assert rejected_source["rejection_reason"] == "The document is incomplete."
        assert service.reject_source_evidence(
            source["evidence_code"], "later-reviewer", "A stale callback."
        )["rejection_reason"] == "The document is incomplete."
        with pytest.raises(RuntimeError, match="Only draft source evidence"):
            service.approve_source_evidence(source["evidence_code"], "reviewer")

        approved_source = service.create_source_evidence(
            {
                "source_type": "document",
                "title": "Reviewable product specification",
                "excerpt": "The product includes a verified 12-month warranty.",
                "access_scope": "internal",
                "created_by": "author",
            }
        )
        service.approve_source_evidence(approved_source["evidence_code"], "reviewer")
        claim = service.create_fact_claim(
            {
                "fact_title": "Warranty",
                "claim": "The product includes a 12-month warranty.",
                "source_evidence_code": approved_source["evidence_code"],
                "citation_excerpt": "The product includes a verified 12-month warranty.",
                "created_by": "author",
            }
        )
        assert claim is not None
        rejected_claim = service.reject_fact_claim(
            claim["claim_code"], "reviewer", "The citation needs a field reference."
        )
        assert rejected_claim is not None
        assert rejected_claim["status"] == "rejected"
        assert rejected_claim["rejection_reason"] == "The citation needs a field reference."
        assert service.resolve_approved_fact_claim(claim["claim_code"]) is None
        with c.cursor() as cur:
            cur.execute(
                "SELECT status FROM functional_knowledge_facts WHERE fact_code = %s",
                (claim["fact_code"],),
            )
            assert cur.fetchone()[0] == "rejected"

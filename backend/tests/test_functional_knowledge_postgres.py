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

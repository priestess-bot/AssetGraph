from __future__ import annotations
from datetime import UTC, datetime
import os
import psycopg
import pytest
from app.services.functional_knowledge import FunctionalKnowledgeService
from app.services.functional_content import FunctionalContentService
from app.repositories.maitu_workbench import MaituWorkbenchRepository

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
        assert claim["citation_start_offset"] == 0
        assert claim["citation_end_offset"] == len("The device includes a verified 12-month warranty.")
        approved = service.approve_fact_claim(claim["claim_code"], "reviewer")
        assert approved is not None
        assert approved["status"] == "approved"
        assert approved["source_evidence_code"] == source["evidence_code"]


def test_source_evidence_creates_an_immutable_local_extraction_run() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        service = FunctionalKnowledgeService(c)
        source = service.create_source_evidence(
            {
                "source_type": "export",
                "title": "Controlled source export",
                "excerpt": "The source export states an approved warranty boundary.",
                "access_scope": "internal",
                "extractor_strategy_ref": "controlled_export_excerpt.v1",
                "extraction_metadata": {
                    "capture_mode": "manual_import",
                    "schema_version": "source-export.v1",
                },
                "created_by": "author",
            }
        )

        runs = service.list_source_extraction_runs(source["evidence_code"])

        assert source["extractor_strategy_ref"] == "controlled_export_excerpt.v1"
        assert source["extraction_runs"] == runs
        assert runs is not None
        assert len(runs) == 1
        assert runs[0]["evidence_code"] == source["evidence_code"]
        assert runs[0]["extractor_strategy_ref"] == "controlled_export_excerpt.v1"
        assert runs[0]["input_fingerprint_sha256"] == source["content_sha256"]
        assert len(runs[0]["output_checksum_sha256"]) == 64
        assert runs[0]["extraction_metadata"] == {
            "capture_mode": "manual_import",
            "schema_version": "source-export.v1",
        }


def test_knowledge_search_revalidates_lifecycle_time_and_scope_without_authorizing() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        service = FunctionalKnowledgeService(c)
        source = service.create_source_evidence(
            {
                "source_type": "document",
                "title": "Search validation source",
                "excerpt": "The product warranty is verified for the supported market.",
                "access_scope": "internal",
                "created_by": "author",
            }
        )
        service.approve_source_evidence(source["evidence_code"], "reviewer")
        claim = service.create_fact_claim(
            {
                "fact_title": "Search warranty",
                "claim": "The product warranty is verified for the supported market.",
                "source_evidence_code": source["evidence_code"],
                "citation_excerpt": "The product warranty is verified for the supported market.",
                "valid_from": "2026-07-24T00:00:00Z",
                "valid_until": "2026-07-26T00:00:00Z",
                "created_by": "author",
            }
        )
        assert claim is not None
        service.approve_fact_claim(claim["claim_code"], "reviewer")
        rule = service.create_content_rule(
            {
                "rule_kind": "compliance_rule",
                "directive": "must_avoid",
                "title": "Search platform rule",
                "rule_text": "Do not make unsupported warranty claims.",
                "scope": {"platforms": ["douyin"]},
                "source_evidence_code": source["evidence_code"],
                "created_by": "author",
            }
        )
        service.approve_content_rule(rule["rule_code"], "reviewer")

        claim_hits = service.search_knowledge(
            "supported market", as_of=datetime(2026, 7, 25, tzinfo=UTC)
        )
        claim_hit = next(hit for hit in claim_hits if hit["entity_code"] == claim["claim_code"])
        source_hit = next(hit for hit in claim_hits if hit["entity_code"] == source["evidence_code"])
        mismatched_rule = next(
            hit
            for hit in service.search_knowledge(
                "unsupported warranty", as_of=datetime(2026, 7, 25, tzinfo=UTC), platform="kuaishou"
            )
            if hit["entity_code"] == rule["rule_code"]
        )
        expired_claim = next(
            hit
            for hit in service.search_knowledge(
                "supported market", as_of=datetime(2026, 7, 27, tzinfo=UTC)
            )
            if hit["entity_code"] == claim["claim_code"]
        )

        assert claim_hit["validation"] == {
            "lifecycle": "approved",
            "source": "approved",
            "validity": "valid",
            "scope": "not_scoped",
            "rights": "not_modeled",
            "content_eligible": True,
            "authorization_eligible": False,
            "blocking_rule_codes": [],
        }
        assert source_hit["validation"]["content_eligible"] is False
        assert "KNOWLEDGE_SOURCE_EVIDENCE_NOT_SELECTABLE" in source_hit["validation"]["blocking_rule_codes"]
        assert "KNOWLEDGE_SCOPE_MISMATCH" in mismatched_rule["validation"]["blocking_rule_codes"]
        assert "KNOWLEDGE_OUTSIDE_VALIDITY_WINDOW" in expired_claim["validation"]["blocking_rule_codes"]


def test_knowledge_search_includes_the_current_approved_product_fact_card_revision() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        repository = MaituWorkbenchRepository(c)
        card = repository.create_product_fact_card(
            {
                "title": "Searchable verified product facts",
                "product_code": "SEARCH-FACT-001",
                "content": {
                    "product_name": "Searchable product",
                    "positioning": "Verified daily product",
                    "verified_facts": ["The product has a verified 12-month warranty."],
                    "valid_from": "2026-07-24T00:00:00Z",
                    "valid_until": "2026-07-26T00:00:00Z",
                    "applicable_platforms": ["douyin"],
                },
                "approve": True,
                "approved_by": "reviewer",
            },
            content_sha256="d" * 64,
        )
        service = FunctionalKnowledgeService(c)
        hit = next(
            item
            for item in service.search_knowledge(
                "verified 12-month", as_of=datetime(2026, 7, 25, tzinfo=UTC), platform="douyin"
            )
            if item["entity_code"] == card["fact_card_code"]
        )

        assert hit["entity_type"] == "product_fact_card"
        assert hit["revision_number"] == 1
        assert hit["validation"]["content_eligible"] is True
        assert hit["validation"]["authorization_eligible"] is False


def test_fact_claim_lineage_follows_only_immutable_pinned_content_revisions() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        knowledge = FunctionalKnowledgeService(c)
        source = knowledge.create_source_evidence(
            {
                "source_type": "document",
                "title": "Lineage source",
                "excerpt": "The product has a verified 12-month warranty.",
                "access_scope": "internal",
                "created_by": "author",
            }
        )
        knowledge.approve_source_evidence(source["evidence_code"], "reviewer")
        claim = knowledge.create_fact_claim(
            {
                "fact_title": "Warranty",
                "claim": "The product has a 12-month warranty.",
                "source_evidence_code": source["evidence_code"],
                "citation_excerpt": "The product has a verified 12-month warranty.",
                "created_by": "author",
            }
        )
        assert claim is not None
        knowledge.approve_fact_claim(claim["claim_code"], "reviewer")

        content = FunctionalContentService(c)
        project = content.create_project(
            {
                "title": "Claim lineage project",
                "generation_goal": "Explain an approved fact.",
                "fact_claim_codes": [claim["claim_code"]],
            },
            actor_id="operator",
        )
        content.confirm_project(project["project_code"], expected_revision=1, actor_id="operator")
        content.parse_design_brief(
            project["project_code"], expected_revision=1, raw_input="Use the approved fact.", actor_id="operator"
        )
        content.confirm_design_brief(project["project_code"], expected_revision=1, actor_id="operator")
        content.generate_chain(project["project_code"], actor_id="operator")

        lineage = knowledge.get_fact_claim_lineage(claim["claim_code"])

        assert lineage is not None
        assert lineage["claim_status"] == "approved"
        assert lineage["source_status"] == "approved"
        assert ("pins_fact_claim", "content_project", project["project_code"]) in {
            (item["relation_type"], item["object_type"], item["object_code"])
            for item in lineage["uses"]
        }
        assert {item["object_type"] for item in lineage["uses"]} >= {
            "content_project",
            "story_brief",
            "content_script",
            "content_program",
            "shot_list",
        }


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

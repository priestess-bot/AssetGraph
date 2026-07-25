from __future__ import annotations

from app.services.functional_knowledge_graph import FunctionalKnowledgeGraphProjectionService


def test_materialize_preserves_recorded_and_descriptive_relationships() -> None:
    rows = {
        "source_evidences": [
            {
                "evidence_code": "EVIDENCE-001",
                "source_type": "document",
                "title": "Product sheet",
                "access_scope": "internal",
                "content_sha256": "a" * 64,
                "status": "approved",
                "captured_at": None,
            }
        ],
        "fact_claims": [
            {
                "claim_code": "CLAIM-001",
                "fact_code": "FACT-001",
                "source_evidence_code": "EVIDENCE-001",
                "field_path": "warranty",
                "status": "approved",
                "fingerprint_sha256": "b" * 64,
                "valid_from": None,
                "valid_until": None,
            }
        ],
        "content_rules": [
            {
                "rule_code": "RULE-001",
                "rule_kind": "expression_ban",
                "directive": "must_avoid",
                "title": "No unsupported claims",
                "source_evidence_code": "EVIDENCE-001",
                "status": "approved",
                "fingerprint_sha256": "c" * 64,
                "valid_from": None,
                "valid_until": None,
            }
        ],
        "content_projects": [
            {
                "project_code": "CONTENT-001",
                "revision_number": 2,
                "status": "confirmed",
                "generation_goal": "Explain the warranty",
                "title": "Warranty room",
                "fingerprint_sha256": "d" * 64,
                "content": {
                    "fact_claim_refs": [{"claim_code": "CLAIM-001", "fingerprint_sha256": "b" * 64}],
                    "content_rule_refs": [{"rule_code": "RULE-001", "fingerprint_sha256": "c" * 64}],
                },
            }
        ],
        "variants": [
            {
                "variant_code": "VARIANT-001",
                "revision_number": 1,
                "status": "confirmed",
                "carrier_kind": "live_room",
                "project_code": "CONTENT-001",
                "source_project_code": "CONTENT-001",
                "source_project_revision": 2,
                "fingerprint_sha256": "e" * 64,
            }
        ],
        "effect_estimates": [
            {
                "effect_code": "EFFECT-001",
                "revision_number": 1,
                "attribution_report_code": "REPORT-001",
                "subject_type": "content_project",
                "subject_code": "CONTENT-001",
                "metric_key": "conversion",
                "evidence_level": "descriptive",
                "status": "approved",
                "fingerprint_sha256": "f" * 64,
                "effect_payload": {"subject_snapshot": {"project_code": "CONTENT-001", "revision_number": 2}},
            }
        ],
    }

    nodes, edges = FunctionalKnowledgeGraphProjectionService.materialize(rows)

    assert {(node.node_type, node.node_code, node.revision_number) for node in nodes} == {
        ("source_evidence", "EVIDENCE-001", 0),
        ("fact_claim", "CLAIM-001", 0),
        ("content_rule", "RULE-001", 0),
        ("content_project", "CONTENT-001", 2),
        ("production_variant", "VARIANT-001", 1),
        ("effect_estimate", "EFFECT-001", 1),
    }
    edge_types = {(edge.relationship_type, edge.assertion_kind, edge.source, edge.target) for edge in edges}
    assert ("SUPPORTS", "recorded_fact", ("source_evidence", "EVIDENCE-001", 0), ("fact_claim", "CLAIM-001", 0)) in edge_types
    assert ("CITES", "recorded_fact", ("content_project", "CONTENT-001", 2), ("content_rule", "RULE-001", 0)) in edge_types
    assert ("DERIVED_FROM", "recorded_fact", ("content_project", "CONTENT-001", 2), ("production_variant", "VARIANT-001", 1)) in edge_types
    assert ("ESTIMATED_EFFECT_ON", "descriptive_association", ("effect_estimate", "EFFECT-001", 1), ("content_project", "CONTENT-001", 2)) in edge_types


def test_materialize_drops_edges_without_an_authoritative_target() -> None:
    rows = {
        "source_evidences": [],
        "fact_claims": [],
        "content_rules": [],
        "content_projects": [{
            "project_code": "CONTENT-001", "revision_number": 1, "status": "confirmed",
            "generation_goal": "Goal", "title": "Title", "fingerprint_sha256": "a" * 64,
            "content": {"fact_claim_refs": [{"claim_code": "CLAIM-MISSING"}]},
        }],
        "variants": [],
        "effect_estimates": [],
    }

    nodes, edges = FunctionalKnowledgeGraphProjectionService.materialize(rows)

    assert len(nodes) == 1
    assert edges == []

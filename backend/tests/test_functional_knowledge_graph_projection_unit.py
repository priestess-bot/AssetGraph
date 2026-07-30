from __future__ import annotations

from app.services.functional_knowledge_graph import FunctionalKnowledgeGraphProjectionService


def test_materialize_preserves_recorded_and_descriptive_relationships() -> None:
    rows = {
        "assets": [{
            "asset_code": "ASSET-001", "title": "Product image", "media_kind": "image",
            "material_roles": ["product"], "execution_capability": "maitu_bound",
            "checksum_sha256": "k" * 64, "status": "ready", "updated_at": None,
        }],
        "product_fact_cards": [{
            "fact_card_code": "FACT-CARD-001", "title": "Product facts", "product_code": "SKU-001",
            "version_number": 1, "status": "approved", "content_sha256": "m" * 64,
            "content": {"product_name": "Demo product", "verified_facts": ["Recorded fact"]},
        }],
        "templates": [{
            "template_code": "TEMPLATE-001", "name": "Selling strategy", "revision_number": 1,
            "status": "published", "content_readiness": "ready", "layout_fidelity": "approximate",
            "buildability": "reference_only", "contract_version": "content-strategy.v2", "content_fingerprint": "l" * 64,
        }],
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
                    "fact_card_refs": [{"fact_card_code": "FACT-CARD-001", "version_number": 1, "content_sha256": "m" * 64}],
                    "content_rule_refs": [{"rule_code": "RULE-001", "fingerprint_sha256": "c" * 64}],
                    "primary_template_ref": {"template_code": "TEMPLATE-001", "revision": 1, "selection_role": "primary", "contribution": "primary_structure"},
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
        "live_room_plans": [
            {
                "plan_code": "ROOM-PLAN-001", "project_code": "CONTENT-001", "variant_code": "VARIANT-001",
                "variant_revision": 1, "target_live_room_id": "room-001", "status": "ready",
                "execution_status": "not_requested", "release_code": "RELEASE-001", "release_revision": 1,
                "selected_asset_codes": ["ASSET-001"],
                "created_at": None, "updated_at": None,
            }
        ],
        "maitu_scenes": [{
            "scene_blueprint_code": "SCENE-001", "revision_number": 1, "title": "Opening",
            "sort_order": 0, "estimated_active_start_ms": 0, "estimated_active_end_ms": 30_000,
            "fingerprint_sha256": "n" * 64, "variant_code": "VARIANT-001", "variant_revision": 1,
            "plan_code": "ROOM-PLAN-001", "program_segment_code": "SEGMENT-001", "shot_code": "SHOT-001",
        }],
        "layer_blueprints": [{
            "layer_blueprint_code": "LAYER-001", "revision_number": 1, "asset_code": "ASSET-001",
            "material_role": "product", "normalized_geometry": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.5},
            "z_order": 20, "source_script_block_codes": ["BLOCK-001"], "fingerprint_sha256": "o" * 64,
            "scene_blueprint_code": "SCENE-001", "scene_revision": 1,
        }],
        "video_plans": [],
        "releases": [
            {
                "release_code": "RELEASE-001", "subject_type": "live_room_plan", "subject_code": "ROOM-PLAN-001",
                "subject_revision": 1, "carrier_kind": "live_room_draft", "status": "candidate",
                "current_manifest_revision": 1, "release_fingerprint": "g" * 64, "created_at": None, "updated_at": None,
            }
        ],
        "delivery_attempts": [{
            "delivery_code": "DELIVERY-001", "release_code": "RELEASE-001", "release_revision": 1,
            "target_type": "maitu_room", "target_id": "room-001", "adapter_type": "manual_handoff",
            "status": "succeeded", "external_identity": {"room_id": "room-001"},
            "readback_evidence": {"matched": True}, "error_code": None,
            "started_at": None, "completed_at": None,
        }],
        "operation_sessions": [
            {
                "session_code": "SESSION-001", "title": "Observed room", "platform": "douyin",
                "content_project_code": "CONTENT-001", "source_kind": "manual_import", "import_version": 1,
                "live_room_plan_code": "ROOM-PLAN-001", "variant_code": "VARIANT-001", "release_code": "RELEASE-001",
                "started_at": None, "ended_at": None, "metrics": {}, "created_at": None, "updated_at": None,
            }
        ],
        "content_exposures": [
            {
                "exposure_code": "EXPOSURE-001", "session_code": "SESSION-001", "session_import_version": 1,
                "plan_code": "ROOM-PLAN-001", "variant_code": "VARIANT-001", "release_code": "RELEASE-001",
                "scene_code": "SCENE-001", "source_kind": "manual_observation", "confidence": 0.8,
                "status": "active", "started_at": None, "ended_at": None, "created_at": None,
                "plan_node_type": "live_room_plan", "plan_node_code": "ROOM-PLAN-001",
                "scene_blueprint_code": "SCENE-001", "scene_revision": 1,
            }
        ],
        "metric_definitions": [
            {
                "metric_code": "METRIC-CONVERSION", "revision_number": 1, "status": "active",
                "name": "Conversion", "unit": "ratio", "value_type": "ratio", "aggregation": "ratio",
                "fingerprint_sha256": "h" * 64,
            }
        ],
        "session_metric_snapshots": [
            {
                "snapshot_code": "METRIC-SNAP-001", "session_code": "SESSION-001", "session_import_version": 1,
                "metric_key": "conversion", "metric_code": "METRIC-CONVERSION", "metric_revision": 1,
                "aggregation": "ratio", "status": "ready", "source_event_count": 12, "fingerprint_sha256": "i" * 64,
            }
        ],
        "attribution_reports": [
            {
                "report_code": "REPORT-001", "metric_key": "conversion", "evidence_level": "descriptive",
                "status": "published_descriptive", "session_refs": [{"session_code": "SESSION-001", "import_version": 1}],
                "supersedes_report_code": None, "fingerprint_sha256": "j" * 64,
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
        ("asset", "ASSET-001", 0),
        ("product_fact_card", "FACT-CARD-001", 1),
        ("content_strategy_template", "TEMPLATE-001", 1),
        ("fact_claim", "CLAIM-001", 0),
        ("content_rule", "RULE-001", 0),
        ("content_project", "CONTENT-001", 2),
        ("production_variant", "VARIANT-001", 1),
        ("live_room_plan", "ROOM-PLAN-001", 0),
        ("maitu_scene_blueprint", "SCENE-001", 1),
        ("layer_blueprint", "LAYER-001", 1),
        ("release", "RELEASE-001", 1),
        ("delivery_attempt", "DELIVERY-001", 0),
        ("operation_session", "SESSION-001", 1),
        ("content_exposure", "EXPOSURE-001", 0),
        ("metric_definition", "METRIC-CONVERSION", 1),
        ("session_metric_snapshot", "METRIC-SNAP-001", 0),
        ("attribution_report", "REPORT-001", 0),
        ("effect_estimate", "EFFECT-001", 1),
    }
    edge_types = {(edge.relationship_type, edge.assertion_kind, edge.source, edge.target) for edge in edges}
    assert ("SUPPORTS", "recorded_fact", ("source_evidence", "EVIDENCE-001", 0), ("fact_claim", "CLAIM-001", 0)) in edge_types
    assert ("CITES", "recorded_fact", ("content_project", "CONTENT-001", 2), ("content_rule", "RULE-001", 0)) in edge_types
    assert ("CITES", "recorded_fact", ("content_project", "CONTENT-001", 2), ("content_strategy_template", "TEMPLATE-001", 1)) in edge_types
    assert ("CITES", "recorded_fact", ("content_project", "CONTENT-001", 2), ("product_fact_card", "FACT-CARD-001", 1)) in edge_types
    assert ("DERIVED_FROM", "recorded_fact", ("content_project", "CONTENT-001", 2), ("production_variant", "VARIANT-001", 1)) in edge_types
    assert ("PROJECTED_AS", "recorded_fact", ("production_variant", "VARIANT-001", 1), ("live_room_plan", "ROOM-PLAN-001", 0)) in edge_types
    assert ("RELEASED_AS", "recorded_fact", ("live_room_plan", "ROOM-PLAN-001", 0), ("release", "RELEASE-001", 1)) in edge_types
    assert ("USES_ASSET", "recorded_fact", ("live_room_plan", "ROOM-PLAN-001", 0), ("asset", "ASSET-001", 0)) in edge_types
    assert ("CONTAINS_SCENE", "recorded_fact", ("live_room_plan", "ROOM-PLAN-001", 0), ("maitu_scene_blueprint", "SCENE-001", 1)) in edge_types
    assert ("CONTAINS_LAYER", "recorded_fact", ("maitu_scene_blueprint", "SCENE-001", 1), ("layer_blueprint", "LAYER-001", 1)) in edge_types
    assert ("USES_ASSET", "recorded_fact", ("layer_blueprint", "LAYER-001", 1), ("asset", "ASSET-001", 0)) in edge_types
    assert ("DELIVERED_BY", "recorded_fact", ("release", "RELEASE-001", 1), ("delivery_attempt", "DELIVERY-001", 0)) in edge_types
    assert ("OBSERVES_SCENE", "recorded_fact", ("content_exposure", "EXPOSURE-001", 0), ("maitu_scene_blueprint", "SCENE-001", 1)) in edge_types
    assert ("EXPOSED_DURING", "recorded_fact", ("live_room_plan", "ROOM-PLAN-001", 0), ("operation_session", "SESSION-001", 1)) in edge_types
    assert ("MEASURED_BY", "recorded_fact", ("operation_session", "SESSION-001", 1), ("session_metric_snapshot", "METRIC-SNAP-001", 0)) in edge_types
    assert ("USES_METRIC_DEFINITION", "recorded_fact", ("session_metric_snapshot", "METRIC-SNAP-001", 0), ("metric_definition", "METRIC-CONVERSION", 1)) in edge_types
    assert ("DERIVED_FROM", "recorded_fact", ("effect_estimate", "EFFECT-001", 1), ("attribution_report", "REPORT-001", 0)) in edge_types
    assert ("ESTIMATED_EFFECT_ON", "descriptive_association", ("effect_estimate", "EFFECT-001", 1), ("content_project", "CONTENT-001", 2)) in edge_types


def test_materialize_drops_edges_without_an_authoritative_target() -> None:
    rows = {
        "assets": [],
        "product_fact_cards": [],
        "templates": [],
        "source_evidences": [],
        "fact_claims": [],
        "content_rules": [],
        "content_projects": [{
            "project_code": "CONTENT-001", "revision_number": 1, "status": "confirmed",
            "generation_goal": "Goal", "title": "Title", "fingerprint_sha256": "a" * 64,
            "content": {"fact_claim_refs": [{"claim_code": "CLAIM-MISSING"}]},
        }],
        "variants": [],
        "live_room_plans": [],
        "video_plans": [],
        "releases": [],
        "operation_sessions": [],
        "content_exposures": [],
        "metric_definitions": [],
        "session_metric_snapshots": [],
        "attribution_reports": [],
        "effect_estimates": [],
    }

    nodes, edges = FunctionalKnowledgeGraphProjectionService.materialize(rows)

    assert len(nodes) == 1
    assert edges == []


def test_search_lineage_matches_scope_and_walks_both_edge_directions() -> None:
    service = object.__new__(FunctionalKnowledgeGraphProjectionService)
    service.current = lambda: {
        "projection_code": "GRAPH-001",
        "revision_number": 2,
        "is_stale": False,
        "nodes": [
            {"node_type": "asset", "node_code": "ASSET-001", "revision_number": 0, "properties": {"title": "红酒主图"}},
            {"node_type": "layer_blueprint", "node_code": "LAYER-001", "revision_number": 1, "properties": {}},
            {"node_type": "maitu_scene_blueprint", "node_code": "SCENE-001", "revision_number": 1, "properties": {"title": "商品讲解"}},
        ],
        "edges": [
            {
                "source_node_type": "layer_blueprint", "source_node_code": "LAYER-001", "source_revision_number": 1,
                "target_node_type": "asset", "target_node_code": "ASSET-001", "target_revision_number": 0,
                "relationship_type": "USES_ASSET", "assertion_kind": "recorded_fact",
            },
            {
                "source_node_type": "maitu_scene_blueprint", "source_node_code": "SCENE-001", "source_revision_number": 1,
                "target_node_type": "layer_blueprint", "target_node_code": "LAYER-001", "target_revision_number": 1,
                "relationship_type": "CONTAINS_LAYER", "assertion_kind": "recorded_fact",
            },
        ],
    }

    result = service.search_lineage("红酒", "material")

    assert result["projection_code"] == "GRAPH-001"
    assert result["results"][0]["match"]["node_code"] == "ASSET-001"
    assert {node["node_code"] for node in result["results"][0]["nodes"]} == {
        "ASSET-001", "LAYER-001", "SCENE-001"
    }
    assert len(result["results"][0]["edges"]) == 2

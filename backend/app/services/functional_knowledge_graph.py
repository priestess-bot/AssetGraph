from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.services.functional_knowledge import FunctionalKnowledgeService


ONTOLOGY_VERSION = "knowledge-lineage.v1"


@dataclass(frozen=True)
class GraphNodeInput:
    node_type: str
    node_code: str
    revision_number: int
    status: str | None
    properties: dict[str, object]
    source_fingerprint: str

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.node_type, self.node_code, self.revision_number)


@dataclass(frozen=True)
class GraphEdgeInput:
    source: tuple[str, str, int]
    target: tuple[str, str, int]
    relationship_type: str
    assertion_kind: str
    confidence: float | None
    valid_from: datetime | None
    valid_until: datetime | None
    evidence: dict[str, object]

    @property
    def key(self) -> tuple[object, ...]:
        return (
            self.source,
            self.target,
            self.relationship_type,
            self.assertion_kind,
        )


class FunctionalKnowledgeGraphProjectionService:
    """Build a local snapshot graph from authoritative relational records.

    This service intentionally does not infer authorization, truth, or causal
    relationships. Every edge either mirrors a stored relation or identifies a
    descriptive effect estimate explicitly as an association.
    """

    def __init__(self, connection: Connection):
        self.connection = connection

    def rebuild(self, actor: str) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('functional_knowledge_graph_projection'))")
                nodes, edges = self._snapshot(cur)
                watermark = self._watermark(nodes, edges)
                cur.execute(
                    "SELECT COALESCE(MAX(revision_number), 0) AS revision FROM functional_knowledge_graph_projections"
                )
                revision_number = int(cur.fetchone()["revision"]) + 1
                cur.execute(
                    "UPDATE functional_knowledge_graph_projections SET status = 'superseded' WHERE status = 'completed'"
                )
                projection_code = FunctionalKnowledgeService._next(
                    cur, "functional_knowledge_graph_projection", "GRAPH"
                )
                snapshot_fingerprint = canonical_fingerprint(
                    {
                        "ontology_version": ONTOLOGY_VERSION,
                        "source_watermark": watermark,
                        "nodes": [self._node_identity(node) for node in nodes],
                        "edges": [self._edge_identity(edge) for edge in edges],
                    }
                )
                cur.execute(
                    """INSERT INTO functional_knowledge_graph_projections
                       (projection_code, revision_number, ontology_version, source_watermark,
                        snapshot_fingerprint_sha256, node_count, edge_count, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        projection_code,
                        revision_number,
                        ONTOLOGY_VERSION,
                        Jsonb(watermark),
                        snapshot_fingerprint,
                        len(nodes),
                        len(edges),
                        actor,
                    ),
                )
                projection = dict(cur.fetchone())
                node_ids: dict[tuple[str, str, int], str] = {}
                for node in nodes:
                    cur.execute(
                        """INSERT INTO functional_knowledge_graph_nodes
                           (projection_id, node_type, node_code, revision_number, status,
                            properties, source_fingerprint_sha256)
                           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (
                            projection["id"],
                            node.node_type,
                            node.node_code,
                            node.revision_number,
                            node.status,
                            Jsonb(node.properties),
                            node.source_fingerprint,
                        ),
                    )
                    node_ids[node.key] = str(cur.fetchone()["id"])
                for edge in edges:
                    cur.execute(
                        """INSERT INTO functional_knowledge_graph_edges
                           (projection_id, source_node_id, target_node_id, relationship_type,
                            assertion_kind, confidence, valid_from, valid_until, evidence)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            projection["id"],
                            node_ids[edge.source],
                            node_ids[edge.target],
                            edge.relationship_type,
                            edge.assertion_kind,
                            edge.confidence,
                            edge.valid_from,
                            edge.valid_until,
                            Jsonb(edge.evidence),
                        ),
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self._read_projection(projection_code) or projection

    def current(self) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT projection_code FROM functional_knowledge_graph_projections WHERE status = 'completed' ORDER BY revision_number DESC LIMIT 1"
            )
            row = cur.fetchone()
        return self._read_projection(row["projection_code"]) if row else None

    def get(self, projection_code: str) -> dict[str, Any] | None:
        return self._read_projection(projection_code)

    def _read_projection(self, projection_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM functional_knowledge_graph_projections WHERE projection_code = %s",
                (projection_code,),
            )
            projection = cur.fetchone()
            if projection is None:
                return None
            nodes, edges = self._snapshot(cur)
            current_watermark = self._watermark(nodes, edges)
            cur.execute(
                """SELECT node_type, node_code, revision_number, status, properties,
                          source_fingerprint_sha256, created_at
                   FROM functional_knowledge_graph_nodes
                   WHERE projection_id = %s
                   ORDER BY node_type, node_code, revision_number""",
                (projection["id"],),
            )
            graph_nodes = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """SELECT source.node_type AS source_node_type, source.node_code AS source_node_code,
                          source.revision_number AS source_revision_number,
                          target.node_type AS target_node_type, target.node_code AS target_node_code,
                          target.revision_number AS target_revision_number,
                          edge.relationship_type, edge.assertion_kind, edge.confidence,
                          edge.valid_from, edge.valid_until, edge.evidence, edge.created_at
                   FROM functional_knowledge_graph_edges AS edge
                   JOIN functional_knowledge_graph_nodes AS source ON source.id = edge.source_node_id
                   JOIN functional_knowledge_graph_nodes AS target ON target.id = edge.target_node_id
                   WHERE edge.projection_id = %s
                   ORDER BY source.node_type, source.node_code, source.revision_number,
                            edge.relationship_type, target.node_type, target.node_code, target.revision_number""",
                (projection["id"],),
            )
            graph_edges = [dict(row) for row in cur.fetchall()]
        result = dict(projection)
        result["is_stale"] = projection["source_watermark"].get("source_fingerprint") != current_watermark["source_fingerprint"]
        result["current_source_watermark"] = current_watermark
        result["nodes"] = graph_nodes
        result["edges"] = graph_edges
        return result

    @classmethod
    def materialize(cls, rows: dict[str, list[dict[str, Any]]]) -> tuple[list[GraphNodeInput], list[GraphEdgeInput]]:
        nodes: list[GraphNodeInput] = []
        edges: list[GraphEdgeInput] = []

        def add_node(node_type: str, code: str, revision: int, status: str | None, properties: dict[str, object], fingerprint: str) -> None:
            nodes.append(GraphNodeInput(node_type, code, revision, status, properties, fingerprint))

        for row in rows.get("assets", []):
            add_node(
                "asset", row["asset_code"], 0, row["status"],
                {"title": row.get("title"), "media_kind": row.get("media_kind"), "material_roles": row.get("material_roles") or [], "execution_capability": row.get("execution_capability")},
                row.get("checksum_sha256") or canonical_fingerprint(row),
            )
        for row in rows.get("templates", []):
            add_node(
                "content_strategy_template", row["template_code"], int(row["revision_number"]), row["status"],
                {"name": row["name"], "content_readiness": row["content_readiness"], "layout_fidelity": row["layout_fidelity"], "buildability": row["buildability"], "contract_version": row["contract_version"]},
                row["content_fingerprint"],
            )
        for row in rows.get("source_evidences", []):
            add_node(
                "source_evidence", row["evidence_code"], 0, row["status"],
                {"title": row["title"], "source_type": row["source_type"], "access_scope": row["access_scope"], "content_sha256": row["content_sha256"]},
                canonical_fingerprint(row),
            )
        for row in rows.get("fact_claims", []):
            add_node(
                "fact_claim", row["claim_code"], 0, row["status"],
                {"fact_code": row["fact_code"], "source_evidence_code": row["source_evidence_code"], "field_path": row.get("field_path")},
                row["fingerprint_sha256"],
            )
            edges.append(GraphEdgeInput(
                ("source_evidence", row["source_evidence_code"], 0), ("fact_claim", row["claim_code"], 0),
                "SUPPORTS", "recorded_fact", 1.0, row.get("valid_from"), row.get("valid_until"),
                {"source_table": "functional_knowledge_fact_claims", "source_code": row["claim_code"]},
            ))
        for row in rows.get("content_rules", []):
            add_node(
                "content_rule", row["rule_code"], 0, row["status"],
                {"title": row["title"], "rule_kind": row["rule_kind"], "directive": row["directive"], "source_evidence_code": row.get("source_evidence_code")},
                row["fingerprint_sha256"],
            )
            if row.get("source_evidence_code"):
                edges.append(GraphEdgeInput(
                    ("source_evidence", row["source_evidence_code"], 0), ("content_rule", row["rule_code"], 0),
                    "SUPPORTS", "recorded_fact", 1.0, row.get("valid_from"), row.get("valid_until"),
                    {"source_table": "functional_knowledge_content_rules", "source_code": row["rule_code"]},
                ))
        for row in rows.get("content_projects", []):
            project_key = ("content_project", row["project_code"], int(row["revision_number"]))
            add_node(
                *project_key, row["status"],
                {"title": row["title"], "generation_goal": row["generation_goal"]}, row["fingerprint_sha256"],
            )
            content = row.get("content") or {}
            for ref in content.get("fact_claim_refs") or []:
                claim_code = ref.get("claim_code") if isinstance(ref, dict) else None
                if claim_code:
                    edges.append(GraphEdgeInput(
                        project_key, ("fact_claim", str(claim_code), 0), "CITES", "recorded_fact", 1.0,
                        None, None, {"source_table": "content_project_revisions", "source_code": row["project_code"], "source_revision": row["revision_number"], "pinned_fingerprint": ref.get("fingerprint_sha256")},
                    ))
            for ref in content.get("content_rule_refs") or []:
                rule_code = ref.get("rule_code") if isinstance(ref, dict) else None
                if rule_code:
                    edges.append(GraphEdgeInput(
                        project_key, ("content_rule", str(rule_code), 0), "CITES", "recorded_fact", 1.0,
                        None, None, {"source_table": "content_project_revisions", "source_code": row["project_code"], "source_revision": row["revision_number"], "pinned_fingerprint": ref.get("fingerprint_sha256")},
                    ))
            for ref in [content.get("primary_template_ref"), *(content.get("secondary_template_refs") or [])]:
                template_code = ref.get("template_code") if isinstance(ref, dict) else None
                revision_number = ref.get("revision") if isinstance(ref, dict) else None
                if template_code and isinstance(revision_number, int):
                    edges.append(GraphEdgeInput(
                        project_key, ("content_strategy_template", str(template_code), revision_number), "CITES",
                        "recorded_fact", 1.0, None, None,
                        {"source_table": "content_project_revisions", "source_code": row["project_code"], "source_revision": row["revision_number"], "selection_role": ref.get("selection_role"), "contribution": ref.get("contribution")},
                    ))
        for row in rows.get("variants", []):
            variant_key = ("production_variant", row["variant_code"], int(row["revision_number"]))
            add_node(
                *variant_key, row["status"],
                {"carrier_kind": row["carrier_kind"], "project_code": row["project_code"]}, row["fingerprint_sha256"],
            )
            if row.get("source_project_code") and row.get("source_project_revision"):
                edges.append(GraphEdgeInput(
                    ("content_project", row["source_project_code"], int(row["source_project_revision"])), variant_key,
                    "DERIVED_FROM", "recorded_fact", 1.0, None, None,
                    {"source_table": "production_variant_revisions", "source_code": row["variant_code"], "source_revision": row["revision_number"]},
                ))
        for row in rows.get("live_room_plans", []):
            plan_key = ("live_room_plan", row["plan_code"], 0)
            add_node(
                *plan_key, row["status"],
                {
                    "project_code": row["project_code"],
                    "variant_code": row["variant_code"],
                    "target_live_room_id": row["target_live_room_id"],
                    "execution_status": row["execution_status"],
                    "release_code": row.get("release_code"),
                },
                canonical_fingerprint(row),
            )
            if row.get("variant_revision") is not None:
                edges.append(GraphEdgeInput(
                    ("production_variant", row["variant_code"], int(row["variant_revision"])), plan_key,
                    "PROJECTED_AS", "recorded_fact", 1.0, None, None,
                    {"source_table": "functional_live_room_plans", "source_code": row["plan_code"]},
                ))
            if row.get("release_code"):
                edges.append(GraphEdgeInput(
                    plan_key, ("release", row["release_code"], int(row["release_revision"])), "RELEASED_AS",
                    "recorded_fact", 1.0, None, None,
                    {"source_table": "functional_live_room_plans", "source_code": row["plan_code"]},
                ))
            for asset_code in row.get("selected_asset_codes") or []:
                edges.append(GraphEdgeInput(
                    plan_key, ("asset", str(asset_code), 0), "USES_ASSET", "recorded_fact", 1.0,
                    None, None, {"source_table": "functional_live_room_plans", "source_code": row["plan_code"]},
                ))
        for row in rows.get("video_plans", []):
            plan_key = ("rendered_video_plan", row["plan_code"], 0)
            add_node(
                *plan_key, None,
                {
                    "project_code": row["project_code"],
                    "variant_code": row["variant_code"],
                    "video_job_code": row["video_job_code"],
                    "release_code": row.get("release_code"),
                },
                canonical_fingerprint(row),
            )
            if row.get("variant_revision") is not None:
                edges.append(GraphEdgeInput(
                    ("production_variant", row["variant_code"], int(row["variant_revision"])), plan_key,
                    "PROJECTED_AS", "recorded_fact", 1.0, None, None,
                    {"source_table": "functional_video_plans", "source_code": row["plan_code"]},
                ))
            if row.get("release_code"):
                edges.append(GraphEdgeInput(
                    plan_key, ("release", row["release_code"], int(row["release_revision"])), "RELEASED_AS",
                    "recorded_fact", 1.0, None, None,
                    {"source_table": "functional_video_plans", "source_code": row["plan_code"]},
                ))
            material_snapshot = row.get("material_snapshot_ref") or {}
            for asset_code in material_snapshot.get("asset_codes") or []:
                edges.append(GraphEdgeInput(
                    plan_key, ("asset", str(asset_code), 0), "USES_ASSET", "recorded_fact", 1.0,
                    None, None, {"source_table": "production_variant_revisions", "source_code": row["variant_code"], "source_revision": row.get("variant_revision")},
                ))
        for row in rows.get("releases", []):
            add_node(
                "release", row["release_code"], int(row["current_manifest_revision"]), row["status"],
                {"subject_type": row["subject_type"], "subject_code": row["subject_code"], "carrier_kind": row["carrier_kind"], "release_fingerprint": row.get("release_fingerprint")},
                canonical_fingerprint(row),
            )
        for row in rows.get("operation_sessions", []):
            add_node(
                "operation_session", row["session_code"], int(row["import_version"]), None,
                {"title": row["title"], "platform": row["platform"], "source_kind": row["source_kind"], "content_project_code": row.get("content_project_code"), "release_code": row.get("release_code")},
                canonical_fingerprint(row),
            )
        for row in rows.get("content_exposures", []):
            exposure_key = ("content_exposure", row["exposure_code"], 0)
            session_key = ("operation_session", row["session_code"], int(row["session_import_version"]))
            add_node(
                *exposure_key, row["status"],
                {"plan_code": row["plan_code"], "variant_code": row["variant_code"], "release_code": row.get("release_code"), "scene_code": row["scene_code"], "source_kind": row["source_kind"]},
                canonical_fingerprint(row),
            )
            edges.append(GraphEdgeInput(
                exposure_key, session_key, "OBSERVED_DURING", "recorded_fact", float(row["confidence"]),
                row["started_at"], row["ended_at"],
                {"source_table": "functional_content_exposures", "source_code": row["exposure_code"], "status": row["status"]},
            ))
            if row.get("plan_node_type") and row.get("plan_node_code"):
                plan_key = (str(row["plan_node_type"]), str(row["plan_node_code"]), 0)
                edges.append(GraphEdgeInput(
                    plan_key, session_key, "EXPOSED_DURING", "recorded_fact", float(row["confidence"]),
                    row["started_at"], row["ended_at"],
                    {"source_table": "functional_content_exposures", "source_code": row["exposure_code"], "scene_code": row["scene_code"], "source_kind": row["source_kind"]},
                ))
        for row in rows.get("metric_definitions", []):
            add_node(
                "metric_definition", row["metric_code"], int(row["revision_number"]), row["status"],
                {"name": row["name"], "unit": row["unit"], "aggregation": row["aggregation"], "value_type": row["value_type"]},
                row["fingerprint_sha256"],
            )
        for row in rows.get("session_metric_snapshots", []):
            snapshot_key = ("session_metric_snapshot", row["snapshot_code"], 0)
            session_key = ("operation_session", row["session_code"], int(row["session_import_version"]))
            metric_key = ("metric_definition", row["metric_code"], int(row["metric_revision"]))
            add_node(
                *snapshot_key, row["status"],
                {"metric_key": row["metric_key"], "metric_code": row["metric_code"], "metric_revision": row["metric_revision"], "aggregation": row["aggregation"], "source_event_count": row["source_event_count"]},
                row["fingerprint_sha256"],
            )
            edges.extend([
                GraphEdgeInput(
                    session_key, snapshot_key, "MEASURED_BY", "recorded_fact", 1.0, None, None,
                    {"source_table": "functional_session_metric_snapshots", "source_code": row["snapshot_code"]},
                ),
                GraphEdgeInput(
                    snapshot_key, metric_key, "USES_METRIC_DEFINITION", "recorded_fact", 1.0, None, None,
                    {"source_table": "functional_session_metric_snapshots", "source_code": row["snapshot_code"]},
                ),
            ])
        for row in rows.get("attribution_reports", []):
            report_key = ("attribution_report", row["report_code"], 0)
            add_node(
                *report_key, row["status"],
                {"metric_key": row["metric_key"], "evidence_level": row["evidence_level"], "publication_scope": "descriptive_only", "supersedes_report_code": row.get("supersedes_report_code")},
                row.get("fingerprint_sha256") or canonical_fingerprint(row),
            )
            for session_ref in row.get("session_refs") or []:
                if not isinstance(session_ref, dict) or not session_ref.get("session_code"):
                    continue
                edges.append(GraphEdgeInput(
                    report_key,
                    ("operation_session", str(session_ref["session_code"]), int(session_ref.get("import_version") or 1)),
                    "DERIVED_FROM", "recorded_fact", 1.0, None, None,
                    {"source_table": "functional_attribution_reports", "source_code": row["report_code"], "session_code": session_ref["session_code"]},
                ))
        for row in rows.get("effect_estimates", []):
            effect_key = ("effect_estimate", row["effect_code"], int(row["revision_number"]))
            add_node(
                *effect_key, row["status"],
                {"subject_type": row["subject_type"], "subject_code": row["subject_code"], "metric_key": row["metric_key"], "evidence_level": row["evidence_level"]}, row["fingerprint_sha256"],
            )
            snapshot = (row.get("effect_payload") or {}).get("subject_snapshot") or {}
            if row["subject_type"] == "content_project" and snapshot.get("project_code") and snapshot.get("revision_number"):
                edges.append(GraphEdgeInput(
                    effect_key, ("content_project", str(snapshot["project_code"]), int(snapshot["revision_number"])),
                    "ESTIMATED_EFFECT_ON", "descriptive_association" if row["evidence_level"] == "descriptive" else "derived_projection",
                    None, None, None,
                    {"source_table": "functional_effect_estimates", "source_code": row["effect_code"], "source_revision": row["revision_number"], "attribution_report_code": row["attribution_report_code"]},
                ))
            edges.append(GraphEdgeInput(
                effect_key, ("attribution_report", row["attribution_report_code"], 0), "DERIVED_FROM",
                "recorded_fact", 1.0, None, None,
                {"source_table": "functional_effect_estimates", "source_code": row["effect_code"], "source_revision": row["revision_number"]},
            ))

        known = {node.key for node in nodes}
        nodes = sorted(nodes, key=lambda node: node.key)
        edges = sorted((edge for edge in edges if edge.source in known and edge.target in known), key=lambda edge: edge.key)
        return nodes, edges

    @classmethod
    def _snapshot(cls, cur: Any) -> tuple[list[GraphNodeInput], list[GraphEdgeInput]]:
        queries = {
            "assets": "SELECT asset_code, title, media_kind, material_roles, execution_capability, checksum_sha256, status, updated_at FROM assets WHERE deleted_at IS NULL ORDER BY asset_code",
            "templates": """SELECT template.template_code, template.name, revision.revision_number, revision.status,
                                     revision.content_readiness, revision.layout_fidelity, revision.buildability,
                                     revision.contract_version, revision.content_fingerprint
                              FROM live_room_templates AS template
                              JOIN live_room_template_revisions AS revision ON revision.template_id = template.id
                              WHERE template.template_kind = 'content_strategy'
                              ORDER BY template.template_code, revision.revision_number""",
            "source_evidences": "SELECT evidence_code, source_type, title, access_scope, content_sha256, status, captured_at FROM functional_knowledge_source_evidences ORDER BY evidence_code",
            "fact_claims": "SELECT claim_code, fact_code, source_evidence_code, field_path, status, fingerprint_sha256, valid_from, valid_until FROM functional_knowledge_fact_claims ORDER BY claim_code",
            "content_rules": "SELECT rule_code, rule_kind, directive, title, source_evidence_code, status, fingerprint_sha256, valid_from, valid_until FROM functional_knowledge_content_rules ORDER BY rule_code",
            "content_projects": """SELECT revision.project_code, revision.revision_number, revision.status, revision.generation_goal, revision.content, revision.fingerprint_sha256, project.title
                                  FROM content_project_revisions AS revision
                                  JOIN content_projects AS project ON project.id = revision.project_id
                                  ORDER BY revision.project_code, revision.revision_number""",
            "variants": """SELECT variant.variant_code, variant.revision_number, variant.status, variant.carrier_kind, variant.fingerprint_sha256,
                                   project.project_code AS source_project_code, project.revision_number AS source_project_revision,
                                   production.project_code
                                FROM production_variant_revisions AS variant
                                JOIN production_variants AS production ON production.id = variant.variant_id
                                LEFT JOIN content_project_revisions AS project ON project.id = variant.source_project_revision_id
                                ORDER BY variant.variant_code, variant.revision_number""",
            "effect_estimates": "SELECT effect_code, revision_number, attribution_report_code, subject_type, subject_code, metric_key, evidence_level, status, effect_payload, fingerprint_sha256 FROM functional_effect_estimates ORDER BY effect_code, revision_number",
            "live_room_plans": """SELECT plan.plan_code, plan.project_code, plan.variant_code, plan.target_live_room_id, plan.status, plan.execution_status,
                                         plan.selected_asset_codes,
                                         plan.release_code, COALESCE(release.current_manifest_revision, 0) AS release_revision,
                                         variant.revision_number AS variant_revision, plan.created_at, plan.updated_at
                                      FROM functional_live_room_plans AS plan
                                      LEFT JOIN production_variant_revisions AS variant
                                        ON variant.variant_code = plan.variant_code AND variant.status = 'confirmed'
                                      LEFT JOIN releases AS release ON release.release_code = plan.release_code
                                      ORDER BY plan.plan_code""",
            "video_plans": """SELECT plan.plan_code, plan.project_code, plan.variant_code, plan.video_job_code, plan.release_code,
                                     COALESCE(release.current_manifest_revision, 0) AS release_revision,
                                     variant.revision_number AS variant_revision, variant.material_snapshot_ref, plan.created_at, plan.updated_at
                                  FROM functional_video_plans AS plan
                                  LEFT JOIN production_variant_revisions AS variant
                                    ON variant.variant_code = plan.variant_code AND variant.status = 'confirmed'
                                  LEFT JOIN releases AS release ON release.release_code = plan.release_code
                                  ORDER BY plan.plan_code""",
            "releases": "SELECT release_code, subject_type, subject_code, subject_revision, carrier_kind, status, current_manifest_revision, release_fingerprint, created_at, updated_at FROM releases ORDER BY release_code",
            "operation_sessions": "SELECT session_code, title, platform, content_project_code, started_at, ended_at, source_kind, import_version, live_room_plan_code, variant_code, release_code, metrics, created_at, updated_at FROM functional_operation_sessions ORDER BY session_code",
            "content_exposures": """SELECT exposure.exposure_code, exposure.session_code, session.import_version AS session_import_version,
                                            exposure.plan_code, exposure.variant_code, exposure.release_code, exposure.scene_code,
                                            exposure.started_at, exposure.ended_at, exposure.source_kind, exposure.confidence,
                                            exposure.status, exposure.created_at,
                                            CASE WHEN live.plan_code IS NOT NULL THEN 'live_room_plan'
                                                 WHEN video.plan_code IS NOT NULL THEN 'rendered_video_plan' END AS plan_node_type,
                                            COALESCE(live.plan_code, video.plan_code) AS plan_node_code
                                     FROM functional_content_exposures AS exposure
                                     JOIN functional_operation_sessions AS session ON session.id = exposure.session_id
                                     LEFT JOIN functional_live_room_plans AS live ON live.plan_code = exposure.plan_code
                                     LEFT JOIN functional_video_plans AS video ON video.plan_code = exposure.plan_code
                                     WHERE exposure.status = 'active'
                                     ORDER BY exposure.exposure_code""",
            "metric_definitions": "SELECT metric_code, revision_number, status, name, unit, value_type, aggregation, fingerprint_sha256 FROM metric_definition_revisions ORDER BY metric_code, revision_number",
            "session_metric_snapshots": """SELECT snapshot.snapshot_code, snapshot.session_code, session.import_version AS session_import_version,
                                               snapshot.metric_key, snapshot.metric_code, snapshot.metric_revision, snapshot.aggregation,
                                               snapshot.status, snapshot.source_event_count, snapshot.fingerprint_sha256
                                        FROM functional_session_metric_snapshots AS snapshot
                                        JOIN functional_operation_sessions AS session ON session.id = snapshot.session_id
                                        ORDER BY snapshot.snapshot_code""",
            "attribution_reports": """SELECT report_code, metric_key, evidence_level, status, session_codes,
                                               input_snapshot, fingerprint_sha256, supersedes_report_code, created_at
                                        FROM functional_attribution_reports
                                        ORDER BY report_code""",
        }
        rows: dict[str, list[dict[str, Any]]] = {}
        for key, query in queries.items():
            cur.execute(query)
            rows[key] = [dict(row) for row in cur.fetchall()]
        for report in rows["attribution_reports"]:
            input_snapshot = report.get("input_snapshot") or {}
            frozen_sessions = input_snapshot.get("sessions") if isinstance(input_snapshot, dict) else None
            report["session_refs"] = [
                {"session_code": str(item["session_code"]), "import_version": int(item["import_version"])}
                for item in (frozen_sessions or [])
                if isinstance(item, dict)
                and item.get("session_code")
                and isinstance(item.get("import_version"), int)
            ]
        return cls.materialize(rows)

    @staticmethod
    def _node_identity(node: GraphNodeInput) -> dict[str, object]:
        return {"type": node.node_type, "code": node.node_code, "revision": node.revision_number, "fingerprint": node.source_fingerprint}

    @staticmethod
    def _edge_identity(edge: GraphEdgeInput) -> dict[str, object]:
        return {"source": edge.source, "target": edge.target, "relationship_type": edge.relationship_type, "assertion_kind": edge.assertion_kind, "evidence": edge.evidence}

    @classmethod
    def _watermark(cls, nodes: list[GraphNodeInput], edges: list[GraphEdgeInput]) -> dict[str, object]:
        return {
            "ontology_version": ONTOLOGY_VERSION,
            "source_fingerprint": canonical_fingerprint({"nodes": [cls._node_identity(node) for node in nodes], "edges": [cls._edge_identity(edge) for edge in edges]}),
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

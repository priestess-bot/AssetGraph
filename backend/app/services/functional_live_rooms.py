from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainValidationError
from app.repositories.content_production import ContentProductionRepository
from app.repositories.material_library import MaterialLibraryRepository, MaterialLibraryValidationError
from app.repositories.maitu import MaituMaterialSlotRepository
from app.repositories.releases import ReleaseRepository
from app.services.functional_content import FunctionalContentService
from app.services.releases import ReleaseService
from app.services.script_layout_build_plan_builder import ScriptLayoutBuildPlanBuilder


class FunctionalLiveRoomService:
    """Builds a reviewable Maitu draft plan without exposing a go-live action."""

    def __init__(
        self,
        connection: Connection,
        *,
        release_signing_key: bytes | None = None,
        release_signing_key_id: str | None = None,
    ):
        self.connection = connection
        self.content = FunctionalContentService(connection)
        self.production = ContentProductionRepository(connection)
        self.materials = MaterialLibraryRepository(connection)
        self.maitu = MaituMaterialSlotRepository(connection)
        self._release_signing_key = release_signing_key
        self._release_signing_key_id = release_signing_key_id

    def create_plan(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        detail = self.content.get_detail(payload["project_code"])
        if detail is None:
            raise KeyError(payload["project_code"])
        if not detail["generated"]:
            raise DomainValidationError("LIVE_ROOM_SHOT_LIST_REQUIRED", "Generate the ContentProject before planning a live room")
        try:
            material_pack_refs, material_pack_asset_codes = self.materials.resolve_published_packs(
                payload.get("material_pack_codes") or []
            )
        except MaterialLibraryValidationError as exc:
            raise DomainValidationError("LIVE_ROOM_MATERIAL_PACK_INVALID", str(exc)) from exc
        try:
            asset_gap_refs = self.materials.resolve_gap_refs(payload.get("asset_gap_codes") or [])
        except MaterialLibraryValidationError as exc:
            raise DomainValidationError("LIVE_ROOM_ASSET_GAP_INVALID", str(exc)) from exc
        selected_assets = self._selected_assets(
            [*(payload.get("asset_codes") or []), *material_pack_asset_codes],
            payload.get("group_codes") or [],
        )
        if not selected_assets:
            raise DomainValidationError("LIVE_ROOM_ASSETS_REQUIRED", "Select at least one asset or group before planning")
        material_role_overrides = self._validate_material_role_overrides(
            payload.get("material_role_overrides") or {}, selected_assets
        )
        room_constraint_overrides = self._validate_room_constraint_overrides(
            payload.get("room_constraint_overrides") or {}, selected_assets, actor_id=actor_id
        )
        payload = {
            **payload,
            "material_role_overrides": material_role_overrides,
            "room_constraint_overrides": room_constraint_overrides,
        }
        selection_sources = self._material_selection_sources(
            asset_codes=payload.get("asset_codes") or [],
            group_codes=payload.get("group_codes") or [],
            material_pack_refs=material_pack_refs,
        )
        story = detail["story_brief"]
        script = detail["script"]
        shot_list = detail["shot_list"]
        if story is None or script is None or shot_list is None:
            raise DomainValidationError("LIVE_ROOM_CONTENT_CHAIN_INVALID", "ContentProject chain is incomplete")
        snapshot = {
            "asset_codes": [asset["asset_code"] for asset in selected_assets],
            "assets": [
                {
                    "asset_code": asset["asset_code"], "media_kind": asset["media_kind"],
                    "material_roles": asset["material_roles"], "execution_capability": asset["execution_capability"],
                    "constraint_profile_ref": asset["constraint_profile_ref"],
                    "selection_sources": selection_sources.get(asset["asset_code"], []),
                }
                for asset in selected_assets
            ],
            "material_pack_refs": material_pack_refs,
            "asset_gap_refs": asset_gap_refs,
            "material_role_overrides": material_role_overrides,
            "room_constraint_overrides": room_constraint_overrides,
        }
        templates = self._project_template_selection(detail, payload)
        variant = self.production.create_production_variant(
            project_code=detail["project_code"],
            project_revision=int(detail["revision_number"]),
            story_brief_code=story["story_brief_code"],
            story_brief_revision=int(story["revision_number"]),
            script_revision_code=script["script_revision_code"],
            shot_list_revision_code=shot_list["shot_list_revision_code"],
            carrier_kind="live_room",
            branch_target={"live_room_id": payload["target_live_room_id"], "expected_title": payload["expected_title"]},
            configuration={
                "templates": templates,
                "selected_asset_codes": snapshot["asset_codes"],
                "selected_material_pack_codes": payload.get("material_pack_codes") or [],
                "selected_asset_gap_codes": payload.get("asset_gap_codes") or [],
                "material_role_overrides": material_role_overrides,
                "room_constraint_overrides": room_constraint_overrides,
            },
            material_snapshot_ref=snapshot,
            constraint_snapshot_ref={
                "schema_version": "functional-asset-constraint-profiles.v1",
                "asset_profiles": [
                    {
                        "asset_code": asset["asset_code"],
                        "profile": asset["constraint_profile_ref"],
                    }
                    for asset in selected_assets
                ],
                "room_constraint_overrides": room_constraint_overrides,
            },
            actor_id=actor_id,
            producer_strategy_revision="functional-live-room.v1",
        )
        variant = self.production.confirm_production_variant_revision(
            variant["variant_code"], revision_number=int(variant["revision_number"]), actor_id=actor_id
        )
        configuration = self.production.create_live_room_configuration_revision(
            variant_code=variant["variant_code"],
            variant_revision=int(variant["revision_number"]),
            expected_revision=0,
            target_live_room_id=payload["target_live_room_id"],
            expected_title=payload["expected_title"],
            # This fast-track surface compiles and queues a plan only. A later
            # Maitu worker integration may create an explicit auto_write_draft
            # revision after its own empty-draft preflight succeeds.
            build_mode="plan_only",
            inventory_snapshot_ref=snapshot,
            site_protection_policy={"requires_empty_draft": True, "go_live_disabled": True},
            configuration={
                "templates": templates,
                "selected_asset_codes": snapshot["asset_codes"],
                "selected_group_codes": payload.get("group_codes") or [],
                "selected_material_pack_codes": payload.get("material_pack_codes") or [],
                "selected_asset_gap_codes": payload.get("asset_gap_codes") or [],
                "material_role_overrides": material_role_overrides,
                "room_constraint_overrides": room_constraint_overrides,
            },
            actor_id=actor_id,
        )
        configuration = self.production.confirm_live_room_configuration_revision(
            configuration["configuration_code"], revision_number=int(configuration["revision_number"]), actor_id=actor_id
        )
        blueprint, _, blocked_reasons = self._compile(
            detail,
            selected_assets,
            payload,
            variant_code=variant["variant_code"],
        )
        blocked_reasons = list(
            dict.fromkeys(
                [
                    *blocked_reasons,
                    *[
                        f"asset_gap_unresolved:{gap['gap_code']}:{gap['status']}"
                        for gap in asset_gap_refs
                        if gap["status"] in {"open", "candidate_found"}
                    ],
                ]
            )
        )
        blueprint["scenes"] = self.production.create_maitu_scene_blueprint_projections(
            variant_code=variant["variant_code"],
            variant_revision=int(variant["revision_number"]),
            configuration_code=configuration["configuration_code"],
            configuration_revision=int(configuration["revision_number"]),
            scenes=blueprint["scenes"],
            actor_id=actor_id,
            producer_strategy_revision="functional-live-room.v1",
        )
        build_plan = self._persist_build_plan(
            detail=detail,
            variant=variant,
            configuration=configuration,
            inventory_snapshot=snapshot,
            blueprint=blueprint,
            blocked_reasons=blocked_reasons,
        )
        gate_results, quality_report = self._evaluate_plan(
            detail=detail,
            snapshot=snapshot,
            blueprint=blueprint,
            build_plan=build_plan,
            compiler_blocked_reasons=blocked_reasons,
        )
        gate_blocked_reasons = [str(gate["rule_code"]) for gate in gate_results if gate["status"] == "blocked"]
        plan_blocked_reasons = list(dict.fromkeys([*blocked_reasons, *(build_plan.get("blocked_reasons") or []), *gate_blocked_reasons]))
        status = "blocked" if plan_blocked_reasons or not build_plan.get("can_execute") else "ready"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code = self._next_code(cursor, "LIVEPLAN", "functional_live_room_plan")
            cursor.execute(
                """
                INSERT INTO functional_live_room_plans (
                    plan_code, project_code, variant_code, configuration_code,
                    target_live_room_id, expected_title, primary_template_code,
                    secondary_template_codes, selected_asset_codes, selected_group_codes, selected_material_pack_codes,
                    blueprint, build_plan, gate_results, quality_report, status, blocked_reasons
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    code, detail["project_code"], variant["variant_code"], configuration["configuration_code"],
                    payload["target_live_room_id"], payload["expected_title"], templates["primary_template_code"],
                    Jsonb(templates["secondary_template_codes"]), Jsonb(snapshot["asset_codes"]),
                    Jsonb(payload.get("group_codes") or []), Jsonb(payload.get("material_pack_codes") or []), Jsonb(blueprint), Jsonb(build_plan),
                    Jsonb(gate_results), Jsonb(quality_report), status, Jsonb(plan_blocked_reasons),
                ),
            )
            row = cursor.fetchone()
        self._persist_operation_trace_links(
            plan_id=row["id"],
            build_plan_code=str(build_plan["build_plan_code"]),
            blueprint=blueprint,
        )
        self.connection.commit()
        return self._with_release(self._serialize(row))

    def list_plans(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_live_room_plans ORDER BY updated_at DESC, plan_code")
            rows = cursor.fetchall()
        return [self._with_release(self._serialize(row)) for row in rows]

    def get_plan(self, plan_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_live_room_plans WHERE plan_code = %s", (plan_code,))
            row = cursor.fetchone()
        return self._with_release(self._serialize(row)) if row else None

    def confirm_execution(self, plan_code: str, *, confirmed: bool) -> dict[str, Any] | None:
        if not confirmed:
            raise DomainValidationError("LIVE_ROOM_EXECUTION_CONFIRMATION_REQUIRED", "Explicit confirmation is required before requesting draft execution")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_live_room_plans WHERE plan_code = %s FOR UPDATE", (plan_code,))
            plan = cursor.fetchone()
            if plan is None:
                self.connection.rollback()
                return None
            if plan["status"] == "blocked":
                cursor.execute(
                    """UPDATE functional_live_room_plans
                       SET execution_status = 'blocked', execution_evidence = %s, updated_at = now()
                       WHERE id = %s RETURNING *""",
                    (Jsonb({"reason": "build_plan_blocked", "blocked_reasons": plan["blocked_reasons"]}), plan["id"]),
                )
            else:
                cursor.execute(
                    """UPDATE functional_live_room_plans
                       SET execution_status = 'requested', execution_evidence = %s, updated_at = now()
                       WHERE id = %s RETURNING *""",
                    (
                        Jsonb(
                            {
                                "status": "awaiting_maitu_worker",
                                "message": "No platform mutation has been performed. A configured Maitu worker must preflight the empty draft before writing.",
                            }
                        ),
                        plan["id"],
                    ),
                )
            row = cursor.fetchone()
        self.connection.commit()
        return self._with_release(self._serialize(row))

    def create_release_candidate(self, plan_code: str, *, actor_id: str) -> dict[str, Any]:
        """Freeze a reviewable live-room draft candidate without delivery.

        The candidate intentionally records pending rights, authorization and
        authoritative readback as blocking release gates.  It is therefore a
        durable review object only, never an implicit approval or write action.
        """
        plan = self._releaseable_plan(plan_code)
        if plan is None:
            raise KeyError(plan_code)
        if plan["status"] != "ready":
            raise DomainValidationError(
                "LIVE_ROOM_RELEASE_PLAN_BLOCKED",
                "Only a ready live-room plan can create a release candidate",
                details={"plan_code": plan_code, "blocked_reasons": plan["blocked_reasons"]},
            )
        if plan["release_code"]:
            existing = self.get_plan(plan_code)
            if existing is None:
                raise KeyError(plan_code)
            return existing

        subject_refs = self._release_subject_refs(plan)
        snapshot_artifact = self._get_or_create_release_snapshot(plan, subject_refs)
        release = self._release_service().create_candidate(
            subject_type="production_variant",
            subject_code=str(plan["variant_code"]),
            subject_revision=int(plan["variant_revision"]),
            carrier_kind="live_room_draft",
            subject_refs=subject_refs,
            artifact_refs=[
                {
                    "artifact_code": snapshot_artifact["artifact_code"],
                    "checksum_sha256": snapshot_artifact["checksum_sha256"],
                    "role": "live_room_build_plan_snapshot",
                }
            ],
            rights_snapshot={
                "status": "pending_evidence",
                "asset_codes": list(plan["selected_asset_codes"] or []),
                "template_refs": self._template_refs(plan),
                "reason": "Asset rights and platform authorization evidence have not been collected.",
            },
            quality_snapshot={
                "schema_version": "functional-live-room-release-quality.v1",
                "gates": self._release_quality_gates(plan),
                "static_gate_results": plan["gate_results"],
                "quality_report": plan["quality_report"],
            },
            lineage_snapshot={
                "complete": True,
                "schema_version": "functional-live-room-lineage.v1",
                "edge_count": self._release_lineage_edge_count(plan),
                "coverage": {
                    "content_chain": "fixed",
                    "scene_and_layer_projection": "fixed",
                    "build_plan": "fixed",
                    "execution_readback": "pending",
                },
            },
            carrier_facet={
                "build_plan_ref": {
                    "code": plan["build_plan"].get("build_plan_code"),
                    "revision": 1,
                    "fingerprint": canonical_fingerprint(plan["build_plan"]),
                    "snapshot_artifact_code": snapshot_artifact["artifact_code"],
                },
                "live_room_configuration_ref": {
                    "code": plan["configuration_code"],
                    "revision": int(plan["configuration_revision"]),
                    "target_live_room_id": plan["target_live_room_id"],
                },
                "maitu_scene_blueprint_refs": [
                    {"code": scene.get("scene_blueprint_code") or scene.get("scene_code"), "revision": 1}
                    for scene in plan["blueprint"].get("scenes") or []
                ],
                "execution": {
                    "status": "not_authorized",
                    "ready_for_go_live": False,
                    "readback_evidence": "pending",
                },
            },
            created_by=actor_id,
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE functional_live_room_plans
                SET release_code = %s,
                    release_snapshot_artifact_code = %s,
                    release_manifest_fingerprint = %s,
                    updated_at = now()
                WHERE id = %s AND release_code IS NULL
                RETURNING *
                """,
                (
                    release["release_code"],
                    snapshot_artifact["artifact_code"],
                    release["manifest"]["manifest_fingerprint"],
                    plan["id"],
                ),
            )
            updated = cursor.fetchone()
            if updated is None:
                cursor.execute(
                    "SELECT * FROM functional_live_room_plans WHERE id = %s", (plan["id"],))
                updated = cursor.fetchone()
        self.connection.commit()
        return self._with_release(self._serialize(updated))

    def clone_plan(self, plan_code: str, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        """Recompile business inputs into a different target room.

        Clone is intentionally not a room-copy operation. It never carries a
        source room fingerprint, authorization, execution evidence, release or
        delivery state into the target plan.
        """
        source = self._releaseable_plan(plan_code)
        if source is None:
            raise KeyError(plan_code)
        target_live_room_id = str(payload["target_live_room_id"]).strip()
        expected_title = str(payload["expected_title"]).strip()
        if target_live_room_id == str(source["target_live_room_id"]):
            raise DomainValidationError(
                "LIVE_ROOM_CLONE_TARGET_MUST_DIFFER",
                "A cloned plan must target a different empty draft room",
                details={"source_plan_code": plan_code},
            )
        current_project = self.content.get_detail(str(source["project_code"]))
        if current_project is None:
            raise KeyError(source["project_code"])
        if int(current_project["revision_number"]) != int(source["project_revision"]):
            raise DomainValidationError(
                "LIVE_ROOM_CLONE_SOURCE_STALE",
                "The source plan is bound to an older ContentProject revision; create a new plan from the current content instead",
                details={
                    "source_plan_code": plan_code,
                    "source_project_revision": source["project_revision"],
                    "current_project_revision": current_project["revision_number"],
                },
            )
        cloned = self.create_plan(
            {
                "project_code": source["project_code"],
                "target_live_room_id": target_live_room_id,
                "expected_title": expected_title,
                "primary_template_code": source["primary_template_code"],
                "secondary_template_codes": list(source["secondary_template_codes"] or []),
                "asset_codes": list(source["selected_asset_codes"] or []),
                "group_codes": list(source["selected_group_codes"] or []),
                "material_pack_codes": list(source["selected_material_pack_codes"] or []),
                "asset_gap_codes": [
                    str(gap["gap_code"])
                    for gap in source["build_plan"].get("inventory_snapshot", {}).get("asset_gap_refs", [])
                    if isinstance(gap, dict) and gap.get("gap_code")
                ],
                "material_role_overrides": dict((source["quality_report"] or {}).get("material_role_overrides") or {}),
                "room_constraint_overrides": dict(
                    (source["build_plan"] or {}).get("inventory_snapshot", {}).get("room_constraint_overrides") or {}
                ),
            },
            actor_id=actor_id,
        )
        clone_context = {
            "schema_version": "functional-live-room-clone.v1",
            "source_plan_code": plan_code,
            "source_project_revision": int(source["project_revision"]),
            "copied_business_inputs": [
                "content_project_revision",
                "pinned_template_revisions",
                "selected_asset_codes",
                "selected_group_codes",
                "selected_material_pack_codes",
                "selected_asset_gap_codes",
                "material_role_overrides",
                "room_constraint_overrides",
            ],
            "cleared_target_state": [
                "target_live_room_fingerprint",
                "authorization",
                "execution_status",
                "execution_evidence",
                "release",
                "delivery",
                "readback",
            ],
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE functional_live_room_plans
                SET cloned_from_plan_code = %s, clone_context = %s, updated_at = now()
                WHERE plan_code = %s
                RETURNING *
                """,
                (plan_code, Jsonb(clone_context), cloned["plan_code"]),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._with_release(self._serialize(row))

    def get_trace(self, plan_code: str) -> dict[str, Any]:
        """Return an explicit operation-to-content provenance projection."""
        plan = self._releaseable_plan(plan_code)
        if plan is None:
            raise KeyError(plan_code)
        self._ensure_operation_trace_links(plan)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT link.build_plan_operation_id, operation.operation_type,
                       operation.operation_name, operation.sort_order,
                       operation.scene_name, operation.layer_name,
                       operation.selected_asset_code, link.target_type,
                       link.target_code, link.target_revision, link.relation_type,
                       scene.scene_blueprint_code, scene.shot_id AS scene_shot_id,
                       layer.layer_blueprint_code, layer.source_shot_id AS layer_shot_id,
                       shot.id AS shot_id, shot.shot_code, shot.shot_goal,
                       segment.segment_code, segment.semantic_goal AS program_segment_goal
                FROM functional_live_room_operation_trace_links AS link
                JOIN maitu_live_room_build_plan_operations AS operation
                  ON operation.id = link.build_plan_operation_id
                LEFT JOIN maitu_scene_blueprints AS scene
                  ON link.target_type = 'maitu_scene_blueprint'
                 AND scene.scene_blueprint_code = link.target_code
                 AND scene.revision_number = link.target_revision
                LEFT JOIN layer_blueprints AS layer
                  ON link.target_type = 'layer_blueprint'
                 AND layer.layer_blueprint_code = link.target_code
                 AND layer.revision_number = link.target_revision
                LEFT JOIN shots AS shot ON shot.id = COALESCE(scene.shot_id, layer.source_shot_id)
                LEFT JOIN program_segments AS segment ON segment.id = shot.program_segment_id
                WHERE link.plan_id = %s
                ORDER BY operation.sort_order, operation.id, link.target_type, link.target_code
                """,
                (plan["id"],),
            )
            rows = cursor.fetchall()

            shot_ids = list(
                dict.fromkeys(row["shot_id"] for row in rows if row["shot_id"] is not None)
            )
            blocks_by_shot: dict[str, list[dict[str, Any]]] = {}
            if shot_ids:
                cursor.execute(
                    """
                    SELECT source.shot_id, block.block_code, block.content,
                           block.fact_citations, block.template_sources, source.relation_type
                    FROM shot_script_block_sources AS source
                    JOIN content_script_blocks AS block ON block.id = source.script_block_id
                    WHERE source.shot_id = ANY(%s)
                    ORDER BY source.shot_id, source.source_order, block.block_code
                    """,
                    (shot_ids,),
                )
                for block in cursor.fetchall():
                    blocks_by_shot.setdefault(str(block["shot_id"]), []).append(
                        {
                            "block_code": block["block_code"],
                            "content": block["content"],
                            "relation_type": block["relation_type"],
                            "fact_citations": block["fact_citations"],
                            "template_sources": block["template_sources"],
                        }
                    )

        operations: list[dict[str, Any]] = []
        by_operation: dict[str, dict[str, Any]] = {}
        for row in rows:
            operation_id = str(row["build_plan_operation_id"])
            operation = by_operation.get(operation_id)
            if operation is None:
                operation = {
                    "operation_id": operation_id,
                    "operation_type": row["operation_type"],
                    "operation_name": row["operation_name"],
                    "sort_order": row["sort_order"],
                    "scene_name": row["scene_name"],
                    "layer_name": row["layer_name"],
                    "asset_code": row["selected_asset_code"],
                    "targets": [],
                }
                by_operation[operation_id] = operation
                operations.append(operation)
            shot_id = row["shot_id"]
            operation["targets"].append(
                {
                    "target_type": row["target_type"],
                    "target_code": row["target_code"],
                    "target_revision": row["target_revision"],
                    "relation_type": row["relation_type"],
                    "shot": (
                        {
                            "shot_code": row["shot_code"],
                            "shot_goal": row["shot_goal"],
                        }
                        if row["shot_code"]
                        else None
                    ),
                    "program_segment": (
                        {
                            "segment_code": row["segment_code"],
                            "semantic_goal": row["program_segment_goal"],
                        }
                        if row["segment_code"]
                        else None
                    ),
                    "script_blocks": blocks_by_shot.get(str(shot_id), []) if shot_id is not None else [],
                }
            )
        return {
            "plan_code": plan_code,
            "content_chain": {
                "content_project_revision": {
                    "code": plan["source_project_code"],
                    "revision": int(plan["project_revision"]),
                },
                "story_brief_revision": {
                    "code": plan["story_brief_code"],
                    "revision": int(plan["story_brief_revision"]),
                    "fact_revision_refs": plan["fact_revision_refs"],
                    "template_revision_refs": plan["template_revision_refs"],
                },
                "script_revision": {
                    "code": plan["script_revision_code"],
                    "revision": int(plan["script_revision"]),
                },
                "program_revision": {
                    "code": plan["program_revision_code"],
                    "revision": int(plan["program_revision"]),
                },
                "shot_list_revision": {
                    "code": plan["shot_list_revision_code"],
                    "revision": int(plan["shot_list_revision"]),
                },
            },
            "operations": operations,
        }

    def _ensure_operation_trace_links(self, plan: dict[str, Any]) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM functional_live_room_operation_trace_links WHERE plan_id = %s",
                (plan["id"],),
            )
            existing_count = int(cursor.fetchone()[0])
        if existing_count:
            return
        self._persist_operation_trace_links(
            plan_id=plan["id"],
            build_plan_code=str(plan["build_plan"]["build_plan_code"]),
            blueprint=plan["blueprint"],
        )
        self.connection.commit()

    def _persist_operation_trace_links(
        self,
        *,
        plan_id: Any,
        build_plan_code: str,
        blueprint: dict[str, Any],
    ) -> None:
        scenes = [scene for scene in blueprint.get("scenes") or [] if isinstance(scene, dict)]
        scenes_by_code = {
            str(scene.get("scene_code") or scene.get("scene_blueprint_code")): scene
            for scene in scenes
            if scene.get("scene_code") or scene.get("scene_blueprint_code")
        }
        layers_by_code = {
            str(layer.get("layer_blueprint_code")): layer
            for scene in scenes
            for layer in scene.get("layers") or []
            if isinstance(layer, dict) and layer.get("layer_blueprint_code")
        }
        if not scenes_by_code:
            raise DomainValidationError(
                "LIVE_ROOM_TRACE_SCENES_REQUIRED",
                "Cannot persist operation trace links without generated MaituSceneBlueprints",
            )
        relation_by_operation = {
            "preflight_content_build_plan": "preflights",
            "fill_default_scene": "configures",
            "create_scene": "configures",
            "insert_asset_layer": "mutates",
            "position_asset_layer": "mutates",
            "write_script": "writes",
            "verify_scene": "verifies",
            "save_draft": "saves",
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, operation_type, scene_name, layer_name
                FROM maitu_live_room_build_plan_operations
                WHERE build_plan_code = %s
                ORDER BY sort_order, id
                """,
                (build_plan_code,),
            )
            operations = cursor.fetchall()
            for operation in operations:
                operation_type = str(operation["operation_type"])
                relation_type = relation_by_operation.get(operation_type)
                if relation_type is None:
                    raise DomainValidationError(
                        "LIVE_ROOM_TRACE_OPERATION_UNKNOWN",
                        "BuildPlan operation cannot be traced to an allowed target",
                        details={"operation_type": operation_type, "build_plan_code": build_plan_code},
                    )
                targets: list[tuple[str, str]] = []
                layer_code = str(operation["layer_name"] or "")
                scene_code = str(operation["scene_name"] or "")
                if layer_code and layer_code in layers_by_code:
                    targets.append(("layer_blueprint", layer_code))
                elif scene_code and scene_code in scenes_by_code:
                    targets.append(("maitu_scene_blueprint", scene_code))
                elif operation_type in {"preflight_content_build_plan", "save_draft"}:
                    targets.extend(("maitu_scene_blueprint", code) for code in scenes_by_code)
                else:
                    raise DomainValidationError(
                        "LIVE_ROOM_TRACE_TARGET_MISSING",
                        "BuildPlan operation does not reference a generated Scene or LayerBlueprint",
                        details={
                            "operation_type": operation_type,
                            "scene_name": operation["scene_name"],
                            "layer_name": operation["layer_name"],
                        },
                    )
                for target_type, target_code in targets:
                    cursor.execute(
                        """
                        INSERT INTO functional_live_room_operation_trace_links (
                            plan_id, build_plan_operation_id, target_type, target_code,
                            target_revision, relation_type, evidence
                        ) VALUES (%s, %s, %s, %s, 1, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            plan_id,
                            operation["id"],
                            target_type,
                            target_code,
                            relation_type,
                            Jsonb(
                                {
                                    "schema_version": "functional-live-room-operation-trace.v1",
                                    "build_plan_code": build_plan_code,
                                    "operation_type": operation_type,
                                }
                            ),
                        ),
                    )

    def _releaseable_plan(self, plan_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT plan.*, variant.revision_number AS variant_revision,
                       configuration.revision_number AS configuration_revision,
                       project.project_code AS source_project_code,
                       project_revision.revision_number AS project_revision,
                       story.story_brief_code AS story_brief_code,
                       story.revision_number AS story_brief_revision,
                       story.fact_revision_refs, story.template_revision_refs,
                       script.script_revision_code AS script_revision_code,
                       script.revision_number AS script_revision,
                       program.program_revision_code AS program_revision_code,
                       program.revision_number AS program_revision,
                       shot_list.shot_list_revision_code AS shot_list_revision_code,
                       shot_list.revision_number AS shot_list_revision
                FROM functional_live_room_plans AS plan
                JOIN production_variant_revisions AS variant
                  ON variant.variant_code = plan.variant_code
                 AND variant.revision_number = (plan.build_plan->'production_variant'->>'revision')::integer
                JOIN content_project_revisions AS project_revision
                  ON project_revision.id = variant.source_project_revision_id
                JOIN content_projects AS project ON project.id = project_revision.project_id
                JOIN story_brief_revisions AS story ON story.id = variant.source_story_brief_revision_id
                JOIN content_script_revisions AS script ON script.id = variant.source_script_revision_id
                JOIN shot_list_revisions AS shot_list ON shot_list.id = variant.source_shot_list_revision_id
                JOIN content_program_revisions AS program ON program.id = shot_list.source_program_revision_id
                JOIN live_room_configuration_revisions AS configuration
                  ON configuration.configuration_code = plan.configuration_code
                 AND configuration.revision_number = (plan.build_plan->'live_room_configuration'->>'revision')::integer
                WHERE plan.plan_code = %s
                """,
                (plan_code,),
            )
            return cursor.fetchone()

    @staticmethod
    def _release_subject_refs(plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "content_project_revision": {
                "code": plan["source_project_code"],
                "revision": int(plan["project_revision"]),
            },
            "production_variant_revision": {
                "code": plan["variant_code"],
                "revision": int(plan["variant_revision"]),
            },
            "story_brief_revision": {
                "code": plan["story_brief_code"],
                "revision": int(plan["story_brief_revision"]),
            },
            "script_revision": {
                "code": plan["script_revision_code"],
                "revision": int(plan["script_revision"]),
            },
            "program_revision": {
                "code": plan["program_revision_code"],
                "revision": int(plan["program_revision"]),
            },
            "shot_list_revision": {
                "code": plan["shot_list_revision_code"],
                "revision": int(plan["shot_list_revision"]),
            },
        }

    def _get_or_create_release_snapshot(
        self,
        plan: dict[str, Any],
        subject_refs: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT artifact.artifact_code, artifact.checksum_sha256, artifact.byte_size
                FROM functional_live_room_plan_release_snapshots AS snapshot
                JOIN artifact_refs AS artifact ON artifact.id = snapshot.artifact_id
                WHERE snapshot.plan_id = %s
                """,
                (plan["id"],),
            )
            existing = cursor.fetchone()
            if existing is not None:
                return existing

            snapshot = {
                "schema_version": "functional-live-room-release-snapshot.v1",
                "plan": {
                    "plan_code": plan["plan_code"],
                    "status": plan["status"],
                    "target_live_room_id": plan["target_live_room_id"],
                    "expected_title": plan["expected_title"],
                },
                "subject_refs": subject_refs,
                "selected_assets": list(plan["selected_asset_codes"] or []),
                "selected_groups": list(plan["selected_group_codes"] or []),
                "selected_material_packs": list(plan["selected_material_pack_codes"] or []),
                "material_pack_refs": plan["build_plan"].get("inventory_snapshot", {}).get("material_pack_refs", []),
                "asset_gap_refs": plan["build_plan"].get("inventory_snapshot", {}).get("asset_gap_refs", []),
                "blueprint": plan["blueprint"],
                "build_plan": plan["build_plan"],
                "static_gate_results": plan["gate_results"],
                "quality_report": plan["quality_report"],
                "execution": {
                    "status": plan["execution_status"],
                    "evidence": plan["execution_evidence"],
                },
            }
            snapshot_bytes = canonical_json_bytes(snapshot)
            fingerprint = canonical_fingerprint(snapshot)
            cursor.execute(
                """
                SELECT * FROM artifact_refs
                WHERE checksum_sha256 = %s AND byte_size = %s AND media_type = 'application/json'
                  AND content_addressed = true
                """,
                (fingerprint, len(snapshot_bytes)),
            )
            artifact = cursor.fetchone()
            if artifact is None:
                artifact_code = self._next_code(cursor, "ART", "artifact_ref")
                cursor.execute(
                    """
                    INSERT INTO artifact_refs (
                        artifact_code, artifact_kind, media_type, schema_version,
                        storage_uri, checksum_sha256, byte_size, producer_type,
                        producer_code, producer_revision, sensitivity,
                        retention_policy_code, metadata
                    ) VALUES (%s, 'live_room_build_plan_snapshot', 'application/json',
                              'functional-live-room-release-snapshot.v1', %s, %s, %s,
                              'functional_live_room_plan', %s, 1, 'internal',
                              'release-candidate', %s)
                    RETURNING *
                    """,
                    (
                        artifact_code,
                        f"assetgraph://functional-live-room-release-snapshots/{fingerprint}",
                        fingerprint,
                        len(snapshot_bytes),
                        plan["plan_code"],
                        Jsonb(
                            {
                                "plan_code": plan["plan_code"],
                                "snapshot_fingerprint": fingerprint,
                                "storage_backend": "postgresql",
                            }
                        ),
                    ),
                )
                artifact = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO functional_live_room_plan_release_snapshots (
                    plan_id, artifact_id, artifact_code, snapshot_fingerprint_sha256, snapshot
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING artifact_code, snapshot_fingerprint_sha256
                """,
                (plan["id"], artifact["id"], artifact["artifact_code"], fingerprint, Jsonb(snapshot)),
            )
            cursor.fetchone()
        self.connection.commit()
        return {
            "artifact_code": artifact["artifact_code"],
            "checksum_sha256": artifact["checksum_sha256"],
            "byte_size": artifact["byte_size"],
        }

    @staticmethod
    def _template_refs(plan: dict[str, Any]) -> list[dict[str, Any]]:
        configuration = plan["build_plan"].get("live_room_configuration") or {}
        return [
            {
                "primary_template_code": plan["primary_template_code"],
                "secondary_template_codes": list(plan["secondary_template_codes"] or []),
                "configuration_revision": configuration.get("revision"),
            }
        ]

    @staticmethod
    def _release_quality_gates(plan: dict[str, Any]) -> list[dict[str, Any]]:
        gates: list[dict[str, Any]] = []
        for static_gate in plan["gate_results"] or []:
            status = str(static_gate.get("status") or "blocked")
            gate_name = str(static_gate.get("gate") or "unknown")
            gates.append(
                {
                    "code": str(static_gate.get("rule_code") or gate_name),
                    "status": status,
                    "blocking": status == "blocked" or gate_name == "evidence_completeness",
                }
            )
        gates.extend(
            [
                {"code": "GATE_RELEASE_RIGHTS_EVIDENCE_PENDING", "status": "pending", "blocking": True},
                {"code": "GATE_RELEASE_AUTHORIZATION_PENDING", "status": "pending", "blocking": True},
            ]
        )
        return gates

    @staticmethod
    def _release_lineage_edge_count(plan: dict[str, Any]) -> int:
        scenes = plan["blueprint"].get("scenes") or []
        layers = sum(len(scene.get("layers") or []) for scene in scenes if isinstance(scene, dict))
        return 6 + len(scenes) + layers

    def _release_service(self) -> ReleaseService:
        if self._release_signing_key is not None:
            key = self._release_signing_key
            key_id = self._release_signing_key_id or "functional-live-room-test-key"
        elif settings.manifest_signing_key is not None and settings.manifest_signing_key.get_secret_value().strip():
            key = settings.manifest_signing_key.get_secret_value().encode("utf-8")
            key_id = settings.manifest_signing_key_id
        elif settings.app_env == "local":
            # Local fast-track candidates remain signed and reproducible. A
            # deployed environment must configure its own signing key instead.
            key = b"assetgraph-local-functional-release-key-v1"
            key_id = "local-functional-release-key-v1"
        else:
            raise DomainValidationError(
                "RELEASE_SIGNING_KEY_MISSING",
                "A release signing key is required outside the local environment",
            )
        return ReleaseService(ReleaseRepository(self.connection), signing_key=key, signing_key_id=key_id)

    def _with_release(self, plan: dict[str, Any]) -> dict[str, Any]:
        release_code = plan.get("release_code")
        if not release_code:
            plan["release"] = None
            return plan
        release = ReleaseRepository(self.connection).get_release(str(release_code))
        if release is None:
            plan["release"] = None
            return plan
        manifest = release["manifest"]
        plan["release"] = {
            "release_code": release["release_code"],
            "status": release["status"],
            "manifest_code": manifest["manifest_code"],
            "manifest_fingerprint": manifest["manifest_fingerprint"],
            "snapshot_artifact_code": plan.get("release_snapshot_artifact_code") or "",
        }
        return plan

    def _selected_assets(self, asset_codes: list[str], group_codes: list[str]) -> list[dict[str, Any]]:
        codes = list(dict.fromkeys([*asset_codes]))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            if group_codes:
                cursor.execute(
                    """SELECT DISTINCT a.asset_code FROM asset_group_members gm
                       JOIN asset_groups g ON g.id = gm.group_id
                       JOIN assets a ON a.id = gm.asset_id AND a.deleted_at IS NULL
                       WHERE g.group_code = ANY(%s)""",
                    (group_codes,),
                )
                codes.extend(row["asset_code"] for row in cursor.fetchall())
            codes = list(dict.fromkeys(codes))
            if not codes:
                return []
            cursor.execute(
                """
                SELECT asset.asset_code, COALESCE(asset.title, asset.original_filename) AS title,
                       asset.media_kind, asset.material_roles, asset.execution_capability,
                       profile.profile_code, revision.revision_number AS constraint_profile_revision,
                       revision.constraints AS constraint_profile_constraints,
                       revision.fingerprint_sha256 AS constraint_profile_fingerprint
                FROM assets AS asset
                LEFT JOIN asset_constraint_profiles AS profile ON profile.asset_id = asset.id
                LEFT JOIN asset_constraint_profile_revisions AS revision
                  ON revision.profile_id = profile.id AND revision.revision_number = profile.current_revision
                WHERE asset.asset_code = ANY(%s) AND asset.deleted_at IS NULL
                """,
                (codes,),
            )
            rows = cursor.fetchall()
        by_code = {
            row["asset_code"]: {
                **row,
                "constraint_profile_ref": (
                    {
                        "profile_code": row["profile_code"],
                        "revision": int(row["constraint_profile_revision"]),
                        "fingerprint": row["constraint_profile_fingerprint"],
                        "constraints": list(row["constraint_profile_constraints"] or []),
                    }
                    if row["profile_code"] is not None
                    else None
                ),
            }
            for row in rows
        }
        missing = [code for code in codes if code not in by_code]
        if missing:
            raise DomainValidationError("LIVE_ROOM_ASSET_NOT_FOUND", "Selected assets no longer exist", details={"asset_codes": missing})
        return [by_code[code] for code in codes]

    def _material_selection_sources(
        self,
        *,
        asset_codes: list[str],
        group_codes: list[str],
        material_pack_refs: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, str]]]:
        """Record the requested source without retaining dynamic group expansion."""
        sources: dict[str, list[dict[str, str]]] = {}

        def add(asset_code: str, kind: str, code: str) -> None:
            entry = {"kind": kind, "code": code}
            if entry not in sources.setdefault(asset_code, []):
                sources[asset_code].append(entry)

        for asset_code in dict.fromkeys(str(code).strip() for code in asset_codes if str(code).strip()):
            add(asset_code, "loose_asset", asset_code)
        for pack in material_pack_refs:
            pack_code = str(pack.get("pack_code") or "")
            for asset_code in pack.get("resolved_asset_codes") or []:
                add(str(asset_code), "material_pack", pack_code)
        codes = list(dict.fromkeys(str(code).strip() for code in group_codes if str(code).strip()))
        if not codes:
            return sources
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT g.group_code, a.asset_code
                   FROM asset_group_members gm
                   JOIN asset_groups g ON g.id = gm.group_id
                   JOIN assets a ON a.id = gm.asset_id AND a.deleted_at IS NULL
                   WHERE g.group_code = ANY(%s)""",
                (codes,),
            )
            for row in cursor.fetchall():
                add(str(row["asset_code"]), "asset_group", str(row["group_code"]))
        return sources

    @staticmethod
    def _project_template_selection(detail: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """Keep the live-room branch bound to the ContentProject's inputs.

        A downstream plan cannot silently swap a content template because the
        project confirmation is the point that freezes its published revision
        and contribution decision.  The optional request fields remain for
        compatibility, but may only repeat the already pinned selection.
        """
        content = detail.get("content") or {}
        primary_ref = content.get("primary_template_ref")
        secondary_refs = content.get("secondary_template_refs") or []
        primary_code = primary_ref.get("template_code") if isinstance(primary_ref, dict) else None
        secondary_codes = [
            str(ref["template_code"])
            for ref in secondary_refs
            if isinstance(ref, dict) and ref.get("template_code")
        ]
        requested_primary = str(payload.get("primary_template_code") or "").strip() or None
        requested_secondary = [str(code).strip() for code in payload.get("secondary_template_codes") or [] if str(code).strip()]
        if requested_primary is not None and requested_primary != primary_code:
            raise DomainValidationError(
                "LIVE_ROOM_TEMPLATE_SELECTION_MISMATCH",
                "Live-room plans must use the ContentProject primary template revision",
                details={"requested": requested_primary, "project_template": primary_code},
            )
        if requested_secondary and requested_secondary != secondary_codes:
            raise DomainValidationError(
                "LIVE_ROOM_TEMPLATE_SELECTION_MISMATCH",
                "Live-room plans must use the ContentProject secondary template revisions",
                details={"requested": requested_secondary, "project_templates": secondary_codes},
            )
        return {
            "primary_template_code": primary_code,
            "secondary_template_codes": secondary_codes,
            "primary_template_ref": primary_ref if isinstance(primary_ref, dict) else None,
            "secondary_template_refs": [ref for ref in secondary_refs if isinstance(ref, dict)],
        }

    def _persist_build_plan(
        self,
        *,
        detail: dict[str, Any],
        variant: dict[str, Any],
        configuration: dict[str, Any],
        inventory_snapshot: dict[str, Any],
        blueprint: dict[str, Any],
        blocked_reasons: list[str],
    ) -> dict[str, Any]:
        layout_scenes: list[dict[str, Any]] = []
        for scene_index, scene in enumerate(blueprint["scenes"]):
            layers = []
            for layer in scene["layers"]:
                geometry = layer.get("normalized_geometry") or {}
                layers.append(
                    {
                        "layer_id": layer["layer_blueprint_code"],
                        "layer_type": layer["material_role"],
                        "asset_code": layer["asset_code"],
                        "x": float(geometry.get("x", 0.0)) * 1080,
                        "y": float(geometry.get("y", 0.0)) * 1920,
                        "width": float(geometry.get("width", 1.0)) * 1080,
                        "height": float(geometry.get("height", 1.0)) * 1920,
                        "z_index": layer["z_order"],
                        "status": "ready",
                    }
                )
            layout_scenes.append(
                {
                    "scene_index": scene_index,
                    "scene_name": scene["scene_code"],
                    "layers": layers,
                    "script_block": {"text": scene.get("script") or ""},
                }
            )
        plan_inputs = {
            "schema_version": "maitu-build-plan.functional.v2",
            "content_project": {"project_code": detail["project_code"], "revision": detail["revision_number"]},
            "production_variant": {"variant_code": variant["variant_code"], "revision": variant["revision_number"]},
            "live_room_configuration": {"configuration_code": configuration["configuration_code"], "revision": configuration["revision_number"]},
            "inventory_snapshot": inventory_snapshot,
            "blueprint_fingerprint": canonical_fingerprint(blueprint),
            "policy_fingerprint": canonical_fingerprint({"requires_empty_draft": True, "go_live_disabled": True}),
        }
        layout_plan = {
            "status": "blocked_missing_required_assets" if blocked_reasons else "ready_for_build_plan",
            "build_mode": "plan_only",
            "can_generate_layout": not blocked_reasons,
            "can_generate_executable_build_plan": not blocked_reasons,
            "blocking_gap_count": len(blocked_reasons),
            "manual_review_required": bool(blocked_reasons),
            "scenes": layout_scenes,
        }
        build_plan = ScriptLayoutBuildPlanBuilder().build(
            layout_plan,
            target_live_room_id=configuration["target_live_room_id"],
        )
        build_plan.update(plan_inputs)
        build_plan["go_live"] = False
        persisted = self.maitu.create_script_layout_build_plan(
            build_plan,
            plan_name=f"{detail['title']} {configuration['expected_title']} BuildPlan",
        )
        return persisted

    @staticmethod
    def _evaluate_plan(
        *,
        detail: dict[str, Any],
        snapshot: dict[str, Any],
        blueprint: dict[str, Any],
        build_plan: dict[str, Any],
        compiler_blocked_reasons: list[str],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        scenes = blueprint.get("scenes") or []
        shots = detail.get("shot_list", {}).get("shots") or []
        target_duration_seconds = (detail.get("content") or {}).get("target_duration_seconds")
        total_duration_ms = sum(int(scene.get("estimated_active_end_ms") or 0) - int(scene.get("estimated_active_start_ms") or 0) for scene in scenes)
        deviation_ratio = None
        duration_warning = False
        if isinstance(target_duration_seconds, int) and target_duration_seconds > 0:
            deviation_ratio = abs(total_duration_ms - target_duration_seconds * 1000) / (target_duration_seconds * 1000)
            duration_warning = deviation_ratio > 0.5
        operations = build_plan.get("operations") or []
        allowed_operations = {
            "preflight_content_build_plan", "fill_default_scene", "create_scene",
            "insert_asset_layer", "position_asset_layer", "write_script", "verify_scene", "save_draft",
        }
        operation_types = {str(operation.get("operation_type") or "") for operation in operations if isinstance(operation, dict)}
        role_needs = sorted({str(role) for shot in shots for role in shot.get("material_role_requirements") or []})
        selected_roles = sorted({str(role) for asset in snapshot.get("assets") or [] for role in asset.get("material_roles") or []})
        missing_roles = sorted(set(role_needs) - set(selected_roles))
        gates = [
            {
                "gate": "identity_version",
                "status": "pass",
                "rule_code": "GATE_IDENTITY_VERSION_FIXED",
                "rule_version": "functional-live-room-gates.v1",
                "evidence": {"project_revision": detail["revision_number"], "shot_count": len(shots)},
                "remediation": None,
            },
            {
                "gate": "authorization_facts",
                "status": "pass",
                "rule_code": "GATE_CONTENT_INPUT_CONFIRMED",
                "rule_version": "functional-live-room-gates.v1",
                "evidence": {"content_project_status": detail["status"], "fact_card_count": len(detail.get("fact_cards") or [])},
                "remediation": None,
            },
            {
                "gate": "input_boundary",
                "status": "blocked" if compiler_blocked_reasons or missing_roles else "pass",
                "rule_code": "GATE_MATERIAL_WHITELIST_COMPLETE" if not (compiler_blocked_reasons or missing_roles) else "GATE_MATERIAL_WHITELIST_BLOCKED",
                "rule_version": "functional-live-room-gates.v1",
                "evidence": {"selected_asset_codes": snapshot.get("asset_codes") or [], "missing_roles": missing_roles, "compiler_blocked_reasons": compiler_blocked_reasons},
                "remediation": "补齐对应角色的 maitu_bound 白名单素材" if compiler_blocked_reasons or missing_roles else None,
            },
            {
                "gate": "structural_references",
                "status": "pass" if len(scenes) == len(shots) and all(scene.get("source_script_block_codes") for scene in scenes) else "blocked",
                "rule_code": "GATE_SHOT_PROJECTION_COMPLETE" if len(scenes) == len(shots) and all(scene.get("source_script_block_codes") for scene in scenes) else "GATE_SHOT_PROJECTION_INCOMPLETE",
                "rule_version": "functional-live-room-gates.v1",
                "evidence": {"shot_count": len(shots), "scene_count": len(scenes), "scene_codes": [scene.get("scene_code") for scene in scenes]},
                "remediation": "重新生成 Shot 到场景/图层投影" if len(scenes) != len(shots) or not all(scene.get("source_script_block_codes") for scene in scenes) else None,
            },
            {
                "gate": "execution_constraints",
                "status": "pass" if not build_plan.get("go_live") and operation_types.issubset(allowed_operations) else "blocked",
                "rule_code": "GATE_BUILD_PLAN_ALLOWLIST" if not build_plan.get("go_live") and operation_types.issubset(allowed_operations) else "GATE_BUILD_PLAN_OPERATION_BLOCKED",
                "rule_version": "functional-live-room-gates.v1",
                "evidence": {"operation_types": sorted(operation_types), "go_live": bool(build_plan.get("go_live")), "build_plan_code": build_plan.get("build_plan_code")},
                "remediation": "移除非白名单操作或正式开播动作" if build_plan.get("go_live") or not operation_types.issubset(allowed_operations) else None,
            },
            {
                "gate": "branch_quality",
                "status": "warning" if duration_warning else "pass",
                "rule_code": "GATE_DURATION_DEVIATION_WARNING" if duration_warning else "GATE_BRANCH_QUALITY_PASS",
                "rule_version": "functional-live-room-gates.v1",
                "evidence": {"total_duration_ms": total_duration_ms, "target_duration_seconds": target_duration_seconds, "deviation_ratio": deviation_ratio},
                "remediation": "调整 ProgramSegment 或 Shot 时长" if duration_warning else None,
            },
            {
                "gate": "evidence_completeness",
                "status": "warning",
                "rule_code": "GATE_EXECUTION_EVIDENCE_PENDING",
                "rule_version": "functional-live-room-gates.v1",
                "evidence": {"projection_persisted": True, "execution_readback": False},
                "remediation": "在麦兔只读 preflight 和写入回读后补充现场证据",
            },
        ]
        quality_report = {
            "schema_version": "live-room-branch-quality.functional.v1",
            "estimated_total_duration_ms": total_duration_ms,
            "target_duration_seconds": target_duration_seconds,
            "duration_deviation_ratio": deviation_ratio,
            "warnings": ["duration_deviation_over_50_percent"] if duration_warning else [],
            "required_material_roles": role_needs,
            "selected_material_roles": selected_roles,
            "missing_material_roles": missing_roles,
            "compiler_blocked_reasons": compiler_blocked_reasons,
            "material_role_overrides": dict(blueprint.get("material_role_overrides") or {}),
            "material_selection_decisions": list(blueprint.get("material_selection_decisions") or []),
        }
        return gates, quality_report

    @staticmethod
    def _validate_material_role_overrides(
        overrides: dict[str, Any], assets: list[dict[str, Any]]
    ) -> dict[str, str]:
        if not isinstance(overrides, dict):
            raise DomainValidationError(
                "LIVE_ROOM_MATERIAL_OVERRIDE_INVALID",
                "Material role overrides must be an object of role to selected asset code",
            )
        selected_by_code = {str(asset["asset_code"]): asset for asset in assets}
        normalized: dict[str, str] = {}
        for raw_role, raw_asset_code in overrides.items():
            role = str(raw_role).strip()
            asset_code = str(raw_asset_code).strip()
            asset = selected_by_code.get(asset_code)
            if asset is None:
                raise DomainValidationError(
                    "LIVE_ROOM_MATERIAL_OVERRIDE_NOT_SELECTED",
                    "A material role override must reference an asset selected for this plan",
                    details={"role": role, "asset_code": asset_code},
                )
            if role not in (asset.get("material_roles") or []):
                raise DomainValidationError(
                    "LIVE_ROOM_MATERIAL_OVERRIDE_ROLE_MISMATCH",
                    "The override asset does not carry the requested material role",
                    details={"role": role, "asset_code": asset_code, "asset_roles": asset.get("material_roles") or []},
                )
            normalized[role] = asset_code
        return normalized

    @staticmethod
    def _validate_room_constraint_overrides(
        overrides: dict[str, Any], assets: list[dict[str, Any]], *, actor_id: str
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(overrides, dict):
            raise DomainValidationError(
                "LIVE_ROOM_CONSTRAINT_OVERRIDE_INVALID",
                "Room constraint overrides must be an object keyed by selected asset code",
            )
        selected_by_code = {str(asset["asset_code"]): asset for asset in assets}
        normalized: dict[str, dict[str, Any]] = {}
        for raw_asset_code, raw_override in overrides.items():
            asset_code = str(raw_asset_code).strip()
            if asset_code not in selected_by_code:
                raise DomainValidationError(
                    "LIVE_ROOM_CONSTRAINT_OVERRIDE_NOT_SELECTED",
                    "A room constraint override must reference an asset selected for this plan",
                    details={"asset_code": asset_code},
                )
            if not isinstance(raw_override, dict):
                raise DomainValidationError(
                    "LIVE_ROOM_CONSTRAINT_OVERRIDE_INVALID",
                    "Each room constraint override must be an object",
                    details={"asset_code": asset_code},
                )
            reason = str(raw_override.get("reason") or "").strip()
            if not reason:
                raise DomainValidationError(
                    "LIVE_ROOM_CONSTRAINT_OVERRIDE_REASON_REQUIRED",
                    "A room constraint override requires an operator reason",
                    details={"asset_code": asset_code},
                )
            geometry = raw_override.get("geometry")
            z_order = raw_override.get("z_order")
            if geometry is None and z_order is None:
                raise DomainValidationError(
                    "LIVE_ROOM_CONSTRAINT_OVERRIDE_EMPTY",
                    "A room constraint override must adjust geometry or z order",
                    details={"asset_code": asset_code},
                )
            normalized_geometry: dict[str, float] | None = None
            if geometry is not None:
                if not isinstance(geometry, dict) or set(geometry) != {"x", "y", "width", "height"}:
                    raise DomainValidationError(
                        "LIVE_ROOM_CONSTRAINT_OVERRIDE_GEOMETRY_INVALID",
                        "Room override geometry must contain x, y, width and height",
                        details={"asset_code": asset_code},
                    )
                try:
                    normalized_geometry = {key: float(geometry[key]) for key in ("x", "y", "width", "height")}
                except (TypeError, ValueError) as exc:
                    raise DomainValidationError(
                        "LIVE_ROOM_CONSTRAINT_OVERRIDE_GEOMETRY_INVALID",
                        "Room override geometry values must be numeric",
                        details={"asset_code": asset_code},
                    ) from exc
                x, y, width, height = (normalized_geometry[key] for key in ("x", "y", "width", "height"))
                if not all(isfinite(value) for value in (x, y, width, height)) or x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
                    raise DomainValidationError(
                        "LIVE_ROOM_CONSTRAINT_OVERRIDE_GEOMETRY_INVALID",
                        "Room override geometry must stay within the normalized canvas",
                        details={"asset_code": asset_code},
                    )
            normalized_z_order: int | None = None
            if z_order is not None:
                if isinstance(z_order, bool):
                    raise DomainValidationError(
                        "LIVE_ROOM_CONSTRAINT_OVERRIDE_Z_ORDER_INVALID",
                        "Room override z order must be an integer",
                        details={"asset_code": asset_code},
                    )
                try:
                    normalized_z_order = int(z_order)
                except (TypeError, ValueError) as exc:
                    raise DomainValidationError(
                        "LIVE_ROOM_CONSTRAINT_OVERRIDE_Z_ORDER_INVALID",
                        "Room override z order must be an integer",
                        details={"asset_code": asset_code},
                    ) from exc
                if normalized_z_order < -999 or normalized_z_order > 999:
                    raise DomainValidationError(
                        "LIVE_ROOM_CONSTRAINT_OVERRIDE_Z_ORDER_INVALID",
                        "Room override z order must be between -999 and 999",
                        details={"asset_code": asset_code},
                    )
            normalized[asset_code] = {
                "schema_version": "functional-live-room-room-constraint-override.v1",
                "asset_code": asset_code,
                "reason": reason,
                "geometry": normalized_geometry,
                "z_order": normalized_z_order,
                "actor_id": actor_id,
                "base_constraint_profile_ref": selected_by_code[asset_code].get("constraint_profile_ref"),
            }
        return normalized

    @staticmethod
    def _choose_material_for_role(
        *,
        role: str,
        candidates: list[dict[str, Any]],
        overrides: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        def candidate_score(asset: dict[str, Any]) -> tuple[int, list[str]]:
            capability = str(asset.get("execution_capability") or "unclassified")
            profile_bound = isinstance(asset.get("constraint_profile_ref"), dict)
            score = 60 + (30 if capability == "maitu_bound" else 0) + (10 if profile_bound else 0)
            reasons = ["ROLE_MATCH", f"CAPABILITY_{capability.upper()}"]
            if profile_bound:
                reasons.append("CONSTRAINT_PROFILE_BOUND")
            return score, reasons

        ordered = sorted(candidates, key=lambda asset: (-candidate_score(asset)[0], str(asset["asset_code"])))
        override_asset_code = overrides.get(role)
        selected = next((asset for asset in ordered if asset["asset_code"] == override_asset_code), None) if override_asset_code else ordered[0]
        if selected is None:
            raise DomainValidationError(
                "LIVE_ROOM_MATERIAL_OVERRIDE_INVALID",
                "The requested material role override is not a candidate for this role",
                details={"role": role, "asset_code": override_asset_code},
            )
        score, reasons = candidate_score(selected)
        return selected, {
            "schema_version": "functional-material-selection-decision.v1",
            "role": role,
            "strategy": "explicit_override" if override_asset_code else "deterministic_score",
            "requested_override_asset_code": override_asset_code,
            "selected_asset_code": selected["asset_code"],
            "selected_score": score,
            "selection_reasons": reasons,
            "candidate_scores": [
                {
                    "asset_code": candidate["asset_code"],
                    "score": candidate_score(candidate)[0],
                    "selection_reasons": candidate_score(candidate)[1],
                }
                for candidate in ordered
            ],
        }

    @staticmethod
    def _compile(
        detail: dict[str, Any],
        assets: list[dict[str, Any]],
        payload: dict[str, Any],
        *,
        variant_code: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        room_constraint_overrides = dict(payload.get("room_constraint_overrides") or {})
        assets = [
            {
                **asset,
                "room_constraint_override": room_constraint_overrides.get(str(asset["asset_code"])),
            }
            for asset in assets
        ]
        shots = detail["shot_list"]["shots"]
        blocks = detail["script"]["blocks"]
        layers_by_role: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            for role in asset["material_roles"] or []:
                layers_by_role.setdefault(role, []).append(asset)
        scenes: list[dict[str, Any]] = []
        operations: list[dict[str, Any]] = [{"kind": "rename_room", "expected_title": payload["expected_title"]}]
        blocked: list[str] = []
        material_role_overrides = dict(payload.get("material_role_overrides") or {})
        material_selection_decisions: list[dict[str, Any]] = []
        named_regions, table_surfaces, named_region_failures = FunctionalLiveRoomService._named_regions(assets)
        blocked.extend(named_region_failures)
        active_start_ms = 0
        for index, shot in enumerate(shots):
            layers: list[dict[str, Any]] = []
            for role in shot["material_role_requirements"]:
                candidates = layers_by_role.get(role, [])
                if not candidates:
                    blocked.append(f"missing_role:{role}:shot:{shot['shot_code']}")
                    continue
                asset, selection_decision = FunctionalLiveRoomService._choose_material_for_role(
                    role=str(role), candidates=candidates, overrides=material_role_overrides
                )
                selection_decision = {**selection_decision, "shot_code": shot["shot_code"]}
                material_selection_decisions.append(selection_decision)
                geometry, z_order, visual_properties, audio_properties, constraint_evidence, failures = (
                    FunctionalLiveRoomService._resolve_layer_constraints(
                        asset=asset,
                        role=str(role),
                        named_regions=named_regions,
                        table_surfaces=table_surfaces,
                    )
                )
                constraint_evidence = {
                    **constraint_evidence,
                    "material_selection": selection_decision,
                }
                blocked.extend(f"{failure}:shot:{shot['shot_code']}" for failure in failures)
                layers.append(
                    {
                        "layer_blueprint_code": f"LYR-MSB-{variant_code}-{index + 1:03d}-{len(layers) + 1:02d}",
                        "role": role,
                        "asset_code": asset["asset_code"],
                        "execution_capability": asset["execution_capability"],
                        "normalized_geometry": geometry,
                        "z_order": z_order,
                        "visual_properties": visual_properties,
                        "audio_properties": audio_properties,
                        "constraint_evidence": constraint_evidence,
                        "constraint_rules": FunctionalLiveRoomService._constraint_rules(asset),
                    }
                )
                if asset["execution_capability"] != "maitu_bound":
                    blocked.append(f"asset_not_maitu_bound:{asset['asset_code']}")
            blocked.extend(
                f"{failure}:shot:{shot['shot_code']}"
                for failure in FunctionalLiveRoomService._resolve_scene_layer_relationships(layers)
            )
            scene_code = f"MSB-{variant_code}-{index + 1:03d}"
            duration_ms = int(shot.get("estimated_duration_ms") or 1)
            scenes.append({"scene_code": scene_code, "shot_code": shot["shot_code"], "title": shot["shot_goal"], "layers": layers, "script": blocks[index]["content"], "transition_strategy": {"type": "cut" if index else "initial"}, "estimated_active_start_ms": active_start_ms, "estimated_active_end_ms": active_start_ms + duration_ms, "estimated_duration_ms": duration_ms, "constraint_evidence": {"selection_source": "functional_live_room.v1", "required_roles": shot["material_role_requirements"], "named_regions": named_regions}})
            operations.append({"kind": "create_scene", "scene_code": scene_code, "source_shot": shot["shot_code"]})
            operations.extend({"kind": "insert_bound_asset", "scene_code": scene_code, "asset_code": layer["asset_code"], "role": layer["role"]} for layer in layers)
            operations.append({"kind": "write_script", "scene_code": scene_code, "script_block_code": blocks[index]["block_code"]})
            active_start_ms += duration_ms
        operations.append({"kind": "save_draft"})
        return (
            {
                "schema_version": "maitu-scene-blueprint.functional.v2",
                "scenes": scenes,
                "material_role_overrides": material_role_overrides,
                "room_constraint_overrides": room_constraint_overrides,
                "material_selection_decisions": material_selection_decisions,
            },
            {"schema_version": "maitu-build-plan.functional.v1", "target_live_room_id": payload["target_live_room_id"], "operations": operations, "go_live": False},
            list(dict.fromkeys(blocked)),
        )

    @staticmethod
    def _constraint_rules(asset: dict[str, Any]) -> list[dict[str, Any]]:
        profile = asset.get("constraint_profile_ref")
        if not isinstance(profile, dict):
            return []
        return [rule for rule in profile.get("constraints") or [] if isinstance(rule, dict)]

    @staticmethod
    def _default_geometry(role: str) -> dict[str, float]:
        defaults = {
            "background": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "digital_human": {"x": 0.08, "y": 0.18, "width": 0.36, "height": 0.64},
            "product_display": {"x": 0.52, "y": 0.28, "width": 0.4, "height": 0.4},
            "product_image": {"x": 0.52, "y": 0.28, "width": 0.4, "height": 0.4},
            "promotion_text": {"x": 0.08, "y": 0.78, "width": 0.84, "height": 0.14},
        }
        return dict(defaults.get(role, {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3}))

    @staticmethod
    def _named_regions(
        assets: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, Any]], list[str]]:
        regions: dict[str, dict[str, float]] = {}
        table_surfaces: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        for asset in assets:
            for rule in FunctionalLiveRoomService._constraint_rules(asset):
                kind = str(rule.get("kind") or "")
                if kind not in {"provide_named_region", "table_surface"}:
                    continue
                parameters = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
                # `region` was used by the early UI. Accept it in persisted
                # profiles while emitting `name` from the structured editor.
                name = str(
                    parameters.get("name")
                    or parameters.get("region")
                    or ("table_surface" if kind == "table_surface" else "")
                ).strip()
                rect = FunctionalLiveRoomService._constraint_rect(parameters)
                if not name or rect is None:
                    if bool(rule.get("hard", True)):
                        failures.append(f"constraint_named_region_invalid:{asset['asset_code']}")
                    continue
                previous = regions.get(name)
                if previous is not None and previous != rect and bool(rule.get("hard", True)):
                    failures.append(f"constraint_named_region_conflict:{name}")
                    continue
                regions.setdefault(name, rect)
                if kind == "table_surface":
                    policy = {
                        "product_role": str(parameters.get("product_role") or "product_display").strip(),
                        "product_anchor": str(parameters.get("product_anchor") or "bottom_center").strip(),
                        "hard": bool(rule.get("hard", True)),
                    }
                    previous_policy = table_surfaces.get(name)
                    if previous_policy is not None and previous_policy != policy and bool(rule.get("hard", True)):
                        failures.append(f"constraint_table_surface_policy_conflict:{name}")
                        continue
                    table_surfaces.setdefault(name, policy)
        return regions, table_surfaces, failures

    @staticmethod
    def _resolve_layer_constraints(
        *,
        asset: dict[str, Any],
        role: str,
        named_regions: dict[str, dict[str, float]],
        table_surfaces: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, float], int, dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
        room_override = asset.get("room_constraint_override")
        geometry = (
            dict(room_override["geometry"])
            if isinstance(room_override, dict) and isinstance(room_override.get("geometry"), dict)
            else FunctionalLiveRoomService._default_geometry(role)
        )
        z_order = (
            int(room_override["z_order"])
            if isinstance(room_override, dict) and isinstance(room_override.get("z_order"), int)
            else (100 if role == "digital_human" else 10)
        )
        visual_properties: dict[str, Any] = {}
        audio_properties: dict[str, Any] = {}
        failures: list[str] = []
        applied: list[dict[str, Any]] = []
        if isinstance(room_override, dict):
            applied.append(
                {
                    "kind": "room_private_override",
                    "hard": False,
                    "parameters": {
                        "reason": room_override.get("reason"),
                        "geometry": room_override.get("geometry"),
                        "z_order": room_override.get("z_order"),
                    },
                }
            )
        for rule in FunctionalLiveRoomService._constraint_rules(asset):
            kind = str(rule.get("kind") or "")
            hard = bool(rule.get("hard", True))
            parameters = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
            if kind == "allowed_region":
                rect = FunctionalLiveRoomService._constraint_rect(parameters)
                if rect is None:
                    if hard:
                        failures.append(f"constraint_allowed_region_invalid:{asset['asset_code']}")
                    continue
                geometry = FunctionalLiveRoomService._fit_inside(geometry, rect)
            elif kind == "forbidden_region":
                rect = FunctionalLiveRoomService._constraint_rect(parameters)
                if rect is None:
                    if hard:
                        failures.append(f"constraint_forbidden_region_invalid:{asset['asset_code']}")
                    continue
                if FunctionalLiveRoomService._intersects(geometry, rect) and hard:
                    failures.append(f"constraint_forbidden_region_hit:{asset['asset_code']}")
            elif kind == "size_range":
                geometry = FunctionalLiveRoomService._apply_size_range(geometry, parameters)
            elif kind == "scale_range":
                geometry = FunctionalLiveRoomService._apply_scale_range(geometry, parameters)
            elif kind in {"require_named_region", "align_anchor"}:
                name = str(parameters.get("region") or parameters.get("name") or "").strip()
                region = named_regions.get(name)
                if region is None:
                    if hard:
                        failures.append(f"constraint_named_region_missing:{name or asset['asset_code']}")
                    continue
                if kind == "align_anchor":
                    geometry = FunctionalLiveRoomService._align_anchor(
                        FunctionalLiveRoomService._fit_inside(geometry, region),
                        region,
                        str(parameters.get("anchor") or "bottom_center"),
                    )
            elif kind == "pin_layer_top":
                z_order = 1000
            elif kind == "pin_layer_bottom":
                z_order = -1000
            elif kind == "crop_policy":
                visual_properties["crop_policy"] = parameters.get("policy") or parameters.get("value") or "contain"
            elif kind == "rotation_policy":
                visual_properties["rotation_policy"] = parameters.get("policy") or parameters.get("value") or "locked"
            elif kind == "loop_policy":
                audio_properties["loop_policy"] = parameters.get("policy") or parameters.get("value") or "disabled"
            elif kind == "mute_policy":
                audio_properties["mute_policy"] = parameters.get("policy") or parameters.get("value") or "muted"
            elif kind == "volume_range":
                audio_properties["volume_range"] = parameters
            applied.append({"kind": kind, "hard": hard, "parameters": parameters})
        for name in sorted(table_surfaces):
            policy = table_surfaces[name]
            if policy["product_role"] != role:
                continue
            geometry = FunctionalLiveRoomService._align_anchor(
                FunctionalLiveRoomService._fit_inside(geometry, named_regions[name]),
                named_regions[name],
                str(policy["product_anchor"]),
            )
            applied.append(
                {
                    "kind": "table_surface_placement",
                    "hard": bool(policy["hard"]),
                    "parameters": {"name": name, **policy},
                }
            )
            break
        return (
            geometry,
            z_order,
            visual_properties,
            audio_properties,
            {
                "schema_version": "functional-live-room-constraints.v1",
                "asset_code": asset["asset_code"],
                "constraint_profile_ref": asset.get("constraint_profile_ref"),
                "room_constraint_override": room_override,
                "applied_rules": applied,
                "named_regions_available": sorted(named_regions),
                "table_surfaces_available": table_surfaces,
                "failures": failures,
            },
            failures,
        )

    @staticmethod
    def _resolve_scene_layer_relationships(layers: list[dict[str, Any]]) -> list[str]:
        failures: list[str] = []
        by_role: dict[str, list[dict[str, Any]]] = {}
        for layer in layers:
            by_role.setdefault(str(layer["role"]), []).append(layer)
        for layer in layers:
            z_order = int(layer["z_order"])
            for rule in layer.get("constraint_rules") or []:
                kind = str(rule.get("kind") or "")
                parameters = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
                target_role = str(parameters.get("role") or parameters.get("target_role") or "").strip()
                targets = by_role.get(target_role) or []
                if kind in {"above_role", "below_role"}:
                    if not targets:
                        if bool(rule.get("hard", True)):
                            failures.append(f"constraint_related_role_missing:{target_role or layer['asset_code']}")
                        continue
                    target_z = max(int(target["z_order"]) for target in targets) if kind == "above_role" else min(int(target["z_order"]) for target in targets)
                    requested = target_z + 1 if kind == "above_role" else target_z - 1
                    if (z_order == -1000 and kind == "above_role") or (z_order == 1000 and kind == "below_role"):
                        if bool(rule.get("hard", True)):
                            failures.append(f"constraint_layer_order_conflict:{layer['asset_code']}")
                    else:
                        layer["z_order"] = requested
                        z_order = requested
                if kind == "avoid_overlap" and targets:
                    for target in targets:
                        if target is layer:
                            continue
                        if FunctionalLiveRoomService._intersects(layer["normalized_geometry"], target["normalized_geometry"]):
                            if bool(rule.get("hard", True)):
                                failures.append(f"constraint_overlap:{layer['asset_code']}:{target['asset_code']}")
        return failures

    @staticmethod
    def _constraint_rect(parameters: dict[str, Any]) -> dict[str, float] | None:
        raw = parameters.get("rect")
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            values = raw
        else:
            values = [parameters.get("x"), parameters.get("y"), parameters.get("width"), parameters.get("height")]
        try:
            x, y, width, height = (float(value) for value in values)
        except (TypeError, ValueError):
            return None
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            return None
        return {"x": x, "y": y, "width": width, "height": height}

    @staticmethod
    def _fit_inside(geometry: dict[str, float], rect: dict[str, float]) -> dict[str, float]:
        width = min(float(geometry["width"]), rect["width"])
        height = min(float(geometry["height"]), rect["height"])
        return {
            "x": min(max(float(geometry["x"]), rect["x"]), rect["x"] + rect["width"] - width),
            "y": min(max(float(geometry["y"]), rect["y"]), rect["y"] + rect["height"] - height),
            "width": width,
            "height": height,
        }

    @staticmethod
    def _apply_size_range(geometry: dict[str, float], parameters: dict[str, Any]) -> dict[str, float]:
        result = dict(geometry)
        for dimension in ("width", "height"):
            try:
                minimum = float(parameters.get(f"min_{dimension}", 0.0))
                maximum = float(parameters.get(f"max_{dimension}", 1.0))
            except (TypeError, ValueError):
                continue
            if 0 <= minimum <= maximum <= 1:
                result[dimension] = min(max(result[dimension], minimum), maximum)
        result["x"] = min(max(result["x"], 0.0), 1.0 - result["width"])
        result["y"] = min(max(result["y"], 0.0), 1.0 - result["height"])
        return result

    @staticmethod
    def _apply_scale_range(geometry: dict[str, float], parameters: dict[str, Any]) -> dict[str, float]:
        try:
            minimum = float(parameters.get("min_scale", 0.0))
            maximum = float(parameters.get("max_scale", 1.0))
        except (TypeError, ValueError):
            return geometry
        if minimum < 0 or maximum < minimum:
            return geometry
        scale = min(max(1.0, minimum), maximum)
        return FunctionalLiveRoomService._apply_size_range(
            {**geometry, "width": geometry["width"] * scale, "height": geometry["height"] * scale},
            {},
        )

    @staticmethod
    def _align_anchor(geometry: dict[str, float], region: dict[str, float], anchor: str) -> dict[str, float]:
        result = dict(geometry)
        if anchor == "top_left":
            result["x"], result["y"] = region["x"], region["y"]
        elif anchor == "top_center":
            result["x"], result["y"] = region["x"] + (region["width"] - result["width"]) / 2, region["y"]
        elif anchor == "bottom_center":
            result["x"], result["y"] = (
                region["x"] + (region["width"] - result["width"]) / 2,
                region["y"] + region["height"] - result["height"],
            )
        else:
            result["x"], result["y"] = (
                region["x"] + (region["width"] - result["width"]) / 2,
                region["y"] + (region["height"] - result["height"]) / 2,
            )
        return result

    @staticmethod
    def _intersects(first: dict[str, float], second: dict[str, float]) -> bool:
        return not (
            first["x"] + first["width"] <= second["x"]
            or second["x"] + second["width"] <= first["x"]
            or first["y"] + first["height"] <= second["y"]
            or second["y"] + second["height"] <= first["y"]
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        inventory_snapshot = dict(result.get("build_plan") or {}).get("inventory_snapshot") or {}
        result["selected_asset_gap_codes"] = [
            str(gap["gap_code"])
            for gap in inventory_snapshot.get("asset_gap_refs") or []
            if isinstance(gap, dict) and gap.get("gap_code")
        ]
        return result

    @staticmethod
    def _next_code(cursor: Any, prefix: str, object_type: str) -> str:
        sequence_date = datetime.now(UTC).date()
        cursor.execute(
            """
            INSERT INTO domain_sequences (sequence_date, object_type, current_value)
            VALUES (%s, %s, 1)
            ON CONFLICT (sequence_date, object_type)
            DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now()
            RETURNING current_value
            """,
            (sequence_date, object_type),
        )
        return f"{prefix}-{sequence_date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"

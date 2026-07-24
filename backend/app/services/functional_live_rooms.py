from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainValidationError
from app.repositories.content_production import ContentProductionRepository
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
        self.maitu = MaituMaterialSlotRepository(connection)
        self._release_signing_key = release_signing_key
        self._release_signing_key_id = release_signing_key_id

    def create_plan(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        detail = self.content.get_detail(payload["project_code"])
        if detail is None:
            raise KeyError(payload["project_code"])
        if not detail["generated"]:
            raise DomainValidationError("LIVE_ROOM_SHOT_LIST_REQUIRED", "Generate the ContentProject before planning a live room")
        selected_assets = self._selected_assets(payload.get("asset_codes") or [], payload.get("group_codes") or [])
        if not selected_assets:
            raise DomainValidationError("LIVE_ROOM_ASSETS_REQUIRED", "Select at least one asset or group before planning")
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
                }
                for asset in selected_assets
            ],
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
            configuration={"templates": templates, "selected_asset_codes": snapshot["asset_codes"]},
            material_snapshot_ref=snapshot,
            constraint_snapshot_ref={"source": "functional_asset_constraint_profiles.v1"},
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
            configuration={"templates": templates, "selected_asset_codes": snapshot["asset_codes"], "selected_group_codes": payload.get("group_codes") or []},
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
                    secondary_template_codes, selected_asset_codes, selected_group_codes,
                    blueprint, build_plan, gate_results, quality_report, status, blocked_reasons
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    code, detail["project_code"], variant["variant_code"], configuration["configuration_code"],
                    payload["target_live_room_id"], payload["expected_title"], templates["primary_template_code"],
                    Jsonb(templates["secondary_template_codes"]), Jsonb(snapshot["asset_codes"]),
                    Jsonb(payload.get("group_codes") or []), Jsonb(blueprint), Jsonb(build_plan),
                    Jsonb(gate_results), Jsonb(quality_report), status, Jsonb(plan_blocked_reasons),
                ),
            )
            row = cursor.fetchone()
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
                """SELECT asset_code, COALESCE(title, original_filename) AS title,
                          media_kind, material_roles, execution_capability
                   FROM assets WHERE asset_code = ANY(%s) AND deleted_at IS NULL""",
                (codes,),
            )
            rows = cursor.fetchall()
        by_code = {row["asset_code"]: row for row in rows}
        missing = [code for code in codes if code not in by_code]
        if missing:
            raise DomainValidationError("LIVE_ROOM_ASSET_NOT_FOUND", "Selected assets no longer exist", details={"asset_codes": missing})
        return [by_code[code] for code in codes]

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
        }
        return gates, quality_report

    @staticmethod
    def _compile(
        detail: dict[str, Any],
        assets: list[dict[str, Any]],
        payload: dict[str, Any],
        *,
        variant_code: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        shots = detail["shot_list"]["shots"]
        blocks = detail["script"]["blocks"]
        layers_by_role: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            for role in asset["material_roles"] or []:
                layers_by_role.setdefault(role, []).append(asset)
        scenes: list[dict[str, Any]] = []
        operations: list[dict[str, Any]] = [{"kind": "rename_room", "expected_title": payload["expected_title"]}]
        blocked: list[str] = []
        active_start_ms = 0
        for index, shot in enumerate(shots):
            layers: list[dict[str, Any]] = []
            for role in shot["material_role_requirements"]:
                candidates = layers_by_role.get(role, [])
                if not candidates:
                    blocked.append(f"missing_role:{role}:shot:{shot['shot_code']}")
                    continue
                asset = candidates[0]
                layers.append({"layer_blueprint_code": f"LYR-MSB-{variant_code}-{index + 1:03d}-{len(layers) + 1:02d}", "role": role, "asset_code": asset["asset_code"], "execution_capability": asset["execution_capability"], "z_order": 100 if role == "digital_human" else 10})
                if asset["execution_capability"] != "maitu_bound":
                    blocked.append(f"asset_not_maitu_bound:{asset['asset_code']}")
            scene_code = f"MSB-{variant_code}-{index + 1:03d}"
            duration_ms = int(shot.get("estimated_duration_ms") or 1)
            scenes.append({"scene_code": scene_code, "shot_code": shot["shot_code"], "title": shot["shot_goal"], "layers": layers, "script": blocks[index]["content"], "transition_strategy": {"type": "cut" if index else "initial"}, "estimated_active_start_ms": active_start_ms, "estimated_active_end_ms": active_start_ms + duration_ms, "estimated_duration_ms": duration_ms, "constraint_evidence": {"selection_source": "functional_live_room.v1", "required_roles": shot["material_role_requirements"]}})
            operations.append({"kind": "create_scene", "scene_code": scene_code, "source_shot": shot["shot_code"]})
            operations.extend({"kind": "insert_bound_asset", "scene_code": scene_code, "asset_code": layer["asset_code"], "role": layer["role"]} for layer in layers)
            operations.append({"kind": "write_script", "scene_code": scene_code, "script_block_code": blocks[index]["block_code"]})
            active_start_ms += duration_ms
        operations.append({"kind": "save_draft"})
        return (
            {"schema_version": "maitu-scene-blueprint.functional.v1", "scenes": scenes},
            {"schema_version": "maitu-build-plan.functional.v1", "target_live_room_id": payload["target_live_room_id"], "operations": operations, "go_live": False},
            list(dict.fromkeys(blocked)),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        return dict(row)

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

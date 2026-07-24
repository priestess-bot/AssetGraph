from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainValidationError
from app.repositories.content_production import ContentProductionRepository
from app.repositories.maitu import MaituMaterialSlotRepository
from app.services.functional_content import FunctionalContentService
from app.services.script_layout_build_plan_builder import ScriptLayoutBuildPlanBuilder


class FunctionalLiveRoomService:
    """Builds a reviewable Maitu draft plan without exposing a go-live action."""

    def __init__(self, connection: Connection):
        self.connection = connection
        self.content = FunctionalContentService(connection)
        self.production = ContentProductionRepository(connection)
        self.maitu = MaituMaterialSlotRepository(connection)

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
        plan_blocked_reasons = list(dict.fromkeys([*blocked_reasons, *(build_plan.get("blocked_reasons") or [])]))
        status = "blocked" if plan_blocked_reasons or not build_plan.get("can_execute") else "ready"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code = self._next_code(cursor, "LIVEPLAN", "functional_live_room_plan")
            cursor.execute(
                """
                INSERT INTO functional_live_room_plans (
                    plan_code, project_code, variant_code, configuration_code,
                    target_live_room_id, expected_title, primary_template_code,
                    secondary_template_codes, selected_asset_codes, selected_group_codes,
                    blueprint, build_plan, status, blocked_reasons
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    code, detail["project_code"], variant["variant_code"], configuration["configuration_code"],
                    payload["target_live_room_id"], payload["expected_title"], templates["primary_template_code"],
                    Jsonb(templates["secondary_template_codes"]), Jsonb(snapshot["asset_codes"]),
                    Jsonb(payload.get("group_codes") or []), Jsonb(blueprint), Jsonb(build_plan), status, Jsonb(plan_blocked_reasons),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def list_plans(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_live_room_plans ORDER BY updated_at DESC, plan_code")
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def get_plan(self, plan_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_live_room_plans WHERE plan_code = %s", (plan_code,))
            row = cursor.fetchone()
        return self._serialize(row) if row else None

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
        return self._serialize(row)

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

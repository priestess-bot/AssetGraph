from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainConflictError, DomainValidationError


class ContentWorkflowRepository:
    """Persistence for the guided live-project authoring workflow."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def get_project(self, project_code: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update else ""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT project.id AS project_id, project.project_code, project.title,
                       project.status AS project_status, project.owner_principal,
                       revision.id AS project_revision_id, revision.revision_number,
                       revision.status, revision.generation_goal, revision.content,
                       revision.source_revision_refs, revision.fingerprint_sha256,
                       revision.created_at, revision.updated_at
                FROM content_projects AS project
                JOIN content_project_revisions AS revision
                  ON revision.project_id = project.id
                 AND revision.revision_number = project.current_revision_number
                WHERE project.project_code = %s{suffix}
                """,
                (project_code,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def create_material_pool(
        self,
        *,
        project_id: UUID,
        project_code: str,
        selected_asset_codes: list[str],
        actor_id: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        codes = self._codes(selected_asset_codes)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id FROM content_projects WHERE id = %s FOR UPDATE", (project_id,))
            cursor.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0)::integer AS revision
                FROM content_project_material_pool_revisions
                WHERE project_id = %s
                """,
                (project_id,),
            )
            current_revision = int(cursor.fetchone()["revision"])
            if expected_revision is not None and current_revision != expected_revision:
                raise DomainConflictError(
                    "MATERIAL_POOL_REVISION_CONFLICT",
                    "The project material pool changed since it was loaded",
                    details={"expected_revision": expected_revision, "actual_revision": current_revision},
                )
            if current_revision:
                cursor.execute(
                    """
                    SELECT * FROM content_project_material_pool_revisions
                    WHERE project_id = %s AND revision_number = %s
                    """,
                    (project_id, current_revision),
                )
                current = cursor.fetchone()
                if list(current["selected_asset_codes"] or []) == codes:
                    self.connection.rollback()
                    return dict(current)
            next_revision = current_revision + 1
            payload = {
                "project_code": project_code,
                "revision_number": next_revision,
                "selected_asset_codes": codes,
            }
            cursor.execute(
                """
                INSERT INTO content_project_material_pool_revisions (
                    pool_revision_code, project_id, project_code, revision_number,
                    selected_asset_codes, fingerprint_sha256, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    f"POOL-{uuid4().hex[:16].upper()}",
                    project_id,
                    project_code,
                    next_revision,
                    Jsonb(codes),
                    canonical_fingerprint(payload),
                    actor_id,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row)

    def latest_material_pool(self, project_id: UUID) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM content_project_material_pool_revisions
                WHERE project_id = %s
                ORDER BY revision_number DESC LIMIT 1
                """,
                (project_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def material_pool_revision(
        self, project_id: UUID, revision_number: int
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM content_project_material_pool_revisions
                WHERE project_id = %s AND revision_number = %s
                """,
                (project_id, revision_number),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def load_assets(
        self,
        asset_codes: list[str],
        *,
        require_usable: bool = True,
        require_maitu_bound: bool = True,
    ) -> list[dict[str, Any]]:
        codes = self._codes(asset_codes)
        if not codes:
            return []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, COALESCE(title, original_filename) AS title,
                       description, media_kind, material_roles, execution_capability,
                       rights_status, classification_review_status,
                       classification_evidence, maitu_category, usage, subject
                FROM assets
                WHERE asset_code = ANY(%s) AND deleted_at IS NULL
                """,
                (codes,),
            )
            rows = cursor.fetchall()
        by_code = {str(row["asset_code"]): dict(row) for row in rows}
        missing = [code for code in codes if code not in by_code]
        if missing:
            raise DomainValidationError(
                "GUIDED_MATERIAL_NOT_FOUND",
                "One or more selected materials no longer exist",
                details={"asset_codes": missing},
            )
        if require_maitu_bound:
            not_bound = [
                code
                for code in codes
                if by_code[code].get("execution_capability") != "maitu_bound"
            ]
            if not_bound:
                raise DomainValidationError(
                    "GUIDED_MATERIAL_NOT_MAITU_BOUND",
                    "Guided live projects only accept Maitu-bound materials",
                    details={"asset_codes": not_bound},
                )
        if require_usable:
            unusable = [
                code
                for code in codes
                if by_code[code].get("rights_status") != "approved"
                or by_code[code].get("execution_capability") != "maitu_bound"
            ]
            if unusable:
                raise DomainValidationError(
                    "GUIDED_MATERIAL_NOT_USABLE",
                    "Guided live projects only accept rights-approved Maitu-bound materials",
                    details={"asset_codes": unusable},
                )
        else:
            unreviewed = [
                code
                for code in codes
                if by_code[code].get("rights_status") not in {"pending", "approved"}
            ]
            if unreviewed:
                raise DomainValidationError(
                    "GUIDED_MATERIAL_NOT_PLANNABLE",
                    "Guided live projects only accept pending or approved materials during planning",
                    details={"asset_codes": unreviewed},
                )
        return [by_code[code] for code in codes]

    def recommendable_assets(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, COALESCE(title, original_filename) AS title,
                       description, media_kind, material_roles, execution_capability,
                       rights_status, classification_review_status,
                       classification_evidence, maitu_category, usage, subject
                FROM assets
                WHERE deleted_at IS NULL
                  AND execution_capability = 'maitu_bound'
                  AND rights_status IN ('pending', 'approved')
                  AND NOT material_roles @> '["digital_human"]'::jsonb
                  AND NOT material_roles @> '["voice"]'::jsonb
                ORDER BY rights_status DESC, updated_at DESC, asset_code
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def planning_assets(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, COALESCE(title, original_filename) AS title,
                       description, media_kind, material_roles, execution_capability,
                       rights_status, classification_review_status,
                       classification_evidence, maitu_category, usage, subject
                FROM assets
                WHERE deleted_at IS NULL
                  AND execution_capability = 'maitu_bound'
                  AND rights_status IN ('pending', 'approved')
                ORDER BY updated_at DESC NULLS LAST, asset_code
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def latest_outline(self, project_id: UUID) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.*, project_revision.revision_number AS source_project_revision
                FROM story_brief_revisions AS revision
                JOIN story_briefs AS brief ON brief.id = revision.story_brief_id
                JOIN content_project_revisions AS project_revision
                  ON project_revision.id = revision.source_project_revision_id
                WHERE brief.project_id = %s
                ORDER BY revision.revision_number DESC LIMIT 1
                """,
                (project_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def latest_confirmed_outline(self, project_id: UUID) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.*, project_revision.revision_number AS source_project_revision
                FROM story_brief_revisions AS revision
                JOIN story_briefs AS brief ON brief.id = revision.story_brief_id
                JOIN content_project_revisions AS project_revision
                  ON project_revision.id = revision.source_project_revision_id
                WHERE brief.project_id = %s AND revision.status = 'confirmed'
                ORDER BY revision.revision_number DESC LIMIT 1
                """,
                (project_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def outline_revision(
        self, project_id: UUID, revision_number: int
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.*, project_revision.revision_number AS source_project_revision
                FROM story_brief_revisions AS revision
                JOIN story_briefs AS brief ON brief.id = revision.story_brief_id
                JOIN content_project_revisions AS project_revision
                  ON project_revision.id = revision.source_project_revision_id
                WHERE brief.project_id = %s AND revision.revision_number = %s
                """,
                (project_id, revision_number),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def latest_script(self, project_id: UUID) -> dict[str, Any] | None:
        return self._load_script(project_id)

    def latest_active_script(self, project_id: UUID) -> dict[str, Any] | None:
        return self._load_script(project_id, active_only=True)

    def script_revision_by_code(self, project_id: UUID, revision_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision_number FROM content_script_revisions
                WHERE project_id = %s AND script_revision_code = %s
                """,
                (project_id, revision_code),
            )
            row = cursor.fetchone()
        return self.script_revision(project_id, int(row["revision_number"])) if row else None

    def script_revision(self, project_id: UUID, revision_number: int) -> dict[str, Any] | None:
        return self._load_script(project_id, revision_number=revision_number)

    def script_archives(self, project_id: UUID, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT DISTINCT script.revision_number
                FROM content_script_revisions AS script
                LEFT JOIN content_guided_revision_archives AS archive
                  ON archive.project_id = script.project_id
                 AND archive.artifact_type = 'script'
                 AND archive.artifact_code = script.script_revision_code
                 AND archive.revision_number = script.revision_number
                WHERE script.project_id = %s
                  AND (script.status = 'superseded' OR archive.id IS NOT NULL)
                ORDER BY script.revision_number DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
            revisions = [int(row["revision_number"]) for row in cursor.fetchall()]
        return [
            script
            for revision in revisions
            if (script := self.script_revision(project_id, revision)) is not None
        ]

    def archive_script_draft(
        self,
        script_revision_id: UUID,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_script_revisions WHERE id = %s FOR UPDATE",
                (script_revision_id,),
            )
            script = cursor.fetchone()
            if script is None:
                raise KeyError(script_revision_id)
            if script["status"] != "draft":
                raise DomainConflictError(
                    "GUIDED_SCRIPT_ARCHIVE_NOT_ALLOWED",
                    "Only the active script draft can be archived",
                )
            cursor.execute(
                """
                UPDATE content_script_revisions
                SET status = 'superseded', superseded_at = now(), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (script_revision_id,),
            )
            archived = cursor.fetchone()
        if commit:
            self.connection.commit()
        return dict(archived)

    def archive_script(
        self,
        script: dict[str, Any],
        *,
        project_code: str,
        reason: str,
        actor_id: str,
        details: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Record a logical archive without mutating immutable confirmed revisions."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO content_guided_revision_archives (
                    archive_code, project_id, project_code, artifact_type, artifact_code,
                    revision_number, reason, details, archived_by
                ) VALUES (%s, %s, %s, 'script', %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, artifact_type, artifact_code, revision_number)
                DO UPDATE SET details = content_guided_revision_archives.details || EXCLUDED.details
                RETURNING *
                """,
                (
                    f"CARCH-{uuid4().hex[:16].upper()}",
                    script["project_id"],
                    project_code,
                    script["script_revision_code"],
                    int(script["revision_number"]),
                    reason,
                    Jsonb(details or {}),
                    actor_id,
                ),
            )
            archive = cursor.fetchone()
        if commit:
            self.connection.commit()
        return dict(archive)

    def _load_script(
        self,
        project_id: UUID,
        *,
        revision_number: int | None = None,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        clauses = ["script.project_id = %s"]
        params: list[Any] = [project_id]
        if revision_number is not None:
            clauses.append("script.revision_number = %s")
            params.append(revision_number)
        if active_only:
            clauses.append("script.status IN ('draft', 'confirmed')")
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM content_guided_revision_archives AS archive "
                "WHERE archive.project_id = script.project_id AND archive.artifact_type = 'script' "
                "AND archive.artifact_code = script.script_revision_code "
                "AND archive.revision_number = script.revision_number)"
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT script.*, outline.story_brief_code,
                       outline.revision_number AS source_outline_revision
                FROM content_script_revisions AS script
                JOIN story_brief_revisions AS outline
                  ON outline.id = script.source_story_brief_revision_id
                WHERE {' AND '.join(clauses)}
                ORDER BY script.revision_number DESC LIMIT 1
                """,
                tuple(params),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            result = dict(row)
            cursor.execute(
                """
                SELECT id, block_code, sort_order, module_type, content,
                       estimated_duration_ms, fact_citations, template_sources,
                       content_rule_refs, interaction_intent, cta_intent
                FROM content_script_blocks
                WHERE script_revision_id = %s ORDER BY sort_order
                """,
                (row["id"],),
            )
            result["blocks"] = [dict(item) for item in cursor.fetchall()]
            result["requirements"] = self._requirements(cursor, row["id"])
        return result

    def requirements_for_script(self, script_revision_id: UUID) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return self._requirements(cursor, script_revision_id)

    def replace_requirements(
        self,
        *,
        script_revision_id: UUID,
        blocks: list[dict[str, Any]],
        requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_order = {int(block["sort_order"]): block for block in blocks}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "DELETE FROM content_script_material_requirements WHERE script_revision_id = %s",
                (script_revision_id,),
            )
            for requirement in requirements:
                block_order = int(requirement["block_sort_order"])
                block = by_order.get(block_order)
                if block is None:
                    raise DomainValidationError(
                        "SCRIPT_MATERIAL_BLOCK_INVALID",
                        "A material requirement references a missing script block",
                    )
                status = str(requirement.get("status") or "missing")
                waived_at = requirement.get("waived_at")
                if isinstance(waived_at, str):
                    waived_at = datetime.fromisoformat(waived_at.replace("Z", "+00:00"))
                cursor.execute(
                    """
                    INSERT INTO content_script_material_requirements (
                        requirement_code, script_revision_id, script_block_id,
                        sort_order, material_role, description, priority, keywords,
                        matched_asset_code, status, match_evidence,
                        waived_by, waived_at, waiver_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(requirement.get("requirement_code") or f"REQ-{uuid4().hex[:16].upper()}"),
                        script_revision_id,
                        block["id"],
                        int(requirement["sort_order"]),
                        requirement["material_role"],
                        requirement["description"],
                        requirement["priority"],
                        Jsonb(list(requirement.get("keywords") or [])),
                        requirement.get("matched_asset_code"),
                        status,
                        Jsonb(dict(requirement.get("match_evidence") or {})),
                        requirement.get("waived_by"),
                        waived_at,
                        requirement.get("waiver_reason"),
                    ),
                )
        self.connection.commit()
        return self.requirements_for_script(script_revision_id)

    def update_requirement_matches(
        self, script_revision_id: UUID, matches: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            for match in matches:
                cursor.execute(
                    """
                    UPDATE content_script_material_requirements
                    SET matched_asset_code = %s, status = %s, match_evidence = %s,
                        waived_by = %s, waived_at = %s, waiver_reason = %s
                    WHERE script_revision_id = %s AND requirement_code = %s
                    """,
                    (
                        match.get("matched_asset_code"),
                        match["status"],
                        Jsonb(dict(match.get("match_evidence") or {})),
                        match.get("waived_by"),
                        match.get("waived_at"),
                        match.get("waiver_reason"),
                        script_revision_id,
                        match["requirement_code"],
                    ),
                )
        self.connection.commit()
        return self.requirements_for_script(script_revision_id)

    def waive_requirement(
        self, requirement_code: str, *, script_revision_id: UUID, actor_id: str
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE content_script_material_requirements
                SET status = 'waived', matched_asset_code = NULL,
                    match_evidence = jsonb_build_object('decision', 'manual_waiver'),
                    waived_by = %s, waived_at = now(), waiver_reason = 'operator_accepted_manual_storyboard'
                WHERE requirement_code = %s AND script_revision_id = %s
                  AND priority = 'required' AND status = 'missing'
                RETURNING *
                """,
                (actor_id, requirement_code, script_revision_id),
            )
            row = cursor.fetchone()
        if row is None:
            self.connection.rollback()
            raise DomainConflictError(
                "SCRIPT_MATERIAL_WAIVER_NOT_ALLOWED",
                "Only a missing required material can be waived",
            )
        self.connection.commit()
        return dict(row)

    def enqueue_job(
        self,
        *,
        project: dict[str, Any],
        stage: str,
        operation: str | None = None,
        material_pool_revision: int,
        input_snapshot: dict[str, Any],
        requested_by: str,
        source_outline_revision: int | None = None,
        source_script_revision: int | None = None,
        template_ref: dict[str, Any] | None = None,
        items: list[dict[str, Any]] | None = None,
        target_node_id: UUID | None = None,
        target_node_revision: int | None = None,
        target_item_id: UUID | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        resolved_operation = operation or {
            "outline": "generate_outline",
            "script": "generate_script",
            "storyboard": "generate_storyboard",
        }.get(stage, "generate")
        fingerprint = canonical_fingerprint(
            {
                "operation": resolved_operation,
                "input_snapshot": input_snapshot,
                "source_project_revision": int(project["revision_number"]),
                "source_material_pool_revision": material_pool_revision,
                "source_outline_revision": source_outline_revision,
                "source_script_revision": source_script_revision,
                "template_ref": template_ref or {},
                "target_node_id": str(target_node_id or ""),
                "target_node_revision": target_node_revision,
                "target_item_id": str(target_item_id or ""),
            }
        )
        idempotency_key = f"{resolved_operation}:{fingerprint}"
        job_items = items or [{"item_key": stage, "input_payload": input_snapshot}]
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT id FROM content_projects WHERE id = %s FOR UPDATE",
                (project["project_id"],),
            )
            cursor.execute(
                """
                SELECT * FROM content_generation_jobs
                WHERE project_id = %s AND stage = %s AND idempotency_key = %s
                """,
                (project["project_id"], stage, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                return dict(existing)
            if target_item_id is not None:
                cursor.execute(
                    """
                    UPDATE content_generation_jobs
                    SET status = 'stale', finished_at = now(), updated_at = now(),
                        error_code = 'INPUT_SUPERSEDED',
                        error_message = 'A newer generation request replaced this item job'
                    WHERE target_item_id = %s AND operation = %s
                      AND status IN ('queued', 'running')
                    """,
                    (target_item_id, resolved_operation),
                )
            else:
                cursor.execute(
                    """
                    UPDATE content_generation_jobs
                    SET status = 'stale', finished_at = now(), updated_at = now(),
                        error_code = 'INPUT_SUPERSEDED',
                        error_message = 'A newer generation request replaced this branch job'
                    WHERE project_id = %s AND stage = %s AND operation = %s
                      AND target_item_id IS NULL AND status IN ('queued', 'running')
                    """,
                    (project["project_id"], stage, resolved_operation),
                )
            cursor.execute(
                """
                INSERT INTO content_generation_jobs (
                    job_code, project_id, project_code, stage, operation, status, idempotency_key,
                    source_project_revision, source_material_pool_revision,
                    source_outline_revision, source_script_revision, template_ref,
                    input_snapshot, input_fingerprint, total_items, requested_by,
                    target_node_id, target_node_revision, target_item_id
                ) VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    f"CGEN-{uuid4().hex[:16].upper()}",
                    project["project_id"],
                    project["project_code"],
                    stage,
                    resolved_operation,
                    idempotency_key,
                    int(project["revision_number"]),
                    material_pool_revision,
                    source_outline_revision,
                    source_script_revision,
                    Jsonb(template_ref or {}),
                    Jsonb(input_snapshot),
                    fingerprint,
                    len(job_items),
                    requested_by,
                    target_node_id,
                    target_node_revision,
                    target_item_id,
                ),
            )
            job = cursor.fetchone()
            for sort_order, item in enumerate(job_items):
                cursor.execute(
                    """
                    INSERT INTO content_generation_job_items (
                        job_id, item_key, sort_order, input_payload
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        job["id"],
                        str(item.get("item_key") or f"item-{sort_order + 1}"),
                        sort_order,
                        Jsonb(dict(item.get("input_payload") or {})),
                    ),
                )
        if commit:
            self.connection.commit()
        return dict(job)

    def latest_jobs(self, project_id: UUID) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (stage, operation, target_node_id, target_item_id) *
                FROM content_generation_jobs
                WHERE project_id = %s
                ORDER BY stage, operation, target_node_id, target_item_id, created_at DESC
                """,
                (project_id,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def workflow_history(self, project_id: UUID, project_code: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT pool_revision_code AS code, revision_number, created_by AS actor,
                       created_at AS occurred_at, selected_asset_codes
                FROM content_project_material_pool_revisions
                WHERE project_id = %s ORDER BY revision_number
                """,
                (project_id,),
            )
            for row in cursor.fetchall():
                events.append(
                    {
                        "event_code": f"material:{row['code']}",
                        "stage": "setup",
                        "kind": "material_pool_revision",
                        "reference_code": row["code"],
                        "revision_number": int(row["revision_number"]),
                        "status": "saved",
                        "actor": row["actor"],
                        "occurred_at": row["occurred_at"],
                        "details": {"asset_count": len(row["selected_asset_codes"] or [])},
                    }
                )
            cursor.execute(
                """
                SELECT revision.story_brief_code AS code, revision.revision_number,
                       revision.status, revision.created_by, revision.confirmed_by,
                       revision.created_at, revision.confirmed_at
                FROM story_brief_revisions AS revision
                JOIN story_briefs AS brief ON brief.id = revision.story_brief_id
                WHERE brief.project_id = %s
                  AND revision.content ->> 'schema_version' = 'guided-live-outline.v1'
                ORDER BY revision.revision_number
                """,
                (project_id,),
            )
            for row in cursor.fetchall():
                events.append(
                    {
                        "event_code": f"outline:{row['code']}",
                        "stage": "outline",
                        "kind": "outline_revision",
                        "reference_code": row["code"],
                        "revision_number": int(row["revision_number"]),
                        "status": row["status"],
                        "actor": row["confirmed_by"] or row["created_by"],
                        "occurred_at": row["confirmed_at"] or row["created_at"],
                        "details": {},
                    }
                )
            cursor.execute(
                """
                SELECT script_revision_code AS code, revision_number, status,
                       created_by, confirmed_by, created_at, confirmed_at
                FROM content_script_revisions
                WHERE project_id = %s AND content ->> 'workflow_version' = 'guided-live.v1'
                ORDER BY revision_number
                """,
                (project_id,),
            )
            for row in cursor.fetchall():
                events.append(
                    {
                        "event_code": f"script:{row['code']}",
                        "stage": "script",
                        "kind": "script_revision",
                        "reference_code": row["code"],
                        "revision_number": int(row["revision_number"]),
                        "status": row["status"],
                        "actor": row["confirmed_by"] or row["created_by"],
                        "occurred_at": row["confirmed_at"] or row["created_at"],
                        "details": {},
                    }
                )
            cursor.execute(
                """
                SELECT plan_code AS code, review_status AS status, confirmed_by,
                       created_at, confirmed_at, revision_context
                FROM functional_live_room_plans
                WHERE project_code = %s
                  AND revision_context ->> 'workflow_version' = 'guided-live.v1'
                ORDER BY created_at
                """,
                (project_code,),
            )
            for index, row in enumerate(cursor.fetchall(), start=1):
                context = dict(row["revision_context"] or {})
                events.append(
                    {
                        "event_code": f"storyboard:{row['code']}",
                        "stage": "storyboard",
                        "kind": "storyboard_revision",
                        "reference_code": row["code"],
                        "revision_number": index,
                        "status": row["status"],
                        "actor": row["confirmed_by"] or context.get("invalidated_by")
                        or "guided-content-generation-worker",
                        "occurred_at": row["confirmed_at"] or row["created_at"],
                        "details": {
                            key: context[key]
                            for key in ("manual_only", "invalidated_reason", "invalidated_at")
                            if context.get(key) is not None
                        },
                    }
                )
            cursor.execute(
                """
                SELECT job_code AS code, stage, status, requested_by, attempts,
                       error_code, error_message, created_at, updated_at
                FROM content_generation_jobs
                WHERE project_id = %s ORDER BY created_at
                """,
                (project_id,),
            )
            for row in cursor.fetchall():
                events.append(
                    {
                        "event_code": f"job:{row['code']}",
                        "stage": row["stage"],
                        "kind": "generation_job",
                        "reference_code": row["code"],
                        "revision_number": None,
                        "status": row["status"],
                        "actor": row["requested_by"],
                        "occurred_at": row["updated_at"] or row["created_at"],
                        "details": {
                            "attempts": int(row["attempts"]),
                            "error_code": row["error_code"],
                            "error_message": row["error_message"],
                        },
                    }
                )
            cursor.execute(
                """
                SELECT requirement.requirement_code AS code, requirement.waived_by,
                       requirement.waived_at, requirement.waiver_reason,
                       script.revision_number
                FROM content_script_material_requirements AS requirement
                JOIN content_script_revisions AS script
                  ON script.id = requirement.script_revision_id
                WHERE script.project_id = %s AND requirement.status = 'waived'
                ORDER BY requirement.waived_at
                """,
                (project_id,),
            )
            for row in cursor.fetchall():
                events.append(
                    {
                        "event_code": f"waiver:{row['code']}",
                        "stage": "script",
                        "kind": "material_waiver",
                        "reference_code": row["code"],
                        "revision_number": int(row["revision_number"]),
                        "status": "waived",
                        "actor": row["waived_by"],
                        "occurred_at": row["waived_at"],
                        "details": {"reason": row["waiver_reason"]},
                    }
                )
        return sorted(events, key=lambda item: item["occurred_at"], reverse=True)[:500]

    def get_job(self, job_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM content_generation_jobs WHERE job_code = %s", (job_code,))
            row = cursor.fetchone()
        return dict(row) if row else None

    def job_items(self, job_id: UUID) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_generation_job_items WHERE job_id = %s ORDER BY sort_order",
                (job_id,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def claim_job(self, worker_id: str, *, lease_seconds: int = 300) -> dict[str, Any] | None:
        expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE content_generation_jobs
                SET status = 'failed', error_code = 'GENERATION_WORKER_LEASE_EXHAUSTED',
                    error_message = 'The worker lease expired after the final attempt',
                    lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = now(), updated_at = now()
                WHERE status = 'running' AND lease_expires_at < now()
                  AND attempts >= max_attempts
                """
            )
            cursor.execute(
                """
                WITH candidate AS (
                    SELECT id FROM content_generation_jobs
                    WHERE attempts < max_attempts
                      AND (
                          status = 'queued'
                          OR (status = 'running' AND lease_expires_at < now())
                      )
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE content_generation_jobs AS job
                SET status = 'running', attempts = job.attempts + 1,
                    lease_owner = %s, lease_expires_at = %s,
                    started_at = COALESCE(started_at, now()), updated_at = now(),
                    error_code = NULL, error_message = NULL
                FROM candidate
                WHERE job.id = candidate.id
                RETURNING job.*
                """,
                (worker_id, expires_at),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row) if row else None

    def renew_job(self, job_id: UUID, worker_id: str, *, lease_seconds: int = 300) -> bool:
        expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE content_generation_jobs
                SET lease_expires_at = %s, updated_at = now()
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                  AND lease_expires_at > now()
                """,
                (expires_at, job_id, worker_id),
            )
            renewed = cursor.rowcount == 1
        self.connection.commit()
        return renewed

    def mark_item_running(self, item_id: UUID, *, job_id: UUID, worker_id: str) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE content_generation_job_items AS item
                SET status = 'running', attempts = item.attempts + 1,
                    started_at = now(), updated_at = now(), error_code = NULL, error_message = NULL
                FROM content_generation_jobs AS job
                WHERE item.id = %s AND item.job_id = %s AND job.id = item.job_id
                  AND job.status = 'running' AND job.lease_owner = %s
                  AND job.lease_expires_at > now()
                  AND item.status IN ('queued', 'failed', 'running')
                """,
                (item_id, job_id, worker_id),
            )
            updated = cursor.rowcount == 1
        self.connection.commit()
        return updated

    def complete_item(
        self,
        item_id: UUID,
        *,
        job_id: UUID,
        worker_id: str,
        output_payload: dict[str, Any],
        evidence_ref: str | None,
    ) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE content_generation_job_items AS item
                SET status = 'succeeded', output_payload = %s,
                    invocation_evidence_ref = %s, finished_at = now(), updated_at = now()
                FROM content_generation_jobs AS job
                WHERE item.id = %s AND item.job_id = %s AND job.id = item.job_id
                  AND job.status = 'running' AND job.lease_owner = %s
                  AND job.lease_expires_at > now() AND item.status = 'running'
                """,
                (Jsonb(output_payload), evidence_ref, item_id, job_id, worker_id),
            )
            updated = cursor.rowcount == 1
            cursor.execute(
                """
                UPDATE content_generation_jobs AS job
                SET completed_items = (
                        SELECT count(*) FROM content_generation_job_items
                        WHERE job_id = job.id AND status = 'succeeded'
                    ), updated_at = now()
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                  AND lease_expires_at > now()
                """,
                (job_id, worker_id),
            )
        self.connection.commit()
        return updated

    def fail_item(
        self,
        item_id: UUID,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        error_message: str,
    ) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE content_generation_job_items AS item
                SET status = 'failed', error_code = %s, error_message = %s,
                    finished_at = now(), updated_at = now()
                FROM content_generation_jobs AS job
                WHERE item.id = %s AND item.job_id = %s AND job.id = item.job_id
                  AND job.status = 'running' AND job.lease_owner = %s
                  AND job.lease_expires_at > now() AND item.status = 'running'
                """,
                (error_code, error_message[:4000], item_id, job_id, worker_id),
            )
            updated = cursor.rowcount == 1
        self.connection.commit()
        return updated

    def complete_job(
        self, job_id: UUID, *, worker_id: str, result_refs: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE content_generation_jobs
                SET status = 'succeeded', completed_items = total_items,
                    result_refs = %s, lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = now(), updated_at = now()
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                  AND lease_expires_at > now()
                RETURNING *
                """,
                (Jsonb(result_refs), job_id, worker_id),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row) if row else None

    def fail_job(
        self, job_id: UUID, *, worker_id: str, error_code: str, error_message: str
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE content_generation_jobs
                SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                    error_code = %s, error_message = %s,
                    lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = CASE WHEN attempts < max_attempts THEN NULL ELSE now() END,
                    updated_at = now()
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                  AND lease_expires_at > now()
                RETURNING *
                """,
                (error_code, error_message[:4000], job_id, worker_id),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row) if row else None

    def retry_job(self, job_code: str) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE content_generation_jobs
                SET status = 'queued', attempts = 0, error_code = NULL, error_message = NULL,
                    lease_owner = NULL, lease_expires_at = NULL, finished_at = NULL, updated_at = now()
                WHERE job_code = %s AND status = 'failed'
                RETURNING *
                """,
                (job_code,),
            )
            row = cursor.fetchone()
            if row is not None:
                cursor.execute(
                    """
                    UPDATE content_generation_job_items
                    SET status = 'queued', error_code = NULL, error_message = NULL,
                        started_at = NULL, finished_at = NULL, updated_at = now()
                    WHERE job_id = %s AND status = 'failed'
                    """,
                    (row["id"],),
                )
        if row is None:
            self.connection.rollback()
            raise DomainConflictError("GENERATION_JOB_RETRY_NOT_ALLOWED", "Only a failed job can be retried")
        self.connection.commit()
        return dict(row)

    def stale_active_jobs(self, project_id: UUID, *, stages: list[str]) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE content_generation_jobs
                SET status = 'stale', error_code = 'INPUT_SUPERSEDED',
                    error_message = 'The workflow input changed', finished_at = now(), updated_at = now(),
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE project_id = %s AND stage = ANY(%s) AND status IN ('queued', 'running')
                """,
                (project_id, stages),
            )
        self.connection.commit()

    def supersede_storyboards(self, project_code: str, *, reason: str, actor_id: str) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE functional_live_room_plans
                SET review_status = 'superseded', superseded_at = now(), updated_at = now(),
                    revision_context = revision_context || %s
                WHERE project_code = %s
                  AND revision_context ->> 'workflow_version' = 'guided-live.v1'
                  AND review_status IN ('draft', 'confirmed')
                """,
                (
                    Jsonb(
                        {
                            "invalidated_reason": reason,
                            "invalidated_by": actor_id,
                            "invalidated_at": datetime.now(UTC).isoformat(),
                        }
                    ),
                    project_code,
                ),
            )
        self.connection.commit()

    def latest_storyboard(self, project_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM functional_live_room_plans
                WHERE project_code = %s
                  AND revision_context ->> 'workflow_version' = 'guided-live.v1'
                ORDER BY created_at DESC LIMIT 1
                """,
                (project_code,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def storyboard_by_creation_key(
        self, project_code: str, creation_key: str
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM functional_live_room_plans
                WHERE project_code = %s AND creation_idempotency_key = %s
                """,
                (project_code, creation_key),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def generated_program(
        self, project_id: UUID, strategy_revision: str
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM content_program_revisions
                WHERE project_id = %s AND producer_strategy_revision = %s
                ORDER BY revision_number DESC LIMIT 1
                """,
                (project_id, strategy_revision),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            result = dict(row)
            cursor.execute(
                "SELECT * FROM program_segments WHERE program_revision_id = %s ORDER BY sort_order",
                (row["id"],),
            )
            result["segments"] = [dict(item) for item in cursor.fetchall()]
        return result

    def generated_shot_list(
        self, project_id: UUID, strategy_revision: str
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM shot_list_revisions
                WHERE project_id = %s AND producer_strategy_revision = %s
                ORDER BY revision_number DESC LIMIT 1
                """,
                (project_id, strategy_revision),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            result = dict(row)
            cursor.execute(
                "SELECT * FROM shots WHERE shot_list_revision_id = %s ORDER BY sort_order",
                (row["id"],),
            )
            result["shots"] = [dict(item) for item in cursor.fetchall()]
        return result

    def mark_storyboard_draft(
        self, plan_code: str, *, context: dict[str, Any]
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT project_code FROM functional_live_room_plans WHERE plan_code = %s FOR UPDATE",
                (plan_code,),
            )
            target = cursor.fetchone()
            if target is None:
                self.connection.rollback()
                raise KeyError(plan_code)
            cursor.execute(
                """
                UPDATE functional_live_room_plans
                SET review_status = 'superseded', superseded_at = now(), updated_at = now()
                WHERE project_code = %s AND plan_code <> %s
                  AND revision_context ->> 'workflow_version' = 'guided-live.v1'
                  AND review_status IN ('draft', 'confirmed')
                """,
                (target["project_code"], plan_code),
            )
            cursor.execute(
                """
                UPDATE functional_live_room_plans
                SET review_status = 'draft', confirmed_by = NULL, confirmed_at = NULL,
                    superseded_at = NULL, revision_context = revision_context || %s, updated_at = now()
                WHERE plan_code = %s
                RETURNING *
                """,
                (Jsonb(context), plan_code),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row)

    def confirm_storyboard(self, plan_code: str, *, project_code: str, actor_id: str) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_live_room_plans WHERE plan_code = %s FOR UPDATE",
                (plan_code,),
            )
            plan = cursor.fetchone()
            if plan is None:
                raise KeyError(plan_code)
            if plan["review_status"] == "confirmed":
                self.connection.rollback()
                return dict(plan)
            if plan["review_status"] != "draft" or plan["project_code"] != project_code:
                raise DomainConflictError(
                    "STORYBOARD_CONFIRM_NOT_ALLOWED", "Only the current project storyboard draft can be confirmed"
                )
            cursor.execute(
                """
                UPDATE functional_live_room_plans
                SET review_status = 'superseded', superseded_at = now(), updated_at = now()
                WHERE project_code = %s AND review_status = 'confirmed' AND plan_code <> %s
                """,
                (project_code, plan_code),
            )
            cursor.execute(
                """
                UPDATE functional_live_room_plans
                SET review_status = 'confirmed', confirmed_by = %s, confirmed_at = now(), updated_at = now()
                WHERE plan_code = %s RETURNING *
                """,
                (actor_id, plan_code),
            )
            confirmed = cursor.fetchone()
        self.connection.commit()
        return dict(confirmed)

    @staticmethod
    def _requirements(cursor: Any, script_revision_id: UUID) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT requirement.*, block.sort_order AS block_sort_order,
                   block.block_code, block.module_type
            FROM content_script_material_requirements AS requirement
            JOIN content_script_blocks AS block ON block.id = requirement.script_block_id
            WHERE requirement.script_revision_id = %s
            ORDER BY block.sort_order, requirement.sort_order
            """,
            (script_revision_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _codes(values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values if str(value).strip()]
        if len(normalized) != len(set(normalized)):
            raise DomainValidationError("DUPLICATE_CODE", "Selection codes must be unique")
        return normalized

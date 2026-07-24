from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainConflictError, DomainValidationError


_BRANCH_KINDS = {"live_room", "rendered_video"}
_SHOT_FORBIDDEN_KEYS = {
    "absolute_path",
    "file_path",
    "layer_index",
    "maitu_index",
    "maitu_sequence",
    "material_index",
    "path",
    "relative_path",
    "scene_index",
    "url",
    "uri",
}


class ContentProductionRepository:
    """Transactional repository for StoryBrief through production branches."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def create_story_brief_revision(
        self,
        *,
        project_code: str,
        project_revision: int,
        expected_revision: int,
        source_design_brief_revision: str,
        content: dict[str, Any],
        fact_revision_refs: list[dict[str, Any]],
        template_revision_refs: list[dict[str, Any]],
        actor_id: str,
        producer_role: str = "content_strategist",
        producer_strategy_revision: str = "system_baseline.v1",
    ) -> dict[str, Any]:
        if not source_design_brief_revision.strip():
            raise DomainValidationError(
                "STORY_BRIEF_DESIGN_SOURCE_REQUIRED",
                "StoryBrief requires a fixed DesignBrief revision",
            )
        input_payload = {
            "project_code": project_code,
            "project_revision": project_revision,
            "source_design_brief_revision": source_design_brief_revision,
            "content": content,
            "fact_revision_refs": fact_revision_refs,
            "template_revision_refs": template_revision_refs,
            "producer_role": producer_role,
            "producer_strategy_revision": producer_strategy_revision,
        }
        fingerprint = canonical_fingerprint(input_payload)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            project_revision_row = self._confirmed_project_revision(cursor, project_code, project_revision)
            cursor.execute(
                "SELECT * FROM story_briefs WHERE project_id = %s FOR UPDATE",
                (project_revision_row["project_id"],),
            )
            identity = cursor.fetchone()
            if identity is None:
                if expected_revision != 0:
                    self._revision_conflict(expected_revision, 0)
                story_brief_code = self._next_code(cursor, "STORY", "story_brief")
                cursor.execute(
                    """
                    INSERT INTO story_briefs (
                        story_brief_code, project_id, project_code, current_revision_number
                    ) VALUES (%s, %s, %s, 0)
                    RETURNING *
                    """,
                    (story_brief_code, project_revision_row["project_id"], project_code),
                )
                identity = cursor.fetchone()
            current_revision = int(identity["current_revision_number"])
            if current_revision != expected_revision:
                self._revision_conflict(expected_revision, current_revision)
            next_revision = current_revision + 1
            cursor.execute(
                """
                INSERT INTO story_brief_revisions (
                    story_brief_id, story_brief_code, revision_number,
                    source_project_revision_id, source_design_brief_revision,
                    content, fact_revision_refs, template_revision_refs,
                    producer_role, producer_strategy_revision, input_fingerprint,
                    fingerprint_sha256, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    identity["id"],
                    identity["story_brief_code"],
                    next_revision,
                    project_revision_row["id"],
                    source_design_brief_revision,
                    Jsonb(content),
                    Jsonb(fact_revision_refs),
                    Jsonb(template_revision_refs),
                    producer_role,
                    producer_strategy_revision,
                    fingerprint,
                    fingerprint,
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
            cursor.execute(
                "UPDATE story_briefs SET current_revision_number = %s, updated_at = now() WHERE id = %s",
                (next_revision, identity["id"]),
            )
            self._insert_derivation(
                cursor,
                source=("content_project", project_code, project_revision),
                target=("story_brief", identity["story_brief_code"], next_revision),
                producer_role=producer_role,
                producer_strategy_revision=producer_strategy_revision,
                input_fingerprint=project_revision_row["fingerprint_sha256"],
                output_fingerprint=fingerprint,
            )
        self.connection.commit()
        return self._serialize(revision)

    def confirm_story_brief_revision(
        self, story_brief_code: str, *, revision_number: int, actor_id: str
    ) -> dict[str, Any]:
        return self._confirm_revision(
            table="story_brief_revisions",
            code_column="story_brief_code",
            code=story_brief_code,
            revision_number=revision_number,
            group_column="story_brief_id",
            object_type="story_brief",
            stable_code=story_brief_code,
            actor_id=actor_id,
            identity_table="story_briefs",
        )

    def create_script_revision(
        self,
        *,
        story_brief_code: str,
        story_brief_revision: int,
        expected_revision: int,
        title: str,
        content: dict[str, Any],
        blocks: list[dict[str, Any]],
        model_strategy_ref: str,
        prompt_revision: str,
        producer_strategy_revision: str,
        actor_id: str,
        generation_run_code: str | None = None,
        validation_result: dict[str, Any] | None = None,
        producer_role: str = "writer",
    ) -> dict[str, Any]:
        if not title.strip() or not blocks:
            raise DomainValidationError(
                "SCRIPT_CONTENT_REQUIRED",
                "Script title and at least one ScriptBlock are required",
            )
        payload = {
            "story_brief_code": story_brief_code,
            "story_brief_revision": story_brief_revision,
            "title": title,
            "content": content,
            "blocks": blocks,
            "model_strategy_ref": model_strategy_ref,
            "prompt_revision": prompt_revision,
            "producer_role": producer_role,
            "producer_strategy_revision": producer_strategy_revision,
            "generation_run_code": generation_run_code,
        }
        fingerprint = canonical_fingerprint(payload)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            source = self._confirmed_story_brief(cursor, story_brief_code, story_brief_revision)
            project_code = self._project_code(cursor, source["project_id"])
            current_revision = self._current_project_scoped_revision(
                cursor, "content_script_revisions", source["project_id"]
            )
            if current_revision != expected_revision:
                self._revision_conflict(expected_revision, current_revision)
            next_revision = current_revision + 1
            script_revision_code = self._next_code(cursor, "SCRIPT", "content_script_revision")
            cursor.execute(
                """
                INSERT INTO content_script_revisions (
                    script_revision_code, project_id, source_story_brief_revision_id,
                    revision_number, title, content, model_strategy_ref, prompt_revision,
                    producer_role, producer_strategy_revision, fingerprint_sha256,
                    generation_run_code, validation_result, source_revision_refs, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    script_revision_code,
                    source["project_id"],
                    source["id"],
                    next_revision,
                    title.strip(),
                    Jsonb(content),
                    model_strategy_ref,
                    prompt_revision,
                    producer_role,
                    producer_strategy_revision,
                    fingerprint,
                    generation_run_code,
                    Jsonb(validation_result or {}),
                    Jsonb(
                        [
                            {
                                "object_type": "story_brief",
                                "code": story_brief_code,
                                "revision": story_brief_revision,
                            }
                        ]
                    ),
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
            stored_blocks: list[dict[str, Any]] = []
            for sort_order, block in enumerate(blocks):
                block_content = str(block.get("content") or "").strip()
                if not block_content:
                    raise DomainValidationError("SCRIPT_BLOCK_CONTENT_REQUIRED", "ScriptBlock content is required")
                block_payload = {
                    "sort_order": sort_order,
                    "module_type": block.get("module_type", "body"),
                    "content": block_content,
                    "estimated_duration_ms": block.get("estimated_duration_ms"),
                    "product_ref": block.get("product_ref"),
                    "fact_citations": block.get("fact_citations") or [],
                    "template_sources": block.get("template_sources") or [],
                    "interaction_intent": block.get("interaction_intent") or {},
                    "cta_intent": block.get("cta_intent") or {},
                }
                block_code = self._next_code(cursor, "BLOCK", "content_script_block")
                cursor.execute(
                    """
                    INSERT INTO content_script_blocks (
                        block_code, script_revision_id, sort_order, module_type,
                        content, estimated_duration_ms, product_ref, fact_citations,
                        template_sources, fingerprint_sha256, interaction_intent, cta_intent
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        block_code,
                        revision["id"],
                        sort_order,
                        block_payload["module_type"],
                        block_content,
                        block_payload["estimated_duration_ms"],
                        block_payload["product_ref"],
                        Jsonb(block_payload["fact_citations"]),
                        Jsonb(block_payload["template_sources"]),
                        canonical_fingerprint(block_payload),
                        Jsonb(block_payload["interaction_intent"]),
                        Jsonb(block_payload["cta_intent"]),
                    ),
                )
                stored_blocks.append(self._serialize(cursor.fetchone()))
            self._insert_derivation(
                cursor,
                source=("story_brief", story_brief_code, story_brief_revision),
                target=("content_script", project_code, next_revision),
                producer_role=producer_role,
                producer_strategy_revision=producer_strategy_revision,
                input_fingerprint=source["fingerprint_sha256"],
                output_fingerprint=fingerprint,
            )
        self.connection.commit()
        return {**self._serialize(revision), "project_code": project_code, "blocks": stored_blocks}

    def confirm_script_revision(
        self, script_revision_code: str, *, revision_number: int, actor_id: str
    ) -> dict[str, Any]:
        project_code = self._stable_project_code(
            table="content_script_revisions", code_column="script_revision_code", code=script_revision_code
        )
        return self._confirm_revision(
            table="content_script_revisions",
            code_column="script_revision_code",
            code=script_revision_code,
            revision_number=revision_number,
            group_column="project_id",
            object_type="content_script",
            stable_code=project_code,
            actor_id=actor_id,
        )

    def create_program_revision(
        self,
        *,
        script_revision_code: str,
        expected_revision: int,
        segments: list[dict[str, Any]],
        producer_strategy_revision: str,
        actor_id: str,
        producer_role: str = "director",
    ) -> dict[str, Any]:
        if not segments:
            raise DomainValidationError("PROGRAM_SEGMENTS_REQUIRED", "A content program requires segments")
        fingerprint = canonical_fingerprint(
            {
                "script_revision_code": script_revision_code,
                "segments": segments,
                "producer_role": producer_role,
                "producer_strategy_revision": producer_strategy_revision,
            }
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            script = self._confirmed_revision_by_code(cursor, "content_script_revisions", "script_revision_code", script_revision_code)
            project_code = self._project_code(cursor, script["project_id"])
            current_revision = self._current_project_scoped_revision(
                cursor, "content_program_revisions", script["project_id"]
            )
            if current_revision != expected_revision:
                self._revision_conflict(expected_revision, current_revision)
            cursor.execute(
                "SELECT * FROM content_script_blocks WHERE script_revision_id = %s ORDER BY sort_order",
                (script["id"],),
            )
            blocks = {row["block_code"]: row for row in cursor.fetchall()}
            next_revision = current_revision + 1
            program_revision_code = self._next_code(cursor, "PROGRAM", "content_program_revision")
            cursor.execute(
                """
                INSERT INTO content_program_revisions (
                    program_revision_code, project_id, source_script_revision_id,
                    revision_number, producer_role, producer_strategy_revision,
                    fingerprint_sha256, source_revision_refs, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    program_revision_code,
                    script["project_id"],
                    script["id"],
                    next_revision,
                    producer_role,
                    producer_strategy_revision,
                    fingerprint,
                    Jsonb(
                        [
                            {
                                "object_type": "content_script",
                                "code": project_code,
                                "revision": script["revision_number"],
                            }
                        ]
                    ),
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
            stored_segments: list[dict[str, Any]] = []
            for sort_order, segment in enumerate(segments):
                adoptions = segment.get("script_block_adoptions") or []
                if not adoptions:
                    raise DomainValidationError(
                        "PROGRAM_SEGMENT_SOURCE_REQUIRED",
                        "Every ProgramSegment requires at least one ScriptBlock adoption",
                    )
                adopted_blocks = []
                for adoption in adoptions:
                    block_code = adoption.get("block_code")
                    if block_code not in blocks:
                        raise DomainValidationError(
                            "PROGRAM_SEGMENT_BLOCK_INVALID",
                            "ProgramSegment references a ScriptBlock outside its source revision",
                            details={"block_code": block_code},
                        )
                    adopted_blocks.append(blocks[block_code])
                segment_payload = {
                    "sort_order": sort_order,
                    "semantic_goal": segment.get("semantic_goal"),
                    "entry_condition": segment.get("entry_condition"),
                    "exit_condition": segment.get("exit_condition"),
                    "program_phase": segment.get("program_phase", "body"),
                    "estimated_duration_ms": segment.get("estimated_duration_ms"),
                    "product_refs": segment.get("product_refs") or [],
                    "interaction_actions": segment.get("interaction_actions") or [],
                    "cta_actions": segment.get("cta_actions") or [],
                    "branch_applicability": self._branches(segment.get("branch_applicability")),
                    "metadata": segment.get("metadata") or {},
                    "script_block_adoptions": adoptions,
                }
                if not str(segment_payload["semantic_goal"] or "").strip():
                    raise DomainValidationError("PROGRAM_SEGMENT_GOAL_REQUIRED", "ProgramSegment goal is required")
                segment_code = self._next_code(cursor, "SEGMENT", "program_segment")
                cursor.execute(
                    """
                    INSERT INTO program_segments (
                        segment_code, program_revision_id, sort_order, semantic_goal,
                        entry_condition, exit_condition, script_block_start, script_block_end,
                        metadata, fingerprint_sha256, program_phase, estimated_duration_ms,
                        product_refs, interaction_actions, cta_actions, branch_applicability
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        segment_code,
                        revision["id"],
                        sort_order,
                        str(segment_payload["semantic_goal"]).strip(),
                        segment_payload["entry_condition"],
                        segment_payload["exit_condition"],
                        min(int(block["sort_order"]) for block in adopted_blocks),
                        max(int(block["sort_order"]) for block in adopted_blocks) + 1,
                        Jsonb(segment_payload["metadata"]),
                        canonical_fingerprint(segment_payload),
                        segment_payload["program_phase"],
                        segment_payload["estimated_duration_ms"],
                        Jsonb(segment_payload["product_refs"]),
                        Jsonb(segment_payload["interaction_actions"]),
                        Jsonb(segment_payload["cta_actions"]),
                        Jsonb(segment_payload["branch_applicability"]),
                    ),
                )
                stored_segment = cursor.fetchone()
                for adoption_order, adoption in enumerate(adoptions):
                    cursor.execute(
                        """
                        INSERT INTO program_segment_script_block_adoptions (
                            segment_id, script_block_id, adoption_order,
                            content_start_offset, content_end_offset, content_action, evidence
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            stored_segment["id"],
                            blocks[adoption["block_code"]]["id"],
                            adoption_order,
                            adoption.get("content_start_offset"),
                            adoption.get("content_end_offset"),
                            adoption.get("content_action", "deliver"),
                            Jsonb(adoption.get("evidence") or {}),
                        ),
                    )
                stored_segments.append(self._serialize(stored_segment))
            self._insert_derivation(
                cursor,
                source=("content_script", project_code, int(script["revision_number"])),
                target=("content_program", project_code, next_revision),
                producer_role=producer_role,
                producer_strategy_revision=producer_strategy_revision,
                input_fingerprint=script["fingerprint_sha256"],
                output_fingerprint=fingerprint,
            )
        self.connection.commit()
        return {**self._serialize(revision), "project_code": project_code, "segments": stored_segments}

    def confirm_program_revision(
        self, program_revision_code: str, *, revision_number: int, actor_id: str
    ) -> dict[str, Any]:
        project_code = self._stable_project_code(
            table="content_program_revisions", code_column="program_revision_code", code=program_revision_code
        )
        return self._confirm_revision(
            table="content_program_revisions",
            code_column="program_revision_code",
            code=program_revision_code,
            revision_number=revision_number,
            group_column="project_id",
            object_type="content_program",
            stable_code=project_code,
            actor_id=actor_id,
        )

    def create_shot_list_revision(
        self,
        *,
        program_revision_code: str,
        expected_revision: int,
        shots: list[dict[str, Any]],
        producer_strategy_revision: str,
        actor_id: str,
        producer_role: str = "director",
    ) -> dict[str, Any]:
        if not shots:
            raise DomainValidationError("SHOT_LIST_REQUIRED", "A ShotList requires at least one Shot")
        self._reject_shot_runtime_locators(shots)
        fingerprint = canonical_fingerprint(
            {
                "program_revision_code": program_revision_code,
                "shots": shots,
                "producer_role": producer_role,
                "producer_strategy_revision": producer_strategy_revision,
            }
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            program = self._confirmed_revision_by_code(
                cursor, "content_program_revisions", "program_revision_code", program_revision_code
            )
            project_code = self._project_code(cursor, program["project_id"])
            current_revision = self._current_project_scoped_revision(
                cursor, "shot_list_revisions", program["project_id"]
            )
            if current_revision != expected_revision:
                self._revision_conflict(expected_revision, current_revision)
            cursor.execute(
                "SELECT * FROM program_segments WHERE program_revision_id = %s",
                (program["id"],),
            )
            segments = {row["segment_code"]: row for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT adoption.segment_id, block.*
                FROM program_segment_script_block_adoptions AS adoption
                JOIN content_script_blocks AS block ON block.id = adoption.script_block_id
                WHERE adoption.segment_id = ANY(%s)
                """,
                ([row["id"] for row in segments.values()],),
            )
            adopted_by_segment: dict[UUID, dict[str, dict[str, Any]]] = {}
            for row in cursor.fetchall():
                adopted_by_segment.setdefault(row["segment_id"], {})[row["block_code"]] = row
            next_revision = current_revision + 1
            shot_list_revision_code = self._next_code(cursor, "SHOTLIST", "shot_list_revision")
            cursor.execute(
                """
                INSERT INTO shot_list_revisions (
                    shot_list_revision_code, project_id, source_program_revision_id,
                    revision_number, producer_role, producer_strategy_revision,
                    fingerprint_sha256, source_revision_refs, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    shot_list_revision_code,
                    program["project_id"],
                    program["id"],
                    next_revision,
                    producer_role,
                    producer_strategy_revision,
                    fingerprint,
                    Jsonb(
                        [
                            {
                                "object_type": "content_program",
                                "code": project_code,
                                "revision": program["revision_number"],
                            }
                        ]
                    ),
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
            stored_shots: list[dict[str, Any]] = []
            for sort_order, shot in enumerate(shots):
                segment_code = shot.get("program_segment_code")
                segment = segments.get(segment_code)
                if segment is None:
                    raise DomainValidationError(
                        "SHOT_SEGMENT_INVALID",
                        "Shot references a ProgramSegment outside the source revision",
                    )
                sources = shot.get("script_block_sources") or []
                if not sources:
                    raise DomainValidationError("SHOT_SCRIPT_SOURCE_REQUIRED", "Shot requires ScriptBlock sources")
                adopted = adopted_by_segment.get(segment["id"], {})
                for source in sources:
                    if source.get("block_code") not in adopted:
                        raise DomainValidationError(
                            "SHOT_SCRIPT_SOURCE_INVALID",
                            "Shot ScriptBlock source must be adopted by its ProgramSegment",
                        )
                shot_payload = {
                    "program_segment_code": segment_code,
                    "shot_goal": shot.get("shot_goal"),
                    "composition_intent": shot.get("composition_intent") or {},
                    "material_role_requirements": shot.get("material_role_requirements") or [],
                    "audio_actions": shot.get("audio_actions") or [],
                    "continuity": shot.get("continuity") or {},
                    "acceptance_criteria": shot.get("acceptance_criteria") or [],
                    "estimated_duration_ms": shot.get("estimated_duration_ms"),
                    "branch_applicability": self._branches(shot.get("branch_applicability")),
                    "must_include": shot.get("must_include") or [],
                    "must_avoid": shot.get("must_avoid") or [],
                    "script_block_sources": sources,
                }
                if not str(shot_payload["shot_goal"] or "").strip():
                    raise DomainValidationError("SHOT_GOAL_REQUIRED", "Shot goal is required")
                shot_code = self._next_code(cursor, "SHOT", "shot")
                cursor.execute(
                    """
                    INSERT INTO shots (
                        shot_code, shot_list_revision_id, program_segment_id, sort_order,
                        composition_intent, material_role_requirements, audio_actions,
                        continuity, acceptance_criteria, estimated_duration_ms,
                        fingerprint_sha256, shot_goal, branch_applicability,
                        must_include, must_avoid
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        shot_code,
                        revision["id"],
                        segment["id"],
                        sort_order,
                        Jsonb(shot_payload["composition_intent"]),
                        Jsonb(shot_payload["material_role_requirements"]),
                        Jsonb(shot_payload["audio_actions"]),
                        Jsonb(shot_payload["continuity"]),
                        Jsonb(shot_payload["acceptance_criteria"]),
                        shot_payload["estimated_duration_ms"],
                        canonical_fingerprint(shot_payload),
                        str(shot_payload["shot_goal"]).strip(),
                        Jsonb(shot_payload["branch_applicability"]),
                        Jsonb(shot_payload["must_include"]),
                        Jsonb(shot_payload["must_avoid"]),
                    ),
                )
                stored_shot = cursor.fetchone()
                for source_order, source in enumerate(sources):
                    cursor.execute(
                        """
                        INSERT INTO shot_script_block_sources (
                            shot_id, script_block_id, source_order, content_start_offset,
                            content_end_offset, relation_type
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            stored_shot["id"],
                            adopted[source["block_code"]]["id"],
                            source_order,
                            source.get("content_start_offset"),
                            source.get("content_end_offset"),
                            source.get("relation_type", "derived_from"),
                        ),
                    )
                stored_shots.append(self._serialize(stored_shot))
            self._insert_derivation(
                cursor,
                source=("content_program", project_code, int(program["revision_number"])),
                target=("shot_list", project_code, next_revision),
                producer_role=producer_role,
                producer_strategy_revision=producer_strategy_revision,
                input_fingerprint=program["fingerprint_sha256"],
                output_fingerprint=fingerprint,
            )
        self.connection.commit()
        return {**self._serialize(revision), "project_code": project_code, "shots": stored_shots}

    def confirm_shot_list_revision(
        self, shot_list_revision_code: str, *, revision_number: int, actor_id: str
    ) -> dict[str, Any]:
        project_code = self._stable_project_code(
            table="shot_list_revisions", code_column="shot_list_revision_code", code=shot_list_revision_code
        )
        return self._confirm_revision(
            table="shot_list_revisions",
            code_column="shot_list_revision_code",
            code=shot_list_revision_code,
            revision_number=revision_number,
            group_column="project_id",
            object_type="shot_list",
            stable_code=project_code,
            actor_id=actor_id,
        )

    def add_shot_projection_link(
        self,
        *,
        shot_code: str,
        target_type: str,
        target_code: str,
        target_revision: int,
        relation_type: str,
        applicable_start_ms: int | None = None,
        applicable_end_ms: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM shots WHERE shot_code = %s", (shot_code,))
            shot = cursor.fetchone()
            if shot is None:
                raise KeyError(shot_code)
            cursor.execute(
                """
                INSERT INTO shot_projection_links (
                    shot_id, target_type, target_code, target_revision, relation_type,
                    applicable_start_ms, applicable_end_ms, evidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    shot["id"],
                    target_type,
                    target_code,
                    target_revision,
                    relation_type,
                    applicable_start_ms,
                    applicable_end_ms,
                    Jsonb(evidence or {}),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def create_production_variant(
        self,
        *,
        project_code: str,
        project_revision: int,
        story_brief_code: str,
        story_brief_revision: int,
        script_revision_code: str,
        shot_list_revision_code: str,
        carrier_kind: str,
        branch_target: dict[str, Any],
        configuration: dict[str, Any],
        material_snapshot_ref: dict[str, Any],
        constraint_snapshot_ref: dict[str, Any],
        actor_id: str,
        producer_strategy_revision: str = "system_baseline.v1",
    ) -> dict[str, Any]:
        if carrier_kind not in _BRANCH_KINDS:
            raise DomainValidationError("VARIANT_KIND_INVALID", "Unsupported ProductionVariant kind")
        expected_delivery_type = "live_room_draft" if carrier_kind == "live_room" else "rendered_video"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            project = self._confirmed_project_revision(cursor, project_code, project_revision)
            story = self._confirmed_story_brief(cursor, story_brief_code, story_brief_revision)
            script = self._confirmed_revision_by_code(
                cursor, "content_script_revisions", "script_revision_code", script_revision_code
            )
            shot_list = self._confirmed_revision_by_code(
                cursor, "shot_list_revisions", "shot_list_revision_code", shot_list_revision_code
            )
            if {project["project_id"], story["project_id"], script["project_id"], shot_list["project_id"]} != {
                project["project_id"]
            }:
                raise DomainValidationError(
                    "VARIANT_CONTENT_PROJECT_MISMATCH",
                    "ProductionVariant sources must belong to one ContentProject",
                )
            if script["source_story_brief_revision_id"] != story["id"]:
                raise DomainValidationError("VARIANT_CONTENT_CHAIN_INVALID", "Script does not derive from StoryBrief")
            variant_code = self._next_code(cursor, "VARIANT", "production_variant")
            payload = {
                "variant_code": variant_code,
                "project_code": project_code,
                "project_revision": project_revision,
                "story_brief": [story_brief_code, story_brief_revision],
                "script_revision_code": script_revision_code,
                "shot_list_revision_code": shot_list_revision_code,
                "carrier_kind": carrier_kind,
                "branch_target": branch_target,
                "configuration": configuration,
                "material_snapshot_ref": material_snapshot_ref,
                "constraint_snapshot_ref": constraint_snapshot_ref,
                "expected_delivery_type": expected_delivery_type,
                "producer_strategy_revision": producer_strategy_revision,
            }
            fingerprint = canonical_fingerprint(payload)
            cursor.execute(
                """
                INSERT INTO production_variants (
                    variant_code, project_id, project_code, carrier_kind, current_revision_number
                ) VALUES (%s, %s, %s, %s, 1)
                RETURNING *
                """,
                (variant_code, project["project_id"], project_code, carrier_kind),
            )
            identity = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO production_variant_revisions (
                    variant_id, variant_code, revision_number, carrier_kind,
                    source_project_revision_id, source_story_brief_revision_id,
                    source_script_revision_id, source_shot_list_revision_id,
                    configuration, source_revision_refs, fingerprint_sha256,
                    branch_target, material_snapshot_ref, constraint_snapshot_ref,
                    expected_delivery_type, producer_role, producer_strategy_revision,
                    source_quality, created_by
                ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          'producer', %s, 'verified', %s)
                RETURNING *
                """,
                (
                    identity["id"],
                    variant_code,
                    carrier_kind,
                    project["id"],
                    story["id"],
                    script["id"],
                    shot_list["id"],
                    Jsonb(configuration),
                    Jsonb(
                        [
                            {"object_type": "content_project", "code": project_code, "revision": project_revision},
                            {"object_type": "story_brief", "code": story_brief_code, "revision": story_brief_revision},
                            {"object_type": "content_script", "code": project_code, "revision": script["revision_number"]},
                            {"object_type": "shot_list", "code": project_code, "revision": shot_list["revision_number"]},
                        ]
                    ),
                    fingerprint,
                    Jsonb(branch_target),
                    Jsonb(material_snapshot_ref),
                    Jsonb(constraint_snapshot_ref),
                    expected_delivery_type,
                    producer_strategy_revision,
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
            self._insert_derivation(
                cursor,
                source=("shot_list", project_code, int(shot_list["revision_number"])),
                target=("production_variant", variant_code, 1),
                producer_role="producer",
                producer_strategy_revision=producer_strategy_revision,
                input_fingerprint=shot_list["fingerprint_sha256"],
                output_fingerprint=fingerprint,
            )
        self.connection.commit()
        return self._serialize(revision)

    def confirm_production_variant_revision(
        self, variant_code: str, *, revision_number: int, actor_id: str
    ) -> dict[str, Any]:
        return self._confirm_revision(
            table="production_variant_revisions",
            code_column="variant_code",
            code=variant_code,
            revision_number=revision_number,
            group_column="variant_id",
            object_type="production_variant",
            stable_code=variant_code,
            actor_id=actor_id,
            identity_table="production_variants",
        )

    def create_live_room_configuration_revision(
        self,
        *,
        variant_code: str,
        variant_revision: int,
        expected_revision: int,
        target_live_room_id: str,
        expected_title: str,
        build_mode: str,
        inventory_snapshot_ref: dict[str, Any],
        site_protection_policy: dict[str, Any],
        configuration: dict[str, Any],
        actor_id: str,
        source_workbench_run_code: str | None = None,
    ) -> dict[str, Any]:
        if not target_live_room_id.strip() or not expected_title.strip():
            raise DomainValidationError(
                "LIVE_ROOM_CONFIGURATION_REQUIRED_FIELD",
                "Target live room ID and expected title are required",
            )
        payload = {
            "variant_code": variant_code,
            "variant_revision": variant_revision,
            "target_live_room_id": target_live_room_id,
            "expected_title": expected_title,
            "build_mode": build_mode,
            "inventory_snapshot_ref": inventory_snapshot_ref,
            "site_protection_policy": site_protection_policy,
            "configuration": configuration,
            "source_workbench_run_code": source_workbench_run_code,
        }
        fingerprint = canonical_fingerprint(payload)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.*, variant.id AS identity_id
                FROM production_variant_revisions AS revision
                JOIN production_variants AS variant ON variant.id = revision.variant_id
                WHERE revision.variant_code = %s AND revision.revision_number = %s
                  AND revision.status = 'confirmed'
                FOR SHARE OF revision
                """,
                (variant_code, variant_revision),
            )
            variant = cursor.fetchone()
            if variant is None:
                raise DomainValidationError("LIVE_ROOM_VARIANT_NOT_CONFIRMED", "Live-room variant must be confirmed")
            if variant["carrier_kind"] != "live_room":
                raise DomainValidationError("LIVE_ROOM_VARIANT_KIND_INVALID", "Variant is not a live-room branch")
            cursor.execute(
                "SELECT * FROM live_room_configurations WHERE variant_id = %s FOR UPDATE",
                (variant["variant_id"],),
            )
            identity = cursor.fetchone()
            if identity is None:
                if expected_revision != 0:
                    self._revision_conflict(expected_revision, 0)
                configuration_code = self._next_code(cursor, "ROOMCFG", "live_room_configuration")
                cursor.execute(
                    """
                    INSERT INTO live_room_configurations (
                        configuration_code, variant_id, variant_code, current_revision_number
                    ) VALUES (%s, %s, %s, 0)
                    RETURNING *
                    """,
                    (configuration_code, variant["variant_id"], variant_code),
                )
                identity = cursor.fetchone()
            current_revision = int(identity["current_revision_number"])
            if current_revision != expected_revision:
                self._revision_conflict(expected_revision, current_revision)
            next_revision = current_revision + 1
            cursor.execute(
                """
                INSERT INTO live_room_configuration_revisions (
                    configuration_id, configuration_code, revision_number,
                    production_variant_revision_id, target_live_room_id, expected_title,
                    build_mode, inventory_snapshot_ref, site_protection_policy,
                    configuration, source_workbench_run_code, fingerprint_sha256, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    identity["id"],
                    identity["configuration_code"],
                    next_revision,
                    variant["id"],
                    target_live_room_id.strip(),
                    expected_title.strip(),
                    build_mode,
                    Jsonb(inventory_snapshot_ref),
                    Jsonb(site_protection_policy),
                    Jsonb(configuration),
                    source_workbench_run_code,
                    fingerprint,
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
            cursor.execute(
                "UPDATE live_room_configurations SET current_revision_number = %s, updated_at = now() WHERE id = %s",
                (next_revision, identity["id"]),
            )
            self._insert_derivation(
                cursor,
                source=("production_variant", variant_code, variant_revision),
                target=("live_room_configuration", identity["configuration_code"], next_revision),
                producer_role="producer",
                producer_strategy_revision="system_baseline.v1",
                input_fingerprint=variant["fingerprint_sha256"],
                output_fingerprint=fingerprint,
            )
        self.connection.commit()
        return self._serialize(revision)

    def confirm_live_room_configuration_revision(
        self, configuration_code: str, *, revision_number: int, actor_id: str
    ) -> dict[str, Any]:
        return self._confirm_revision(
            table="live_room_configuration_revisions",
            code_column="configuration_code",
            code=configuration_code,
            revision_number=revision_number,
            group_column="configuration_id",
            object_type="live_room_configuration",
            stable_code=configuration_code,
            actor_id=actor_id,
            identity_table="live_room_configurations",
        )

    def bind_workbench_run(
        self,
        *,
        run_code: str,
        configuration_code: str,
        configuration_revision: int,
        actor_id: str,
        mapping_quality: str = "verified",
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM maitu_workbench_runs WHERE run_code = %s FOR UPDATE", (run_code,))
            run = cursor.fetchone()
            if run is None:
                raise KeyError(run_code)
            cursor.execute(
                """
                SELECT configuration.*, variant.variant_code, variant.id AS variant_revision_id
                FROM live_room_configuration_revisions AS configuration
                JOIN production_variant_revisions AS variant
                  ON variant.id = configuration.production_variant_revision_id
                WHERE configuration.configuration_code = %s
                  AND configuration.revision_number = %s
                  AND configuration.status = 'confirmed'
                """,
                (configuration_code, configuration_revision),
            )
            configuration = cursor.fetchone()
            if configuration is None:
                raise DomainValidationError(
                    "WORKBENCH_CONFIGURATION_NOT_CONFIRMED",
                    "WorkbenchRun can only map to a confirmed live-room configuration",
                )
            if run["target_live_room_id"] and run["target_live_room_id"] != configuration["target_live_room_id"]:
                raise DomainValidationError(
                    "WORKBENCH_TARGET_MISMATCH",
                    "WorkbenchRun target differs from the fixed configuration target",
                )
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET production_variant_revision_id = %s,
                    live_room_configuration_revision_id = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (configuration["variant_revision_id"], configuration["id"], run["id"]),
            )
            link = self._upsert_legacy_link(
                cursor,
                source_type="maitu_workbench_run",
                source_code=run_code,
                variant_revision_id=configuration["variant_revision_id"],
                configuration_revision_id=configuration["id"],
                mapping_quality=mapping_quality,
                source_snapshot={
                    "title": run["title"],
                    "topic": run["topic"],
                    "target_live_room_id": run["target_live_room_id"],
                    "legacy_status": run["status"],
                },
                actor_id=actor_id,
            )
        self.connection.commit()
        return self._serialize(link)

    def bind_video_production_job(
        self,
        *,
        job_code: str,
        variant_code: str,
        variant_revision: int,
        actor_id: str,
        mapping_quality: str = "verified",
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM video_production_jobs WHERE job_code = %s FOR UPDATE", (job_code,))
            job = cursor.fetchone()
            if job is None:
                raise KeyError(job_code)
            cursor.execute(
                """
                SELECT * FROM production_variant_revisions
                WHERE variant_code = %s AND revision_number = %s
                  AND carrier_kind = 'rendered_video' AND status = 'confirmed'
                """,
                (variant_code, variant_revision),
            )
            variant = cursor.fetchone()
            if variant is None:
                raise DomainValidationError(
                    "VIDEO_VARIANT_NOT_CONFIRMED",
                    "VideoProductionJob can only map to a confirmed rendered-video variant",
                )
            cursor.execute(
                "UPDATE video_production_jobs SET production_variant_revision_id = %s, updated_at = now() WHERE id = %s",
                (variant["id"], job["id"]),
            )
            link = self._upsert_legacy_link(
                cursor,
                source_type="video_production_job",
                source_code=job_code,
                variant_revision_id=variant["id"],
                configuration_revision_id=None,
                mapping_quality=mapping_quality,
                source_snapshot={
                    "topic": job["topic"],
                    "preset_code": job["preset_code"],
                    "target_duration_seconds": job["target_duration_seconds"],
                    "legacy_status": job["status"],
                },
                actor_id=actor_id,
            )
        self.connection.commit()
        return self._serialize(link)

    def _confirm_revision(
        self,
        *,
        table: str,
        code_column: str,
        code: str,
        revision_number: int,
        group_column: str,
        object_type: str,
        stable_code: str,
        actor_id: str,
        identity_table: str | None = None,
    ) -> dict[str, Any]:
        table_id = sql.Identifier(table)
        code_id = sql.Identifier(code_column)
        group_id = sql.Identifier(group_column)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                sql.SQL("SELECT * FROM {} WHERE {} = %s AND revision_number = %s FOR UPDATE").format(
                    table_id, code_id
                ),
                (code, revision_number),
            )
            revision = cursor.fetchone()
            if revision is None:
                raise KeyError(f"{code}@{revision_number}")
            if revision["status"] == "confirmed":
                self.connection.rollback()
                return self._serialize(revision)
            if revision["status"] != "draft":
                raise DomainConflictError(
                    "REVISION_CONFIRM_NOT_ALLOWED",
                    "Only a draft revision can be confirmed",
                    details={"status": revision["status"]},
                )
            cursor.execute(
                sql.SQL(
                    "SELECT * FROM {} WHERE {} = %s AND status = 'confirmed' "
                    "ORDER BY revision_number DESC LIMIT 1 FOR UPDATE"
                ).format(table_id, group_id),
                (revision[group_column],),
            )
            previous = cursor.fetchone()
            if previous is not None:
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET status = 'superseded', superseded_at = now(), updated_at = now() "
                        "WHERE id = %s"
                    ).format(table_id),
                    (previous["id"],),
                )
                self._propagate_stale(
                    cursor,
                    source_type=object_type,
                    source_code=stable_code,
                    old_revision=int(previous["revision_number"]),
                    new_revision=revision_number,
                )
            cursor.execute(
                sql.SQL(
                    "UPDATE {} SET status = 'confirmed', confirmed_by = %s, "
                    "confirmed_at = now(), updated_at = now() WHERE id = %s RETURNING *"
                ).format(table_id),
                (actor_id, revision["id"]),
            )
            confirmed = cursor.fetchone()
            if identity_table:
                identity_id = sql.Identifier(identity_table)
                identity_primary = {
                    "story_briefs": "story_brief_id",
                    "production_variants": "variant_id",
                    "live_room_configurations": "configuration_id",
                }[identity_table]
                if identity_table == "story_briefs":
                    cursor.execute(
                        sql.SQL(
                            "UPDATE {} SET current_revision_number = GREATEST(current_revision_number, %s), "
                            "updated_at = now() WHERE id = %s"
                        ).format(identity_id),
                        (revision_number, revision[identity_primary]),
                    )
                else:
                    cursor.execute(
                        sql.SQL(
                            "UPDATE {} SET current_revision_number = GREATEST(current_revision_number, %s), "
                            "status = 'active', updated_at = now() WHERE id = %s"
                        ).format(identity_id),
                        (revision_number, revision[identity_primary]),
                    )
        self.connection.commit()
        return self._serialize(confirmed)

    def _upsert_legacy_link(
        self,
        cursor: Any,
        *,
        source_type: str,
        source_code: str,
        variant_revision_id: UUID,
        configuration_revision_id: UUID | None,
        mapping_quality: str,
        source_snapshot: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO legacy_production_variant_links (
                source_type, source_code, production_variant_revision_id,
                live_room_configuration_revision_id, mapping_quality,
                source_snapshot, mapped_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_type, source_code) DO UPDATE SET
                production_variant_revision_id = EXCLUDED.production_variant_revision_id,
                live_room_configuration_revision_id = EXCLUDED.live_room_configuration_revision_id,
                mapping_quality = EXCLUDED.mapping_quality,
                source_snapshot = EXCLUDED.source_snapshot,
                mapped_by = EXCLUDED.mapped_by,
                mapped_at = now()
            RETURNING *
            """,
            (
                source_type,
                source_code,
                variant_revision_id,
                configuration_revision_id,
                mapping_quality,
                Jsonb(source_snapshot),
                actor_id,
            ),
        )
        return cursor.fetchone()

    @staticmethod
    def _confirmed_project_revision(cursor: Any, project_code: str, revision_number: int) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT * FROM content_project_revisions
            WHERE project_code = %s AND revision_number = %s AND status = 'confirmed'
            """,
            (project_code, revision_number),
        )
        row = cursor.fetchone()
        if row is None:
            raise DomainValidationError(
                "CONTENT_PROJECT_REVISION_NOT_CONFIRMED",
                "ContentProject revision must be confirmed",
            )
        return row

    @staticmethod
    def _confirmed_story_brief(cursor: Any, code: str, revision_number: int) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT revision.*, brief.project_id
            FROM story_brief_revisions AS revision
            JOIN story_briefs AS brief ON brief.id = revision.story_brief_id
            WHERE revision.story_brief_code = %s AND revision.revision_number = %s
              AND revision.status = 'confirmed'
            """,
            (code, revision_number),
        )
        row = cursor.fetchone()
        if row is None:
            raise DomainValidationError("STORY_BRIEF_NOT_CONFIRMED", "StoryBrief revision must be confirmed")
        return row

    @staticmethod
    def _confirmed_revision_by_code(cursor: Any, table: str, code_column: str, code: str) -> dict[str, Any]:
        cursor.execute(
            sql.SQL("SELECT * FROM {} WHERE {} = %s AND status = 'confirmed'").format(
                sql.Identifier(table), sql.Identifier(code_column)
            ),
            (code,),
        )
        row = cursor.fetchone()
        if row is None:
            raise DomainValidationError(
                "SOURCE_REVISION_NOT_CONFIRMED",
                "Source revision must exist and be confirmed",
                details={"source_code": code},
            )
        return row

    @staticmethod
    def _current_project_scoped_revision(cursor: Any, table: str, project_id: UUID) -> int:
        cursor.execute(
            sql.SQL("SELECT COALESCE(MAX(revision_number), 0) AS revision FROM {} WHERE project_id = %s").format(
                sql.Identifier(table)
            ),
            (project_id,),
        )
        return int(cursor.fetchone()["revision"])

    def _stable_project_code(self, *, table: str, code_column: str, code: str) -> str:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                sql.SQL(
                    "SELECT project.project_code FROM {} AS revision "
                    "JOIN content_projects AS project ON project.id = revision.project_id "
                    "WHERE revision.{} = %s"
                ).format(sql.Identifier(table), sql.Identifier(code_column)),
                (code,),
            )
            row = cursor.fetchone()
        if row is None:
            raise KeyError(code)
        return str(row["project_code"])

    @staticmethod
    def _project_code(cursor: Any, project_id: UUID) -> str:
        cursor.execute("SELECT project_code FROM content_projects WHERE id = %s", (project_id,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(str(project_id))
        return str(row["project_code"])

    @staticmethod
    def _insert_derivation(
        cursor: Any,
        *,
        source: tuple[str, str, int],
        target: tuple[str, str, int],
        producer_role: str,
        producer_strategy_revision: str,
        input_fingerprint: str,
        output_fingerprint: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO domain_derivation_edges (
                source_type, source_code, source_revision, target_type,
                target_code, target_revision, relation_type, producer_role,
                producer_strategy_revision, input_fingerprint, output_fingerprint
            ) VALUES (%s, %s, %s, %s, %s, %s, 'derived_from', %s, %s, %s, %s)
            ON CONFLICT (
                source_type, source_code, source_revision, target_type,
                target_code, target_revision, relation_type
            ) DO NOTHING
            """,
            (*source, *target, producer_role, producer_strategy_revision, input_fingerprint, output_fingerprint),
        )

    @staticmethod
    def _propagate_stale(
        cursor: Any,
        *,
        source_type: str,
        source_code: str,
        old_revision: int,
        new_revision: int,
    ) -> None:
        cursor.execute(
            """
            WITH RECURSIVE downstream(
                source_type, source_code, source_revision,
                target_type, target_code, target_revision
            ) AS (
                SELECT source_type, source_code, source_revision,
                       target_type, target_code, target_revision
                FROM domain_derivation_edges
                WHERE source_type = %s AND source_code = %s AND source_revision = %s
                UNION
                SELECT edge.source_type, edge.source_code, edge.source_revision,
                       edge.target_type, edge.target_code, edge.target_revision
                FROM domain_derivation_edges AS edge
                JOIN downstream AS parent
                  ON edge.source_type = parent.target_type
                 AND edge.source_code = parent.target_code
                 AND edge.source_revision = parent.target_revision
            )
            INSERT INTO stale_propagation_records (
                source_type, source_code, old_revision, new_revision,
                target_type, target_code, target_revision, reason_code
            )
            SELECT %s, %s, %s, %s, target_type, target_code, target_revision,
                   'UPSTREAM_REVISION_SUPERSEDED'
            FROM downstream
            ON CONFLICT (
                source_type, source_code, new_revision,
                target_type, target_code, target_revision
            ) DO NOTHING
            """,
            (
                source_type,
                source_code,
                old_revision,
                source_type,
                source_code,
                old_revision,
                new_revision,
            ),
        )
        cursor.execute(
            """
            UPDATE production_variant_revisions AS revision
            SET stale = true,
                stale_reason_codes = CASE
                    WHEN stale_reason_codes @> '["UPSTREAM_REVISION_SUPERSEDED"]'::jsonb
                    THEN stale_reason_codes
                    ELSE stale_reason_codes || '["UPSTREAM_REVISION_SUPERSEDED"]'::jsonb
                END,
                updated_at = now()
            FROM stale_propagation_records AS stale
            WHERE stale.source_type = %s AND stale.source_code = %s
              AND stale.new_revision = %s AND stale.cleared_at IS NULL
              AND stale.target_type = 'production_variant'
              AND revision.variant_code = stale.target_code
              AND revision.revision_number = stale.target_revision
            """,
            (source_type, source_code, new_revision),
        )

    @staticmethod
    def _branches(value: Any) -> list[str]:
        branches = list(value or ["live_room", "rendered_video"])
        if not branches or not set(branches).issubset(_BRANCH_KINDS):
            raise DomainValidationError("BRANCH_APPLICABILITY_INVALID", "Invalid branch applicability")
        return branches

    @classmethod
    def _reject_shot_runtime_locators(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in _SHOT_FORBIDDEN_KEYS:
                    raise DomainValidationError(
                        "SHOT_RUNTIME_LOCATOR_FORBIDDEN",
                        "Shot cannot contain mutable paths, URLs, or Maitu list indexes",
                        details={"key": key},
                    )
                cls._reject_shot_runtime_locators(child)
        elif isinstance(value, list):
            for child in value:
                cls._reject_shot_runtime_locators(child)

    def _revision_conflict(self, expected: int, actual: int) -> None:
        self.connection.rollback()
        raise DomainConflictError(
            "REVISION_CONFLICT",
            "Content revision changed since it was loaded",
            details={"expected_revision": expected, "actual_revision": actual},
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
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
        sequence = int(cursor.fetchone()["current_value"])
        return f"{prefix}-{sequence_date:%Y%m%d}-{sequence:06d}"

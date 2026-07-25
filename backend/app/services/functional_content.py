from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.repositories.content_core import ContentCoreRepository
from app.repositories.content_production import ContentProductionRepository
from app.repositories.live_observations import LiveObservationRepository
from app.repositories.maitu_workbench import MaituWorkbenchRepository
from app.domain.errors import DomainConflictError, DomainValidationError
from app.services.functional_knowledge import FunctionalKnowledgeService


class FunctionalContentService:
    """Fast-track content chain over the Phase 0 immutable revision model."""

    def __init__(self, connection: Connection):
        self.connection = connection
        self.core = ContentCoreRepository(connection)
        self.production = ContentProductionRepository(connection)
        self.facts = MaituWorkbenchRepository(connection)
        self.knowledge = FunctionalKnowledgeService(connection)
        self.templates = LiveObservationRepository(connection)

    def create_project(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        document = self._document(payload)
        self._pin_fact_cards(document)
        self._pin_fact_claims(document)
        self._pin_content_rules(document)
        self._pin_template_refs(document)
        created = self.core.create_project(
            title=payload["title"],
            generation_goal=payload["generation_goal"],
            content=document,
            actor_id=actor_id,
            producer_strategy_revision="functional-input.v1",
            source_revision_refs=self._source_refs(document),
        )
        return self._summary(created)

    def update_project(
        self,
        project_code: str,
        payload: dict[str, Any],
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        expected_revision = payload.pop("expected_revision", None)
        if not isinstance(expected_revision, int):
            raise DomainValidationError(
                "CONTENT_PROJECT_EXPECTED_REVISION_REQUIRED",
                "Updating a content project requires expected_revision",
            )
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        document = dict(current["content"] or {})
        updates = self._document(payload, include_defaults=False)
        if "fact_card_codes" in updates and "fact_card_refs" not in updates:
            document.pop("fact_card_refs", None)
        if "fact_claim_codes" in updates and "fact_claim_refs" not in updates:
            document.pop("fact_claim_refs", None)
        if "content_rule_codes" in updates and "content_rule_refs" not in updates:
            document.pop("content_rule_refs", None)
        if (
            {"primary_template_code", "secondary_template_codes"} & set(updates)
            and "template_contribution_decisions" not in updates
        ):
            document.pop("template_contribution_decisions", None)
        document.update(updates)
        self._pin_fact_cards(document)
        self._pin_fact_claims(document)
        self._pin_content_rules(document)
        self._pin_template_refs(document)
        revision = self.core.create_project_revision(
            project_code,
            expected_revision=expected_revision,
            title=str(payload.get("title") or current["title"]),
            generation_goal=str(payload.get("generation_goal") or current["generation_goal"]),
            content=document,
            source_revision_refs=self._source_refs(document),
            actor_id=actor_id,
            producer_strategy_revision="functional-input.v1",
        )
        detail = self.get_detail(project_code)
        if detail is None:
            raise KeyError(project_code)
        if int(detail["revision_number"]) != int(revision["revision_number"]):
            raise DomainConflictError(
                "CONTENT_PROJECT_UPDATE_NOT_CURRENT",
                "Content project update did not become the current revision",
            )
        return detail

    def confirm_project(
        self,
        project_code: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        if int(current["revision_number"]) != expected_revision:
            raise DomainConflictError(
                "REVISION_CONFLICT",
                "Content project changed since it was loaded",
                details={"expected_revision": expected_revision, "actual_revision": current["revision_number"]},
            )
        document = dict(current["content"] or {})
        self._pin_fact_cards(document, require_existing_pins=True)
        self._pin_fact_claims(document, require_existing_pins=True)
        self._pin_content_rules(document, require_existing_pins=True)
        self._pin_template_refs(document, require_existing_pins=True)
        if document != current["content"]:
            revision = self.core.create_project_revision(
                project_code,
                expected_revision=expected_revision,
                title=current["title"],
                generation_goal=current["generation_goal"],
                content=document,
                source_revision_refs=self._source_refs(document),
                actor_id=actor_id,
                producer_strategy_revision="functional-input.v1",
            )
            expected_revision = int(revision["revision_number"])
        self.core.confirm_project_revision(
            project_code,
            revision_number=expected_revision,
            actor_id=actor_id,
        )
        return self.get_detail(project_code) or {}

    def parse_design_brief(
        self,
        project_code: str,
        *,
        expected_revision: int,
        raw_input: str,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        if int(current["revision_number"]) != expected_revision:
            raise DomainConflictError(
                "REVISION_CONFLICT",
                "Content project changed since it was loaded",
                details={"expected_revision": expected_revision, "actual_revision": current["revision_number"]},
            )
        # The raw brief is retained as untrusted user input. Only project fields
        # and the bounded deterministic compiler below can affect parsed output.
        parsed, questions = self._compile_design_brief(current, raw_input)
        fingerprint = canonical_fingerprint(
            {
                "project_code": project_code,
                "project_revision": expected_revision,
                "raw_input": raw_input,
                "parsed": parsed,
                "questions": questions,
                "parser_strategy_ref": "local-deterministic-design-brief.v1",
            }
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_revision
                FROM functional_design_briefs
                WHERE project_id = %s
                """,
                (current["project_id"],),
            )
            next_revision = int(cursor.fetchone()["next_revision"])
            cursor.execute(
                """
                SELECT id FROM content_project_revisions
                WHERE project_id = %s AND revision_number = %s
                """,
                (current["project_id"], expected_revision),
            )
            project_revision = cursor.fetchone()
            if project_revision is None:
                self.connection.rollback()
                raise DomainConflictError(
                    "CONTENT_PROJECT_REVISION_MISSING",
                    "The current content project revision no longer exists",
                )
            cursor.execute(
                """
                INSERT INTO functional_design_briefs (
                    design_brief_code, project_id, source_project_revision_id,
                    source_project_revision_number, revision_number, raw_input,
                    parsed_brief, open_questions, user_overrides, parser_strategy_ref,
                    prompt_revision, response_fingerprint_sha256, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, %s, %s, %s, %s)
                """,
                (
                    f"DBR-{uuid4().hex[:12].upper()}",
                    current["project_id"],
                    project_revision["id"],
                    expected_revision,
                    next_revision,
                    raw_input.strip(),
                    Jsonb(parsed),
                    Jsonb(questions),
                    "local-deterministic-design-brief.v1",
                    "design-brief-local-prompt.v1",
                    fingerprint,
                    actor_id,
                ),
            )
        self.connection.commit()
        return self.get_detail(project_code) or {}

    def confirm_design_brief(
        self,
        project_code: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        if int(current["revision_number"]) != expected_revision:
            raise DomainConflictError(
                "REVISION_CONFLICT",
                "Content project changed since it was loaded",
                details={"expected_revision": expected_revision, "actual_revision": current["revision_number"]},
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM functional_design_briefs
                WHERE project_id = %s AND source_project_revision_number = %s
                ORDER BY revision_number DESC LIMIT 1 FOR UPDATE
                """,
                (current["project_id"], expected_revision),
            )
            brief = cursor.fetchone()
            if brief is None:
                self.connection.rollback()
                raise KeyError(f"{project_code}@{expected_revision}:design_brief")
            if brief["status"] == "confirmed":
                self.connection.rollback()
                return self.get_detail(project_code) or {}
            if brief["status"] != "draft":
                self.connection.rollback()
                raise DomainConflictError(
                    "DESIGN_BRIEF_CONFIRM_NOT_ALLOWED",
                    "Only a draft DesignBrief can be confirmed",
                    details={"status": brief["status"]},
                )
            cursor.execute(
                """
                UPDATE functional_design_briefs
                SET status = 'superseded', superseded_at = now(), updated_at = now()
                WHERE project_id = %s AND status = 'confirmed'
                """,
                (current["project_id"],),
            )
            cursor.execute(
                """
                UPDATE functional_design_briefs
                SET status = 'confirmed', confirmed_by = %s, confirmed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (actor_id, brief["id"]),
            )
        self.connection.commit()
        return self.get_detail(project_code) or {}

    def revise_design_brief(
        self,
        project_code: str,
        *,
        expected_revision: int,
        overrides: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        if int(current["revision_number"]) != expected_revision:
            raise DomainConflictError(
                "REVISION_CONFLICT",
                "Content project changed since it was loaded",
                details={"expected_revision": expected_revision, "actual_revision": current["revision_number"]},
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM functional_design_briefs
                WHERE project_id = %s AND source_project_revision_number = %s
                ORDER BY revision_number DESC LIMIT 1 FOR UPDATE
                """,
                (current["project_id"], expected_revision),
            )
            previous = cursor.fetchone()
            if previous is None:
                self.connection.rollback()
                raise KeyError(f"{project_code}@{expected_revision}:design_brief")
            if previous["status"] != "draft":
                self.connection.rollback()
                raise DomainConflictError(
                    "DESIGN_BRIEF_REVISE_NOT_ALLOWED",
                    "Only the current draft DesignBrief can be revised",
                    details={"status": previous["status"]},
                )
            parsed = dict(previous["parsed_brief"] or {})
            parsed.update(overrides)
            prior_overrides = dict(previous["user_overrides"] or {})
            user_overrides = {**prior_overrides, **overrides}
            question_fields = {"duration_seconds": "target_duration_seconds"}
            questions = [
                question for question in previous["open_questions"] or []
                if str(question.get("field") or "") not in {question_fields.get(key, key) for key in overrides}
            ]
            fingerprint = canonical_fingerprint(
                {
                    "project_code": project_code,
                    "project_revision": expected_revision,
                    "raw_input": previous["raw_input"],
                    "parsed": parsed,
                    "questions": questions,
                    "user_overrides": user_overrides,
                    "parser_strategy_ref": previous["parser_strategy_ref"],
                }
            )
            cursor.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_revision
                FROM functional_design_briefs
                WHERE project_id = %s
                """,
                (current["project_id"],),
            )
            next_revision = int(cursor.fetchone()["next_revision"])
            cursor.execute(
                """
                UPDATE functional_design_briefs
                SET status = 'superseded', superseded_at = now(), updated_at = now()
                WHERE project_id = %s AND source_project_revision_number = %s AND status = 'draft'
                """,
                (current["project_id"], expected_revision),
            )
            cursor.execute(
                """
                INSERT INTO functional_design_briefs (
                    design_brief_code, project_id, source_project_revision_id,
                    source_project_revision_number, revision_number, raw_input,
                    parsed_brief, open_questions, user_overrides, parser_strategy_ref,
                    prompt_revision, response_fingerprint_sha256, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    f"DBR-{uuid4().hex[:12].upper()}", current["project_id"], previous["source_project_revision_id"],
                    expected_revision, next_revision, previous["raw_input"], Jsonb(parsed), Jsonb(questions), Jsonb(user_overrides),
                    previous["parser_strategy_ref"], previous["prompt_revision"], fingerprint, actor_id,
                ),
            )
        self.connection.commit()
        return self.get_detail(project_code) or {}

    def revise_script(
        self,
        project_code: str,
        *,
        expected_revision: int,
        blocks: list[dict[str, Any]],
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        if int(current["revision_number"]) != expected_revision:
            raise DomainConflictError(
                "REVISION_CONFLICT",
                "Content project changed since it was loaded",
                details={"expected_revision": expected_revision, "actual_revision": current["revision_number"]},
            )
        if current["status"] != "confirmed":
            raise DomainConflictError("CONTENT_PROJECT_CONFIRM_REQUIRED", "Confirm the content project before revising its script")
        content = dict(current["content"] or {})
        self._pin_fact_cards(content, require_existing_pins=True)
        self._pin_fact_claims(content, require_existing_pins=True)
        self._pin_content_rules(content, require_existing_pins=True)
        self._pin_template_refs(content, require_existing_pins=True)
        design_brief = self._confirmed_design_brief(current["project_id"], expected_revision)
        if design_brief is None:
            raise DomainConflictError("DESIGN_BRIEF_CONFIRM_REQUIRED", "Confirm a DesignBrief before revising its script")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT story.*
                FROM story_brief_revisions AS story
                JOIN content_project_revisions AS project_revision ON project_revision.id = story.source_project_revision_id
                WHERE story.story_brief_id IN (SELECT id FROM story_briefs WHERE project_id = %s)
                  AND project_revision.revision_number = %s
                  AND story.source_design_brief_revision = %s
                  AND story.status = 'confirmed'
                ORDER BY story.revision_number DESC LIMIT 1
                """,
                (current["project_id"], expected_revision, f"{design_brief['design_brief_code']}:r{design_brief['revision_number']}"),
            )
            story = cursor.fetchone()
        if story is None:
            raise KeyError(f"{project_code}@{expected_revision}:story_brief")
        approved_facts = self._generation_context(current, design_brief, content)["approved_facts"]
        blocks = self._attach_literal_content_rule_refs(blocks, content)
        self._validate_fact_citations(blocks, approved_facts)
        self._validate_literal_content_rules(blocks, content)
        script_draft = self.production.create_script_revision(
            story_brief_code=story["story_brief_code"],
            story_brief_revision=int(story["revision_number"]),
            expected_revision=self._current_project_revision("content_script_revisions", current["project_id"]),
            title=f"{current['title']} 人工修订脚本",
            content={
                "generation_mode": "human_script_revision",
                "theme": content.get("theme"),
                "story": content.get("story"),
                "product_order": content.get("product_order") or [],
                "source_design_brief": f"{design_brief['design_brief_code']}:r{design_brief['revision_number']}",
            },
            blocks=blocks,
            model_strategy_ref="human_override",
            prompt_revision="human-script-editor.v1",
            producer_strategy_revision="human-script-editor.v1",
            actor_id=actor_id,
            producer_role="human_editor",
        )
        script = self.production.confirm_script_revision(
            script_draft["script_revision_code"], revision_number=int(script_draft["revision_number"]), actor_id=actor_id
        )
        program_draft = self.production.create_program_revision(
            script_revision_code=script["script_revision_code"],
            expected_revision=self._current_project_revision("content_program_revisions", current["project_id"]),
            segments=self._segments(script_draft["blocks"], content.get("product_order") or []),
            producer_strategy_revision="human-script-editor.v1",
            actor_id=actor_id,
            producer_role="human_editor",
        )
        program = self.production.confirm_program_revision(
            program_draft["program_revision_code"], revision_number=int(program_draft["revision_number"]), actor_id=actor_id
        )
        shots = self._shots(program_draft["segments"], script_draft["blocks"], content)
        shot_list = self.production.create_shot_list_revision(
            program_revision_code=program["program_revision_code"],
            expected_revision=self._current_project_revision("shot_list_revisions", current["project_id"]),
            shots=shots,
            producer_strategy_revision="human-script-editor.v1",
            actor_id=actor_id,
            producer_role="human_editor",
        )
        self.production.confirm_shot_list_revision(
            shot_list["shot_list_revision_code"], revision_number=int(shot_list["revision_number"]), actor_id=actor_id
        )
        return self.get_detail(project_code) or {}

    def revise_program_and_shots(
        self,
        project_code: str,
        *,
        expected_revision: int,
        segments: list[dict[str, Any]],
        shots: list[dict[str, Any]],
        actor_id: str,
    ) -> dict[str, Any]:
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        if int(current["revision_number"]) != expected_revision:
            raise DomainConflictError(
                "REVISION_CONFLICT",
                "Content project changed since it was loaded",
                details={"expected_revision": expected_revision, "actual_revision": current["revision_number"]},
            )
        if current["status"] != "confirmed":
            raise DomainConflictError("CONTENT_PROJECT_CONFIRM_REQUIRED", "Confirm the content project before revising its program")
        design_brief = self._confirmed_design_brief(current["project_id"], expected_revision)
        if design_brief is None:
            raise DomainConflictError("DESIGN_BRIEF_CONFIRM_REQUIRED", "Confirm a DesignBrief before revising its program")
        self.production._reject_shot_runtime_locators(shots)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT script.*
                FROM content_script_revisions AS script
                JOIN story_brief_revisions AS story ON story.id = script.source_story_brief_revision_id
                JOIN content_project_revisions AS project_revision ON project_revision.id = story.source_project_revision_id
                WHERE script.project_id = %s
                  AND script.status = 'confirmed'
                  AND story.status = 'confirmed'
                  AND project_revision.revision_number = %s
                  AND story.source_design_brief_revision = %s
                ORDER BY script.revision_number DESC
                LIMIT 1
                """,
                (
                    current["project_id"],
                    expected_revision,
                    f"{design_brief['design_brief_code']}:r{design_brief['revision_number']}",
                ),
            )
            script = cursor.fetchone()
            if script is None:
                raise KeyError(f"{project_code}@{expected_revision}:script")
            cursor.execute(
                "SELECT block_code FROM content_script_blocks WHERE script_revision_id = %s ORDER BY sort_order",
                (script["id"],),
            )
            script_block_codes = {row["block_code"] for row in cursor.fetchall()}
        program_segments: list[dict[str, Any]] = []
        segment_source_codes: list[set[str]] = []
        for index, segment in enumerate(segments):
            block_codes = [str(code) for code in segment.get("script_block_codes") or []]
            unknown_codes = sorted(set(block_codes) - script_block_codes)
            if unknown_codes:
                raise DomainValidationError(
                    "PROGRAM_SEGMENT_BLOCK_INVALID",
                    "ProgramSegment references a ScriptBlock outside the current confirmed script",
                    details={"segment_index": index, "block_codes": unknown_codes},
                )
            segment_source_codes.append(set(block_codes))
            program_segments.append(
                {
                    "semantic_goal": segment.get("semantic_goal"),
                    "program_phase": segment.get("program_phase", "body"),
                    "estimated_duration_ms": segment.get("estimated_duration_ms"),
                    "entry_condition": segment.get("entry_condition"),
                    "exit_condition": segment.get("exit_condition"),
                    "product_refs": segment.get("product_refs") or [],
                    "interaction_actions": segment.get("interaction_actions") or [],
                    "cta_actions": segment.get("cta_actions") or [],
                    "branch_applicability": segment.get("branch_applicability") or [],
                    "metadata": segment.get("metadata") or {},
                    "script_block_adoptions": [{"block_code": code, "content_action": "deliver"} for code in block_codes],
                }
            )
        prepared_shot_sources: list[list[str]] = []
        covered_segments: set[int] = set()
        for index, shot in enumerate(shots):
            segment_index = int(shot.get("program_segment_index", -1))
            if segment_index < 0 or segment_index >= len(program_segments):
                raise DomainValidationError(
                    "SHOT_SEGMENT_INVALID",
                    "Shot references a ProgramSegment outside the submitted program",
                    details={"shot_index": index, "program_segment_index": segment_index},
                )
            source_codes = [str(code) for code in shot.get("script_block_codes") or []]
            missing_sources = sorted(set(source_codes) - segment_source_codes[segment_index])
            if missing_sources:
                raise DomainValidationError(
                    "SHOT_SCRIPT_SOURCE_INVALID",
                    "Shot ScriptBlock sources must be adopted by its ProgramSegment",
                    details={"shot_index": index, "block_codes": missing_sources},
                )
            covered_segments.add(segment_index)
            prepared_shot_sources.append(source_codes)
        missing_segment_shots = sorted(set(range(len(program_segments))) - covered_segments)
        if missing_segment_shots:
            raise DomainValidationError(
                "PROGRAM_SEGMENT_SHOT_REQUIRED",
                "Every submitted ProgramSegment requires at least one Shot",
                details={"segment_indexes": missing_segment_shots},
            )
        program_draft = self.production.create_program_revision(
            script_revision_code=script["script_revision_code"],
            expected_revision=self._current_project_revision("content_program_revisions", current["project_id"]),
            segments=program_segments,
            producer_strategy_revision="human-program-shot-editor.v1",
            actor_id=actor_id,
            producer_role="human_editor",
        )
        program = self.production.confirm_program_revision(
            program_draft["program_revision_code"], revision_number=int(program_draft["revision_number"]), actor_id=actor_id
        )
        content = dict(current["content"] or {})
        program_shots: list[dict[str, Any]] = []
        for index, shot in enumerate(shots):
            segment_index = int(shot.get("program_segment_index", -1))
            source_codes = prepared_shot_sources[index]
            program_shots.append(
                {
                    "program_segment_code": program_draft["segments"][segment_index]["segment_code"],
                    "shot_goal": shot.get("shot_goal"),
                    "composition_intent": shot.get("composition_intent") or {},
                    "material_role_requirements": shot.get("material_role_requirements") or [],
                    "audio_actions": shot.get("audio_actions") or [],
                    "continuity": shot.get("continuity") or {},
                    "acceptance_criteria": shot.get("acceptance_criteria") or [],
                    "estimated_duration_ms": shot.get("estimated_duration_ms"),
                    "branch_applicability": shot.get("branch_applicability") or [],
                    "must_include": shot.get("must_include") or self._effective_rule_directives(content, "must_include"),
                    "must_avoid": shot.get("must_avoid") or self._effective_rule_directives(content, "must_avoid"),
                    "script_block_sources": [{"block_code": code, "relation_type": "derived_from"} for code in source_codes],
                }
            )
        shot_list = self.production.create_shot_list_revision(
            program_revision_code=program["program_revision_code"],
            expected_revision=self._current_project_revision("shot_list_revisions", current["project_id"]),
            shots=program_shots,
            producer_strategy_revision="human-program-shot-editor.v1",
            actor_id=actor_id,
            producer_role="human_editor",
        )
        self.production.confirm_shot_list_revision(
            shot_list["shot_list_revision_code"], revision_number=int(shot_list["revision_number"]), actor_id=actor_id
        )
        return self.get_detail(project_code) or {}

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT p.project_code, p.title, r.revision_number, r.status, r.generation_goal,
                       r.created_at, r.updated_at
                FROM content_projects p
                JOIN content_project_revisions r
                  ON r.project_id = p.id AND r.revision_number = p.current_revision_number
                WHERE p.archived_at IS NULL
                ORDER BY r.updated_at DESC, p.project_code
                """
            )
            rows = cursor.fetchall()
        return [self._summary(row) for row in rows]

    def list_chain_revisions(self, project_code: str) -> list[dict[str, Any]]:
        """Return immutable content-chain revisions with their direct source links."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id FROM content_projects WHERE project_code = %s", (project_code,))
            project = cursor.fetchone()
            if project is None:
                raise KeyError(project_code)
            project_id = project["id"]
            cursor.execute(
                """
                SELECT project_code AS object_code, revision_number, status, created_at, created_by,
                       confirmed_at, fingerprint_sha256, 'content_project' AS object_type
                FROM content_project_revisions WHERE project_id = %s
                """,
                (project_id,),
            )
            rows = [self._chain_revision_view(row, []) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT design_brief_code AS object_code, revision_number, status, created_at, created_by,
                       confirmed_at, response_fingerprint_sha256 AS fingerprint_sha256,
                       'design_brief' AS object_type, source_project_revision_number
                FROM functional_design_briefs WHERE project_id = %s
                """,
                (project_id,),
            )
            rows.extend(self._chain_revision_view(row, [f"CONTENT {project_code} r{row['source_project_revision_number']}"]) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT story.story_brief_code AS object_code, story.revision_number, story.status, story.created_at,
                       story.created_by, story.confirmed_at, story.fingerprint_sha256, 'story_brief' AS object_type,
                       project_revision.revision_number AS source_revision_number
                FROM story_brief_revisions AS story
                JOIN content_project_revisions AS project_revision ON project_revision.id = story.source_project_revision_id
                WHERE story.story_brief_id IN (SELECT id FROM story_briefs WHERE project_id = %s)
                """,
                (project_id,),
            )
            rows.extend(self._chain_revision_view(row, [f"CONTENT {project_code} r{row['source_revision_number']}"]) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT script.script_revision_code AS object_code, script.revision_number, script.status, script.created_at,
                       script.created_by, script.confirmed_at, script.fingerprint_sha256, 'script' AS object_type,
                       story.story_brief_code AS source_code, story.revision_number AS source_revision_number
                FROM content_script_revisions AS script
                JOIN story_brief_revisions AS story ON story.id = script.source_story_brief_revision_id
                WHERE script.project_id = %s
                """,
                (project_id,),
            )
            rows.extend(self._chain_revision_view(row, [f"STORY {row['source_code']} r{row['source_revision_number']}"]) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT program.program_revision_code AS object_code, program.revision_number, program.status, program.created_at,
                       program.created_by, program.confirmed_at, program.fingerprint_sha256, 'program' AS object_type,
                       script.script_revision_code AS source_code, script.revision_number AS source_revision_number
                FROM content_program_revisions AS program
                JOIN content_script_revisions AS script ON script.id = program.source_script_revision_id
                WHERE program.project_id = %s
                """,
                (project_id,),
            )
            rows.extend(self._chain_revision_view(row, [f"SCRIPT {row['source_code']} r{row['source_revision_number']}"]) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT shots.shot_list_revision_code AS object_code, shots.revision_number, shots.status, shots.created_at,
                       shots.created_by, shots.confirmed_at, shots.fingerprint_sha256, 'shot_list' AS object_type,
                       program.program_revision_code AS source_code, program.revision_number AS source_revision_number
                FROM shot_list_revisions AS shots
                JOIN content_program_revisions AS program ON program.id = shots.source_program_revision_id
                WHERE shots.project_id = %s
                """,
                (project_id,),
            )
            rows.extend(self._chain_revision_view(row, [f"PROGRAM {row['source_code']} r{row['source_revision_number']}"]) for row in cursor.fetchall())
        return sorted(rows, key=lambda row: (row["created_at"], row["object_type"], row["revision_number"]), reverse=True)

    def get_detail(self, project_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT p.id AS project_id, r.id AS project_revision_id, p.project_code, p.title, r.revision_number, r.status,
                       r.generation_goal, r.content, r.created_at, r.updated_at
                FROM content_projects p
                JOIN content_project_revisions r
                  ON r.project_id = p.id AND r.revision_number = p.current_revision_number
                WHERE p.project_code = %s
                """,
                (project_code,),
            )
            project = cursor.fetchone()
            if project is None:
                return None
            cursor.execute(
                """
                SELECT design_brief_code, revision_number, status, parsed_brief, open_questions, user_overrides,
                       raw_input, parser_strategy_ref, prompt_revision, created_at
                FROM functional_design_briefs
                WHERE project_id = %s AND source_project_revision_id = %s
                ORDER BY revision_number DESC LIMIT 1
                """,
                (project["project_id"], project["project_revision_id"]),
            )
            design_brief = cursor.fetchone()
            cursor.execute(
                """
                SELECT * FROM story_brief_revisions
                WHERE story_brief_id = (
                    SELECT id FROM story_briefs WHERE project_id = %s
                ) AND status = 'confirmed'
                ORDER BY revision_number DESC LIMIT 1
                """,
                (project["project_id"],),
            )
            story = cursor.fetchone()
            script = None
            program = None
            shot_list = None
            if story is not None:
                cursor.execute(
                    """
                    SELECT * FROM content_script_revisions
                    WHERE source_story_brief_revision_id = %s AND status = 'confirmed'
                    ORDER BY revision_number DESC LIMIT 1
                    """,
                    (story["id"],),
                )
                script = cursor.fetchone()
            if script is not None:
                cursor.execute(
                    """
                    SELECT * FROM content_program_revisions
                    WHERE source_script_revision_id = %s AND status = 'confirmed'
                    ORDER BY revision_number DESC LIMIT 1
                    """,
                    (script["id"],),
                )
                program = cursor.fetchone()
            if program is not None:
                cursor.execute(
                    """
                    SELECT * FROM shot_list_revisions
                    WHERE source_program_revision_id = %s AND status = 'confirmed'
                    ORDER BY revision_number DESC LIMIT 1
                    """,
                    (program["id"],),
                )
                shot_list = cursor.fetchone()
            content = project["content"] or {}
            detail = {
                **self._summary(project),
                "content": content,
                "fact_cards": self._fact_card_views(content),
                "fact_claims": self._fact_claim_views(content),
                "content_rules": self._content_rule_views(content),
                "design_brief": self._design_brief_view(design_brief),
                "generated": shot_list is not None,
                "generation_mode": content.get("generation_mode"),
                "story_brief": self._story_view(story),
                "script": self._script_view(cursor, script),
                "program": self._program_view(cursor, program),
                "shot_list": self._shot_list_view(cursor, shot_list),
            }
        return detail

    def generate_chain(self, project_code: str, *, actor_id: str) -> dict[str, Any]:
        current = self.core.get_project(project_code)
        if current is None:
            raise KeyError(project_code)
        project_revision = int(current["revision_number"])
        frozen_inputs = dict(current["content"] or {})
        self._pin_fact_cards(frozen_inputs, require_existing_pins=True)
        self._pin_fact_claims(frozen_inputs, require_existing_pins=True)
        self._pin_content_rules(frozen_inputs, require_existing_pins=True)
        self._pin_template_refs(frozen_inputs, require_existing_pins=True)
        if current["status"] != "confirmed":
            raise DomainConflictError(
                "CONTENT_PROJECT_CONFIRM_REQUIRED",
                "Confirm the content project before generating the content chain",
            )
        design_brief = self._confirmed_design_brief(current["project_id"], project_revision)
        if design_brief is None:
            raise DomainConflictError(
                "DESIGN_BRIEF_CONFIRM_REQUIRED",
                "Confirm a DesignBrief for the current content-project revision before generation",
            )
        content = frozen_inputs
        design_ref = f"{design_brief['design_brief_code']}:r{design_brief['revision_number']}"
        generation_context = self._generation_context(current, design_brief, content)
        story = self.production.create_story_brief_revision(
            project_code=project_code,
            project_revision=int(current["revision_number"]),
            expected_revision=self._current_story_revision(current["project_id"]),
            source_design_brief_revision=design_ref,
            content=self._story_content(current["generation_goal"], content, design_brief["parsed_brief"]),
            fact_revision_refs=self._fact_revision_refs(content),
            template_revision_refs=self._template_refs(content),
            actor_id=actor_id,
            producer_strategy_revision="functional-deterministic.v1",
        )
        story = self.production.confirm_story_brief_revision(
            story["story_brief_code"], revision_number=int(story["revision_number"]), actor_id=actor_id
        )
        blocks = self._script_blocks(current["generation_goal"], content, generation_context["approved_facts"])
        blocks = self._attach_literal_content_rule_refs(blocks, content)
        self._validate_fact_citations(blocks, generation_context["approved_facts"])
        self._validate_literal_content_rules(blocks, content)
        script_draft = self.production.create_script_revision(
            story_brief_code=story["story_brief_code"],
            story_brief_revision=int(story["revision_number"]),
            expected_revision=self._current_project_revision("content_script_revisions", current["project_id"]),
            title=f"{current['title']} 直播脚本",
            content={
                "generation_mode": "deterministic_demo",
                "theme": content.get("theme"),
                "story": content.get("story"),
                "product_order": content.get("product_order") or [],
                "generation_context_fingerprint": canonical_fingerprint(generation_context),
                "generation_context_sections": list(generation_context),
            },
            blocks=blocks,
            model_strategy_ref="functional-deterministic.v1",
            prompt_revision="functional-prompt.v1",
            producer_strategy_revision="functional-deterministic.v1",
            actor_id=actor_id,
        )
        script = self.production.confirm_script_revision(
            script_draft["script_revision_code"], revision_number=int(script_draft["revision_number"]), actor_id=actor_id
        )
        script["blocks"] = script_draft["blocks"]
        segments = self._segments(script_draft["blocks"], content.get("product_order") or [])
        program_draft = self.production.create_program_revision(
            script_revision_code=script["script_revision_code"],
            expected_revision=self._current_project_revision("content_program_revisions", current["project_id"]),
            segments=segments,
            producer_strategy_revision="functional-deterministic.v1",
            actor_id=actor_id,
        )
        program = self.production.confirm_program_revision(
            program_draft["program_revision_code"], revision_number=int(program_draft["revision_number"]), actor_id=actor_id
        )
        program["segments"] = program_draft["segments"]
        shots = self._shots(program_draft["segments"], script_draft["blocks"], content)
        shot_list = self.production.create_shot_list_revision(
            program_revision_code=program["program_revision_code"],
            expected_revision=self._current_project_revision("shot_list_revisions", current["project_id"]),
            shots=shots,
            producer_strategy_revision="functional-deterministic.v1",
            actor_id=actor_id,
        )
        self.production.confirm_shot_list_revision(
            shot_list["shot_list_revision_code"], revision_number=int(shot_list["revision_number"]), actor_id=actor_id
        )
        return self.get_detail(project_code) or {}

    @staticmethod
    def _document(payload: dict[str, Any], *, include_defaults: bool = True) -> dict[str, Any]:
        fields = (
            "theme", "story", "detailed_design", "audience", "platform", "persona", "tone",
            "target_duration_seconds", "product_order", "must_include", "must_avoid",
            "interaction_requirements", "conversion_requirements", "staging_requirements",
            "visual_requirements", "audio_requirements", "fact_card_codes", "fact_card_refs",
            "fact_claim_codes", "fact_claim_refs",
            "content_rule_codes", "content_rule_refs",
            "primary_template_code", "secondary_template_codes", "primary_template_ref",
            "secondary_template_refs", "template_contribution_decisions",
        )
        document = {field: payload.get(field) for field in fields if include_defaults or field in payload}
        if include_defaults:
            for field in (
                "product_order", "must_include", "must_avoid", "interaction_requirements",
                "conversion_requirements", "staging_requirements", "visual_requirements",
                "audio_requirements", "fact_card_codes", "fact_card_refs", "fact_claim_codes",
                "fact_claim_refs", "content_rule_codes", "content_rule_refs", "secondary_template_codes",
                "secondary_template_refs", "template_contribution_decisions",
            ):
                document[field] = document.get(field) or []
        document["generation_mode"] = "deterministic_demo"
        return document

    def _pin_fact_cards(self, document: dict[str, Any], *, require_existing_pins: bool = False) -> None:
        raw_refs = document.get("fact_card_refs") or []
        raw_codes = document.get("fact_card_codes") or []
        if require_existing_pins and raw_codes and not raw_refs:
            raise DomainValidationError(
                "FACT_CARD_VERSION_PIN_REQUIRED",
                "A content project must pin a fact card version before confirmation or generation",
            )
        requested: list[tuple[str, int | None]] = []
        if raw_refs:
            for value in raw_refs:
                if not isinstance(value, dict):
                    raise DomainValidationError("FACT_CARD_REFERENCE_INVALID", "Fact card references must be objects")
                code = str(value.get("fact_card_code") or "").strip()
                version = value.get("version_number")
                if not code or (version is not None and (not isinstance(version, int) or version < 1)):
                    raise DomainValidationError("FACT_CARD_REFERENCE_INVALID", "Fact card code and version are invalid")
                if require_existing_pins and version is None:
                    raise DomainValidationError("FACT_CARD_VERSION_PIN_REQUIRED", "Fact card version is required")
                requested.append((code, version))
        else:
            requested = [(str(code).strip(), None) for code in raw_codes if str(code).strip()]
        codes = [code for code, _ in requested]
        if len(codes) != len(set(codes)):
            raise DomainValidationError("FACT_CARD_REFERENCE_DUPLICATE", "A fact card can only be selected once")

        platform = str(document.get("platform") or "").strip()
        pinned: list[dict[str, Any]] = []
        for code, version in requested:
            resolved = self.facts.resolve_product_fact_card_version(code, version, require_approved=True)
            if resolved is None:
                raise DomainValidationError(
                    "FACT_CARD_NOT_APPROVED",
                    "The selected fact card version is unavailable or not approved",
                    details={"fact_card_code": code, "version_number": version},
                )
            fact_content = resolved.get("content") or {}
            self._validate_fact_scope(code, int(resolved["version_number"]), fact_content, platform)
            pinned.append(
                {
                    "fact_card_code": code,
                    "version_number": int(resolved["version_number"]),
                    "version_code": resolved["version_code"],
                    "content_sha256": resolved["content_sha256"],
                }
            )
        document["fact_card_refs"] = pinned
        document["fact_card_codes"] = [ref["fact_card_code"] for ref in pinned]

    def _pin_fact_claims(self, document: dict[str, Any], *, require_existing_pins: bool = False) -> None:
        raw_refs = document.get("fact_claim_refs") or []
        raw_codes = document.get("fact_claim_codes") or []
        if require_existing_pins and raw_codes and not raw_refs:
            raise DomainValidationError(
                "FACT_CLAIM_PIN_REQUIRED",
                "A content project must pin a fact claim before confirmation or generation",
            )
        requested: list[str] = []
        if raw_refs:
            for value in raw_refs:
                if not isinstance(value, dict) or not str(value.get("claim_code") or "").strip():
                    raise DomainValidationError("FACT_CLAIM_REFERENCE_INVALID", "Fact claim references must contain claim_code")
                requested.append(str(value["claim_code"]).strip())
        else:
            requested = [str(code).strip() for code in raw_codes if str(code).strip()]
        if len(requested) != len(set(requested)):
            raise DomainValidationError("FACT_CLAIM_REFERENCE_DUPLICATE", "A fact claim can only be selected once")

        now = datetime.now(UTC)
        pinned: list[dict[str, Any]] = []
        for claim_code in requested:
            resolved = self.knowledge.resolve_approved_fact_claim(claim_code)
            if resolved is None:
                raise DomainValidationError(
                    "FACT_CLAIM_NOT_APPROVED",
                    "The selected fact claim or its source is unavailable or not approved",
                    details={"claim_code": claim_code},
                )
            valid_from = resolved.get("valid_from")
            valid_until = resolved.get("valid_until")
            if valid_from and now < valid_from:
                raise DomainValidationError("FACT_CLAIM_NOT_YET_VALID", "Fact claim is not effective yet", details={"claim_code": claim_code})
            if valid_until and now >= valid_until:
                raise DomainValidationError("FACT_CLAIM_EXPIRED", "Fact claim has expired", details={"claim_code": claim_code})
            pinned.append(
                {
                    "claim_code": resolved["claim_code"],
                    "fact_code": resolved["fact_code"],
                    "source_evidence_code": resolved["source_evidence_code"],
                    "source_content_sha256": resolved["content_sha256"],
                    "claim": resolved["claim"],
                    "citation_excerpt": resolved["citation_excerpt"],
                    "citation_start_offset": resolved.get("citation_start_offset"),
                    "citation_end_offset": resolved.get("citation_end_offset"),
                    "field_path": resolved.get("field_path"),
                    "valid_from": self._json_timestamp(valid_from),
                    "valid_until": self._json_timestamp(valid_until),
                    "fingerprint_sha256": resolved["fingerprint_sha256"],
                }
            )
        document["fact_claim_refs"] = pinned
        document["fact_claim_codes"] = [ref["claim_code"] for ref in pinned]

    def _pin_content_rules(self, document: dict[str, Any], *, require_existing_pins: bool = False) -> None:
        raw_refs = document.get("content_rule_refs") or []
        raw_codes = document.get("content_rule_codes") or []
        if require_existing_pins and raw_codes and not raw_refs:
            raise DomainValidationError(
                "CONTENT_RULE_PIN_REQUIRED",
                "A content project must pin a content rule before confirmation or generation",
            )
        if raw_refs:
            requested = [
                str(value.get("rule_code") or "").strip()
                for value in raw_refs
                if isinstance(value, dict)
            ]
            if len(requested) != len(raw_refs) or not all(requested):
                raise DomainValidationError("CONTENT_RULE_REFERENCE_INVALID", "Content rule references must contain rule_code")
        else:
            requested = [str(code).strip() for code in raw_codes if str(code).strip()]
        if len(requested) != len(set(requested)):
            raise DomainValidationError("CONTENT_RULE_REFERENCE_DUPLICATE", "A content rule can only be selected once")

        now = datetime.now(UTC)
        platform = str(document.get("platform") or "").strip().lower()
        pinned: list[dict[str, Any]] = []
        for rule_code in requested:
            resolved = self.knowledge.resolve_approved_content_rule(rule_code)
            if resolved is None:
                raise DomainValidationError(
                    "CONTENT_RULE_NOT_APPROVED",
                    "The selected content rule or its source is unavailable or not approved",
                    details={"rule_code": rule_code},
                )
            valid_from = resolved.get("valid_from")
            valid_until = resolved.get("valid_until")
            if valid_from and now < valid_from:
                raise DomainValidationError("CONTENT_RULE_NOT_YET_VALID", "Content rule is not effective yet", details={"rule_code": rule_code})
            if valid_until and now >= valid_until:
                raise DomainValidationError("CONTENT_RULE_EXPIRED", "Content rule has expired", details={"rule_code": rule_code})
            scope = resolved.get("scope") or {}
            platforms = scope.get("platforms") if isinstance(scope, dict) else None
            if platforms is not None:
                if not isinstance(platforms, list) or not all(isinstance(value, str) for value in platforms):
                    raise DomainValidationError("CONTENT_RULE_SCOPE_INVALID", "Content rule scope.platforms must be a string array", details={"rule_code": rule_code})
                normalized = {value.strip().lower() for value in platforms if value.strip()}
                if platform and normalized and "all" not in normalized and platform not in normalized:
                    raise DomainValidationError("CONTENT_RULE_SCOPE_MISMATCH", "Content rule does not apply to the selected platform", details={"rule_code": rule_code, "platform": platform})
            pinned.append(
                {
                    "rule_code": resolved["rule_code"],
                    "rule_kind": resolved["rule_kind"],
                    "directive": resolved["directive"],
                    "title": resolved["title"],
                    "rule_text": resolved["rule_text"],
                    "scope": scope,
                    "source_evidence_code": resolved.get("source_evidence_code"),
                    "source_content_sha256": resolved.get("source_content_sha256"),
                    "valid_from": self._json_timestamp(valid_from),
                    "valid_until": self._json_timestamp(valid_until),
                    "fingerprint_sha256": resolved["fingerprint_sha256"],
                }
            )
        document["content_rule_refs"] = pinned
        document["content_rule_codes"] = [ref["rule_code"] for ref in pinned]

    @staticmethod
    def _json_timestamp(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        if isinstance(value, str):
            return value
        raise DomainValidationError(
            "FACT_CLAIM_VALIDITY_INVALID",
            "Fact claim validity must be an ISO-8601 timestamp",
        )

    def _pin_template_refs(self, document: dict[str, Any], *, require_existing_pins: bool = False) -> None:
        """Resolve template selections to immutable published revisions.

        Template text/layout can change after a project has been drafted.  The
        ContentProject therefore owns revision references and contribution
        decisions, while the bare codes are retained solely for form
        compatibility and filtering.
        """
        primary_code = str(document.get("primary_template_code") or "").strip() or None
        secondary_codes = [str(code).strip() for code in document.get("secondary_template_codes") or [] if str(code).strip()]
        all_codes = [*([primary_code] if primary_code else []), *secondary_codes]
        if len(all_codes) != len(set(all_codes)):
            raise DomainValidationError("TEMPLATE_REFERENCE_DUPLICATE", "A template can only be selected once")

        existing_primary = document.get("primary_template_ref")
        existing_secondary = document.get("secondary_template_refs") or []
        existing_by_code: dict[str, dict[str, Any]] = {}
        for item in [existing_primary, *existing_secondary]:
            if isinstance(item, dict) and str(item.get("template_code") or "").strip():
                existing_by_code[str(item["template_code"]).strip()] = item

        requested_decisions: dict[str, dict[str, Any]] = {}
        for item in document.get("template_contribution_decisions") or []:
            if not isinstance(item, dict):
                raise DomainValidationError(
                    "TEMPLATE_CONTRIBUTION_INVALID",
                    "Template contribution decisions must be objects",
                )
            code = str(item.get("template_code") or "").strip()
            if not code or code in requested_decisions:
                raise DomainValidationError(
                    "TEMPLATE_CONTRIBUTION_INVALID",
                    "Template contribution decisions must identify each selected template once",
                )
            accepted_modules = item.get("accepted_modules") or []
            if not isinstance(accepted_modules, list) or not all(isinstance(value, str) for value in accepted_modules):
                raise DomainValidationError(
                    "TEMPLATE_CONTRIBUTION_INVALID",
                    "Accepted template modules must be a string array",
                    details={"template_code": code},
                )
            requested_decisions[code] = {"accepted_modules": [value.strip() for value in accepted_modules if value.strip()]}

        pinned: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        for index, code in enumerate(all_codes):
            previous = existing_by_code.get(code)
            if require_existing_pins and previous is None:
                raise DomainValidationError(
                    "TEMPLATE_VERSION_PIN_REQUIRED",
                    "A content project must pin selected template revisions before confirmation or generation",
                    details={"template_code": code},
                )
            if previous is not None:
                revision_number = previous.get("revision")
                if not isinstance(revision_number, int) or revision_number < 1:
                    raise DomainValidationError("TEMPLATE_REFERENCE_INVALID", "Pinned template revision is invalid", details={"template_code": code})
                template = self.templates.get_room_template(code, include_revisions=True)
                revision = next(
                    (row for row in (template or {}).get("revisions") or [] if int(row["revision_number"]) == revision_number),
                    None,
                )
                if template is None or revision is None:
                    raise DomainValidationError("TEMPLATE_REVISION_NOT_FOUND", "Pinned template revision is unavailable", details={"template_code": code, "revision": revision_number})
                self._validate_content_strategy_template(template, revision, code)
                reference = dict(previous)
            else:
                template = self.templates.get_room_template(code, include_revisions=True)
                published_revision = template.get("published_revision_number") if template else None
                if template is None or template.get("status") != "published" or not isinstance(published_revision, int):
                    raise DomainValidationError(
                        "TEMPLATE_NOT_PUBLISHED",
                        "Selected content templates must have a published revision",
                        details={"template_code": code},
                    )
                revision = next(
                    (row for row in template.get("revisions") or [] if int(row["revision_number"]) == published_revision),
                    None,
                )
                if revision is None:
                    raise DomainValidationError(
                        "TEMPLATE_REVISION_NOT_FOUND",
                        "Selected published template revision is unavailable",
                        details={"template_code": code, "revision": published_revision},
                    )
                self._validate_content_strategy_template(template, revision, code)
                reference = {
                    "template_code": code,
                    "revision": int(published_revision),
                    "contract_version": "content-strategy.v2",
                }

            selection_role = "primary" if index == 0 and primary_code else "secondary"
            contribution = "primary_structure" if selection_role == "primary" else "secondary_supplement"
            reference.update({"contribution": contribution, "selection_role": selection_role})
            pinned.append(reference)
            strategy = dict(revision.get("content_strategy") or {})
            available_modules = [
                str(item.get("module_key") or "").strip()
                for item in strategy.get("program_outline") or []
                if isinstance(item, dict) and str(item.get("module_key") or "").strip()
            ]
            requested = requested_decisions.get(code)
            if requested is None:
                # A primary strategy supplies its full skeleton by default.
                # Secondary strategies remain opt-in per module so they cannot
                # silently replace the primary's stage order.
                accepted_modules = available_modules if selection_role == "primary" else []
            else:
                accepted_modules = requested["accepted_modules"]
            unknown_modules = sorted(set(accepted_modules) - set(available_modules))
            if unknown_modules:
                raise DomainValidationError(
                    "TEMPLATE_CONTRIBUTION_MODULE_UNKNOWN",
                    "Selected template module is not present in the pinned revision",
                    details={"template_code": code, "modules": unknown_modules},
                )
            decisions.append(
                {
                    "template_code": code,
                    "revision": int(reference["revision"]),
                    "selection_role": selection_role,
                    "contribution": contribution,
                    "available_modules": available_modules,
                    "accepted_modules": accepted_modules,
                    "rejected_modules": [key for key in available_modules if key not in accepted_modules],
                    "material_cues": [
                        str(value).strip()
                        for value in strategy.get("material_cues") or []
                        if str(value).strip()
                    ],
                    "program_outline": self._content_strategy_outline_snapshot(
                        strategy
                    ),
                    "reviewed_examples": self._content_strategy_example_snapshot(
                        strategy
                    ),
                    "content_strategy_policy": self._content_strategy_policy_snapshot(
                        strategy
                    ),
                }
            )

        unknown_decisions = sorted(set(requested_decisions) - set(all_codes))
        if unknown_decisions:
            raise DomainValidationError(
                "TEMPLATE_CONTRIBUTION_TEMPLATE_NOT_SELECTED",
                "Template contribution decisions must reference a selected template",
                details={"template_codes": unknown_decisions},
            )
        adopted_by_module: dict[str, str] = {}
        for decision in decisions:
            for module_key in decision["accepted_modules"]:
                previous_code = adopted_by_module.get(module_key)
                if previous_code is not None:
                    raise DomainValidationError(
                        "TEMPLATE_CONTRIBUTION_MODULE_CONFLICT",
                        "A program module can be adopted from only one selected template",
                        details={"module_key": module_key, "template_codes": [previous_code, decision["template_code"]]},
                    )
                adopted_by_module[module_key] = decision["template_code"]

        document["primary_template_ref"] = next((item for item in pinned if item["selection_role"] == "primary"), None)
        document["secondary_template_refs"] = [item for item in pinned if item["selection_role"] == "secondary"]
        document["primary_template_code"] = primary_code
        document["secondary_template_codes"] = secondary_codes
        document["template_contribution_decisions"] = decisions

    @staticmethod
    def _content_strategy_outline_snapshot(strategy: dict[str, Any]) -> list[dict[str, Any]]:
        """Freeze reviewed stage semantics and bounded evidence, not source media."""
        stages: list[dict[str, Any]] = []
        for item in strategy.get("program_outline") or []:
            if not isinstance(item, dict):
                continue
            module_key = str(item.get("module_key") or "").strip()
            title = str(item.get("title") or "").strip()
            purpose = str(item.get("purpose") or "").strip()
            source_session_code = str(item.get("source_session_code") or "").strip()
            start_ms = item.get("start_ms")
            end_ms = item.get("end_ms")
            if (
                not module_key
                or not title
                or not purpose
                or not source_session_code
                or not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
                or start_ms < 0
                or end_ms <= start_ms
            ):
                continue
            stages.append(
                {
                    "module_key": module_key,
                    "title": title,
                    "purpose": purpose,
                    "source_session_code": source_session_code,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )
        return stages

    @staticmethod
    def _content_strategy_example_snapshot(strategy: dict[str, Any]) -> list[dict[str, Any]]:
        """Keep reviewed wording as non-factual reference evidence only."""
        examples: list[dict[str, Any]] = []
        for item in strategy.get("reviewed_examples") or []:
            if not isinstance(item, dict):
                continue
            module_key = str(item.get("module_key") or "").strip()
            example_text = str(item.get("example_text") or "").strip()
            source_session_code = str(item.get("source_session_code") or "").strip()
            start_ms = item.get("start_ms")
            end_ms = item.get("end_ms")
            if (
                not module_key
                or not example_text
                or not source_session_code
                or not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
                or start_ms < 0
                or end_ms <= start_ms
            ):
                continue
            examples.append(
                {
                    "module_key": module_key,
                    "example_text": example_text,
                    "source_session_code": source_session_code,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )
        return examples

    @staticmethod
    def _content_strategy_policy_snapshot(strategy: dict[str, Any]) -> dict[str, Any]:
        """Freeze only the structured strategy fields a content branch may consume."""
        def object_value(key: str) -> dict[str, Any]:
            value = strategy.get(key)
            return dict(value) if isinstance(value, dict) else {}

        recipes = []
        for item in strategy.get("module_recipes") or []:
            if not isinstance(item, dict):
                continue
            module_key = str(item.get("module_key") or "").strip()
            guidance = str(item.get("guidance") or item.get("recipe") or "").strip()
            if module_key and guidance:
                recipes.append({"module_key": module_key, "guidance": guidance})
        return {
            "duration_policy": object_value("duration_policy"),
            "module_recipes": recipes,
            "product_rotation_policy": object_value("product_rotation_policy"),
            "interaction_policy": object_value("interaction_policy"),
            "conversion_policy": object_value("conversion_policy"),
            "host_style": object_value("host_style"),
        }

    @staticmethod
    def _validate_content_strategy_template(
        template: dict[str, Any], revision: dict[str, Any], template_code: str
    ) -> None:
        if template.get("template_kind") != "content_strategy" or revision.get("contract_version") != "content-strategy.v2":
            raise DomainValidationError(
                "TEMPLATE_CONTENT_STRATEGY_REQUIRED",
                "Content projects can only select published content-strategy.v2 templates",
                details={"template_code": template_code},
            )
        if revision.get("content_readiness") != "ready":
            raise DomainValidationError(
                "TEMPLATE_CONTENT_NOT_READY",
                "Selected content template revision is not ready for production use",
                details={"template_code": template_code, "revision": revision.get("revision_number")},
            )
        if revision.get("buildability") != "reference_only":
            raise DomainValidationError(
                "TEMPLATE_BUILDABILITY_INVALID",
                "External content templates must remain reference_only",
                details={"template_code": template_code, "revision": revision.get("revision_number")},
            )

    @staticmethod
    def _validate_fact_scope(
        code: str,
        version: int,
        content: dict[str, Any],
        platform: str,
    ) -> None:
        now = datetime.now(UTC)
        valid_from = FunctionalContentService._parse_fact_time(content.get("valid_from"), code, version)
        valid_until = FunctionalContentService._parse_fact_time(content.get("valid_until"), code, version)
        if valid_from and now < valid_from:
            raise DomainValidationError("FACT_CARD_NOT_YET_VALID", "Fact card version is not effective yet", details={"fact_card_code": code, "version_number": version})
        if valid_until and now >= valid_until:
            raise DomainValidationError("FACT_CARD_EXPIRED", "Fact card version has expired", details={"fact_card_code": code, "version_number": version})
        applicable = content.get("applicable_platforms")
        if applicable is not None:
            if not isinstance(applicable, list) or not all(isinstance(value, str) for value in applicable):
                raise DomainValidationError("FACT_CARD_SCOPE_INVALID", "Fact card applicable_platforms must be a string array", details={"fact_card_code": code, "version_number": version})
            normalized = {value.strip().lower() for value in applicable if value.strip()}
            if platform and normalized and "all" not in normalized and platform.lower() not in normalized:
                raise DomainValidationError("FACT_CARD_SCOPE_MISMATCH", "Fact card version does not apply to the selected platform", details={"fact_card_code": code, "version_number": version, "platform": platform})

    @staticmethod
    def _parse_fact_time(value: Any, code: str, version: int) -> datetime | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise DomainValidationError("FACT_CARD_VALIDITY_INVALID", "Fact card validity must be an ISO-8601 timestamp", details={"fact_card_code": code, "version_number": version})
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DomainValidationError("FACT_CARD_VALIDITY_INVALID", "Fact card validity must be an ISO-8601 timestamp", details={"fact_card_code": code, "version_number": version}) from exc
        if parsed.tzinfo is None:
            raise DomainValidationError("FACT_CARD_VALIDITY_INVALID", "Fact card validity must include a timezone", details={"fact_card_code": code, "version_number": version})
        return parsed.astimezone(UTC)

    @staticmethod
    def _source_refs(document: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"object_type": "fact_card", **ref, "relation_type": "approved_fact"}
            for ref in document.get("fact_card_refs") or []
        ] + [
            {"object_type": "fact_claim", **ref, "relation_type": "approved_claim"}
            for ref in document.get("fact_claim_refs") or []
        ] + [
            {"object_type": "content_rule", **ref, "relation_type": "approved_content_rule"}
            for ref in document.get("content_rule_refs") or []
        ] + [
            {"object_type": "live_room_template", "template_code": ref["template_code"], "revision": ref["revision"], "relation_type": "reference_template"}
            for ref in FunctionalContentService._template_refs(document)
        ]

    @staticmethod
    def _fact_revision_refs(content: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"fact_card_code": ref["fact_card_code"], "revision": ref["version_number"], "version_code": ref["version_code"], "content_sha256": ref["content_sha256"]}
            for ref in content.get("fact_card_refs") or []
        ] + [
            {"claim_code": ref["claim_code"], "fact_code": ref["fact_code"], "source_evidence_code": ref["source_evidence_code"], "fingerprint_sha256": ref["fingerprint_sha256"]}
            for ref in content.get("fact_claim_refs") or []
        ]

    @staticmethod
    def _content_rule_views(content: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "rule_code": ref.get("rule_code"),
                "rule_kind": ref.get("rule_kind"),
                "directive": ref.get("directive"),
                "title": ref.get("title"),
                "rule_text": ref.get("rule_text"),
                "source_evidence_code": ref.get("source_evidence_code"),
                "fingerprint_sha256": ref.get("fingerprint_sha256"),
            }
            for ref in content.get("content_rule_refs") or []
            if isinstance(ref, dict)
        ]

    @staticmethod
    def _effective_rule_directives(content: dict[str, Any], directive: str) -> list[str]:
        manual = [str(value).strip() for value in content.get(directive) or [] if str(value).strip()]
        rules = [
            str(ref.get("rule_text") or "").strip()
            for ref in content.get("content_rule_refs") or []
            if isinstance(ref, dict) and ref.get("directive") == directive
        ]
        return list(dict.fromkeys([*manual, *[value for value in rules if value]]))

    @staticmethod
    def _fact_card_views(content: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"fact_card_code": ref.get("fact_card_code"), "version_number": ref.get("version_number"), "version_code": ref.get("version_code"), "content_sha256": ref.get("content_sha256")}
            for ref in content.get("fact_card_refs") or []
            if isinstance(ref, dict)
        ]

    @staticmethod
    def _fact_claim_views(content: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "claim_code": ref.get("claim_code"), "fact_code": ref.get("fact_code"),
                "source_evidence_code": ref.get("source_evidence_code"), "claim": ref.get("claim"),
                "citation_excerpt": ref.get("citation_excerpt"), "fingerprint_sha256": ref.get("fingerprint_sha256"),
                "citation_start_offset": ref.get("citation_start_offset"), "citation_end_offset": ref.get("citation_end_offset"),
            }
            for ref in content.get("fact_claim_refs") or []
            if isinstance(ref, dict)
        ]

    @staticmethod
    def _compile_design_brief(current: dict[str, Any], raw_input: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        content = current.get("content") or {}
        parsed = {
            "objective": current["generation_goal"],
            "theme": content.get("theme"),
            "story": content.get("story"),
            "audience": content.get("audience"),
            "priorities": FunctionalContentService._effective_rule_directives(content, "must_include"),
            "persona": content.get("persona"),
            "tone": content.get("tone"),
            "duration_seconds": content.get("target_duration_seconds"),
            "must_include": FunctionalContentService._effective_rule_directives(content, "must_include"),
            "must_avoid": FunctionalContentService._effective_rule_directives(content, "must_avoid"),
            "staging": content.get("staging_requirements") or [],
            "interaction": content.get("interaction_requirements") or [],
            "conversion": content.get("conversion_requirements") or [],
            "visual": content.get("visual_requirements") or [],
            "audio": content.get("audio_requirements") or [],
            "platform": content.get("platform"),
            "raw_input_sha256": canonical_fingerprint({"raw_input": raw_input.strip()}),
        }
        candidates = (
            ("audience", "目标受众会改变信息密度和表达方式。", "使用当前常见购买者作为暂定受众"),
            ("target_duration_seconds", "目标时长会影响节目段与镜头节奏。", "先以 180 秒作为可编辑基线"),
            ("platform", "平台决定互动和合规表达边界。", "使用当前默认直播平台"),
        )
        questions = [
            {"field": field, "question": question, "recommended_answer": recommendation, "blocking": False}
            for field, question, recommendation in candidates
            if not content.get(field)
        ][:3]
        return parsed, questions

    @staticmethod
    def _design_brief_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "design_brief_code": row["design_brief_code"],
            "revision_number": row["revision_number"],
            "status": row["status"],
            "parsed_brief": row["parsed_brief"],
            "open_questions": row["open_questions"],
            "user_overrides": row["user_overrides"],
            "raw_input": row["raw_input"],
            "parser_strategy_ref": row["parser_strategy_ref"],
            "prompt_revision": row["prompt_revision"],
            "created_at": row["created_at"],
        }

    def _current_story_revision(self, project_id: str) -> int:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT current_revision_number FROM story_briefs WHERE project_id = %s", (project_id,))
            row = cursor.fetchone()
        return int(row["current_revision_number"]) if row else 0

    def _confirmed_design_brief(self, project_id: str, source_project_revision: int) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT design_brief_code, revision_number, parsed_brief, response_fingerprint_sha256
                FROM functional_design_briefs
                WHERE project_id = %s AND source_project_revision_number = %s AND status = 'confirmed'
                """,
                (project_id, source_project_revision),
            )
            row = cursor.fetchone()
        return row

    def _generation_context(
        self,
        project: dict[str, Any],
        design_brief: dict[str, Any],
        content: dict[str, Any],
    ) -> dict[str, Any]:
        approved_facts: list[dict[str, Any]] = []
        for ref in content.get("fact_card_refs") or []:
            if not isinstance(ref, dict):
                continue
            resolved = self.facts.resolve_product_fact_card_version(
                str(ref.get("fact_card_code") or ""),
                ref.get("version_number"),
                require_approved=True,
            )
            if resolved is None:
                raise DomainValidationError(
                    "FACT_CARD_NOT_APPROVED",
                    "A pinned fact card changed before generation",
                    details={"fact_card_code": ref.get("fact_card_code"), "version_number": ref.get("version_number")},
                )
            approved_facts.append(
                {
                    "fact_card_code": resolved["fact_card_code"],
                    "version_number": resolved["version_number"],
                    "content_sha256": resolved["content_sha256"],
                    "content": resolved["content"],
                }
            )
        for ref in content.get("fact_claim_refs") or []:
            if not isinstance(ref, dict):
                continue
            resolved = self.knowledge.resolve_approved_fact_claim(str(ref.get("claim_code") or ""))
            if (
                resolved is None
                or resolved["fingerprint_sha256"] != ref.get("fingerprint_sha256")
                or resolved["content_sha256"] != ref.get("source_content_sha256")
            ):
                raise DomainValidationError(
                    "FACT_CLAIM_STALE_OR_UNAVAILABLE",
                    "A pinned fact claim changed or is no longer approved before generation",
                    details={"claim_code": ref.get("claim_code")},
                )
            approved_facts.append(
                {
                    "kind": "fact_claim",
                    "claim_code": resolved["claim_code"],
                    "fact_code": resolved["fact_code"],
                    "source_evidence_code": resolved["source_evidence_code"],
                    "fingerprint_sha256": resolved["fingerprint_sha256"],
                    "content": {"verified_facts": [resolved["claim"]]},
                }
            )
        approved_content_rules: list[dict[str, Any]] = []
        for ref in content.get("content_rule_refs") or []:
            if not isinstance(ref, dict):
                continue
            resolved = self.knowledge.resolve_approved_content_rule(str(ref.get("rule_code") or ""))
            if (
                resolved is None
                or resolved["fingerprint_sha256"] != ref.get("fingerprint_sha256")
                or resolved.get("source_content_sha256") != ref.get("source_content_sha256")
            ):
                raise DomainValidationError(
                    "CONTENT_RULE_STALE_OR_UNAVAILABLE",
                    "A pinned content rule changed or is no longer approved before generation",
                    details={"rule_code": ref.get("rule_code")},
                )
            approved_content_rules.append(
                {
                    "rule_code": resolved["rule_code"],
                    "rule_kind": resolved["rule_kind"],
                    "directive": resolved["directive"],
                    "rule_text": resolved["rule_text"],
                    "fingerprint_sha256": resolved["fingerprint_sha256"],
                }
            )
        return {
            "system_baseline": {
                "strategy_revision": "content-generation-baseline.v1",
                "rules": ["approved facts are authoritative", "external references are non-authoritative"],
            },
            "approved_facts": approved_facts,
            "approved_content_rules": approved_content_rules,
            "user_goal": {
                "title": project["title"],
                "generation_goal": project["generation_goal"],
                "product_order": content.get("product_order") or [],
                "design_brief_code": design_brief["design_brief_code"],
                "design_brief_revision": design_brief["revision_number"],
                "parsed_design_brief": design_brief["parsed_brief"],
            },
            "external_references": self._template_refs(content),
            "template_context": self._template_context(content),
        }

    @staticmethod
    def _template_context(content: dict[str, Any]) -> list[dict[str, Any]]:
        """Expose only adopted structure and reviewed non-factual wording."""
        decisions = {
            str(item.get("template_code")): item
            for item in content.get("template_contribution_decisions") or []
            if isinstance(item, dict) and item.get("template_code")
        }
        context: list[dict[str, Any]] = []
        for reference in FunctionalContentService._template_refs(content):
            decision = decisions.get(str(reference["template_code"]), {})
            accepted = {
                str(module).strip()
                for module in decision.get("accepted_modules") or []
                if str(module).strip()
            }
            stages = [
                {
                    "module_key": stage.get("module_key"),
                    "title": stage.get("title"),
                    "purpose": stage.get("purpose"),
                }
                for stage in decision.get("program_outline") or []
                if isinstance(stage, dict) and stage.get("module_key") in accepted
            ]
            examples = [
                {
                    "module_key": example.get("module_key"),
                    "example_text": example.get("example_text"),
                }
                for example in decision.get("reviewed_examples") or []
                if isinstance(example, dict)
                and example.get("module_key") in accepted
            ]
            context.append(
                {
                    **reference,
                    "stages": stages,
                    "reviewed_examples": examples,
                    "fact_boundary": "non_authoritative_reference_only",
                }
            )
        return context

    @staticmethod
    def _validate_fact_citations(blocks: list[dict[str, Any]], approved_facts: list[dict[str, Any]]) -> None:
        fact_versions = {
            (str(fact["fact_card_code"]), int(fact["version_number"]))
            for fact in approved_facts
            if fact.get("kind") != "fact_claim"
        }
        fact_codes = {code for code, _ in fact_versions}
        fact_claim_codes = {
            str(fact["claim_code"])
            for fact in approved_facts
            if fact.get("kind") == "fact_claim"
        }
        restricted_markers = (
            "价格", "优惠", "促销", "库存", "赠品", "功效", "¥", "￥",
            "price", "discount", "inventory", "free gift", "benefit",
        )
        for block in blocks:
            text = str(block.get("content") or "").lower()
            citations = block.get("fact_citations") or []
            for citation in citations:
                if not isinstance(citation, dict):
                    raise DomainValidationError(
                        "FACT_CITATION_INVALID",
                        "Fact citations must be structured objects",
                        details={"module_type": block.get("module_type")},
                    )
                code = str(citation.get("fact_card_code") or "")
                version = citation.get("version_number")
                claim_code = str(citation.get("claim_code") or "")
                card_valid = bool(code and isinstance(version, int) and (code, version) in fact_versions)
                claim_valid = bool(claim_code and claim_code in fact_claim_codes)
                if not card_valid and not claim_valid:
                    raise DomainValidationError(
                        "FACT_CITATION_NOT_APPROVED",
                        "A fact citation must point to an approved pinned fact-card revision",
                        details={"module_type": block.get("module_type"), "fact_card_code": code, "version_number": version, "claim_code": claim_code},
                    )
                claim = citation.get("claim_text")
                start = citation.get("start_offset")
                end = citation.get("end_offset")
                if claim is not None and (not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(str(block.get("content") or ""))):
                    raise DomainValidationError(
                        "FACT_CITATION_SPAN_INVALID",
                        "Fact citation claim spans must stay within the ScriptBlock text",
                        details={"module_type": block.get("module_type"), "fact_card_code": code},
                    )
            if not any(marker.lower() in text for marker in restricted_markers):
                continue
            cited_codes = {
                str(citation.get("fact_card_code"))
                for citation in citations
                if isinstance(citation, dict) and citation.get("fact_card_code")
            } | {
                str(citation.get("claim_code"))
                for citation in citations
                if isinstance(citation, dict) and citation.get("claim_code")
            }
            allowed_codes = fact_codes | fact_claim_codes
            if not cited_codes or not cited_codes.issubset(allowed_codes):
                raise DomainValidationError(
                    "FACT_CITATION_REQUIRED",
                    "Price, promotion, inventory, gift, and efficacy claims require approved fact citations",
                    details={"module_type": block.get("module_type")},
                )

    @staticmethod
    def _validate_literal_content_rules(blocks: list[dict[str, Any]], content: dict[str, Any]) -> None:
        """Enforce only exact text directives from pinned content rules.

        This is deliberately a bounded compiler check. It does not infer
        paraphrases, regulatory meaning, or approval of a human exception.
        """
        script_text = "\n".join(str(block.get("content") or "") for block in blocks).casefold()
        missing: list[dict[str, str]] = []
        forbidden: list[dict[str, str]] = []
        for ref in content.get("content_rule_refs") or []:
            if not isinstance(ref, dict):
                continue
            directive = str(ref.get("directive") or "").strip()
            rule_text = str(ref.get("rule_text") or "").strip()
            if directive not in {"must_include", "must_avoid"} or not rule_text:
                continue
            rule = {
                "rule_code": str(ref.get("rule_code") or ""),
                "rule_text": rule_text,
            }
            if directive == "must_include" and rule_text.casefold() not in script_text:
                missing.append(rule)
            if directive == "must_avoid" and rule_text.casefold() in script_text:
                forbidden.append(rule)
        if forbidden:
            raise DomainValidationError(
                "CONTENT_RULE_BANNED_TEXT",
                "A pinned content rule forbids literal text in the script",
                details={"rules": forbidden},
            )
        if missing:
            raise DomainValidationError(
                "CONTENT_RULE_REQUIRED_TEXT_MISSING",
                "A pinned content rule requires literal text in the script",
                details={"rules": missing},
            )

    @staticmethod
    def _attach_literal_content_rule_refs(
        blocks: list[dict[str, Any]], content: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Attach frozen must-include evidence to the ScriptBlock that contains it."""
        attached: list[dict[str, Any]] = []
        for block in blocks:
            block_payload = dict(block)
            text = str(block_payload.get("content") or "").casefold()
            refs: list[dict[str, Any]] = []
            for ref in content.get("content_rule_refs") or []:
                if not isinstance(ref, dict) or ref.get("directive") != "must_include":
                    continue
                rule_text = str(ref.get("rule_text") or "").strip()
                if not rule_text or rule_text.casefold() not in text:
                    continue
                refs.append(
                    {
                        "rule_code": ref.get("rule_code"),
                        "rule_kind": ref.get("rule_kind"),
                        "directive": "must_include",
                        "rule_text": rule_text,
                        "fingerprint_sha256": ref.get("fingerprint_sha256"),
                    }
                )
            block_payload["content_rule_refs"] = refs
            attached.append(block_payload)
        return attached

    def _current_project_revision(self, table: str, project_id: str) -> int:
        allowed = {"content_script_revisions", "content_program_revisions", "shot_list_revisions"}
        if table not in allowed:
            raise ValueError(f"unsupported content revision table: {table}")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(f"SELECT COALESCE(MAX(revision_number), 0) AS revision FROM {table} WHERE project_id = %s", (project_id,))
            row = cursor.fetchone()
        return int(row["revision"])

    @staticmethod
    def _story_content(goal: str, content: dict[str, Any], design_brief: dict[str, Any]) -> dict[str, Any]:
        return {
            "objective": goal,
            "theme": design_brief.get("theme") or content.get("theme") or goal,
            "story": design_brief.get("story") or content.get("story") or "通过清晰的场景和节奏帮助观众完成选择。",
            "audience": design_brief.get("audience") or content.get("audience") or "目标直播间观众",
            "tone": design_brief.get("tone") or content.get("tone") or "自然、可信、直接",
            "product_order": content.get("product_order") or [],
            "must_include": design_brief.get("must_include") or FunctionalContentService._effective_rule_directives(content, "must_include"),
            "must_avoid": design_brief.get("must_avoid") or FunctionalContentService._effective_rule_directives(content, "must_avoid"),
            "design_brief_fingerprint": canonical_fingerprint(design_brief),
        }

    @staticmethod
    def _template_refs(content: dict[str, Any]) -> list[dict[str, Any]]:
        refs = [content.get("primary_template_ref"), *(content.get("secondary_template_refs") or [])]
        return [
            {
                "template_code": ref["template_code"],
                "revision": ref["revision"],
                "contribution": ref.get("contribution", "content_reference"),
                "selection_role": ref.get("selection_role"),
            }
            for ref in refs
            if isinstance(ref, dict) and ref.get("template_code") and isinstance(ref.get("revision"), int)
        ]

    @staticmethod
    def _template_sources_for_block(content: dict[str, Any], module_type: str) -> list[dict[str, Any]]:
        refs = FunctionalContentService._template_refs(content)
        decisions = {
            str(item.get("template_code")): item
            for item in content.get("template_contribution_decisions") or []
            if isinstance(item, dict) and item.get("template_code")
        }
        def with_policy(ref: dict[str, Any]) -> dict[str, Any]:
            decision = decisions.get(str(ref["template_code"]), {})
            policy = decision.get("content_strategy_policy")
            if not isinstance(policy, dict):
                return ref
            stage = next(
                (
                    item
                    for item in decision.get("program_outline") or []
                    if isinstance(item, dict)
                    and item.get("module_key") == module_type
                ),
                None,
            )
            examples = [
                item
                for item in decision.get("reviewed_examples") or []
                if isinstance(item, dict) and item.get("module_key") == module_type
            ]
            guidance = [
                str(item.get("guidance") or "").strip()
                for item in policy.get("module_recipes") or []
                if isinstance(item, dict) and item.get("module_key") == module_type
                and str(item.get("guidance") or "").strip()
            ]
            return {
                **ref,
                "content_strategy_policy": policy,
                **({"module_guidance": guidance} if guidance else {}),
                **({"strategy_stage": stage} if isinstance(stage, dict) else {}),
                **({"reference_examples": examples} if examples else {}),
            }
        adopted = [
            ref for ref in refs
            if module_type in decisions.get(str(ref["template_code"]), {}).get("accepted_modules", [])
        ]
        if adopted:
            return [with_policy(ref) for ref in adopted]
        # A primary strategy controls the overall skeleton even when its
        # source module names differ from this deterministic demo's names.
        primary_sources = [ref for ref in refs if ref.get("selection_role") == "primary"]
        if not primary_sources:
            return []
        if any(
            decisions.get(str(ref["template_code"]), {}).get("accepted_modules", [])
            for ref in primary_sources
        ):
            return [with_policy(ref) for ref in primary_sources]
        return []

    @staticmethod
    def _selected_strategy_stages(content: dict[str, Any]) -> list[dict[str, Any]]:
        """Keep the primary order, then append only explicitly adopted supplements."""
        decisions = {
            str(item.get("template_code")): item
            for item in content.get("template_contribution_decisions") or []
            if isinstance(item, dict) and item.get("template_code")
        }
        primary_stages: list[dict[str, Any]] = []
        secondary_stages: list[dict[str, Any]] = []
        for ref in FunctionalContentService._template_refs(content):
            decision = decisions.get(str(ref["template_code"]), {})
            accepted = {
                str(module).strip()
                for module in decision.get("accepted_modules") or []
                if str(module).strip()
            }
            for stage in decision.get("program_outline") or []:
                if not isinstance(stage, dict):
                    continue
                module_key = str(stage.get("module_key") or "").strip()
                if module_key in accepted:
                    target = (
                        primary_stages
                        if ref.get("selection_role") == "primary"
                        else secondary_stages
                    )
                    target.append(dict(stage))
        # A named primary conversion stage remains terminal; secondary modules
        # can only fill the body before it.
        if primary_stages and primary_stages[-1].get("module_key") == "conversion":
            return [*primary_stages[:-1], *secondary_stages, primary_stages[-1]]
        return [*primary_stages, *secondary_stages]

    @staticmethod
    def _policy_for_sources(
        sources: list[dict[str, Any]], policy_key: str
    ) -> dict[str, Any]:
        """Merge selected template policy fields without replacing the primary source."""
        result: dict[str, Any] = {}
        for source in sources:
            policy = source.get("content_strategy_policy")
            value = policy.get(policy_key) if isinstance(policy, dict) else None
            if not isinstance(value, dict):
                continue
            for key, item in value.items():
                result.setdefault(key, item)
        return result

    @staticmethod
    def _material_cues_for_sources(content: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
        decisions = {
            str(item.get("template_code")): item
            for item in content.get("template_contribution_decisions") or []
            if isinstance(item, dict) and item.get("template_code")
        }
        allowed = {
            "background", "product_display", "digital_human", "brand_title", "promotion_text",
            "decoration_foreground", "supporting_video", "voice", "background_music", "sound_effect",
        }
        return list(
            dict.fromkeys(
                cue
                for source in sources
                for cue in decisions.get(str(source.get("template_code")), {}).get("material_cues", [])
                if isinstance(cue, str) and cue in allowed
            )
        )

    @staticmethod
    def _script_blocks(
        goal: str,
        content: dict[str, Any],
        approved_facts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        theme = content.get("theme") or goal
        story = content.get("story") or "从真实使用场景出发，给出容易理解的选择建议。"

        def fact_blocks(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
            facts: list[dict[str, Any]] = []
            for fact in approved_facts:
                fact_content = fact.get("content") or {}
                verified_facts = fact_content.get("verified_facts") or []
                if not isinstance(verified_facts, list):
                    continue
                for fact_index, raw_fact in enumerate(verified_facts[:3]):
                    claim = str(raw_fact).strip()
                    if not claim:
                        continue
                    facts.append(
                        {
                            "module_type": "product_fact",
                            "content": claim,
                            "estimated_duration_ms": 30_000,
                            "template_sources": sources,
                            "fact_citations": [
                                (
                                    {
                                        "claim_code": fact["claim_code"],
                                        "fact_code": fact["fact_code"],
                                        "source_evidence_code": fact[
                                            "source_evidence_code"
                                        ],
                                        "claim_text": claim,
                                        "start_offset": 0,
                                        "end_offset": len(claim),
                                    }
                                    if fact.get("kind") == "fact_claim"
                                    else {
                                        "fact_card_code": fact["fact_card_code"],
                                        "version_number": fact["version_number"],
                                        "field_path": f"verified_facts[{fact_index}]",
                                        "claim_text": claim,
                                        "start_offset": 0,
                                        "end_offset": len(claim),
                                    }
                                )
                            ],
                        }
                    )
            return facts

        def interaction_intent(sources: list[dict[str, Any]]) -> dict[str, Any]:
            policy = FunctionalContentService._policy_for_sources(
                sources, "interaction_policy"
            )
            return {"type": "template_interaction", "policy": policy} if policy else {}

        required_rule_blocks: list[dict[str, Any]] = []
        required_rule_refs: dict[str, list[dict[str, Any]]] = {}
        for ref in content.get("content_rule_refs") or []:
            if not isinstance(ref, dict) or ref.get("directive") != "must_include":
                continue
            rule_text = str(ref.get("rule_text") or "").strip()
            if not rule_text:
                continue
            frozen_ref = {
                "rule_code": ref.get("rule_code"),
                "rule_kind": ref.get("rule_kind"),
                "directive": "must_include",
                "rule_text": rule_text,
                "fingerprint_sha256": ref.get("fingerprint_sha256"),
            }
            refs = required_rule_refs.setdefault(rule_text, [])
            if frozen_ref not in refs:
                refs.append(frozen_ref)
        for rule_text, refs in required_rule_refs.items():
            required_rule_blocks.append(
                {
                    "module_type": "content_rule",
                    "content": rule_text,
                    "estimated_duration_ms": 15_000,
                    "template_sources": [],
                    "content_rule_refs": refs,
                }
            )

        strategy_stages = FunctionalContentService._selected_strategy_stages(content)
        if strategy_stages:
            # Approved facts are independent content inputs. Preserve the
            # strategy order and insert them before a named conversion stage.
            fact_stage_sources = (
                FunctionalContentService._template_sources_for_block(
                    content, "product_fact"
                )
                if any(stage.get("module_key") == "product_fact" for stage in strategy_stages)
                else []
            )
            inserted_facts = fact_blocks(fact_stage_sources)
            conversion_index = next(
                (
                    index
                    for index, stage in enumerate(strategy_stages)
                    if stage.get("module_key") == "conversion"
                ),
                None,
            )
            blocks: list[dict[str, Any]] = []
            for index, stage in enumerate(strategy_stages):
                if conversion_index == index:
                    blocks.extend(inserted_facts)
                    blocks.extend(required_rule_blocks)
                module_type = str(stage["module_key"])
                sources = FunctionalContentService._template_sources_for_block(
                    content, module_type
                )
                stage_content = (
                    f"{stage['title']}：围绕{theme}，{stage['purpose']}。"
                    if module_type != "story"
                    else f"{stage['title']}：{story} {stage['purpose']}。"
                )
                conversion_policy = FunctionalContentService._policy_for_sources(
                    sources, "conversion_policy"
                )
                block = {
                    "module_type": module_type,
                    "content": stage_content,
                    "estimated_duration_ms": 45_000 if index in {0, len(strategy_stages) - 1} else 60_000,
                    "template_sources": sources,
                    "interaction_intent": interaction_intent(sources),
                }
                if index == len(strategy_stages) - 1:
                    block["cta_intent"] = {
                        "type": "comment",
                        **({"policy": conversion_policy} if conversion_policy else {}),
                    }
                blocks.append(block)
            if conversion_index is None:
                blocks.extend(inserted_facts)
                blocks.extend(required_rule_blocks)
            return blocks

        opening_sources = FunctionalContentService._template_sources_for_block(
            content, "opening"
        )
        story_sources = FunctionalContentService._template_sources_for_block(
            content, "story"
        )
        blocks = [
            {
                "module_type": "opening",
                "content": f"今天我们围绕{theme}展开，目标是{goal}。",
                "estimated_duration_ms": 45_000,
                "template_sources": opening_sources,
                "interaction_intent": interaction_intent(opening_sources),
            },
            {
                "module_type": "story",
                "content": story,
                "estimated_duration_ms": 90_000,
                "template_sources": story_sources,
                "interaction_intent": interaction_intent(story_sources),
            },
        ]
        blocks.extend(
            fact_blocks(
                FunctionalContentService._template_sources_for_block(
                    content, "product_fact"
                )
            )
        )
        blocks.extend(required_rule_blocks)
        conversion_sources = FunctionalContentService._template_sources_for_block(
            content, "conversion"
        )
        conversion_policy = FunctionalContentService._policy_for_sources(
            conversion_sources, "conversion_policy"
        )
        blocks.append(
            {
                "module_type": "conversion",
                "content": "结合你的实际需求选择合适方案，欢迎在互动区留下你的使用场景。",
                "estimated_duration_ms": 45_000,
                "template_sources": conversion_sources,
                "cta_intent": {"type": "comment", **({"policy": conversion_policy} if conversion_policy else {})},
            },
        )
        return blocks

    @staticmethod
    def _segments(
        blocks: list[dict[str, Any]], product_order: list[str] | tuple[str, ...] = ()
    ) -> list[dict[str, Any]]:
        phase_by_module = {"opening": "opening", "story": "body", "product_fact": "body", "conversion": "conversion"}
        goal_by_module = {
            "opening": "建立主题和观看预期",
            "story": "解释核心故事与选择理由",
            "product_fact": "说明已批准的产品事实",
            "conversion": "引导互动与下一步",
        }
        ordered_products = [str(code).strip() for code in product_order if str(code).strip()]
        product_index = 0
        segments: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            module_type = str(block.get("module_type"))
            sources = block.get("template_sources") or []
            strategy_stage = next(
                (
                    source.get("strategy_stage")
                    for source in sources
                    if isinstance(source, dict)
                    and isinstance(source.get("strategy_stage"), dict)
                ),
                None,
            )
            product_rotation_policy = FunctionalContentService._policy_for_sources(
                sources, "product_rotation_policy"
            )
            duration_policy = FunctionalContentService._policy_for_sources(
                sources, "duration_policy"
            )
            host_style = FunctionalContentService._policy_for_sources(
                sources, "host_style"
            )
            product_refs: list[str] = []
            if module_type == "product_fact" and product_index < len(ordered_products):
                product_refs = [ordered_products[product_index]]
                product_index += 1
            stage_title = (
                str(strategy_stage.get("title") or "").strip()
                if isinstance(strategy_stage, dict)
                else ""
            )
            stage_purpose = (
                str(strategy_stage.get("purpose") or "").strip()
                if isinstance(strategy_stage, dict)
                else ""
            )
            segments.append(
                {
                    "semantic_goal": stage_purpose or goal_by_module.get(module_type, "传达内容模块"),
                    "program_phase": (
                        "opening"
                        if index == 0
                        else "conversion"
                        if block.get("cta_intent")
                        else phase_by_module.get(module_type, "body")
                    ),
                    "estimated_duration_ms": block.get("estimated_duration_ms"),
                    "entry_condition": (
                        f"进入{stage_title}" if stage_title else None
                    ),
                    "exit_condition": (
                        f"完成{stage_purpose}" if stage_purpose else None
                    ),
                    "product_refs": product_refs,
                    "interaction_actions": [block["interaction_intent"]] if block.get("interaction_intent") else [],
                    "cta_actions": [block["cta_intent"]] if block.get("cta_intent") else [],
                    "metadata": {
                        **({"template_product_rotation_policy": product_rotation_policy} if product_rotation_policy else {}),
                        **({"template_duration_policy": duration_policy} if duration_policy else {}),
                        **({"template_host_style": host_style} if host_style else {}),
                        **({"template_strategy_stage": strategy_stage} if isinstance(strategy_stage, dict) else {}),
                    },
                    "script_block_adoptions": [{"block_code": block["block_code"], "content_action": "deliver"}],
                }
            )
        return segments

    @staticmethod
    def _shots(segments: list[dict[str, Any]], blocks: list[dict[str, Any]], content: dict[str, Any]) -> list[dict[str, Any]]:
        default_roles = ["digital_human", "background"]
        return [
            {
                "program_segment_code": segment["segment_code"],
                "shot_goal": segment["semantic_goal"],
                "composition_intent": {"style": "talking_head", "focus": "host" if index == 0 else "product_or_message"},
                "material_role_requirements": FunctionalContentService._shot_material_roles(
                    blocks[index].get("module_type"),
                    default_roles,
                    FunctionalContentService._material_cues_for_sources(
                        content, blocks[index].get("template_sources") or []
                    ),
                ),
                "audio_actions": [],
                "continuity": {"from_previous": index > 0},
                "acceptance_criteria": ["script_visible", "required_materials_present"],
                "estimated_duration_ms": blocks[index].get("estimated_duration_ms"),
                "must_include": FunctionalContentService._effective_rule_directives(content, "must_include"),
                "must_avoid": FunctionalContentService._effective_rule_directives(content, "must_avoid"),
                "script_block_sources": [{"block_code": blocks[index]["block_code"], "relation_type": "derived_from"}],
            }
            for index, segment in enumerate(segments)
        ]

    @staticmethod
    def _shot_material_roles(module_type: Any, default_roles: list[str], material_cues: list[str]) -> list[str]:
        if module_type in {"opening", "story"}:
            base = default_roles
        elif module_type == "product_fact":
            base = ["digital_human", "product_image"]
        else:
            base = ["digital_human", "promotion_text"]
        return list(dict.fromkeys([*base, *material_cues]))

    @staticmethod
    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "project_code": row["project_code"], "title": row["title"], "revision_number": row["revision_number"],
            "status": row["status"], "generation_goal": row["generation_goal"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _chain_revision_view(row: dict[str, Any], sources: list[str]) -> dict[str, Any]:
        return {
            "object_type": row["object_type"], "object_code": row["object_code"],
            "revision_number": int(row["revision_number"]), "status": row["status"],
            "created_at": row["created_at"], "created_by": row.get("created_by"),
            "confirmed_at": row.get("confirmed_at"), "fingerprint_sha256": row.get("fingerprint_sha256"),
            "sources": sources,
        }

    @staticmethod
    def _story_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {"story_brief_code": row["story_brief_code"], "revision_number": row["revision_number"], "content": row["content"]}

    @staticmethod
    def _script_view(cursor: Any, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        cursor.execute("SELECT block_code, module_type, content, estimated_duration_ms, fact_citations, template_sources, content_rule_refs, interaction_intent, cta_intent FROM content_script_blocks WHERE script_revision_id = %s ORDER BY sort_order", (row["id"],))
        return {"script_revision_code": row["script_revision_code"], "revision_number": row["revision_number"], "title": row["title"], "blocks": cursor.fetchall()}

    @staticmethod
    def _program_view(cursor: Any, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        cursor.execute(
            """
            SELECT id, segment_code, semantic_goal, program_phase, estimated_duration_ms,
                   entry_condition, exit_condition, product_refs, interaction_actions,
                   cta_actions, branch_applicability, metadata
            FROM program_segments WHERE program_revision_id = %s ORDER BY sort_order
            """,
            (row["id"],),
        )
        segments = cursor.fetchall()
        if not segments:
            return {"program_revision_code": row["program_revision_code"], "revision_number": row["revision_number"], "segments": []}
        cursor.execute(
            """
            SELECT adoption.segment_id, block.block_code
            FROM program_segment_script_block_adoptions AS adoption
            JOIN content_script_blocks AS block ON block.id = adoption.script_block_id
            WHERE adoption.segment_id = ANY(%s)
            ORDER BY adoption.segment_id, adoption.adoption_order
            """,
            ([segment["id"] for segment in segments],),
        )
        adopted_codes: dict[Any, list[str]] = {}
        for adoption in cursor.fetchall():
            adopted_codes.setdefault(adoption["segment_id"], []).append(adoption["block_code"])
        return {
            "program_revision_code": row["program_revision_code"],
            "revision_number": row["revision_number"],
            "segments": [
                {key: value for key, value in segment.items() if key != "id"}
                | {"script_block_codes": adopted_codes.get(segment["id"], [])}
                for segment in segments
            ],
        }

    @staticmethod
    def _shot_list_view(cursor: Any, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        cursor.execute(
            """
            SELECT shot.id, shot.shot_code, shot.shot_goal, segment.segment_code AS program_segment_code,
                   shot.composition_intent, shot.material_role_requirements, shot.audio_actions,
                   shot.continuity, shot.acceptance_criteria, shot.estimated_duration_ms,
                   shot.branch_applicability, shot.must_include, shot.must_avoid
            FROM shots AS shot
            JOIN program_segments AS segment ON segment.id = shot.program_segment_id
            WHERE shot.shot_list_revision_id = %s ORDER BY shot.sort_order
            """,
            (row["id"],),
        )
        shots = cursor.fetchall()
        if not shots:
            return {"shot_list_revision_code": row["shot_list_revision_code"], "revision_number": row["revision_number"], "shots": []}
        cursor.execute(
            """
            SELECT source.shot_id, block.block_code
            FROM shot_script_block_sources AS source
            JOIN content_script_blocks AS block ON block.id = source.script_block_id
            WHERE source.shot_id = ANY(%s)
            ORDER BY source.shot_id, source.source_order
            """,
            ([shot["id"] for shot in shots],),
        )
        source_codes: dict[Any, list[str]] = {}
        for source in cursor.fetchall():
            source_codes.setdefault(source["shot_id"], []).append(source["block_code"])
        return {
            "shot_list_revision_code": row["shot_list_revision_code"],
            "revision_number": row["revision_number"],
            "shots": [
                {key: value for key, value in shot.items() if key != "id"}
                | {"script_block_codes": source_codes.get(shot["id"], [])}
                for shot in shots
            ],
        }

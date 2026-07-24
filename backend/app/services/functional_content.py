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


class FunctionalContentService:
    """Fast-track content chain over the Phase 0 immutable revision model."""

    def __init__(self, connection: Connection):
        self.connection = connection
        self.core = ContentCoreRepository(connection)
        self.production = ContentProductionRepository(connection)
        self.facts = MaituWorkbenchRepository(connection)
        self.templates = LiveObservationRepository(connection)

    def create_project(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        document = self._document(payload)
        self._pin_fact_cards(document)
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
        if (
            {"primary_template_code", "secondary_template_codes"} & set(updates)
            and "template_contribution_decisions" not in updates
        ):
            document.pop("template_contribution_decisions", None)
        document.update(updates)
        self._pin_fact_cards(document)
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
        self._validate_fact_citations(blocks, generation_context["approved_facts"])
        script_draft = self.production.create_script_revision(
            story_brief_code=story["story_brief_code"],
            story_brief_revision=int(story["revision_number"]),
            expected_revision=self._current_project_revision("content_script_revisions", current["project_id"]),
            title=f"{current['title']} 直播脚本",
            content={
                "generation_mode": "deterministic_demo",
                "theme": content.get("theme"),
                "story": content.get("story"),
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
        segments = self._segments(script_draft["blocks"])
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
            "primary_template_code", "secondary_template_codes", "primary_template_ref",
            "secondary_template_refs", "template_contribution_decisions",
        )
        document = {field: payload.get(field) for field in fields if include_defaults or field in payload}
        if include_defaults:
            for field in (
                "product_order", "must_include", "must_avoid", "interaction_requirements",
                "conversion_requirements", "staging_requirements", "visual_requirements",
                "audio_requirements", "fact_card_codes", "fact_card_refs", "secondary_template_codes",
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
            {"object_type": "live_room_template", "template_code": ref["template_code"], "revision": ref["revision"], "relation_type": "reference_template"}
            for ref in FunctionalContentService._template_refs(document)
        ]

    @staticmethod
    def _fact_revision_refs(content: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"fact_card_code": ref["fact_card_code"], "revision": ref["version_number"], "version_code": ref["version_code"], "content_sha256": ref["content_sha256"]}
            for ref in content.get("fact_card_refs") or []
        ]

    @staticmethod
    def _fact_card_views(content: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"fact_card_code": ref.get("fact_card_code"), "version_number": ref.get("version_number"), "version_code": ref.get("version_code"), "content_sha256": ref.get("content_sha256")}
            for ref in content.get("fact_card_refs") or []
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
            "priorities": content.get("must_include") or [],
            "persona": content.get("persona"),
            "tone": content.get("tone"),
            "duration_seconds": content.get("target_duration_seconds"),
            "must_include": content.get("must_include") or [],
            "must_avoid": content.get("must_avoid") or [],
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
        return {
            "system_baseline": {
                "strategy_revision": "content-generation-baseline.v1",
                "rules": ["approved facts are authoritative", "external references are non-authoritative"],
            },
            "approved_facts": approved_facts,
            "user_goal": {
                "title": project["title"],
                "generation_goal": project["generation_goal"],
                "design_brief_code": design_brief["design_brief_code"],
                "design_brief_revision": design_brief["revision_number"],
                "parsed_design_brief": design_brief["parsed_brief"],
            },
            "external_references": self._template_refs(content),
        }

    @staticmethod
    def _validate_fact_citations(blocks: list[dict[str, Any]], approved_facts: list[dict[str, Any]]) -> None:
        fact_versions = {
            (str(fact["fact_card_code"]), int(fact["version_number"]))
            for fact in approved_facts
        }
        fact_codes = {code for code, _ in fact_versions}
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
                if not code or not isinstance(version, int) or (code, version) not in fact_versions:
                    raise DomainValidationError(
                        "FACT_CITATION_NOT_APPROVED",
                        "A fact citation must point to an approved pinned fact-card revision",
                        details={"module_type": block.get("module_type"), "fact_card_code": code, "version_number": version},
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
            }
            if not cited_codes or not cited_codes.issubset(fact_codes):
                raise DomainValidationError(
                    "FACT_CITATION_REQUIRED",
                    "Price, promotion, inventory, gift, and efficacy claims require approved fact citations",
                    details={"module_type": block.get("module_type")},
                )

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
            "must_include": design_brief.get("must_include") or content.get("must_include") or [],
            "must_avoid": design_brief.get("must_avoid") or content.get("must_avoid") or [],
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
        adopted = [
            ref for ref in refs
            if module_type in decisions.get(str(ref["template_code"]), {}).get("accepted_modules", [])
        ]
        if adopted:
            return adopted
        # A primary strategy controls the overall skeleton even when its
        # source module names differ from this deterministic demo's names.
        primary_sources = [ref for ref in refs if ref.get("selection_role") == "primary"]
        if not primary_sources:
            return []
        if any(
            decisions.get(str(ref["template_code"]), {}).get("accepted_modules", [])
            for ref in primary_sources
        ):
            return primary_sources
        return []

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
        blocks = [
            {
                "module_type": "opening",
                "content": f"今天我们围绕{theme}展开，目标是{goal}。",
                "estimated_duration_ms": 45_000,
                "template_sources": FunctionalContentService._template_sources_for_block(content, "opening"),
            },
            {
                "module_type": "story",
                "content": story,
                "estimated_duration_ms": 90_000,
                "template_sources": FunctionalContentService._template_sources_for_block(content, "story"),
            },
        ]
        for fact in approved_facts:
            fact_content = fact.get("content") or {}
            verified_facts = fact_content.get("verified_facts") or []
            if not isinstance(verified_facts, list):
                continue
            for fact_index, raw_fact in enumerate(verified_facts[:3]):
                claim = str(raw_fact).strip()
                if not claim:
                    continue
                blocks.append(
                    {
                        "module_type": "product_fact",
                        "content": claim,
                        "estimated_duration_ms": 30_000,
                        "template_sources": FunctionalContentService._template_sources_for_block(content, "product_fact"),
                        "fact_citations": [
                            {
                                "fact_card_code": fact["fact_card_code"],
                                "version_number": fact["version_number"],
                                "field_path": f"verified_facts[{fact_index}]",
                                "claim_text": claim,
                                "start_offset": 0,
                                "end_offset": len(claim),
                            }
                        ],
                    }
                )
        blocks.append(
            {
                "module_type": "conversion",
                "content": "结合你的实际需求选择合适方案，欢迎在互动区留下你的使用场景。",
                "estimated_duration_ms": 45_000,
                "template_sources": FunctionalContentService._template_sources_for_block(content, "conversion"),
                "cta_intent": {"type": "comment"},
            },
        )
        return blocks

    @staticmethod
    def _segments(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        phase_by_module = {"opening": "opening", "story": "body", "product_fact": "body", "conversion": "conversion"}
        goal_by_module = {
            "opening": "建立主题和观看预期",
            "story": "解释核心故事与选择理由",
            "product_fact": "说明已批准的产品事实",
            "conversion": "引导互动与下一步",
        }
        return [
            {
                "semantic_goal": goal_by_module.get(str(block.get("module_type")), "传达内容模块"),
                "program_phase": phase_by_module.get(str(block.get("module_type")), "body"),
                "estimated_duration_ms": block.get("estimated_duration_ms"),
                "script_block_adoptions": [{"block_code": block["block_code"], "content_action": "deliver"}],
            }
            for index, block in enumerate(blocks)
        ]

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
                "must_include": content.get("must_include") or [],
                "must_avoid": content.get("must_avoid") or [],
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
    def _story_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {"story_brief_code": row["story_brief_code"], "revision_number": row["revision_number"], "content": row["content"]}

    @staticmethod
    def _script_view(cursor: Any, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        cursor.execute("SELECT block_code, module_type, content, estimated_duration_ms, fact_citations, template_sources, interaction_intent, cta_intent FROM content_script_blocks WHERE script_revision_id = %s ORDER BY sort_order", (row["id"],))
        return {"script_revision_code": row["script_revision_code"], "revision_number": row["revision_number"], "title": row["title"], "blocks": cursor.fetchall()}

    @staticmethod
    def _program_view(cursor: Any, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        cursor.execute("SELECT segment_code, semantic_goal, program_phase, estimated_duration_ms FROM program_segments WHERE program_revision_id = %s ORDER BY sort_order", (row["id"],))
        return {"program_revision_code": row["program_revision_code"], "revision_number": row["revision_number"], "segments": cursor.fetchall()}

    @staticmethod
    def _shot_list_view(cursor: Any, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        cursor.execute("SELECT shot_code, shot_goal, composition_intent, material_role_requirements, estimated_duration_ms FROM shots WHERE shot_list_revision_id = %s ORDER BY sort_order", (row["id"],))
        return {"shot_list_revision_code": row["shot_list_revision_code"], "revision_number": row["revision_number"], "shots": cursor.fetchall()}

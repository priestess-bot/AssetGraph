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
from app.repositories.maitu_workbench import MaituWorkbenchRepository
from app.domain.errors import DomainConflictError, DomainValidationError


class FunctionalContentService:
    """Fast-track content chain over the Phase 0 immutable revision model."""

    def __init__(self, connection: Connection):
        self.connection = connection
        self.core = ContentCoreRepository(connection)
        self.production = ContentProductionRepository(connection)
        self.facts = MaituWorkbenchRepository(connection)

    def create_project(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        document = self._document(payload)
        self._pin_fact_cards(document)
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
        document.update(updates)
        self._pin_fact_cards(document)
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
                SELECT design_brief_code, revision_number, status, parsed_brief, open_questions,
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
        self._pin_fact_cards(dict(current["content"] or {}), require_existing_pins=True)
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
        content = current["content"]
        design_ref = f"{design_brief['design_brief_code']}:r{design_brief['revision_number']}"
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
        blocks = self._script_blocks(current["generation_goal"], content)
        script_draft = self.production.create_script_revision(
            story_brief_code=story["story_brief_code"],
            story_brief_revision=int(story["revision_number"]),
            expected_revision=self._current_project_revision("content_script_revisions", current["project_id"]),
            title=f"{current['title']} 直播脚本",
            content={"generation_mode": "deterministic_demo", "theme": content.get("theme"), "story": content.get("story")},
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
            "primary_template_code", "secondary_template_codes",
        )
        document = {field: payload.get(field) for field in fields if include_defaults or field in payload}
        if include_defaults:
            for field in (
                "product_order", "must_include", "must_avoid", "interaction_requirements",
                "conversion_requirements", "staging_requirements", "visual_requirements",
                "audio_requirements", "fact_card_codes", "fact_card_refs", "secondary_template_codes",
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
        codes = [code for code in [content.get("primary_template_code"), *(content.get("secondary_template_codes") or [])] if code]
        return [{"template_code": code, "revision": "selected", "contribution": "content_reference"} for code in codes]

    @staticmethod
    def _script_blocks(goal: str, content: dict[str, Any]) -> list[dict[str, Any]]:
        theme = content.get("theme") or goal
        story = content.get("story") or "从真实使用场景出发，给出容易理解的选择建议。"
        return [
            {"module_type": "opening", "content": f"今天我们围绕{theme}展开，目标是{goal}。", "estimated_duration_ms": 45_000},
            {"module_type": "story", "content": story, "estimated_duration_ms": 90_000},
            {"module_type": "conversion", "content": "结合你的实际需求选择合适方案，欢迎在互动区留下你的使用场景。", "estimated_duration_ms": 45_000, "cta_intent": {"type": "comment"}},
        ]

    @staticmethod
    def _segments(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        phases = ("opening", "body", "conversion")
        goals = ("建立主题和观看预期", "解释核心故事与选择理由", "引导互动与下一步")
        return [
            {
                "semantic_goal": goals[index],
                "program_phase": phases[index],
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
                "material_role_requirements": default_roles if index < 2 else ["digital_human", "promotion_text"],
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
        cursor.execute("SELECT block_code, module_type, content, estimated_duration_ms FROM content_script_blocks WHERE script_revision_id = %s ORDER BY sort_order", (row["id"],))
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

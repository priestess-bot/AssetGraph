from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from app.repositories.content_core import ContentCoreRepository
from app.repositories.content_production import ContentProductionRepository


class FunctionalContentService:
    """Fast-track content chain over the Phase 0 immutable revision model."""

    def __init__(self, connection: Connection):
        self.connection = connection
        self.core = ContentCoreRepository(connection)
        self.production = ContentProductionRepository(connection)

    def create_project(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        document = self._document(payload)
        created = self.core.create_project(
            title=payload["title"],
            generation_goal=payload["generation_goal"],
            content=document,
            actor_id=actor_id,
            producer_strategy_revision="functional-input.v1",
        )
        return self._summary(created)

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
                SELECT p.id AS project_id, p.project_code, p.title, r.revision_number, r.status,
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
            detail = {
                **self._summary(project),
                "content": project["content"],
                "generated": shot_list is not None,
                "generation_mode": (project["content"] or {}).get("generation_mode"),
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
        if current["status"] != "confirmed":
            current = self.core.confirm_project_revision(project_code, revision_number=project_revision, actor_id=actor_id)
        content = current["content"]
        design_ref = f"functional-design-brief:{project_code}:r{current['revision_number']}"
        story = self.production.create_story_brief_revision(
            project_code=project_code,
            project_revision=int(current["revision_number"]),
            expected_revision=self._current_story_revision(current["project_id"]),
            source_design_brief_revision=design_ref,
            content=self._story_content(current["generation_goal"], content),
            fact_revision_refs=[{"fact_card_code": code, "revision": "selected"} for code in content.get("fact_card_codes", [])],
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
    def _document(payload: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "theme", "story", "detailed_design", "audience", "tone", "target_duration_seconds",
            "must_include", "must_avoid", "fact_card_codes", "primary_template_code", "secondary_template_codes",
        )
        return {**{field: payload.get(field) for field in fields}, "generation_mode": "deterministic_demo"}

    def _current_story_revision(self, project_id: str) -> int:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT current_revision_number FROM story_briefs WHERE project_id = %s", (project_id,))
            row = cursor.fetchone()
        return int(row["current_revision_number"]) if row else 0

    def _current_project_revision(self, table: str, project_id: str) -> int:
        allowed = {"content_script_revisions", "content_program_revisions", "shot_list_revisions"}
        if table not in allowed:
            raise ValueError(f"unsupported content revision table: {table}")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(f"SELECT COALESCE(MAX(revision_number), 0) AS revision FROM {table} WHERE project_id = %s", (project_id,))
            row = cursor.fetchone()
        return int(row["revision"])

    @staticmethod
    def _story_content(goal: str, content: dict[str, Any]) -> dict[str, Any]:
        return {
            "objective": goal,
            "theme": content.get("theme") or goal,
            "story": content.get("story") or "通过清晰的场景和节奏帮助观众完成选择。",
            "audience": content.get("audience") or "目标直播间观众",
            "tone": content.get("tone") or "自然、可信、直接",
            "must_include": content.get("must_include") or [],
            "must_avoid": content.get("must_avoid") or [],
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

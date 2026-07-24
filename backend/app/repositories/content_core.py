from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainConflictError, DomainValidationError


class ContentCoreRepository:
    """Transactional access to carrier-independent content revisions."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def create_project(
        self,
        *,
        title: str,
        generation_goal: str,
        content: dict[str, Any],
        actor_id: str,
        producer_strategy_revision: str = "human_input.v1",
    ) -> dict[str, Any]:
        if not title.strip() or not generation_goal.strip():
            raise DomainValidationError(
                "CONTENT_PROJECT_REQUIRED_FIELD_MISSING",
                "Content project title and generation goal are required",
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            project_code = self._next_code(cursor, prefix="CONTENT", object_type="content_project")
            fingerprint = canonical_fingerprint(
                {
                    "title": title.strip(),
                    "generation_goal": generation_goal.strip(),
                    "content": content,
                    "producer_role": "human_business",
                    "producer_strategy_revision": producer_strategy_revision,
                }
            )
            cursor.execute(
                """
                INSERT INTO content_projects (
                    project_code, title, current_revision_number, status, owner_principal
                )
                VALUES (%s, %s, 1, 'draft', %s)
                RETURNING id
                """,
                (project_code, title.strip(), actor_id),
            )
            project_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO content_project_revisions (
                    project_id, project_code, revision_number, generation_goal,
                    content, source_revision_refs, producer_role,
                    producer_strategy_revision, fingerprint_sha256,
                    expected_parent_revision, created_by
                )
                VALUES (%s, %s, 1, %s, %s, '[]'::jsonb, 'human_business', %s, %s, 0, %s)
                RETURNING *
                """,
                (
                    project_id,
                    project_code,
                    generation_goal.strip(),
                    Jsonb(content),
                    producer_strategy_revision,
                    fingerprint,
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
        self.connection.commit()
        return self._project_revision_view(revision, title=title.strip())

    def get_project(self, project_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.*, project.title, project.status AS project_status,
                       project.owner_principal
                FROM content_projects AS project
                JOIN content_project_revisions AS revision
                  ON revision.project_id = project.id
                 AND revision.revision_number = project.current_revision_number
                WHERE project.project_code = %s
                """,
                (project_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def get_project_revision(self, project_code: str, revision_number: int) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.*, project.title, project.status AS project_status,
                       project.owner_principal
                FROM content_project_revisions AS revision
                JOIN content_projects AS project ON project.id = revision.project_id
                WHERE revision.project_code = %s AND revision.revision_number = %s
                """,
                (project_code, revision_number),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def create_project_revision(
        self,
        project_code: str,
        *,
        expected_revision: int,
        title: str,
        generation_goal: str,
        content: dict[str, Any],
        source_revision_refs: list[dict[str, Any]],
        actor_id: str,
        producer_strategy_revision: str = "human_input.v1",
    ) -> dict[str, Any]:
        fingerprint = canonical_fingerprint(
            {
                "title": title.strip(),
                "generation_goal": generation_goal.strip(),
                "content": content,
                "source_revision_refs": source_revision_refs,
                "producer_role": "human_business",
                "producer_strategy_revision": producer_strategy_revision,
            }
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_projects WHERE project_code = %s FOR UPDATE",
                (project_code,),
            )
            project = cursor.fetchone()
            if project is None:
                self.connection.rollback()
                raise KeyError(project_code)
            current_revision = int(project["current_revision_number"])
            cursor.execute(
                """
                SELECT * FROM content_project_revisions
                WHERE project_id = %s AND revision_number = %s
                """,
                (project["id"], current_revision),
            )
            current = cursor.fetchone()
            if current_revision != expected_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "REVISION_CONFLICT",
                    "Content project changed since it was loaded",
                    details={"expected_revision": expected_revision, "actual_revision": current_revision},
                )
            if current and current["fingerprint_sha256"] == fingerprint:
                self.connection.rollback()
                return self._project_revision_view(current, title=project["title"])
            next_revision = current_revision + 1
            cursor.execute(
                """
                INSERT INTO content_project_revisions (
                    project_id, project_code, revision_number, generation_goal,
                    content, source_revision_refs, producer_role,
                    producer_strategy_revision, fingerprint_sha256,
                    expected_parent_revision, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'human_business', %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    project["id"],
                    project_code,
                    next_revision,
                    generation_goal.strip(),
                    Jsonb(content),
                    Jsonb(source_revision_refs),
                    producer_strategy_revision,
                    fingerprint,
                    expected_revision,
                    actor_id,
                ),
            )
            revision = cursor.fetchone()
            cursor.execute(
                """
                UPDATE content_projects
                SET title = %s, current_revision_number = %s, updated_at = now()
                WHERE id = %s
                """,
                (title.strip(), next_revision, project["id"]),
            )
        self.connection.commit()
        return self._project_revision_view(revision, title=title.strip())

    def confirm_project_revision(
        self,
        project_code: str,
        *,
        revision_number: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_projects WHERE project_code = %s FOR UPDATE",
                (project_code,),
            )
            project = cursor.fetchone()
            if project is None:
                self.connection.rollback()
                raise KeyError(project_code)
            cursor.execute(
                """
                SELECT * FROM content_project_revisions
                WHERE project_id = %s AND revision_number = %s FOR UPDATE
                """,
                (project["id"], revision_number),
            )
            revision = cursor.fetchone()
            if revision is None:
                self.connection.rollback()
                raise KeyError(f"{project_code}@{revision_number}")
            if revision["status"] == "confirmed":
                self.connection.rollback()
                return self._project_revision_view(revision, title=project["title"])
            if revision["status"] != "draft":
                self.connection.rollback()
                raise DomainConflictError(
                    "REVISION_CONFIRM_NOT_ALLOWED",
                    "Only a draft revision can be confirmed",
                    details={"status": revision["status"]},
                )
            cursor.execute(
                """
                SELECT revision_number FROM content_project_revisions
                WHERE project_id = %s AND status = 'confirmed'
                ORDER BY revision_number DESC LIMIT 1 FOR UPDATE
                """,
                (project["id"],),
            )
            previous = cursor.fetchone()
            if previous is not None:
                cursor.execute(
                    """
                    UPDATE content_project_revisions
                    SET status = 'superseded', superseded_at = now(), updated_at = now()
                    WHERE project_id = %s AND revision_number = %s
                    """,
                    (project["id"], previous["revision_number"]),
                )
                self._propagate_stale(
                    cursor,
                    source_type="content_project",
                    source_code=project_code,
                    old_revision=int(previous["revision_number"]),
                    new_revision=revision_number,
                )
            cursor.execute(
                """
                UPDATE content_project_revisions
                SET status = 'confirmed', confirmed_by = %s, confirmed_at = now(), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (actor_id, revision["id"]),
            )
            confirmed = cursor.fetchone()
            cursor.execute(
                """
                UPDATE content_projects
                SET current_revision_number = GREATEST(current_revision_number, %s),
                    status = 'active', updated_at = now()
                WHERE id = %s
                """,
                (revision_number, project["id"]),
            )
        self.connection.commit()
        return self._project_revision_view(confirmed, title=project["title"])

    def materialize_and_confirm_project_revision(
        self,
        project_code: str,
        *,
        expected_revision: int,
        title: str,
        generation_goal: str,
        content: dict[str, Any],
        source_revision_refs: list[dict[str, Any]],
        actor_id: str,
        producer_strategy_revision: str = "human_input.v1",
        commit: bool = True,
    ) -> dict[str, Any]:
        """Atomically materialize an editable document as the confirmed revision."""

        normalized_title = title.strip()
        normalized_goal = generation_goal.strip()
        if not normalized_title or not normalized_goal:
            raise DomainValidationError(
                "CONTENT_PROJECT_REQUIRED_FIELD_MISSING",
                "Content project title and generation goal are required",
            )
        fingerprint = canonical_fingerprint(
            {
                "title": normalized_title,
                "generation_goal": normalized_goal,
                "content": content,
                "source_revision_refs": source_revision_refs,
                "producer_role": "human_business",
                "producer_strategy_revision": producer_strategy_revision,
            }
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_projects WHERE project_code = %s FOR UPDATE",
                (project_code,),
            )
            project = cursor.fetchone()
            if project is None:
                self.connection.rollback()
                raise KeyError(project_code)
            current_revision = int(project["current_revision_number"])
            if current_revision != expected_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "REVISION_CONFLICT",
                    "Content project changed since the draft was loaded",
                    details={"expected_revision": expected_revision, "actual_revision": current_revision},
                )
            cursor.execute(
                """
                SELECT * FROM content_project_revisions
                WHERE project_id = %s AND revision_number = %s FOR UPDATE
                """,
                (project["id"], current_revision),
            )
            current = cursor.fetchone()
            if current is None:
                self.connection.rollback()
                raise DomainConflictError(
                    "CONTENT_PROJECT_REVISION_MISSING",
                    "The current content project revision does not exist",
                )

            if current["status"] == "draft":
                cursor.execute(
                    """
                    UPDATE content_project_revisions
                    SET generation_goal = %s, content = %s, source_revision_refs = %s,
                        producer_role = 'human_business', producer_strategy_revision = %s,
                        fingerprint_sha256 = %s, status = 'confirmed', confirmed_by = %s,
                        confirmed_at = now(), updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        normalized_goal,
                        Jsonb(content),
                        Jsonb(source_revision_refs),
                        producer_strategy_revision,
                        fingerprint,
                        actor_id,
                        current["id"],
                    ),
                )
                confirmed = cursor.fetchone()
                result_revision = current_revision
            elif current["status"] == "confirmed" and current["fingerprint_sha256"] == fingerprint:
                confirmed = current
                result_revision = current_revision
            elif current["status"] == "confirmed":
                result_revision = current_revision + 1
                cursor.execute(
                    """
                    INSERT INTO content_project_revisions (
                        project_id, project_code, revision_number, generation_goal,
                        content, source_revision_refs, producer_role,
                        producer_strategy_revision, fingerprint_sha256,
                        expected_parent_revision, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'human_business', %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        project["id"],
                        project_code,
                        result_revision,
                        normalized_goal,
                        Jsonb(content),
                        Jsonb(source_revision_refs),
                        producer_strategy_revision,
                        fingerprint,
                        current_revision,
                        actor_id,
                    ),
                )
                inserted_id = cursor.fetchone()["id"]
                cursor.execute(
                    """
                    UPDATE content_project_revisions
                    SET status = 'superseded', superseded_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (current["id"],),
                )
                self._propagate_stale(
                    cursor,
                    source_type="content_project",
                    source_code=project_code,
                    old_revision=current_revision,
                    new_revision=result_revision,
                )
                cursor.execute(
                    """
                    UPDATE content_project_revisions
                    SET status = 'confirmed', confirmed_by = %s, confirmed_at = now(), updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (actor_id, inserted_id),
                )
                confirmed = cursor.fetchone()
            else:
                self.connection.rollback()
                raise DomainConflictError(
                    "REVISION_CONFIRM_NOT_ALLOWED",
                    "The current content project revision cannot be confirmed",
                    details={"status": current["status"]},
                )

            cursor.execute(
                """
                UPDATE content_projects
                SET title = %s, current_revision_number = %s,
                    status = 'active', updated_at = now()
                WHERE id = %s
                """,
                (normalized_title, result_revision, project["id"]),
            )
        if commit:
            self.connection.commit()
        return self._project_revision_view(confirmed, title=normalized_title)

    def add_derivation_edge(
        self,
        *,
        source_type: str,
        source_code: str,
        source_revision: int,
        target_type: str,
        target_code: str,
        target_revision: int,
        relation_type: str,
        producer_role: str,
        producer_strategy_revision: str,
        input_fingerprint: str,
        output_fingerprint: str,
    ) -> dict[str, Any]:
        if (source_type, source_code, source_revision) == (target_type, target_code, target_revision):
            raise DomainValidationError("DERIVATION_SELF_CYCLE", "A revision cannot derive from itself")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH RECURSIVE downstream(object_type, object_code, revision_number) AS (
                    SELECT target_type, target_code, target_revision
                    FROM domain_derivation_edges
                    WHERE source_type = %s AND source_code = %s AND source_revision = %s
                    UNION
                    SELECT edge.target_type, edge.target_code, edge.target_revision
                    FROM domain_derivation_edges AS edge
                    JOIN downstream AS item
                      ON edge.source_type = item.object_type
                     AND edge.source_code = item.object_code
                     AND edge.source_revision = item.revision_number
                )
                SELECT 1 FROM downstream
                WHERE object_type = %s AND object_code = %s AND revision_number = %s
                LIMIT 1
                """,
                (target_type, target_code, target_revision, source_type, source_code, source_revision),
            )
            if cursor.fetchone() is not None:
                self.connection.rollback()
                raise DomainConflictError("DERIVATION_CYCLE", "Derivation edge would create a cycle")
            cursor.execute(
                """
                INSERT INTO domain_derivation_edges (
                    source_type, source_code, source_revision, target_type,
                    target_code, target_revision, relation_type, producer_role,
                    producer_strategy_revision, input_fingerprint, output_fingerprint
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    source_type, source_code, source_revision, target_type,
                    target_code, target_revision, relation_type
                ) DO UPDATE SET input_fingerprint = domain_derivation_edges.input_fingerprint
                RETURNING *
                """,
                (
                    source_type,
                    source_code,
                    source_revision,
                    target_type,
                    target_code,
                    target_revision,
                    relation_type,
                    producer_role,
                    producer_strategy_revision,
                    input_fingerprint,
                    output_fingerprint,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def list_active_stale_records(self, *, target_type: str, target_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM stale_propagation_records
                WHERE target_type = %s AND target_code = %s AND cleared_at IS NULL
                ORDER BY detected_at, id
                """,
                (target_type, target_code),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def clear_stale_records(
        self,
        *,
        target_type: str,
        target_code: str,
        target_revision: int,
        rebuilt_by_revision: int,
    ) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE stale_propagation_records
                SET cleared_at = now(), cleared_by_revision = %s
                WHERE target_type = %s AND target_code = %s
                  AND target_revision = %s AND cleared_at IS NULL
                """,
                (rebuilt_by_revision, target_type, target_code, target_revision),
            )
            count = cursor.rowcount
        self.connection.commit()
        return count

    def _propagate_stale(
        self,
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
    def _project_revision_view(row: dict[str, Any], *, title: str) -> dict[str, Any]:
        return ContentCoreRepository._serialize({**row, "title": title})

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
        return result

    @staticmethod
    def _next_code(cursor: Any, *, prefix: str, object_type: str) -> str:
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

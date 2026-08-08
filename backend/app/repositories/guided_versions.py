from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainConflictError, DomainValidationError


_STAGE_ORDER = {"setup": 0, "outline": 1, "script": 2, "storyboard": 3}
_ITEM_TYPES = {
    "outline": "outline_section",
    "script": "script_block",
    "storyboard": "storyboard_scene",
}


class GuidedVersionRepository:
    """Immutable authoring tree layered over canonical content revisions."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def ensure_initial_setup(
        self,
        *,
        project: dict[str, Any],
        content: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_guided_project_heads WHERE project_id = %s",
                (project["project_id"],),
            )
            head = cursor.fetchone()
        if head is not None:
            return self.context(project["project_id"])
        node = self.create_node(
            project_id=project["project_id"],
            project_code=project["project_code"],
            stage="setup",
            parent_node_id=None,
            label=self._setup_label(content),
            actor_id=actor_id,
            status="draft",
            select=False,
            commit=False,
        )
        revision = self.save_revision(
            node_id=node["id"],
            expected_revision=0,
            content=content,
            items=[],
            actor_id=actor_id,
            producer_kind="human",
            producer_ref="guided-project-create",
            commit=False,
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO content_guided_project_heads (
                    project_id, project_code, selected_root_node_id,
                    selected_leaf_node_id, revision, updated_by
                ) VALUES (%s, %s, %s, %s, 1, %s)
                """,
                (
                    project["project_id"],
                    project["project_code"],
                    node["id"],
                    node["id"],
                    actor_id,
                ),
            )
        self.connection.commit()
        return {"head": self.head(project["project_id"]), "path": [{**node, "revision": revision}]}

    def create_node(
        self,
        *,
        project_id: UUID,
        project_code: str,
        stage: str,
        parent_node_id: UUID | None,
        label: str,
        actor_id: str,
        status: str = "draft",
        select: bool = True,
        commit: bool = True,
    ) -> dict[str, Any]:
        self._validate_stage_parent(stage, parent_node_id)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id FROM content_projects WHERE id = %s FOR UPDATE", (project_id,))
            if cursor.fetchone() is None:
                raise KeyError(project_id)
            if parent_node_id is not None:
                cursor.execute(
                    "SELECT * FROM content_guided_nodes WHERE id = %s AND project_id = %s",
                    (parent_node_id, project_id),
                )
                parent = cursor.fetchone()
                if parent is None:
                    raise KeyError(parent_node_id)
                expected = _STAGE_ORDER[stage] - 1
                if _STAGE_ORDER[str(parent["stage"])] != expected:
                    raise DomainValidationError(
                        "GUIDED_TREE_PARENT_INVALID", "The selected parent belongs to the wrong workflow stage"
                    )
            if parent_node_id is None:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(branch_order), 0) + 1 AS next_branch_order
                    FROM content_guided_nodes
                    WHERE project_id = %s AND stage = %s AND parent_node_id IS NULL
                    """,
                    (project_id, stage),
                )
            else:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(branch_order), 0) + 1 AS next_branch_order
                    FROM content_guided_nodes
                    WHERE project_id = %s AND stage = %s AND parent_node_id = %s
                    """,
                    (project_id, stage, parent_node_id),
                )
            branch_order = int(cursor.fetchone()["next_branch_order"])
            cursor.execute(
                """
                INSERT INTO content_guided_nodes (
                    node_code, project_id, project_code, stage, parent_node_id,
                    branch_order, label, status, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    f"GNODE-{uuid4().hex[:16].upper()}",
                    project_id,
                    project_code,
                    stage,
                    parent_node_id,
                    branch_order,
                    label.strip() or f"{stage} {branch_order}",
                    status,
                    actor_id,
                ),
            )
            node = dict(cursor.fetchone())
            if select:
                self._select_cursor(cursor, project_id, node, actor_id)
        if commit:
            self.connection.commit()
        return node

    def create_setup_draft(
        self,
        *,
        project: dict[str, Any],
        base_node: dict[str, Any],
        content: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        if base_node["stage"] != "setup":
            raise DomainValidationError("GUIDED_SETUP_NODE_REQUIRED", "A setup branch is required")
        node = self.create_node(
            project_id=project["project_id"],
            project_code=project["project_code"],
            stage="setup",
            parent_node_id=None,
            label=self._setup_label(content),
            actor_id=actor_id,
            status="draft",
            select=False,
            commit=False,
        )
        revision = self.save_revision(
            node_id=node["id"],
            expected_revision=0,
            content=content,
            items=[],
            actor_id=actor_id,
            producer_kind="human",
            producer_ref=f"forked-from:{base_node['node_code']}",
            commit=False,
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._select_cursor(cursor, project["project_id"], node, actor_id)
        self.connection.commit()
        return {**node, "revision": revision}

    def save_revision(
        self,
        *,
        node_id: UUID,
        expected_revision: int,
        content: dict[str, Any],
        items: list[dict[str, Any]],
        actor_id: str,
        producer_kind: str,
        producer_ref: str | None,
        source_parent_revision_id: UUID | None = None,
        change_summary: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM content_guided_nodes WHERE id = %s FOR UPDATE", (node_id,))
            node = cursor.fetchone()
            if node is None:
                raise KeyError(node_id)
            current_revision = int(node["current_revision_number"])
            if current_revision != expected_revision:
                raise DomainConflictError(
                    "GUIDED_NODE_REVISION_CONFLICT",
                    "The workflow node changed since it was loaded",
                    details={"expected_revision": expected_revision, "actual_revision": current_revision},
                )
            current = self._revision_cursor(cursor, node_id, current_revision) if current_revision else None
            item_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for item in items:
                item_row = self._item_cursor(
                    cursor,
                    node_id=node_id,
                    item_key=str(item["item_key"]),
                    item_type=str(item.get("item_type") or _ITEM_TYPES[str(node["stage"])]),
                    source_item_key=item.get("source_item_key"),
                    actor_id=actor_id,
                )
                if item.get("item_version_id"):
                    version = self._item_version_cursor(cursor, UUID(str(item["item_version_id"])))
                    if version is None or version["item_id"] != item_row["id"]:
                        raise DomainValidationError(
                            "GUIDED_ITEM_VERSION_SCOPE_INVALID",
                            "The selected item version does not belong to this workflow node",
                        )
                else:
                    version = self._create_item_version_cursor(
                        cursor,
                        item=item_row,
                        content=dict(item.get("content") or {}),
                        actor_id=actor_id,
                        producer_kind=str(item.get("producer_kind") or producer_kind),
                        producer_ref=item.get("producer_ref") or producer_ref,
                        guidance=item.get("guidance"),
                        invocation_evidence_ref=item.get("invocation_evidence_ref"),
                        source_node_revision_id=item.get("source_node_revision_id"),
                        source_item_version_id=item.get("source_item_version_id"),
                        source_relation=str(item.get("source_relation") or "derived_from"),
                    )
                item_rows.append((item_row, version))
            semantic_payload = {
                "stage": node["stage"],
                "content": content,
                "items": [
                    {
                        "item_key": item["item_key"],
                        "semantic_fingerprint": version["semantic_fingerprint"],
                    }
                    for item, version in item_rows
                ],
            }
            lineage_payload = {
                **semantic_payload,
                "source_parent_revision_id": str(source_parent_revision_id or ""),
                "item_versions": [str(version["id"]) for _, version in item_rows],
            }
            semantic_fingerprint = canonical_fingerprint(semantic_payload)
            lineage_fingerprint = canonical_fingerprint(lineage_payload)
            if current and current["semantic_fingerprint"] == semantic_fingerprint and current[
                "lineage_fingerprint"
            ] == lineage_fingerprint:
                if commit:
                    self.connection.rollback()
                return self._load_revision_items(dict(current), cursor=cursor)
            cursor.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_revision
                FROM content_guided_node_revisions WHERE node_id = %s
                """,
                (node_id,),
            )
            next_revision = int(cursor.fetchone()["next_revision"])
            cursor.execute(
                """
                INSERT INTO content_guided_node_revisions (
                    node_id, revision_number, status, base_revision_id,
                    source_parent_revision_id, content, change_summary, canonical_refs,
                    semantic_fingerprint, lineage_fingerprint, producer_kind,
                    producer_ref, created_by
                ) VALUES (%s, %s, 'draft', %s, %s, %s, %s, '{}'::jsonb,
                          %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    node_id,
                    next_revision,
                    current["id"] if current else None,
                    source_parent_revision_id,
                    Jsonb(content),
                    Jsonb(change_summary or {}),
                    semantic_fingerprint,
                    lineage_fingerprint,
                    producer_kind,
                    producer_ref,
                    actor_id,
                ),
            )
            revision = dict(cursor.fetchone())
            for sort_order, (item, version) in enumerate(item_rows):
                cursor.execute(
                    """
                    INSERT INTO content_guided_node_revision_items (
                        node_revision_id, item_id, item_version_id, sort_order
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (revision["id"], item["id"], version["id"], sort_order),
                )
            if current and current["status"] == "draft":
                cursor.execute(
                    """
                    UPDATE content_guided_node_revisions
                    SET status = 'superseded', superseded_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (current["id"],),
                )
            cursor.execute(
                """
                UPDATE content_guided_nodes
                SET current_revision_number = %s, status = 'draft', updated_at = now()
                WHERE id = %s
                """,
                (next_revision, node_id),
            )
            loaded = self._load_revision_items(revision, cursor=cursor)
        if commit:
            self.connection.commit()
        return loaded

    def confirm_revision(
        self,
        *,
        node_id: UUID,
        expected_revision: int,
        actor_id: str,
        canonical_refs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM content_guided_nodes WHERE id = %s FOR UPDATE", (node_id,))
            node = cursor.fetchone()
            if node is None:
                raise KeyError(node_id)
            if int(node["current_revision_number"]) != expected_revision:
                raise DomainConflictError(
                    "GUIDED_NODE_REVISION_CONFLICT", "The workflow node changed since it was loaded"
                )
            current = self._revision_cursor(cursor, node_id, expected_revision)
            if current is None:
                raise KeyError(f"{node_id}@{expected_revision}")
            confirmed_number = int(node["confirmed_revision_number"])
            confirmed = self._revision_cursor(cursor, node_id, confirmed_number) if confirmed_number else None
            current_with_items = self._load_revision_items(dict(current), cursor=cursor)
            confirmed_with_items = (
                self._load_revision_items(dict(confirmed), cursor=cursor) if confirmed else None
            )
            applicability_lineage_changed = bool(
                confirmed_with_items
                and self._applicability_lineage_changed(
                    confirmed_with_items, current_with_items
                )
            )
            if (
                confirmed
                and confirmed["semantic_fingerprint"] == current["semantic_fingerprint"]
                and not applicability_lineage_changed
            ):
                if current["id"] != confirmed["id"]:
                    cursor.execute(
                        """
                        UPDATE content_guided_node_revisions
                        SET status = 'discarded', discarded_at = now(), updated_at = now()
                        WHERE id = %s
                        """,
                        (current["id"],),
                    )
                cursor.execute(
                    """
                    UPDATE content_guided_nodes
                    SET current_revision_number = confirmed_revision_number,
                        status = 'confirmed', updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (node_id,),
                )
                result_node = dict(cursor.fetchone())
                outcome = "unchanged"
                selected = dict(confirmed)
            else:
                semantic_reaffirmation = bool(
                    confirmed
                    and confirmed["semantic_fingerprint"] == current["semantic_fingerprint"]
                    and applicability_lineage_changed
                )
                if confirmed is not None:
                    cursor.execute(
                        """
                        UPDATE content_guided_node_revisions
                        SET status = 'superseded', superseded_at = now(), updated_at = now()
                        WHERE id = %s
                        """,
                        (confirmed["id"],),
                    )
                cursor.execute(
                    """
                    UPDATE content_guided_node_revisions
                    SET status = 'confirmed', confirmed_by = %s, confirmed_at = now(),
                        canonical_refs = %s, updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        actor_id,
                        Jsonb(
                            canonical_refs
                            if canonical_refs is not None
                            else dict((confirmed or {}).get("canonical_refs") or {})
                        ),
                        current["id"],
                    ),
                )
                selected = dict(cursor.fetchone())
                cursor.execute(
                    """
                    UPDATE content_guided_nodes
                    SET confirmed_revision_number = %s, status = 'confirmed', updated_at = now()
                    WHERE id = %s RETURNING *
                    """,
                    (expected_revision, node_id),
                )
                result_node = dict(cursor.fetchone())
                outcome = "reaffirmed" if semantic_reaffirmation else "confirmed"
            loaded = self._load_revision_items(selected, cursor=cursor)
        self.connection.commit()
        return {"outcome": outcome, "node": result_node, "revision": loaded}

    def confirmation_preview(self, node_id: UUID) -> dict[str, Any]:
        node = self.node_by_id(node_id)
        if node is None:
            raise KeyError(node_id)
        current = self.node_revision(node_id, int(node["current_revision_number"]))
        confirmed = (
            self.node_revision(node_id, int(node["confirmed_revision_number"]))
            if int(node["confirmed_revision_number"])
            else None
        )
        if current is None:
            raise DomainConflictError("GUIDED_NODE_REVISION_REQUIRED", "Save the workflow draft first")
        diff = self._revision_diff(confirmed, current)
        return {
            "node_code": node["node_code"],
            "stage": node["stage"],
            "expected_revision": int(current["revision_number"]),
            "changed": confirmed is None or current["semantic_fingerprint"] != confirmed["semantic_fingerprint"],
            "lineage_changed": bool(
                confirmed
                and self._applicability_lineage_changed(confirmed, current)
            ),
            "preview_fingerprint": canonical_fingerprint(
                {
                    "node_code": node["node_code"],
                    "revision": int(current["revision_number"]),
                    "semantic_fingerprint": current["semantic_fingerprint"],
                    "diff": diff,
                }
            ),
            "diff": diff,
        }

    def node_revision(self, node_id: UUID, revision_number: int) -> dict[str, Any] | None:
        if revision_number <= 0:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            revision = self._revision_cursor(cursor, node_id, revision_number)
            return self._load_revision_items(dict(revision), cursor=cursor) if revision else None

    def current_revision(self, node_id: UUID) -> dict[str, Any] | None:
        node = self.node_by_id(node_id)
        return self.node_revision(node_id, int(node["current_revision_number"])) if node else None

    def confirmed_revision(self, node_id: UUID) -> dict[str, Any] | None:
        node = self.node_by_id(node_id)
        return self.node_revision(node_id, int(node["confirmed_revision_number"])) if node else None

    def item_versions(self, node_id: UUID, item_key: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT version.*, item.item_key, item.item_type, item.source_item_key,
                       source.source_node_revision_id, source.source_item_version_id,
                       source.relation_type AS source_relation,
                       source.accepted_by, source.accepted_at,
                       source_version.semantic_fingerprint AS source_item_semantic_fingerprint
                FROM content_guided_item_versions AS version
                JOIN content_guided_items AS item ON item.id = version.item_id
                LEFT JOIN content_guided_item_version_sources AS source
                  ON source.item_version_id = version.id
                LEFT JOIN content_guided_item_versions AS source_version
                  ON source_version.id = source.source_item_version_id
                WHERE item.node_id = %s AND item.item_key = %s
                ORDER BY version.version_number
                """,
                (node_id, item_key),
            )
            return [dict(row) for row in cursor.fetchall()]

    def node_by_code(self, project_id: UUID, node_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_guided_nodes WHERE project_id = %s AND node_code = %s",
                (project_id, node_code),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def node_by_id(self, node_id: UUID) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM content_guided_nodes WHERE id = %s", (node_id,))
            row = cursor.fetchone()
        return dict(row) if row else None

    def head(self, project_id: UUID) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM content_guided_project_heads WHERE project_id = %s", (project_id,))
            row = cursor.fetchone()
        return dict(row) if row else None

    def context(self, project_id: UUID) -> dict[str, Any]:
        head = self.head(project_id)
        if head is None or head.get("selected_leaf_node_id") is None:
            return {"head": head, "path": []}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH RECURSIVE path AS (
                    SELECT node.*, 0 AS depth
                    FROM content_guided_nodes AS node
                    WHERE node.id = %s AND node.project_id = %s
                    UNION ALL
                    SELECT parent.*, path.depth + 1
                    FROM content_guided_nodes AS parent
                    JOIN path ON path.parent_node_id = parent.id
                )
                SELECT * FROM path ORDER BY depth DESC
                """,
                (head["selected_leaf_node_id"], project_id),
            )
            nodes = [dict(row) for row in cursor.fetchall()]
        path = []
        for node in nodes:
            revision = self.current_revision(node["id"])
            path.append({**node, "revision": revision})
        return {"head": head, "path": path}

    def context_for_node(self, node_id: UUID) -> dict[str, Any]:
        node = self.node_by_id(node_id)
        if node is None:
            raise KeyError(node_id)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH RECURSIVE path AS (
                    SELECT selected.*, 0 AS depth
                    FROM content_guided_nodes AS selected
                    WHERE selected.id = %s
                    UNION ALL
                    SELECT parent.*, path.depth + 1
                    FROM content_guided_nodes AS parent
                    JOIN path ON path.parent_node_id = parent.id
                )
                SELECT * FROM path ORDER BY depth DESC
                """,
                (node_id,),
            )
            nodes = [dict(row) for row in cursor.fetchall()]
        return {
            "head": self.head(node["project_id"]),
            "path": [
                {**item, "revision": self.current_revision(item["id"])} for item in nodes
            ],
        }

    def tree(self, project_id: UUID, *, include_archived: bool = False) -> dict[str, Any]:
        context = self.context(project_id)
        active_codes = [node["node_code"] for node in context["path"]]
        with self.connection.cursor(row_factory=dict_row) as cursor:
            clauses = ["node.project_id = %s"]
            params: list[Any] = [project_id]
            if not include_archived:
                clauses.append("node.status <> 'archived'")
            cursor.execute(
                f"""
                SELECT node.*, parent.node_code AS parent_node_code,
                       current.semantic_fingerprint AS current_fingerprint,
                       confirmed.semantic_fingerprint AS confirmed_fingerprint,
                       EXISTS (
                           SELECT 1 FROM content_guided_nodes AS child
                           WHERE child.parent_node_id = node.id AND child.status <> 'archived'
                       ) AS has_children
                FROM content_guided_nodes AS node
                LEFT JOIN content_guided_nodes AS parent ON parent.id = node.parent_node_id
                LEFT JOIN content_guided_node_revisions AS current
                  ON current.node_id = node.id
                 AND current.revision_number = node.current_revision_number
                LEFT JOIN content_guided_node_revisions AS confirmed
                  ON confirmed.node_id = node.id
                 AND confirmed.revision_number = node.confirmed_revision_number
                WHERE {' AND '.join(clauses)}
                ORDER BY node.created_at, node.branch_order
                """,
                tuple(params),
            )
            nodes = [dict(row) for row in cursor.fetchall()]
        return {
            "head_revision": int((context.get("head") or {}).get("revision") or 0),
            "active_path": active_codes,
            "nodes": [
                {
                    **node,
                    "has_draft": bool(
                        int(node["current_revision_number"]) != int(node["confirmed_revision_number"])
                    ),
                }
                for node in nodes
            ],
        }

    def select_node(
        self,
        *,
        project_id: UUID,
        node_code: str,
        expected_head_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_guided_project_heads WHERE project_id = %s FOR UPDATE",
                (project_id,),
            )
            head = cursor.fetchone()
            if head is None:
                raise KeyError(project_id)
            if int(head["revision"]) != expected_head_revision:
                raise DomainConflictError(
                    "GUIDED_HEAD_REVISION_CONFLICT", "The selected workflow branch changed since it was loaded"
                )
            cursor.execute(
                "SELECT * FROM content_guided_nodes WHERE project_id = %s AND node_code = %s",
                (project_id, node_code),
            )
            node = cursor.fetchone()
            if node is None:
                raise KeyError(node_code)
            cursor.execute(
                """
                WITH RECURSIVE ancestors AS (
                    SELECT selected.id, selected.parent_node_id, selected.status
                    FROM content_guided_nodes AS selected
                    WHERE selected.id = %s
                    UNION ALL
                    SELECT parent.id, parent.parent_node_id, parent.status
                    FROM content_guided_nodes AS parent
                    JOIN ancestors AS child ON child.parent_node_id = parent.id
                )
                SELECT COALESCE(bool_or(status = 'archived'), false) AS has_archived_node
                FROM ancestors
                """,
                (node["id"],),
            )
            if bool(cursor.fetchone()["has_archived_node"]):
                raise DomainConflictError(
                    "GUIDED_NODE_ARCHIVED",
                    "An archived workflow branch cannot be selected",
                )
            self._select_cursor(cursor, project_id, dict(node), actor_id)
        self.connection.commit()
        return self.context(project_id)

    def update_node(
        self,
        *,
        project_id: UUID,
        node_code: str,
        label: str | None,
        archive: bool | None,
        actor_id: str,
    ) -> dict[str, Any]:
        normalized_label = label.strip() if label is not None else None
        if label is not None and not normalized_label:
            raise DomainValidationError(
                "GUIDED_NODE_LABEL_REQUIRED", "A workflow branch label cannot be empty"
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM content_guided_nodes WHERE project_id = %s AND node_code = %s FOR UPDATE",
                (project_id, node_code),
            )
            node = cursor.fetchone()
            if node is None:
                raise KeyError(node_code)
            if archive is True:
                cursor.execute(
                    """
                    WITH RECURSIVE active_path AS (
                        SELECT selected.id, selected.parent_node_id
                        FROM content_guided_project_heads AS head
                        JOIN content_guided_nodes AS selected
                          ON selected.id = head.selected_leaf_node_id
                        WHERE head.project_id = %s
                        UNION ALL
                        SELECT parent.id, parent.parent_node_id
                        FROM content_guided_nodes AS parent
                        JOIN active_path AS child ON child.parent_node_id = parent.id
                    )
                    SELECT EXISTS (
                        SELECT 1 FROM active_path WHERE id = %s
                    ) AS is_active
                    """,
                    (project_id, node["id"]),
                )
                if bool(cursor.fetchone()["is_active"]):
                    raise DomainConflictError(
                        "GUIDED_ACTIVE_NODE_ARCHIVE_NOT_ALLOWED",
                        "Switch away from the active branch before archiving it",
                    )
            if archive is None:
                cursor.execute(
                    """
                    UPDATE content_guided_nodes
                    SET label = COALESCE(%s, label), updated_at = now()
                    WHERE id = %s RETURNING *
                    """,
                    (normalized_label, node["id"]),
                )
                updated = dict(cursor.fetchone())
            else:
                cursor.execute(
                    """
                    WITH RECURSIVE branch AS (
                        SELECT selected.id
                        FROM content_guided_nodes AS selected
                        WHERE selected.id = %s
                        UNION ALL
                        SELECT child.id
                        FROM content_guided_nodes AS child
                        JOIN branch AS parent ON child.parent_node_id = parent.id
                    )
                    UPDATE content_guided_nodes AS target
                    SET label = CASE
                            WHEN target.id = %s THEN COALESCE(%s, target.label)
                            ELSE target.label
                        END,
                        status = CASE
                            WHEN %s::boolean THEN 'archived'
                            WHEN target.confirmed_revision_number > 0 THEN 'confirmed'
                            ELSE 'draft'
                        END,
                        archived_at = CASE WHEN %s::boolean THEN now() ELSE NULL END,
                        updated_at = now()
                    WHERE target.id IN (SELECT id FROM branch)
                    RETURNING target.*
                    """,
                    (node["id"], node["id"], normalized_label, archive, archive),
                )
                updated_rows = [dict(row) for row in cursor.fetchall()]
                updated = next(row for row in updated_rows if row["id"] == node["id"])
        self.connection.commit()
        return updated

    def mark_node_status(self, node_id: UUID, status: str, *, commit: bool = True) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE content_guided_nodes SET status = %s, updated_at = now() WHERE id = %s",
                (status, node_id),
            )
        if commit:
            self.connection.commit()

    def add_projection(
        self,
        *,
        node_revision_id: UUID,
        artifact_type: str,
        artifact_code: str,
        revision_number: int | None,
        fingerprint_sha256: str | None,
        commit: bool = True,
    ) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO content_guided_revision_projections (
                    node_revision_id, artifact_type, artifact_code,
                    revision_number, fingerprint_sha256
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (node_revision_id, artifact_type, artifact_code)
                DO UPDATE SET revision_number = EXCLUDED.revision_number,
                              fingerprint_sha256 = EXCLUDED.fingerprint_sha256
                """,
                (
                    node_revision_id,
                    artifact_type,
                    artifact_code,
                    revision_number,
                    fingerprint_sha256,
                ),
            )
        if commit:
            self.connection.commit()

    def update_revision_canonical_refs(
        self,
        revision_id: UUID,
        canonical_refs: dict[str, Any],
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE content_guided_node_revisions
                SET canonical_refs = canonical_refs || %s, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (Jsonb(canonical_refs), revision_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise KeyError(revision_id)
        if commit:
            self.connection.commit()
        return dict(row)

    @staticmethod
    def stage_node(context: dict[str, Any], stage: str) -> dict[str, Any] | None:
        return next((node for node in context.get("path") or [] if node["stage"] == stage), None)

    @staticmethod
    def _setup_label(content: dict[str, Any]) -> str:
        theme = str(content.get("theme") or "未命名主题").strip()
        return theme[:80]

    @staticmethod
    def _validate_stage_parent(stage: str, parent_node_id: UUID | None) -> None:
        if stage not in _STAGE_ORDER:
            raise DomainValidationError("GUIDED_TREE_STAGE_INVALID", "Unknown guided workflow stage")
        if stage == "setup" and parent_node_id is not None:
            raise DomainValidationError("GUIDED_SETUP_PARENT_INVALID", "Setup branches must be tree roots")
        if stage != "setup" and parent_node_id is None:
            raise DomainValidationError("GUIDED_TREE_PARENT_REQUIRED", "A downstream workflow node requires a parent")

    def _select_cursor(
        self, cursor: Any, project_id: UUID, selected: dict[str, Any], actor_id: str
    ) -> None:
        ancestors: list[dict[str, Any]] = [selected]
        current = selected
        while current.get("parent_node_id") is not None:
            cursor.execute("SELECT * FROM content_guided_nodes WHERE id = %s", (current["parent_node_id"],))
            parent = cursor.fetchone()
            if parent is None:
                raise DomainConflictError("GUIDED_TREE_BROKEN", "The workflow branch has a missing parent")
            ancestors.append(dict(parent))
            current = dict(parent)
        ancestors.reverse()
        for parent, child in zip(ancestors, ancestors[1:], strict=False):
            cursor.execute(
                """
                INSERT INTO content_guided_child_selections (
                    project_id, parent_node_id, selected_child_node_id, revision, updated_by
                ) VALUES (%s, %s, %s, 1, %s)
                ON CONFLICT (project_id, parent_node_id)
                DO UPDATE SET selected_child_node_id = EXCLUDED.selected_child_node_id,
                              revision = content_guided_child_selections.revision + 1,
                              updated_by = EXCLUDED.updated_by, updated_at = now()
                """,
                (project_id, parent["id"], child["id"], actor_id),
            )
        leaf = selected
        seen = {leaf["id"]}
        while True:
            cursor.execute(
                """
                SELECT child.*
                FROM content_guided_child_selections AS selection
                JOIN content_guided_nodes AS child ON child.id = selection.selected_child_node_id
                WHERE selection.project_id = %s AND selection.parent_node_id = %s
                  AND child.status <> 'archived'
                """,
                (project_id, leaf["id"]),
            )
            child = cursor.fetchone()
            if child is None or child["id"] in seen:
                break
            leaf = dict(child)
            seen.add(leaf["id"])
        root = ancestors[0]
        cursor.execute(
            """
            INSERT INTO content_guided_project_heads (
                project_id, project_code, selected_root_node_id,
                selected_leaf_node_id, revision, updated_by
            ) VALUES (%s, %s, %s, %s, 1, %s)
            ON CONFLICT (project_id)
            DO UPDATE SET selected_root_node_id = EXCLUDED.selected_root_node_id,
                          selected_leaf_node_id = EXCLUDED.selected_leaf_node_id,
                          revision = content_guided_project_heads.revision + 1,
                          updated_by = EXCLUDED.updated_by, updated_at = now()
            """,
            (project_id, selected["project_code"], root["id"], leaf["id"], actor_id),
        )

    @staticmethod
    def _revision_cursor(cursor: Any, node_id: UUID, revision_number: int) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT * FROM content_guided_node_revisions
            WHERE node_id = %s AND revision_number = %s
            """,
            (node_id, revision_number),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _load_revision_items(revision: dict[str, Any], *, cursor: Any) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT item.id AS item_id, item.item_key, item.item_type, item.source_item_key,
                   version.id AS item_version_id, version.version_number,
                   version.content, version.semantic_fingerprint,
                   version.input_fingerprint, version.lineage_fingerprint,
                   version.producer_kind, version.producer_ref, version.guidance,
                   version.invocation_evidence_ref, version.created_by,
                   version.created_at, composition.sort_order,
                   source.source_node_revision_id, source.source_item_version_id,
                   source.relation_type AS source_relation
                   , source_version.semantic_fingerprint AS source_item_semantic_fingerprint
            FROM content_guided_node_revision_items AS composition
            JOIN content_guided_items AS item ON item.id = composition.item_id
            JOIN content_guided_item_versions AS version ON version.id = composition.item_version_id
            LEFT JOIN content_guided_item_version_sources AS source
              ON source.item_version_id = version.id
            LEFT JOIN content_guided_item_versions AS source_version
              ON source_version.id = source.source_item_version_id
            WHERE composition.node_revision_id = %s
            ORDER BY composition.sort_order
            """,
            (revision["id"],),
        )
        return {**revision, "items": [dict(row) for row in cursor.fetchall()]}

    @staticmethod
    def _item_cursor(
        cursor: Any,
        *,
        node_id: UUID,
        item_key: str,
        item_type: str,
        source_item_key: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            "SELECT * FROM content_guided_items WHERE node_id = %s AND item_key = %s",
            (node_id, item_key),
        )
        row = cursor.fetchone()
        if row:
            if row["item_type"] != item_type:
                raise DomainValidationError(
                    "GUIDED_ITEM_TYPE_CONFLICT", "The workflow item key is already used by another item type"
                )
            return dict(row)
        cursor.execute(
            """
            INSERT INTO content_guided_items (
                node_id, item_key, item_type, source_item_key, created_by
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (node_id, item_key, item_type, source_item_key, actor_id),
        )
        return dict(cursor.fetchone())

    @staticmethod
    def _item_version_cursor(cursor: Any, item_version_id: UUID) -> dict[str, Any] | None:
        cursor.execute("SELECT * FROM content_guided_item_versions WHERE id = %s", (item_version_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def _create_item_version_cursor(
        self,
        cursor: Any,
        *,
        item: dict[str, Any],
        content: dict[str, Any],
        actor_id: str,
        producer_kind: str,
        producer_ref: str | None,
        guidance: str | None,
        invocation_evidence_ref: str | None,
        source_node_revision_id: UUID | str | None,
        source_item_version_id: UUID | str | None,
        source_relation: str,
    ) -> dict[str, Any]:
        semantic_fingerprint = canonical_fingerprint(content)
        input_payload = {
            "source_node_revision_id": str(source_node_revision_id or ""),
            "source_item_version_id": str(source_item_version_id or ""),
            "guidance": (guidance or "").strip(),
        }
        input_fingerprint = canonical_fingerprint(input_payload)
        lineage_fingerprint = canonical_fingerprint(
            {"semantic_fingerprint": semantic_fingerprint, "input": input_payload}
        )
        cursor.execute(
            """
            SELECT * FROM content_guided_item_versions
            WHERE item_id = %s AND semantic_fingerprint = %s AND lineage_fingerprint = %s
            ORDER BY version_number DESC LIMIT 1
            """,
            (item["id"], semantic_fingerprint, lineage_fingerprint),
        )
        existing = cursor.fetchone()
        if existing:
            return dict(existing)
        cursor.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
            FROM content_guided_item_versions WHERE item_id = %s
            """,
            (item["id"],),
        )
        version_number = int(cursor.fetchone()["next_version"])
        cursor.execute(
            """
            INSERT INTO content_guided_item_versions (
                item_id, version_number, content, semantic_fingerprint,
                input_fingerprint, lineage_fingerprint, producer_kind,
                producer_ref, guidance, invocation_evidence_ref, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                item["id"],
                version_number,
                Jsonb(content),
                semantic_fingerprint,
                input_fingerprint,
                lineage_fingerprint,
                producer_kind,
                producer_ref,
                guidance.strip() if guidance else None,
                invocation_evidence_ref,
                actor_id,
            ),
        )
        version = dict(cursor.fetchone())
        if source_node_revision_id or source_item_version_id:
            cursor.execute(
                """
                INSERT INTO content_guided_item_version_sources (
                    item_version_id, source_node_revision_id, source_item_version_id,
                    relation_type, accepted_by, accepted_at
                ) VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'reaffirmed_from' THEN now() ELSE NULL END)
                """,
                (
                    version["id"],
                    source_node_revision_id,
                    source_item_version_id,
                    source_relation,
                    actor_id if source_relation == "reaffirmed_from" else None,
                    source_relation,
                ),
            )
        return version

    @staticmethod
    def _revision_diff(
        previous: dict[str, Any] | None, current: dict[str, Any]
    ) -> dict[str, Any]:
        if previous is None:
            return {
                "initial": True,
                "added": [item["item_key"] for item in current.get("items") or []],
                "removed": [],
                "changed": [],
                "reordered": False,
                "content_changed": True,
            }
        old_items = {item["item_key"]: item for item in previous.get("items") or []}
        new_items = {item["item_key"]: item for item in current.get("items") or []}
        old_order = [item["item_key"] for item in previous.get("items") or []]
        new_order = [item["item_key"] for item in current.get("items") or []]
        return {
            "initial": False,
            "added": [key for key in new_order if key not in old_items],
            "removed": [key for key in old_order if key not in new_items],
            "changed": [
                key
                for key in new_order
                if key in old_items
                and new_items[key]["semantic_fingerprint"] != old_items[key]["semantic_fingerprint"]
            ],
            "reordered": [key for key in old_order if key in new_items]
            != [key for key in new_order if key in old_items],
            "content_changed": canonical_fingerprint(previous.get("content") or {})
            != canonical_fingerprint(current.get("content") or {}),
        }

    @staticmethod
    def _applicability_lineage_changed(
        previous: dict[str, Any], current: dict[str, Any]
    ) -> bool:
        if str(previous.get("source_parent_revision_id") or "") != str(
            current.get("source_parent_revision_id") or ""
        ):
            return True
        previous_items = {item["item_key"]: item for item in previous.get("items") or []}
        for item in current.get("items") or []:
            old = previous_items.get(item["item_key"])
            if old is None:
                continue
            if item.get("source_relation") == "reaffirmed_from":
                return True
            if str(old.get("source_item_semantic_fingerprint") or "") != str(
                item.get("source_item_semantic_fingerprint") or ""
            ):
                return True
        return False


def version_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]

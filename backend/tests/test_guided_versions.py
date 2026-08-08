from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from pglast import parse_sql


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
for source_root in (REPO_ROOT, BACKEND_ROOT):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from app.domain.errors import DomainConflictError, DomainValidationError  # noqa: E402
from app.repositories.content_core import ContentCoreRepository  # noqa: E402
from app.repositories.guided_versions import GuidedVersionRepository  # noqa: E402
from app.services.content_workflow import GuidedContentWorkflowService  # noqa: E402
from scripts.apply_migrations import apply_migrations  # noqa: E402


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
MIGRATION = BACKEND_ROOT / "migrations" / "115_guided_workflow_branch_tree.sql"
SOURCE_CASCADE_MIGRATION = BACKEND_ROOT / "migrations" / "116_guided_item_source_cascade.sql"
SOURCE_TARGET_MIGRATION = (
    BACKEND_ROOT / "migrations" / "117_restore_guided_item_version_source_target_fk.sql"
)
GUIDED_TABLES = {
    "content_guided_nodes",
    "content_guided_node_revisions",
    "content_guided_items",
    "content_guided_item_versions",
    "content_guided_node_revision_items",
    "content_guided_item_version_sources",
    "content_guided_project_heads",
    "content_guided_child_selections",
    "content_guided_revision_projections",
}


@pytest.fixture(scope="session")
def migrated_database() -> str:
    if not DATABASE_URL:
        pytest.skip("ASSETGRAPH_TEST_DATABASE_URL is not configured")
    apply_migrations(
        DATABASE_URL, [MIGRATION, SOURCE_CASCADE_MIGRATION, SOURCE_TARGET_MIGRATION]
    )
    return DATABASE_URL


@pytest.fixture
def guided_project(
    migrated_database: str,
) -> Iterator[tuple[psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]]]:
    connection = psycopg.connect(migrated_database)
    setup_content = {
        "workflow_version": "guided-live.v1",
        "theme": f"Guided repository test {uuid4().hex[:8]}",
        "room_id": "test-room-001",
        "selected_asset_codes": ["ASSET-TEST-001"],
        "pinned_knowledge_refs": [{"knowledge_code": "KNOWLEDGE-TEST-001", "revision": 1}],
    }
    project = ContentCoreRepository(connection).create_project(
        title=f"Guided repository test {uuid4().hex[:10]}",
        generation_goal="Exercise branch-aware guided authoring",
        content=setup_content,
        actor_id="guided-test-operator",
    )
    repository = GuidedVersionRepository(connection)
    try:
        yield connection, repository, project, setup_content
    finally:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM content_projects WHERE id = %s", (project["project_id"],))
        connection.commit()
        connection.close()


def _project_id(project: dict[str, Any]) -> UUID:
    return UUID(str(project["project_id"]))


def _setup_node(
    repository: GuidedVersionRepository,
    project: dict[str, Any],
    setup_content: dict[str, Any],
) -> dict[str, Any]:
    repository.ensure_initial_setup(
        project=project,
        content=setup_content,
        actor_id="guided-test-operator",
    )
    context = repository.context(_project_id(project))
    assert len(context["path"]) == 1
    return context["path"][0]


def _create_node(
    repository: GuidedVersionRepository,
    project: dict[str, Any],
    *,
    stage: str,
    parent_node_id: UUID,
    label: str,
    select: bool = True,
) -> dict[str, Any]:
    return repository.create_node(
        project_id=_project_id(project),
        project_code=str(project["project_code"]),
        stage=stage,
        parent_node_id=parent_node_id,
        label=label,
        actor_id="guided-test-operator",
        select=select,
    )


def _save_single_item(
    repository: GuidedVersionRepository,
    node: dict[str, Any],
    *,
    expected_revision: int,
    item_key: str,
    text: str,
    guidance: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "item_key": item_key,
        "content": {"title": text, "summary": text},
    }
    if guidance is not None:
        item["guidance"] = guidance
    return repository.save_revision(
        node_id=node["id"],
        expected_revision=expected_revision,
        content={"objective": "Repository contract test"},
        items=[item],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
    )


def _seed_two_item_lineage(
    repository: GuidedVersionRepository,
    project: dict[str, Any],
    setup_content: dict[str, Any],
) -> dict[str, Any]:
    """Create a confirmed outline, script, and storyboard with matching item keys."""
    setup = _setup_node(repository, project, setup_content)
    outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Two section outline",
    )
    outline_revision = repository.save_revision(
        node_id=outline["id"],
        expected_revision=0,
        content={"objective": "Lineage assertions"},
        items=[
            {"item_key": "section-1", "content": {"summary": "First outline"}},
            {"item_key": "section-2", "content": {"summary": "Second outline"}},
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
    )
    repository.confirm_revision(
        node_id=outline["id"],
        expected_revision=outline_revision["revision_number"],
        actor_id="guided-test-operator",
    )
    script = _create_node(
        repository,
        project,
        stage="script",
        parent_node_id=outline["id"],
        label="Two block script",
    )
    script_revision = repository.save_revision(
        node_id=script["id"],
        expected_revision=0,
        content={"title": "Lineage script"},
        items=[
            {
                "item_key": item["item_key"],
                "item_type": "script_block",
                "source_item_key": item["item_key"],
                "content": {"speech": f"Speech for {item['item_key']}"},
                "source_node_revision_id": outline_revision["id"],
                "source_item_version_id": item["item_version_id"],
            }
            for item in outline_revision["items"]
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
        source_parent_revision_id=outline_revision["id"],
    )
    repository.confirm_revision(
        node_id=script["id"],
        expected_revision=script_revision["revision_number"],
        actor_id="guided-test-operator",
    )
    storyboard = _create_node(
        repository,
        project,
        stage="storyboard",
        parent_node_id=script["id"],
        label="Two scene storyboard",
    )
    storyboard_revision = repository.save_revision(
        node_id=storyboard["id"],
        expected_revision=0,
        content={"template_code": "TEST-TEMPLATE"},
        items=[
            {
                "item_key": item["item_key"],
                "item_type": "storyboard_scene",
                "source_item_key": item["item_key"],
                "content": {"shot_code": item["item_key"], "title": item["item_key"]},
                "source_node_revision_id": script_revision["id"],
                "source_item_version_id": item["item_version_id"],
            }
            for item in script_revision["items"]
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
        source_parent_revision_id=script_revision["id"],
    )
    repository.confirm_revision(
        node_id=storyboard["id"],
        expected_revision=storyboard_revision["revision_number"],
        actor_id="guided-test-operator",
    )
    return {
        "outline": outline,
        "outline_revision": outline_revision,
        "script": script,
        "script_revision": script_revision,
        "storyboard": storyboard,
        "storyboard_revision": storyboard_revision,
    }


def test_guided_branch_tree_migration_parses_and_declares_required_contract() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    parse_sql(sql)
    for table in GUIDED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "UNIQUE (node_id, item_key)" in sql
    assert "UNIQUE (item_id, version_number)" in sql
    assert "PRIMARY KEY (project_id, parent_node_id)" in sql
    assert "idx_content_guided_setup_branch_order" in sql
    assert "target_node_id UUID REFERENCES content_guided_nodes(id)" in sql
    assert "target_node_revision INTEGER" in sql
    assert "target_item_id UUID REFERENCES content_guided_items(id)" in sql


def test_migration_installs_guided_tables_and_generation_job_targets(
    migrated_database: str,
) -> None:
    with psycopg.connect(migrated_database) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s::text[])
                """,
                (sorted(GUIDED_TABLES),),
            )
            installed_tables = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'content_generation_jobs'
                  AND column_name = ANY(%s::text[])
                """,
                (["target_node_id", "target_node_revision", "target_item_id"],),
            )
            target_columns = {row[0] for row in cursor.fetchall()}

    assert installed_tables == GUIDED_TABLES
    assert target_columns == {"target_node_id", "target_node_revision", "target_item_id"}


def test_initial_setup_is_idempotent_and_establishes_head_and_active_path(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    project_id = _project_id(project)

    created = repository.ensure_initial_setup(
        project=project,
        content=setup_content,
        actor_id="guided-test-operator",
    )
    repeated = repository.ensure_initial_setup(
        project=project,
        content=setup_content,
        actor_id="guided-test-operator",
    )
    persisted = repository.context(project_id)
    tree = repository.tree(project_id)

    assert created["head"]["revision"] == 1
    assert created["head"]["selected_root_node_id"] == created["head"]["selected_leaf_node_id"]
    assert len(created["path"]) == 1
    assert created["path"][0]["stage"] == "setup"
    assert created["path"][0]["revision"]["revision_number"] == 1
    assert repeated["head"]["revision"] == 1
    assert repeated["path"][0]["id"] == created["path"][0]["id"]
    assert persisted["path"][0]["current_revision_number"] == 1
    assert persisted["path"][0]["revision"]["content"] == setup_content
    assert tree["head_revision"] == 1
    assert tree["active_path"] == [created["path"][0]["node_code"]]


def test_sibling_branches_keep_same_key_items_and_versions_isolated(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    setup = _setup_node(repository, project, setup_content)
    first = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Outline branch A",
    )
    _save_single_item(
        repository,
        first,
        expected_revision=0,
        item_key="section-1",
        text="Branch A section",
    )
    second = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Outline branch B",
    )
    _save_single_item(
        repository,
        second,
        expected_revision=0,
        item_key="section-1",
        text="Branch B section",
    )

    first_versions = repository.item_versions(first["id"], "section-1")
    second_versions = repository.item_versions(second["id"], "section-1")
    tree = repository.tree(_project_id(project))
    outlines = [node for node in tree["nodes"] if node["stage"] == "outline"]

    assert [version["version_number"] for version in first_versions] == [1]
    assert [version["version_number"] for version in second_versions] == [1]
    assert first_versions[0]["item_id"] != second_versions[0]["item_id"]
    assert first_versions[0]["content"]["summary"] == "Branch A section"
    assert second_versions[0]["content"]["summary"] == "Branch B section"
    assert {node["parent_node_id"] for node in outlines} == {setup["id"]}
    assert {node["branch_order"] for node in outlines} == {1, 2}
    assert tree["active_path"][-1] == second["node_code"]


def test_item_versions_are_local_to_a_node_and_can_be_reselected(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    setup = _setup_node(repository, project, setup_content)
    outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Versioned outline",
    )
    first = repository.save_revision(
        node_id=outline["id"],
        expected_revision=0,
        content={"objective": "Version selection"},
        items=[
            {"item_key": "section-1", "content": {"summary": "Version one"}},
            {"item_key": "section-2", "content": {"summary": "Stable section"}},
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
    )
    second = repository.save_revision(
        node_id=outline["id"],
        expected_revision=1,
        content={"objective": "Version selection"},
        items=[
            {"item_key": "section-1", "content": {"summary": "Version two"}},
            {"item_key": "section-2", "content": {"summary": "Stable section"}},
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
    )
    section_one_versions = repository.item_versions(outline["id"], "section-1")
    section_two_versions = repository.item_versions(outline["id"], "section-2")
    restored = repository.save_revision(
        node_id=outline["id"],
        expected_revision=2,
        content={"objective": "Version selection"},
        items=[
            {
                "item_key": "section-1",
                "item_version_id": section_one_versions[0]["id"],
            },
            {
                "item_key": "section-2",
                "item_version_id": section_two_versions[0]["id"],
            },
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
    )

    assert first["items"][0]["version_number"] == 1
    assert second["items"][0]["version_number"] == 2
    assert second["items"][1]["item_version_id"] == first["items"][1]["item_version_id"]
    assert [version["version_number"] for version in section_one_versions] == [1, 2]
    assert [version["version_number"] for version in section_two_versions] == [1]
    assert restored["revision_number"] == 3
    assert restored["items"][0]["version_number"] == 1
    assert len(repository.item_versions(outline["id"], "section-1")) == 2


def test_noop_confirmation_discards_unchanged_draft_and_preserves_child_path(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    setup = _setup_node(repository, project, setup_content)
    outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Confirmed outline",
    )
    first = _save_single_item(
        repository,
        outline,
        expected_revision=0,
        item_key="section-1",
        text="Unchanged section",
    )
    repository.confirm_revision(
        node_id=outline["id"],
        expected_revision=first["revision_number"],
        actor_id="guided-test-operator",
    )
    script = _create_node(
        repository,
        project,
        stage="script",
        parent_node_id=outline["id"],
        label="Remembered script child",
    )
    _save_single_item(
        repository,
        script,
        expected_revision=0,
        item_key="section-1",
        text="Script content",
    )
    head_before = repository.head(_project_id(project))
    unchanged_draft = _save_single_item(
        repository,
        outline,
        expected_revision=1,
        item_key="section-1",
        text="Unchanged section",
        guidance="Reviewed and accepted without semantic changes",
    )
    preview = repository.confirmation_preview(outline["id"])
    result = repository.confirm_revision(
        node_id=outline["id"],
        expected_revision=unchanged_draft["revision_number"],
        actor_id="guided-test-operator",
    )
    persisted_node = repository.node_by_id(outline["id"])
    discarded = repository.node_revision(outline["id"], 2)
    context = repository.context(_project_id(project))

    assert preview["changed"] is False
    assert preview["diff"]["changed"] == []
    assert preview["diff"]["content_changed"] is False
    assert result["outcome"] == "unchanged"
    assert result["revision"]["revision_number"] == 1
    assert persisted_node is not None
    assert persisted_node["current_revision_number"] == 1
    assert persisted_node["confirmed_revision_number"] == 1
    assert discarded is not None and discarded["status"] == "discarded"
    assert context["path"][-1]["node_code"] == script["node_code"]
    assert context["head"]["revision"] == head_before["revision"]


def test_edit_after_noop_confirmation_uses_the_next_unused_revision_number(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    setup = _setup_node(repository, project, setup_content)
    outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="No-op revision sequence",
    )
    first = _save_single_item(
        repository,
        outline,
        expected_revision=0,
        item_key="section-1",
        text="Original section",
    )
    repository.confirm_revision(
        node_id=outline["id"],
        expected_revision=first["revision_number"],
        actor_id="guided-test-operator",
    )
    no_op = _save_single_item(
        repository,
        outline,
        expected_revision=1,
        item_key="section-1",
        text="Original section",
        guidance="No semantic change",
    )
    repository.confirm_revision(
        node_id=outline["id"],
        expected_revision=no_op["revision_number"],
        actor_id="guided-test-operator",
    )

    next_revision = _save_single_item(
        repository,
        outline,
        expected_revision=1,
        item_key="section-1",
        text="Actually changed section",
    )

    assert next_revision["revision_number"] == 3


def test_selecting_a_parent_restores_its_remembered_child_path(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    project_id = _project_id(project)
    setup = _setup_node(repository, project, setup_content)
    outline_a = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Outline A",
    )
    script_a = _create_node(
        repository,
        project,
        stage="script",
        parent_node_id=outline_a["id"],
        label="Script A",
    )
    outline_b = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Outline B",
    )
    script_b = _create_node(
        repository,
        project,
        stage="script",
        parent_node_id=outline_b["id"],
        label="Script B",
    )

    selected_a = repository.select_node(
        project_id=project_id,
        node_code=outline_a["node_code"],
        expected_head_revision=repository.head(project_id)["revision"],
        actor_id="guided-test-operator",
    )
    selected_b = repository.select_node(
        project_id=project_id,
        node_code=outline_b["node_code"],
        expected_head_revision=selected_a["head"]["revision"],
        actor_id="guided-test-operator",
    )

    assert [node["node_code"] for node in selected_a["path"]] == [
        setup["node_code"],
        outline_a["node_code"],
        script_a["node_code"],
    ]
    assert [node["node_code"] for node in selected_b["path"]] == [
        setup["node_code"],
        outline_b["node_code"],
        script_b["node_code"],
    ]


def test_select_node_rejects_stale_head_revision_without_changing_selection(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    project_id = _project_id(project)
    setup = _setup_node(repository, project, setup_content)
    first = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="First branch",
        select=False,
    )
    second = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Second branch",
        select=False,
    )
    stale_head_revision = repository.head(project_id)["revision"]
    selected = repository.select_node(
        project_id=project_id,
        node_code=first["node_code"],
        expected_head_revision=stale_head_revision,
        actor_id="guided-test-operator",
    )

    with pytest.raises(DomainConflictError) as conflict:
        repository.select_node(
            project_id=project_id,
            node_code=second["node_code"],
            expected_head_revision=stale_head_revision,
            actor_id="guided-test-operator",
        )

    persisted = repository.context(project_id)
    assert conflict.value.code == "GUIDED_HEAD_REVISION_CONFLICT"
    assert persisted["head"]["revision"] == selected["head"]["revision"]
    assert persisted["path"][-1]["node_code"] == first["node_code"]


@pytest.mark.parametrize("target_stage", ["setup", "outline", "script", "storyboard"])
def test_active_path_nodes_cannot_be_archived(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
    target_stage: str,
) -> None:
    _connection, repository, project, setup_content = guided_project
    project_id = _project_id(project)
    setup = _setup_node(repository, project, setup_content)
    outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Active outline",
    )
    script = _create_node(
        repository,
        project,
        stage="script",
        parent_node_id=outline["id"],
        label="Active script",
    )
    storyboard = _create_node(
        repository,
        project,
        stage="storyboard",
        parent_node_id=script["id"],
        label="Active storyboard",
    )
    nodes = {
        "setup": setup,
        "outline": outline,
        "script": script,
        "storyboard": storyboard,
    }
    active_path_before = repository.tree(project_id)["active_path"]

    with pytest.raises(DomainConflictError) as conflict:
        repository.update_node(
            project_id=project_id,
            node_code=nodes[target_stage]["node_code"],
            label=None,
            archive=True,
            actor_id="guided-test-operator",
        )

    tree_after = repository.tree(project_id, include_archived=True)
    persisted = next(
        node for node in tree_after["nodes"] if node["node_code"] == nodes[target_stage]["node_code"]
    )
    assert conflict.value.code == "GUIDED_ACTIVE_NODE_ARCHIVE_NOT_ALLOWED"
    assert tree_after["active_path"] == active_path_before
    assert persisted["status"] != "archived"


def test_archiving_an_inactive_parent_archives_and_restores_its_entire_subtree(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    project_id = _project_id(project)
    setup = _setup_node(repository, project, setup_content)
    inactive_outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=setup["id"],
        label="Inactive parent branch",
        select=False,
    )
    inactive_script = _create_node(
        repository,
        project,
        stage="script",
        parent_node_id=inactive_outline["id"],
        label="Inactive child script",
        select=False,
    )
    inactive_storyboard = _create_node(
        repository,
        project,
        stage="storyboard",
        parent_node_id=inactive_script["id"],
        label="Inactive child storyboard",
        select=False,
    )
    subtree_codes = {
        inactive_outline["node_code"],
        inactive_script["node_code"],
        inactive_storyboard["node_code"],
    }

    repository.update_node(
        project_id=project_id,
        node_code=inactive_outline["node_code"],
        label=None,
        archive=True,
        actor_id="guided-test-operator",
    )
    archived_tree = repository.tree(project_id, include_archived=True)
    archived_statuses = {
        node["node_code"]: node["status"]
        for node in archived_tree["nodes"]
        if node["node_code"] in subtree_codes
    }

    assert archived_statuses == {code: "archived" for code in subtree_codes}
    with pytest.raises(DomainConflictError) as blocked_child_selection:
        repository.select_node(
            project_id=project_id,
            node_code=inactive_storyboard["node_code"],
            expected_head_revision=repository.head(project_id)["revision"],
            actor_id="guided-test-operator",
        )
    assert blocked_child_selection.value.code == "GUIDED_NODE_ARCHIVED"

    repository.update_node(
        project_id=project_id,
        node_code=inactive_outline["node_code"],
        label=None,
        archive=False,
        actor_id="guided-test-operator",
    )
    restored_tree = repository.tree(project_id, include_archived=True)
    restored_nodes = {
        node["node_code"]: node
        for node in restored_tree["nodes"]
        if node["node_code"] in subtree_codes
    }
    selected = repository.select_node(
        project_id=project_id,
        node_code=inactive_storyboard["node_code"],
        expected_head_revision=repository.head(project_id)["revision"],
        actor_id="guided-test-operator",
    )

    assert all(node["status"] != "archived" for node in restored_nodes.values())
    assert all(node["archived_at"] is None for node in restored_nodes.values())
    assert [node["node_code"] for node in selected["path"]] == [
        setup["node_code"],
        inactive_outline["node_code"],
        inactive_script["node_code"],
        inactive_storyboard["node_code"],
    ]


def test_item_version_from_another_parent_branch_cannot_be_selected(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    _connection, repository, project, setup_content = guided_project
    first_setup = _setup_node(repository, project, setup_content)
    second_setup = repository.create_node(
        project_id=_project_id(project),
        project_code=str(project["project_code"]),
        stage="setup",
        parent_node_id=None,
        label="Second setup branch",
        actor_id="guided-test-operator",
    )
    repository.save_revision(
        node_id=second_setup["id"],
        expected_revision=0,
        content={**setup_content, "theme": "Second setup theme"},
        items=[],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
    )
    first_outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=first_setup["id"],
        label="First parent branch outline",
    )
    second_outline = _create_node(
        repository,
        project,
        stage="outline",
        parent_node_id=second_setup["id"],
        label="Second parent branch outline",
    )
    _save_single_item(
        repository,
        first_outline,
        expected_revision=0,
        item_key="section-1",
        text="First branch version",
    )
    second_revision = _save_single_item(
        repository,
        second_outline,
        expected_revision=0,
        item_key="section-1",
        text="Second branch version",
    )
    foreign_version = repository.item_versions(first_outline["id"], "section-1")[0]

    with pytest.raises(DomainValidationError) as invalid_scope:
        repository.save_revision(
            node_id=second_outline["id"],
            expected_revision=second_revision["revision_number"],
            content={"objective": "Cross-branch selection must fail"},
            items=[
                {
                    "item_key": "section-1",
                    "item_version_id": foreign_version["id"],
                }
            ],
            actor_id="guided-test-operator",
            producer_kind="human",
            producer_ref="guided-version-test",
        )

    persisted = repository.current_revision(second_outline["id"])
    assert invalid_scope.value.code == "GUIDED_ITEM_VERSION_SCOPE_INVALID"
    assert persisted is not None
    assert persisted["revision_number"] == second_revision["revision_number"]
    assert persisted["items"][0]["content"]["summary"] == "Second branch version"


def test_changing_one_script_block_only_stales_its_matching_storyboard_scene(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    connection, repository, project, setup_content = guided_project
    seeded = _seed_two_item_lineage(repository, project, setup_content)
    script_revision = seeded["script_revision"]
    outline_revision = seeded["outline_revision"]

    changed_script = repository.save_revision(
        node_id=seeded["script"]["id"],
        expected_revision=script_revision["revision_number"],
        content={"title": "Lineage script"},
        items=[
            {
                "item_key": "section-1",
                "item_type": "script_block",
                "source_item_key": "section-1",
                "content": {"speech": "Changed first speech"},
                "source_node_revision_id": outline_revision["id"],
                "source_item_version_id": outline_revision["items"][0]["item_version_id"],
            },
            {
                "item_key": "section-2",
                "item_version_id": script_revision["items"][1]["item_version_id"],
            },
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
        source_parent_revision_id=outline_revision["id"],
    )
    context = repository.context_for_node(seeded["storyboard"]["id"])
    nodes_by_stage = {node["stage"]: node for node in context["path"]}
    view = GuidedContentWorkflowService(connection)._version_storyboard_view(
        nodes_by_stage["storyboard"], nodes_by_stage["script"]
    )

    assert changed_script["revision_number"] == 2
    assert view is not None
    assert {
        scene["shot_code"]: scene["stale"] for scene in view["blueprint"]["scenes"]
    } == {"section-1": True, "section-2": False}


def test_reaffirmed_script_item_updates_lineage_without_staling_storyboard(
    guided_project: tuple[
        psycopg.Connection[Any], GuidedVersionRepository, dict[str, Any], dict[str, Any]
    ],
) -> None:
    connection, repository, project, setup_content = guided_project
    seeded = _seed_two_item_lineage(repository, project, setup_content)
    outline_revision = seeded["outline_revision"]
    script_revision = seeded["script_revision"]

    updated_outline = repository.save_revision(
        node_id=seeded["outline"]["id"],
        expected_revision=outline_revision["revision_number"],
        content={"objective": "Lineage assertions"},
        items=[
            {"item_key": "section-1", "content": {"summary": "Changed first outline"}},
            {
                "item_key": "section-2",
                "item_version_id": outline_revision["items"][1]["item_version_id"],
            },
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
    )
    repository.confirm_revision(
        node_id=seeded["outline"]["id"],
        expected_revision=updated_outline["revision_number"],
        actor_id="guided-test-operator",
    )
    reaffirmed_script = repository.save_revision(
        node_id=seeded["script"]["id"],
        expected_revision=script_revision["revision_number"],
        content={"title": "Lineage script"},
        items=[
            {
                "item_key": "section-1",
                "item_type": "script_block",
                "source_item_key": "section-1",
                "content": script_revision["items"][0]["content"],
                "source_node_revision_id": updated_outline["id"],
                "source_item_version_id": updated_outline["items"][0]["item_version_id"],
                "source_relation": "reaffirmed_from",
            },
            {
                "item_key": "section-2",
                "item_version_id": script_revision["items"][1]["item_version_id"],
            },
        ],
        actor_id="guided-test-operator",
        producer_kind="human",
        producer_ref="guided-version-test",
        source_parent_revision_id=updated_outline["id"],
    )
    preview = repository.confirmation_preview(seeded["script"]["id"])
    confirmed = repository.confirm_revision(
        node_id=seeded["script"]["id"],
        expected_revision=reaffirmed_script["revision_number"],
        actor_id="guided-test-operator",
    )
    context = repository.context_for_node(seeded["storyboard"]["id"])
    nodes_by_stage = {node["stage"]: node for node in context["path"]}
    view = GuidedContentWorkflowService(connection)._version_storyboard_view(
        nodes_by_stage["storyboard"], nodes_by_stage["script"]
    )

    assert preview["changed"] is False
    assert preview["lineage_changed"] is True
    assert confirmed["outcome"] == "reaffirmed"
    assert reaffirmed_script["items"][0]["semantic_fingerprint"] == script_revision["items"][0][
        "semantic_fingerprint"
    ]
    assert reaffirmed_script["items"][0]["source_item_version_id"] == updated_outline["items"][0][
        "item_version_id"
    ]
    assert view is not None
    assert all(scene["stale"] is False for scene in view["blueprint"]["scenes"])

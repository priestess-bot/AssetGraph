from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.repositories.console_entities import ConsoleEntityRepository, structured_diff


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_structured_diff_preserves_nested_paths_and_change_kinds() -> None:
    changes = structured_diff(
        {"goal": "old", "facts": ["a", "b"], "removed": True},
        {"goal": "new", "facts": ["a", "c", "d"], "added": {"ready": True}},
    )

    assert changes == [
        {"path": "$.added", "change": "added", "before": None, "after": {"ready": True}},
        {"path": "$.facts[1]", "change": "changed", "before": "b", "after": "c"},
        {"path": "$.facts[2]", "change": "added", "before": None, "after": "d"},
        {"path": "$.goal", "change": "changed", "before": "old", "after": "new"},
        {"path": "$.removed", "change": "removed", "before": True, "after": None},
    ]


def test_content_project_detail_has_verified_timeline_sources_runs_and_releases() -> None:
    suffix = uuid4().hex
    project_code = f"CONTENT-CONSOLE-{suffix[:16]}"
    asset_code = f"SRC-{suffix[:12]}"
    run_code = f"RUN-ENTITY-{suffix[:16]}"
    release_code = f"RELEASE-ENTITY-{suffix[:16]}"
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO assets (asset_code, asset_type, original_filename, status)
                    VALUES (%s, 'IMG', %s, 'ready')
                    """,
                    (asset_code, f"{asset_code}.png"),
                )
                cursor.execute(
                    """
                    INSERT INTO content_projects (
                        project_code, title, current_revision_number, status, owner_principal
                    ) VALUES (%s, 'Console entity project', 2, 'active', 'operator-a')
                    RETURNING id
                    """,
                    (project_code,),
                )
                project_id = cursor.fetchone()["id"]
                for revision, status, goal, fingerprint in (
                    (1, "superseded", "old goal", "a" * 64),
                    (2, "confirmed", "new goal", "b" * 64),
                ):
                    cursor.execute(
                        """
                        INSERT INTO content_project_revisions (
                            project_id, project_code, revision_number, status,
                            generation_goal, content, source_revision_refs,
                            producer_role, producer_strategy_revision, fingerprint_sha256,
                            expected_parent_revision, created_by, confirmed_by, confirmed_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                            'human_business', 'human_input.v1', %s, %s, 'operator-a',
                            CASE WHEN %s = 'confirmed' THEN 'operator-a' END,
                            CASE WHEN %s = 'confirmed' THEN now() END
                        )
                        """,
                        (
                            project_id,
                            project_code,
                            revision,
                            status,
                            goal,
                            f'{{"theme":"revision-{revision}"}}',
                            f'[{{"object_type":"asset","code":"{asset_code}","revision":1}}]',
                            fingerprint,
                            revision - 1,
                            status,
                            status,
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO workflow_runs (
                        run_code, workflow_type, subject_type, subject_code,
                        subject_revision, status, progress_total, waiting_reason, requested_by
                    ) VALUES (
                        %s, 'entity_validation', 'content_project', %s,
                        2, 'waiting_human', 1, 'review required', 'operator-a'
                    )
                    """,
                    (run_code, project_code),
                )
                cursor.execute(
                    """
                    INSERT INTO releases (
                        release_code, subject_type, subject_code, subject_revision,
                        carrier_kind, status, created_by
                    ) VALUES (
                        %s, 'content_project', %s, 2,
                        'live_room_draft', 'candidate', 'operator-a'
                    )
                    """,
                    (release_code, project_code),
                )
            connection.commit()

            entity = ConsoleEntityRepository(connection).get_entity(
                "content_project", project_code, from_revision=1, to_revision=2
            )

            assert entity is not None
            assert [row["revision"] for row in entity["revisions"]] == [2, 1]
            assert entity["diff"]["available"] is True
            assert {row["path"] for row in entity["diff"]["changes"]} >= {
                "$.content.theme",
                "$.generation_goal",
            }
            assert entity["sources"] == [{
                "relation_type": "derived_from",
                "entity_type": "asset",
                "entity_code": asset_code,
                "revision": 1,
                "status": None,
                "href": f"/assets/library?asset={asset_code}",
                "mapping_quality": "verified",
            }]
            assert {(row["entity_type"], row["entity_code"]) for row in entity["used_by"]} == {
                ("workflow_run", run_code),
                ("release", release_code),
            }
        finally:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM releases WHERE release_code = %s", (release_code,))
                cursor.execute("DELETE FROM workflow_runs WHERE run_code = %s", (run_code,))
                cursor.execute("DELETE FROM content_projects WHERE project_code = %s", (project_code,))
                cursor.execute("DELETE FROM assets WHERE asset_code = %s", (asset_code,))
            connection.commit()

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.domain.errors import DomainConflictError
from app.repositories.content_core import ContentCoreRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_content_project_creation_idempotency_returns_original_and_rejects_drift() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ContentCoreRepository(connection)
        key = f"live-room-entry-{uuid4().hex}"
        payload = {
            "title": "统一入口项目",
            "generation_goal": "生成三段直播内容",
            "content": {"theme": "介绍张裕品酒大师PRO"},
            "actor_id": "test-operator",
            "idempotency_key": key,
        }

        first = repository.create_project(**payload)
        repeated = repository.create_project(**payload)

        assert repeated["project_code"] == first["project_code"]
        with pytest.raises(DomainConflictError) as error:
            repository.create_project(**{**payload, "title": "不同输入"})
        assert error.value.code == "CONTENT_PROJECT_IDEMPOTENCY_CONFLICT"


def test_content_revision_optimistic_concurrency_confirmation_and_immutability() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ContentCoreRepository(connection)
        created = repository.create_project(
            title=f"Project {suffix}",
            generation_goal="Introduce the product clearly",
            content={"audience": "new customers"},
            actor_id="operator-a",
        )
        project_code = created["project_code"]
        confirmed = repository.confirm_project_revision(project_code, revision_number=1, actor_id="operator-a")
        replay = repository.confirm_project_revision(project_code, revision_number=1, actor_id="operator-a")
        assert confirmed["status"] == "confirmed"
        assert replay["id"] == confirmed["id"]

        with pytest.raises(DomainConflictError) as conflict:
            repository.create_project_revision(
                project_code,
                expected_revision=0,
                title=created["title"],
                generation_goal="changed",
                content={},
                source_revision_refs=[],
                actor_id="operator-b",
            )
        assert conflict.value.code == "REVISION_CONFLICT"

        with pytest.raises(psycopg.errors.RaiseException, match="immutable closed-loop revision"):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE content_project_revisions SET generation_goal = 'tampered'
                    WHERE project_code = %s AND revision_number = 1
                    """,
                    (project_code,),
                )
        connection.rollback()


def test_upstream_supersede_propagates_stale_transitively_and_cycles_are_rejected() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ContentCoreRepository(connection)
        created = repository.create_project(
            title=f"Project {suffix}",
            generation_goal="Version one",
            content={"theme": "one"},
            actor_id="operator-a",
        )
        project_code = created["project_code"]
        repository.confirm_project_revision(project_code, revision_number=1, actor_id="operator-a")
        repository.add_derivation_edge(
            source_type="content_project",
            source_code=project_code,
            source_revision=1,
            target_type="build_plan",
            target_code=f"PLAN-{suffix}",
            target_revision=1,
            relation_type="derived_from",
            producer_role="planner",
            producer_strategy_revision="planner.v1",
            input_fingerprint="a" * 64,
            output_fingerprint="b" * 64,
        )
        repository.add_derivation_edge(
            source_type="build_plan",
            source_code=f"PLAN-{suffix}",
            source_revision=1,
            target_type="release_candidate",
            target_code=f"RELEASE-{suffix}",
            target_revision=1,
            relation_type="derived_from",
            producer_role="release_builder",
            producer_strategy_revision="release.v1",
            input_fingerprint="b" * 64,
            output_fingerprint="c" * 64,
        )
        with pytest.raises(DomainConflictError) as cycle:
            repository.add_derivation_edge(
                source_type="release_candidate",
                source_code=f"RELEASE-{suffix}",
                source_revision=1,
                target_type="content_project",
                target_code=project_code,
                target_revision=1,
                relation_type="derived_from",
                producer_role="invalid",
                producer_strategy_revision="invalid.v1",
                input_fingerprint="c" * 64,
                output_fingerprint="a" * 64,
            )
        assert cycle.value.code == "DERIVATION_CYCLE"

        second = repository.create_project_revision(
            project_code,
            expected_revision=1,
            title=created["title"],
            generation_goal="Version two",
            content={"theme": "two"},
            source_revision_refs=[{"object_type": "content_project", "code": project_code, "revision": 1}],
            actor_id="operator-b",
        )
        repository.confirm_project_revision(project_code, revision_number=2, actor_id="operator-b")

        plan_stale = repository.list_active_stale_records(target_type="build_plan", target_code=f"PLAN-{suffix}")
        release_stale = repository.list_active_stale_records(
            target_type="release_candidate", target_code=f"RELEASE-{suffix}"
        )
        assert second["revision_number"] == 2
        assert plan_stale[0]["reason_code"] == "UPSTREAM_REVISION_SUPERSEDED"
        assert release_stale[0]["new_revision"] == 2
        assert repository.clear_stale_records(
            target_type="build_plan",
            target_code=f"PLAN-{suffix}",
            target_revision=1,
            rebuilt_by_revision=2,
        ) == 1
        assert repository.list_active_stale_records(target_type="build_plan", target_code=f"PLAN-{suffix}") == []

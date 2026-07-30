from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_control_plane_operator
from app.api.routes import console
from app.domain.errors import DomainConflictError
from app.main import app


NOW = datetime(2026, 7, 23, tzinfo=UTC)


class FakeConsoleRepository:
    def business_overview(self, *, from_at: datetime, to_at: datetime) -> dict:
        assert from_at == datetime(2026, 7, 1, tzinfo=UTC)
        assert to_at == datetime(2026, 7, 28, tzinfo=UTC)
        return {
            "from_date": from_at,
            "to_date": to_at,
            "metrics": [
                {"key": "projects", "label": "新建内容项目", "value": 3, "previous_value": 2, "unit": "个"},
                {"key": "live_rooms", "label": "直播间方案", "value": 2, "previous_value": 1, "unit": "份"},
                {"key": "videos", "label": "成片制作", "value": 1, "previous_value": 0, "unit": "条"},
                {"key": "sessions", "label": "已关联场次", "value": 4, "previous_value": 3, "unit": "场"},
            ],
            "trend": [{"date": NOW, "projects": 1, "live_rooms": 1, "videos": 1, "sessions": 2}],
            "rankings": [{"project_code": "CONTENT-001", "title": "夏日直播", "session_count": 4, "last_session_at": NOW}],
            "coverage": {"ready_assets": 12, "published_templates": 3, "approved_facts": 8, "bound_sessions": 4, "total_sessions": 5},
            "recent_projects": [{"project_code": "CONTENT-001", "title": "夏日直播", "status": "active", "has_live_room": True, "has_video": True, "session_count": 4, "updated_at": NOW}],
            "internal_debug_code": "OVERVIEW-DEBUG-001",
        }

    def search(self, query: str, *, limit: int) -> list[dict]:
        assert query == "CONTENT"
        assert limit == 10
        return [{
            "entity_type": "content_project",
            "entity_code": "CONTENT-001",
            "title": "夏日直播",
            "status": "active",
            "revision": 2,
            "href": "/content/projects?project=CONTENT-001",
            "updated_at": NOW,
        }]

    def list_tasks(self, operator_id: str, *, limit: int) -> list[dict]:
        assert operator_id == "operator-a"
        assert limit == 50
        return [{
            "item_code": "TASK-001",
            "item_type": "human_task",
            "title": "approve_release",
            "status": "open",
            "priority": 10,
            "summary": "检查发布证据",
            "href": "/governance/runs?run=RUN-001&task=TASK-001",
            "due_at": NOW,
            "updated_at": NOW,
            "run_code": "RUN-001",
            "progress_completed": 1,
            "progress_total": 2,
            "owner_principal": "operator-a",
            "claimed_by": None,
        }]

    def list_notifications(self, *, limit: int) -> list[dict]:
        assert limit == 50
        return [{
            "notification_code": "ALERT-001",
            "state": "warning",
            "title": "MISSING_EVIDENCE",
            "summary": "release / RELEASE-001",
            "href": "/governance/runs?alert=ALERT-001",
            "evidence": {"manifest": "MANIFEST-001"},
            "occurrence_count": 1,
            "occurred_at": NOW,
            "status": "open",
        }]


class FakeConsoleEntityRepository:
    def get_entity(self, entity_type: str, entity_code: str, **_kwargs: object) -> dict | None:
        if (entity_type, entity_code) != ("content_project", "CONTENT-001"):
            return None
        return {
            "entity_type": entity_type,
            "entity_code": entity_code,
            "title": "夏日直播",
            "status": "active",
            "current_revision": 2,
            "canonical_href": "/content/projects?project=CONTENT-001",
            "source_of_truth": "postgresql",
            "revisions": [
                {"revision": 2, "status": "confirmed", "schema_version": "content-project.v1", "created_at": NOW, "created_by": "operator-a", "fingerprint": "b" * 64, "snapshot": {"goal": "new"}},
                {"revision": 1, "status": "superseded", "schema_version": "content-project.v1", "created_at": NOW, "created_by": "operator-a", "fingerprint": "a" * 64, "snapshot": {"goal": "old"}},
            ],
            "diff": {"from_revision": 1, "to_revision": 2, "available": True, "changes": [{"path": "$.goal", "change": "changed", "before": "old", "after": "new"}]},
            "sources": [{"relation_type": "derived_from", "entity_type": "asset", "entity_code": "ASSET-001", "revision": 1, "href": "/assets/library?asset=ASSET-001", "mapping_quality": "verified"}],
            "used_by": [{"relation_type": "used_by_run", "entity_type": "workflow_run", "entity_code": "RUN-001", "status": "waiting_human", "href": "/governance/runs?run=RUN-001", "mapping_quality": "verified"}],
        }


class FakeConsoleDraftRepository:
    def get_draft(self, entity_type: str, entity_code: str, draft_kind: str) -> dict | None:
        if entity_code == "MISSING":
            return None
        return self._draft(entity_type, entity_code, draft_kind, document={"title": "saved"})

    def save_draft(self, **kwargs: object) -> dict:
        assert kwargs["actor_id"] == "operator-a"
        document = kwargs["document"]
        if document == {"title": "conflict"}:
            raise DomainConflictError(
                "CONSOLE_DRAFT_REVISION_CONFLICT",
                "Console draft revision changed",
                details={"expected_revision": 1, "actual_revision": 2},
            )
        return self._draft(
            str(kwargs["entity_type"]),
            str(kwargs["entity_code"]),
            str(kwargs["draft_kind"]),
            document=document,
        )

    @staticmethod
    def _draft(entity_type: str, entity_code: str, draft_kind: str, *, document: object) -> dict:
        return {
            "draft_code": "DRAFT-001",
            "entity_type": entity_type,
            "entity_code": entity_code,
            "draft_kind": draft_kind,
            "schema_version": "console-draft.v1",
            "draft_revision": 2,
            "base_entity_revision": 1,
            "status": "active",
            "document": document,
            "content_fingerprint": "a" * 64,
            "created_by": "operator-a",
            "updated_by": "operator-a",
            "created_at": NOW,
            "updated_at": NOW,
        }


class FakeConsoleCommandRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _result(self, command: str, entity_type: str, entity_code: str, revision: int) -> dict:
        return {
            "command": command,
            "entity_type": entity_type,
            "entity_code": entity_code,
            "entity_revision": revision,
            "status": "issued" if command == "authorize" else "confirmed",
            "impact": "fixed impact",
            "receipt_code": f"COMMAND-{command}",
            "replayed": False,
        }

    def confirm_content_project(self, project_code: str, **kwargs: object) -> dict:
        self.calls.append(("confirm", kwargs))
        return self._result("confirm", "content_project", project_code, int(kwargs["expected_entity_revision"]))

    def publish_live_room_template(self, template_code: str, **kwargs: object) -> dict:
        self.calls.append(("publish", kwargs))
        return {
            **self._result("publish", "live_room_template", template_code, int(kwargs["expected_revision"])),
            "status": "published",
            "layout_fidelity": "approximate",
            "buildability": "reference_only",
        }

    def decide_release(self, release_code: str, **kwargs: object) -> dict:
        decision = str(kwargs["decision"])
        self.calls.append((decision, kwargs))
        return {
            **self._result(decision, "release", release_code, int(kwargs["expected_manifest_revision"])),
            "status": "approved" if decision == "approve" else "candidate",
        }

    def issue_authorization(self, run_code: str, **kwargs: object) -> dict:
        self.calls.append(("authorize", kwargs))
        return {
            **self._result("authorize", "workflow_run", run_code, int(kwargs["expected_task_revision"])),
            "authorization_code": "AUTH-001",
            "authorization_token": "ephemeral-token",
            "token_available": True,
        }


@pytest.fixture
def client() -> TestClient:
    repository = FakeConsoleRepository()
    entity_repository = FakeConsoleEntityRepository()
    draft_repository = FakeConsoleDraftRepository()
    command_repository = FakeConsoleCommandRepository()
    app.dependency_overrides[console.get_console_repository] = lambda: repository
    app.dependency_overrides[console.get_console_entity_repository] = lambda: entity_repository
    app.dependency_overrides[console.get_console_draft_repository] = lambda: draft_repository
    app.dependency_overrides[console.get_console_command_repository] = lambda: command_repository
    app.dependency_overrides[require_control_plane_operator] = lambda: "operator-a"
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(console.get_console_repository, None)
    app.dependency_overrides.pop(console.get_console_entity_repository, None)
    app.dependency_overrides.pop(console.get_console_draft_repository, None)
    app.dependency_overrides.pop(console.get_console_command_repository, None)
    app.dependency_overrides.pop(require_control_plane_operator, None)


def test_console_session_search_tasks_and_notifications_are_stable_deep_links(
    client: TestClient,
) -> None:
    session = client.get("/api/console/session")
    assert session.status_code == 200
    assert session.json() == {
        "operator_id": "operator-a",
        "auth_scheme": "bearer_memory",
        "roles": ["control_plane_operator"],
    }

    search = client.get("/api/console/search", params={"q": "CONTENT", "limit": 10})
    assert search.status_code == 200
    assert search.json()[0]["href"] == "/content/projects?project=CONTENT-001"

    tasks = client.get("/api/console/tasks")
    assert tasks.status_code == 200
    assert tasks.json()[0]["href"] == "/governance/runs?run=RUN-001&task=TASK-001"

    notifications = client.get("/api/console/notifications")
    assert notifications.status_code == 200
    assert notifications.json()[0]["state"] == "warning"
    assert notifications.json()[0]["evidence"] == {"manifest": "MANIFEST-001"}


def test_console_business_overview_returns_only_business_projection(client: TestClient) -> None:
    response = client.get(
        "/api/console/business-overview",
        params={"from": "2026-07-01T00:00:00Z", "to": "2026-07-28T00:00:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["key"] for item in body["metrics"]] == ["projects", "live_rooms", "videos", "sessions"]
    assert body["coverage"] == {"ready_assets": 12, "published_templates": 3, "approved_facts": 8, "bound_sessions": 4, "total_sessions": 5}
    assert body["recent_projects"][0]["title"] == "夏日直播"
    assert "internal_debug_code" not in body


def test_console_search_rejects_single_character_query(client: TestClient) -> None:
    response = client.get("/api/console/search", params={"q": "a"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"


def test_console_entity_route_exposes_timeline_diff_sources_and_usage(client: TestClient) -> None:
    response = client.get(
        "/api/console/entities/content_project/CONTENT-001",
        params={"from_revision": 1, "to_revision": 2},
    )

    assert response.status_code == 200
    assert [row["revision"] for row in response.json()["revisions"]] == [2, 1]
    assert response.json()["diff"]["changes"][0] == {
        "path": "$.goal",
        "change": "changed",
        "before": "old",
        "after": "new",
    }
    assert response.json()["sources"][0]["href"] == "/assets/library?asset=ASSET-001"
    assert response.json()["used_by"][0]["href"] == "/governance/runs?run=RUN-001"

    missing = client.get("/api/console/entities/unknown/UNKNOWN-001")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CONSOLE_ENTITY_NOT_FOUND"


def test_console_draft_put_uses_expected_revision_and_maps_conflict_to_stale(client: TestClient) -> None:
    saved = client.put(
        "/api/console/drafts/content_project/CONTENT-001/input",
        json={
            "expected_revision": 1,
            "base_entity_revision": 1,
            "schema_version": "console-draft.v1",
            "document": {"title": "saved"},
        },
    )
    conflict = client.put(
        "/api/console/drafts/content_project/CONTENT-001/input",
        json={
            "expected_revision": 1,
            "base_entity_revision": 1,
            "document": {"title": "conflict"},
        },
    )
    forged_identity = client.put(
        "/api/console/drafts/content_project/CONTENT-001/input",
        json={
            "expected_revision": 1,
            "base_entity_revision": 1,
            "document": {"title": "saved"},
            "actor_id": "forged-operator",
        },
    )

    assert saved.status_code == 200 and saved.json()["draft_revision"] == 2
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "STALE_REVISION"
    assert conflict.json()["detail"]["code"] == "CONSOLE_DRAFT_REVISION_CONFLICT"
    assert conflict.json()["error"]["state"] == "stale"
    assert forged_identity.status_code == 422


def test_console_named_commands_fix_revision_reason_and_do_not_accept_generic_action(client: TestClient) -> None:
    confirm = client.post(
        "/api/console/content-projects/CONTENT-001/confirm",
        json={
            "expected_entity_revision": 2,
            "expected_draft_revision": 3,
            "idempotency_key": "confirm-001",
        },
    )
    publish = client.post(
        "/api/console/live-room-templates/TEMPLATE-001/publish",
        json={
            "expected_revision": 4,
            "structured_reason": {"reason_code": "REVIEW_COMPLETE", "summary": "Limits reviewed"},
            "idempotency_key": "publish-001",
        },
    )
    approve = client.post(
        "/api/console/releases/RELEASE-001/decision",
        json={
            "expected_manifest_revision": 1,
            "decision": "approve",
            "structured_reason": {"reason_code": "ALL_GATES_PASS", "summary": "Manifest reviewed"},
            "approved_scope": {"target_type": "maitu_room"},
            "idempotency_key": "approve-001",
        },
    )
    generic_action = client.post(
        "/api/console/content-projects/CONTENT-001/confirm",
        json={
            "expected_entity_revision": 2,
            "expected_draft_revision": 3,
            "idempotency_key": "confirm-002",
            "action": "authorize_anything",
        },
    )

    assert confirm.status_code == 200 and confirm.json()["entity_revision"] == 2
    assert publish.status_code == 200 and publish.json()["buildability"] == "reference_only"
    assert approve.status_code == 200 and approve.json()["status"] == "approved"
    assert generic_action.status_code == 422


def test_console_authorize_command_is_no_store_and_returns_ephemeral_token(client: TestClient) -> None:
    response = client.post(
        "/api/console/workflow-runs/RUN-001/authorize",
        json={
            "task_code": "TASK-001",
            "expected_task_revision": 3,
            "idempotency_key": "authorize-001",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["authorization_token"] == "ephemeral-token"
    assert response.json()["token_available"] is True

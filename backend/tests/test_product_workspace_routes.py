from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.routes import content_projects
from app.main import app


NOW = datetime(2026, 7, 28, tzinfo=UTC)


class FakeContentService:
    def get_workspace_summary(self, project_code: str) -> dict | None:
        if project_code == "MISSING":
            return None
        output = {"available": True, "status": "ready", "updated_at": NOW, "title": "已就绪", "progress_percent": 100, "reference_code": "INTERNAL-REF-001", "fingerprint": "a" * 64}
        return {
            "project_code": project_code,
            "title": "夏日新品直播",
            "status": "active",
            "revision_number": 3,
            "generation_goal": "完成新品介绍并引导观众查看商品详情",
            "brief": output,
            "script": output,
            "live_room": output,
            "video": output,
            "delivery": output,
            "operations": output,
            "activity": [{"kind": "script", "title": "剧本已更新", "detail": "新版本可以继续制作", "status": "completed", "occurred_at": NOW, "internal_code": "EVENT-001"}],
            "updated_at": NOW,
            "internal_debug_code": "PROJECT-DEBUG-001",
        }


class FakeCreateContentService:
    def __init__(self) -> None:
        self.idempotency_key: str | None = None

    def create_project(
        self,
        payload: dict,
        *,
        actor_id: str,
        idempotency_key: str | None = None,
    ) -> dict:
        self.idempotency_key = idempotency_key
        return {
            "project_code": "CONTENT-001",
            "title": payload["title"],
            "revision_number": 1,
            "status": "draft",
            "generation_goal": payload["generation_goal"],
            "created_at": NOW,
            "updated_at": NOW,
        }


def test_project_workspace_summary_contract_filters_internal_fields() -> None:
    app.dependency_overrides[content_projects.get_service] = lambda: FakeContentService()
    try:
        with TestClient(app) as client:
            response = client.get("/api/content-projects/CONTENT-001/workspace-summary")
            missing = client.get("/api/content-projects/MISSING/workspace-summary")
    finally:
        app.dependency_overrides.pop(content_projects.get_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "夏日新品直播"
    assert set(("brief", "script", "live_room", "video", "delivery", "operations")).issubset(body)
    assert body["activity"][0]["title"] == "剧本已更新"
    assert "internal_debug_code" not in body
    assert "fingerprint" not in body["brief"]
    assert "internal_code" not in body["activity"][0]
    assert missing.status_code == 404


def test_create_content_project_forwards_browser_idempotency_key() -> None:
    service = FakeCreateContentService()
    app.dependency_overrides[content_projects.get_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/content-projects",
                headers={"Idempotency-Key": "live-room-form-001"},
                json={"title": "直播间方案", "generation_goal": "生成三段直播内容"},
            )
    finally:
        app.dependency_overrides.pop(content_projects.get_service, None)

    assert response.status_code == 201
    assert service.idempotency_key == "live-room-form-001"
    assert "idempotency" not in response.text.lower()

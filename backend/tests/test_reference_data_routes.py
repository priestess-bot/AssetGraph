from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import digital_humans, products, voice_profiles
from app.main import app


class FakeReferenceRepository:
    def __init__(self, code_field: str, code_value: str):
        self.code_field = code_field
        self.code_value = code_value
        self.rows: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": "00000000-0000-0000-0000-000000000001",
            self.code_field: self.code_value,
            **payload,
        }
        self.rows[self.code_value] = row
        return row

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.rows.values())[offset : offset + limit]

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        return self.rows.get(code)

    def update(self, code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.rows.get(code)
        if row is None:
            return None
        row.update(payload)
        return row

    def soft_delete(self, code: str) -> bool:
        return self.rows.pop(code, None) is not None


@pytest.fixture
def client() -> TestClient:
    digital_human_repo = FakeReferenceRepository("digital_human_code", "AG-DH-20260707-000001")
    voice_repo = FakeReferenceRepository("voice_code", "AG-VOICE-20260707-000001")
    product_repo = FakeReferenceRepository("product_code", "AG-PROD-20260707-000001")

    app.dependency_overrides[digital_humans.get_digital_human_repository] = lambda: digital_human_repo
    app.dependency_overrides[voice_profiles.get_voice_profile_repository] = lambda: voice_repo
    app.dependency_overrides[products.get_product_repository] = lambda: product_repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_digital_human(client: TestClient) -> None:
    response = client.post(
        "/api/digital-humans",
        json={
            "name": "小雅",
            "persona": "专业健康顾问",
            "gender": "female",
            "style": "温柔可信",
            "version": "v1",
            "provider": "internal",
            "description": "用于保健品直播",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["digital_human_code"] == "AG-DH-20260707-000001"
    assert body["name"] == "小雅"
    assert body["persona"] == "专业健康顾问"


def test_list_get_update_and_delete_digital_human(client: TestClient) -> None:
    create_response = client.post("/api/digital-humans", json={"name": "小雅"})
    code = create_response.json()["digital_human_code"]

    list_response = client.get("/api/digital-humans")
    assert list_response.status_code == 200
    assert list_response.json()[0]["digital_human_code"] == code

    get_response = client.get(f"/api/digital-humans/{code}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "小雅"

    update_response = client.patch(f"/api/digital-humans/{code}", json={"style": "专业亲和"})
    assert update_response.status_code == 200
    assert update_response.json()["style"] == "专业亲和"

    delete_response = client.delete(f"/api/digital-humans/{code}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/api/digital-humans/{code}")
    assert missing_response.status_code == 404


def test_create_voice_profile(client: TestClient) -> None:
    response = client.post(
        "/api/voice-profiles",
        json={"name": "温柔女声", "provider": "internal", "gender": "female", "style": "gentle"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["voice_code"] == "AG-VOICE-20260707-000001"
    assert body["name"] == "温柔女声"


def test_create_product(client: TestClient) -> None:
    response = client.post(
        "/api/products",
        json={
            "name": "胶原蛋白饮",
            "brand": "示例品牌",
            "category": "健康食品",
            "selling_points": "低糖、便携",
            "pain_points": "熬夜暗沉",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["product_code"] == "AG-PROD-20260707-000001"
    assert body["name"] == "胶原蛋白饮"

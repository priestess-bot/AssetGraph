from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_console_entry_and_stable_deep_links_serve_the_same_spa() -> None:
    with TestClient(app) as client:
        root = client.get("/", follow_redirects=False)
        console = client.get("/console/")
        assets = client.get("/assets/library?asset=AG-IMG-001")
        research = client.get("/research/live-sources?session=CAP-001")
        api_missing = client.get("/api/not-a-route")

    assert root.status_code == 307
    assert root.headers["location"] == "/console/"
    assert console.status_code == 200
    assert assets.status_code == 200
    assert research.status_code == 200
    assert "AssetGraph Console" in console.text
    assert console.text == assets.text == research.text
    assert api_missing.status_code == 404
    assert api_missing.headers["content-type"].startswith("application/json")


def test_console_asset_paths_do_not_fall_back_to_html_when_missing() -> None:
    with TestClient(app) as client:
        response = client.get("/console/assets/missing.js")

    assert response.status_code == 404
    assert "AssetGraph Console" not in response.text


def test_retired_frontend_roots_do_not_serve_or_redirect_legacy_apps() -> None:
    with TestClient(app) as client:
        maitu = client.get("/maitu/?run=RUN-001", follow_redirects=False)
        research = client.get("/live-research/?session=CAP-001", follow_redirects=False)

    for response in (maitu, research):
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert "AssetGraph Console" not in response.text

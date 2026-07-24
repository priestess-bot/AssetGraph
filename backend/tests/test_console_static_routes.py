from __future__ import annotations

from fastapi.testclient import TestClient
from urllib.parse import parse_qs, urlsplit

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


def _redirect(path: str) -> tuple[str, dict[str, list[str]]]:
    with TestClient(app) as client:
        response = client.get(path, follow_redirects=False)
    assert response.status_code == 308
    location = urlsplit(response.headers["location"])
    return location.path, parse_qs(location.query, keep_blank_values=True)


def test_legacy_maitu_frontend_views_redirect_to_stable_routes_with_deep_links() -> None:
    production_path, production_query = _redirect(
        "/maitu/?run=RUN-001&reference_template_code=TPL-001&"
        f"reference_template_revision_number=2&reference_template_projection_fingerprint={'a' * 64}"
    )
    assert production_path == "/production/live-rooms"
    assert production_query == {
        "run": ["RUN-001"],
        "reference_template_code": ["TPL-001"],
        "reference_template_revision_number": ["2"],
        "reference_template_projection_fingerprint": ["a" * 64],
    }

    resources_path, resources_query = _redirect("/maitu?view=resources&asset=ASSET-001&tag=a&tag=b")
    assert resources_path == "/assets/library"
    assert resources_query == {"asset": ["ASSET-001"], "tag": ["a", "b"]}

    analysis_path, analysis_query = _redirect("/maitu/?view=gemini&run=RUN-002&panel=legacy")
    assert analysis_path == "/assets/library"
    assert analysis_query == {"run": ["RUN-002"], "panel": ["analysis"]}


def test_legacy_live_research_views_redirect_to_stable_routes_with_deep_links() -> None:
    watch_path, watch_query = _redirect("/live-research/?source=ROOM-001")
    assert watch_path == "/research/live-sources"
    assert watch_query == {"source": ["ROOM-001"]}

    sessions_path, sessions_query = _redirect(
        "/live-research?view=sessions&session=CAP-001&track=asr&track=visual"
    )
    assert sessions_path == "/research/live-sources"
    assert sessions_query == {"view": ["sessions"], "session": ["CAP-001"], "track": ["asr", "visual"]}

    published_path, published_query = _redirect("/live-research/?view=published&template=TPL-002")
    assert published_path == "/research/live-sources"
    assert published_query == {"view": ["published"], "template": ["TPL-002"]}

    invalid_path, invalid_query = _redirect("/live-research/?view=unknown&template=TPL-003")
    assert invalid_path == "/research/live-sources"
    assert invalid_query == {"template": ["TPL-003"]}

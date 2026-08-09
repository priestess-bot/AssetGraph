from __future__ import annotations

from typing import Any

from app.repositories.releases import ReleaseRepository


class RecordingCursor:
    def __init__(self) -> None:
        self.query = ""
        self.parameters: tuple[Any, ...] = ()

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[Any, ...]) -> None:
        self.query = query
        self.parameters = parameters

    def fetchall(self) -> list[dict[str, Any]]:
        return [{"release_code": "RELEASE-001", "delivery_count": 0}]


class RecordingConnection:
    def __init__(self) -> None:
        self.recording_cursor = RecordingCursor()

    def cursor(self, **_: object) -> RecordingCursor:
        return self.recording_cursor


def test_project_filter_uses_both_functional_plan_associations() -> None:
    connection = RecordingConnection()
    repository = ReleaseRepository(connection)  # type: ignore[arg-type]

    releases = repository.list_releases(project_code="CONTENT-001")

    assert releases == [{"release_code": "RELEASE-001", "delivery_count": 0}]
    assert "FROM functional_live_room_plans AS live" in connection.recording_cursor.query
    assert "FROM functional_video_plans AS video" in connection.recording_cursor.query
    assert "project_release.release_code = release.release_code" in connection.recording_cursor.query
    assert connection.recording_cursor.parameters == ("CONTENT-001", "CONTENT-001")

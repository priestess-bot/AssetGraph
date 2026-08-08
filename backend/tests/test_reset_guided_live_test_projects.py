from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import reset_guided_live_test_projects as reset  # noqa: E402


PROJECT_ID = UUID("11111111-1111-1111-1111-111111111111")


class TargetCursor:
    def __init__(self, rows: list[dict[str, object]]):
        self.rows = rows
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.sql = sql
        self.params = params

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class CursorContext:
    def __enter__(self) -> "CursorContext":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: object = None) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = CursorContext()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kwargs: object) -> CursorContext:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _target() -> reset.TargetProject:
    return reset.TargetProject(
        project_id=PROJECT_ID,
        project_code="CONTENT-TEST-1",
        current_revision_number=3,
    )


def test_project_code_is_repeatable_and_default_is_dry_run() -> None:
    options = reset.parse_options(
        ["--project-code", "CONTENT-TEST-1", "--project-code", "CONTENT-TEST-2"]
    )

    assert options.project_codes == ("CONTENT-TEST-1", "CONTENT-TEST-2")
    assert options.dry_run is True
    assert options.all_guided is False


def test_selection_is_required() -> None:
    with pytest.raises(SystemExit) as exc_info:
        reset.parse_options([])

    assert exc_info.value.code == 2


def test_confirming_all_guided_is_always_refused() -> None:
    with pytest.raises(SystemExit) as exc_info:
        reset.parse_options(["--all-guided", "--confirm"])

    assert exc_info.value.code == 2


def test_runtime_guard_cannot_be_bypassed_by_constructing_options_directly() -> None:
    with pytest.raises(reset.ResetRefused, match="dry-run only"):
        reset.validate_runtime_guard(
            reset.ResetOptions(project_codes=(), all_guided=True, confirm=True)
        )


def test_target_resolution_uses_only_the_current_guided_revision() -> None:
    cursor = TargetCursor(
        [
            {
                "project_id": PROJECT_ID,
                "project_code": "CONTENT-TEST-1",
                "current_revision_number": 3,
            }
        ]
    )

    targets = reset.resolve_targets(
        cursor,
        project_codes=["CONTENT-TEST-1"],
        all_guided=False,
    )

    assert targets == [_target()]
    assert "revision.revision_number = project.current_revision_number" in cursor.sql
    assert "revision.content ->> 'workflow_version' = %s" in cursor.sql
    assert "project.project_code = ANY(%s::text[])" in cursor.sql
    assert cursor.params == (reset.GUIDED_WORKFLOW_VERSION, ["CONTENT-TEST-1"])


def test_target_resolution_refuses_partial_or_non_guided_matches() -> None:
    cursor = TargetCursor(
        [
            {
                "project_id": PROJECT_ID,
                "project_code": "CONTENT-TEST-1",
                "current_revision_number": 3,
            }
        ]
    )

    with pytest.raises(reset.ResetRefused, match="CONTENT-NOT-GUIDED"):
        reset.resolve_targets(
            cursor,
            project_codes=["CONTENT-TEST-1", "CONTENT-NOT-GUIDED"],
            all_guided=False,
        )


def test_target_resolution_refuses_an_empty_all_guided_scope() -> None:
    cursor = TargetCursor([])

    with pytest.raises(reset.ResetRefused, match=reset.GUIDED_WORKFLOW_VERSION):
        reset.resolve_targets(cursor, project_codes=[], all_guided=True)


def test_delete_order_covers_required_aggregates_and_never_targets_protected_data() -> None:
    tables = [step.table for step in reset.DELETION_STEPS]

    assert tables.index("functional_live_room_plans") < tables.index("content_projects")
    assert tables.index("shot_list_revisions") < tables.index("content_program_revisions")
    assert tables.index("content_program_revisions") < tables.index("content_script_revisions")
    assert tables.index("content_script_revisions") < tables.index("story_briefs")
    assert tables.index("content_generation_jobs") < tables.index("content_projects")
    assert tables.index("content_guided_revision_archives") < tables.index("content_projects")
    assert tables.index("content_project_material_pool_revisions") < tables.index(
        "content_projects"
    )
    protected_fragments = ("asset", "knowledge", "template", "fact_card", "fact_claim")
    assert not any(
        fragment in step.table
        for step in reset.DELETION_STEPS
        for fragment in protected_fragments
    )


def test_default_dry_run_executes_rehearsal_then_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    calls: list[str] = []
    messages: list[str] = []
    target = _target()
    monkeypatch.setattr(reset, "resolve_targets", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(reset, "collect_domain_references", lambda *_args: ())
    monkeypatch.setattr(reset, "collect_row_counts", lambda *_args: {"content_projects": 1})
    monkeypatch.setattr(
        reset,
        "delete_target_data",
        lambda *_args: calls.append("delete") or {"content_projects": 1},
    )
    monkeypatch.setattr(reset, "verify_targets_deleted", lambda *_args: None)

    reset.run_reset(
        connection,
        reset.ResetOptions(
            project_codes=(target.project_code,),
            all_guided=False,
            confirm=False,
        ),
        output=messages.append,
    )

    assert calls == ["delete"]
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert messages[-1] == "result=dry-run-rolled-back projects_would_delete=1"


def test_confirm_commits_only_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    target = _target()
    monkeypatch.setattr(reset, "resolve_targets", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(reset, "collect_domain_references", lambda *_args: ())
    monkeypatch.setattr(reset, "collect_row_counts", lambda *_args: {"content_projects": 1})
    monkeypatch.setattr(reset, "delete_target_data", lambda *_args: {"content_projects": 1})
    monkeypatch.setattr(reset, "verify_targets_deleted", lambda *_args: None)

    reset.run_reset(
        connection,
        reset.ResetOptions(
            project_codes=(target.project_code,),
            all_guided=False,
            confirm=True,
        ),
        output=lambda _message: None,
    )

    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_failure_rolls_back_and_never_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    target = _target()
    monkeypatch.setattr(reset, "resolve_targets", lambda *_args, **_kwargs: [target])
    monkeypatch.setattr(reset, "collect_domain_references", lambda *_args: ())
    monkeypatch.setattr(reset, "collect_row_counts", lambda *_args: {"content_projects": 1})

    def fail_delete(*_args: object) -> dict[str, int]:
        raise RuntimeError("simulated foreign-key failure")

    monkeypatch.setattr(reset, "delete_target_data", fail_delete)

    with pytest.raises(RuntimeError, match="simulated foreign-key failure"):
        reset.run_reset(
            connection,
            reset.ResetOptions(
                project_codes=(target.project_code,),
                all_guided=False,
                confirm=True,
            ),
            output=lambda _message: None,
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1

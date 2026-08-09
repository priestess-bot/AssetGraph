from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.errors import DomainValidationError
from app.services.functional_videos import FunctionalVideoService
from app.services.releases import ReleaseService


FIXED_RENDER_INPUTS = (
    ("MT-VID-0016", "video/MT-VID-0016.mov", "1" * 64),
    ("MT-VID-0024", "video/MT-VID-0024.mp4", "2" * 64),
    ("MT-VID-0027", "video/MT-VID-0027.mp4", "3" * 64),
    ("MT-DEC-0003", "overlay/MT-DEC-0003.png", "4" * 64),
    ("MT-DEC-0024", "overlay/MT-DEC-0024.png", "5" * 64),
)


def _fixed_render_job() -> dict[str, Any]:
    assets = [
        {"asset_code": code, "relative_path": path, "checksum_sha256": checksum}
        for code, path, checksum in FIXED_RENDER_INPUTS
    ]
    return {
        "shot_list": {
            "shots": [
                {"asset_code": "MT-VID-0027"},
                {"asset_code": "MT-VID-0016"},
                {"asset_code": "MT-VID-0024"},
            ]
        },
        "asset_plan": {
            "source": "fixed_maitu_asset_plan_v1",
            "asset_count": len(assets),
            "assets": assets,
            "shot_assets": [
                {"asset_code": "MT-VID-0027"},
                {"asset_code": "MT-VID-0016"},
                {"asset_code": "MT-VID-0024"},
            ],
            "overlays": {
                "brand_logo": "overlay/MT-DEC-0003.png",
                "product_sticker": "overlay/MT-DEC-0024.png",
            },
        },
    }


def _catalog_asset(
    index: int,
    *,
    local_file_code: str | None,
    checksum: str,
    rights_status: str = "approved",
) -> dict[str, Any]:
    return {
        "asset_code": f"AG-VID-20260809-{index:06d}",
        "local_file_code": local_file_code,
        "checksum_sha256": checksum,
        "rights_status": rights_status,
        "rights_updated_at": datetime(2026, 8, 9, tzinfo=UTC),
        "rights_updated_by": "rights-reviewer",
    }


def test_release_rights_snapshot_resolves_fixed_baseline_and_overlays() -> None:
    rendered = FunctionalVideoService._rendered_release_inputs(_fixed_render_job())
    catalog = [
        _catalog_asset(index, local_file_code=code, checksum=checksum)
        for index, (code, _path, checksum) in enumerate(FIXED_RENDER_INPUTS, start=1)
    ]

    snapshot = FunctionalVideoService._build_release_rights_snapshot(rendered, catalog)

    assert snapshot["status"] == "valid"
    assert snapshot["asset_count"] == 5
    assert snapshot["asset_codes"] == sorted(asset["asset_code"] for asset in catalog)
    assert {
        code for asset in snapshot["assets"] for code in asset["rendered_input_codes"]
    } == {code for code, _path, _checksum in FIXED_RENDER_INPUTS}
    assert all(
        asset["matched_by"] == ["local_file_code"] for asset in snapshot["assets"]
    )
    assert all(asset["rights_status"] == "approved" for asset in snapshot["assets"])
    assert len(snapshot["render_input_fingerprint_sha256"]) == 64
    assert len(snapshot["rights_evidence_fingerprint_sha256"]) == 64


def test_release_rights_snapshot_prefers_global_asset_code_with_exact_checksum() -> (
    None
):
    checksum = "a" * 64
    rendered = [
        {
            "asset_code": "AG-VID-20260809-000101",
            "local_file_code": None,
            "checksum_sha256": checksum,
            "relative_path": "video/selected.mp4",
        }
    ]
    catalog = [
        {
            **_catalog_asset(101, local_file_code="MT-VID-0101", checksum=checksum),
            "asset_code": "AG-VID-20260809-000101",
        }
    ]

    snapshot = FunctionalVideoService._build_release_rights_snapshot(rendered, catalog)

    assert snapshot["assets"][0]["matched_by"] == ["asset_code"]
    assert snapshot["assets"][0]["asset_code"] == "AG-VID-20260809-000101"


def test_release_rights_snapshot_prefers_explicit_local_file_code_over_legacy_alias() -> None:
    checksum = "a" * 64
    rendered = [
        {
            "asset_code": "MT-DEC-0003",
            "local_file_code": "MT-DEC-0003-UNIQUE",
            "checksum_sha256": checksum,
            "relative_path": "overlay/logo.png",
        }
    ]
    legacy = _catalog_asset(
        105,
        local_file_code="MT-DEC-0003",
        checksum=checksum,
    )
    explicit = _catalog_asset(
        106,
        local_file_code="MT-DEC-0003-UNIQUE",
        checksum=checksum,
    )

    snapshot = FunctionalVideoService._build_release_rights_snapshot(
        rendered,
        [legacy, explicit],
    )

    assert snapshot["assets"][0]["asset_code"] == explicit["asset_code"]
    assert snapshot["assets"][0]["matched_by"] == ["local_file_code"]


def test_release_rights_snapshot_falls_back_to_a_unique_checksum() -> None:
    checksum = "b" * 64
    rendered = [
        {
            "asset_code": "LEGACY-RENDER-CODE",
            "local_file_code": None,
            "checksum_sha256": checksum,
            "relative_path": "video/legacy.mp4",
        }
    ]
    catalog = [_catalog_asset(102, local_file_code="MT-VID-0102", checksum=checksum)]

    snapshot = FunctionalVideoService._build_release_rights_snapshot(rendered, catalog)

    assert snapshot["assets"][0]["matched_by"] == ["checksum_sha256"]
    assert snapshot["assets"][0]["asset_code"] == catalog[0]["asset_code"]


def test_release_rights_snapshot_rejects_an_ambiguous_checksum_fallback() -> None:
    checksum = "c" * 64
    rendered = [
        {
            "asset_code": "LEGACY-RENDER-CODE",
            "local_file_code": None,
            "checksum_sha256": checksum,
            "relative_path": "video/legacy.mp4",
        }
    ]
    catalog = [
        _catalog_asset(103, local_file_code="MT-VID-0103", checksum=checksum),
        _catalog_asset(104, local_file_code="MT-VID-0104", checksum=checksum),
    ]

    with pytest.raises(DomainValidationError) as raised:
        FunctionalVideoService._build_release_rights_snapshot(rendered, catalog)

    assert raised.value.code == "VIDEO_RELEASE_ASSET_AMBIGUOUS"


@pytest.mark.parametrize(
    ("catalog", "error_code"),
    [
        ([], "VIDEO_RELEASE_ASSET_NOT_FOUND"),
        (
            [_catalog_asset(1, local_file_code="MT-VID-0016", checksum="f" * 64)],
            "VIDEO_RELEASE_ASSET_CHECKSUM_MISMATCH",
        ),
        (
            [
                _catalog_asset(
                    1,
                    local_file_code="MT-VID-0016",
                    checksum="1" * 64,
                    rights_status="pending",
                )
            ],
            "VIDEO_RELEASE_ASSET_RIGHTS_REQUIRED",
        ),
    ],
)
def test_release_rights_snapshot_fails_closed_for_invalid_catalog_evidence(
    catalog: list[dict[str, Any]],
    error_code: str,
) -> None:
    rendered = [
        {
            "asset_code": "MT-VID-0016",
            "local_file_code": None,
            "checksum_sha256": "1" * 64,
            "relative_path": "video/MT-VID-0016.mov",
        }
    ]

    with pytest.raises(DomainValidationError) as raised:
        FunctionalVideoService._build_release_rights_snapshot(rendered, catalog)

    assert raised.value.code == error_code


def test_rendered_release_inputs_reject_an_omitted_fixed_overlay() -> None:
    job = _fixed_render_job()
    job["asset_plan"]["assets"] = job["asset_plan"]["assets"][:-1]
    job["asset_plan"]["asset_count"] = 4

    with pytest.raises(DomainValidationError) as raised:
        FunctionalVideoService._rendered_release_inputs(job)

    assert raised.value.code == "VIDEO_RELEASE_ASSET_PLAN_INCOMPLETE"
    assert raised.value.details["missing_relative_paths"] == ["overlay/MT-DEC-0024.png"]


class _FakeCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(
        self, statement: str, parameters: tuple[Any, ...] | None = None
    ) -> None:
        self.executions.append((statement, parameters))

    @staticmethod
    def fetchone() -> dict[str, Any]:
        return {"id": "plan-id", "release_code": "RELEASE-1"}


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()
        self.commits = 0

    def cursor(self, **_kwargs: Any) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


class _FakeVideos:
    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job

    def get_by_code(self, _job_code: str) -> dict[str, Any]:
        return self.job


class _FakeReleaseService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_candidate(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(payload)
        return {
            "release_code": "RELEASE-1",
            "manifest": {"manifest_fingerprint": "f" * 64},
        }


class _ProbeFunctionalVideoService(FunctionalVideoService):
    def __init__(
        self,
        job: dict[str, Any],
        *,
        rights_error: DomainValidationError | None = None,
    ) -> None:
        self.connection = _FakeConnection()
        self.videos = _FakeVideos(job)
        self.release_service = _FakeReleaseService()
        self.rights_error = rights_error
        self.rights_called = False
        self.snapshot_called = False
        self.source = {
            "id": "plan-id",
            "plan_code": "VIDPLAN-1",
            "release_code": None,
            "video_job_code": "VIDEOJOB-1",
            "variant_code": "VARIANT-1",
            "variant_revision": 1,
            "source_project_code": "CONTENT-1",
            "source_project_revision": 1,
            "story_brief_code": "STORY-1",
            "story_brief_revision": 1,
            "script_revision_code": "SCRIPT-1",
            "script_revision": 1,
            "program_revision_code": "PROGRAM-1",
            "program_revision": 1,
            "shot_list_revision_code": "SHOTS-1",
            "shot_list_revision": 1,
            "timeline_revision": 1,
            "production_timeline": {"tracks": []},
            "render_profile": {"schema_version": "functional-render-profile.v1"},
        }

    def _branch_source(self, _plan_code: str) -> dict[str, Any]:
        return self.source

    def _release_rights_snapshot(self, _job: dict[str, Any]) -> dict[str, Any]:
        self.rights_called = True
        if self.rights_error is not None:
            raise self.rights_error
        return {"status": "valid", "asset_codes": ["AG-VID-1"]}

    def _get_or_create_release_snapshot(
        self,
        _source: dict[str, Any],
        _job: dict[str, Any],
        _subject_refs: dict[str, Any],
    ) -> dict[str, Any]:
        self.snapshot_called = True
        return {"artifact_code": "ART-1", "checksum_sha256": "e" * 64}

    def _release_service(self) -> _FakeReleaseService:
        return self.release_service

    def _enrich(self, row: dict[str, Any]) -> dict[str, Any]:
        return row


def _candidate_job(
    *, status: str = "succeeded", quality_passed: bool = True
) -> dict[str, Any]:
    return {
        "job_code": "VIDEOJOB-1",
        "status": status,
        "attempt": 1,
        "quality_report": {"passed": quality_passed},
        "artifacts": [
            {
                "artifact_key": "video",
                "relative_path": "fixture/final.mp4",
                "checksum_sha256": "d" * 64,
            }
        ],
    }


@pytest.mark.parametrize(
    ("status", "quality_passed"),
    [("queued", True), ("succeeded", False)],
)
def test_release_candidate_requires_successful_render_and_passing_qc(
    status: str,
    quality_passed: bool,
) -> None:
    service = _ProbeFunctionalVideoService(
        _candidate_job(status=status, quality_passed=quality_passed)
    )

    with pytest.raises(DomainValidationError) as raised:
        service.create_release_candidate("VIDPLAN-1", actor_id="producer")

    assert raised.value.code == "VIDEO_RELEASE_QC_REQUIRED"
    assert service.rights_called is False
    assert service.snapshot_called is False
    assert service.release_service.calls == []


def test_release_candidate_has_only_machine_verifiable_preapproval_gates() -> None:
    service = _ProbeFunctionalVideoService(_candidate_job())

    service.create_release_candidate("VIDPLAN-1", actor_id="producer")

    payload = service.release_service.calls[0]
    gates = payload["quality_snapshot"]["gates"]
    assert [gate["code"] for gate in gates] == [
        "GATE_VIDEO_RENDER_SUCCEEDED",
        "GATE_VIDEO_QC",
        "GATE_VIDEO_ASSET_RIGHTS",
    ]
    assert all(gate["status"] == "pass" and gate["blocking"] is True for gate in gates)
    assert all("AUTHORIZATION" not in gate["code"] for gate in gates)
    assert payload["rights_snapshot"] == {
        "status": "valid",
        "asset_codes": ["AG-VID-1"],
    }
    assert payload["carrier_facet"]["delivery"]["status"] == "awaiting_release_approval"
    gate_failures = ReleaseService._gate_failures(
        {
            "rights_snapshot": payload["rights_snapshot"],
            "quality_snapshot": payload["quality_snapshot"],
            "lineage_snapshot": payload["lineage_snapshot"],
            "artifact_refs": payload["artifact_refs"],
        }
    )
    assert gate_failures == []


def test_release_rights_failure_precedes_any_release_write() -> None:
    service = _ProbeFunctionalVideoService(
        _candidate_job(),
        rights_error=DomainValidationError(
            "VIDEO_RELEASE_ASSET_RIGHTS_REQUIRED",
            "rights are not approved",
        ),
    )

    with pytest.raises(DomainValidationError) as raised:
        service.create_release_candidate("VIDPLAN-1", actor_id="producer")

    assert raised.value.code == "VIDEO_RELEASE_ASSET_RIGHTS_REQUIRED"
    assert service.rights_called is True
    assert service.snapshot_called is False
    assert service.release_service.calls == []
    assert service.connection.commits == 0

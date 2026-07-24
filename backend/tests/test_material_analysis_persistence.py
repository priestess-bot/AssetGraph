from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pglast import parse_sql

from app.api.routes.maitu_workbench import (
    get_material_analysis_workbench_service,
    router,
)
from app.services.material_analysis import (
    MaterialAnalysisError,
    MaterialAnalysisWorkbenchService,
    resolve_material_source_path,
)


FINGERPRINT = "a" * 64
NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _observation(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "material-profile-observation-v1",
        "asset_code": "AG-VID-1",
        "asset_fingerprint": FINGERPRINT,
        "summary": "product video",
        "semantic_roles": ["product_visual"],
        "product_identities": ["PRO"],
        "people": [],
        "visible_text": ["PRO"],
        "palette": ["red"],
        "style_tags": ["commercial"],
        "audio_class": "unknown",
        "original_audio_recommended": False,
        "reusable_as_whole": True,
        "scenes": [],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


class FakeAnalysisRepository:
    def __init__(self) -> None:
        self.analysis = {
            "id": "10000000-0000-0000-0000-000000000001",
            "analysis_code": "MT-MAT-AN-001",
            "run_code": "MT-WB-RUN-001",
            "asset_code": "AG-VID-1",
            "asset_fingerprint": FINGERPRINT,
            "asset_title": "Product video",
            "selected": True,
            "status": "succeeded",
            "attempt": 1,
            "provisional_source": "strategy_frames",
            "analysis_strategy_revision": "material.semantic-observation.v2",
            "invocation_evidence_ref": "ART-EVIDENCE-001",
            "provisional_summary": "product video",
            "technical": {"duration_seconds": 10},
            "automatic_observation": _observation(),
            "gemini_status": "not_requested",
            "gemini_summary": None,
            "conflict_count": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
        self.sync_calls: list[str] = []
        self.completed: dict[str, Any] | None = None
        self.submission: dict[str, Any] | None = None

    def synchronize_selected_video_analyses(self, run_code: str) -> list[dict[str, Any]] | None:
        self.sync_calls.append(run_code)
        return [deepcopy(self.analysis)] if run_code == self.analysis["run_code"] else None

    def list_video_analyses(self, run_code: str) -> list[dict[str, Any]] | None:
        return [deepcopy(self.analysis)] if run_code == self.analysis["run_code"] else None

    def get_video_analysis(self, analysis_code: str) -> dict[str, Any] | None:
        return deepcopy(self.analysis) if analysis_code == self.analysis["analysis_code"] else None

    def complete_video_analysis(
        self,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.completed = {
            "analysis_code": analysis_code,
            "worker_id": worker_id,
            "lease_token": lease_token,
            **deepcopy(payload),
        }
        return {**deepcopy(self.analysis), "status": "succeeded"}

    def persist_gemini_submission(self, run_code: str, analysis_code: str, **kwargs: Any) -> dict[str, Any]:
        self.submission = {"run_code": run_code, "analysis_code": analysis_code, **deepcopy(kwargs)}
        profile = kwargs["merged_profile"]
        return {
            **deepcopy(self.analysis),
            "gemini_status": "succeeded",
            "gemini_summary": kwargs["parsed_observation"]["summary"],
            "conflict_count": len(profile["conflicts"]),
        }

    @staticmethod
    def list_analysis_conflicts(run_code: str, *, selected_only: bool) -> list[dict[str, Any]]:
        assert run_code == "MT-WB-RUN-001"
        assert selected_only is True
        return []

    @staticmethod
    def resolve_analysis_conflict(
        run_code: str,
        conflict_code: str,
        *,
        resolution: str,
        resolved_by: str,
    ) -> dict[str, Any]:
        return {
            "run_code": run_code,
            "conflict_code": conflict_code,
            "resolution": resolution,
            "resolved_by": resolved_by,
        }


def test_material_analysis_migration_is_replayable_and_audited() -> None:
    migration = Path("migrations/025_maitu_material_analysis.sql")
    sql = migration.read_text(encoding="utf-8")

    parse_sql(sql)
    for table in (
        "maitu_workbench_video_analyses",
        "maitu_workbench_gemini_submissions",
        "maitu_workbench_analysis_conflicts",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "raw_submission JSONB NOT NULL" in sql
    assert "asset_fingerprint CHAR(64) NOT NULL" in sql
    assert "resolution IN ('provisional', 'gemini', 'replace_asset')" in sql
    assert "lease_token UUID" in sql


def test_listing_synchronizes_selected_video_jobs_and_completion_merges_provisional_profile() -> None:
    repository = FakeAnalysisRepository()
    service = MaterialAnalysisWorkbenchService(repository)

    listed = service.list_video_analyses("MT-WB-RUN-001")
    completed = service.complete_video_analysis(
        "MT-MAT-AN-001",
        "analysis-worker",
        {
            "lease_token": "lease",
            "technical": {"duration_seconds": 10},
            "frame_manifest": {"frames": []},
            "observation": _observation(),
            "analysis_strategy_revision": "material.semantic-observation.v2",
            "invocation_evidence_ref": "ART-EVIDENCE-001",
            "analysis_prompt_revision": "material-observation-v1",
            "analysis_input_fingerprint": "b" * 64,
            "analysis_output_fingerprint": "c" * 64,
        },
    )

    assert listed and listed[0]["selected"] is True
    assert repository.sync_calls == ["MT-WB-RUN-001"]
    assert completed["status"] == "succeeded"
    assert repository.completed is not None
    assert repository.completed["merged_profile"]["status"] == "provisional"


def test_completion_rejects_model_observation_for_a_different_fingerprint() -> None:
    service = MaterialAnalysisWorkbenchService(FakeAnalysisRepository())

    with pytest.raises(MaterialAnalysisError, match="identity"):
        service.complete_video_analysis(
            "MT-MAT-AN-001",
            "analysis-worker",
            {
                "lease_token": "lease",
                "technical": {},
                "frame_manifest": {},
                "observation": _observation(asset_fingerprint="b" * 64),
            },
        )


def test_gemini_raw_json_is_identity_bound_and_persists_critical_conflicts() -> None:
    repository = FakeAnalysisRepository()
    service = MaterialAnalysisWorkbenchService(repository)
    raw_json = {
        "analysis_task_code": "MT-MAT-AN-001",
        "asset_code": "AG-VID-1",
        "asset_fingerprint": FINGERPRINT,
        "prompt_schema_version": "gemini-material-analysis-v1",
        "observation": _observation(product_identities=["OTHER"]),
    }

    result = service.submit_gemini_backfill(
        "MT-WB-RUN-001",
        "MT-MAT-AN-001",
        {
            "raw_json": raw_json,
            "asset_code": "AG-VID-1",
            "asset_fingerprint": FINGERPRINT,
            "submitted_by": "reviewer",
        },
    )

    assert result and result["gemini_status"] == "succeeded"
    assert repository.submission is not None
    assert repository.submission["raw_submission"] == raw_json
    conflicts = repository.submission["merged_profile"]["conflicts"]
    assert any(item["field"] == "product_identities" and item["severity"] == "critical" for item in conflicts)

    with pytest.raises(MaterialAnalysisError, match="request identity"):
        service.submit_gemini_backfill(
            "MT-WB-RUN-001",
            "MT-MAT-AN-001",
            {
                "raw_json": raw_json,
                "asset_code": "AG-VID-1",
                "asset_fingerprint": "b" * 64,
            },
        )


def test_material_source_resolution_rejects_absolute_and_parent_paths(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    mirror = tmp_path / "mirror"
    materials.mkdir()
    mirror.mkdir()
    source = materials / "video.mp4"
    source.write_bytes(b"video")

    assert resolve_material_source_path(
        relative_path="video.mp4",
        root_kind="asset_materials",
        asset_materials_root=materials,
        maitu_mirror_root=mirror,
    ) == source.resolve()
    with pytest.raises(MaterialAnalysisError, match="relative"):
        resolve_material_source_path(
            relative_path=str(source),
            root_kind="asset_materials",
            asset_materials_root=materials,
            maitu_mirror_root=mirror,
        )
    with pytest.raises(MaterialAnalysisError, match="escapes"):
        resolve_material_source_path(
            relative_path="../outside.mp4",
            root_kind="asset_materials",
            asset_materials_root=materials,
            maitu_mirror_root=mirror,
        )


class FakeRouteAnalysisService:
    @staticmethod
    def list_video_analyses(run_code: str) -> list[dict[str, Any]]:
        return [_route_analysis(run_code)]

    @staticmethod
    def submit_gemini_backfill(
        run_code: str,
        analysis_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        assert payload["asset_fingerprint"] == FINGERPRINT
        return {**_route_analysis(run_code), "analysis_code": analysis_code, "gemini_status": "succeeded"}

    @staticmethod
    def list_analysis_conflicts(run_code: str) -> list[dict[str, Any]]:
        return [_route_conflict(run_code)]

    @staticmethod
    def resolve_analysis_conflict(
        run_code: str,
        conflict_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {**_route_conflict(run_code), "conflict_code": conflict_code, **payload}


def _route_analysis(run_code: str) -> dict[str, Any]:
    return {
        "id": "10000000-0000-0000-0000-000000000001",
        "analysis_code": "MT-MAT-AN-001",
        "run_code": run_code,
        "asset_code": "AG-VID-1",
        "asset_fingerprint": FINGERPRINT,
        "asset_title": "Video",
        "selected": True,
        "status": "succeeded",
        "attempt": 1,
        "provisional_source": "strategy_frames",
        "analysis_strategy_revision": "material.semantic-observation.v2",
        "invocation_evidence_ref": "ART-EVIDENCE-001",
        "provisional_summary": "video",
        "gemini_status": "not_requested",
        "conflict_count": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _route_conflict(run_code: str) -> dict[str, Any]:
    del run_code
    return {
        "id": "20000000-0000-0000-0000-000000000001",
        "conflict_code": "MT-MAT-CON-001",
        "analysis_code": "MT-MAT-AN-001",
        "field": "product_identities",
        "severity": "critical",
        "provisional_value": json.dumps(["PRO"]),
        "gemini_value": json.dumps(["OTHER"]),
        "resolution": None,
        "reason": "identity conflict",
        "created_at": NOW,
    }


def test_frontend_material_analysis_routes_match_the_published_contract() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_material_analysis_workbench_service] = FakeRouteAnalysisService

    with TestClient(app) as client:
        listed = client.get("/api/maitu/workbench/runs/MT-WB-RUN-001/video-analyses")
        backfill = client.post(
            "/api/maitu/workbench/runs/MT-WB-RUN-001/video-analyses/MT-MAT-AN-001/gemini-backfill",
            json={
                "asset_code": "AG-VID-1",
                "asset_fingerprint": FINGERPRINT,
                "raw_json": {
                    "analysis_task_code": "MT-MAT-AN-001",
                    "asset_code": "AG-VID-1",
                    "asset_fingerprint": FINGERPRINT,
                    "prompt_schema_version": "gemini-material-analysis-v1",
                    "observation": _observation(),
                },
            },
        )
        conflicts = client.get("/api/maitu/workbench/runs/MT-WB-RUN-001/analysis-conflicts")
        resolved = client.patch(
            "/api/maitu/workbench/runs/MT-WB-RUN-001/analysis-conflicts/MT-MAT-CON-001",
            json={"resolution": "gemini"},
        )

    assert listed.status_code == 200
    assert listed.json()[0]["asset_fingerprint"] == FINGERPRINT
    assert backfill.status_code == 200
    assert backfill.json()["gemini_status"] == "succeeded"
    assert conflicts.status_code == 200
    assert conflicts.json()[0]["severity"] == "critical"
    assert resolved.status_code == 200
    assert resolved.json()["resolution"] == "gemini"

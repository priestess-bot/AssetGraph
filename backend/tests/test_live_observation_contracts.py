from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.live_observations import (
    AnalysisRunCompletion,
    AnalysisRunCreate,
    RawEventBatchRegistration,
    RoomTemplateRevisionCreate,
    WatchTargetCreate,
)
from app.services.live_observations import (
    LiveObservationConflictError,
    build_template_projection,
    validate_timeline_append,
)


def test_watch_target_is_fixed_to_single_720p_stream_and_30_day_video_retention() -> None:
    target = WatchTargetCreate(
        display_name="research room",
        room_url="https://live.douyin.com/123456",
    )

    assert target.preferred_quality == "720p"
    assert target.retention_days == 30
    with pytest.raises(ValidationError):
        WatchTargetCreate(
            display_name="unsafe quality",
            room_url="https://live.douyin.com/123456",
            preferred_quality="original",
        )
    with pytest.raises(ValidationError):
        WatchTargetCreate(
            display_name="unsafe retention",
            room_url="https://live.douyin.com/123456",
            retention_days=29,
        )


def test_raw_event_batch_requires_gzip_mode_0600_and_has_no_retention_input() -> None:
    now = datetime.now(UTC)
    batch = RawEventBatchRegistration(
        batch_index=0,
        relative_path="events/LR-CAP-1/events.jsonl.gz",
        file_size=123,
        checksum_sha256="a" * 64,
        event_count=2,
        event_types={"chat": 2},
        first_received_at=now,
        last_received_at=now,
        finalized_at=now,
    )

    assert batch.file_mode == 0o600
    assert "retention_expires_at" not in batch.model_dump()
    with pytest.raises(ValidationError):
        RawEventBatchRegistration(
            **{**batch.model_dump(), "file_mode": 0o644}
        )


def test_analysis_dag_rejects_chunkless_sources_and_empty_aggregation() -> None:
    common = {
        "input_fingerprint": "a" * 64,
        "strategy_revision": "live.asr.zh.v2",
    }
    with pytest.raises(ValidationError, match="requires chunk_code"):
        AnalysisRunCreate(analysis_type="asr", **common)
    with pytest.raises(ValidationError, match="upstream observations"):
        AnalysisRunCreate(analysis_type="template_aggregation", **common)
    aggregation = AnalysisRunCreate(
        analysis_type="template_aggregation",
        parameters={"observations": [{"analysis_run_code": "run-1"}]},
        **common,
    )
    assert aggregation.chunk_code is None


def test_analysis_completion_rejects_supplier_metadata_in_domain_output() -> None:
    with pytest.raises(ValidationError, match="provider evidence"):
        AnalysisRunCompletion(
            worker_id="worker-1",
            lease_token="11111111-1111-1111-1111-111111111111",
            output_payload={
                "transcript": {"text": "verified", "actual_model": "supplier-model"}
            },
            invocation_evidence_ref="ART-EVIDENCE-001",
        )


def test_timeline_requires_sequential_non_overlapping_spans_and_explicit_gaps() -> None:
    first = {
        "span_index": 0,
        "global_start_seconds": 0,
        "global_end_seconds": 10,
        "chunk_start_seconds": 0,
        "chunk_end_seconds": 10,
        "mapping_slope": 1,
        "discontinuity_before": "none",
    }
    validate_timeline_append([], first)

    with pytest.raises(LiveObservationConflictError, match="declared explicitly"):
        validate_timeline_append(
            [first],
            {
                **first,
                "span_index": 1,
                "global_start_seconds": 15,
                "global_end_seconds": 25,
            },
        )
    validate_timeline_append(
        [first],
        {
            **first,
            "span_index": 1,
            "global_start_seconds": 15,
            "global_end_seconds": 25,
            "discontinuity_before": "gap",
        },
    )


def test_external_flat_template_projection_stays_reference_only_when_claimed_safe() -> None:
    revision = RoomTemplateRevisionCreate(
        canvas={"width": 1080, "height": 1920},
        scenes=[{"scene_key": "main"}],
        components=[
            {
                "component_id": "background",
                "scene_key": "main",
                "role": "background",
                "geometry": {"x": 0, "y": 0, "width": 1, "height": 1},
                "observability": "observed",
                "source_binding_status": "verified",
                "asset_code": "AG-IMG-1",
                "audio_classification": "unknown",
                "muted": True,
                "confidence": 0.95,
            }
        ],
        provenance={"source_session_codes": ["S1", "S2", "S3"]},
        confidence=0.95,
    ).model_dump(mode="json")
    revision.update({"revision_number": 1})
    projection = build_template_projection(
        {"template_code": "LR-TPL-1", "name": "room"}, revision
    )

    assert projection["layout_fidelity"] == "approximate"
    assert projection["buildability"] == "reference_only"
    assert projection["projection_ready"] is False
    assert projection["manual_review_required"] is True
    assert projection["blocking_reasons"] == ["external_flat_video_reference_only"]

    revision["provenance"] = {"source_session_codes": ["S1"]}
    blocked = build_template_projection(
        {"template_code": "LR-TPL-1", "name": "room"}, revision
    )
    assert blocked["projection_ready"] is False
    assert "external_flat_video_reference_only" in blocked["blocking_reasons"]
    assert "fewer_than_three_independent_source_sessions" in blocked["blocking_reasons"]


def test_unknown_template_audio_cannot_be_unmuted() -> None:
    with pytest.raises(ValidationError, match="unknown audio"):
        RoomTemplateRevisionCreate(
            canvas={"width": 1080, "height": 1920},
            components=[
                {
                    "component_id": "video",
                    "role": "video",
                    "geometry": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "observability": "observed",
                    "audio_classification": "unknown",
                    "muted": False,
                    "confidence": 0.9,
                }
            ],
            confidence=0.9,
        )

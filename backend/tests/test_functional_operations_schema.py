from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.errors import DomainValidationError
from app.schemas.functional_operations import (
    ContentExposureCorrection,
    OperationSessionCreate,
    SessionMetricSnapshotCreate,
    TimeMappingCreate,
)
from app.services.functional_operations import FunctionalOperationsService


def test_content_exposure_correction_requires_a_replacement_only_for_supersede() -> None:
    started_at = datetime.now(UTC)
    replacement = {
        "session_code": "OPS-001",
        "plan_code": "PLAN-001",
        "scene_code": "SCENE-001",
        "started_at": started_at,
        "ended_at": started_at + timedelta(minutes=1),
        "source_kind": "recording_match",
        "evidence_note": "Corrected against the recording.",
    }
    supersede = ContentExposureCorrection(
        source_exposure_code="EXPOSURE-001",
        correction_kind="supersede",
        reason="The original scene match was wrong.",
        replacement=replacement,
    )
    assert supersede.replacement is not None

    retract = ContentExposureCorrection(
        source_exposure_code="EXPOSURE-001",
        correction_kind="retract",
        reason="The source evidence was withdrawn.",
    )
    assert retract.replacement is None

    with pytest.raises(ValidationError, match="requires replacement"):
        ContentExposureCorrection(
            source_exposure_code="EXPOSURE-001",
            correction_kind="supersede",
            reason="No replacement.",
        )


def test_operation_session_metric_definition_pins_require_a_unique_existing_metric_key() -> None:
    started_at = datetime.now(UTC)
    session = OperationSessionCreate(
        title="Governed metric session",
        platform="douyin",
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=1),
        metrics={"orders": 4},
        metric_definition_refs=[
            {
                "metric_key": "orders",
                "metric_code": "orders-completed",
                "revision_number": 2,
            }
        ],
    )
    assert session.metric_definition_refs[0].metric_code == "orders-completed"

    with pytest.raises(ValidationError, match="has no metric value"):
        OperationSessionCreate(
            title="Missing metric",
            platform="douyin",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=1),
            metrics={"orders": 4},
            metric_definition_refs=[
                {
                    "metric_key": "clicks",
                    "metric_code": "clicks",
                    "revision_number": 1,
                }
            ],
        )

    with pytest.raises(ValidationError, match="is duplicated"):
        OperationSessionCreate(
            title="Duplicate metric",
            platform="douyin",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=1),
            metrics={"orders": 4},
            metric_definition_refs=[
                {
                    "metric_key": "orders",
                    "metric_code": "orders",
                    "revision_number": 1,
                },
                {
                    "metric_key": "orders",
                    "metric_code": "orders-v2",
                    "revision_number": 2,
                },
            ],
        )

    with pytest.raises(ValidationError, match="must be finite"):
        OperationSessionCreate(
            title="Infinite metric",
            platform="douyin",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=1),
            metrics={"orders": float("inf")},
        )


def test_time_mapping_requires_a_nonempty_half_open_coverage_interval() -> None:
    mapping = TimeMappingCreate(
        expected_revision=0,
        source_clock="recording_elapsed_ms",
        source_kind="recording_anchor",
        source_offset_ms=120,
        coverage_start_ms=0,
        coverage_end_ms=60_000,
        evidence_note="Matched the opening product scene to the recording.",
    )
    assert mapping.drift_ppm == 0

    with pytest.raises(ValidationError, match="must be after"):
        TimeMappingCreate(
            expected_revision=0,
            source_clock="recording_elapsed_ms",
            source_kind="recording_anchor",
            source_offset_ms=0,
            coverage_start_ms=60_000,
            coverage_end_ms=60_000,
            evidence_note="Invalid interval.",
        )


def test_session_metric_snapshot_selectors_are_declarative_json_pointers() -> None:
    ratio = SessionMetricSnapshotCreate(
        metric_key="conversion_rate",
        metric_code="conversion-rate",
        revision_number=1,
        numerator_json_pointer="/purchases",
        denominator_json_pointer="/visitors",
    )
    assert ratio.numerator_json_pointer == "/purchases"

    with pytest.raises(ValidationError, match="must start"):
        SessionMetricSnapshotCreate(
            metric_key="gmv",
            metric_code="gmv",
            revision_number=1,
            value_json_pointer="amount",
        )


def test_session_metric_snapshot_aggregation_is_deterministic_and_never_zero_fills() -> None:
    events = [
        {"event_id": "EVENT-001", "payload": {"amount": 3, "visitors": 10}},
        {"event_id": "EVENT-002", "payload": {"amount": 5, "visitors": 20}},
    ]
    summed = FunctionalOperationsService._aggregate_metric_events(
        aggregation="sum",
        events=events,
        value_json_pointer="/amount",
        numerator_json_pointer=None,
        denominator_json_pointer=None,
    )
    counted = FunctionalOperationsService._aggregate_metric_events(
        aggregation="count",
        events=events,
        value_json_pointer=None,
        numerator_json_pointer=None,
        denominator_json_pointer=None,
    )
    ratio = FunctionalOperationsService._aggregate_metric_events(
        aggregation="ratio",
        events=events,
        value_json_pointer=None,
        numerator_json_pointer="/amount",
        denominator_json_pointer="/visitors",
    )
    missing = FunctionalOperationsService._aggregate_metric_events(
        aggregation="count",
        events=[],
        value_json_pointer=None,
        numerator_json_pointer=None,
        denominator_json_pointer=None,
    )

    assert summed == (8.0, "ready", {})
    assert counted == (2.0, "ready", {})
    assert ratio == (8 / 30, "ready", {"numerator": 8.0, "denominator": 30.0})
    assert missing == (None, "insufficient_data", {"reason": "no_accepted_source_events"})

    with pytest.raises(DomainValidationError) as missing_selector:
        FunctionalOperationsService._aggregate_metric_events(
            aggregation="sum",
            events=events,
            value_json_pointer=None,
            numerator_json_pointer=None,
            denominator_json_pointer=None,
        )
    assert missing_selector.value.code == "SESSION_METRIC_SNAPSHOT_VALUE_SELECTOR_REQUIRED"

    with pytest.raises(DomainValidationError) as unknown_value:
        FunctionalOperationsService._aggregate_metric_events(
            aggregation="sum",
            events=events,
            value_json_pointer="/missing",
            numerator_json_pointer=None,
            denominator_json_pointer=None,
        )
    assert unknown_value.value.code == "SESSION_METRIC_SNAPSHOT_SELECTOR_MISSING"


def test_session_metric_snapshot_uses_catalog_deduplication_keys_and_tombstones() -> None:
    events = [
        {
            "event_id": "EVENT-001",
            "event_time": datetime(2026, 7, 25, 12, tzinfo=UTC),
            "payload": {"order_id": "order-1", "amount": 3},
            "tombstone": False,
        },
        {
            "event_id": "EVENT-002",
            "event_time": datetime(2026, 7, 25, 12, 1, tzinfo=UTC),
            "payload": {"order_id": "order-1", "amount": 5},
            "tombstone": False,
        },
        {
            "event_id": "EVENT-003",
            "event_time": datetime(2026, 7, 25, 12, 2, tzinfo=UTC),
            "payload": {"order_id": "order-2", "amount": 7},
            "tombstone": True,
        },
    ]

    effective, tombstoned = FunctionalOperationsService._deduplicate_metric_events(
        events, ["order_id"]
    )

    assert [event["event_id"] for event in effective] == ["EVENT-002"]
    assert tombstoned == 1
    with pytest.raises(DomainValidationError) as missing_key:
        FunctionalOperationsService._deduplicate_metric_events(
            [{**events[0], "payload": {"amount": 3}}], ["order_id"]
        )
    assert missing_key.value.code == "SESSION_METRIC_SNAPSHOT_DEDUPLICATION_KEY_MISSING"


def test_attribution_input_snapshot_and_quality_are_deterministic_and_descriptive() -> None:
    started_at = datetime(2026, 7, 25, 12, tzinfo=UTC)
    snapshot = FunctionalOperationsService._attribution_input_snapshot(
        [
            {
                "session_code": "OPS-002",
                "started_at": started_at,
                "ended_at": started_at + timedelta(minutes=1),
                "source_kind": "manual_import",
                "import_version": 1,
                "metrics": {"orders": 4},
                "metric_definition_refs": [
                    {"metric_key": "orders", "metric_code": "orders", "revision_number": 2}
                ],
            },
            {
                "session_code": "OPS-001",
                "started_at": started_at,
                "ended_at": started_at + timedelta(minutes=1),
                "source_kind": "adapter_import",
                "import_version": 3,
                "metrics": {"orders": 7},
                "metric_definition_refs": [],
            },
        ],
        {
            "OPS-002": [
                {
                    "exposure_code": "EXP-002",
                    "session_code": "OPS-002",
                    "plan_code": "PLAN-002",
                    "release_code": "REL-002",
                    "scene_code": "SCENE-002",
                    "started_at": started_at,
                    "ended_at": started_at + timedelta(seconds=20),
                    "source_kind": "recording_match",
                    "confidence": 0.9,
                }
            ],
            "OPS-001": [],
        },
        metric_key="orders",
    )

    assert [item["session_code"] for item in snapshot["sessions"]] == ["OPS-001", "OPS-002"]
    assert snapshot["active_exposures"][0]["exposure_code"] == "EXP-002"
    assert snapshot["sessions"][1]["metric_definition_refs"] == [
        {"metric_key": "orders", "metric_code": "orders", "revision_number": 2}
    ]

    incomplete, incomplete_status = FunctionalOperationsService._attribution_quality_snapshot(
        metric_definition_state="metric_unpinned",
        selected_session_count=2,
        observed_session_count=1,
        active_exposure_count=1,
        release_bound_exposure_count=1,
    )
    assert incomplete_status == "insufficient_data"
    assert incomplete["eligible_for_descriptive_publication"] is False
    assert incomplete["reasons"] == [
        "metric_definition_not_resolved",
        "some_sessions_have_no_observed_content",
    ]

    reviewable, reviewable_status = FunctionalOperationsService._attribution_quality_snapshot(
        metric_definition_state="resolved",
        selected_session_count=2,
        observed_session_count=2,
        active_exposure_count=3,
        release_bound_exposure_count=3,
    )
    assert reviewable_status == "review_required"
    assert reviewable["publication_scope"] == "descriptive_only"
    assert reviewable["eligible_for_descriptive_publication"] is True

def test_timeline_content_projection_uses_the_fixed_variant_chain() -> None:
    class ProjectionCursor:
        def execute(self, statement: str, parameters: object) -> None:
            assert "production_variant_revisions" in statement
            assert parameters == (["VAR-001"],)

        @staticmethod
        def fetchall() -> list[dict[str, object]]:
            return [
                {
                    "variant_code": "VAR-001",
                    "shot_code": "SHOT-001",
                    "segment_code": "SEGMENT-001",
                    "program_phase": "conversion",
                    "semantic_goal": "Guide the next action.",
                    "product_refs": ["PRODUCT-001"],
                    "cta_actions": [{"type": "comment"}],
                    "block_code": "BLOCK-001",
                    "module_type": "conversion",
                    "product_ref": "PRODUCT-001",
                    "template_sources": [
                        {"template_code": "TEMPLATE-001", "revision": 2}
                    ],
                    "cta_intent": {"type": "comment"},
                }
            ]

    projection = FunctionalOperationsService._timeline_content_projections(
        ProjectionCursor(), ["VAR-001"]
    )

    assert projection[("VAR-001", "SHOT-001")] == {
        "status": "resolved",
        "program_segment": {
            "segment_code": "SEGMENT-001",
            "program_phase": "conversion",
            "semantic_goal": "Guide the next action.",
            "product_refs": ["PRODUCT-001"],
            "cta_actions": [{"type": "comment"}],
        },
        "script_blocks": [
            {
                "block_code": "BLOCK-001",
                "module_type": "conversion",
                "product_ref": "PRODUCT-001",
                "template_modules": [
                    {
                        "template_code": "TEMPLATE-001",
                        "revision": 2,
                        "module_key": "conversion",
                    }
                ],
                "cta_intent": {"type": "comment"},
            }
        ],
    }

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.functional_operations import FunctionalOperationsService
from app.services.functional_operation_imports import (
    TEMPLATE_COLUMNS,
    operation_import_template_csv,
    operation_import_template_xlsx,
    read_operation_import_rows,
)


def test_csv_and_xlsx_templates_round_trip_to_the_same_customer_rows() -> None:
    csv_headers, csv_rows = read_operation_import_rows(
        operation_import_template_csv(), "csv"
    )
    xlsx_headers, xlsx_rows = read_operation_import_rows(
        operation_import_template_xlsx(), "xlsx"
    )

    expected_headers = [label for _key, label in TEMPLATE_COLUMNS]
    assert csv_headers == expected_headers
    assert xlsx_headers == expected_headers
    assert csv_rows == xlsx_rows
    assert len(csv_rows) == 2
    assert csv_rows[0]["来源时区"] == "Asia/Shanghai"
    assert csv_rows[0]["指标来源时钟"] == "recording_elapsed_ms"
    assert csv_rows[1]["区间开始毫秒"] == "60000"


def test_xlsx_template_is_a_real_zip_based_workbook() -> None:
    content = operation_import_template_xlsx()

    assert content.startswith(b"PK")
    assert b"LIVEPLAN-000001" not in content  # worksheet XML is compressed


class _DimensionCursor:
    def __init__(self) -> None:
        self.results = [
            [
                {
                    "plan_code": "PLAN-001",
                    "variant_code": "VARIANT-001",
                    "blueprint": {
                        "scenes": [
                            {
                                "scene_code": "SCENE-001",
                                "shot_code": "SHOT-001",
                                "layers": [
                                    {"asset_code": "ASSET-001", "title": "商品主图"}
                                ],
                            }
                        ]
                    },
                }
            ],
            [],
            [
                {
                    "variant_code": "VARIANT-001",
                    "shot_code": "SHOT-001",
                    "segment_code": "SEGMENT-001",
                    "program_phase": "product",
                    "semantic_goal": "讲解商品",
                    "product_refs": [],
                    "cta_actions": [],
                    "block_code": "BLOCK-001",
                    "module_type": "opening",
                    "product_ref": None,
                    "template_sources": [
                        {"template_code": "TPL-001", "revision": 2}
                    ],
                    "cta_intent": {},
                }
            ],
        ]

    def execute(self, _query: str, _parameters: object = None) -> None:
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return self.results.pop(0)


def test_descriptive_dimensions_use_explicit_content_lineage() -> None:
    start = datetime(2026, 7, 26, tzinfo=UTC)
    session = {
        "session_code": "OPS-001",
        "title": "晚场",
        "metrics": {"watchers": 120},
    }
    exposure = {
        "exposure_code": "EXPOSURE-001",
        "session_code": "OPS-001",
        "plan_code": "PLAN-001",
        "variant_code": "VARIANT-001",
        "scene_code": "SCENE-001",
        "content_kind": "live_room_plan",
        "scope_type": "maitu_scene",
        "scope_code": "SCENE-001",
        "started_at": start,
        "ended_at": start + timedelta(seconds=60),
    }

    groups = FunctionalOperationsService._dimension_groups(
        _DimensionCursor(),
        [session],
        {"OPS-001": [exposure]},
        metric_key="watchers",
    )

    assert {
        (group["dimension_type"], group["dimension_code"])
        for group in groups
    } == {
        ("operation_session", "OPS-001"),
        ("content_segment", "SEGMENT-001"),
        ("content_template", "TPL-001"),
        ("material", "ASSET-001"),
    }
    assert all(group["evidence_level"] == "descriptive" for group in groups)
    assert all(group["effect_signal_eligible"] is False for group in groups)


def test_metric_bucket_alignment_requires_the_matching_explicit_clock_mapping() -> None:
    start = datetime(2026, 7, 26, tzinfo=UTC)
    summary = {
        "time_mapping_missing_bucket_count": 0,
        "time_mapping_clock_mismatch_bucket_count": 0,
        "outside_time_mapping_coverage_bucket_count": 0,
        "direct_session_clock_bucket_count": 0,
        "time_mapped_bucket_count": 0,
    }
    session = {
        "started_at": start,
        "_metric_snapshot": {"event_time_clock": "recording_elapsed_ms"},
        "_time_mapping": {
            "mapping_code": "TIME-MAP-002",
            "source_clock": "recording_elapsed_ms",
            "source_offset_ms": 1_000,
            "drift_ppm": 0,
            "coverage_start_ms": 0,
            "coverage_end_ms": 60_000,
        },
    }

    aligned, mapping_code, basis = FunctionalOperationsService._bucket_allocation_time(
        {"event_time": start + timedelta(seconds=11)}, session, summary
    )

    assert aligned == start + timedelta(seconds=10)
    assert mapping_code == "TIME-MAP-002"
    assert basis == "event_time_inverse_active_time_mapping_within_exposure"
    assert summary["time_mapped_bucket_count"] == 1

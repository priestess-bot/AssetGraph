from __future__ import annotations
import os
from uuid import uuid4
import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.errors import DomainValidationError
from app.services.functional_learning import FunctionalLearningService

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def test_decisions_and_stable_experiment_outcomes() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        s = FunctionalLearningService(c)
        report_code = f"ATTR-LEARNING-{uuid4().hex}"
        with c.cursor() as cursor:
            cursor.execute(
                """INSERT INTO functional_attribution_reports
                   (report_code, metric_key, session_codes, results)
                   VALUES (%s, %s, %s, %s)""",
                (
                    report_code,
                    "watchers",
                    Jsonb(["OPS-001"]),
                    Jsonb({"groups": {}, "metadata": {}}),
                ),
            )
        c.commit()
        d = s.create_decision(
            {
                "observation": "观看人数较高",
                "recommendation": "复用开场节奏",
                "attribution_report_code": report_code,
            }
        )
        assert d["decision_code"].startswith("DEC-")
        assert d["attribution_report_code"] == report_code
        with pytest.raises(DomainValidationError) as missing_report:
            s.create_decision(
                {
                    "observation": "不存在的归因报告",
                    "recommendation": "不得关联",
                    "attribution_report_code": "ATTR-MISSING",
                }
            )
        assert missing_report.value.code == "LEARNING_ATTRIBUTION_REPORT_NOT_FOUND"
        e = s.create_experiment(
            {
                "title": "Opening",
                "metric_key": "watchers",
                "variants": ["control", "treatment"],
            }
        )
        first = s.record_outcome(
            e["experiment_code"], {"subject_key": "viewer-1", "metric_value": 12}
        )
        second = s.record_outcome(
            e["experiment_code"], {"subject_key": "viewer-1", "metric_value": 20}
        )
        assert first and second
        assert sum(item["sample_size"] for item in second["results"].values()) == 1

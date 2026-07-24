from __future__ import annotations
import os
import psycopg
import pytest
from app.services.functional_learning import FunctionalLearningService

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def test_decisions_and_stable_experiment_outcomes() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        s = FunctionalLearningService(c)
        d = s.create_decision(
            {"observation": "观看人数较高", "recommendation": "复用开场节奏"}
        )
        assert d["decision_code"].startswith("DEC-")
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

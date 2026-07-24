from __future__ import annotations
import os
import psycopg
import pytest
from app.services.functional_knowledge import FunctionalKnowledgeService

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def test_knowledge_search_and_impact() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        s = FunctionalKnowledgeService(c)
        first = s.create(
            {"title": "Product fact", "claim": "A verified fact", "related_codes": []}
        )
        second = s.create(
            {
                "title": "Related fact",
                "claim": "Uses product fact",
                "related_codes": [first["fact_code"]],
            }
        )
        assert any(x["fact_code"] == first["fact_code"] for x in s.list("verified"))
        assert {x["fact_code"] for x in s.impact(first["fact_code"])} >= {
            first["fact_code"],
            second["fact_code"],
        }

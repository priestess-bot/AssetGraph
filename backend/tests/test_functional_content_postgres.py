from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.services.functional_content import FunctionalContentService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_functional_content_chain_is_generated_and_can_be_regenerated() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        service = FunctionalContentService(connection)
        created = service.create_project(
            {
                "title": f"Functional project {uuid4().hex}",
                "generation_goal": "Explain a product choice through a concise live presentation",
                "theme": "Summer gathering",
                "story": "Start from a real hosting scenario.",
                "must_include": ["audience question"],
                "must_avoid": ["unsupported claim"],
                "fact_card_codes": [],
                "secondary_template_codes": [],
            },
            actor_id="test-operator",
        )
        first = service.generate_chain(created["project_code"], actor_id="test-operator")
        second = service.generate_chain(created["project_code"], actor_id="test-operator")

        assert first["generated"] is True
        assert first["generation_mode"] == "deterministic_demo"
        assert len(first["script"]["blocks"]) == 3
        assert len(first["program"]["segments"]) == 3
        assert len(first["shot_list"]["shots"]) == 3
        assert second["story_brief"]["revision_number"] == 2
        assert second["shot_list"]["revision_number"] == 2
        assert second["shot_list"]["shots"][0]["material_role_requirements"] == [
            "digital_human",
            "background",
        ]

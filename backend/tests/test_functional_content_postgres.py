from __future__ import annotations

import os
from hashlib import sha256
import json
from uuid import uuid4

import psycopg
import pytest

from app.services.functional_content import FunctionalContentService
from app.domain.errors import DomainConflictError, DomainValidationError
from app.repositories.maitu_workbench import MaituWorkbenchRepository


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


def test_content_project_update_requires_current_revision() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        service = FunctionalContentService(connection)
        created = service.create_project(
            {
                "title": f"Revision project {uuid4().hex}",
                "generation_goal": "Explain the selection constraints",
                "platform": "douyin",
            },
            actor_id="test-operator",
        )
        updated = service.update_project(
            created["project_code"],
            {
                "expected_revision": 1,
                "generation_goal": "Explain the selection constraints with an audience interaction",
                "persona": "trusted host",
                "interaction_requirements": ["ask one question"],
            },
            actor_id="test-operator",
        )

        assert updated["revision_number"] == 2
        assert updated["content"]["persona"] == "trusted host"
        assert updated["content"]["interaction_requirements"] == ["ask one question"]

        with pytest.raises(DomainConflictError) as conflict:
            service.update_project(
                created["project_code"],
                {"expected_revision": 1, "theme": "stale edit"},
                actor_id="test-operator",
            )
        assert conflict.value.code == "REVISION_CONFLICT"


def test_content_project_pins_and_revalidates_approved_fact_version() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        facts = MaituWorkbenchRepository(connection)
        fact_content = {
            "product_name": "Verified product",
            "positioning": "For a hosted gathering",
            "verified_facts": ["A verified fact"],
            "applicable_platforms": ["douyin"],
        }
        fact = facts.create_product_fact_card(
            {
                "title": f"Fact {uuid4().hex}",
                "content": fact_content,
                "approve": True,
                "approved_by": "test-reviewer",
            },
            content_sha256=sha256(json.dumps(fact_content, sort_keys=True).encode()).hexdigest(),
        )
        service = FunctionalContentService(connection)
        created = service.create_project(
            {
                "title": f"Fact pin project {uuid4().hex}",
                "generation_goal": "Use only approved product facts",
                "platform": "douyin",
                "fact_card_refs": [{"fact_card_code": fact["fact_card_code"], "version_number": 1}],
            },
            actor_id="test-operator",
        )
        detail = service.confirm_project(
            created["project_code"], expected_revision=1, actor_id="test-operator"
        )

        assert detail["fact_cards"] == [
            {
                "fact_card_code": fact["fact_card_code"],
                "version_number": 1,
                "version_code": f"{fact['fact_card_code']}-V001",
                "content_sha256": sha256(json.dumps(fact_content, sort_keys=True).encode()).hexdigest(),
            }
        ]

        replacement = {**fact_content, "verified_facts": ["A newer fact"]}
        facts.create_product_fact_card_version(
            fact["fact_card_code"],
            {"content": replacement, "approve": True, "approved_by": "test-reviewer"},
            content_sha256=sha256(json.dumps(replacement, sort_keys=True).encode()).hexdigest(),
        )
        with pytest.raises(DomainValidationError) as invalid:
            service.generate_chain(created["project_code"], actor_id="test-operator")
        assert invalid.value.code == "FACT_CARD_NOT_APPROVED"

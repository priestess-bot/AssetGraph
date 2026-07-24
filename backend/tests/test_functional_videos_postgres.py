from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.services.functional_content import FunctionalContentService
from app.services.functional_videos import FunctionalVideoService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_functional_video_plan_seeds_content_stages_and_queues_renderer() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        content = FunctionalContentService(connection)
        project = content.create_project(
            {
                "title": f"Video plan {suffix}",
                "generation_goal": "Explain a product choice in a short vertical video",
                "theme": "Summer choice",
                "story": "Start with a real question from the audience.",
                "must_include": [],
                "must_avoid": [],
                "fact_card_codes": [],
                "secondary_template_codes": [],
            },
            actor_id="test-operator",
        )
        generated = content.generate_chain(project["project_code"], actor_id="test-operator")
        plan = FunctionalVideoService(connection).create_plan(
            {"project_code": generated["project_code"], "target_duration_seconds": 55},
            actor_id="test-operator",
        )

        assert plan["job_status"] == "queued"
        assert plan["current_stage"] == "asset_selection"
        assert plan["progress_percent"] == 37
        assert plan["production_timeline"]["schema_version"] == "otio-compatible-production-timeline.v1"
        assert len(plan["production_timeline"]["tracks"][0]["clips"]) == 6
        assert plan["render_profile"]["visual_asset_mode"] == "baseline_verified_video_assets"

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM video_production_stages WHERE job_code = %s ORDER BY stage_order",
                (plan["video_job_code"],),
            )
            assert [row[0] for row in cursor.fetchall()] == ["succeeded", "succeeded", "succeeded", "pending", "pending", "pending", "pending", "pending"]
            cursor.execute(
                "SELECT production_variant_revision_id IS NOT NULL FROM video_production_jobs WHERE job_code = %s",
                (plan["video_job_code"],),
            )
            assert cursor.fetchone()[0] is True

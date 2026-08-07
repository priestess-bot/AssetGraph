from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.repositories.maitu_interactions import MaituInteractionsRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")
FINGERPRINT = "a" * 64
ANALYZER_VERSION = "maitu-interaction-v2-test"


def _analysis_payload(*, answered: bool, intent: str, topic: str) -> dict[str, object]:
    return {
        "output_fingerprint": ("b" if answered else "c") * 64,
        "invocation_evidence_ref": f"evidence/{topic}.json",
        "interaction_form": "question" if answered else "greeting",
        "business_intent": intent,
        "topic_summary": topic,
        "classification_reason": "集成测试分类依据",
        "quality_applicable": answered,
        "relevance_grade": "good" if answered else None,
        "completeness_grade": "fair" if answered else None,
        "resolution_grade": "fair" if answered else None,
        "overall_grade": "fair" if answered else None,
        "confidence": 0.9,
        "reason": "回复相关但不够完整" if answered else None,
    }


def test_v2_analysis_topics_and_dashboard_are_durable() -> None:
    assert DATABASE_URL is not None
    schema = f"maitu_interactions_v2_{uuid4().hex[:12]}"
    migration_root = Path(__file__).resolve().parents[1] / "migrations"
    migrations = [
        (migration_root / name).read_text(encoding="utf-8")
        for name in (
            "109_maitu_live_interactions.sql",
            "110_maitu_fixed_interaction_filter.sql",
            "111_maitu_fixed_interaction_analysis_cleanup.sql",
            "112_maitu_interaction_analysis_v2.sql",
        )
    ]
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
                for migration in migrations:
                    cursor.execute(sql.SQL(migration))
                cursor.execute("SELECT id FROM maitu_interaction_sources WHERE source_code = 'maitu-primary'")
                source_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO maitu_interaction_platforms (
                        source_id, external_platform_id, platform_code, platform_name
                    ) VALUES (%s, 4, 'jd', '京东') RETURNING id
                    """,
                    (source_id,),
                )
                platform_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO maitu_live_sessions (
                        source_id, platform_id, external_session_id, external_live_room_id,
                        title, started_at, ended_at, source_fingerprint
                    ) VALUES (
                        %s, %s, 156953, 9001, '集成测试直播',
                        now() - interval '1 hour', now(), %s
                    ) RETURNING id
                    """,
                    (source_id, platform_id, FINGERPRINT),
                )
                session_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO maitu_live_interactions (
                        source_id, session_id, external_interaction_id, live_room_id,
                        content, normalized_content, is_arrival, digital_reply_content,
                        source_fingerprint, analysis_input_fingerprint, published_at
                    ) VALUES
                        (%s, %s, 'answered', 9001, '整箱送一瓶吗', '整箱送一瓶吗', FALSE,
                         '前二十名整箱赠一瓶', %s, %s, now() - interval '2 minutes'),
                        (%s, %s, 'unanswered', 9001, '你好', '你好', FALSE,
                         NULL, %s, %s, now() - interval '1 minute')
                    """,
                    (
                        source_id,
                        session_id,
                        "d" * 64,
                        "e" * 64,
                        source_id,
                        session_id,
                        "f" * 64,
                        "1" * 64,
                    ),
                )
            connection.commit()

            repository = MaituInteractionsRepository(connection)
            assert repository.synchronize_analysis_jobs(ANALYZER_VERSION, "strategy-v2") == 2
            for _ in range(2):
                job = repository.claim_analysis_job(ANALYZER_VERSION, "test-worker", 300)
                assert job is not None
                answered = bool(job["interaction"]["is_answered"])
                repository.complete_analysis_job(
                    job["analysis_code"],
                    "test-worker",
                    job["lease_token"],
                    _analysis_payload(
                        answered=answered,
                        intent="promotion" if answered else "small_talk",
                        topic="整箱赠品" if answered else "问候",
                    ),
                )

            assert repository.synchronize_topic_jobs(ANALYZER_VERSION) == 2
            for _ in range(2):
                batch = repository.claim_topic_batch(ANALYZER_VERSION, "test-worker", 300)
                assert batch is not None
                assignments = [
                    {
                        "item_key": item["analysis_result_id"],
                        "topic_code": None,
                        "topic_title": item["topic_summary"],
                    }
                    for item in batch["jobs"]
                ]
                repository.complete_topic_batch(
                    "test-worker",
                    batch["lease_token"],
                    business_intent=batch["business_intent"],
                    assignments=assignments,
                    invocation_evidence_ref="evidence/topic-batch.json",
                )

            dashboard = repository.analysis_dashboard(
                ANALYZER_VERSION,
                platform_id=None,
                external_session_id=None,
            )
            assert dashboard | {"intents": []} == {
                "total": 2,
                "classified": 2,
                "classification_pending": 0,
                "topic_pending": 0,
                "answered": 1,
                "unanswered": 1,
                "quality_evaluated": 1,
                "intents": [],
            }
            assert {item["business_intent"] for item in dashboard["intents"]} == {
                "promotion",
                "small_talk",
            }
            topics = repository.list_topics(
                ANALYZER_VERSION,
                business_intent=None,
                platform_id=None,
                external_session_id=None,
                limit=10,
                offset=0,
            )
            assert topics["total"] == 2
            assert {item["title"] for item in topics["items"]} == {"整箱赠品", "问候"}
            interactions = repository.list_interactions(
                analyzer_version=ANALYZER_VERSION,
                external_session_id=None,
                platform_id=None,
                include_arrivals=False,
                answered=False,
                interaction_form=None,
                business_intent=None,
                overall_grade=None,
                search=None,
                limit=10,
                offset=0,
            )
            assert interactions["items"][0]["analysis"]["quality_applicable"] is False
            assert interactions["items"][0]["analysis"]["overall_grade"] is None
            assert interactions["items"][0]["topic_status"] == "succeeded"
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as cleanup:
            cleanup.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))

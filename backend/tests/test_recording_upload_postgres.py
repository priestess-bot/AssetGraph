from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.repositories.live_observations import LiveObservationRepository
from app.services.live_observations import default_chunk_analysis_specs


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="ASSETGRAPH_TEST_DATABASE_URL is not configured",
)


def test_uploaded_recording_creates_reusable_room_timeline_and_analysis_dag() -> None:
    schema = f"recording_upload_test_{uuid4().hex[:12]}"
    migration_root = Path(__file__).resolve().parents[1] / "migrations"
    migrations = [
        (migration_root / name).read_text(encoding="utf-8")
        for name in (
            "023_maitu_production_workbench.sql",
            "024_live_research_observations.sql",
            "043_provider_neutral_producer_contracts.sql",
        )
    ]
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                cursor.execute(
                    sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
                )
                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE {}.artifact_refs "
                        "(LIKE public.artifact_refs INCLUDING ALL)"
                    ).format(sql.Identifier(schema))
                )
                for migration in migrations:
                    cursor.execute(sql.SQL(migration))
            connection.commit()
            repository = LiveObservationRepository(connection)
            ended_at = datetime.now(UTC)
            session = repository.import_recording(
                {
                    "source_room_id": "893746120",
                    "source_room_title": "品牌夏季专场",
                    "file_name": "room.mp4",
                    "relative_path": "uploads/aa/recording.mp4",
                    "file_size": 1024,
                    "checksum_sha256": "a" * 64,
                    "content_type": "video/mp4",
                    "container_format": "mp4",
                    "duration_seconds": 60.5,
                    "media_probe": {
                        "schema_version": "file-truth-v1",
                        "video": {
                            "codec": "h264",
                            "width": 1080,
                            "height": 1920,
                            "frame_rate": "30/1",
                            "time_base": "1/90000",
                        },
                        "audio": [{"codec": "aac", "sample_rate": 48000, "channels": 2}],
                    },
                    "observed_started_at": ended_at - timedelta(seconds=60.5),
                    "observed_ended_at": ended_at,
                },
                analysis_specs=default_chunk_analysis_specs(),
            )

            assert session["status"] == "completed"
            assert session["metadata"]["source_type"] == "uploaded_recording"
            assert len(session["chunks"]) == 1
            assert len(session["timeline"]) == 1
            assert float(session["timeline"][0]["global_end_seconds"]) == 60.5
            assert {item["media_kind"] for item in session["channels"]} == {"video", "audio"}
            runs = repository.list_analysis_runs(
                session_code=session["session_code"],
                analysis_type=None,
                status=None,
                limit=20,
                offset=0,
            )
            assert {item["analysis_type"] for item in runs} == {
                "frame_sampling",
                "asr",
                "ocr",
                "layout_inference",
            }
            target = repository.get_watch_target(session["target_code"])
            assert target is not None
            assert target["status"] == "paused"
            assert target["metadata"]["capture_mode"] == "upload_only"
    finally:
        if DATABASE_URL:
            with psycopg.connect(DATABASE_URL, autocommit=True) as cleanup:
                cleanup.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))

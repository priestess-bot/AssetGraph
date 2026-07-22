from pathlib import Path


def test_live_research_migration_enforces_video_ttl_and_permanent_raw_events() -> None:
    sql = Path("migrations/024_live_research_observations.sql").read_text(encoding="utf-8")

    assert "idx_live_capture_sessions_single_active" in sql
    assert "preferred_quality = '720p'" in sql
    assert "retention_expires_at >= finalized_at + interval '30 days'" in sql
    assert "chk_live_raw_event_batch_retention CHECK (retention_expires_at IS NULL)" in sql
    assert "idx_live_raw_event_batches_retention" not in sql
    assert "entity_type = 'capture_chunk'" in sql
    assert "file_mode = 384" in sql
    assert "delete_claim_token UUID" in sql
    assert "delete_claim_expires_at TIMESTAMPTZ" in sql
    assert "idx_live_capture_chunks_delete_lease" in sql
    assert "attempt_count INTEGER NOT NULL DEFAULT 0" in sql
    assert "max_attempts INTEGER NOT NULL DEFAULT 3" in sql
    assert "retry_history JSONB NOT NULL DEFAULT '[]'::jsonb" in sql

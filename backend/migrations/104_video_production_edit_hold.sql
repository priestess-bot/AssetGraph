ALTER TABLE video_production_jobs
    ADD COLUMN IF NOT EXISTS edit_locked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_video_production_jobs_editable_queue
    ON video_production_jobs(status, edit_locked, created_at);

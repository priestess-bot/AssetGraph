-- Render-time artifacts are produced after a TimelineSegment is frozen.  Keep
-- their evidence append-only in a separate table instead of mutating the
-- segment's planning-time input references.

CREATE TABLE IF NOT EXISTS functional_video_timeline_segment_execution_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timeline_segment_id UUID NOT NULL REFERENCES functional_video_timeline_segments(id) ON DELETE CASCADE,
    video_artifact_id UUID NOT NULL REFERENCES video_production_artifacts(id) ON DELETE CASCADE,
    job_attempt INTEGER NOT NULL,
    artifact_role VARCHAR(32) NOT NULL,
    artifact_key VARCHAR(64) NOT NULL,
    relative_path TEXT NOT NULL,
    checksum_sha256 CHAR(64) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (timeline_segment_id, job_attempt, artifact_role),
    CONSTRAINT chk_functional_video_timeline_execution_attempt
        CHECK (job_attempt >= 1),
    CONSTRAINT chk_functional_video_timeline_execution_role
        CHECK (artifact_role IN ('voice_segment', 'subtitle_track')),
    CONSTRAINT chk_functional_video_timeline_execution_path
        CHECK (relative_path <> '' AND relative_path !~ '(^|/)\.\.(/|$)' AND relative_path !~ '^/'),
    CONSTRAINT chk_functional_video_timeline_execution_checksum
        CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_functional_video_timeline_execution_evidence
        CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_functional_video_timeline_execution_segment
    ON functional_video_timeline_segment_execution_artifacts(timeline_segment_id, created_at);

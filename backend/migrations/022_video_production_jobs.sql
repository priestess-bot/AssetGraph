-- Theme-driven commercial video production jobs and durable stage checkpoints.

CREATE TABLE IF NOT EXISTS video_production_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_code VARCHAR(40) NOT NULL UNIQUE,
    topic VARCHAR(1000) NOT NULL,
    preset_code VARCHAR(64) NOT NULL DEFAULT 'zhangyu_wine_demo_v1',
    target_duration_seconds INTEGER NOT NULL DEFAULT 55,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    current_stage VARCHAR(64),
    progress_percent INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 1,
    story_brief JSONB NOT NULL DEFAULT '{}'::jsonb,
    script JSONB NOT NULL DEFAULT '{}'::jsonb,
    shot_list JSONB NOT NULL DEFAULT '{}'::jsonb,
    asset_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    final_asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_video_production_job_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    CONSTRAINT chk_video_production_job_stage
        CHECK (
            current_stage IS NULL OR current_stage IN (
                'brief_generation', 'script_generation', 'shot_planning', 'asset_selection',
                'voice_synthesis', 'subtitle_generation', 'rendering', 'quality_check'
            )
        ),
    CONSTRAINT chk_video_production_job_duration
        CHECK (target_duration_seconds BETWEEN 15 AND 600),
    CONSTRAINT chk_video_production_job_progress
        CHECK (progress_percent BETWEEN 0 AND 100),
    CONSTRAINT chk_video_production_job_attempt
        CHECK (attempt >= 1),
    CONSTRAINT chk_video_production_job_json_objects
        CHECK (
            jsonb_typeof(story_brief) = 'object'
            AND jsonb_typeof(script) = 'object'
            AND jsonb_typeof(shot_list) = 'object'
            AND jsonb_typeof(asset_plan) = 'object'
            AND jsonb_typeof(quality_report) = 'object'
        ),
    CONSTRAINT chk_video_production_job_lease
        CHECK (
            (claimed_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
            OR (claimed_by IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        ),
    CONSTRAINT chk_video_production_job_terminal
        CHECK (
            (status = 'succeeded' AND completed_at IS NOT NULL AND error_code IS NULL)
            OR status <> 'succeeded'
        )
);

CREATE INDEX IF NOT EXISTS idx_video_production_jobs_queue
    ON video_production_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_video_production_jobs_lease
    ON video_production_jobs(lease_expires_at)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS video_production_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES video_production_jobs(id) ON DELETE CASCADE,
    job_code VARCHAR(40) NOT NULL,
    stage_name VARCHAR(64) NOT NULL,
    stage_order INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 1,
    input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(64),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, stage_name),
    UNIQUE (job_id, stage_order),
    CONSTRAINT chk_video_production_stage_name
        CHECK (stage_name IN (
            'brief_generation', 'script_generation', 'shot_planning', 'asset_selection',
            'voice_synthesis', 'subtitle_generation', 'rendering', 'quality_check'
        )),
    CONSTRAINT chk_video_production_stage_order CHECK (stage_order BETWEEN 1 AND 8),
    CONSTRAINT chk_video_production_stage_status
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    CONSTRAINT chk_video_production_stage_attempt CHECK (attempt >= 1),
    CONSTRAINT chk_video_production_stage_json_objects
        CHECK (jsonb_typeof(input_payload) = 'object' AND jsonb_typeof(output_payload) = 'object'),
    CONSTRAINT chk_video_production_stage_terminal
        CHECK (
            (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
            OR status NOT IN ('succeeded', 'failed')
        )
);

CREATE INDEX IF NOT EXISTS idx_video_production_stages_job
    ON video_production_stages(job_id, stage_order);

CREATE TABLE IF NOT EXISTS video_production_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES video_production_jobs(id) ON DELETE CASCADE,
    stage_id UUID NOT NULL REFERENCES video_production_stages(id) ON DELETE CASCADE,
    job_code VARCHAR(40) NOT NULL,
    artifact_key VARCHAR(64) NOT NULL,
    relative_path TEXT NOT NULL,
    mime_type VARCHAR(128),
    file_size BIGINT,
    checksum_sha256 CHAR(64),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, artifact_key),
    CONSTRAINT chk_video_production_artifact_key
        CHECK (artifact_key IN (
            'story_brief', 'script', 'shot_list', 'asset_plan', 'voice',
            'subtitles', 'poster', 'quality_report', 'video', 'render_log'
        )),
    CONSTRAINT chk_video_production_artifact_path
        CHECK (relative_path <> '' AND relative_path !~ '(^|/)\.\.(/|$)' AND relative_path !~ '^/'),
    CONSTRAINT chk_video_production_artifact_size CHECK (file_size IS NULL OR file_size >= 0),
    CONSTRAINT chk_video_production_artifact_checksum
        CHECK (checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_video_production_artifact_metadata CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_video_production_artifacts_job
    ON video_production_artifacts(job_id, created_at);

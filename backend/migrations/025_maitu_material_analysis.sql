-- Durable Maitu workbench video analysis, manual Gemini observations, and review conflicts.

CREATE TABLE IF NOT EXISTS maitu_workbench_video_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_code VARCHAR(80) NOT NULL UNIQUE,
    run_id UUID NOT NULL REFERENCES maitu_workbench_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(64) NOT NULL,
    origin_requirement_id UUID REFERENCES maitu_workbench_material_requirements(id) ON DELETE SET NULL,
    requirement_code VARCHAR(80),
    asset_code VARCHAR(64) NOT NULL,
    asset_fingerprint CHAR(64),
    asset_title VARCHAR(512) NOT NULL,
    source_relative_path TEXT,
    source_root_kind VARCHAR(32),
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 1,
    provisional_source VARCHAR(32) NOT NULL DEFAULT 'none',
    provisional_summary TEXT,
    technical JSONB NOT NULL DEFAULT '{}'::jsonb,
    frame_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    automatic_observation JSONB NOT NULL DEFAULT '{}'::jsonb,
    merged_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    gemini_status VARCHAR(32) NOT NULL DEFAULT 'not_requested',
    gemini_summary TEXT,
    current_gemini_revision INTEGER NOT NULL DEFAULT 0,
    model_provider VARCHAR(64),
    model_requested VARCHAR(128),
    model_actual VARCHAR(128),
    model_prompt_version VARCHAR(64),
    model_request_id VARCHAR(255),
    model_input_fingerprint CHAR(64),
    model_output_fingerprint CHAR(64),
    model_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_latency_ms INTEGER,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, asset_code),
    CONSTRAINT chk_maitu_video_analysis_fingerprint
        CHECK (asset_fingerprint IS NULL OR asset_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_video_analysis_source_root
        CHECK (source_root_kind IS NULL OR source_root_kind IN ('asset_materials', 'maitu_mirror')),
    CONSTRAINT chk_maitu_video_analysis_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT chk_maitu_video_analysis_attempt CHECK (attempt >= 1),
    CONSTRAINT chk_maitu_video_analysis_provisional_source
        CHECK (provisional_source IN ('none', 'keyframe', 'gpt_5_6_sol')),
    CONSTRAINT chk_maitu_video_analysis_gemini_status
        CHECK (gemini_status IN ('not_requested', 'queued', 'running', 'succeeded', 'failed')),
    CONSTRAINT chk_maitu_video_analysis_gemini_revision CHECK (current_gemini_revision >= 0),
    CONSTRAINT chk_maitu_video_analysis_technical CHECK (jsonb_typeof(technical) = 'object'),
    CONSTRAINT chk_maitu_video_analysis_frames CHECK (jsonb_typeof(frame_manifest) = 'object'),
    CONSTRAINT chk_maitu_video_analysis_observation CHECK (jsonb_typeof(automatic_observation) = 'object'),
    CONSTRAINT chk_maitu_video_analysis_profile CHECK (jsonb_typeof(merged_profile) = 'object'),
    CONSTRAINT chk_maitu_video_analysis_usage CHECK (jsonb_typeof(model_usage) = 'object'),
    CONSTRAINT chk_maitu_video_analysis_model_input_sha
        CHECK (model_input_fingerprint IS NULL OR model_input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_video_analysis_model_output_sha
        CHECK (model_output_fingerprint IS NULL OR model_output_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_video_analysis_latency CHECK (model_latency_ms IS NULL OR model_latency_ms >= 0),
    CONSTRAINT chk_maitu_video_analysis_lease
        CHECK (
            (claimed_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
            OR (claimed_by IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        ),
    CONSTRAINT chk_maitu_video_analysis_terminal
        CHECK (
            (status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL)
            OR status NOT IN ('succeeded', 'failed', 'cancelled')
        )
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_video_analysis_queue
ON maitu_workbench_video_analyses(status, created_at);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_video_analysis_run
ON maitu_workbench_video_analyses(run_id, asset_code);

CREATE TABLE IF NOT EXISTS maitu_workbench_gemini_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_code VARCHAR(80) NOT NULL UNIQUE,
    analysis_id UUID NOT NULL REFERENCES maitu_workbench_video_analyses(id) ON DELETE CASCADE,
    analysis_code VARCHAR(80) NOT NULL,
    run_id UUID NOT NULL REFERENCES maitu_workbench_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    asset_code VARCHAR(64) NOT NULL,
    asset_fingerprint CHAR(64) NOT NULL,
    prompt_schema_version VARCHAR(64) NOT NULL,
    raw_submission JSONB NOT NULL,
    parsed_observation JSONB NOT NULL,
    merged_profile JSONB NOT NULL,
    submitted_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (analysis_id, revision_number),
    CONSTRAINT chk_maitu_gemini_submission_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_maitu_gemini_submission_sha CHECK (asset_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_gemini_submission_raw CHECK (jsonb_typeof(raw_submission) = 'object'),
    CONSTRAINT chk_maitu_gemini_submission_observation CHECK (jsonb_typeof(parsed_observation) = 'object'),
    CONSTRAINT chk_maitu_gemini_submission_profile CHECK (jsonb_typeof(merged_profile) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_gemini_submission_analysis
ON maitu_workbench_gemini_submissions(analysis_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS maitu_workbench_analysis_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conflict_code VARCHAR(80) NOT NULL UNIQUE,
    analysis_id UUID NOT NULL REFERENCES maitu_workbench_video_analyses(id) ON DELETE CASCADE,
    analysis_code VARCHAR(80) NOT NULL,
    submission_id UUID NOT NULL REFERENCES maitu_workbench_gemini_submissions(id) ON DELETE CASCADE,
    submission_code VARCHAR(80) NOT NULL,
    run_id UUID NOT NULL REFERENCES maitu_workbench_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(64) NOT NULL,
    field VARCHAR(128) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    provisional_value JSONB,
    gemini_value JSONB,
    reason TEXT NOT NULL,
    resolution VARCHAR(32),
    resolved_by VARCHAR(128),
    resolved_at TIMESTAMPTZ,
    is_current BOOLEAN NOT NULL DEFAULT true,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_analysis_conflict_severity CHECK (severity IN ('warning', 'critical')),
    CONSTRAINT chk_maitu_analysis_conflict_resolution
        CHECK (resolution IS NULL OR resolution IN ('provisional', 'gemini', 'replace_asset')),
    CONSTRAINT chk_maitu_analysis_conflict_resolution_audit
        CHECK (
            (resolution IS NULL AND resolved_by IS NULL AND resolved_at IS NULL)
            OR (resolution IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)
        ),
    CONSTRAINT chk_maitu_analysis_conflict_current
        CHECK (
            (is_current = true AND superseded_at IS NULL)
            OR (is_current = false AND superseded_at IS NOT NULL)
        )
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_analysis_conflict_current
ON maitu_workbench_analysis_conflicts(run_id, severity, resolution)
WHERE is_current = true;

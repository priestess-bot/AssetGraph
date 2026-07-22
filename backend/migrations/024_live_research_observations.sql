-- Douyin live-research capture, timeline, analysis, and template publication.

CREATE TABLE IF NOT EXISTS live_research_sequences (
    sequence_date DATE NOT NULL,
    object_type VARCHAR(32) NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sequence_date, object_type)
);

CREATE TABLE IF NOT EXISTS live_watch_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_code VARCHAR(64) NOT NULL UNIQUE,
    platform VARCHAR(32) NOT NULL DEFAULT 'douyin',
    room_url TEXT NOT NULL,
    canonical_room_id VARCHAR(128),
    display_name VARCHAR(255) NOT NULL,
    recorder_engine VARCHAR(32) NOT NULL DEFAULT 'streamcap',
    preferred_quality VARCHAR(32) NOT NULL DEFAULT '720p',
    status VARCHAR(32) NOT NULL DEFAULT 'enabled',
    poll_interval_seconds INTEGER NOT NULL DEFAULT 180,
    retention_days INTEGER NOT NULL DEFAULT 30,
    next_check_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_observed_at TIMESTAMPTZ,
    last_live_at TIMESTAMPTZ,
    last_capture_session_code VARCHAR(64),
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code VARCHAR(64),
    last_error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    claimed_by VARCHAR(128),
    claim_token UUID,
    lease_version BIGINT NOT NULL DEFAULT 0,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT chk_live_watch_target_platform CHECK (platform = 'douyin'),
    CONSTRAINT chk_live_watch_target_recorder CHECK (recorder_engine IN ('streamcap', 'external')),
    CONSTRAINT chk_live_watch_target_status CHECK (status IN ('enabled', 'paused', 'blocked', 'deleted')),
    CONSTRAINT chk_live_watch_target_poll CHECK (poll_interval_seconds BETWEEN 30 AND 86400),
    CONSTRAINT chk_live_watch_target_quality CHECK (preferred_quality = '720p'),
    CONSTRAINT chk_live_watch_target_retention CHECK (retention_days = 30),
    CONSTRAINT chk_live_watch_target_failures CHECK (consecutive_failures >= 0),
    CONSTRAINT chk_live_watch_target_metadata CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT chk_live_watch_target_lease CHECK (
        (claimed_by IS NULL AND claim_token IS NULL AND lease_expires_at IS NULL)
        OR (claimed_by IS NOT NULL AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_live_watch_targets_room_active
    ON live_watch_targets(platform, room_url)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_live_watch_targets_canonical_room_active
    ON live_watch_targets(platform, canonical_room_id)
    WHERE deleted_at IS NULL AND canonical_room_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_live_watch_targets_scheduler
    ON live_watch_targets(status, next_check_at, lease_expires_at)
    WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS live_capture_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_code VARCHAR(64) NOT NULL UNIQUE,
    target_id UUID NOT NULL REFERENCES live_watch_targets(id),
    target_code VARCHAR(64) NOT NULL,
    platform VARCHAR(32) NOT NULL DEFAULT 'douyin',
    source_live_session_id VARCHAR(255),
    recorder_engine VARCHAR(32) NOT NULL,
    recorder_version VARCHAR(64) NOT NULL,
    recorder_build_fingerprint VARCHAR(128) NOT NULL,
    event_adapter VARCHAR(64) NOT NULL DEFAULT 'douyinlive',
    event_adapter_version VARCHAR(64) NOT NULL DEFAULT 'v2.0.24',
    status VARCHAR(32) NOT NULL DEFAULT 'starting',
    observed_started_at TIMESTAMPTZ NOT NULL,
    observed_ended_at TIMESTAMPTZ,
    monotonic_started_ns BIGINT,
    monotonic_ended_ns BIGINT,
    capture_boot_id VARCHAR(128),
    timeline_origin_at TIMESTAMPTZ,
    failure_code VARCHAR(64),
    failure_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_live_capture_session_platform CHECK (platform = 'douyin'),
    CONSTRAINT chk_live_capture_session_status CHECK (
        status IN ('starting', 'recording', 'finalizing', 'completed', 'failed', 'abandoned')
    ),
    CONSTRAINT chk_live_capture_session_metadata CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT chk_live_capture_session_wall_time CHECK (
        observed_ended_at IS NULL OR observed_ended_at >= observed_started_at
    ),
    CONSTRAINT chk_live_capture_session_monotonic CHECK (
        monotonic_ended_ns IS NULL OR monotonic_started_ns IS NULL OR monotonic_ended_ns >= monotonic_started_ns
    ),
    CONSTRAINT chk_live_capture_session_terminal CHECK (
        (status IN ('completed', 'failed', 'abandoned') AND ended_at IS NOT NULL)
        OR status NOT IN ('completed', 'failed', 'abandoned')
    )
);

CREATE INDEX IF NOT EXISTS idx_live_capture_sessions_target
    ON live_capture_sessions(target_id, observed_started_at DESC);
CREATE INDEX IF NOT EXISTS idx_live_capture_sessions_status
    ON live_capture_sessions(status, observed_started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_live_capture_sessions_single_active
    ON live_capture_sessions((1))
    WHERE status IN ('starting', 'recording', 'finalizing');

CREATE TABLE IF NOT EXISTS live_capture_channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES live_capture_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    channel_key VARCHAR(128) NOT NULL,
    media_kind VARCHAR(16) NOT NULL,
    stream_index INTEGER NOT NULL,
    codec_name VARCHAR(64),
    time_base VARCHAR(32),
    language VARCHAR(32),
    sample_rate INTEGER,
    channels INTEGER,
    width INTEGER,
    height INTEGER,
    average_frame_rate VARCHAR(32),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, channel_key),
    UNIQUE (session_id, media_kind, stream_index),
    CONSTRAINT chk_live_capture_channel_kind CHECK (media_kind IN ('video', 'audio', 'data')),
    CONSTRAINT chk_live_capture_channel_index CHECK (stream_index >= 0),
    CONSTRAINT chk_live_capture_channel_dimensions CHECK (
        (width IS NULL AND height IS NULL) OR (width > 0 AND height > 0)
    ),
    CONSTRAINT chk_live_capture_channel_audio CHECK (
        (sample_rate IS NULL OR sample_rate > 0) AND (channels IS NULL OR channels > 0)
    ),
    CONSTRAINT chk_live_capture_channel_metadata CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE IF NOT EXISTS live_capture_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES live_capture_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    part_index INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    container_format VARCHAR(32) NOT NULL DEFAULT 'mpegts',
    status VARCHAR(32) NOT NULL DEFAULT 'writing',
    file_size BIGINT,
    checksum_sha256 CHAR(64),
    capture_started_at TIMESTAMPTZ,
    capture_ended_at TIMESTAMPTZ,
    finalized_at TIMESTAMPTZ,
    retention_expires_at TIMESTAMPTZ,
    source_start_seconds NUMERIC(18, 6),
    source_end_seconds NUMERIC(18, 6),
    decoded_duration_seconds NUMERIC(18, 6),
    stream_timing JSONB NOT NULL DEFAULT '{}'::jsonb,
    media_probe JSONB NOT NULL DEFAULT '{}'::jsonb,
    discontinuity_kind VARCHAR(32) NOT NULL DEFAULT 'none',
    discontinuity_milliseconds BIGINT NOT NULL DEFAULT 0,
    timeline_ready BOOLEAN NOT NULL DEFAULT false,
    legal_hold BOOLEAN NOT NULL DEFAULT false,
    pinned_until TIMESTAMPTZ,
    delete_marked_at TIMESTAMPTZ,
    delete_claimed_by VARCHAR(128),
    delete_claim_token UUID,
    delete_claim_expires_at TIMESTAMPTZ,
    delete_heartbeat_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    tombstone JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, part_index),
    UNIQUE (session_id, relative_path),
    CONSTRAINT chk_live_capture_chunk_part CHECK (part_index >= 0),
    CONSTRAINT chk_live_capture_chunk_path CHECK (
        relative_path <> '' AND relative_path !~ '(^|/)\.\.(/|$)' AND relative_path !~ '^/'
    ),
    CONSTRAINT chk_live_capture_chunk_status CHECK (
        status IN ('writing', 'finalized', 'quarantined', 'delete_candidate', 'deleted', 'failed')
    ),
    CONSTRAINT chk_live_capture_chunk_size CHECK (file_size IS NULL OR file_size >= 0),
    CONSTRAINT chk_live_capture_chunk_checksum CHECK (
        checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_live_capture_chunk_times CHECK (
        capture_ended_at IS NULL OR capture_started_at IS NULL OR capture_ended_at >= capture_started_at
    ),
    CONSTRAINT chk_live_capture_chunk_source_range CHECK (
        source_end_seconds IS NULL OR source_start_seconds IS NULL OR source_end_seconds > source_start_seconds
    ),
    CONSTRAINT chk_live_capture_chunk_duration CHECK (
        decoded_duration_seconds IS NULL OR decoded_duration_seconds > 0
    ),
    CONSTRAINT chk_live_capture_chunk_discontinuity CHECK (
        discontinuity_kind IN ('none', 'reset', 'gap', 'overlap', 'reconnect', 'unknown')
    ),
    CONSTRAINT chk_live_capture_chunk_json CHECK (
        jsonb_typeof(stream_timing) = 'object'
        AND jsonb_typeof(media_probe) = 'object'
        AND jsonb_typeof(tombstone) = 'object'
    ),
    CONSTRAINT chk_live_capture_chunk_finalized CHECK (
        status NOT IN ('finalized', 'delete_candidate', 'deleted')
        OR (
            file_size IS NOT NULL AND checksum_sha256 IS NOT NULL AND finalized_at IS NOT NULL
            AND retention_expires_at >= finalized_at + interval '30 days'
        )
    ),
    CONSTRAINT chk_live_capture_chunk_deleted CHECK (
        status <> 'deleted' OR deleted_at IS NOT NULL
    ),
    CONSTRAINT chk_live_capture_chunk_delete_lease CHECK (
        (
            delete_claimed_by IS NULL AND delete_claim_token IS NULL
            AND delete_claim_expires_at IS NULL AND delete_heartbeat_at IS NULL
        )
        OR (
            delete_claimed_by IS NOT NULL AND delete_claim_token IS NOT NULL
            AND delete_claim_expires_at IS NOT NULL AND delete_heartbeat_at IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_live_capture_chunks_session
    ON live_capture_chunks(session_id, part_index);
CREATE INDEX IF NOT EXISTS idx_live_capture_chunks_retention
    ON live_capture_chunks(retention_expires_at, status)
    WHERE status IN ('finalized', 'delete_candidate') AND legal_hold = false;
CREATE INDEX IF NOT EXISTS idx_live_capture_chunks_delete_lease
    ON live_capture_chunks(delete_claim_expires_at)
    WHERE status = 'delete_candidate';

CREATE TABLE IF NOT EXISTS live_raw_event_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES live_capture_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    batch_index INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'finalized',
    schema_version VARCHAR(32) NOT NULL,
    content_encoding VARCHAR(16) NOT NULL DEFAULT 'gzip',
    file_mode INTEGER NOT NULL DEFAULT 384,
    file_size BIGINT NOT NULL,
    checksum_sha256 CHAR(64) NOT NULL,
    event_count INTEGER NOT NULL,
    event_types JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_server_at TIMESTAMPTZ,
    last_server_at TIMESTAMPTZ,
    first_received_at TIMESTAMPTZ NOT NULL,
    last_received_at TIMESTAMPTZ NOT NULL,
    finalized_at TIMESTAMPTZ NOT NULL,
    retention_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, batch_index),
    UNIQUE (session_id, relative_path),
    CONSTRAINT chk_live_raw_event_batch_index CHECK (batch_index >= 0),
    CONSTRAINT chk_live_raw_event_batch_path CHECK (
        relative_path <> '' AND relative_path !~ '(^|/)\.\.(/|$)' AND relative_path !~ '^/'
    ),
    CONSTRAINT chk_live_raw_event_batch_status CHECK (
        status IN ('finalized', 'quarantined', 'failed')
    ),
    CONSTRAINT chk_live_raw_event_batch_mode CHECK (file_mode = 384),
    CONSTRAINT chk_live_raw_event_batch_encoding CHECK (content_encoding = 'gzip'),
    CONSTRAINT chk_live_raw_event_batch_size CHECK (file_size >= 0),
    CONSTRAINT chk_live_raw_event_batch_checksum CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_live_raw_event_batch_count CHECK (event_count >= 0),
    CONSTRAINT chk_live_raw_event_batch_times CHECK (
        last_received_at >= first_received_at
        AND (last_server_at IS NULL OR first_server_at IS NULL OR last_server_at >= first_server_at)
    ),
    CONSTRAINT chk_live_raw_event_batch_retention CHECK (retention_expires_at IS NULL),
    CONSTRAINT chk_live_raw_event_batch_json CHECK (jsonb_typeof(event_types) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_live_raw_event_batches_session
    ON live_raw_event_batches(session_id, batch_index);

CREATE TABLE IF NOT EXISTS live_timeline_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES live_capture_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    chunk_id UUID NOT NULL REFERENCES live_capture_chunks(id) ON DELETE CASCADE,
    chunk_code VARCHAR(64) NOT NULL,
    span_index INTEGER NOT NULL,
    contract_version VARCHAR(32) NOT NULL DEFAULT 'media-timeline.v1',
    global_start_seconds NUMERIC(18, 6) NOT NULL,
    global_end_seconds NUMERIC(18, 6) NOT NULL,
    chunk_start_seconds NUMERIC(18, 6) NOT NULL,
    chunk_end_seconds NUMERIC(18, 6) NOT NULL,
    wall_start_at TIMESTAMPTZ,
    wall_end_at TIMESTAMPTZ,
    mapping_slope NUMERIC(18, 9) NOT NULL DEFAULT 1,
    confidence NUMERIC(5, 4) NOT NULL DEFAULT 1,
    discontinuity_before VARCHAR(32) NOT NULL DEFAULT 'none',
    mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, span_index),
    UNIQUE (chunk_id),
    CONSTRAINT chk_live_timeline_span_index CHECK (span_index >= 0),
    CONSTRAINT chk_live_timeline_span_global CHECK (
        global_start_seconds >= 0 AND global_end_seconds > global_start_seconds
    ),
    CONSTRAINT chk_live_timeline_span_chunk CHECK (
        chunk_start_seconds >= 0 AND chunk_end_seconds > chunk_start_seconds
    ),
    CONSTRAINT chk_live_timeline_span_slope CHECK (mapping_slope > 0),
    CONSTRAINT chk_live_timeline_span_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT chk_live_timeline_span_wall CHECK (
        wall_end_at IS NULL OR wall_start_at IS NULL OR wall_end_at >= wall_start_at
    ),
    CONSTRAINT chk_live_timeline_span_discontinuity CHECK (
        discontinuity_before IN ('none', 'reset', 'gap', 'overlap', 'reconnect', 'unknown')
    ),
    CONSTRAINT chk_live_timeline_span_mapping CHECK (jsonb_typeof(mapping) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_live_timeline_spans_session
    ON live_timeline_spans(session_id, global_start_seconds);

CREATE TABLE IF NOT EXISTS live_clip_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clip_job_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES live_capture_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    title VARCHAR(255),
    requested_start_seconds NUMERIC(18, 6) NOT NULL,
    requested_end_seconds NUMERIC(18, 6) NOT NULL,
    cut_mode VARCHAR(32) NOT NULL DEFAULT 'exact_reencode',
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    source_fingerprint CHAR(64),
    actual_start_seconds NUMERIC(18, 6),
    actual_end_seconds NUMERIC(18, 6),
    output_relative_path TEXT,
    output_file_size BIGINT,
    output_checksum_sha256 CHAR(64),
    ffmpeg_version VARCHAR(128),
    ffmpeg_arguments JSONB NOT NULL DEFAULT '[]'::jsonb,
    final_asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_live_clip_job_range CHECK (
        requested_start_seconds >= 0 AND requested_end_seconds > requested_start_seconds
    ),
    CONSTRAINT chk_live_clip_job_actual_range CHECK (
        actual_end_seconds IS NULL OR actual_start_seconds IS NULL OR actual_end_seconds > actual_start_seconds
    ),
    CONSTRAINT chk_live_clip_job_mode CHECK (cut_mode IN ('exact_reencode', 'keyframe_copy')),
    CONSTRAINT chk_live_clip_job_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT chk_live_clip_job_source_fingerprint CHECK (
        source_fingerprint IS NULL OR source_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_live_clip_job_output_checksum CHECK (
        output_checksum_sha256 IS NULL OR output_checksum_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_live_clip_job_output_path CHECK (
        output_relative_path IS NULL
        OR (output_relative_path <> '' AND output_relative_path !~ '(^|/)\.\.(/|$)' AND output_relative_path !~ '^/')
    ),
    CONSTRAINT chk_live_clip_job_arguments CHECK (jsonb_typeof(ffmpeg_arguments) = 'array'),
    CONSTRAINT chk_live_clip_job_lease CHECK (
        (claimed_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
        OR (claimed_by IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    ),
    CONSTRAINT chk_live_clip_job_success CHECK (
        status <> 'succeeded'
        OR (
            completed_at IS NOT NULL AND output_relative_path IS NOT NULL
            AND output_file_size IS NOT NULL AND output_checksum_sha256 IS NOT NULL
            AND actual_start_seconds IS NOT NULL AND actual_end_seconds IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_live_clip_jobs_queue
    ON live_clip_jobs(status, created_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_live_clip_jobs_session
    ON live_clip_jobs(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS live_analysis_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES live_capture_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    chunk_id UUID REFERENCES live_capture_chunks(id) ON DELETE CASCADE,
    chunk_code VARCHAR(64),
    analysis_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    input_fingerprint CHAR(64) NOT NULL,
    model_provider VARCHAR(128) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_relative_path TEXT,
    output_checksum_sha256 CHAR(64),
    error_code VARCHAR(64),
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retry_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_live_analysis_run_type CHECK (
        analysis_type IN ('asr', 'frame_sampling', 'ocr', 'layout_inference', 'template_aggregation')
    ),
    CONSTRAINT chk_live_analysis_run_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT chk_live_analysis_run_fingerprint CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_live_analysis_run_output_checksum CHECK (
        output_checksum_sha256 IS NULL OR output_checksum_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_live_analysis_run_output_path CHECK (
        output_relative_path IS NULL
        OR (output_relative_path <> '' AND output_relative_path !~ '(^|/)\.\.(/|$)' AND output_relative_path !~ '^/')
    ),
    CONSTRAINT chk_live_analysis_run_json CHECK (
        jsonb_typeof(parameters) = 'object' AND jsonb_typeof(output_payload) = 'object'
        AND jsonb_typeof(retry_history) = 'array'
    ),
    CONSTRAINT chk_live_analysis_run_attempts CHECK (
        attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10
        AND attempt_count <= max_attempts
    ),
    CONSTRAINT chk_live_analysis_run_lease CHECK (
        (claimed_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
        OR (claimed_by IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    ),
    CONSTRAINT chk_live_analysis_run_terminal CHECK (
        status NOT IN ('succeeded', 'failed', 'cancelled') OR completed_at IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_live_analysis_runs_queue
    ON live_analysis_runs(status, next_attempt_at, analysis_type, created_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_live_analysis_runs_session
    ON live_analysis_runs(session_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_live_analysis_runs_input_unique
    ON live_analysis_runs(
        session_id,
        coalesce(chunk_id, '00000000-0000-0000-0000-000000000000'::uuid),
        analysis_type,
        input_fingerprint,
        model_provider,
        model_version
    );

CREATE TABLE IF NOT EXISTS live_room_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    source_target_id UUID REFERENCES live_watch_targets(id) ON DELETE SET NULL,
    source_target_code VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    published_revision_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT chk_live_room_template_status CHECK (status IN ('draft', 'published', 'archived'))
);

CREATE TABLE IF NOT EXISTS live_room_template_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL REFERENCES live_room_templates(id) ON DELETE CASCADE,
    template_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    source_session_id UUID REFERENCES live_capture_sessions(id) ON DELETE SET NULL,
    source_session_code VARCHAR(64),
    contract_version VARCHAR(32) NOT NULL DEFAULT 'layout-hypothesis.v1',
    canvas JSONB NOT NULL,
    scenes JSONB NOT NULL DEFAULT '[]'::jsonb,
    components JSONB NOT NULL DEFAULT '[]'::jsonb,
    audio_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5, 4) NOT NULL,
    review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    review_notes TEXT,
    content_fingerprint CHAR(64) NOT NULL,
    created_by VARCHAR(128),
    reviewed_by VARCHAR(128),
    reviewed_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (template_id, revision_number),
    UNIQUE (template_id, content_fingerprint),
    CONSTRAINT chk_live_room_template_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_live_room_template_revision_status CHECK (
        status IN ('draft', 'published', 'superseded', 'rejected')
    ),
    CONSTRAINT chk_live_room_template_revision_review CHECK (
        review_status IN ('pending', 'accepted', 'rejected')
    ),
    CONSTRAINT chk_live_room_template_revision_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT chk_live_room_template_revision_fingerprint CHECK (
        content_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_live_room_template_revision_json CHECK (
        jsonb_typeof(canvas) = 'object'
        AND jsonb_typeof(scenes) = 'array'
        AND jsonb_typeof(components) = 'array'
        AND jsonb_typeof(audio_policy) = 'object'
        AND jsonb_typeof(provenance) = 'object'
    ),
    CONSTRAINT chk_live_room_template_revision_publish CHECK (
        status <> 'published'
        OR (review_status = 'accepted' AND reviewed_at IS NOT NULL AND published_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_live_room_template_revision_published
    ON live_room_template_revisions(template_id)
    WHERE status = 'published';

ALTER TABLE live_room_templates
    DROP CONSTRAINT IF EXISTS fk_live_room_templates_published_revision;
ALTER TABLE live_room_templates
    ADD CONSTRAINT fk_live_room_templates_published_revision
    FOREIGN KEY (published_revision_id) REFERENCES live_room_template_revisions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS live_room_template_publications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_code VARCHAR(64) NOT NULL UNIQUE,
    template_id UUID NOT NULL REFERENCES live_room_templates(id) ON DELETE CASCADE,
    template_code VARCHAR(64) NOT NULL,
    revision_id UUID NOT NULL REFERENCES live_room_template_revisions(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    projection_contract VARCHAR(64) NOT NULL DEFAULT 'maitu-layout-projection.v1',
    projection_payload JSONB NOT NULL,
    projection_fingerprint CHAR(64) NOT NULL,
    projection_ready BOOLEAN NOT NULL DEFAULT false,
    manual_review_required BOOLEAN NOT NULL DEFAULT true,
    published_by VARCHAR(128) NOT NULL,
    publication_reason TEXT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retracted_at TIMESTAMPTZ,
    UNIQUE (template_id, revision_id),
    CONSTRAINT chk_live_room_template_publication_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_live_room_template_publication_fingerprint CHECK (
        projection_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_live_room_template_publication_payload CHECK (
        jsonb_typeof(projection_payload) = 'object'
    ),
    CONSTRAINT chk_live_room_template_publication_readiness CHECK (
        projection_ready = false OR manual_review_required = false
    )
);

CREATE INDEX IF NOT EXISTS idx_live_room_template_publications_template
    ON live_room_template_publications(template_id, published_at DESC);

CREATE TABLE IF NOT EXISTS live_retention_tombstones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(32) NOT NULL,
    entity_id UUID NOT NULL,
    entity_code VARCHAR(64) NOT NULL,
    relative_path TEXT NOT NULL,
    checksum_sha256 CHAR(64),
    deletion_reason VARCHAR(128) NOT NULL,
    deletion_attempt_id UUID NOT NULL,
    marked_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_id),
    UNIQUE (deletion_attempt_id),
    CONSTRAINT chk_live_retention_tombstone_type CHECK (
        entity_type = 'capture_chunk'
    ),
    CONSTRAINT chk_live_retention_tombstone_path CHECK (
        relative_path <> '' AND relative_path !~ '(^|/)\.\.(/|$)' AND relative_path !~ '^/'
    ),
    CONSTRAINT chk_live_retention_tombstone_checksum CHECK (
        checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_live_retention_tombstone_times CHECK (deleted_at >= marked_at),
    CONSTRAINT chk_live_retention_tombstone_details CHECK (jsonb_typeof(details) = 'object')
);

CREATE OR REPLACE VIEW live_research_projection_ready AS
SELECT
    template.template_code,
    template.name,
    revision.revision_number,
    publication.publication_code,
    publication.projection_contract,
    publication.projection_payload,
    publication.projection_fingerprint,
    publication.projection_ready,
    publication.manual_review_required,
    publication.published_at
FROM live_room_templates AS template
JOIN live_room_template_revisions AS revision
  ON revision.id = template.published_revision_id
JOIN live_room_template_publications AS publication
  ON publication.revision_id = revision.id
WHERE template.status = 'published'
  AND revision.status = 'published'
  AND publication.retracted_at IS NULL;

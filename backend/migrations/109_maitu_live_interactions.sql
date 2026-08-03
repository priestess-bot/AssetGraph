-- Durable Maitu live-session interactions, synchronization, and model analysis.

CREATE TABLE IF NOT EXISTS maitu_interaction_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code VARCHAR(64) NOT NULL UNIQUE,
    source_system VARCHAR(32) NOT NULL DEFAULT 'maitu',
    external_account_id BIGINT,
    account_name VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'unbound',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    daily_sync_time TIME NOT NULL DEFAULT TIME '02:00:00',
    rescan_days INTEGER NOT NULL DEFAULT 7,
    last_full_sync_at TIMESTAMPTZ,
    last_incremental_sync_at TIMESTAMPTZ,
    next_sync_at TIMESTAMPTZ,
    retry_after TIMESTAMPTZ,
    last_error_code VARCHAR(64),
    last_error_message VARCHAR(4000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_interaction_source_status CHECK (
        status IN ('unbound', 'active', 'waiting_login', 'account_mismatch', 'error')
    ),
    CONSTRAINT chk_maitu_interaction_source_rescan_days CHECK (rescan_days BETWEEN 0 AND 365)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_interaction_source_account
    ON maitu_interaction_sources(source_system, external_account_id)
    WHERE external_account_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS maitu_interaction_platforms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES maitu_interaction_sources(id) ON DELETE RESTRICT,
    external_platform_id INTEGER NOT NULL,
    platform_code VARCHAR(64) NOT NULL,
    platform_name VARCHAR(128) NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, external_platform_id)
);

CREATE TABLE IF NOT EXISTS maitu_live_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES maitu_interaction_sources(id) ON DELETE RESTRICT,
    platform_id UUID NOT NULL REFERENCES maitu_interaction_platforms(id) ON DELETE RESTRICT,
    external_session_id BIGINT NOT NULL,
    external_live_room_id BIGINT NOT NULL,
    platform_live_id VARCHAR(255),
    title VARCHAR(512) NOT NULL,
    live_room_type VARCHAR(64),
    source_status INTEGER NOT NULL DEFAULT 2,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    duration_seconds BIGINT NOT NULL DEFAULT 0,
    source_created_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_fingerprint CHAR(64) NOT NULL,
    source_interaction_count INTEGER,
    stored_interaction_count INTEGER NOT NULL DEFAULT 0,
    is_sync_complete BOOLEAN NOT NULL DEFAULT FALSE,
    last_interaction_sync_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, external_session_id),
    CONSTRAINT chk_maitu_live_session_time CHECK (ended_at >= started_at),
    CONSTRAINT chk_maitu_live_session_duration CHECK (duration_seconds >= 0),
    CONSTRAINT chk_maitu_live_session_source_payload CHECK (jsonb_typeof(source_payload) = 'object'),
    CONSTRAINT chk_maitu_live_session_fingerprint CHECK (source_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_maitu_live_sessions_platform_started
    ON maitu_live_sessions(platform_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_maitu_live_sessions_source_ended
    ON maitu_live_sessions(source_id, ended_at DESC);

CREATE TABLE IF NOT EXISTS maitu_interaction_sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_code VARCHAR(80) NOT NULL UNIQUE,
    source_id UUID NOT NULL REFERENCES maitu_interaction_sources(id) ON DELETE RESTRICT,
    sync_mode VARCHAR(24) NOT NULL,
    target_external_session_id BIGINT,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    idempotency_key VARCHAR(160) UNIQUE,
    requested_by VARCHAR(128),
    scheduled_for TIMESTAMPTZ,
    retry_after TIMESTAMPTZ,
    attempt INTEGER NOT NULL DEFAULT 0,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(64),
    error_message VARCHAR(4000),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_interaction_sync_mode CHECK (sync_mode IN ('full', 'incremental', 'session')),
    CONSTRAINT chk_maitu_interaction_sync_status CHECK (
        status IN ('queued', 'running', 'waiting_login', 'succeeded', 'partial', 'failed')
    ),
    CONSTRAINT chk_maitu_interaction_sync_summary CHECK (jsonb_typeof(result_summary) = 'object'),
    CONSTRAINT chk_maitu_interaction_sync_target CHECK (
        (sync_mode = 'session' AND target_external_session_id IS NOT NULL)
        OR (sync_mode <> 'session' AND target_external_session_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_maitu_interaction_sync_claim
    ON maitu_interaction_sync_jobs(status, retry_after, created_at);

CREATE TABLE IF NOT EXISTS maitu_live_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES maitu_interaction_sources(id) ON DELETE RESTRICT,
    session_id UUID NOT NULL REFERENCES maitu_live_sessions(id) ON DELETE RESTRICT,
    external_interaction_id VARCHAR(128) NOT NULL,
    live_room_id BIGINT NOT NULL,
    platform INTEGER,
    platform_live_id VARCHAR(255),
    request_id VARCHAR(255),
    interaction_type INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL DEFAULT '',
    normalized_content TEXT NOT NULL DEFAULT '',
    is_arrival BOOLEAN NOT NULL DEFAULT FALSE,
    publisher_name VARCHAR(512),
    publisher_role VARCHAR(64),
    item_id VARCHAR(255),
    published_at TIMESTAMPTZ,
    digital_reply_type INTEGER,
    digital_reply_status INTEGER,
    digital_reply_content TEXT,
    digital_replied_at TIMESTAMPTZ,
    bullet_reply_type INTEGER,
    bullet_reply_status INTEGER,
    bullet_reply_content TEXT,
    bullet_replied_at TIMESTAMPTZ,
    reply_decision_code INTEGER,
    bullet_reply_decision_code INTEGER,
    source_created_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_fingerprint CHAR(64) NOT NULL,
    analysis_input_fingerprint CHAR(64) NOT NULL,
    last_seen_run_code VARCHAR(80),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, session_id, external_interaction_id),
    CONSTRAINT chk_maitu_live_interaction_payload CHECK (jsonb_typeof(source_payload) = 'object'),
    CONSTRAINT chk_maitu_live_interaction_source_fingerprint CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_live_interaction_analysis_fingerprint CHECK (
        analysis_input_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_maitu_live_interactions_session_published
    ON maitu_live_interactions(session_id, published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_maitu_live_interactions_analysis_population
    ON maitu_live_interactions(source_id, is_arrival, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_maitu_live_interactions_unanswered
    ON maitu_live_interactions(source_id, published_at DESC)
    WHERE NOT is_arrival AND NULLIF(btrim(COALESCE(digital_reply_content, '')), '') IS NULL;

CREATE TABLE IF NOT EXISTS maitu_interaction_analysis_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_code VARCHAR(80) NOT NULL UNIQUE,
    interaction_id UUID NOT NULL REFERENCES maitu_live_interactions(id) ON DELETE RESTRICT,
    analyzer_version VARCHAR(128) NOT NULL,
    strategy_revision VARCHAR(128) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    retry_after TIMESTAMPTZ,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    result_id UUID,
    error_code VARCHAR(64),
    error_message VARCHAR(4000),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (interaction_id, analyzer_version, input_fingerprint),
    CONSTRAINT chk_maitu_interaction_analysis_job_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed')
    ),
    CONSTRAINT chk_maitu_interaction_analysis_job_fingerprint CHECK (
        input_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_maitu_interaction_analysis_claim
    ON maitu_interaction_analysis_jobs(status, retry_after, created_at);

CREATE TABLE IF NOT EXISTS maitu_interaction_analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_code VARCHAR(80) NOT NULL,
    interaction_id UUID NOT NULL REFERENCES maitu_live_interactions(id) ON DELETE RESTRICT,
    analyzer_version VARCHAR(128) NOT NULL,
    strategy_revision VARCHAR(128) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    output_fingerprint CHAR(64) NOT NULL,
    invocation_evidence_ref VARCHAR(512) NOT NULL,
    interaction_form VARCHAR(32) NOT NULL,
    business_intent VARCHAR(64) NOT NULL,
    relevance_grade VARCHAR(16) NOT NULL,
    completeness_grade VARCHAR(16) NOT NULL,
    resolution_grade VARCHAR(16) NOT NULL,
    overall_grade VARCHAR(16) NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (interaction_id, analyzer_version, input_fingerprint),
    CONSTRAINT chk_maitu_interaction_analysis_output_fingerprint CHECK (
        output_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_maitu_interaction_form CHECK (
        interaction_form IN ('question', 'request', 'greeting', 'feedback', 'purchase_signal', 'noise', 'other')
    ),
    CONSTRAINT chk_maitu_interaction_intent CHECK (
        business_intent IN (
            'product_attributes', 'product_lookup', 'recommendation', 'price_promotion_gift',
            'inventory_shipping', 'order_purchase', 'after_sales_invoice', 'live_room_operation',
            'social_feedback', 'off_topic_noise', 'other'
        )
    ),
    CONSTRAINT chk_maitu_interaction_analysis_grades CHECK (
        relevance_grade IN ('good', 'fair', 'poor')
        AND completeness_grade IN ('good', 'fair', 'poor')
        AND resolution_grade IN ('good', 'fair', 'poor')
        AND overall_grade IN ('good', 'fair', 'poor')
    ),
    CONSTRAINT chk_maitu_interaction_analysis_confidence CHECK (confidence BETWEEN 0 AND 1)
);

ALTER TABLE maitu_interaction_analysis_jobs
    DROP CONSTRAINT IF EXISTS fk_maitu_interaction_analysis_result;
ALTER TABLE maitu_interaction_analysis_jobs
    ADD CONSTRAINT fk_maitu_interaction_analysis_result
    FOREIGN KEY (result_id) REFERENCES maitu_interaction_analysis_results(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_maitu_interaction_analysis_latest
    ON maitu_interaction_analysis_results(interaction_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_maitu_interaction_analysis_dimensions
    ON maitu_interaction_analysis_results(analyzer_version, business_intent, interaction_form, overall_grade);

INSERT INTO maitu_interaction_sources (source_code, source_system, next_sync_at)
VALUES ('maitu-primary', 'maitu', now())
ON CONFLICT (source_code) DO NOTHING;

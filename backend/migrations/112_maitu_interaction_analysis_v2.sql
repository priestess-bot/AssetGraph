-- Versioned interaction intent, answer-quality, and semantic-topic analysis.

ALTER TABLE maitu_interaction_analysis_jobs
    DROP CONSTRAINT IF EXISTS chk_maitu_interaction_analysis_job_status;
ALTER TABLE maitu_interaction_analysis_jobs
    ADD CONSTRAINT chk_maitu_interaction_analysis_job_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')
    );

UPDATE maitu_interaction_analysis_jobs
SET status = 'superseded',
    claimed_by = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    heartbeat_at = NULL,
    retry_after = NULL,
    error_code = 'ANALYZER_VERSION_SUPERSEDED',
    error_message = 'The interaction analyzer taxonomy was replaced by v2',
    completed_at = COALESCE(completed_at, now()),
    updated_at = now()
WHERE status IN ('queued', 'running', 'failed');

ALTER TABLE maitu_interaction_analysis_results
    ADD COLUMN IF NOT EXISTS classification_reason VARCHAR(1000) NOT NULL DEFAULT '历史分析结果',
    ADD COLUMN IF NOT EXISTS topic_summary VARCHAR(255) NOT NULL DEFAULT '未归类主题',
    ADD COLUMN IF NOT EXISTS quality_applicable BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE maitu_interaction_analysis_results
    ALTER COLUMN relevance_grade DROP NOT NULL,
    ALTER COLUMN completeness_grade DROP NOT NULL,
    ALTER COLUMN resolution_grade DROP NOT NULL,
    ALTER COLUMN overall_grade DROP NOT NULL,
    ALTER COLUMN reason DROP NOT NULL;

ALTER TABLE maitu_interaction_analysis_results
    DROP CONSTRAINT IF EXISTS chk_maitu_interaction_intent,
    DROP CONSTRAINT IF EXISTS chk_maitu_interaction_analysis_grades;

ALTER TABLE maitu_interaction_analysis_results
    ADD CONSTRAINT chk_maitu_interaction_intent CHECK (
        business_intent IN (
            'product_attributes', 'product_lookup', 'recommendation', 'price_promotion_gift',
            'inventory_shipping', 'order_purchase', 'after_sales_invoice', 'live_room_operation',
            'social_feedback', 'off_topic_noise', 'other',
            'product_consultation', 'promotion', 'non_inquiry', 'order_fulfillment',
            'after_sales', 'account_membership', 'purchase_conversion',
            'review_complaint', 'small_talk'
        )
    ),
    ADD CONSTRAINT chk_maitu_interaction_analysis_grades CHECK (
        (
            quality_applicable
            AND relevance_grade IN ('good', 'fair', 'poor')
            AND completeness_grade IN ('good', 'fair', 'poor')
            AND resolution_grade IN ('good', 'fair', 'poor')
            AND overall_grade IN ('good', 'fair', 'poor')
            AND reason IS NOT NULL
        )
        OR (
            NOT quality_applicable
            AND relevance_grade IS NULL
            AND completeness_grade IS NULL
            AND resolution_grade IS NULL
            AND overall_grade IS NULL
            AND reason IS NULL
        )
    );

CREATE TABLE IF NOT EXISTS maitu_interaction_topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_code VARCHAR(80) NOT NULL UNIQUE,
    analyzer_version VARCHAR(128) NOT NULL,
    business_intent VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    normalized_title VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (analyzer_version, business_intent, normalized_title),
    CONSTRAINT chk_maitu_interaction_topic_intent CHECK (
        business_intent IN (
            'product_consultation', 'promotion', 'non_inquiry', 'order_fulfillment',
            'after_sales', 'account_membership', 'purchase_conversion',
            'review_complaint', 'small_talk'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_maitu_interaction_topics_catalog
    ON maitu_interaction_topics(analyzer_version, business_intent, created_at);

CREATE TABLE IF NOT EXISTS maitu_interaction_topic_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_job_code VARCHAR(80) NOT NULL UNIQUE,
    analysis_result_id UUID NOT NULL REFERENCES maitu_interaction_analysis_results(id) ON DELETE RESTRICT,
    analyzer_version VARCHAR(128) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    retry_after TIMESTAMPTZ,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message VARCHAR(4000),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (analysis_result_id),
    CONSTRAINT chk_maitu_interaction_topic_job_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'superseded')
    )
);

CREATE INDEX IF NOT EXISTS idx_maitu_interaction_topic_job_claim
    ON maitu_interaction_topic_jobs(analyzer_version, status, retry_after, created_at);

CREATE TABLE IF NOT EXISTS maitu_interaction_topic_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interaction_id UUID NOT NULL REFERENCES maitu_live_interactions(id) ON DELETE RESTRICT,
    analysis_result_id UUID NOT NULL REFERENCES maitu_interaction_analysis_results(id) ON DELETE RESTRICT,
    topic_id UUID NOT NULL REFERENCES maitu_interaction_topics(id) ON DELETE RESTRICT,
    analyzer_version VARCHAR(128) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    assignment_fingerprint CHAR(64) NOT NULL,
    invocation_evidence_ref VARCHAR(512) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (interaction_id, analyzer_version, input_fingerprint),
    UNIQUE (analysis_result_id),
    CONSTRAINT chk_maitu_interaction_topic_assignment_input CHECK (
        input_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_maitu_interaction_topic_assignment_output CHECK (
        assignment_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_maitu_interaction_topic_assignments_topic
    ON maitu_interaction_topic_assignments(topic_id, created_at DESC);

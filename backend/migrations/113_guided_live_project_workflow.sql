-- Guided live-project authoring: versioned material pools, durable generation
-- jobs, script material requirements, and explicit storyboard review.

CREATE TABLE IF NOT EXISTS content_project_material_pool_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pool_revision_code VARCHAR(80) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    project_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    selected_asset_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, revision_number),
    CONSTRAINT chk_content_material_pool_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_content_material_pool_assets CHECK (jsonb_typeof(selected_asset_codes) = 'array'),
    CONSTRAINT chk_content_material_pool_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_content_material_pool_project
    ON content_project_material_pool_revisions(project_id, revision_number DESC);

INSERT INTO content_project_material_pool_revisions (
    pool_revision_code, project_id, project_code, revision_number,
    selected_asset_codes, fingerprint_sha256, created_by
)
SELECT
    'POOL-' || upper(substr(md5(project.id::text), 1, 12)) || '-R1',
    project.id,
    project.project_code,
    1,
    CASE
        WHEN jsonb_typeof(revision.content -> 'selected_asset_codes') = 'array'
            THEN revision.content -> 'selected_asset_codes'
        ELSE '[]'::jsonb
    END,
    encode(
        digest(
            convert_to(
                jsonb_build_object(
                    'project_code', project.project_code,
                    'revision_number', 1,
                    'selected_asset_codes', CASE
                        WHEN jsonb_typeof(revision.content -> 'selected_asset_codes') = 'array'
                            THEN revision.content -> 'selected_asset_codes'
                        ELSE '[]'::jsonb
                    END
                )::text,
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    ),
    COALESCE(project.owner_principal, 'migration-113')
FROM content_projects AS project
JOIN content_project_revisions AS revision
  ON revision.project_id = project.id
 AND revision.revision_number = project.current_revision_number
WHERE NOT EXISTS (
    SELECT 1 FROM content_project_material_pool_revisions AS pool
    WHERE pool.project_id = project.id
);

CREATE TABLE IF NOT EXISTS content_generation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_code VARCHAR(80) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    project_code VARCHAR(64) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    idempotency_key VARCHAR(128),
    source_project_revision INTEGER NOT NULL,
    source_material_pool_revision INTEGER NOT NULL,
    source_outline_revision INTEGER,
    source_script_revision INTEGER,
    template_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_fingerprint CHAR(64) NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 1,
    completed_items INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    result_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(128),
    error_message TEXT,
    requested_by VARCHAR(128) NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_content_generation_job_stage CHECK (stage IN ('outline', 'script', 'storyboard')),
    CONSTRAINT chk_content_generation_job_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'stale', 'cancelled')
    ),
    CONSTRAINT chk_content_generation_job_revisions CHECK (
        source_project_revision >= 1
        AND source_material_pool_revision >= 1
        AND (source_outline_revision IS NULL OR source_outline_revision >= 1)
        AND (source_script_revision IS NULL OR source_script_revision >= 1)
    ),
    CONSTRAINT chk_content_generation_job_payloads CHECK (
        jsonb_typeof(template_ref) = 'object'
        AND jsonb_typeof(input_snapshot) = 'object'
        AND jsonb_typeof(result_refs) = 'object'
    ),
    CONSTRAINT chk_content_generation_job_progress CHECK (
        total_items >= 1 AND completed_items >= 0 AND completed_items <= total_items
        AND attempts >= 0 AND max_attempts BETWEEN 1 AND 10
    ),
    CONSTRAINT chk_content_generation_job_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_generation_job_idempotency
    ON content_generation_jobs(project_id, stage, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_generation_job_active
    ON content_generation_jobs(project_id, stage)
    WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_content_generation_job_claim
    ON content_generation_jobs(status, lease_expires_at, created_at);

CREATE TABLE IF NOT EXISTS content_generation_job_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES content_generation_jobs(id) ON DELETE CASCADE,
    item_key VARCHAR(128) NOT NULL,
    sort_order INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    invocation_evidence_ref VARCHAR(80),
    error_code VARCHAR(128),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, item_key),
    UNIQUE (job_id, sort_order),
    CONSTRAINT chk_content_generation_item_order CHECK (sort_order >= 0 AND attempts >= 0),
    CONSTRAINT chk_content_generation_item_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'stale', 'cancelled')
    ),
    CONSTRAINT chk_content_generation_item_payloads CHECK (
        jsonb_typeof(input_payload) = 'object' AND jsonb_typeof(output_payload) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS idx_content_generation_item_job
    ON content_generation_job_items(job_id, sort_order);

CREATE TABLE IF NOT EXISTS content_script_material_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requirement_code VARCHAR(80) NOT NULL UNIQUE,
    script_revision_id UUID NOT NULL REFERENCES content_script_revisions(id) ON DELETE CASCADE,
    script_block_id UUID NOT NULL REFERENCES content_script_blocks(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    material_role VARCHAR(64) NOT NULL,
    description TEXT NOT NULL,
    priority VARCHAR(16) NOT NULL,
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    matched_asset_code VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    match_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    waived_by VARCHAR(128),
    waived_at TIMESTAMPTZ,
    waiver_reason VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (script_revision_id, script_block_id, sort_order),
    CONSTRAINT chk_content_script_material_order CHECK (sort_order >= 0),
    CONSTRAINT chk_content_script_material_priority CHECK (priority IN ('required', 'optional')),
    CONSTRAINT chk_content_script_material_status CHECK (status IN ('matched', 'missing', 'waived')),
    CONSTRAINT chk_content_script_material_payloads CHECK (
        jsonb_typeof(keywords) = 'array' AND jsonb_typeof(match_evidence) = 'object'
    ),
    CONSTRAINT chk_content_script_material_match CHECK (
        (status = 'matched' AND matched_asset_code IS NOT NULL AND waived_by IS NULL AND waived_at IS NULL)
        OR (status = 'missing' AND matched_asset_code IS NULL AND waived_by IS NULL AND waived_at IS NULL)
        OR (status = 'waived' AND matched_asset_code IS NULL AND waived_by IS NOT NULL AND waived_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_content_script_material_revision
    ON content_script_material_requirements(script_revision_id, script_block_id, sort_order);

ALTER TABLE functional_live_room_plans
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'confirmed',
    ADD COLUMN IF NOT EXISTS confirmed_by VARCHAR(128) DEFAULT 'functional-live-room-service',
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ DEFAULT now(),
    ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ;

UPDATE functional_live_room_plans
SET confirmed_by = COALESCE(confirmed_by, 'legacy-migration-113'),
    confirmed_at = COALESCE(confirmed_at, created_at)
WHERE review_status = 'confirmed';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_functional_live_room_review_status'
          AND conrelid = 'functional_live_room_plans'::regclass
    ) THEN
        ALTER TABLE functional_live_room_plans
            ADD CONSTRAINT chk_functional_live_room_review_status
                CHECK (review_status IN ('draft', 'confirmed', 'superseded'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_functional_live_room_review_confirmation'
          AND conrelid = 'functional_live_room_plans'::regclass
    ) THEN
        ALTER TABLE functional_live_room_plans
            ADD CONSTRAINT chk_functional_live_room_review_confirmation
                CHECK (
                    (review_status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
                    OR review_status <> 'confirmed'
                );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_functional_live_room_review_project
    ON functional_live_room_plans(project_code, review_status, created_at DESC);

-- Versioned, auditable production-workbench state for Maitu draft planning.

CREATE TABLE IF NOT EXISTS maitu_workbench_product_fact_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_card_code VARCHAR(64) NOT NULL UNIQUE,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    product_code VARCHAR(64),
    title VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    current_approved_version INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT chk_maitu_workbench_fact_card_status
        CHECK (status IN ('active', 'archived')),
    CONSTRAINT chk_maitu_workbench_fact_card_current_version
        CHECK (current_approved_version IS NULL OR current_approved_version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_fact_cards_product_code
ON maitu_workbench_product_fact_cards(product_code);

CREATE TABLE IF NOT EXISTS maitu_workbench_product_fact_card_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_card_id UUID NOT NULL REFERENCES maitu_workbench_product_fact_cards(id) ON DELETE CASCADE,
    fact_card_code VARCHAR(64) NOT NULL,
    version_code VARCHAR(80) NOT NULL UNIQUE,
    version_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    content JSONB NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    change_reason TEXT,
    created_by VARCHAR(128),
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    rejected_by VARCHAR(128),
    rejected_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fact_card_id, version_number),
    CONSTRAINT chk_maitu_workbench_fact_version_number CHECK (version_number >= 1),
    CONSTRAINT chk_maitu_workbench_fact_version_status
        CHECK (status IN ('draft', 'approved', 'rejected', 'superseded')),
    CONSTRAINT chk_maitu_workbench_fact_version_content CHECK (jsonb_typeof(content) = 'object'),
    CONSTRAINT chk_maitu_workbench_fact_version_sha
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_fact_version_approval
        CHECK (
            (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
            OR status <> 'approved'
        ),
    CONSTRAINT chk_maitu_workbench_fact_version_rejection
        CHECK (
            (status = 'rejected' AND rejected_by IS NOT NULL AND rejected_at IS NOT NULL
                AND rejection_reason IS NOT NULL)
            OR status <> 'rejected'
        )
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_fact_versions_card
ON maitu_workbench_product_fact_card_versions(fact_card_id, version_number DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_workbench_fact_versions_one_approved
ON maitu_workbench_product_fact_card_versions(fact_card_id)
WHERE status = 'approved';

CREATE TABLE IF NOT EXISTS maitu_workbench_inventory_sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_job_code VARCHAR(64) NOT NULL UNIQUE,
    source_system VARCHAR(64) NOT NULL DEFAULT 'maitu',
    project_code VARCHAR(64),
    sync_mode VARCHAR(32) NOT NULL DEFAULT 'full',
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 1,
    request_fingerprint CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_by VARCHAR(128),
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    source_revision VARCHAR(255),
    snapshot_id UUID,
    snapshot_code VARCHAR(64),
    result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(64),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_workbench_inventory_sync_mode
        CHECK (sync_mode IN ('full', 'incremental')),
    CONSTRAINT chk_maitu_workbench_inventory_sync_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT chk_maitu_workbench_inventory_sync_attempt CHECK (attempt >= 1),
    CONSTRAINT chk_maitu_workbench_inventory_sync_request_sha
        CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_inventory_sync_config CHECK (jsonb_typeof(config) = 'object'),
    CONSTRAINT chk_maitu_workbench_inventory_sync_summary CHECK (jsonb_typeof(result_summary) = 'object'),
    CONSTRAINT chk_maitu_workbench_inventory_sync_lease
        CHECK (
            (claimed_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
            OR (claimed_by IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        ),
    CONSTRAINT chk_maitu_workbench_inventory_sync_terminal
        CHECK (
            (status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL)
            OR status NOT IN ('succeeded', 'failed', 'cancelled')
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_workbench_inventory_sync_idempotency
ON maitu_workbench_inventory_sync_jobs(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_inventory_sync_queue
ON maitu_workbench_inventory_sync_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS maitu_workbench_inventory_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_code VARCHAR(64) NOT NULL UNIQUE,
    sync_job_id UUID NOT NULL UNIQUE REFERENCES maitu_workbench_inventory_sync_jobs(id),
    source_system VARCHAR(64) NOT NULL,
    project_code VARCHAR(64),
    source_revision VARCHAR(255),
    schema_version VARCHAR(64) NOT NULL DEFAULT 'maitu-inventory-snapshot-v1',
    quality_status VARCHAR(32) NOT NULL DEFAULT 'complete',
    fingerprint_sha256 CHAR(64) NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_workbench_inventory_snapshot_quality
        CHECK (quality_status IN ('complete', 'partial')),
    CONSTRAINT chk_maitu_workbench_inventory_snapshot_sha
        CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_inventory_snapshot_count CHECK (item_count >= 0),
    CONSTRAINT chk_maitu_workbench_inventory_snapshot_summary CHECK (jsonb_typeof(summary) = 'object')
);

ALTER TABLE maitu_workbench_inventory_sync_jobs
    DROP CONSTRAINT IF EXISTS fk_maitu_workbench_inventory_sync_snapshot;

ALTER TABLE maitu_workbench_inventory_sync_jobs
    ADD CONSTRAINT fk_maitu_workbench_inventory_sync_snapshot
    FOREIGN KEY (snapshot_id) REFERENCES maitu_workbench_inventory_snapshots(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_inventory_snapshots_scope
ON maitu_workbench_inventory_snapshots(source_system, project_code, captured_at DESC);

CREATE TABLE IF NOT EXISTS maitu_workbench_inventory_snapshot_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES maitu_workbench_inventory_snapshots(id) ON DELETE CASCADE,
    snapshot_code VARCHAR(64) NOT NULL,
    item_key VARCHAR(255) NOT NULL,
    material_id VARCHAR(128),
    asset_code VARCHAR(64),
    title VARCHAR(512),
    material_type VARCHAR(64),
    category VARCHAR(64),
    subtype VARCHAR(64),
    availability_status VARCHAR(32) NOT NULL DEFAULT 'available',
    checksum_sha256 CHAR(64),
    source_material_url TEXT,
    source_cover_url TEXT,
    speaker_id BIGINT,
    digital_human_image_id BIGINT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_id, item_key),
    CONSTRAINT chk_maitu_workbench_inventory_item_availability
        CHECK (availability_status IN ('available', 'unavailable', 'deleted', 'unknown')),
    CONSTRAINT chk_maitu_workbench_inventory_item_sha
        CHECK (checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_inventory_item_metadata CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_inventory_items_material
ON maitu_workbench_inventory_snapshot_items(snapshot_id, material_id);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_inventory_items_asset
ON maitu_workbench_inventory_snapshot_items(snapshot_id, asset_code);

CREATE TABLE IF NOT EXISTS maitu_workbench_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    topic TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    fact_card_version_id UUID NOT NULL REFERENCES maitu_workbench_product_fact_card_versions(id),
    fact_card_version_code VARCHAR(80) NOT NULL,
    inventory_snapshot_id UUID NOT NULL REFERENCES maitu_workbench_inventory_snapshots(id),
    inventory_snapshot_code VARCHAR(64) NOT NULL,
    target_live_room_id VARCHAR(64),
    target_duration_minutes INTEGER NOT NULL DEFAULT 1,
    build_mode VARCHAR(64) NOT NULL DEFAULT 'strict',
    include_default_host BOOLEAN NOT NULL DEFAULT true,
    max_candidates_per_need INTEGER NOT NULL DEFAULT 1,
    canvas_width INTEGER NOT NULL DEFAULT 1080,
    canvas_height INTEGER NOT NULL DEFAULT 1920,
    active_plan_revision INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    error_message TEXT,
    created_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT chk_maitu_workbench_run_status
        CHECK (status IN (
            'draft', 'planning', 'ready', 'blocked', 'replan_required',
            'preflight_passed', 'execution_queued', 'executing', 'completed', 'failed'
        )),
    CONSTRAINT chk_maitu_workbench_run_duration CHECK (target_duration_minutes BETWEEN 1 AND 480),
    CONSTRAINT chk_maitu_workbench_run_candidates CHECK (max_candidates_per_need BETWEEN 1 AND 20),
    CONSTRAINT chk_maitu_workbench_run_canvas CHECK (canvas_width > 0 AND canvas_height > 0),
    CONSTRAINT chk_maitu_workbench_run_revision CHECK (active_plan_revision >= 0)
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_runs_status
ON maitu_workbench_runs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS maitu_workbench_plan_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_revision_code VARCHAR(80) NOT NULL UNIQUE,
    run_id UUID NOT NULL REFERENCES maitu_workbench_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    trigger_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    fact_card_version_id UUID NOT NULL REFERENCES maitu_workbench_product_fact_card_versions(id),
    fact_card_version_code VARCHAR(80) NOT NULL,
    inventory_snapshot_id UUID NOT NULL REFERENCES maitu_workbench_inventory_snapshots(id),
    inventory_snapshot_code VARCHAR(64) NOT NULL,
    source_build_plan_code VARCHAR(64),
    input_fingerprint CHAR(64) NOT NULL,
    generation_provider VARCHAR(64) NOT NULL,
    generation_requested_model VARCHAR(128) NOT NULL,
    generation_actual_model VARCHAR(128) NOT NULL,
    generation_prompt_version VARCHAR(64) NOT NULL,
    generation_request_id VARCHAR(255),
    generation_input_fingerprint CHAR(64) NOT NULL,
    generation_output_fingerprint CHAR(64) NOT NULL,
    generation_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    generation_latency_ms INTEGER NOT NULL,
    pipeline_source VARCHAR(64) NOT NULL,
    pipeline_output JSONB NOT NULL,
    gap_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT,
    created_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    UNIQUE (run_id, revision_number),
    CONSTRAINT chk_maitu_workbench_plan_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_maitu_workbench_plan_trigger
        CHECK (trigger_type IN ('initial', 'replan')),
    CONSTRAINT chk_maitu_workbench_plan_status
        CHECK (status IN ('ready', 'blocked', 'failed', 'superseded')),
    CONSTRAINT chk_maitu_workbench_plan_input_sha
        CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_plan_generation_input_sha
        CHECK (generation_input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_plan_generation_output_sha
        CHECK (generation_output_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_plan_generation_usage
        CHECK (jsonb_typeof(generation_usage) = 'object'),
    CONSTRAINT chk_maitu_workbench_plan_generation_latency
        CHECK (generation_latency_ms >= 0),
    CONSTRAINT chk_maitu_workbench_plan_pipeline_output CHECK (jsonb_typeof(pipeline_output) = 'object'),
    CONSTRAINT chk_maitu_workbench_plan_gap_report CHECK (jsonb_typeof(gap_report) = 'object'),
    CONSTRAINT chk_maitu_workbench_plan_blocked_reasons CHECK (jsonb_typeof(blocked_reasons) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_plan_revisions_run
ON maitu_workbench_plan_revisions(run_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS maitu_workbench_material_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requirement_code VARCHAR(80) NOT NULL UNIQUE,
    requirement_key CHAR(64) NOT NULL,
    run_id UUID NOT NULL REFERENCES maitu_workbench_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(64) NOT NULL,
    plan_revision_id UUID NOT NULL REFERENCES maitu_workbench_plan_revisions(id) ON DELETE CASCADE,
    plan_revision_number INTEGER NOT NULL,
    scene_index INTEGER NOT NULL,
    scene_name VARCHAR(128) NOT NULL,
    need_index INTEGER NOT NULL,
    need_type VARCHAR(64) NOT NULL,
    required_category VARCHAR(64) NOT NULL,
    accepted_asset_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT NOT NULL,
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    priority VARCHAR(32) NOT NULL,
    is_required BOOLEAN NOT NULL DEFAULT false,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    current_decision_revision INTEGER NOT NULL DEFAULT 0,
    pipeline_selection JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_revision_id, requirement_key),
    CONSTRAINT chk_maitu_workbench_material_requirement_scene CHECK (scene_index >= 0 AND need_index >= 0),
    CONSTRAINT chk_maitu_workbench_material_requirement_priority
        CHECK (priority IN ('low', 'medium', 'high')),
    CONSTRAINT chk_maitu_workbench_material_requirement_status
        CHECK (status IN ('pending', 'selected', 'deferred', 'waived', 'missing')),
    CONSTRAINT chk_maitu_workbench_material_requirement_decision_revision
        CHECK (current_decision_revision >= 0),
    CONSTRAINT chk_maitu_workbench_material_requirement_asset_types
        CHECK (jsonb_typeof(accepted_asset_types) = 'array'),
    CONSTRAINT chk_maitu_workbench_material_requirement_keywords CHECK (jsonb_typeof(keywords) = 'array'),
    CONSTRAINT chk_maitu_workbench_material_requirement_selection
        CHECK (jsonb_typeof(pipeline_selection) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_material_requirements_run
ON maitu_workbench_material_requirements(run_id, plan_revision_number, scene_index, need_index);

CREATE TABLE IF NOT EXISTS maitu_workbench_material_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_code VARCHAR(80) NOT NULL UNIQUE,
    requirement_id UUID NOT NULL REFERENCES maitu_workbench_material_requirements(id) ON DELETE CASCADE,
    requirement_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    decision VARCHAR(32) NOT NULL,
    selected_asset_code VARCHAR(64),
    selected_material_key VARCHAR(255),
    reason TEXT NOT NULL,
    decision_source VARCHAR(32) NOT NULL DEFAULT 'manual',
    decided_by VARCHAR(128),
    inventory_snapshot_id UUID REFERENCES maitu_workbench_inventory_snapshots(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (requirement_id, revision_number),
    CONSTRAINT chk_maitu_workbench_material_decision_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_maitu_workbench_material_decision_value
        CHECK (decision IN ('selected', 'deferred', 'waived')),
    CONSTRAINT chk_maitu_workbench_material_decision_source
        CHECK (decision_source IN ('manual', 'pipeline_auto', 'carried_forward')),
    CONSTRAINT chk_maitu_workbench_material_decision_selection
        CHECK (
            (decision = 'selected' AND num_nonnulls(selected_asset_code, selected_material_key) = 1)
            OR (decision IN ('deferred', 'waived')
                AND selected_asset_code IS NULL AND selected_material_key IS NULL)
        )
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_material_decisions_requirement
ON maitu_workbench_material_decisions(requirement_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS maitu_workbench_preflights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preflight_code VARCHAR(80) NOT NULL UNIQUE,
    run_id UUID NOT NULL REFERENCES maitu_workbench_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(64) NOT NULL,
    plan_revision_id UUID NOT NULL REFERENCES maitu_workbench_plan_revisions(id) ON DELETE CASCADE,
    plan_revision_number INTEGER NOT NULL,
    preflight_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    performed_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, preflight_number),
    CONSTRAINT chk_maitu_workbench_preflight_status CHECK (status IN ('passed', 'blocked')),
    CONSTRAINT chk_maitu_workbench_preflight_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_preflight_checks CHECK (jsonb_typeof(checks) = 'array'),
    CONSTRAINT chk_maitu_workbench_preflight_blocked_reasons CHECK (jsonb_typeof(blocked_reasons) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_preflights_run
ON maitu_workbench_preflights(run_id, preflight_number DESC);

CREATE TABLE IF NOT EXISTS maitu_workbench_draft_execution_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_job_code VARCHAR(80) NOT NULL UNIQUE,
    run_id UUID NOT NULL REFERENCES maitu_workbench_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(64) NOT NULL,
    plan_revision_id UUID NOT NULL REFERENCES maitu_workbench_plan_revisions(id),
    plan_revision_number INTEGER NOT NULL,
    preflight_id UUID NOT NULL REFERENCES maitu_workbench_preflights(id),
    preflight_code VARCHAR(80) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 1,
    input_fingerprint CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128),
    payload JSONB NOT NULL,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    ready_for_go_live BOOLEAN NOT NULL DEFAULT false,
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message TEXT,
    queued_by VARCHAR(128),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_workbench_draft_execution_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT chk_maitu_workbench_draft_execution_attempt CHECK (attempt >= 1),
    CONSTRAINT chk_maitu_workbench_draft_execution_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_workbench_draft_execution_payload CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT chk_maitu_workbench_draft_execution_result CHECK (jsonb_typeof(result) = 'object'),
    CONSTRAINT chk_maitu_workbench_draft_execution_never_go_live CHECK (ready_for_go_live = false),
    CONSTRAINT chk_maitu_workbench_draft_execution_lease
        CHECK (
            (claimed_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
            OR (claimed_by IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        ),
    CONSTRAINT chk_maitu_workbench_draft_execution_terminal
        CHECK (
            (status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL)
            OR status NOT IN ('succeeded', 'failed', 'cancelled')
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_workbench_draft_execution_idempotency
ON maitu_workbench_draft_execution_jobs(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_draft_execution_queue
ON maitu_workbench_draft_execution_jobs(status, created_at);

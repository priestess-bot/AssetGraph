-- Local schedule design and validation. This schema never grants go-live.

CREATE TABLE IF NOT EXISTS broadcast_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_code VARCHAR(80) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    current_revision_number INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_broadcast_schedule_revision CHECK (current_revision_number >= 1)
);

CREATE TABLE IF NOT EXISTS broadcast_schedule_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID NOT NULL REFERENCES broadcast_schedules(id) ON DELETE CASCADE,
    schedule_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    release_code VARCHAR(80) NOT NULL REFERENCES releases(release_code),
    release_fingerprint_sha256 CHAR(64),
    target_account_id VARCHAR(128) NOT NULL,
    target_room_id VARCHAR(128) NOT NULL,
    platform VARCHAR(64) NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    owner VARCHAR(128) NOT NULL,
    promotion_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    inventory_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflict_strategy VARCHAR(64) NOT NULL,
    stop_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (schedule_id, revision_number),
    CONSTRAINT chk_broadcast_schedule_status CHECK (
        status IN ('draft', 'validated', 'approval_required', 'approved', 'active', 'rejected', 'canceled', 'completed')
    ),
    CONSTRAINT chk_broadcast_schedule_window CHECK (ends_at > starts_at),
    CONSTRAINT chk_broadcast_schedule_promotion CHECK (jsonb_typeof(promotion_dependencies) = 'array'),
    CONSTRAINT chk_broadcast_schedule_inventory CHECK (jsonb_typeof(inventory_dependencies) = 'array'),
    CONSTRAINT chk_broadcast_schedule_stop CHECK (jsonb_typeof(stop_conditions) = 'array'),
    CONSTRAINT chk_broadcast_schedule_validation CHECK (jsonb_typeof(validation_result) = 'object'),
    CONSTRAINT chk_broadcast_schedule_fingerprint CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_broadcast_schedule_revisions_room_window
    ON broadcast_schedule_revisions (target_room_id, starts_at, ends_at);

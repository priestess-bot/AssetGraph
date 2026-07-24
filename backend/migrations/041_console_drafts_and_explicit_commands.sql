BEGIN;

CREATE TABLE IF NOT EXISTS console_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_code VARCHAR(80) NOT NULL UNIQUE,
    entity_type VARCHAR(64) NOT NULL,
    entity_code VARCHAR(128) NOT NULL,
    draft_kind VARCHAR(32) NOT NULL,
    schema_version VARCHAR(64) NOT NULL DEFAULT 'console-draft.v1',
    draft_revision INTEGER NOT NULL DEFAULT 1,
    base_entity_revision INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    document JSONB NOT NULL,
    content_fingerprint CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_code, draft_kind),
    CONSTRAINT chk_console_draft_entity_type CHECK (entity_type IN (
        'content_project', 'live_room_configuration', 'asset_constraint_profile',
        'material_pack', 'live_room_template', 'metric_definition',
        'effect_estimate', 'broadcast_schedule', 'role_strategy', 'experiment'
    )),
    CONSTRAINT chk_console_draft_kind CHECK (draft_kind IN (
        'input', 'configuration', 'constraints', 'cleaning', 'timeline',
        'strategy', 'schedule'
    )),
    CONSTRAINT chk_console_draft_revision CHECK (draft_revision >= 1),
    CONSTRAINT chk_console_draft_base_revision CHECK (base_entity_revision >= 0),
    CONSTRAINT chk_console_draft_status CHECK (status IN ('active', 'consumed')),
    CONSTRAINT chk_console_draft_document CHECK (jsonb_typeof(document) = 'object'),
    CONSTRAINT chk_console_draft_sha CHECK (content_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_console_drafts_updated
    ON console_drafts(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS console_draft_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL REFERENCES console_drafts(id),
    draft_code VARCHAR(80) NOT NULL,
    draft_revision INTEGER NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    base_entity_revision INTEGER NOT NULL,
    content_fingerprint CHAR(64) NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    event_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (draft_id, draft_revision),
    CONSTRAINT chk_console_draft_event_revision CHECK (draft_revision >= 1),
    CONSTRAINT chk_console_draft_event_type CHECK (event_type IN ('created', 'saved', 'reopened', 'consumed')),
    CONSTRAINT chk_console_draft_event_base CHECK (base_entity_revision >= 0),
    CONSTRAINT chk_console_draft_event_sha CHECK (content_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_console_draft_event_metadata CHECK (jsonb_typeof(event_metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_console_draft_events_draft
    ON console_draft_events(draft_id, draft_revision DESC);

DROP TRIGGER IF EXISTS trg_console_draft_events_append_only ON console_draft_events;
CREATE TRIGGER trg_console_draft_events_append_only
BEFORE UPDATE OR DELETE ON console_draft_events
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

ALTER TABLE execution_authorizations
    ADD COLUMN IF NOT EXISTS source_human_task_id UUID REFERENCES human_tasks(id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_authorization_source_task
    ON execution_authorizations(source_human_task_id)
    WHERE source_human_task_id IS NOT NULL;

COMMIT;

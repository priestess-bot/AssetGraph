-- Fast-track operational input, descriptive attribution, and planning-only schedule records.

CREATE TABLE IF NOT EXISTS functional_operation_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    platform VARCHAR(64) NOT NULL,
    content_project_code VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    source_kind VARCHAR(32) NOT NULL DEFAULT 'manual_import',
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    import_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_operation_interval CHECK (ended_at > started_at),
    CONSTRAINT chk_functional_operation_source CHECK (source_kind IN ('manual_import', 'adapter_import')),
    CONSTRAINT chk_functional_operation_metrics CHECK (jsonb_typeof(metrics) = 'object')
);

CREATE TABLE IF NOT EXISTS functional_attribution_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_code VARCHAR(64) NOT NULL UNIQUE,
    metric_key VARCHAR(80) NOT NULL,
    evidence_level VARCHAR(32) NOT NULL DEFAULT 'descriptive',
    session_codes JSONB NOT NULL,
    results JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_attribution_sessions CHECK (jsonb_typeof(session_codes) = 'array'),
    CONSTRAINT chk_functional_attribution_results CHECK (jsonb_typeof(results) = 'object')
);

CREATE TABLE IF NOT EXISTS functional_schedule_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    target_live_room_id VARCHAR(128) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    duration_minutes INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    conflict_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_schedule_duration CHECK (duration_minutes BETWEEN 1 AND 1440),
    CONSTRAINT chk_functional_schedule_status CHECK (status IN ('planned', 'conflict')),
    CONSTRAINT chk_functional_schedule_conflicts CHECK (jsonb_typeof(conflict_codes) = 'array')
);

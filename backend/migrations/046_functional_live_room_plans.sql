-- Fast-track preview and execution-request records for generated live-room drafts.

CREATE TABLE IF NOT EXISTS functional_live_room_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_code VARCHAR(64) NOT NULL UNIQUE,
    project_code VARCHAR(64) NOT NULL,
    variant_code VARCHAR(64) NOT NULL UNIQUE,
    configuration_code VARCHAR(64) NOT NULL UNIQUE,
    target_live_room_id VARCHAR(128) NOT NULL,
    expected_title VARCHAR(255) NOT NULL,
    primary_template_code VARCHAR(80),
    secondary_template_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_asset_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_group_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    blueprint JSONB NOT NULL,
    build_plan JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    execution_status VARCHAR(32) NOT NULL DEFAULT 'not_requested',
    execution_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_live_room_plan_status CHECK (status IN ('ready', 'blocked')),
    CONSTRAINT chk_functional_live_room_execution_status CHECK (execution_status IN ('not_requested', 'requested', 'blocked', 'demo_complete', 'maitu_complete')),
    CONSTRAINT chk_functional_live_room_secondary_templates CHECK (jsonb_typeof(secondary_template_codes) = 'array'),
    CONSTRAINT chk_functional_live_room_selected_assets CHECK (jsonb_typeof(selected_asset_codes) = 'array'),
    CONSTRAINT chk_functional_live_room_selected_groups CHECK (jsonb_typeof(selected_group_codes) = 'array'),
    CONSTRAINT chk_functional_live_room_blueprint CHECK (jsonb_typeof(blueprint) = 'object'),
    CONSTRAINT chk_functional_live_room_build_plan CHECK (jsonb_typeof(build_plan) = 'object'),
    CONSTRAINT chk_functional_live_room_blocked_reasons CHECK (jsonb_typeof(blocked_reasons) = 'array'),
    CONSTRAINT chk_functional_live_room_execution_evidence CHECK (jsonb_typeof(execution_evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_functional_live_room_plans_project
    ON functional_live_room_plans(project_code, created_at DESC);

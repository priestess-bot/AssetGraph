-- AssetGraph Maitu live-room BuildPlan execution/evidence extension
-- Stores callbacks from worker BuildPlan dry-run/preflight/non-destructive execution phases.

CREATE TABLE IF NOT EXISTS maitu_live_room_build_plan_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_code VARCHAR(64) NOT NULL UNIQUE,
    build_plan_code VARCHAR(64) NOT NULL,
    blueprint_code VARCHAR(64) NOT NULL,
    executor VARCHAR(64) NOT NULL DEFAULT 'browser_use',
    execution_status VARCHAR(32) NOT NULL,
    mode VARCHAR(64) NOT NULL DEFAULT 'non_destructive',
    failure_type VARCHAR(64),
    retryable BOOLEAN NOT NULL DEFAULT false,
    retry_instruction TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    screenshot_asset_code VARCHAR(64),
    dom_snapshot_asset_code VARCHAR(64),
    result_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_executions_build_plan_code ON maitu_live_room_build_plan_executions(build_plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_executions_blueprint_code ON maitu_live_room_build_plan_executions(blueprint_code);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_executions_executor ON maitu_live_room_build_plan_executions(executor);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_executions_status ON maitu_live_room_build_plan_executions(execution_status);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_executions_mode ON maitu_live_room_build_plan_executions(mode);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_executions_created_at ON maitu_live_room_build_plan_executions(created_at);

CREATE TABLE IF NOT EXISTS maitu_live_room_build_plan_operation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES maitu_live_room_build_plan_executions(id),
    execution_code VARCHAR(64) NOT NULL,
    build_plan_code VARCHAR(64) NOT NULL,
    operation_index INTEGER NOT NULL,
    operation_type VARCHAR(64) NOT NULL,
    operation_name VARCHAR(255),
    scene_name VARCHAR(128),
    layer_name VARCHAR(128),
    action_type VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    failure_type VARCHAR(64),
    retryable BOOLEAN NOT NULL DEFAULT false,
    retry_instruction TEXT,
    error_message TEXT,
    screenshot_asset_code VARCHAR(64),
    dom_snapshot_asset_code VARCHAR(64),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operation_results_execution_code ON maitu_live_room_build_plan_operation_results(execution_code);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operation_results_build_plan_code ON maitu_live_room_build_plan_operation_results(build_plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operation_results_operation_type ON maitu_live_room_build_plan_operation_results(operation_type);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operation_results_action_type ON maitu_live_room_build_plan_operation_results(action_type);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operation_results_status ON maitu_live_room_build_plan_operation_results(status);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operation_results_failure_type ON maitu_live_room_build_plan_operation_results(failure_type);

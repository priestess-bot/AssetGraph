-- AssetGraph Maitu Browser use execution result extension
-- Stores execution callbacks from Browser use after it operates Maitu projects/templates.

CREATE TABLE IF NOT EXISTS maitu_replacement_plan_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_code VARCHAR(64) NOT NULL UNIQUE,
    plan_code VARCHAR(64) NOT NULL,
    executor VARCHAR(64) NOT NULL DEFAULT 'browser_use',
    execution_status VARCHAR(32) NOT NULL,
    failure_type VARCHAR(64),
    retryable BOOLEAN NOT NULL DEFAULT false,
    retry_instruction TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    screenshot_asset_code VARCHAR(64),
    result_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_executions_plan_code ON maitu_replacement_plan_executions(plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_executions_executor ON maitu_replacement_plan_executions(executor);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_executions_status ON maitu_replacement_plan_executions(execution_status);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_executions_created_at ON maitu_replacement_plan_executions(created_at);

CREATE TABLE IF NOT EXISTS maitu_replacement_plan_operation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES maitu_replacement_plan_executions(id),
    execution_code VARCHAR(64) NOT NULL,
    plan_code VARCHAR(64) NOT NULL,
    slot_code VARCHAR(64) NOT NULL,
    operation_type VARCHAR(64) NOT NULL DEFAULT 'replace_layer_asset',
    asset_code VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    failure_type VARCHAR(64),
    retryable BOOLEAN NOT NULL DEFAULT false,
    retry_instruction TEXT,
    error_message TEXT,
    screenshot_asset_code VARCHAR(64),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maitu_operation_results_execution_code ON maitu_replacement_plan_operation_results(execution_code);
CREATE INDEX IF NOT EXISTS idx_maitu_operation_results_plan_code ON maitu_replacement_plan_operation_results(plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_operation_results_slot_code ON maitu_replacement_plan_operation_results(slot_code);
CREATE INDEX IF NOT EXISTS idx_maitu_operation_results_status ON maitu_replacement_plan_operation_results(status);
CREATE INDEX IF NOT EXISTS idx_maitu_operation_results_failure_type ON maitu_replacement_plan_operation_results(failure_type);

CREATE TABLE IF NOT EXISTS maitu_execution_retry_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retry_task_code VARCHAR(64) NOT NULL UNIQUE,
    plan_code VARCHAR(64) NOT NULL,
    execution_code VARCHAR(64) NOT NULL,
    slot_code VARCHAR(64),
    asset_code VARCHAR(64),
    executor VARCHAR(64) NOT NULL DEFAULT 'browser_use',
    failure_type VARCHAR(64),
    retryable BOOLEAN NOT NULL DEFAULT true,
    retry_instruction TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    screenshot_asset_code VARCHAR(64),
    retry_attempt_count INTEGER NOT NULL DEFAULT 0,
    last_retry_execution_code VARCHAR(64),
    result_summary TEXT,
    claimed_by VARCHAR(128),
    claimed_at TIMESTAMPTZ,
    claim_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_plan_code ON maitu_execution_retry_tasks(plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_execution_code ON maitu_execution_retry_tasks(execution_code);
CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_slot_code ON maitu_execution_retry_tasks(slot_code);
CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_status ON maitu_execution_retry_tasks(status);
CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_failure_type ON maitu_execution_retry_tasks(failure_type);
CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_claimed_by ON maitu_execution_retry_tasks(claimed_by);
CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_claim_expires_at ON maitu_execution_retry_tasks(claim_expires_at);

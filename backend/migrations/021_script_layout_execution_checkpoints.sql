-- Phase D: fenced, resumable script-layout checkpoints on existing BuildPlan executions/results.
-- The only new table is an immutable reconciliation receipt ledger; it is audit data, not a queue.

-- Material bindings consumed by the frozen manifest carry a signed inventory
-- readback receipt.  This prevents an authenticated empty/partial PATCH from
-- blessing identity fields written through an older asset endpoint.
ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS maitu_binding_inventory_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_binding_readback_nonce UUID,
    ADD COLUMN IF NOT EXISTS maitu_binding_attestation VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_maitu_binding_readback_nonce
ON assets(maitu_binding_readback_nonce)
WHERE maitu_binding_readback_nonce IS NOT NULL;

ALTER TABLE maitu_live_room_build_plan_executions
    ADD COLUMN IF NOT EXISTS execution_attempt_id UUID,
    ADD COLUMN IF NOT EXISTS start_request_id UUID,
    ADD COLUMN IF NOT EXISTS run_attempt_id UUID,
    ADD COLUMN IF NOT EXISTS plan_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS manifest_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS expected_operation_count INTEGER,
    ADD COLUMN IF NOT EXISTS checkpoint_contract VARCHAR(64),
    ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(128),
    ADD COLUMN IF NOT EXISTS lease_token UUID,
    ADD COLUMN IF NOT EXISTS lease_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS lease_acquired_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS lease_reconcile_not_before TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finalization_id UUID,
    ADD COLUMN IF NOT EXISTS finalization_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ;

ALTER TABLE maitu_live_room_build_plan_operation_results
    ADD COLUMN IF NOT EXISTS operation_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS effect_class VARCHAR(32),
    ADD COLUMN IF NOT EXISTS intent_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS checkpoint_state VARCHAR(32),
    ADD COLUMN IF NOT EXISTS attempt_id UUID,
    ADD COLUMN IF NOT EXISTS completion_id UUID,
    ADD COLUMN IF NOT EXISTS completion_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reconciled_attempt_id UUID,
    ADD COLUMN IF NOT EXISTS reconciliation_resolution VARCHAR(32),
    ADD COLUMN IF NOT EXISTS reconciliation_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS reconciled_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_build_execution_attempt_id
ON maitu_live_room_build_plan_executions(execution_attempt_id)
WHERE execution_attempt_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_build_execution_start_request_id
ON maitu_live_room_build_plan_executions(start_request_id)
WHERE start_request_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_build_execution_finalization_id
ON maitu_live_room_build_plan_executions(finalization_id)
WHERE finalization_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_build_execution_checkpoint_singleton
ON maitu_live_room_build_plan_executions(build_plan_code, checkpoint_contract)
WHERE checkpoint_contract IS NOT NULL AND deleted_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_build_execution_operation_checkpoint_unique
ON maitu_live_room_build_plan_operation_results(execution_code, operation_index)
WHERE operation_fingerprint IS NOT NULL;

CREATE TABLE IF NOT EXISTS maitu_live_room_build_plan_reconciliations (
    reconciliation_id UUID PRIMARY KEY,
    receipt_fingerprint VARCHAR(64),
    operation_result_id UUID NOT NULL REFERENCES maitu_live_room_build_plan_operation_results(id) ON DELETE CASCADE,
    execution_code VARCHAR(64) NOT NULL,
    operation_index INTEGER NOT NULL,
    operation_fingerprint VARCHAR(64) NOT NULL,
    reconciled_attempt_id UUID NOT NULL,
    resolution VARCHAR(32) NOT NULL,
    resolution_summary TEXT NOT NULL,
    evidence JSONB NOT NULL,
    operation_result JSONB,
    prior_completion_id UUID,
    prior_completion_evidence JSONB,
    prior_completed_at TIMESTAMPTZ,
    reconciled_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_build_reconciliation_resolution
        CHECK (resolution IN ('confirmed_completed', 'confirmed_not_applied')),
    CONSTRAINT chk_maitu_build_reconciliation_evidence
        CHECK (jsonb_typeof(evidence) = 'object' AND evidence @> '{"verified": true}'::jsonb)
);

ALTER TABLE maitu_live_room_build_plan_reconciliations
    ADD COLUMN IF NOT EXISTS receipt_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS operation_result JSONB,
    ADD COLUMN IF NOT EXISTS prior_completion_id UUID,
    ADD COLUMN IF NOT EXISTS prior_completion_evidence JSONB,
    ADD COLUMN IF NOT EXISTS prior_completed_at TIMESTAMPTZ;

-- Reconciliation receipts are an audit ledger, not child rows whose lifetime is
-- owned by the mutable operation-result projection.  In particular, a plan or
-- execution cleanup must not erase the only durable record explaining why an
-- uncertain external side effect was accepted or retried.
ALTER TABLE maitu_live_room_build_plan_reconciliations
    DROP CONSTRAINT IF EXISTS maitu_live_room_build_plan_reconciliations_operation_result_id_fkey,
    DROP CONSTRAINT IF EXISTS maitu_live_room_build_plan_reconciliat_operation_result_id_fkey;

ALTER TABLE maitu_live_room_build_plan_reconciliations
    DROP CONSTRAINT IF EXISTS chk_maitu_build_reconciliation_fingerprint,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_reconciliation_payloads;

ALTER TABLE maitu_live_room_build_plan_reconciliations
    ADD CONSTRAINT chk_maitu_build_reconciliation_fingerprint
        CHECK (receipt_fingerprint IS NULL OR receipt_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT chk_maitu_build_reconciliation_payloads
        CHECK (
            (operation_result IS NULL OR jsonb_typeof(operation_result) = 'object')
            AND (prior_completion_evidence IS NULL OR jsonb_typeof(prior_completion_evidence) = 'object')
        );

CREATE INDEX IF NOT EXISTS idx_maitu_build_reconciliations_execution_operation
ON maitu_live_room_build_plan_reconciliations(execution_code, operation_index, created_at);

ALTER TABLE maitu_live_room_build_plan_executions
    DROP CONSTRAINT IF EXISTS chk_maitu_build_execution_plan_fingerprint,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_execution_checkpoint_manifest,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_execution_lease,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_execution_finalization;

ALTER TABLE maitu_live_room_build_plan_executions
    ADD CONSTRAINT chk_maitu_build_execution_plan_fingerprint
        CHECK (
            (plan_fingerprint IS NULL OR plan_fingerprint ~ '^[0-9a-f]{64}$')
            AND (manifest_fingerprint IS NULL OR manifest_fingerprint ~ '^[0-9a-f]{64}$')
        ),
    ADD CONSTRAINT chk_maitu_build_execution_checkpoint_manifest
        CHECK (
            checkpoint_contract IS NULL
            OR (
                execution_attempt_id IS NOT NULL
                AND start_request_id IS NOT NULL
                AND plan_fingerprint IS NOT NULL
                AND manifest_fingerprint IS NOT NULL
                AND expected_operation_count IS NOT NULL
                AND expected_operation_count > 0
            )
        ),
    ADD CONSTRAINT chk_maitu_build_execution_lease
        CHECK (
            (lease_token IS NULL AND lease_owner IS NULL AND run_attempt_id IS NULL
                AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)
            OR (lease_token IS NOT NULL AND lease_owner IS NOT NULL AND run_attempt_id IS NOT NULL
                AND lease_acquired_at IS NOT NULL AND lease_expires_at IS NOT NULL
                AND lease_version > 0 AND lease_expires_at > lease_acquired_at)
        ),
    ADD CONSTRAINT chk_maitu_build_execution_finalization
        CHECK (
            (finalization_id IS NULL AND finalization_fingerprint IS NULL AND finalized_at IS NULL)
            OR (finalization_id IS NOT NULL AND finalization_fingerprint ~ '^[0-9a-f]{64}$' AND finalized_at IS NOT NULL)
        );

ALTER TABLE maitu_live_room_build_plan_operation_results
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_fingerprint,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_checkpoint_state,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_completion_evidence,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_reconciliation_resolution,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_checkpoint_json_objects,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_manifest,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_dispatch,
    DROP CONSTRAINT IF EXISTS chk_maitu_build_operation_terminal_policy;

ALTER TABLE maitu_live_room_build_plan_operation_results
    ADD CONSTRAINT chk_maitu_build_operation_fingerprint
        CHECK (operation_fingerprint IS NULL OR operation_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT chk_maitu_build_operation_checkpoint_state
        CHECK (
            checkpoint_state IS NULL
            OR checkpoint_state IN (
                'not_started', 'prepared', 'dispatched', 'reconcile_required',
                'retry_authorized', 'completed', 'observed', 'manual_required'
            )
        ),
    ADD CONSTRAINT chk_maitu_build_operation_manifest
        CHECK (
            checkpoint_state IS NULL
            OR (
                operation_fingerprint IS NOT NULL
                AND effect_class IN ('mutating', 'read_only', 'manual_noop')
                AND jsonb_typeof(intent_snapshot) = 'object'
            )
        ),
    ADD CONSTRAINT chk_maitu_build_operation_dispatch
        CHECK (
            checkpoint_state NOT IN ('prepared', 'dispatched')
            OR (
                attempt_id IS NOT NULL
                AND (checkpoint_state <> 'dispatched' OR dispatched_at IS NOT NULL)
            )
        ),
    ADD CONSTRAINT chk_maitu_build_operation_terminal_policy
        CHECK (
            checkpoint_state NOT IN ('completed', 'observed', 'manual_required')
            OR (
                completion_id IS NOT NULL
                AND completed_at IS NOT NULL
                AND completion_evidence @> '{"verified": true}'::jsonb
                AND (
                    (effect_class = 'mutating' AND checkpoint_state = 'completed'
                        AND completion_evidence @> '{"operation_applied": true}'::jsonb)
                    OR (effect_class = 'read_only' AND checkpoint_state = 'observed'
                        AND completion_evidence @> '{"no_side_effect": true}'::jsonb)
                    OR (effect_class = 'manual_noop' AND checkpoint_state = 'manual_required'
                        AND completion_evidence @> '{"no_side_effect": true}'::jsonb)
                )
            )
        ),
    ADD CONSTRAINT chk_maitu_build_operation_reconciliation_resolution
        CHECK (
            reconciliation_resolution IS NULL
            OR reconciliation_resolution IN ('confirmed_completed', 'confirmed_not_applied')
        ),
    ADD CONSTRAINT chk_maitu_build_operation_checkpoint_json_objects
        CHECK (
            jsonb_typeof(completion_evidence) = 'object'
            AND jsonb_typeof(reconciliation_evidence) = 'object'
        );

CREATE OR REPLACE FUNCTION reject_maitu_build_reconciliation_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'BuildPlan reconciliation receipts are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_maitu_build_reconciliations_immutable
ON maitu_live_room_build_plan_reconciliations;
CREATE TRIGGER trg_maitu_build_reconciliations_immutable
BEFORE UPDATE OR DELETE ON maitu_live_room_build_plan_reconciliations
FOR EACH ROW EXECUTE FUNCTION reject_maitu_build_reconciliation_mutation();

-- Durable four-stage protocol for workflow steps with external side effects.

CREATE TABLE IF NOT EXISTS workflow_external_effects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    effect_code VARCHAR(96) NOT NULL UNIQUE,
    step_id UUID NOT NULL REFERENCES workflow_steps(id) ON DELETE CASCADE,
    step_code VARCHAR(96) NOT NULL,
    attempt INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    phase VARCHAR(32) NOT NULL DEFAULT 'prepared',
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(255) NOT NULL,
    operation_type VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    plan_or_release_hash CHAR(64) NOT NULL,
    request_fingerprint CHAR(64) NOT NULL,
    authorization_code VARCHAR(80),
    external_identity JSONB,
    response_summary JSONB,
    readback_evidence JSONB,
    reconcile_evidence JSONB,
    unknown_outcome BOOLEAN NOT NULL DEFAULT false,
    error_code VARCHAR(64),
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    authorized_at TIMESTAMPTZ,
    commit_started_at TIMESTAMPTZ,
    commit_completed_at TIMESTAMPTZ,
    readback_completed_at TIMESTAMPTZ,
    reconciled_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (step_id, attempt, idempotency_key),
    CONSTRAINT chk_workflow_external_effect_attempt CHECK (attempt >= 1),
    CONSTRAINT chk_workflow_external_effect_revision CHECK (revision >= 1),
    CONSTRAINT chk_workflow_external_effect_phase CHECK (
        phase IN (
            'prepared', 'authorized', 'committing', 'committed',
            'readback_succeeded', 'reconcile_required', 'reconciled',
            'compensated', 'failed', 'cancelled'
        )
    ),
    CONSTRAINT chk_workflow_external_effect_plan_hash CHECK (plan_or_release_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_workflow_external_effect_request_hash CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_workflow_external_effect_identity CHECK (
        external_identity IS NULL OR jsonb_typeof(external_identity) = 'object'
    ),
    CONSTRAINT chk_workflow_external_effect_response CHECK (
        response_summary IS NULL OR jsonb_typeof(response_summary) = 'object'
    ),
    CONSTRAINT chk_workflow_external_effect_readback CHECK (
        readback_evidence IS NULL OR jsonb_typeof(readback_evidence) = 'object'
    ),
    CONSTRAINT chk_workflow_external_effect_reconcile CHECK (
        reconcile_evidence IS NULL OR jsonb_typeof(reconcile_evidence) = 'object'
    ),
    CONSTRAINT chk_workflow_external_effect_authorized CHECK (
        phase = 'prepared' OR authorization_code IS NOT NULL
    ),
    CONSTRAINT chk_workflow_external_effect_readback_required CHECK (
        phase <> 'readback_succeeded'
        OR (external_identity IS NOT NULL AND readback_evidence IS NOT NULL AND readback_completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_workflow_external_effect_reconcile
    ON workflow_external_effects(phase, updated_at)
    WHERE phase = 'reconcile_required';

CREATE TABLE IF NOT EXISTS workflow_external_effect_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    effect_id UUID NOT NULL REFERENCES workflow_external_effects(id) ON DELETE CASCADE,
    from_phase VARCHAR(32),
    to_phase VARCHAR(32) NOT NULL,
    revision INTEGER NOT NULL,
    actor_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128),
    reason_code VARCHAR(64) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_workflow_external_history_revision CHECK (revision >= 1),
    CONSTRAINT chk_workflow_external_history_actor CHECK (
        actor_type IN ('user', 'worker', 'system', 'reconciler')
    ),
    CONSTRAINT chk_workflow_external_history_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_workflow_external_history_effect
    ON workflow_external_effect_history(effect_id, revision);

DROP TRIGGER IF EXISTS trg_workflow_external_history_append_only ON workflow_external_effect_history;
CREATE TRIGGER trg_workflow_external_history_append_only
BEFORE UPDATE OR DELETE ON workflow_external_effect_history
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

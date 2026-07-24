-- Hash-chained authorization/effect evidence and durable integrity alerts.

CREATE TABLE IF NOT EXISTS execution_authorization_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    authorization_id UUID NOT NULL REFERENCES execution_authorizations(id),
    authorization_code VARCHAR(80) NOT NULL,
    revision INTEGER NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    authorization_status VARCHAR(32) NOT NULL,
    actor_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128),
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    claim_fingerprint CHAR(64) NOT NULL,
    event_fingerprint CHAR(64) NOT NULL,
    previous_chain_hash CHAR(64),
    chain_hash CHAR(64) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (authorization_id, revision),
    CONSTRAINT chk_authorization_history_revision CHECK (revision >= 1),
    CONSTRAINT chk_authorization_history_event CHECK (
        event_type IN ('issued', 'consumed', 'revoked', 'expired', 'legacy_snapshot')
    ),
    CONSTRAINT chk_authorization_history_status CHECK (
        authorization_status IN ('active', 'consumed', 'revoked', 'expired')
    ),
    CONSTRAINT chk_authorization_history_actor CHECK (
        actor_type IN ('user', 'worker', 'system', 'migration')
    ),
    CONSTRAINT chk_authorization_history_payload CHECK (jsonb_typeof(event_payload) = 'object'),
    CONSTRAINT chk_authorization_history_claim_sha CHECK (claim_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_authorization_history_event_sha CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_authorization_history_previous_sha CHECK (
        previous_chain_hash IS NULL OR previous_chain_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_authorization_history_chain_sha CHECK (chain_hash ~ '^[0-9a-f]{64}$')
);

INSERT INTO execution_authorization_history (
    authorization_id, authorization_code, revision, event_type,
    authorization_status, actor_type, actor_id, event_payload,
    claim_fingerprint, event_fingerprint, previous_chain_hash, chain_hash,
    occurred_at
)
SELECT auth.id,
       auth.authorization_code,
       1,
       'legacy_snapshot',
       auth.status,
       'migration',
       'migration-035',
       jsonb_build_object('source', 'pre-035-current-state'),
       encode(digest(convert_to(jsonb_build_object(
           'authorization_code', auth.authorization_code,
           'principal_type', auth.principal_type,
           'principal_id', auth.principal_id,
           'capability', auth.capability,
           'target_type', auth.target_type,
           'target_id', auth.target_id,
           'plan_or_release_hash', auth.plan_or_release_hash,
           'site_fingerprint', auth.site_fingerprint,
           'nonce_hash', auth.nonce_hash,
           'token_hash', auth.token_hash,
           'issued_at', auth.issued_at,
           'expires_at', auth.expires_at
       )::text, 'UTF8'), 'sha256'), 'hex'),
       encode(digest(convert_to(jsonb_build_object(
           'event_type', 'legacy_snapshot',
           'status', auth.status,
           'payload', jsonb_build_object('source', 'pre-035-current-state')
       )::text, 'UTF8'), 'sha256'), 'hex'),
       NULL,
       encode(digest(convert_to(':' || encode(digest(convert_to(jsonb_build_object(
           'event_type', 'legacy_snapshot',
           'status', auth.status,
           'payload', jsonb_build_object('source', 'pre-035-current-state')
       )::text, 'UTF8'), 'sha256'), 'hex'), 'UTF8'), 'sha256'), 'hex'),
       auth.issued_at
FROM execution_authorizations AS auth
ON CONFLICT (authorization_id, revision) DO NOTHING;

DROP TRIGGER IF EXISTS trg_execution_authorization_history_append_only
    ON execution_authorization_history;
CREATE TRIGGER trg_execution_authorization_history_append_only
BEFORE UPDATE OR DELETE ON execution_authorization_history
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_workflow_external_history_append_only
    ON workflow_external_effect_history;

ALTER TABLE workflow_external_effect_history
    ADD COLUMN event_fingerprint CHAR(64),
    ADD COLUMN previous_chain_hash CHAR(64),
    ADD COLUMN chain_hash CHAR(64);

DO $$
DECLARE
    item RECORD;
    current_effect UUID := NULL;
    previous_hash TEXT := NULL;
    fingerprint TEXT;
    next_hash TEXT;
BEGIN
    FOR item IN
        SELECT * FROM workflow_external_effect_history
        ORDER BY effect_id, revision, id
    LOOP
        IF current_effect IS DISTINCT FROM item.effect_id THEN
            current_effect := item.effect_id;
            previous_hash := NULL;
        END IF;
        fingerprint := encode(digest(convert_to(jsonb_build_object(
            'effect_id', item.effect_id,
            'from_phase', item.from_phase,
            'to_phase', item.to_phase,
            'revision', item.revision,
            'actor_type', item.actor_type,
            'actor_id', item.actor_id,
            'reason_code', item.reason_code,
            'evidence', item.evidence
        )::text, 'UTF8'), 'sha256'), 'hex');
        next_hash := encode(digest(convert_to(COALESCE(previous_hash, '') || ':' || fingerprint, 'UTF8'), 'sha256'), 'hex');
        UPDATE workflow_external_effect_history
        SET event_fingerprint = fingerprint,
            previous_chain_hash = previous_hash,
            chain_hash = next_hash
        WHERE id = item.id;
        previous_hash := next_hash;
    END LOOP;
END;
$$;

ALTER TABLE workflow_external_effect_history
    ALTER COLUMN event_fingerprint SET NOT NULL,
    ALTER COLUMN chain_hash SET NOT NULL,
    ADD CONSTRAINT chk_workflow_external_history_event_sha
        CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT chk_workflow_external_history_previous_sha
        CHECK (previous_chain_hash IS NULL OR previous_chain_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT chk_workflow_external_history_chain_sha
        CHECK (chain_hash ~ '^[0-9a-f]{64}$');

CREATE TRIGGER trg_workflow_external_history_append_only
BEFORE UPDATE OR DELETE ON workflow_external_effect_history
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

CREATE TABLE IF NOT EXISTS evidence_integrity_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_code VARCHAR(80) NOT NULL UNIQUE,
    alert_type VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    dedupe_key VARCHAR(255) NOT NULL UNIQUE,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_by VARCHAR(128),
    acknowledged_at TIMESTAMPTZ,
    resolved_by VARCHAR(128),
    resolved_at TIMESTAMPTZ,
    resolution JSONB,
    CONSTRAINT chk_integrity_alert_severity CHECK (severity IN ('info', 'warning', 'critical')),
    CONSTRAINT chk_integrity_alert_status CHECK (status IN ('open', 'acknowledged', 'resolved')),
    CONSTRAINT chk_integrity_alert_occurrences CHECK (occurrence_count >= 1),
    CONSTRAINT chk_integrity_alert_evidence CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT chk_integrity_alert_resolution CHECK (resolution IS NULL OR jsonb_typeof(resolution) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_integrity_alerts_open
    ON evidence_integrity_alerts(severity, last_detected_at DESC)
    WHERE status <> 'resolved';

CREATE TABLE IF NOT EXISTS integrity_check_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_code VARCHAR(80) NOT NULL UNIQUE,
    check_type VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    checked_count BIGINT NOT NULL DEFAULT 0,
    failure_count BIGINT NOT NULL DEFAULT 0,
    watermark TIMESTAMPTZ,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_integrity_check_status CHECK (status IN ('passed', 'failed', 'partial')),
    CONSTRAINT chk_integrity_check_counts CHECK (
        checked_count >= 0 AND failure_count >= 0 AND failure_count <= checked_count
    ),
    CONSTRAINT chk_integrity_check_details CHECK (jsonb_typeof(details) = 'object')
);

CREATE TABLE IF NOT EXISTS projection_event_consumptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projection_name VARCHAR(128) NOT NULL,
    event_id UUID NOT NULL,
    payload_fingerprint CHAR(64) NOT NULL,
    first_consumed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (projection_name, event_id),
    CONSTRAINT chk_projection_consumption_sha CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_projection_consumption_duplicates CHECK (duplicate_count >= 0)
);

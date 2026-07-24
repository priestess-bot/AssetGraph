-- Purpose-bound data access, redaction, retention, deletion and credential governance.

CREATE TABLE IF NOT EXISTS data_access_policy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    rules JSONB NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (policy_code, revision_number),
    CONSTRAINT chk_data_access_policy_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_data_access_policy_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_data_access_policy_rules CHECK (jsonb_typeof(rules) = 'object'),
    CONSTRAINT chk_data_access_policy_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_data_access_policy_approval CHECK (
        (status = 'active' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR status <> 'active'
    )
);

INSERT INTO data_access_policy_versions (
    policy_code, revision_number, status, rules, fingerprint_sha256,
    approved_by, approved_at
)
VALUES (
    'baseline-purpose-bound-access',
    1,
    'active',
    '{
      "schema_version": "data-access-policy.v1",
      "role_grants": {
        "production_operator": [
          {"purposes": ["content_production"], "actions": ["batch_query", "model_call"], "data_classes": ["public", "internal", "confidential"]}
        ],
        "data_operator": [
          {"purposes": ["analytics"], "actions": ["batch_query", "export", "model_call"], "data_classes": ["public", "internal", "confidential"]}
        ],
        "graph_operator": [
          {"purposes": ["knowledge_projection"], "actions": ["batch_query", "graph_query"], "data_classes": ["public", "internal", "confidential"]}
        ],
        "privacy_operator": [
          {"purposes": ["deletion", "subject_request"], "actions": ["batch_query", "export", "delete"], "data_classes": ["public", "internal", "confidential", "restricted_personal"]}
        ],
        "security_operator": [
          {"purposes": ["audit", "security_response"], "actions": ["batch_query", "export", "decrypt", "graph_query"], "data_classes": ["public", "internal", "confidential", "restricted_personal"]}
        ],
        "credential_manager": [
          {"purposes": ["credential_rotation"], "actions": ["decrypt"], "data_classes": ["credential"]}
        ]
      }
    }'::jsonb,
    encode(digest(convert_to('baseline-purpose-bound-access.v1', 'UTF8'), 'sha256'), 'hex'),
    'system-data-governance-baseline',
    now()
)
ON CONFLICT (policy_code, revision_number) DO NOTHING;

CREATE TABLE IF NOT EXISTS data_access_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_code VARCHAR(80) NOT NULL UNIQUE,
    principal_id VARCHAR(128) NOT NULL,
    roles JSONB NOT NULL,
    purpose VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_code VARCHAR(255) NOT NULL,
    data_class VARCHAR(32) NOT NULL,
    policy_code VARCHAR(80) NOT NULL,
    policy_revision INTEGER NOT NULL,
    decision VARCHAR(16) NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_fingerprint CHAR(64) NOT NULL,
    trace_id VARCHAR(64),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_data_access_roles CHECK (jsonb_typeof(roles) = 'array'),
    CONSTRAINT chk_data_access_action CHECK (
        action IN ('export', 'decrypt', 'batch_query', 'model_call', 'graph_query', 'delete')
    ),
    CONSTRAINT chk_data_access_class CHECK (
        data_class IN ('public', 'internal', 'confidential', 'restricted_personal', 'credential')
    ),
    CONSTRAINT chk_data_access_revision CHECK (policy_revision >= 1),
    CONSTRAINT chk_data_access_decision CHECK (decision IN ('allow', 'deny')),
    CONSTRAINT chk_data_access_reasons CHECK (jsonb_typeof(reason_codes) = 'array'),
    CONSTRAINT chk_data_access_input_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_data_access_decisions_principal
    ON data_access_decisions(principal_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_access_decisions_resource
    ON data_access_decisions(resource_type, resource_code, decided_at DESC);

CREATE TABLE IF NOT EXISTS redaction_policy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    contexts JSONB NOT NULL,
    rules JSONB NOT NULL,
    replacement VARCHAR(64) NOT NULL DEFAULT '[REDACTED]',
    fingerprint_sha256 CHAR(64) NOT NULL,
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (policy_code, revision_number),
    CONSTRAINT chk_redaction_policy_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_redaction_policy_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_redaction_policy_contexts CHECK (jsonb_typeof(contexts) = 'array'),
    CONSTRAINT chk_redaction_policy_rules CHECK (jsonb_typeof(rules) = 'object'),
    CONSTRAINT chk_redaction_policy_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

INSERT INTO redaction_policy_versions (
    policy_code, revision_number, status, contexts, rules,
    fingerprint_sha256, approved_by, approved_at
)
VALUES (
    'baseline-sensitive-field-redaction',
    1,
    'active',
    '["log", "screenshot", "prompt", "model_response", "public_evidence", "graph"]'::jsonb,
    '{
      "forbidden_key_markers": ["authorization", "cookie", "token", "password", "secret", "credential", "raw_payload"],
      "personal_key_markers": ["email", "phone", "mobile", "user_id", "open_id", "order_id", "address", "comment_text"],
      "value_patterns": ["bearer", "provider_token", "email", "phone"]
    }'::jsonb,
    encode(digest(convert_to('baseline-sensitive-field-redaction.v1', 'UTF8'), 'sha256'), 'hex'),
    'system-data-governance-baseline',
    now()
)
ON CONFLICT (policy_code, revision_number) DO NOTHING;

INSERT INTO retention_policy_versions (
    policy_code, revision_number, status, data_class, retention_days,
    legal_basis, deletion_behavior, approved_by, approved_at
)
VALUES
    ('external-raw-capture', 1, 'active', 'external_raw_capture', 30,
     'authorized capture purpose', '{"terminal_action":"delete","legal_hold_allowed":true}'::jsonb,
     'system-data-governance-baseline', now()),
    ('raw-personal-event', 1, 'active', 'raw_personal_event', 90,
     'source contract and approved purpose', '{"terminal_action":"delete_or_irreversibly_anonymize","contract_range_days":[30,90],"legal_hold_allowed":true}'::jsonb,
     'system-data-governance-baseline', now()),
    ('deidentified-standard-event', 1, 'active', 'deidentified_standard_event', 180,
     'analytics recomputation window', '{"terminal_action":"delete","legal_hold_allowed":true}'::jsonb,
     'system-data-governance-baseline', now()),
    ('aggregate-published-result', 1, 'active', 'aggregate_published_result', NULL,
     'versioned non-reidentifiable business record', '{"terminal_action":"retain_versioned","must_be_non_reidentifiable":true}'::jsonb,
     'system-data-governance-baseline', now()),
    ('critical-audit-evidence', 1, 'active', 'critical_audit_evidence', NULL,
     'audit and accountability policy', '{"terminal_action":"retain_versioned","sensitive_payload_separate":true}'::jsonb,
     'system-data-governance-baseline', now()),
    ('intermediate-artifact', 1, 'active', 'intermediate_artifact', 30,
     'rebuildable production evidence', '{"terminal_action":"delete","purpose_range_days":[30,180],"legal_hold_allowed":true}'::jsonb,
     'system-data-governance-baseline', now())
ON CONFLICT (policy_code, revision_number) DO NOTHING;

ALTER TABLE deletion_runs DROP CONSTRAINT IF EXISTS chk_deletion_run_status;
UPDATE deletion_runs SET status = 'blocked_by_legal_hold' WHERE status = 'legal_hold';
ALTER TABLE deletion_runs
    ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS required_processors JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD CONSTRAINT chk_deletion_run_status CHECK (
        status IN ('requested', 'validating', 'blocked_by_legal_hold', 'approved',
                   'executing', 'verifying', 'completed', 'partial_failed', 'rejected')
    ),
    ADD CONSTRAINT chk_deletion_run_revision CHECK (revision >= 1),
    ADD CONSTRAINT chk_deletion_run_processors CHECK (jsonb_typeof(required_processors) = 'array'),
    ADD CONSTRAINT chk_deletion_run_retry CHECK (retry_count >= 0);

CREATE TABLE IF NOT EXISTS deletion_run_status_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deletion_run_id UUID NOT NULL REFERENCES deletion_runs(id),
    deletion_run_code VARCHAR(80) NOT NULL,
    revision INTEGER NOT NULL,
    from_status VARCHAR(32),
    to_status VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (deletion_run_id, revision),
    CONSTRAINT chk_deletion_history_revision CHECK (revision >= 1),
    CONSTRAINT chk_deletion_history_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE TABLE IF NOT EXISTS legal_hold_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_hold_id UUID NOT NULL REFERENCES legal_holds(id),
    hold_code VARCHAR(80) NOT NULL,
    revision INTEGER NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (legal_hold_id, revision),
    CONSTRAINT chk_legal_hold_history_revision CHECK (revision >= 1),
    CONSTRAINT chk_legal_hold_history_type CHECK (event_type IN ('created', 'released', 'expired')),
    CONSTRAINT chk_legal_hold_history_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE TABLE IF NOT EXISTS credential_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_code VARCHAR(80) NOT NULL UNIQUE,
    processor_code VARCHAR(80) NOT NULL,
    secret_ref VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    allowed_scopes JSONB NOT NULL,
    allowed_regions JSONB NOT NULL,
    credential_owner VARCHAR(128) NOT NULL,
    rotation_interval_days INTEGER NOT NULL,
    last_rotated_at TIMESTAMPTZ NOT NULL,
    next_rotation_due_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_credential_status CHECK (status IN ('active', 'rotation_due', 'revoked')),
    CONSTRAINT chk_credential_scopes CHECK (jsonb_typeof(allowed_scopes) = 'array'),
    CONSTRAINT chk_credential_regions CHECK (jsonb_typeof(allowed_regions) = 'array'),
    CONSTRAINT chk_credential_rotation_days CHECK (rotation_interval_days BETWEEN 1 AND 365),
    CONSTRAINT chk_credential_rotation_window CHECK (next_rotation_due_at > last_rotated_at),
    CONSTRAINT chk_credential_secret_ref CHECK (
        secret_ref ~ '^(vault|secret-manager|kms)://[A-Za-z0-9._/-]+$'
    )
);

CREATE TABLE IF NOT EXISTS credential_rotation_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    credential_id UUID NOT NULL REFERENCES credential_records(id),
    credential_code VARCHAR(80) NOT NULL,
    revision INTEGER NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    old_secret_ref_fingerprint CHAR(64),
    new_secret_ref_fingerprint CHAR(64),
    actor_id VARCHAR(128) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (credential_id, revision),
    CONSTRAINT chk_credential_rotation_revision CHECK (revision >= 1),
    CONSTRAINT chk_credential_rotation_type CHECK (event_type IN ('registered', 'rotated', 'revoked', 'marked_due')),
    CONSTRAINT chk_credential_old_sha CHECK (old_secret_ref_fingerprint IS NULL OR old_secret_ref_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_credential_new_sha CHECK (new_secret_ref_fingerprint IS NULL OR new_secret_ref_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_credential_rotation_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE TABLE IF NOT EXISTS external_processor_call_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_code VARCHAR(80) NOT NULL UNIQUE,
    processor_code VARCHAR(80) NOT NULL,
    processor_revision INTEGER NOT NULL,
    purpose VARCHAR(64) NOT NULL,
    region VARCHAR(128) NOT NULL,
    data_class VARCHAR(32) NOT NULL,
    fields_sent JSONB NOT NULL,
    payload_fingerprint CHAR(64) NOT NULL,
    decision VARCHAR(16) NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    principal_id VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_processor_call_fields CHECK (jsonb_typeof(fields_sent) = 'array'),
    CONSTRAINT chk_processor_call_sha CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_processor_call_decision CHECK (decision IN ('allow', 'deny')),
    CONSTRAINT chk_processor_call_reasons CHECK (jsonb_typeof(reason_codes) = 'array')
);

DROP TRIGGER IF EXISTS trg_data_access_decisions_append_only ON data_access_decisions;
CREATE TRIGGER trg_data_access_decisions_append_only
BEFORE UPDATE OR DELETE ON data_access_decisions
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_deletion_run_history_append_only ON deletion_run_status_history;
CREATE TRIGGER trg_deletion_run_history_append_only
BEFORE UPDATE OR DELETE ON deletion_run_status_history
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_legal_hold_history_append_only ON legal_hold_history;
CREATE TRIGGER trg_legal_hold_history_append_only
BEFORE UPDATE OR DELETE ON legal_hold_history
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_credential_rotation_events_append_only ON credential_rotation_events;
CREATE TRIGGER trg_credential_rotation_events_append_only
BEFORE UPDATE OR DELETE ON credential_rotation_events
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_external_processor_call_audits_append_only ON external_processor_call_audits;
CREATE TRIGGER trg_external_processor_call_audits_append_only
BEFORE UPDATE OR DELETE ON external_processor_call_audits
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

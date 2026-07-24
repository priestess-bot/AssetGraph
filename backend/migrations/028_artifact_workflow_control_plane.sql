-- Content-addressed artifacts, manifests, lineage, outbox and durable workflow control plane.

CREATE TABLE IF NOT EXISTS artifact_refs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_code VARCHAR(80) NOT NULL UNIQUE,
    artifact_kind VARCHAR(64) NOT NULL,
    media_type VARCHAR(255) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    storage_uri TEXT NOT NULL,
    checksum_sha256 CHAR(64) NOT NULL,
    byte_size BIGINT NOT NULL,
    producer_type VARCHAR(64) NOT NULL,
    producer_code VARCHAR(128) NOT NULL,
    producer_revision INTEGER,
    sensitivity VARCHAR(32) NOT NULL DEFAULT 'internal',
    retention_policy_code VARCHAR(64) NOT NULL,
    content_addressed BOOLEAN NOT NULL DEFAULT true,
    encryption_key_ref VARCHAR(255),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_artifact_ref_schema CHECK (schema_version ~ '^[a-z0-9-]+\.v[1-9][0-9]*$'),
    CONSTRAINT chk_artifact_ref_uri CHECK (storage_uri <> ''),
    CONSTRAINT chk_artifact_ref_sha CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_artifact_ref_size CHECK (byte_size >= 0),
    CONSTRAINT chk_artifact_ref_revision CHECK (producer_revision IS NULL OR producer_revision >= 1),
    CONSTRAINT chk_artifact_ref_sensitivity CHECK (
        sensitivity IN ('public', 'internal', 'confidential', 'restricted_personal', 'credential')
    ),
    CONSTRAINT chk_artifact_ref_metadata CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_refs_content_address
    ON artifact_refs(checksum_sha256, byte_size, media_type)
    WHERE content_addressed = true;
CREATE INDEX IF NOT EXISTS idx_artifact_refs_producer
    ON artifact_refs(producer_type, producer_code, producer_revision);

CREATE TABLE IF NOT EXISTS artifact_input_refs (
    artifact_id UUID NOT NULL REFERENCES artifact_refs(id) ON DELETE CASCADE,
    input_artifact_id UUID NOT NULL REFERENCES artifact_refs(id),
    relation_type VARCHAR(64) NOT NULL DEFAULT 'derived_from',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_id, input_artifact_id, relation_type),
    CONSTRAINT chk_artifact_input_no_self CHECK (artifact_id <> input_artifact_id),
    CONSTRAINT chk_artifact_input_order CHECK (sort_order >= 0)
);

CREATE TABLE IF NOT EXISTS run_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manifest_code VARCHAR(80) NOT NULL UNIQUE,
    schema_version VARCHAR(64) NOT NULL DEFAULT 'run-manifest.v1',
    run_code VARCHAR(80) NOT NULL,
    manifest JSONB NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    output_fingerprint CHAR(64),
    manifest_fingerprint CHAR(64) NOT NULL UNIQUE,
    signature_algorithm VARCHAR(32),
    signature_key_id VARCHAR(128),
    signature_value TEXT,
    previous_chain_hash CHAR(64),
    chain_hash CHAR(64),
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_run_manifest_schema CHECK (schema_version ~ '^[a-z0-9-]+\.v[1-9][0-9]*$'),
    CONSTRAINT chk_run_manifest_object CHECK (jsonb_typeof(manifest) = 'object'),
    CONSTRAINT chk_run_manifest_input_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_run_manifest_output_sha CHECK (output_fingerprint IS NULL OR output_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_run_manifest_sha CHECK (manifest_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_run_manifest_previous_sha CHECK (previous_chain_hash IS NULL OR previous_chain_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_run_manifest_chain_sha CHECK (chain_hash IS NULL OR chain_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_run_manifest_signature_bundle CHECK (
        (signature_algorithm IS NULL AND signature_key_id IS NULL AND signature_value IS NULL)
        OR (signature_algorithm IS NOT NULL AND signature_key_id IS NOT NULL AND signature_value IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_code VARCHAR(80) NOT NULL UNIQUE,
    workflow_type VARCHAR(64) NOT NULL,
    schema_version VARCHAR(64) NOT NULL DEFAULT 'workflow-run.v1',
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    subject_revision INTEGER,
    parent_run_id UUID REFERENCES workflow_runs(id),
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    progress_completed INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    queue_reason VARCHAR(255),
    budget JSONB NOT NULL DEFAULT '{}'::jsonb,
    actual_cost JSONB NOT NULL DEFAULT '{}'::jsonb,
    trace_id VARCHAR(64),
    root_span_id VARCHAR(32),
    idempotency_key VARCHAR(255),
    requested_by VARCHAR(128),
    cancellation_requested_at TIMESTAMPTZ,
    waiting_reason VARCHAR(255),
    error_code VARCHAR(64),
    error_summary TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workflow_type, idempotency_key),
    CONSTRAINT chk_workflow_run_schema CHECK (schema_version ~ '^[a-z0-9-]+\.v[1-9][0-9]*$'),
    CONSTRAINT chk_workflow_run_revision CHECK (subject_revision IS NULL OR subject_revision >= 1),
    CONSTRAINT chk_workflow_run_status CHECK (
        status IN ('queued', 'running', 'waiting_human', 'cancelling', 'cancelled', 'succeeded', 'failed', 'reconcile_required')
    ),
    CONSTRAINT chk_workflow_run_priority CHECK (priority BETWEEN 0 AND 1000),
    CONSTRAINT chk_workflow_run_progress CHECK (
        progress_completed >= 0 AND progress_total >= 0 AND progress_completed <= progress_total
    ),
    CONSTRAINT chk_workflow_run_budget CHECK (jsonb_typeof(budget) = 'object'),
    CONSTRAINT chk_workflow_run_cost CHECK (jsonb_typeof(actual_cost) = 'object'),
    CONSTRAINT chk_workflow_run_terminal CHECK (
        (status IN ('cancelled', 'succeeded', 'failed') AND completed_at IS NOT NULL)
        OR status NOT IN ('cancelled', 'succeeded', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_queue
    ON workflow_runs(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_subject
    ON workflow_runs(subject_type, subject_code, subject_revision);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_parent
    ON workflow_runs(parent_run_id);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    step_code VARCHAR(96) NOT NULL UNIQUE,
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    run_code VARCHAR(80) NOT NULL,
    step_type VARCHAR(64) NOT NULL,
    sort_order INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 100,
    idempotency_key VARCHAR(255) NOT NULL,
    side_effect_level VARCHAR(32) NOT NULL DEFAULT 'pure_compute',
    max_attempts INTEGER NOT NULL DEFAULT 3,
    attempt INTEGER NOT NULL DEFAULT 0,
    backoff_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    timeout_seconds INTEGER NOT NULL,
    cancellable BOOLEAN NOT NULL DEFAULT true,
    compensation_strategy VARCHAR(64),
    reconcile_strategy VARCHAR(64),
    input_fingerprint CHAR(64) NOT NULL,
    output_fingerprint CHAR(64),
    claimed_by VARCHAR(128),
    claim_token UUID,
    lease_version INTEGER NOT NULL DEFAULT 0,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    trace_id VARCHAR(64),
    span_id VARCHAR(32),
    error_code VARCHAR(64),
    error_summary TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, sort_order),
    UNIQUE (run_id, idempotency_key),
    CONSTRAINT chk_workflow_step_order CHECK (sort_order >= 0),
    CONSTRAINT chk_workflow_step_status CHECK (
        status IN ('pending', 'ready', 'running', 'waiting_human', 'succeeded', 'failed', 'cancelled', 'reconcile_required')
    ),
    CONSTRAINT chk_workflow_step_priority CHECK (priority BETWEEN 0 AND 1000),
    CONSTRAINT chk_workflow_step_side_effect CHECK (
        side_effect_level IN ('pure_compute', 'read_external', 'write_external', 'irreversible_external')
    ),
    CONSTRAINT chk_workflow_step_attempt CHECK (max_attempts >= 1 AND attempt >= 0 AND attempt <= max_attempts),
    CONSTRAINT chk_workflow_step_backoff CHECK (jsonb_typeof(backoff_policy) = 'object'),
    CONSTRAINT chk_workflow_step_timeout CHECK (timeout_seconds >= 1),
    CONSTRAINT chk_workflow_step_input_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_workflow_step_output_sha CHECK (output_fingerprint IS NULL OR output_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_workflow_step_lease_version CHECK (lease_version >= 0),
    CONSTRAINT chk_workflow_step_lease CHECK (
        (claimed_by IS NULL AND claim_token IS NULL AND lease_expires_at IS NULL)
        OR (claimed_by IS NOT NULL AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    ),
    CONSTRAINT chk_workflow_step_terminal CHECK (
        (status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL)
        OR status NOT IN ('succeeded', 'failed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_workflow_steps_claim
    ON workflow_steps(status, priority, created_at)
    WHERE status = 'ready';
CREATE INDEX IF NOT EXISTS idx_workflow_steps_expired_lease
    ON workflow_steps(lease_expires_at)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS workflow_step_dependencies (
    step_id UUID NOT NULL REFERENCES workflow_steps(id) ON DELETE CASCADE,
    depends_on_step_id UUID NOT NULL REFERENCES workflow_steps(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (step_id, depends_on_step_id),
    CONSTRAINT chk_workflow_step_dependency_self CHECK (step_id <> depends_on_step_id)
);

CREATE TABLE IF NOT EXISTS workflow_status_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    step_id UUID REFERENCES workflow_steps(id) ON DELETE CASCADE,
    from_status VARCHAR(32),
    to_status VARCHAR(32) NOT NULL,
    reason_code VARCHAR(64),
    actor_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_workflow_history_actor CHECK (actor_type IN ('user', 'worker', 'system', 'reconciler')),
    CONSTRAINT chk_workflow_history_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_workflow_status_history_run
    ON workflow_status_history(run_id, occurred_at);

CREATE TABLE IF NOT EXISTS human_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_code VARCHAR(80) NOT NULL UNIQUE,
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    step_id UUID REFERENCES workflow_steps(id) ON DELETE CASCADE,
    task_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    revision INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 100,
    owner_principal VARCHAR(128),
    claimed_by VARCHAR(128),
    claimed_at TIMESTAMPTZ,
    due_at TIMESTAMPTZ,
    escalated_at TIMESTAMPTZ,
    subject JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision VARCHAR(64),
    structured_reason JSONB,
    decided_by VARCHAR(128),
    decided_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_human_task_status CHECK (status IN ('open', 'claimed', 'decided', 'expired', 'cancelled', 'escalated')),
    CONSTRAINT chk_human_task_revision CHECK (revision >= 1),
    CONSTRAINT chk_human_task_priority CHECK (priority BETWEEN 0 AND 1000),
    CONSTRAINT chk_human_task_subject CHECK (jsonb_typeof(subject) = 'object'),
    CONSTRAINT chk_human_task_reason CHECK (structured_reason IS NULL OR jsonb_typeof(structured_reason) = 'object'),
    CONSTRAINT chk_human_task_claim CHECK (
        (claimed_by IS NULL AND claimed_at IS NULL)
        OR (claimed_by IS NOT NULL AND claimed_at IS NOT NULL)
    ),
    CONSTRAINT chk_human_task_decision CHECK (
        (status = 'decided' AND decision IS NOT NULL AND structured_reason IS NOT NULL
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
        OR status <> 'decided'
    )
);

CREATE INDEX IF NOT EXISTS idx_human_tasks_queue
    ON human_tasks(status, priority, due_at, created_at);

CREATE TABLE IF NOT EXISTS workflow_artifact_links (
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    step_id UUID REFERENCES workflow_steps(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES artifact_refs(id),
    direction VARCHAR(16) NOT NULL,
    role VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, step_id, artifact_id, direction, role),
    CONSTRAINT chk_workflow_artifact_direction CHECK (direction IN ('input', 'output', 'evidence'))
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_code VARCHAR(80),
    source_namespace VARCHAR(128) NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    source_version VARCHAR(128) NOT NULL,
    target_namespace VARCHAR(128) NOT NULL,
    target_name VARCHAR(255) NOT NULL,
    target_version VARCHAR(128) NOT NULL,
    relation_type VARCHAR(64) NOT NULL,
    schema_version VARCHAR(64) NOT NULL DEFAULT 'lineage-edge.v1',
    facets JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (
        source_namespace, source_name, source_version,
        target_namespace, target_name, target_version, relation_type
    ),
    CONSTRAINT chk_lineage_edge_facets CHECK (jsonb_typeof(facets) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_lineage_edges_source
    ON lineage_edges(source_namespace, source_name, source_version);
CREATE INDEX IF NOT EXISTS idx_lineage_edges_target
    ON lineage_edges(target_namespace, target_name, target_version);

CREATE TABLE IF NOT EXISTS transactional_outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL UNIQUE,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_code VARCHAR(128) NOT NULL,
    aggregate_revision INTEGER,
    event_type VARCHAR(128) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    trace_id VARCHAR(64),
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    publish_attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    last_error_code VARCHAR(64),
    dead_lettered_at TIMESTAMPTZ,
    CONSTRAINT chk_outbox_revision CHECK (aggregate_revision IS NULL OR aggregate_revision >= 1),
    CONSTRAINT chk_outbox_schema CHECK (schema_version ~ '^[a-z0-9.-]+\.v[1-9][0-9]*$'),
    CONSTRAINT chk_outbox_payload CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT chk_outbox_attempts CHECK (publish_attempts >= 0)
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON transactional_outbox_events(next_attempt_at, created_at)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL;

CREATE TABLE IF NOT EXISTS projection_checkpoints (
    projection_name VARCHAR(128) PRIMARY KEY,
    projection_version VARCHAR(64) NOT NULL,
    last_event_id UUID,
    watermark_occurred_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'current',
    lag_seconds BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_projection_checkpoint_status CHECK (status IN ('building', 'current', 'lagging', 'failed', 'rebuilding')),
    CONSTRAINT chk_projection_checkpoint_lag CHECK (lag_seconds >= 0)
);

CREATE TABLE IF NOT EXISTS graph_projection_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projection_code VARCHAR(80) NOT NULL UNIQUE,
    schema_version VARCHAR(64) NOT NULL,
    source_watermark TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'building',
    node_count BIGINT NOT NULL DEFAULT 0,
    edge_count BIGINT NOT NULL DEFAULT 0,
    fingerprint_sha256 CHAR(64),
    build_run_code VARCHAR(80),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT chk_graph_projection_status CHECK (status IN ('building', 'current', 'superseded', 'failed')),
    CONSTRAINT chk_graph_projection_counts CHECK (node_count >= 0 AND edge_count >= 0),
    CONSTRAINT chk_graph_projection_sha CHECK (fingerprint_sha256 IS NULL OR fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_event_id UUID NOT NULL UNIQUE,
    principal_type VARCHAR(32) NOT NULL,
    principal_id VARCHAR(128),
    action VARCHAR(128) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_code VARCHAR(128) NOT NULL,
    target_revision INTEGER,
    outcome VARCHAR(32) NOT NULL,
    reason_code VARCHAR(64),
    trace_id VARCHAR(64),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_audit_principal_type CHECK (principal_type IN ('user', 'worker', 'system', 'provider')),
    CONSTRAINT chk_audit_target_revision CHECK (target_revision IS NULL OR target_revision >= 1),
    CONSTRAINT chk_audit_outcome CHECK (outcome IN ('allowed', 'denied', 'succeeded', 'failed', 'unknown')),
    CONSTRAINT chk_audit_details CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_audit_events_target
    ON audit_events(target_type, target_code, target_revision, occurred_at);

CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'append-only record cannot be mutated';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_artifact_refs_append_only ON artifact_refs;
CREATE TRIGGER trg_artifact_refs_append_only
BEFORE UPDATE OR DELETE ON artifact_refs
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_run_manifests_append_only ON run_manifests;
CREATE TRIGGER trg_run_manifests_append_only
BEFORE UPDATE OR DELETE ON run_manifests
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_lineage_edges_append_only ON lineage_edges;
CREATE TRIGGER trg_lineage_edges_append_only
BEFORE UPDATE OR DELETE ON lineage_edges
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_workflow_history_append_only ON workflow_status_history;
CREATE TRIGGER trg_workflow_history_append_only
BEFORE UPDATE OR DELETE ON workflow_status_history
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
CREATE TRIGGER trg_audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

-- Policy decisions, execution authorization, release/exposure and governed data contracts.

CREATE TABLE IF NOT EXISTS capability_policy_versions (
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
    CONSTRAINT chk_capability_policy_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_capability_policy_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_capability_policy_rules CHECK (jsonb_typeof(rules) = 'object'),
    CONSTRAINT chk_capability_policy_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_capability_policy_approval CHECK (
        (status = 'active' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR status <> 'active'
    )
);

CREATE TABLE IF NOT EXISTS protected_resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    protection_mode VARCHAR(32) NOT NULL,
    allowed_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason_code VARCHAR(64) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (resource_type, resource_id),
    CONSTRAINT chk_protected_resource_mode CHECK (protection_mode IN ('read_only', 'deny_write', 'allowlisted_write')),
    CONSTRAINT chk_protected_resource_capabilities CHECK (jsonb_typeof(allowed_capabilities) = 'array'),
    CONSTRAINT chk_protected_resource_evidence CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT chk_protected_resource_window CHECK (expires_at IS NULL OR expires_at > effective_at)
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_code VARCHAR(80) NOT NULL UNIQUE,
    principal_type VARCHAR(32) NOT NULL,
    principal_id VARCHAR(128) NOT NULL,
    capability VARCHAR(64) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(255) NOT NULL,
    action VARCHAR(128) NOT NULL,
    plan_or_release_hash CHAR(64),
    site_fingerprint CHAR(64),
    policy_code VARCHAR(80) NOT NULL,
    policy_revision INTEGER NOT NULL,
    decision VARCHAR(16) NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    approval_chain JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_fingerprint CHAR(64) NOT NULL,
    trace_id VARCHAR(64),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_policy_decision_principal CHECK (principal_type IN ('user', 'worker', 'system')),
    CONSTRAINT chk_policy_decision_capability CHECK (
        capability IN (
            'edit_production', 'publish_fact', 'publish_template', 'approve_effect',
            'write_draft', 'upload_asset', 'deliver_release', 'rebuild_projection', 'go_live'
        )
    ),
    CONSTRAINT chk_policy_decision_hash CHECK (plan_or_release_hash IS NULL OR plan_or_release_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_policy_decision_site_sha CHECK (site_fingerprint IS NULL OR site_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_policy_decision_policy_revision CHECK (policy_revision >= 1),
    CONSTRAINT chk_policy_decision_value CHECK (decision IN ('allow', 'deny')),
    CONSTRAINT chk_policy_decision_reasons CHECK (jsonb_typeof(reason_codes) = 'array'),
    CONSTRAINT chk_policy_decision_approvals CHECK (jsonb_typeof(approval_chain) = 'array'),
    CONSTRAINT chk_policy_decision_input_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_policy_decisions_target
    ON policy_decisions(target_type, target_id, capability, decided_at DESC);

CREATE TABLE IF NOT EXISTS execution_authorizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    authorization_code VARCHAR(80) NOT NULL UNIQUE,
    decision_id UUID NOT NULL REFERENCES policy_decisions(id),
    decision_code VARCHAR(80) NOT NULL,
    principal_type VARCHAR(32) NOT NULL,
    principal_id VARCHAR(128) NOT NULL,
    capability VARCHAR(64) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(255) NOT NULL,
    plan_or_release_hash CHAR(64) NOT NULL,
    site_fingerprint CHAR(64),
    nonce_hash CHAR(64) NOT NULL UNIQUE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    single_use BOOLEAN NOT NULL DEFAULT true,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_by VARCHAR(128),
    revoked_at TIMESTAMPTZ,
    revoked_by VARCHAR(128),
    revocation_reason VARCHAR(255),
    CONSTRAINT chk_execution_authorization_principal CHECK (principal_type IN ('user', 'worker', 'system')),
    CONSTRAINT chk_execution_authorization_capability CHECK (
        capability IN ('write_draft', 'upload_asset', 'deliver_release', 'rebuild_projection', 'go_live')
    ),
    CONSTRAINT chk_execution_authorization_plan_sha CHECK (plan_or_release_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_execution_authorization_site_sha CHECK (site_fingerprint IS NULL OR site_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_execution_authorization_nonce_sha CHECK (nonce_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_execution_authorization_token_sha CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_execution_authorization_status CHECK (status IN ('active', 'consumed', 'revoked', 'expired')),
    CONSTRAINT chk_execution_authorization_window CHECK (expires_at > issued_at),
    CONSTRAINT chk_execution_authorization_consumed CHECK (
        (status = 'consumed' AND consumed_at IS NOT NULL AND consumed_by IS NOT NULL)
        OR status <> 'consumed'
    ),
    CONSTRAINT chk_execution_authorization_revoked CHECK (
        (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revocation_reason IS NOT NULL)
        OR status <> 'revoked'
    )
);

CREATE INDEX IF NOT EXISTS idx_execution_authorizations_active
    ON execution_authorizations(capability, target_type, target_id, expires_at)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS capability_flags (
    capability VARCHAR(64) NOT NULL,
    environment VARCHAR(64) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT false,
    kill_switch_active BOOLEAN NOT NULL DEFAULT true,
    policy_code VARCHAR(80),
    policy_revision INTEGER,
    changed_by VARCHAR(128) NOT NULL,
    reason TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (capability, environment),
    CONSTRAINT chk_capability_flag_policy_revision CHECK (policy_revision IS NULL OR policy_revision >= 1)
);

INSERT INTO capability_flags (capability, environment, enabled, kill_switch_active, changed_by, reason)
VALUES ('go_live', '*', false, true, 'system', 'Go-live is disabled until independent safety review')
ON CONFLICT (capability, environment) DO NOTHING;

CREATE TABLE IF NOT EXISTS releases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    release_code VARCHAR(80) NOT NULL UNIQUE,
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    subject_revision INTEGER NOT NULL,
    carrier_kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'candidate',
    current_manifest_revision INTEGER NOT NULL DEFAULT 0,
    release_fingerprint CHAR(64),
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    CONSTRAINT chk_release_subject_revision CHECK (subject_revision >= 1),
    CONSTRAINT chk_release_carrier CHECK (carrier_kind IN ('live_room_draft', 'rendered_video')),
    CONSTRAINT chk_release_status CHECK (
        status IN ('candidate', 'validating', 'awaiting_approval', 'approved', 'delivery_pending',
                   'delivered', 'delivery_failed', 'reconcile_required', 'revoked')
    ),
    CONSTRAINT chk_release_manifest_revision CHECK (current_manifest_revision >= 0),
    CONSTRAINT chk_release_fingerprint CHECK (release_fingerprint IS NULL OR release_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_releases_subject
    ON releases(subject_type, subject_code, subject_revision);

CREATE TABLE IF NOT EXISTS release_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manifest_code VARCHAR(96) NOT NULL UNIQUE,
    release_id UUID NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    release_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    schema_version VARCHAR(64) NOT NULL DEFAULT 'release-manifest.v1',
    carrier_kind VARCHAR(32) NOT NULL,
    subject_refs JSONB NOT NULL,
    artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    rights_snapshot JSONB NOT NULL,
    quality_snapshot JSONB NOT NULL,
    lineage_snapshot JSONB NOT NULL,
    carrier_facet JSONB NOT NULL,
    manifest_fingerprint CHAR(64) NOT NULL UNIQUE,
    signature_algorithm VARCHAR(32),
    signature_key_id VARCHAR(128),
    signature_value TEXT,
    sealed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (release_id, revision_number),
    CONSTRAINT chk_release_manifest_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_release_manifest_carrier CHECK (carrier_kind IN ('live_room_draft', 'rendered_video')),
    CONSTRAINT chk_release_manifest_subjects CHECK (jsonb_typeof(subject_refs) = 'object'),
    CONSTRAINT chk_release_manifest_artifacts CHECK (jsonb_typeof(artifact_refs) = 'array'),
    CONSTRAINT chk_release_manifest_rights CHECK (jsonb_typeof(rights_snapshot) = 'object'),
    CONSTRAINT chk_release_manifest_quality CHECK (jsonb_typeof(quality_snapshot) = 'object'),
    CONSTRAINT chk_release_manifest_lineage CHECK (jsonb_typeof(lineage_snapshot) = 'object'),
    CONSTRAINT chk_release_manifest_carrier_facet CHECK (jsonb_typeof(carrier_facet) = 'object'),
    CONSTRAINT chk_release_manifest_sha CHECK (manifest_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_release_manifest_signature CHECK (
        (signature_algorithm IS NULL AND signature_key_id IS NULL AND signature_value IS NULL)
        OR (signature_algorithm IS NOT NULL AND signature_key_id IS NOT NULL AND signature_value IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS release_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_code VARCHAR(80) NOT NULL UNIQUE,
    release_id UUID NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    manifest_id UUID NOT NULL REFERENCES release_manifests(id),
    decision VARCHAR(16) NOT NULL,
    structured_reason JSONB NOT NULL,
    approved_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    decided_by VARCHAR(128) NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_release_approval_decision CHECK (decision IN ('approve', 'reject', 'waive')),
    CONSTRAINT chk_release_approval_reason CHECK (jsonb_typeof(structured_reason) = 'object'),
    CONSTRAINT chk_release_approval_scope CHECK (jsonb_typeof(approved_scope) = 'object')
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_code VARCHAR(80) NOT NULL UNIQUE,
    release_id UUID NOT NULL REFERENCES releases(id),
    manifest_id UUID NOT NULL REFERENCES release_manifests(id),
    target_type VARCHAR(64) NOT NULL,
    target_id VARCHAR(255) NOT NULL,
    adapter_type VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    authorization_id UUID REFERENCES execution_authorizations(id),
    status VARCHAR(32) NOT NULL DEFAULT 'prepared',
    external_identity JSONB,
    request_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_summary JSONB,
    readback_evidence JSONB,
    error_code VARCHAR(64),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_type, target_id, idempotency_key),
    CONSTRAINT chk_delivery_status CHECK (
        status IN ('prepared', 'authorized', 'committing', 'succeeded', 'failed', 'reconcile_required', 'cancelled')
    ),
    CONSTRAINT chk_delivery_external_identity CHECK (external_identity IS NULL OR jsonb_typeof(external_identity) = 'object'),
    CONSTRAINT chk_delivery_request CHECK (jsonb_typeof(request_summary) = 'object'),
    CONSTRAINT chk_delivery_response CHECK (response_summary IS NULL OR jsonb_typeof(response_summary) = 'object'),
    CONSTRAINT chk_delivery_readback CHECK (readback_evidence IS NULL OR jsonb_typeof(readback_evidence) = 'object'),
    CONSTRAINT chk_delivery_terminal CHECK (
        (status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL)
        OR status NOT IN ('succeeded', 'failed', 'cancelled')
    )
);

CREATE TABLE IF NOT EXISTS release_status_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    release_id UUID NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    from_status VARCHAR(32),
    to_status VARCHAR(32) NOT NULL,
    actor_id VARCHAR(128),
    reason_code VARCHAR(64),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_release_history_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE TABLE IF NOT EXISTS content_exposure_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exposure_event_id UUID NOT NULL UNIQUE,
    schema_version VARCHAR(64) NOT NULL DEFAULT 'content-exposure-event.v1',
    source_system VARCHAR(64) NOT NULL,
    source_event_id VARCHAR(255) NOT NULL,
    release_manifest_id UUID NOT NULL REFERENCES release_manifests(id),
    live_session_code VARCHAR(80) NOT NULL,
    external_session_id VARCHAR(255),
    exposed_content_type VARCHAR(64) NOT NULL,
    exposed_content_code VARCHAR(128) NOT NULL,
    exposed_content_revision INTEGER NOT NULL,
    start_ms BIGINT NOT NULL,
    end_ms BIGINT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    processing_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    time_mapping_revision VARCHAR(128),
    source_evidence JSONB NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL DEFAULT 1,
    tombstone BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_system, source_event_id),
    CONSTRAINT chk_exposure_revision CHECK (exposed_content_revision >= 1),
    CONSTRAINT chk_exposure_interval CHECK (start_ms >= 0 AND end_ms > start_ms),
    CONSTRAINT chk_exposure_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT chk_exposure_evidence CHECK (jsonb_typeof(source_evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_exposure_release_time
    ON content_exposure_events(release_manifest_id, event_time);
CREATE INDEX IF NOT EXISTS idx_exposure_session_interval
    ON content_exposure_events(live_session_code, start_ms, end_ms);

CREATE TABLE IF NOT EXISTS metric_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_code VARCHAR(80) NOT NULL UNIQUE,
    owner_principal VARCHAR(128) NOT NULL,
    current_revision_number INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_metric_definition_revision CHECK (current_revision_number >= 0),
    CONSTRAINT chk_metric_definition_status CHECK (status IN ('draft', 'active', 'deprecated', 'retired'))
);

CREATE TABLE IF NOT EXISTS metric_definition_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_id UUID NOT NULL REFERENCES metric_definitions(id) ON DELETE CASCADE,
    metric_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    unit VARCHAR(64) NOT NULL,
    value_type VARCHAR(32) NOT NULL,
    aggregation VARCHAR(32) NOT NULL,
    numerator_expression TEXT,
    denominator_expression TEXT,
    dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    event_contract_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    effective_at TIMESTAMPTZ,
    deprecated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (metric_id, revision_number),
    UNIQUE (metric_code, revision_number),
    CONSTRAINT chk_metric_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_metric_revision_status CHECK (status IN ('draft', 'active', 'superseded', 'deprecated')),
    CONSTRAINT chk_metric_revision_value CHECK (value_type IN ('integer', 'decimal', 'duration_ms', 'currency', 'ratio')),
    CONSTRAINT chk_metric_revision_aggregation CHECK (aggregation IN ('sum', 'count', 'min', 'max', 'average', 'ratio', 'last')),
    CONSTRAINT chk_metric_revision_dimensions CHECK (jsonb_typeof(dimensions) = 'array'),
    CONSTRAINT chk_metric_revision_contracts CHECK (jsonb_typeof(event_contract_refs) = 'array'),
    CONSTRAINT chk_metric_revision_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS data_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    owner_principal VARCHAR(128) NOT NULL,
    source_system VARCHAR(64) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    json_schema JSONB NOT NULL,
    event_id_path VARCHAR(255) NOT NULL,
    event_time_path VARCHAR(255),
    operation_path VARCHAR(255),
    upsert_delete_semantics JSONB NOT NULL,
    lateness_policy JSONB NOT NULL,
    compatibility_window JSONB NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contract_code, revision_number),
    CONSTRAINT chk_data_contract_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_data_contract_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_data_contract_schema CHECK (jsonb_typeof(json_schema) = 'object'),
    CONSTRAINT chk_data_contract_upsert CHECK (jsonb_typeof(upsert_delete_semantics) = 'object'),
    CONSTRAINT chk_data_contract_lateness CHECK (jsonb_typeof(lateness_policy) = 'object'),
    CONSTRAINT chk_data_contract_compat CHECK (jsonb_typeof(compatibility_window) = 'object'),
    CONSTRAINT chk_data_contract_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS standard_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL UNIQUE,
    source_system VARCHAR(64) NOT NULL,
    source_event_id VARCHAR(255) NOT NULL,
    contract_id UUID NOT NULL REFERENCES data_contracts(id),
    operation VARCHAR(16) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    processing_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB NOT NULL,
    payload_fingerprint CHAR(64) NOT NULL,
    tombstone BOOLEAN NOT NULL DEFAULT false,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'accepted',
    quarantine_reason VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_system, source_event_id),
    CONSTRAINT chk_standard_event_operation CHECK (operation IN ('insert', 'upsert', 'delete')),
    CONSTRAINT chk_standard_event_payload CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT chk_standard_event_sha CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_standard_event_quality CHECK (quality_status IN ('accepted', 'quarantined', 'rejected'))
);

CREATE TABLE IF NOT EXISTS attribution_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attribution_run_code VARCHAR(80) NOT NULL UNIQUE,
    schema_version VARCHAR(64) NOT NULL DEFAULT 'attribution-run.v1',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    release_manifest_refs JSONB NOT NULL,
    exposure_snapshot_ref VARCHAR(128) NOT NULL,
    metric_revision_refs JSONB NOT NULL,
    data_contract_refs JSONB NOT NULL,
    method VARCHAR(64) NOT NULL,
    evidence_level VARCHAR(32) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    cutoff_event_time TIMESTAMPTZ NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT chk_attribution_status CHECK (status IN ('draft', 'running', 'succeeded', 'failed', 'superseded', 'revoked')),
    CONSTRAINT chk_attribution_releases CHECK (jsonb_typeof(release_manifest_refs) = 'array'),
    CONSTRAINT chk_attribution_metrics CHECK (jsonb_typeof(metric_revision_refs) = 'array'),
    CONSTRAINT chk_attribution_contracts CHECK (jsonb_typeof(data_contract_refs) = 'array'),
    CONSTRAINT chk_attribution_evidence CHECK (
        evidence_level IN ('descriptive', 'associational', 'quasi_experimental', 'randomized')
    ),
    CONSTRAINT chk_attribution_input_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS attribution_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_code VARCHAR(80) NOT NULL UNIQUE,
    run_id UUID NOT NULL REFERENCES attribution_runs(id) ON DELETE CASCADE,
    target_type VARCHAR(64) NOT NULL,
    target_code VARCHAR(128) NOT NULL,
    target_revision INTEGER NOT NULL,
    metric_code VARCHAR(80) NOT NULL,
    metric_revision INTEGER NOT NULL,
    estimate NUMERIC,
    interval_lower NUMERIC,
    interval_upper NUMERIC,
    sample_size BIGINT NOT NULL DEFAULT 0,
    evidence_level VARCHAR(32) NOT NULL,
    quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    result_fingerprint CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_attribution_result_revision CHECK (target_revision >= 1 AND metric_revision >= 1),
    CONSTRAINT chk_attribution_result_sample CHECK (sample_size >= 0),
    CONSTRAINT chk_attribution_result_evidence CHECK (
        evidence_level IN ('descriptive', 'associational', 'quasi_experimental', 'randomized')
    ),
    CONSTRAINT chk_attribution_result_quality CHECK (jsonb_typeof(quality_flags) = 'array'),
    CONSTRAINT chk_attribution_result_sha CHECK (result_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS performance_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    subject_revision INTEGER NOT NULL,
    context JSONB NOT NULL,
    descriptive_metrics JSONB NOT NULL,
    source_result_refs JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (profile_code, revision_number),
    CONSTRAINT chk_performance_profile_revision CHECK (revision_number >= 1 AND subject_revision >= 1),
    CONSTRAINT chk_performance_profile_context CHECK (jsonb_typeof(context) = 'object'),
    CONSTRAINT chk_performance_profile_metrics CHECK (jsonb_typeof(descriptive_metrics) = 'object'),
    CONSTRAINT chk_performance_profile_sources CHECK (jsonb_typeof(source_result_refs) = 'array'),
    CONSTRAINT chk_performance_profile_status CHECK (status IN ('draft', 'published', 'superseded', 'revoked')),
    CONSTRAINT chk_performance_profile_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS effect_estimates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    estimate_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    estimate_kind VARCHAR(32) NOT NULL,
    evidence_level VARCHAR(32) NOT NULL,
    attribution_result_id UUID NOT NULL REFERENCES attribution_results(id),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    estimate_payload JSONB NOT NULL,
    eligibility_snapshot JSONB NOT NULL,
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (estimate_code, revision_number),
    CONSTRAINT chk_effect_estimate_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_effect_estimate_kind CHECK (estimate_kind IN ('associational', 'causal')),
    CONSTRAINT chk_effect_estimate_evidence CHECK (
        evidence_level IN ('associational', 'quasi_experimental', 'randomized')
    ),
    CONSTRAINT chk_effect_estimate_status CHECK (status IN ('draft', 'reviewed', 'approved', 'superseded', 'revoked')),
    CONSTRAINT chk_effect_estimate_payload CHECK (jsonb_typeof(estimate_payload) = 'object'),
    CONSTRAINT chk_effect_estimate_eligibility CHECK (jsonb_typeof(eligibility_snapshot) = 'object'),
    CONSTRAINT chk_effect_estimate_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_effect_estimate_approval CHECK (
        (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR status <> 'approved'
    )
);

CREATE TABLE IF NOT EXISTS feature_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_code VARCHAR(80) NOT NULL UNIQUE,
    entity_type VARCHAR(64) NOT NULL,
    entity_code VARCHAR(128) NOT NULL,
    as_of_event_time TIMESTAMPTZ NOT NULL,
    definition_revision VARCHAR(128) NOT NULL,
    features JSONB NOT NULL,
    source_event_watermark TIMESTAMPTZ NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_feature_snapshot_features CHECK (jsonb_typeof(features) = 'object'),
    CONSTRAINT chk_feature_snapshot_time CHECK (source_event_watermark <= as_of_event_time),
    CONSTRAINT chk_feature_snapshot_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS decision_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_log_code VARCHAR(80) NOT NULL UNIQUE,
    decision_type VARCHAR(64) NOT NULL,
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    subject_revision INTEGER NOT NULL,
    feature_snapshot_id UUID REFERENCES feature_snapshots(id),
    policy_code VARCHAR(80) NOT NULL,
    policy_revision INTEGER NOT NULL,
    candidates JSONB NOT NULL,
    selected JSONB NOT NULL,
    propensity JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    decided_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_decision_log_subject_revision CHECK (subject_revision >= 1),
    CONSTRAINT chk_decision_log_policy_revision CHECK (policy_revision >= 1),
    CONSTRAINT chk_decision_log_candidates CHECK (jsonb_typeof(candidates) = 'array'),
    CONSTRAINT chk_decision_log_selected CHECK (jsonb_typeof(selected) = 'object'),
    CONSTRAINT chk_decision_log_propensity CHECK (jsonb_typeof(propensity) = 'object'),
    CONSTRAINT chk_decision_log_evidence CHECK (jsonb_typeof(evidence_refs) = 'array')
);

CREATE TABLE IF NOT EXISTS learning_policy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    minimum_evidence_level VARCHAR(32) NOT NULL,
    policy JSONB NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (policy_code, revision_number),
    CONSTRAINT chk_learning_policy_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_learning_policy_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_learning_policy_evidence CHECK (
        minimum_evidence_level IN ('descriptive', 'associational', 'quasi_experimental', 'randomized')
    ),
    CONSTRAINT chk_learning_policy_payload CHECK (jsonb_typeof(policy) = 'object'),
    CONSTRAINT chk_learning_policy_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS effect_eligibility_policy_versions (
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
    CONSTRAINT chk_effect_eligibility_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_effect_eligibility_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_effect_eligibility_rules CHECK (jsonb_typeof(rules) = 'object'),
    CONSTRAINT chk_effect_eligibility_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS retention_policy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    data_class VARCHAR(64) NOT NULL,
    retention_days INTEGER,
    legal_basis VARCHAR(255) NOT NULL,
    deletion_behavior JSONB NOT NULL,
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (policy_code, revision_number),
    CONSTRAINT chk_retention_policy_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_retention_policy_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_retention_policy_days CHECK (retention_days IS NULL OR retention_days >= 0),
    CONSTRAINT chk_retention_policy_behavior CHECK (jsonb_typeof(deletion_behavior) = 'object')
);

CREATE TABLE IF NOT EXISTS legal_holds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hold_code VARCHAR(80) NOT NULL UNIQUE,
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    scope JSONB NOT NULL,
    reason TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    owner_principal VARCHAR(128) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    released_at TIMESTAMPTZ,
    released_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_legal_hold_scope CHECK (jsonb_typeof(scope) = 'object'),
    CONSTRAINT chk_legal_hold_evidence CHECK (jsonb_typeof(evidence_refs) = 'array'),
    CONSTRAINT chk_legal_hold_window CHECK (expires_at IS NULL OR expires_at > effective_at)
);

CREATE TABLE IF NOT EXISTS deletion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deletion_run_code VARCHAR(80) NOT NULL UNIQUE,
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'requested',
    requested_scope JSONB NOT NULL,
    legal_hold_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    requested_by VARCHAR(128) NOT NULL,
    approved_by VARCHAR(128),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_summary TEXT,
    CONSTRAINT chk_deletion_run_status CHECK (
        status IN ('requested', 'validating', 'legal_hold', 'approved', 'executing', 'verifying', 'completed', 'partial_failed', 'rejected')
    ),
    CONSTRAINT chk_deletion_run_scope CHECK (jsonb_typeof(requested_scope) = 'object'),
    CONSTRAINT chk_deletion_run_holds CHECK (jsonb_typeof(legal_hold_snapshot) = 'array')
);

CREATE TABLE IF NOT EXISTS deletion_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deletion_run_id UUID NOT NULL REFERENCES deletion_runs(id) ON DELETE CASCADE,
    processor VARCHAR(64) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_code VARCHAR(255) NOT NULL,
    outcome VARCHAR(32) NOT NULL,
    retention_basis VARCHAR(255),
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (deletion_run_id, processor, target_type, target_code),
    CONSTRAINT chk_deletion_receipt_outcome CHECK (outcome IN ('deleted', 'tombstoned', 'retained_legal_hold', 'not_found', 'failed')),
    CONSTRAINT chk_deletion_receipt_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE TABLE IF NOT EXISTS data_tombstones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(255) NOT NULL,
    source_system VARCHAR(64) NOT NULL,
    deletion_run_id UUID NOT NULL REFERENCES deletion_runs(id),
    reason_code VARCHAR(64) NOT NULL,
    tombstoned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subject_type, subject_code, source_system)
);

CREATE TABLE IF NOT EXISTS external_processor_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processor_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    purposes JSONB NOT NULL,
    data_classes JSONB NOT NULL,
    region VARCHAR(128),
    retention_terms TEXT,
    credential_owner VARCHAR(128) NOT NULL,
    rotation_policy VARCHAR(255) NOT NULL,
    minimum_fields JSONB NOT NULL,
    exit_plan TEXT NOT NULL,
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (processor_code, revision_number),
    CONSTRAINT chk_external_processor_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_external_processor_status CHECK (status IN ('draft', 'active', 'superseded', 'retired')),
    CONSTRAINT chk_external_processor_purposes CHECK (jsonb_typeof(purposes) = 'array'),
    CONSTRAINT chk_external_processor_classes CHECK (jsonb_typeof(data_classes) = 'array'),
    CONSTRAINT chk_external_processor_fields CHECK (jsonb_typeof(minimum_fields) = 'object')
);

DROP TRIGGER IF EXISTS trg_policy_decisions_append_only ON policy_decisions;
CREATE TRIGGER trg_policy_decisions_append_only
BEFORE UPDATE OR DELETE ON policy_decisions
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_release_manifests_append_only ON release_manifests;
CREATE TRIGGER trg_release_manifests_append_only
BEFORE UPDATE OR DELETE ON release_manifests
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_release_approvals_append_only ON release_approvals;
CREATE TRIGGER trg_release_approvals_append_only
BEFORE UPDATE OR DELETE ON release_approvals
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_release_history_append_only ON release_status_history;
CREATE TRIGGER trg_release_history_append_only
BEFORE UPDATE OR DELETE ON release_status_history
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_content_exposure_append_only ON content_exposure_events;
CREATE TRIGGER trg_content_exposure_append_only
BEFORE UPDATE OR DELETE ON content_exposure_events
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_standard_events_append_only ON standard_events;
CREATE TRIGGER trg_standard_events_append_only
BEFORE UPDATE OR DELETE ON standard_events
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_attribution_results_append_only ON attribution_results;
CREATE TRIGGER trg_attribution_results_append_only
BEFORE UPDATE OR DELETE ON attribution_results
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_decision_logs_append_only ON decision_logs;
CREATE TRIGGER trg_decision_logs_append_only
BEFORE UPDATE OR DELETE ON decision_logs
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_deletion_receipts_append_only ON deletion_receipts;
CREATE TRIGGER trg_deletion_receipts_append_only
BEFORE UPDATE OR DELETE ON deletion_receipts
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

DROP TRIGGER IF EXISTS trg_data_tombstones_append_only ON data_tombstones;
CREATE TRIGGER trg_data_tombstones_append_only
BEFORE UPDATE OR DELETE ON data_tombstones
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

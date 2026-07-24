-- Least-privilege policy baseline and auditable protected-resource registry.

INSERT INTO capability_policy_versions (
    policy_code, revision_number, status, rules, fingerprint_sha256,
    approved_by, approved_at
)
VALUES (
    'baseline-least-privilege',
    1,
    'active',
    '{
      "schema_version": "capability-policy.v1",
      "role_capabilities": {
        "production_editor": ["edit_production"],
        "fact_publisher": ["publish_fact"],
        "template_publisher": ["publish_template"],
        "effect_approver": ["approve_effect"],
        "draft_writer": ["write_draft"],
        "asset_uploader": ["upload_asset"],
        "release_deliverer": ["deliver_release"],
        "graph_operator": ["rebuild_projection"],
        "broadcast_operator": ["go_live"]
      },
      "required_approval_count": {
        "publish_fact": 1,
        "publish_template": 1,
        "approve_effect": 1,
        "deliver_release": 1,
        "go_live": 2
      },
      "separation_of_duties": {
        "release_creator_cannot_deliver": true,
        "effect_producer_cannot_approve": true,
        "broadcast_requester_cannot_self_approve": true
      }
    }'::jsonb,
    encode(digest(convert_to('baseline-least-privilege.v1', 'UTF8'), 'sha256'), 'hex'),
    'system-security-baseline',
    now()
)
ON CONFLICT (policy_code, revision_number) DO NOTHING;

INSERT INTO protected_resources (
    resource_type, resource_id, protection_mode, allowed_capabilities,
    reason_code, evidence, created_by
)
SELECT 'maitu_room', room_id, 'read_only', '[]'::jsonb,
       'REFERENCE_ROOM_READ_ONLY',
       jsonb_build_object(
           'source', 'maitu-reference-room-baseline',
           'system_locked', true,
           'registered_by_migration', '037'
       ),
       'system-security-baseline'
FROM unnest(ARRAY['38336', '38995']) AS room_id
ON CONFLICT (resource_type, resource_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS protected_resource_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protected_resource_id UUID NOT NULL REFERENCES protected_resources(id),
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    revision INTEGER NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    protection_mode VARCHAR(32),
    allowed_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason_code VARCHAR(64) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_id VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (protected_resource_id, revision),
    CONSTRAINT chk_protected_resource_event_revision CHECK (revision >= 1),
    CONSTRAINT chk_protected_resource_event_type CHECK (event_type IN ('registered', 'updated', 'revoked')),
    CONSTRAINT chk_protected_resource_event_mode CHECK (
        protection_mode IS NULL OR protection_mode IN ('read_only', 'deny_write', 'allowlisted_write')
    ),
    CONSTRAINT chk_protected_resource_event_capabilities CHECK (
        jsonb_typeof(allowed_capabilities) = 'array'
    ),
    CONSTRAINT chk_protected_resource_event_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

INSERT INTO protected_resource_events (
    protected_resource_id, resource_type, resource_id, revision, event_type,
    protection_mode, allowed_capabilities, reason_code, evidence, actor_id
)
SELECT resource.id, resource.resource_type, resource.resource_id, 1, 'registered',
       resource.protection_mode, resource.allowed_capabilities,
       resource.reason_code, resource.evidence, resource.created_by
FROM protected_resources AS resource
WHERE NOT EXISTS (
    SELECT 1 FROM protected_resource_events AS event
    WHERE event.protected_resource_id = resource.id
);

DROP TRIGGER IF EXISTS trg_protected_resource_events_append_only ON protected_resource_events;
CREATE TRIGGER trg_protected_resource_events_append_only
BEFORE UPDATE OR DELETE ON protected_resource_events
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

CREATE INDEX IF NOT EXISTS idx_protected_resource_events_subject
    ON protected_resource_events(resource_type, resource_id, revision DESC);

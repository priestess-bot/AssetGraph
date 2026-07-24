-- Fail-closed defaults for every privileged capability. Environment-specific
-- activation is an explicit operational action and go_live remains hard-disabled.

INSERT INTO capability_flags (
    capability, environment, enabled, kill_switch_active, changed_by, reason
)
SELECT capability, '*', false, true, 'system', 'Disabled until an approved environment policy enables the capability'
FROM unnest(ARRAY[
    'edit_production',
    'publish_fact',
    'publish_template',
    'approve_effect',
    'write_draft',
    'upload_asset',
    'deliver_release',
    'rebuild_projection'
]) AS capability
ON CONFLICT (capability, environment) DO NOTHING;

UPDATE capability_flags
SET enabled = false,
    kill_switch_active = true,
    reason = 'Go-live is hard-disabled until independent safety review',
    updated_at = now()
WHERE capability = 'go_live' AND environment = '*';

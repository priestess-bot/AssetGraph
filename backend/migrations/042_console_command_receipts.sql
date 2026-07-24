BEGIN;

CREATE TABLE IF NOT EXISTS console_command_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_code VARCHAR(80) NOT NULL UNIQUE,
    command_type VARCHAR(32) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_code VARCHAR(128) NOT NULL,
    requested_entity_revision INTEGER,
    idempotency_key VARCHAR(128) NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    result_status VARCHAR(32) NOT NULL,
    result_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (command_type, entity_type, entity_code, idempotency_key),
    CONSTRAINT chk_console_command_type CHECK (command_type IN (
        'confirm', 'publish', 'approve', 'reject', 'authorize'
    )),
    CONSTRAINT chk_console_command_requested_revision CHECK (
        requested_entity_revision IS NULL OR requested_entity_revision >= 1
    ),
    CONSTRAINT chk_console_command_status CHECK (result_status IN ('succeeded', 'issued')),
    CONSTRAINT chk_console_command_payload CHECK (jsonb_typeof(result_payload) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_console_command_receipts_entity
    ON console_command_receipts(entity_type, entity_code, created_at DESC);

DROP TRIGGER IF EXISTS trg_console_command_receipts_append_only ON console_command_receipts;
CREATE TRIGGER trg_console_command_receipts_append_only
BEFORE UPDATE OR DELETE ON console_command_receipts
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();

COMMIT;

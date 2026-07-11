-- Freeze authoritative Maitu retry mutation targets without storing credentials.
-- Partial rows remain valid for incremental authoring; operation-plan generation
-- keeps them blocked until every required field is complete and consistent.

ALTER TABLE maitu_replacement_plans
    ADD COLUMN IF NOT EXISTS target_live_room_id VARCHAR(64);

ALTER TABLE maitu_material_slots
    ADD COLUMN IF NOT EXISTS target_live_room_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS target_clip_id BIGINT,
    ADD COLUMN IF NOT EXISTS target_layer_id BIGINT,
    ADD COLUMN IF NOT EXISTS expected_before_state JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_maitu_material_slots_target_clip_positive'
    ) THEN
        ALTER TABLE maitu_material_slots
            ADD CONSTRAINT chk_maitu_material_slots_target_clip_positive
            CHECK (target_clip_id IS NULL OR target_clip_id > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_maitu_material_slots_target_layer_positive'
    ) THEN
        ALTER TABLE maitu_material_slots
            ADD CONSTRAINT chk_maitu_material_slots_target_layer_positive
            CHECK (target_layer_id IS NULL OR target_layer_id > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_maitu_material_slots_before_state_object'
    ) THEN
        ALTER TABLE maitu_material_slots
            ADD CONSTRAINT chk_maitu_material_slots_before_state_object
            CHECK (jsonb_typeof(expected_before_state) = 'object');
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plans_target_room
    ON maitu_replacement_plans(target_live_room_id);

CREATE INDEX IF NOT EXISTS idx_maitu_material_slots_target_room
    ON maitu_material_slots(target_live_room_id);

CREATE INDEX IF NOT EXISTS idx_maitu_material_slots_target_clip
    ON maitu_material_slots(target_clip_id);

CREATE INDEX IF NOT EXISTS idx_maitu_material_slots_target_layer
    ON maitu_material_slots(target_layer_id);

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS maitu_binding_verification_source VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_binding_verified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS maitu_binding_scope VARCHAR(128);

CREATE TABLE IF NOT EXISTS maitu_retry_operation_intents (
    retry_task_code VARCHAR(64) NOT NULL
        REFERENCES maitu_execution_retry_tasks(retry_task_code),
    operation_key VARCHAR(128) NOT NULL,
    contract_version VARCHAR(32) NOT NULL,
    operation_type VARCHAR(64) NOT NULL,
    target_app VARCHAR(32) NOT NULL,
    intent_fingerprint VARCHAR(64) NOT NULL,
    intent_payload JSONB NOT NULL,
    readiness_status VARCHAR(32) NOT NULL,
    blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (retry_task_code, operation_key),
    CONSTRAINT chk_maitu_retry_intents_contract_version
        CHECK (contract_version = 'maitu-retry-mutation-v1'),
    CONSTRAINT chk_maitu_retry_intents_operation_type
        CHECK (operation_type IN (
            'retry_replace_layer_asset',
            'retry_asset_upload_and_replace',
            'retry_save_project',
            'recover_login_then_retry',
            'retry_browser_use_operation'
        )),
    CONSTRAINT chk_maitu_retry_intents_target_app
        CHECK (target_app = 'maitu'),
    CONSTRAINT chk_maitu_retry_intents_fingerprint
        CHECK (intent_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_retry_intents_payload_object
        CHECK (jsonb_typeof(intent_payload) = 'object'),
    CONSTRAINT chk_maitu_retry_intents_readiness
        CHECK (readiness_status IN ('ready', 'blocked')),
    CONSTRAINT chk_maitu_retry_intents_blocked_reasons_array
        CHECK (jsonb_typeof(blocked_reasons) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_maitu_retry_operation_intents_readiness
    ON maitu_retry_operation_intents(readiness_status, operation_type);

CREATE OR REPLACE FUNCTION reject_maitu_retry_operation_intent_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'maitu retry operation intents are immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_maitu_retry_operation_intents_immutable
    ON maitu_retry_operation_intents;

CREATE TRIGGER trg_maitu_retry_operation_intents_immutable
BEFORE UPDATE OR DELETE ON maitu_retry_operation_intents
FOR EACH ROW
EXECUTE FUNCTION reject_maitu_retry_operation_intent_mutation();

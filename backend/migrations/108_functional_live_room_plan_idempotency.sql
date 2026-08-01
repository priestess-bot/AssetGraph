-- Make the unified product command resumable without duplicating a live-room plan.

ALTER TABLE functional_live_room_plans
    ADD COLUMN IF NOT EXISTS creation_idempotency_key VARCHAR(128),
    ADD COLUMN IF NOT EXISTS creation_input_fingerprint CHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS idx_functional_live_room_plan_creation_idempotency
    ON functional_live_room_plans(creation_idempotency_key)
    WHERE creation_idempotency_key IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_functional_live_room_plan_creation_idempotency_pair'
          AND conrelid = 'functional_live_room_plans'::regclass
    ) THEN
        ALTER TABLE functional_live_room_plans
            ADD CONSTRAINT chk_functional_live_room_plan_creation_idempotency_pair CHECK (
                (creation_idempotency_key IS NULL AND creation_input_fingerprint IS NULL)
                OR (
                    creation_idempotency_key IS NOT NULL
                    AND btrim(creation_idempotency_key) <> ''
                    AND creation_input_fingerprint ~ '^[0-9a-f]{64}$'
                )
            );
    END IF;
END $$;

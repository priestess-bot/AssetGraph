-- Revocation is an explicit, attributable lifecycle transition. It prevents
-- subsequent approval/reproduction without changing drafts already created from
-- the immutable effect snapshot.

ALTER TABLE functional_effect_estimates
    ADD COLUMN IF NOT EXISTS revoked_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;

ALTER TABLE functional_effect_estimates
    ADD CONSTRAINT chk_functional_effect_revocation_details CHECK (
        status <> 'revoked'
        OR (
            revoked_by IS NOT NULL
            AND revoked_at IS NOT NULL
            AND revoked_reason IS NOT NULL
            AND length(btrim(revoked_reason)) > 0
        )
    ) NOT VALID;

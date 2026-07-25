-- Preserve a local revocation decision without deleting evidence or claims
-- already referenced by immutable content-project revisions.

ALTER TABLE functional_knowledge_source_evidences
    ADD COLUMN IF NOT EXISTS revoked_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;

ALTER TABLE functional_knowledge_fact_claims
    ADD COLUMN IF NOT EXISTS revoked_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;

ALTER TABLE functional_knowledge_source_evidences
    ADD CONSTRAINT chk_functional_knowledge_evidence_revocation_details CHECK (
        status <> 'revoked'
        OR (
            revoked_by IS NOT NULL
            AND length(btrim(revoked_by)) > 0
            AND revoked_at IS NOT NULL
            AND revoked_reason IS NOT NULL
            AND length(btrim(revoked_reason)) > 0
        )
    ) NOT VALID;

ALTER TABLE functional_knowledge_fact_claims
    ADD CONSTRAINT chk_functional_knowledge_claim_revocation_details CHECK (
        status <> 'revoked'
        OR (
            revoked_by IS NOT NULL
            AND length(btrim(revoked_by)) > 0
            AND revoked_at IS NOT NULL
            AND revoked_reason IS NOT NULL
            AND length(btrim(revoked_reason)) > 0
        )
    ) NOT VALID;

-- Preserve a local draft-review rejection without deleting its source,
-- citation, or previously recorded lifecycle context.

ALTER TABLE functional_knowledge_source_evidences
    ADD COLUMN IF NOT EXISTS rejected_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

ALTER TABLE functional_knowledge_fact_claims
    ADD COLUMN IF NOT EXISTS rejected_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- Claims create local facts in draft state. Both rejection and the pre-existing
-- revocation workflow need their terminal statuses to remain representable.
ALTER TABLE functional_knowledge_facts
    DROP CONSTRAINT IF EXISTS chk_functional_fact_status;

ALTER TABLE functional_knowledge_facts
    ADD CONSTRAINT chk_functional_fact_status CHECK (
        status IN ('approved', 'draft', 'rejected', 'revoked', 'superseded')
    ) NOT VALID;

ALTER TABLE functional_knowledge_source_evidences
    ADD CONSTRAINT chk_functional_knowledge_evidence_rejection_details CHECK (
        status <> 'rejected'
        OR (
            rejected_by IS NOT NULL
            AND length(btrim(rejected_by)) > 0
            AND rejected_at IS NOT NULL
            AND rejection_reason IS NOT NULL
            AND length(btrim(rejection_reason)) > 0
        )
    ) NOT VALID;

ALTER TABLE functional_knowledge_fact_claims
    ADD CONSTRAINT chk_functional_knowledge_claim_rejection_details CHECK (
        status <> 'rejected'
        OR (
            rejected_by IS NOT NULL
            AND length(btrim(rejected_by)) > 0
            AND rejected_at IS NOT NULL
            AND rejection_reason IS NOT NULL
            AND length(btrim(rejection_reason)) > 0
        )
    ) NOT VALID;

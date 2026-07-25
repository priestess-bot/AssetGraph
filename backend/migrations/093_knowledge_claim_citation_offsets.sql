-- New claims retain the exact cited span in the locally captured evidence text.
-- Historical claims remain readable with a null span instead of invented offsets.

ALTER TABLE functional_knowledge_fact_claims
    ADD COLUMN IF NOT EXISTS citation_start_offset INTEGER,
    ADD COLUMN IF NOT EXISTS citation_end_offset INTEGER;

ALTER TABLE functional_knowledge_fact_claims
    ADD CONSTRAINT chk_functional_knowledge_claim_citation_offsets CHECK (
        (citation_start_offset IS NULL AND citation_end_offset IS NULL)
        OR (
            citation_start_offset IS NOT NULL
            AND citation_end_offset IS NOT NULL
            AND citation_start_offset >= 0
            AND citation_end_offset > citation_start_offset
        )
    ) NOT VALID;

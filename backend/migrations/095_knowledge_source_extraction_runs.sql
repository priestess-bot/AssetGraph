-- A SourceEvidence excerpt is the immutable output of a local capture/extraction run.
-- Remote connectors can later add strategies without changing this provenance contract.

CREATE TABLE IF NOT EXISTS functional_knowledge_source_extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_code VARCHAR(64) NOT NULL UNIQUE,
    evidence_code VARCHAR(64) NOT NULL
        REFERENCES functional_knowledge_source_evidences(evidence_code) ON DELETE RESTRICT,
    extractor_strategy_ref VARCHAR(128) NOT NULL,
    input_fingerprint_sha256 CHAR(64) NOT NULL,
    output_checksum_sha256 CHAR(64) NOT NULL,
    extraction_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_knowledge_extraction_strategy
        CHECK (length(btrim(extractor_strategy_ref)) > 0),
    CONSTRAINT chk_functional_knowledge_extraction_input_fingerprint
        CHECK (input_fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_functional_knowledge_extraction_output_checksum
        CHECK (output_checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_functional_knowledge_extraction_metadata
        CHECK (jsonb_typeof(extraction_metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_functional_knowledge_extraction_runs_evidence
    ON functional_knowledge_source_extraction_runs(evidence_code, created_at DESC);

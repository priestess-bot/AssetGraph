-- Local, reviewable knowledge evidence. Source acquisition remains outside this schema.

CREATE TABLE IF NOT EXISTS functional_knowledge_source_evidences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_code VARCHAR(64) NOT NULL UNIQUE,
    source_type VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    source_url TEXT,
    excerpt TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    captured_at TIMESTAMPTZ,
    access_scope VARCHAR(64) NOT NULL DEFAULT 'internal',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_by VARCHAR(128),
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_knowledge_evidence_type CHECK (source_type IN ('human', 'document', 'webpage', 'export')),
    CONSTRAINT chk_functional_knowledge_evidence_status CHECK (status IN ('draft', 'approved', 'rejected', 'revoked')),
    CONSTRAINT chk_functional_knowledge_evidence_checksum CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
);

ALTER TABLE functional_knowledge_facts
    ADD COLUMN IF NOT EXISTS source_evidence_code VARCHAR(64)
    REFERENCES functional_knowledge_source_evidences(evidence_code);

CREATE INDEX IF NOT EXISTS idx_functional_knowledge_facts_source_evidence
    ON functional_knowledge_facts(source_evidence_code)
    WHERE source_evidence_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS functional_knowledge_fact_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_code VARCHAR(64) NOT NULL UNIQUE,
    fact_code VARCHAR(64) NOT NULL REFERENCES functional_knowledge_facts(fact_code) ON DELETE CASCADE,
    source_evidence_code VARCHAR(64) NOT NULL REFERENCES functional_knowledge_source_evidences(evidence_code),
    field_path VARCHAR(255),
    claim TEXT NOT NULL,
    citation_excerpt TEXT NOT NULL,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_by VARCHAR(128),
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_knowledge_claim_status CHECK (status IN ('draft', 'approved', 'rejected', 'revoked')),
    CONSTRAINT chk_functional_knowledge_claim_window CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from),
    CONSTRAINT chk_functional_knowledge_claim_fingerprint CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_functional_knowledge_claims_fact
    ON functional_knowledge_fact_claims(fact_code, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_functional_knowledge_claims_evidence
    ON functional_knowledge_fact_claims(source_evidence_code, created_at DESC);

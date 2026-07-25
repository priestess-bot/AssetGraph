-- Content knowledge is reviewed separately from product facts and claims.

CREATE TABLE IF NOT EXISTS functional_knowledge_content_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_code VARCHAR(64) NOT NULL UNIQUE,
    rule_kind VARCHAR(32) NOT NULL,
    directive VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    rule_text TEXT NOT NULL,
    scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_evidence_code VARCHAR(64) REFERENCES functional_knowledge_source_evidences(evidence_code),
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_by VARCHAR(128),
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    revoked_by VARCHAR(128),
    revoked_at TIMESTAMPTZ,
    revoked_reason TEXT,
    rejected_by VARCHAR(128),
    rejected_at TIMESTAMPTZ,
    rejection_reason TEXT,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_knowledge_content_rule_kind CHECK (
        rule_kind IN ('content_guidance', 'compliance_rule', 'term', 'expression_ban')
    ),
    CONSTRAINT chk_functional_knowledge_content_rule_directive CHECK (
        directive IN ('guidance', 'must_include', 'must_avoid')
    ),
    CONSTRAINT chk_functional_knowledge_content_rule_expression_ban CHECK (
        rule_kind <> 'expression_ban' OR directive = 'must_avoid'
    ),
    CONSTRAINT chk_functional_knowledge_content_rule_scope CHECK (jsonb_typeof(scope) = 'object'),
    CONSTRAINT chk_functional_knowledge_content_rule_window CHECK (
        valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from
    ),
    CONSTRAINT chk_functional_knowledge_content_rule_status CHECK (
        status IN ('draft', 'approved', 'rejected', 'revoked')
    ),
    CONSTRAINT chk_functional_knowledge_content_rule_fingerprint CHECK (
        fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_functional_knowledge_content_rule_revocation CHECK (
        status <> 'revoked' OR (
            revoked_by IS NOT NULL AND length(btrim(revoked_by)) > 0
            AND revoked_at IS NOT NULL
            AND revoked_reason IS NOT NULL AND length(btrim(revoked_reason)) > 0
        )
    ),
    CONSTRAINT chk_functional_knowledge_content_rule_rejection CHECK (
        status <> 'rejected' OR (
            rejected_by IS NOT NULL AND length(btrim(rejected_by)) > 0
            AND rejected_at IS NOT NULL
            AND rejection_reason IS NOT NULL AND length(btrim(rejection_reason)) > 0
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_functional_knowledge_content_rules_status
    ON functional_knowledge_content_rules(status, rule_kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_functional_knowledge_content_rules_evidence
    ON functional_knowledge_content_rules(source_evidence_code, created_at DESC)
    WHERE source_evidence_code IS NOT NULL;

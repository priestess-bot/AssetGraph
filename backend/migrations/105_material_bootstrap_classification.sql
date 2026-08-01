-- Material-library bootstrap evidence and worker-observed Maitu bindings.
-- Classification inference remains independent from rights approval.

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS classification_review_status VARCHAR(32) NOT NULL DEFAULT 'review_required',
    ADD COLUMN IF NOT EXISTS classification_confidence NUMERIC(5, 4),
    ADD COLUMN IF NOT EXISTS classification_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS classification_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_source_material_id BIGINT,
    ADD COLUMN IF NOT EXISTS maitu_binding_evidence JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE assets
    DROP CONSTRAINT IF EXISTS chk_assets_classification_review_status,
    DROP CONSTRAINT IF EXISTS chk_assets_classification_confidence,
    DROP CONSTRAINT IF EXISTS chk_assets_classification_evidence,
    DROP CONSTRAINT IF EXISTS chk_assets_classification_fingerprint,
    DROP CONSTRAINT IF EXISTS chk_assets_maitu_binding_evidence;

ALTER TABLE assets
    ADD CONSTRAINT chk_assets_classification_review_status
        CHECK (classification_review_status IN ('inferred', 'review_required', 'confirmed')),
    ADD CONSTRAINT chk_assets_classification_confidence
        CHECK (classification_confidence IS NULL OR classification_confidence BETWEEN 0 AND 1),
    ADD CONSTRAINT chk_assets_classification_evidence
        CHECK (jsonb_typeof(classification_evidence) = 'object'),
    ADD CONSTRAINT chk_assets_classification_fingerprint
        CHECK (classification_fingerprint IS NULL OR classification_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT chk_assets_maitu_binding_evidence
        CHECK (jsonb_typeof(maitu_binding_evidence) = 'object');

CREATE INDEX IF NOT EXISTS idx_assets_classification_review_active
    ON assets (classification_review_status, updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_assets_maitu_source_material_id
    ON assets (maitu_source_material_id)
    WHERE maitu_source_material_id IS NOT NULL;

-- Historical generic classifications are not proof of an executable Maitu
-- binding.  Preserve already-attested bindings and demote every unverified row.
UPDATE assets
SET execution_capability = 'local_only', updated_at = now()
WHERE execution_capability = 'maitu_bound'
  AND COALESCE(maitu_binding_verification_source, '') NOT IN (
      'backend_maitu_inventory_readback',
      'worker_maitu_inventory_readback'
  );

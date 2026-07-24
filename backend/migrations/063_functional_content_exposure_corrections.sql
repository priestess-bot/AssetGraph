-- Corrections append new evidence and preserve the prior exposure rather than
-- overwriting the observed interval in place.

ALTER TABLE functional_content_exposures
    ADD COLUMN IF NOT EXISTS supersedes_exposure_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS superseded_by_exposure_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS correction_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_functional_content_exposures_supersedes
    ON functional_content_exposures(supersedes_exposure_code)
    WHERE supersedes_exposure_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS functional_content_exposure_corrections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correction_code VARCHAR(64) NOT NULL UNIQUE,
    source_exposure_id UUID NOT NULL REFERENCES functional_content_exposures(id),
    replacement_exposure_id UUID REFERENCES functional_content_exposures(id),
    correction_kind VARCHAR(32) NOT NULL,
    reason TEXT NOT NULL,
    actor VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_content_exposure_correction_kind
        CHECK (correction_kind IN ('supersede', 'retract')),
    CONSTRAINT chk_functional_content_exposure_correction_replacement
        CHECK (
            (correction_kind = 'supersede' AND replacement_exposure_id IS NOT NULL)
            OR (correction_kind = 'retract' AND replacement_exposure_id IS NULL)
        )
);

CREATE INDEX IF NOT EXISTS idx_functional_content_exposure_corrections_source
    ON functional_content_exposure_corrections(source_exposure_id, created_at, correction_code);

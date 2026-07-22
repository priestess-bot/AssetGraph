-- Pin an immutable, sanitized live-research reference template to a workbench run.

ALTER TABLE maitu_workbench_runs
    ADD COLUMN IF NOT EXISTS reference_template_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS reference_template_revision_number INTEGER,
    ADD COLUMN IF NOT EXISTS reference_template_projection_fingerprint CHAR(64),
    ADD COLUMN IF NOT EXISTS reference_template_snapshot JSONB;

ALTER TABLE maitu_workbench_runs
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_run_reference_template_bundle;
ALTER TABLE maitu_workbench_runs
    ADD CONSTRAINT chk_maitu_workbench_run_reference_template_bundle CHECK (
        (
            reference_template_code IS NULL
            AND reference_template_revision_number IS NULL
            AND reference_template_projection_fingerprint IS NULL
            AND reference_template_snapshot IS NULL
        )
        OR (
            reference_template_code IS NOT NULL
            AND reference_template_revision_number IS NOT NULL
            AND reference_template_revision_number >= 1
            AND reference_template_projection_fingerprint IS NOT NULL
            AND reference_template_projection_fingerprint ~ '^[0-9a-f]{64}$'
            AND reference_template_snapshot IS NOT NULL
            AND jsonb_typeof(reference_template_snapshot) = 'object'
        )
    );

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_runs_reference_template
    ON maitu_workbench_runs(
        reference_template_code,
        reference_template_revision_number,
        reference_template_projection_fingerprint
    )
    WHERE reference_template_code IS NOT NULL;

CREATE OR REPLACE FUNCTION prevent_maitu_workbench_reference_template_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.reference_template_code IS DISTINCT FROM NEW.reference_template_code
       OR OLD.reference_template_revision_number IS DISTINCT FROM NEW.reference_template_revision_number
       OR OLD.reference_template_projection_fingerprint IS DISTINCT FROM NEW.reference_template_projection_fingerprint
       OR OLD.reference_template_snapshot IS DISTINCT FROM NEW.reference_template_snapshot THEN
        RAISE EXCEPTION 'workbench run reference template is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_maitu_workbench_reference_template_immutable
    ON maitu_workbench_runs;
CREATE TRIGGER trg_maitu_workbench_reference_template_immutable
BEFORE UPDATE ON maitu_workbench_runs
FOR EACH ROW
EXECUTE FUNCTION prevent_maitu_workbench_reference_template_mutation();

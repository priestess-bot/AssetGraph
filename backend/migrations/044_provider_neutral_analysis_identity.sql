-- Require a complete, reproducible neutral identity for newly produced material analyses.
-- Migration 043 introduced these fields; this additive migration hardens direct database
-- writes after existing legacy rows have been classified.

ALTER TABLE maitu_workbench_video_analyses
    DROP CONSTRAINT IF EXISTS chk_maitu_video_neutral_analysis_identity;

ALTER TABLE maitu_workbench_video_analyses
    ADD CONSTRAINT chk_maitu_video_neutral_analysis_identity CHECK (
        status <> 'succeeded'
        OR analysis_strategy_revision = 'legacy.material-vision.v1'
        OR (
            analysis_prompt_revision IS NOT NULL
            AND analysis_input_fingerprint IS NOT NULL
            AND analysis_output_fingerprint IS NOT NULL
        )
    );

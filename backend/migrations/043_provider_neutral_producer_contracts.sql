-- Replace supplier-specific producer contracts with strategy and evidence references.
-- Legacy columns remain nullable, read-only compatibility data for rows created before
-- the corresponding producer was migrated.

ALTER TABLE maitu_workbench_plan_revisions
    ADD COLUMN IF NOT EXISTS generation_strategy_revision VARCHAR(128),
    ADD COLUMN IF NOT EXISTS generation_invocation_evidence_ref VARCHAR(80);

UPDATE maitu_workbench_plan_revisions
SET generation_strategy_revision = 'legacy.maitu-plan.v1'
WHERE generation_strategy_revision IS NULL;

ALTER TABLE maitu_workbench_plan_revisions
    ALTER COLUMN generation_strategy_revision SET NOT NULL,
    ALTER COLUMN generation_strategy_revision SET DEFAULT 'legacy.maitu-plan.v1',
    ALTER COLUMN generation_provider DROP NOT NULL,
    ALTER COLUMN generation_requested_model DROP NOT NULL,
    ALTER COLUMN generation_actual_model DROP NOT NULL,
    ALTER COLUMN generation_latency_ms DROP NOT NULL;

ALTER TABLE maitu_workbench_plan_revisions
    DROP CONSTRAINT IF EXISTS fk_maitu_plan_provider_evidence,
    DROP CONSTRAINT IF EXISTS chk_maitu_plan_provider_contract,
    DROP CONSTRAINT IF EXISTS chk_maitu_plan_provider_evidence;

ALTER TABLE maitu_workbench_plan_revisions
    ADD CONSTRAINT fk_maitu_plan_provider_evidence
        FOREIGN KEY (generation_invocation_evidence_ref)
        REFERENCES artifact_refs(artifact_code),
    ADD CONSTRAINT chk_maitu_plan_provider_contract CHECK (
        generation_strategy_revision = 'legacy.maitu-plan.v1'
        OR (
            generation_provider IS NULL
            AND generation_requested_model IS NULL
            AND generation_actual_model IS NULL
            AND generation_request_id IS NULL
            AND generation_usage = '{}'::jsonb
            AND generation_latency_ms IS NULL
        )
    ),
    ADD CONSTRAINT chk_maitu_plan_provider_evidence CHECK (
        generation_strategy_revision = 'legacy.maitu-plan.v1'
        OR generation_strategy_revision LIKE 'test.%'
        OR generation_invocation_evidence_ref IS NOT NULL
    );

ALTER TABLE live_analysis_runs
    ADD COLUMN IF NOT EXISTS strategy_revision VARCHAR(128),
    ADD COLUMN IF NOT EXISTS invocation_evidence_ref VARCHAR(80);

UPDATE live_analysis_runs
SET strategy_revision = 'legacy.live-analysis.v1'
WHERE strategy_revision IS NULL;

ALTER TABLE live_analysis_runs
    ALTER COLUMN strategy_revision SET NOT NULL,
    ALTER COLUMN strategy_revision SET DEFAULT 'legacy.live-analysis.v1',
    ALTER COLUMN model_provider DROP NOT NULL,
    ALTER COLUMN model_version DROP NOT NULL;

DROP INDEX IF EXISTS idx_live_analysis_runs_input_unique;
CREATE UNIQUE INDEX idx_live_analysis_runs_input_unique
    ON live_analysis_runs(
        session_id,
        coalesce(chunk_id, '00000000-0000-0000-0000-000000000000'::uuid),
        analysis_type,
        input_fingerprint,
        strategy_revision
    );

ALTER TABLE live_analysis_runs
    DROP CONSTRAINT IF EXISTS fk_live_analysis_provider_evidence,
    DROP CONSTRAINT IF EXISTS chk_live_analysis_provider_contract,
    DROP CONSTRAINT IF EXISTS chk_live_analysis_provider_evidence;

ALTER TABLE live_analysis_runs
    ADD CONSTRAINT fk_live_analysis_provider_evidence
        FOREIGN KEY (invocation_evidence_ref)
        REFERENCES artifact_refs(artifact_code),
    ADD CONSTRAINT chk_live_analysis_provider_contract CHECK (
        strategy_revision = 'legacy.live-analysis.v1'
        OR (model_provider IS NULL AND model_version IS NULL)
    ),
    ADD CONSTRAINT chk_live_analysis_provider_evidence CHECK (
        status <> 'succeeded'
        OR analysis_type = 'frame_sampling'
        OR strategy_revision = 'legacy.live-analysis.v1'
        OR strategy_revision LIKE 'test.%'
        OR invocation_evidence_ref IS NOT NULL
    );

ALTER TABLE maitu_workbench_video_analyses
    ADD COLUMN IF NOT EXISTS analysis_strategy_revision VARCHAR(128),
    ADD COLUMN IF NOT EXISTS invocation_evidence_ref VARCHAR(80),
    ADD COLUMN IF NOT EXISTS analysis_prompt_revision VARCHAR(64),
    ADD COLUMN IF NOT EXISTS analysis_input_fingerprint CHAR(64),
    ADD COLUMN IF NOT EXISTS analysis_output_fingerprint CHAR(64);

UPDATE maitu_workbench_video_analyses
SET analysis_strategy_revision = 'legacy.material-vision.v1'
WHERE analysis_strategy_revision IS NULL;

UPDATE maitu_workbench_video_analyses
SET analysis_prompt_revision = model_prompt_version,
    analysis_input_fingerprint = model_input_fingerprint,
    analysis_output_fingerprint = model_output_fingerprint
WHERE analysis_strategy_revision = 'legacy.material-vision.v1';

UPDATE maitu_workbench_video_analyses
SET provisional_source = 'strategy_frames'
WHERE provisional_source = 'gpt_5_6_sol';

ALTER TABLE maitu_workbench_video_analyses
    ALTER COLUMN analysis_strategy_revision SET NOT NULL,
    ALTER COLUMN analysis_strategy_revision SET DEFAULT 'legacy.material-vision.v1';

ALTER TABLE maitu_workbench_video_analyses
    DROP CONSTRAINT IF EXISTS fk_maitu_video_provider_evidence,
    DROP CONSTRAINT IF EXISTS chk_maitu_video_provider_contract,
    DROP CONSTRAINT IF EXISTS chk_maitu_video_provider_evidence,
    DROP CONSTRAINT IF EXISTS chk_maitu_video_analysis_provisional_source,
    DROP CONSTRAINT IF EXISTS chk_maitu_video_analysis_input_sha,
    DROP CONSTRAINT IF EXISTS chk_maitu_video_analysis_output_sha;

ALTER TABLE maitu_workbench_video_analyses
    ADD CONSTRAINT fk_maitu_video_provider_evidence
        FOREIGN KEY (invocation_evidence_ref)
        REFERENCES artifact_refs(artifact_code),
    ADD CONSTRAINT chk_maitu_video_provider_contract CHECK (
        analysis_strategy_revision = 'legacy.material-vision.v1'
        OR (
            model_provider IS NULL
            AND model_requested IS NULL
            AND model_actual IS NULL
            AND model_prompt_version IS NULL
            AND model_request_id IS NULL
            AND model_input_fingerprint IS NULL
            AND model_output_fingerprint IS NULL
            AND model_usage = '{}'::jsonb
            AND model_latency_ms IS NULL
        )
    ),
    ADD CONSTRAINT chk_maitu_video_provider_evidence CHECK (
        status <> 'succeeded'
        OR analysis_strategy_revision = 'legacy.material-vision.v1'
        OR analysis_strategy_revision LIKE 'test.%'
        OR invocation_evidence_ref IS NOT NULL
    ),
    ADD CONSTRAINT chk_maitu_video_analysis_provisional_source CHECK (
        provisional_source IN ('none', 'keyframe', 'strategy_frames')
    ),
    ADD CONSTRAINT chk_maitu_video_analysis_input_sha CHECK (
        analysis_input_fingerprint IS NULL
        OR analysis_input_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT chk_maitu_video_analysis_output_sha CHECK (
        analysis_output_fingerprint IS NULL
        OR analysis_output_fingerprint ~ '^[0-9a-f]{64}$'
    );

COMMENT ON COLUMN maitu_workbench_plan_revisions.generation_provider IS
    'Legacy descriptive compatibility data; new producers must leave this null.';
COMMENT ON COLUMN live_analysis_runs.model_provider IS
    'Legacy descriptive compatibility data; new producers must leave this null.';
COMMENT ON COLUMN maitu_workbench_video_analyses.model_provider IS
    'Legacy descriptive compatibility data; new producers must leave this null.';

-- Keep the command log and its immutable render manifest as separate
-- downloadable artifacts for a rendered-video job attempt.

ALTER TABLE video_production_artifacts
    DROP CONSTRAINT IF EXISTS chk_video_production_artifact_key;

ALTER TABLE video_production_artifacts
    ADD CONSTRAINT chk_video_production_artifact_key
        CHECK (artifact_key IN (
            'story_brief', 'script', 'shot_list', 'asset_plan', 'voice',
            'subtitles', 'poster', 'quality_report', 'video', 'render_log',
            'render_manifest'
        ));

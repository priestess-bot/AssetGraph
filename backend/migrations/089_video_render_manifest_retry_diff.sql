-- Keep render retries inspectable, and bring the database artifact contract
-- in line with the contact-sheet artifact already emitted by the renderer.

ALTER TABLE video_production_artifacts
    DROP CONSTRAINT IF EXISTS chk_video_production_artifact_key;

ALTER TABLE video_production_artifacts
    ADD CONSTRAINT chk_video_production_artifact_key
        CHECK (artifact_key IN (
            'story_brief', 'script', 'shot_list', 'asset_plan', 'voice',
            'subtitles', 'poster', 'contact_sheet', 'quality_report', 'video',
            'render_log', 'render_manifest', 'render_manifest_diff'
        ));

-- Rendering produces plan-wide outputs and one poster selected at a precise
-- timeline point. Extend the existing append-only execution evidence roles
-- without changing already-recorded voice or subtitle links.

ALTER TABLE functional_video_timeline_segment_execution_artifacts
    DROP CONSTRAINT IF EXISTS chk_functional_video_timeline_execution_role;

ALTER TABLE functional_video_timeline_segment_execution_artifacts
    ADD CONSTRAINT chk_functional_video_timeline_execution_role
    CHECK (artifact_role IN (
        'voice_segment',
        'subtitle_track',
        'render_manifest',
        'rendered_video',
        'poster'
    ));

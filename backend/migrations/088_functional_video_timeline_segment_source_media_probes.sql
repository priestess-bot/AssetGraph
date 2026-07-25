-- Asset selection is where the local renderer has authoritative ffprobe
-- metadata. Keep its PTS/timebase mapping as segment execution evidence.

ALTER TABLE functional_video_timeline_segment_execution_artifacts
    DROP CONSTRAINT IF EXISTS chk_functional_video_timeline_execution_role;

ALTER TABLE functional_video_timeline_segment_execution_artifacts
    ADD CONSTRAINT chk_functional_video_timeline_execution_role
    CHECK (artifact_role IN (
        'source_media_probe',
        'voice_segment',
        'subtitle_track',
        'render_manifest',
        'rendered_video',
        'poster'
    ));

-- Read-only domain compatibility projections. They preserve source uncertainty.

CREATE OR REPLACE FUNCTION reject_legacy_compatibility_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'legacy compatibility projections are read-only'
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE VIEW legacy_asset_observations_v1 AS
SELECT asset.asset_code AS projection_code,
       asset.asset_code,
       asset.asset_type,
       asset.title,
       asset.source_system,
       asset.maitu_category,
       asset.maitu_scene_name,
       asset.maitu_scene_index,
       asset.maitu_layer_name,
       asset.maitu_layer_index,
       jsonb_strip_nulls(jsonb_build_object(
           'left', asset.layer_left,
           'top', asset.layer_top,
           'width', asset.layer_width,
           'height', asset.layer_height,
           'z_index', asset.layer_z_index
       )) AS observed_geometry,
       asset.duplicate_group,
       asset.duplicate_rank,
       asset.duplicate_count,
       'observed_legacy_placement'::varchar AS geometry_semantics,
       'legacy_duplicate_candidate'::varchar AS duplicate_group_semantics,
       false AS is_constraint,
       false AS is_user_group,
       'assets'::varchar AS source_type,
       asset.asset_code::varchar AS source_code,
       'legacy_import'::varchar AS mapping_quality,
       asset.updated_at,
       true AS read_only
FROM assets AS asset
WHERE asset.deleted_at IS NULL;

CREATE OR REPLACE VIEW legacy_content_project_projections_v1 AS
SELECT 'LEGACY-CONTENT:WORKBENCH:' || run.run_code AS projection_project_code,
       'maitu_workbench_run'::varchar AS source_type,
       run.run_code::varchar AS source_code,
       run.title::varchar AS title,
       run.topic::text AS generation_goal,
       (run.target_duration_minutes * 60)::integer AS target_duration_seconds,
       jsonb_build_object(
           'fact_card_version_code', run.fact_card_version_code,
           'inventory_snapshot_code', run.inventory_snapshot_code,
           'reference_template_code', run.reference_template_code,
           'reference_template_revision_number', run.reference_template_revision_number,
           'production_variant_revision_id', run.production_variant_revision_id
       ) AS source_snapshot,
       jsonb_build_array(
           'independent_design_brief_revision',
           'confirmed_content_project_revision',
           'complete_fact_scope'
       ) AS missing_provenance,
       'legacy_import'::varchar AS mapping_quality,
       run.created_at,
       run.updated_at,
       true AS read_only
FROM maitu_workbench_runs AS run

UNION ALL

SELECT 'LEGACY-CONTENT:VIDEO:' || job.job_code,
       'video_production_job', job.job_code, job.topic, job.topic,
       job.target_duration_seconds,
       jsonb_build_object(
           'preset_code', job.preset_code,
           'story_brief_present', job.story_brief <> '{}'::jsonb,
           'script_present', job.script <> '{}'::jsonb,
           'shot_list_present', job.shot_list <> '{}'::jsonb,
           'production_variant_revision_id', job.production_variant_revision_id
       ),
       jsonb_build_array(
           'confirmed_content_project_revision',
           'fixed_fact_revisions',
           'verified_story_brief_lineage'
       ),
       'legacy_import', job.created_at, job.updated_at, true
FROM video_production_jobs AS job;

CREATE OR REPLACE VIEW legacy_live_room_variant_projections_v1 AS
SELECT 'LEGACY-LIVE-VARIANT:' || run.run_code AS projection_variant_code,
       'maitu_workbench_run'::varchar AS source_type,
       run.run_code::varchar AS source_code,
       variant.variant_code,
       variant_revision.revision_number AS variant_revision,
       configuration.configuration_code,
       configuration_revision.revision_number AS configuration_revision,
       'live_room'::varchar AS carrier_kind,
       run.target_live_room_id,
       run.title AS expected_title,
       run.status AS legacy_status,
       CASE
           WHEN variant_revision.id IS NOT NULL AND configuration_revision.id IS NOT NULL
           THEN 'verified' ELSE 'legacy_import'
       END::varchar AS mapping_quality,
       jsonb_build_object(
           'active_plan_revision', run.active_plan_revision,
           'inventory_snapshot_code', run.inventory_snapshot_code,
           'production_variant_revision_id', run.production_variant_revision_id,
           'live_room_configuration_revision_id', run.live_room_configuration_revision_id
       ) AS source_snapshot,
       run.created_at,
       run.updated_at,
       true AS read_only
FROM maitu_workbench_runs AS run
LEFT JOIN production_variant_revisions AS variant_revision
  ON variant_revision.id = run.production_variant_revision_id
LEFT JOIN production_variants AS variant ON variant.id = variant_revision.variant_id
LEFT JOIN live_room_configuration_revisions AS configuration_revision
  ON configuration_revision.id = run.live_room_configuration_revision_id
LEFT JOIN live_room_configurations AS configuration
  ON configuration.id = configuration_revision.configuration_id;

CREATE OR REPLACE VIEW legacy_layout_hypothesis_projections_v1 AS
SELECT 'LEGACY-LAYOUT:' || revision.template_code || ':' || revision.revision_number AS projection_code,
       revision.template_code,
       revision.revision_number,
       revision.status,
       revision.contract_version,
       revision.canvas,
       revision.scenes,
       revision.components,
       revision.audio_policy,
       revision.provenance,
       revision.confidence,
       revision.review_status,
       revision.source_session_code,
       'reference_only'::varchar AS reference_mode,
       'approximate'::varchar AS layout_fidelity,
       'reference_only'::varchar AS buildability,
       false AS conversion_allowed,
       'live_room_template_revision'::varchar AS source_type,
       revision.id::varchar AS source_code,
       'descriptive_only'::varchar AS mapping_quality,
       revision.created_at,
       revision.updated_at,
       true AS read_only
FROM live_room_template_revisions AS revision
WHERE revision.contract_version = 'layout-hypothesis.v1';

CREATE OR REPLACE VIEW legacy_delivery_unknown_projections_v1 AS
SELECT 'LEGACY-DELIVERY-UNKNOWN:WORKBENCH:' || run.run_code AS projection_code,
       'maitu_workbench_run'::varchar AS source_type,
       run.run_code::varchar AS source_code,
       'live_room_draft'::varchar AS possible_carrier_kind,
       NULL::varchar AS release_code,
       NULL::varchar AS delivery_code,
       run.target_live_room_id::varchar AS possible_target_id,
       NULL::jsonb AS external_identity,
       NULL::jsonb AS readback_evidence,
       'legacy_delivery_unknown'::varchar AS delivery_semantics,
       false AS is_actual_delivery,
       false AS is_exposure,
       jsonb_build_object(
           'legacy_status', run.status,
           'completed_at', run.completed_at,
           'active_plan_revision', run.active_plan_revision
       ) AS source_snapshot,
       run.completed_at AS observed_at,
       true AS read_only
FROM maitu_workbench_runs AS run
WHERE run.status = 'completed'

UNION ALL

SELECT 'LEGACY-DELIVERY-UNKNOWN:VIDEO:' || job.job_code,
       'video_production_job', job.job_code, 'rendered_video',
       NULL::varchar, NULL::varchar, NULL::varchar, NULL::jsonb, NULL::jsonb,
       'legacy_delivery_unknown', false, false,
       jsonb_build_object(
           'legacy_status', job.status,
           'completed_at', job.completed_at,
           'final_asset_code', asset.asset_code,
           'final_asset_checksum', asset.checksum_sha256
       ),
       job.completed_at, true
FROM video_production_jobs AS job
LEFT JOIN assets AS asset ON asset.id = job.final_asset_id
WHERE job.status = 'succeeded';

COMMENT ON VIEW legacy_asset_observations_v1 IS
    'Legacy geometry and duplicate_group are observations only, never constraints or user groups.';
COMMENT ON VIEW legacy_content_project_projections_v1 IS
    'Synthetic read root over legacy content sources; missing provenance remains explicit.';
COMMENT ON VIEW legacy_live_room_variant_projections_v1 IS
    'Legacy workbench to live-room variant projection; only explicit links are verified.';
COMMENT ON VIEW legacy_layout_hypothesis_projections_v1 IS
    'layout-hypothesis.v1 remains descriptive, approximate and reference-only.';
COMMENT ON VIEW legacy_delivery_unknown_projections_v1 IS
    'Completed legacy execution is not proof of Release, Delivery or Exposure.';

DO $$
DECLARE
    view_name TEXT;
BEGIN
    FOREACH view_name IN ARRAY ARRAY[
        'legacy_asset_observations_v1',
        'legacy_content_project_projections_v1',
        'legacy_live_room_variant_projections_v1',
        'legacy_layout_hypothesis_projections_v1',
        'legacy_delivery_unknown_projections_v1',
        'legacy_workflow_run_projections_v1',
        'legacy_workflow_step_projections_v1'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_read_only ON %I', view_name, view_name);
        EXECUTE format(
            'CREATE TRIGGER trg_%s_read_only INSTEAD OF INSERT OR UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION reject_legacy_compatibility_mutation()',
            view_name,
            view_name
        );
    END LOOP;
END;
$$;

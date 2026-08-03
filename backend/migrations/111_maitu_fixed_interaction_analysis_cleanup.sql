-- Retire analysis jobs created before fixed interactions were reclassified.

UPDATE maitu_interaction_analysis_jobs AS job
SET status = 'failed',
    claimed_by = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    heartbeat_at = NULL,
    retry_after = NULL,
    error_code = 'INTERACTION_FILTERED',
    error_message = 'Interaction is excluded by the fixed-interaction filter',
    completed_at = COALESCE(job.completed_at, now()),
    updated_at = now()
FROM maitu_live_interactions AS interaction
WHERE job.interaction_id = interaction.id
  AND interaction.is_arrival
  AND job.status IN ('queued', 'running');

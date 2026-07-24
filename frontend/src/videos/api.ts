import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

const ROOT = "/api/functional-video-plans";

export interface FunctionalVideoPlan {
  planCode: string; projectCode: string; variantCode: string; videoJobCode: string; title: string;
  timelineRevision: number;
  productionTimeline: { global_end_ms: number; tracks: Array<{ track_kind: string; clips: Array<{ clip_code: string; timeline_range: { start_ms: number; duration_ms: number }; source_range?: { asset_code: string; start_seconds?: number; end_seconds?: number; available_start_seconds?: number; available_end_seconds?: number }; transition?: string }> }> };
  renderProfile: { visual_asset_mode?: string; target_duration_seconds?: number; canvas?: { width: number; height: number; fps: number } };
  jobStatus: string; currentStage?: string; progressPercent: number; errorMessage?: string; finalAssetId?: string;
  qualityReport: { passed?: boolean; checks: Record<string, boolean> };
  workflowStages: Array<{ stageName: string; stageOrder: number; status: string; attempt: number; errorCode?: string; errorMessage?: string }>;
  artifacts: Array<{ artifact_key: string; stage_name?: string; download_url?: string; mime_type?: string; file_size?: number; checksum_sha256?: string }>;
}

export interface VideoTimelineRevision {
  revisionNumber: number; productionTimeline: FunctionalVideoPlan["productionTimeline"]; actorId: string; createdAt: string;
}

function productionTimeline(value: unknown): FunctionalVideoPlan["productionTimeline"] {
  const timeline = isRecord(value) ? value : {};
  return { global_end_ms: asNumber(timeline.global_end_ms), tracks: asArray(timeline.tracks).flatMap((track) => isRecord(track) ? [{ track_kind: asString(track.track_kind), clips: asArray(track.clips).flatMap((clip) => isRecord(clip) && isRecord(clip.timeline_range) ? [{ clip_code: asString(clip.clip_code), timeline_range: { start_ms: asNumber(clip.timeline_range.start_ms), duration_ms: asNumber(clip.timeline_range.duration_ms) }, source_range: isRecord(clip.source_range) ? { asset_code: asString(clip.source_range.asset_code), start_seconds: typeof clip.source_range.start_seconds === "number" ? clip.source_range.start_seconds : undefined, end_seconds: typeof clip.source_range.end_seconds === "number" ? clip.source_range.end_seconds : undefined, available_start_seconds: typeof clip.source_range.available_start_seconds === "number" ? clip.source_range.available_start_seconds : undefined, available_end_seconds: typeof clip.source_range.available_end_seconds === "number" ? clip.source_range.available_end_seconds : undefined } : undefined, transition: asOptionalString(clip.transition) }] : []) }] : []) };
}

function plan(value: unknown): FunctionalVideoPlan {
  if (!isRecord(value)) throw new Error("成片计划响应无效");
  const code = asString(value.plan_code); if (!code) throw new Error("成片计划缺少编码");
  const profile = isRecord(value.render_profile) ? value.render_profile : {};
  const quality = isRecord(value.quality_report) ? value.quality_report : {};
  return { planCode: code, projectCode: asString(value.project_code), variantCode: asString(value.variant_code), videoJobCode: asString(value.video_job_code), title: asString(value.title), timelineRevision: asNumber(value.timeline_revision, 1), productionTimeline: productionTimeline(value.production_timeline), renderProfile: { visual_asset_mode: asOptionalString(profile.visual_asset_mode), target_duration_seconds: typeof profile.target_duration_seconds === "number" ? profile.target_duration_seconds : undefined, canvas: isRecord(profile.canvas) ? { width: asNumber(profile.canvas.width), height: asNumber(profile.canvas.height), fps: asNumber(profile.canvas.fps) } : undefined }, jobStatus: asString(value.job_status), currentStage: asOptionalString(value.current_stage), progressPercent: asNumber(value.progress_percent), errorMessage: asOptionalString(value.error_message), finalAssetId: asOptionalString(value.final_asset_id), qualityReport: { passed: typeof quality.passed === "boolean" ? quality.passed : undefined, checks: isRecord(quality.checks) ? Object.fromEntries(Object.entries(quality.checks).flatMap(([key, check]) => typeof check === "boolean" ? [[key, check]] : [])) : {} }, workflowStages: asArray(value.workflow_stages).flatMap((stage) => isRecord(stage) ? [{ stageName: asString(stage.stage_name), stageOrder: asNumber(stage.stage_order), status: asString(stage.status), attempt: asNumber(stage.attempt, 1), errorCode: asOptionalString(stage.error_code), errorMessage: asOptionalString(stage.error_message) }] : []), artifacts: asArray(value.artifacts).flatMap((artifact) => isRecord(artifact) ? [{ artifact_key: asString(artifact.artifact_key), stage_name: asOptionalString(artifact.stage_name), download_url: asOptionalString(artifact.download_url), mime_type: asOptionalString(artifact.mime_type), file_size: typeof artifact.file_size === "number" ? artifact.file_size : undefined, checksum_sha256: asOptionalString(artifact.checksum_sha256) }] : []) };
}

function timelineRevision(value: unknown): VideoTimelineRevision {
  if (!isRecord(value)) throw new Error("时间轴修订响应无效");
  return { revisionNumber: asNumber(value.revision_number), productionTimeline: productionTimeline(value.production_timeline), actorId: asString(value.actor_id), createdAt: asString(value.created_at) };
}

export const functionalVideosApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.map(plan)),
  get: (code: string) => requestJson<unknown>(`${ROOT}/${code}`).then(plan),
  listTimelineRevisions: (code: string) => requestJson<unknown[]>(`${ROOT}/${code}/timeline-revisions`).then((rows) => rows.map(timelineRevision)),
  create: (payload: { project_code: string; title?: string; target_duration_seconds: number }) => postJson<unknown>(ROOT, payload).then(plan),
  updateTimeline: (code: string, payload: { expected_revision: number; video_clips: Array<{ clip_code: string; duration_ms: number; transition: string; source_start_seconds?: number; source_end_seconds?: number }> }) => requestJson<unknown>(`${ROOT}/${code}/timeline`, { method: "PUT", body: JSON.stringify(payload) }).then(plan),
  restoreTimelineRevision: (code: string, sourceRevision: number, expectedRevision: number) => postJson<unknown>(`${ROOT}/${code}/timeline-revisions/${sourceRevision}/restore`, { expected_revision: expectedRevision }).then(plan),
  retry: (code: string) => postJson<unknown>(`${ROOT}/${code}/retry`).then(plan),
};

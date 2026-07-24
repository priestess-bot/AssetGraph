import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

const ROOT = "/api/functional-video-plans";

export interface FunctionalVideoPlan {
  planCode: string; projectCode: string; variantCode: string; videoJobCode: string; title: string;
  timelineRevision: number;
  productionTimeline: { global_end_ms: number; tracks: Array<{ track_kind: string; clips: Array<{ clip_code: string; timeline_range: { start_ms: number; duration_ms: number }; source_range?: { asset_code: string }; transition?: string }> }> };
  renderProfile: { visual_asset_mode?: string; target_duration_seconds?: number; canvas?: { width: number; height: number; fps: number } };
  jobStatus: string; currentStage?: string; progressPercent: number; errorMessage?: string;
  artifacts: Array<{ artifact_key: string; download_url?: string; mime_type?: string }>;
}

function plan(value: unknown): FunctionalVideoPlan {
  if (!isRecord(value)) throw new Error("成片计划响应无效");
  const code = asString(value.plan_code); if (!code) throw new Error("成片计划缺少编码");
  const timeline = isRecord(value.production_timeline) ? value.production_timeline : {};
  const profile = isRecord(value.render_profile) ? value.render_profile : {};
  return { planCode: code, projectCode: asString(value.project_code), variantCode: asString(value.variant_code), videoJobCode: asString(value.video_job_code), title: asString(value.title), timelineRevision: asNumber(value.timeline_revision, 1), productionTimeline: { global_end_ms: asNumber(timeline.global_end_ms), tracks: asArray(timeline.tracks).flatMap((track) => isRecord(track) ? [{ track_kind: asString(track.track_kind), clips: asArray(track.clips).flatMap((clip) => isRecord(clip) && isRecord(clip.timeline_range) ? [{ clip_code: asString(clip.clip_code), timeline_range: { start_ms: asNumber(clip.timeline_range.start_ms), duration_ms: asNumber(clip.timeline_range.duration_ms) }, source_range: isRecord(clip.source_range) ? { asset_code: asString(clip.source_range.asset_code) } : undefined, transition: asOptionalString(clip.transition) }] : []) }] : []) }, renderProfile: { visual_asset_mode: asOptionalString(profile.visual_asset_mode), target_duration_seconds: typeof profile.target_duration_seconds === "number" ? profile.target_duration_seconds : undefined, canvas: isRecord(profile.canvas) ? { width: asNumber(profile.canvas.width), height: asNumber(profile.canvas.height), fps: asNumber(profile.canvas.fps) } : undefined }, jobStatus: asString(value.job_status), currentStage: asOptionalString(value.current_stage), progressPercent: asNumber(value.progress_percent), errorMessage: asOptionalString(value.error_message), artifacts: asArray(value.artifacts).flatMap((artifact) => isRecord(artifact) ? [{ artifact_key: asString(artifact.artifact_key), download_url: asOptionalString(artifact.download_url), mime_type: asOptionalString(artifact.mime_type) }] : []) };
}

export const functionalVideosApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.map(plan)),
  get: (code: string) => requestJson<unknown>(`${ROOT}/${code}`).then(plan),
  create: (payload: { project_code: string; title?: string; target_duration_seconds: number }) => postJson<unknown>(ROOT, payload).then(plan),
  updateTimeline: (code: string, payload: { expected_revision: number; video_clips: Array<{ clip_code: string; duration_ms: number; transition: string }> }) => requestJson<unknown>(`${ROOT}/${code}/timeline`, { method: "PUT", body: JSON.stringify(payload) }).then(plan),
  retry: (code: string) => postJson<unknown>(`${ROOT}/${code}/retry`).then(plan),
};

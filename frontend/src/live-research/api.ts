import { asArray, asBoolean, asNumber, asOptionalString, asString, isRecord, patchJson, postJson, requestJson } from "../workbench/api";
import type {
  AnalysisRun,
  AsrSegment,
  Buildability,
  CaptureSession,
  CaptureTimeline,
  ContentReadiness,
  ContentStrategy,
  ClipJob,
  InferredComponent,
  InteractionBucket,
  JobStatus,
  Keyframe,
  LayoutFidelity,
  ResearchOverview,
  RoomTemplate,
  TemplateProjection,
  TemplateRevision,
  TemplateScene,
  TemplateKind,
  VisualSegment,
  WatchTarget,
} from "./types";

const ROOT = "/api/live-research";

function strings(value: unknown): string[] {
  return asArray(value).flatMap((item) => typeof item === "string" ? [item] : []);
}

function normalizeHealth(value: unknown, fallback: "healthy" | "degraded" | "offline" | "unknown" = "unknown") {
  const text = asString(value, fallback);
  return text === "healthy" || text === "degraded" || text === "offline" ? text : "unknown";
}

export function normalizeWatchTarget(value: unknown): WatchTarget {
  if (!isRecord(value)) throw new Error("Invalid watch target response");
  const enabled = value.enabled === true;
  const metadata = isRecord(value.metadata) ? value.metadata : {};
  const status = asString(value.status, enabled ? "enabled" : "paused") as WatchTarget["status"];
  const failures = asNumber(value.consecutive_failures);
  return {
    target_code: asString(value.target_code ?? value.watch_target_code),
    platform: "douyin",
    display_name: asString(value.display_name ?? value.account_name ?? value.room_id, "未命名直播间"),
    room_url: asString(value.room_url ?? value.source_url),
    room_id: asOptionalString(value.room_id ?? value.canonical_room_id),
    account_name: asOptionalString(value.account_name ?? metadata.account_name),
    status,
    live_state: asString(value.live_state ?? metadata.live_state, value.last_capture_session_code ? "offline" : "unknown") as WatchTarget["live_state"],
    recorder_health: normalizeHealth(value.recorder_health ?? metadata.recorder_health, status === "blocked" || status === "paused" ? "offline" : failures ? "degraded" : "unknown"),
    interaction_health: normalizeHealth(value.interaction_health ?? metadata.interaction_health, status === "blocked" || status === "paused" ? "offline" : failures ? "degraded" : "unknown"),
    last_live_at: asOptionalString(value.last_live_at),
    last_checked_at: asOptionalString(value.last_checked_at ?? value.last_observed_at),
    next_retry_at: asOptionalString(value.next_retry_at ?? value.next_check_at),
    failure_reason: asOptionalString(value.failure_reason ?? value.last_error_message),
    created_at: asOptionalString(value.created_at),
  };
}

export function normalizeOverview(value: unknown): ResearchOverview {
  const record = isRecord(value) ? value : {};
  return {
    enabled_target_count: asNumber(record.enabled_target_count ?? record.watch_targets_enabled),
    live_target_count: asNumber(record.live_target_count ?? record.active_capture_sessions),
    recording_session_count: asNumber(record.recording_session_count ?? record.active_capture_sessions),
    analysis_queue_count: asNumber(record.analysis_queue_count, asNumber(record.queued_analysis_runs) + asNumber(record.running_analysis_runs)),
    draft_template_count: asNumber(record.draft_template_count ?? record.draft_templates),
    expiring_recording_count: asNumber(record.expiring_recording_count ?? record.expiring_capture_chunks),
  };
}

export function normalizeCaptureSession(value: unknown): CaptureSession {
  if (!isRecord(value)) throw new Error("Invalid capture session response");
  const status = asString(value.status, "starting") as CaptureSession["status"];
  const metadata = isRecord(value.metadata) ? value.metadata : {};
  const chunks = asArray(value.chunks);
  const timelineSpans = asArray(value.timeline);
  const retentionDates = chunks.flatMap((item) => isRecord(item) && asOptionalString(item.retention_expires_at) ? [asString(item.retention_expires_at)] : []);
  const channels = asArray(value.channels);
  const recorderChannel = channels.find((item) => isRecord(item) && ["recording", "video", "recorder"].includes(asString(item.channel_type ?? item.kind ?? item.media_kind)));
  const channelHealth = (channel: unknown, fallback: "healthy" | "degraded" | "failed") => {
    if (!isRecord(channel)) return fallback;
    const channelStatus = asString(channel.status);
    return channelStatus === "failed" ? "failed" : ["degraded", "partial"].includes(channelStatus) ? "degraded" : "healthy";
  };
  const mediaChunks = chunks.flatMap((item) => {
    if (!isRecord(item) || !asOptionalString(item.media_url)) return [];
    const span = timelineSpans.find((entry) => isRecord(entry) && asString(entry.chunk_code) === asString(item.chunk_code));
    const decodedDuration = asNumber(item.decoded_duration_seconds);
    return [{
      chunk_code: asString(item.chunk_code),
      media_url: asString(item.media_url),
      global_start_seconds: isRecord(span) ? asNumber(span.global_start_seconds) : 0,
      global_end_seconds: isRecord(span) ? asNumber(span.global_end_seconds) : decodedDuration,
      chunk_start_seconds: isRecord(span) ? asNumber(span.chunk_start_seconds) : 0,
    }];
  }).sort((left, right) => left.global_start_seconds - right.global_start_seconds);
  const interactionEventCount = asNumber(value.interaction_event_count ?? value.event_count);
  const hasRecordedMedia = mediaChunks.length > 0 || asNumber(value.chunk_count) > 0;
  const hasInteractionEvidence = interactionEventCount > 0 || asArray(value.raw_event_batches).length > 0;
  return {
    session_code: asString(value.session_code ?? value.capture_session_code),
    target_code: asString(value.target_code),
    title: asString(value.title ?? value.display_name ?? metadata.title, `抖音采集 ${asString(value.session_code)}`),
    status,
    started_at: asOptionalString(value.started_at ?? value.observed_started_at),
    finalized_at: asOptionalString(value.finalized_at ?? value.ended_at ?? value.observed_ended_at),
    duration_seconds: asNumber(value.duration_seconds ?? value.timeline_duration_seconds),
    playback_url: asOptionalString(value.playback_url ?? value.recording_url ?? value.media_url),
    poster_url: asOptionalString(value.poster_url),
    expires_at: asOptionalString(value.expires_at ?? value.recording_expires_at) ?? retentionDates.sort()[0],
    recording_available: asBoolean(value.recording_available, status !== "failed" && status !== "abandoned"),
    recorder_health: asString(value.recorder_health, channelHealth(recorderChannel, status === "failed" || status === "abandoned" ? "failed" : hasRecordedMedia ? "healthy" : "degraded")) as CaptureSession["recorder_health"],
    interaction_health: asString(value.interaction_health, status === "failed" || status === "abandoned" ? "failed" : hasInteractionEvidence ? "healthy" : "degraded") as CaptureSession["interaction_health"],
    interaction_event_count: interactionEventCount,
    analysis_status: asOptionalString(value.analysis_status) as JobStatus | undefined,
    template_code: asOptionalString(value.template_code),
    media_chunks: mediaChunks,
  };
}

function normalizeAsr(value: unknown): AsrSegment | undefined {
  if (!isRecord(value)) return undefined;
  return { start_seconds: asNumber(value.start_seconds ?? value.start), end_seconds: asNumber(value.end_seconds ?? value.end), text: asString(value.text ?? value.transcript), confidence: typeof value.confidence === "number" ? value.confidence : undefined };
}

function normalizeVisual(value: unknown): VisualSegment | undefined {
  if (!isRecord(value)) return undefined;
  const start = asNumber(value.start_seconds ?? value.start ?? value.at_seconds ?? value.timeline_seconds);
  return { start_seconds: start, end_seconds: asNumber(value.end_seconds ?? value.end, start + 1), label: asString(value.label ?? value.scene_name ?? value.summary ?? value.kind, "视觉段落"), confidence: typeof value.confidence === "number" ? value.confidence : undefined, composition: asOptionalString(value.composition ?? value.text ?? value.kind) };
}

function normalizeInteraction(value: unknown): InteractionBucket | undefined {
  if (!isRecord(value)) return undefined;
  return { start_seconds: asNumber(value.start_seconds ?? value.start), end_seconds: asNumber(value.end_seconds ?? value.end), total_count: asNumber(value.total_count ?? value.count), dominant_type: asOptionalString(value.dominant_type ?? value.event_type), summary: asOptionalString(value.summary) };
}

function normalizeKeyframe(value: unknown): Keyframe | undefined {
  if (!isRecord(value)) return undefined;
  return { at_seconds: asNumber(value.at_seconds ?? value.timestamp_seconds ?? value.timeline_seconds), thumbnail_url: asOptionalString(value.thumbnail_url), label: asOptionalString(value.label ?? value.frame_code) };
}

export function normalizeTimeline(value: unknown): CaptureTimeline {
  const record = isRecord(value) ? value : {};
  const timelineSpans = Array.isArray(value) ? value : asArray(record.timeline ?? record.spans);
  const spanSegments = timelineSpans.flatMap((item, index) => {
    if (!isRecord(item)) return [];
    return [{
      start_seconds: asNumber(item.global_start_seconds),
      end_seconds: asNumber(item.global_end_seconds),
      label: `录屏分片 ${asNumber(item.span_index, index) + 1}`,
      confidence: typeof item.confidence === "number" ? item.confidence : undefined,
      composition: asOptionalString(item.discontinuity_before),
    }];
  });
  const spanDuration = spanSegments.reduce((maximum, item) => Math.max(maximum, item.end_seconds), 0);
  return {
    session_code: asString(record.session_code),
    duration_seconds: asNumber(record.duration_seconds ?? record.timeline_duration_seconds, spanDuration),
    asr_segments: asArray(record.asr_segments ?? record.asr).flatMap((item) => { const result = normalizeAsr(item); return result ? [result] : []; }),
    visual_segments: asArray(record.visual_segments ?? record.visual).flatMap((item) => { const result = normalizeVisual(item); return result ? [result] : []; }).concat(spanSegments),
    interaction_buckets: asArray(record.interaction_buckets ?? record.interactions).flatMap((item) => { const result = normalizeInteraction(item); return result ? [result] : []; }),
    keyframes: asArray(record.keyframes).flatMap((item) => { const result = normalizeKeyframe(item); return result ? [result] : []; }),
    media_gaps: asArray(record.media_gaps).flatMap((item) => isRecord(item) ? [{ start_seconds: asNumber(item.start_seconds), end_seconds: asNumber(item.end_seconds), reason: asOptionalString(item.reason) }] : []),
  };
}

function mergeAnalysisTracks(timeline: CaptureTimeline, value: unknown, rawTimeline: unknown): CaptureTimeline {
  const asr: AsrSegment[] = [];
  const visual: VisualSegment[] = [];
  const interactions: InteractionBucket[] = [];
  const keyframes: Keyframe[] = [];
  const spans = asArray(rawTimeline).filter(isRecord);
  const projectionFor = (run: Record<string, unknown>) => spans.find((span) => asString(span.chunk_code) === asString(run.chunk_code));
  const projectTime = (localSeconds: number, span: Record<string, unknown> | undefined) => {
    if (!span) return localSeconds;
    const chunkStart = asNumber(span.chunk_start_seconds);
    const globalStart = asNumber(span.global_start_seconds);
    const slope = asNumber(span.mapping_slope, 1);
    return globalStart + (localSeconds - chunkStart) * slope;
  };
  const projectSegment = <T extends { start_seconds: number; end_seconds: number }>(segment: T, span: Record<string, unknown> | undefined): T | undefined => {
    if (!span) return segment;
    const start = Math.max(asNumber(span.global_start_seconds), projectTime(segment.start_seconds, span));
    const end = Math.min(asNumber(span.global_end_seconds), projectTime(segment.end_seconds, span));
    return end > start ? { ...segment, start_seconds: start, end_seconds: end } : undefined;
  };
  asArray(value).filter(isRecord).forEach((run) => {
    const output = isRecord(run.output_payload) ? run.output_payload : {};
    const analysisType = asString(run.analysis_type);
    const span = projectionFor(run);
    const transcript = isRecord(output.transcript) ? output.transcript : {};
    const segmentSource = output.asr_segments ?? (analysisType === "asr" ? output.segments ?? transcript.segments : undefined);
    asArray(segmentSource).forEach((item) => {
      const local = normalizeAsr(item);
      const result = local ? projectSegment(local, span) : undefined;
      if (result) asr.push(result);
    });
    const visualSource = output.visual_segments ?? output.scenes ?? (analysisType === "layout_inference" ? output.segments : undefined);
    asArray(visualSource).forEach((item) => {
      const local = normalizeVisual(item);
      const result = local ? projectSegment(local, span) : undefined;
      if (result) visual.push(result);
    });
    const observations = asArray(output.observations).filter(isRecord);
    if (observations.length && !asArray(visualSource).length) {
      const parameters = isRecord(run.parameters) ? run.parameters : {};
      const sampleTimes = asArray(parameters.sample_times_seconds).filter((item): item is number => typeof item === "number" && Number.isFinite(item));
      const localStart = sampleTimes.length ? Math.min(...sampleTimes) : 0;
      const localEnd = sampleTimes.length ? Math.max(...sampleTimes) : localStart + 1;
      const labels = observations.map((item) => asString(item.label ?? item.kind)).filter(Boolean);
      const local = normalizeVisual({
        start_seconds: localStart,
        end_seconds: localEnd > localStart ? localEnd : localStart + 1,
        label: asString(output.summary, `${analysisType === "ocr" ? "文字" : "布局"}观察`),
        composition: labels.join(" / "),
      });
      const result = local ? projectSegment(local, span) : undefined;
      if (result) visual.push(result);
    }
    const interactionSource = output.interaction_buckets ?? output.interaction_summary;
    asArray(interactionSource).forEach((item) => {
      const local = normalizeInteraction(item);
      const result = local ? projectSegment(local, span) : undefined;
      if (result) interactions.push(result);
    });
    const keyframeSource = output.keyframes ?? (analysisType === "frame_sampling" ? output.frames : undefined);
    asArray(keyframeSource).forEach((item) => {
      const result = normalizeKeyframe(item);
      if (!result) return;
      const atSeconds = projectTime(result.at_seconds, span);
      if (!span || atSeconds >= asNumber(span.global_start_seconds) && atSeconds <= asNumber(span.global_end_seconds)) {
        keyframes.push({ ...result, at_seconds: atSeconds });
      }
    });
  });
  return {
    ...timeline,
    asr_segments: asr.length ? asr : timeline.asr_segments,
    visual_segments: visual.length ? visual.concat(timeline.visual_segments) : timeline.visual_segments,
    interaction_buckets: interactions.length ? interactions : timeline.interaction_buckets,
    keyframes: keyframes.length ? keyframes : timeline.keyframes,
  };
}

function interactionBucketsFromSummary(value: unknown, originAt?: string): InteractionBucket[] {
  if (!isRecord(value) || !originAt) return [];
  const origin = new Date(originAt).getTime();
  if (!Number.isFinite(origin)) return [];
  return asArray(value.buckets).flatMap((item) => {
    if (!isRecord(item)) return [];
    const start = (new Date(asString(item.bucket_start_at)).getTime() - origin) / 1000;
    const end = (new Date(asString(item.bucket_end_at)).getTime() - origin) / 1000;
    if (!Number.isFinite(start) || !Number.isFinite(end)) return [];
    const eventTypes = isRecord(item.event_types) ? item.event_types : {};
    const orderedTypes = Object.entries(eventTypes).sort((left, right) => asNumber(right[1]) - asNumber(left[1]));
    return [{
      start_seconds: Math.max(0, start),
      end_seconds: Math.max(start, end),
      total_count: asNumber(item.event_count),
      dominant_type: orderedTypes[0]?.[0],
      summary: orderedTypes.slice(0, 3).map(([eventType, count]) => `${eventType} ${asNumber(count)}`).join(" · ") || "脱敏互动聚合",
    }];
  });
}

export function normalizeClipJob(value: unknown): ClipJob {
  if (!isRecord(value)) throw new Error("Invalid clip job response");
  return {
    clip_job_code: asString(value.clip_job_code ?? value.job_code),
    session_code: asString(value.session_code),
    in_seconds: asNumber(value.in_seconds ?? value.start_seconds ?? value.requested_start_seconds),
    out_seconds: asNumber(value.out_seconds ?? value.end_seconds ?? value.requested_end_seconds),
    title: asString(value.title, "人工永久片段"),
    status: asString(value.status, "queued") as JobStatus,
    permanent: asBoolean(value.permanent, true),
    clip_code: asOptionalString(value.clip_code ?? value.final_asset_id),
    playback_url: asOptionalString(value.playback_url),
    checksum_sha256: asOptionalString(value.checksum_sha256 ?? value.output_checksum_sha256),
    error_message: asOptionalString(value.error_message),
    created_at: asOptionalString(value.created_at),
  };
}

export function normalizeAnalysisRun(value: unknown): AnalysisRun {
  if (!isRecord(value)) throw new Error("Invalid analysis run response");
  return {
    analysis_run_code: asString(value.analysis_run_code ?? value.run_code),
    session_code: asString(value.session_code),
    status: asString(value.status, "queued") as JobStatus,
    progress_percent: asNumber(value.progress_percent, asString(value.status) === "succeeded" ? 100 : asString(value.status) === "running" ? 50 : 0),
    asr_status: asString(value.asr_status, asString(value.analysis_type) === "asr" ? asString(value.status, "queued") : "queued") as JobStatus,
    visual_status: asString(value.visual_status, ["frame_sampling", "ocr", "layout_inference"].includes(asString(value.analysis_type)) ? asString(value.status, "queued") : "queued") as JobStatus,
    structure_status: asString(value.structure_status, asString(value.analysis_type) === "template_aggregation" ? asString(value.status, "queued") : "queued") as JobStatus,
    result_template_code: asOptionalString(value.result_template_code ?? value.template_code ?? (isRecord(value.output_payload) ? value.output_payload.template_code : undefined)),
    error_message: asOptionalString(value.error_message),
    updated_at: asOptionalString(value.updated_at),
  };
}

function normalizeAnalysisRunList(value: unknown): AnalysisRun[] {
  const raw = asArray(value).filter(isRecord);
  const groups = new Map<string, typeof raw>();
  raw.forEach((item) => {
    const sessionCode = asString(item.session_code);
    groups.set(sessionCode, [...(groups.get(sessionCode) ?? []), item]);
  });
  const statusFor = (items: typeof raw, types: string[]): JobStatus => {
    const matching = items.filter((item) => types.includes(asString(item.analysis_type)));
    if (!matching.length) return "queued";
    if (matching.some((item) => asString(item.status) === "failed")) return "failed";
    if (matching.every((item) => asString(item.status) === "succeeded")) return "succeeded";
    return matching.some((item) => asString(item.status) === "running") ? "running" : "queued";
  };
  return [...groups.entries()].map(([sessionCode, items]) => {
    const succeeded = items.filter((item) => asString(item.status) === "succeeded").length;
    const failed = items.some((item) => asString(item.status) === "failed");
    const running = items.some((item) => asString(item.status) === "running");
    const aggregation = items.find((item) => asString(item.analysis_type) === "template_aggregation");
    const output = aggregation && isRecord(aggregation.output_payload) ? aggregation.output_payload : {};
    return {
      analysis_run_code: asString(aggregation?.analysis_run_code ?? items.at(-1)?.analysis_run_code),
      session_code: sessionCode,
      status: (failed ? "failed" : aggregation && asString(aggregation.status) === "succeeded" ? "succeeded" : running || succeeded ? "running" : "queued") as JobStatus,
      progress_percent: Math.min(100, Math.round((succeeded / 5) * 100)),
      asr_status: statusFor(items, ["asr"]),
      visual_status: statusFor(items, ["frame_sampling", "ocr", "layout_inference"]),
      structure_status: statusFor(items, ["template_aggregation"]),
      result_template_code: asOptionalString(output.template_code ?? output.result_template_code),
      error_message: items.map((item) => asOptionalString(item.error_message)).find(Boolean),
      updated_at: items.map((item) => asOptionalString(item.updated_at)).filter((item): item is string => Boolean(item)).sort().at(-1),
    };
  });
}

function normalizeComponent(value: unknown): InferredComponent | undefined {
  if (!isRecord(value)) return undefined;
  const geometry = isRecord(value.geometry) ? value.geometry : value;
  const evidence = asArray(value.evidence).find((item) => isRecord(item) && asOptionalString(item.label));
  return {
    component_code: asOptionalString(value.component_code ?? value.component_id),
    role: asString(value.role ?? value.component_role, "unknown"),
    label: asString(value.label ?? value.component_name ?? (isRecord(evidence) ? evidence.label : undefined) ?? value.role, "推断组件"),
    x: asNumber(geometry.x), y: asNumber(geometry.y), width: asNumber(geometry.width), height: asNumber(geometry.height),
    confidence: typeof value.confidence === "number" ? value.confidence : undefined,
  };
}

function normalizeScene(value: unknown): TemplateScene | undefined {
  if (!isRecord(value)) return undefined;
  return {
    scene_code: asOptionalString(value.scene_code ?? value.scene_key),
    title: asString(value.title ?? value.scene_name ?? value.name, "未命名场景"),
    start_seconds: asNumber(value.start_seconds),
    end_seconds: asNumber(value.end_seconds),
    purpose: asString(value.purpose ?? value.scene_goal, "待人工确认"),
    script_pattern: asOptionalString(value.script_pattern),
    interaction_cue: asOptionalString(value.interaction_cue),
    material_slots: Array.isArray(value.material_slots) ? value.material_slots.filter((item): item is string => typeof item === "string") : [],
    components: asArray(value.components).flatMap((item) => { const result = normalizeComponent(item); return result ? [result] : []; }),
  };
}

function normalizeContentStrategy(value: unknown): ContentStrategy {
  const record = isRecord(value) ? value : {};
  return {
    targetCategory: asString(record.target_category),
    compatibilityTags: strings(record.compatibility_tags),
    programOutline: asArray(record.program_outline).flatMap((item) => isRecord(item) ? [{
      moduleKey: asString(item.module_key), title: asString(item.title), purpose: asString(item.purpose),
      sourceSessionCode: asOptionalString(item.source_session_code), startMs: asNumber(item.start_ms), endMs: asNumber(item.end_ms),
    }] : []),
    materialCues: strings(record.material_cues),
    reviewedExamples: asArray(record.reviewed_examples).flatMap((item) => isRecord(item) ? [{
      moduleKey: asString(item.module_key), exampleText: asString(item.example_text), sourceSessionCode: asString(item.source_session_code),
      startMs: asNumber(item.start_ms), endMs: asNumber(item.end_ms),
    }] : []),
  };
}

function normalizeRevision(value: unknown): TemplateRevision | undefined {
  if (!isRecord(value)) return undefined;
  const components = asArray(value.components);
  const scenes = asArray(value.scenes ?? (isRecord(value.content) ? value.content.scenes : undefined)).flatMap((item, index) => {
    const scene = normalizeScene(item);
    if (!scene) return [];
    const sceneKey = scene.scene_code ?? `scene-${index + 1}`;
    const linkedComponents = components.filter((component) => isRecord(component) && asString(component.scene_key, "default") === sceneKey).flatMap((component) => { const result = normalizeComponent(component); return result ? [result] : []; });
    return [{ ...scene, scene_code: sceneKey, components: linkedComponents.length ? linkedComponents : scene.components }];
  });
  return {
    revision: asNumber(value.revision ?? value.revision_number, 1),
    status: asString(value.status, "draft") as TemplateRevision["status"],
    layout_fidelity: asString(value.layout_fidelity, "approximate") as LayoutFidelity,
    buildability: asString(value.buildability, "reference_only") as Buildability,
    contentReadiness: asString(value.content_readiness, "review_required") as ContentReadiness,
    sourceSessionCodes: strings(value.source_session_codes),
    contentStrategy: normalizeContentStrategy(value.content_strategy),
    scenes,
    reviewer_note: asOptionalString(value.reviewer_note ?? value.review_notes),
    created_at: asOptionalString(value.created_at),
    published_at: asOptionalString(value.published_at),
  };
}

export function normalizeTemplate(value: unknown): RoomTemplate {
  if (!isRecord(value)) throw new Error("Invalid template response");
  const revisions = asArray(value.revisions).flatMap((item) => { const revision = normalizeRevision(item); return revision ? [revision] : []; });
  const rawRevisions = asArray(value.revisions);
  const latest = normalizeRevision(value.latest_revision_payload) ?? [...revisions].sort((left, right) => left.revision - right.revision).at(-1);
  const latestRaw = rawRevisions.filter(isRecord).sort((left, right) => asNumber(left.revision_number) - asNumber(right.revision_number)).at(-1);
  const publishedRevision = asNumber(value.published_revision_number);
  return {
    template_code: asString(value.template_code),
    title: asString(value.title ?? value.name, "未命名直播模板"),
    source_session_code: asString(value.source_session_code ?? value.session_code ?? latestRaw?.source_session_code),
    source_type: asString(value.source_type, "external_flat_video") as RoomTemplate["source_type"],
    templateKind: asString(value.template_kind, "layout_hypothesis") as TemplateKind,
    sourceTargetCode: asOptionalString(value.source_target_code),
    latest_revision: asNumber(value.latest_revision ?? value.latest_revision_number ?? latest?.revision ?? value.published_revision_number, 1),
    published_revision: publishedRevision || undefined,
    status: (latest && latest.revision > publishedRevision ? latest.status : asString(value.status, latest?.status ?? "draft")) as RoomTemplate["status"],
    layout_fidelity: asString(value.layout_fidelity, latest?.layout_fidelity ?? "approximate") as LayoutFidelity,
    buildability: asString(value.buildability, latest?.buildability ?? "reference_only") as Buildability,
    contentReadiness: asString(value.content_readiness, latest?.contentReadiness ?? "review_required") as ContentReadiness,
    contentStrategy: latest?.contentStrategy ?? normalizeContentStrategy(value.content_strategy),
    scenes: asArray(value.scenes ?? latest?.scenes).flatMap((item) => { const result = normalizeScene(item); return result ? [result] : []; }),
    source_playback_url: asOptionalString(value.source_playback_url ?? value.playback_url),
    published_version_code: asOptionalString(value.published_version_code ?? value.template_version_code) ?? (publishedRevision ? `${asString(value.template_code)}@r${publishedRevision}` : undefined),
    updated_at: asOptionalString(value.updated_at),
  };
}

export function normalizeProjection(value: unknown): TemplateProjection {
  if (!isRecord(value)) throw new Error("Invalid projection response");
  const strings = (item: unknown) => Array.isArray(item) ? item.filter((entry): entry is string => typeof entry === "string") : [];
  const provenance = isRecord(value.provenance) ? value.provenance : {};
  const components = asArray(value.components);
  const scenes = asArray(value.scenes).flatMap((item, index) => {
    const scene = normalizeScene(item);
    if (!scene) return [];
    const sceneKey = scene.scene_code ?? `scene-${index + 1}`;
    const linkedComponents = components.filter((component) => isRecord(component) && asString(component.scene_key, "default") === sceneKey).flatMap((component) => { const result = normalizeComponent(component); return result ? [result] : []; });
    return [{ ...scene, scene_code: sceneKey, components: linkedComponents.length ? linkedComponents : scene.components }];
  });
  return {
    template_code: asString(value.template_code), revision: asNumber(value.revision ?? value.revision_number), source_session_code: asOptionalString(value.source_session_code) ?? strings(provenance.source_session_codes)[0], projection_fingerprint: asOptionalString(value.projection_fingerprint), production_eligible: asBoolean(value.production_eligible ?? value.projection_ready),
    reference_capabilities: strings(value.reference_capabilities).length ? strings(value.reference_capabilities) : ["场景顺序", "时长节奏", "素材槽位", "互动提示"],
    executable_capabilities: strings(value.executable_capabilities),
    blocked_operations: strings(value.blocked_operations).length ? strings(value.blocked_operations) : (asBoolean(value.manual_review_required, true) ? ["insert_template_component", "set_exact_geometry"] : []),
    warnings: strings(value.warnings).concat(strings(value.blocking_reasons)),
    scenes,
  };
}

interface RevisionRequest {
  expected_revision: number;
  reviewer_note: string;
  source_session_code: string;
  scenes: TemplateScene[];
}

function backendRevisionPayload(payload: RevisionRequest) {
  const components = payload.scenes.flatMap((scene) => scene.components);
  return {
    source_session_code: payload.source_session_code || undefined,
    canvas: { width: 1080, height: 1920, rotation_degrees: 0, pixel_aspect_ratio: "1:1" },
    scenes: payload.scenes.map((scene, index) => ({ scene_key: scene.scene_code ?? `scene-${index + 1}`, name: scene.title, start_seconds: scene.start_seconds, end_seconds: scene.end_seconds, purpose: scene.purpose, script_pattern: scene.script_pattern, interaction_cue: scene.interaction_cue, material_slots: scene.material_slots })),
    components: payload.scenes.flatMap((scene, sceneIndex) => scene.components.map((component, componentIndex) => ({ component_id: component.component_code ?? `component-${sceneIndex + 1}-${componentIndex + 1}`, scene_key: scene.scene_code ?? `scene-${sceneIndex + 1}`, role: component.role, start_seconds: scene.start_seconds, end_seconds: scene.end_seconds, geometry: { x: component.x, y: component.y, width: component.width, height: component.height }, observability: "inferred", source_binding_status: "unmatched", audio_classification: "none", muted: true, confidence: component.confidence ?? 0.5, evidence: [{ label: component.label, source: "flat_video_visual_inference" }], ambiguities: ["外部平面视频无法恢复真实图层关系"] }))),
    audio_policy: { max_active_speech: 1, max_active_bgm: 1, unknown_audio_default_muted: true, allow_overlapping_bgm_crossfade: false, speech_ducking_db: -9 },
    provenance: { source_session_codes: payload.source_session_code ? [payload.source_session_code] : [], reviewer_note: payload.reviewer_note, layout_fidelity: "approximate", buildability: "reference_only", expected_prior_revision: payload.expected_revision },
    confidence: components.length ? components.reduce((sum, item) => sum + (item.confidence ?? 0.5), 0) / components.length : 0.5,
    created_by: "assetgraph_template_reviewer",
  };
}

export const liveResearchApi = {
  getOverview: async () => normalizeOverview(await requestJson(`${ROOT}/overview`)),
  listWatchTargets: async () => asArray(await requestJson<unknown>(`${ROOT}/watch-targets`)).map(normalizeWatchTarget),
  createWatchTarget: async (payload: { display_name: string; room_url: string }) => normalizeWatchTarget(await postJson(`${ROOT}/watch-targets`, { ...payload, platform: "douyin", recorder_engine: "streamcap", retention_days: 30 })),
  updateWatchTarget: async (targetCode: string, payload: { status: "enabled" | "paused" }) => normalizeWatchTarget(await patchJson(`${ROOT}/watch-targets/${encodeURIComponent(targetCode)}`, payload)),
  listCaptureSessions: async () => asArray(await requestJson<unknown>(`${ROOT}/capture-sessions`)).map(normalizeCaptureSession),
  getCaptureSession: async (sessionCode: string) => normalizeCaptureSession(await requestJson(`${ROOT}/capture-sessions/${encodeURIComponent(sessionCode)}`)),
  getTimeline: async (sessionCode: string) => {
    const [spans, analyses, session, interactionSummary] = await Promise.all([
      requestJson<unknown>(`${ROOT}/capture-sessions/${encodeURIComponent(sessionCode)}/timeline`),
      requestJson<unknown>(`${ROOT}/analysis-runs?session_code=${encodeURIComponent(sessionCode)}`),
      requestJson<unknown>(`${ROOT}/capture-sessions/${encodeURIComponent(sessionCode)}`),
      requestJson<unknown>(`${ROOT}/capture-sessions/${encodeURIComponent(sessionCode)}/interaction-summary?bucket_seconds=60`).catch(() => undefined),
    ]);
    const timeline = normalizeTimeline(spans);
    const analyzed = mergeAnalysisTracks({ ...timeline, session_code: sessionCode }, analyses, spans);
    const sessionRecord = isRecord(session) ? session : {};
    const originAt = asOptionalString(sessionRecord.timeline_origin_at ?? sessionRecord.observed_started_at ?? sessionRecord.started_at);
    const interactionBuckets = interactionBucketsFromSummary(interactionSummary, originAt);
    return { ...analyzed, interaction_buckets: interactionBuckets.length ? interactionBuckets : analyzed.interaction_buckets };
  },
  createClip: async (sessionCode: string, payload: { title: string; in_seconds: number; out_seconds: number }) => normalizeClipJob(await postJson(`${ROOT}/capture-sessions/${encodeURIComponent(sessionCode)}/clips`, { title: payload.title, requested_start_seconds: payload.in_seconds, requested_end_seconds: payload.out_seconds, cut_mode: "exact_reencode" })),
  listClipJobs: async () => asArray(await requestJson<unknown>(`${ROOT}/clip-jobs`)).map(normalizeClipJob),
  listAnalysisRuns: async () => normalizeAnalysisRunList(await requestJson<unknown>(`${ROOT}/analysis-runs`)),
  listTemplates: async () => asArray(await requestJson<unknown>(`${ROOT}/room-templates`)).map(normalizeTemplate),
  getTemplate: async (templateCode: string) => normalizeTemplate(await requestJson(`${ROOT}/room-templates/${encodeURIComponent(templateCode)}`)),
  createTemplate: async (payload: { title: string; source_session_code: string }) => normalizeTemplate(await postJson(`${ROOT}/room-templates`, { name: payload.title, description: `由采集场次 ${payload.source_session_code} 生成的外部平面视频参考模板` })),
  createContentStrategyTemplate: async (payload: {
    title: string;
    sourceTargetCode: string;
    sourceSessionCodes: string[];
    targetCategory: string;
    modules: Array<{ moduleKey: string; title: string; purpose: string; sourceSessionCode: string; startMs: number; endMs: number }>;
    reviewedExamples: Array<{ moduleKey: string; exampleText: string; sourceSessionCode: string; startMs: number; endMs: number }>;
    materialCues: string[];
  }) => {
    const created = normalizeTemplate(await postJson(`${ROOT}/room-templates`, {
      name: payload.title, source_target_code: payload.sourceTargetCode, template_kind: "content_strategy",
      description: "由同一来源直播间已完成录屏清洗出的内容策略模板",
    }));
    await postJson(`${ROOT}/room-templates/${encodeURIComponent(created.template_code)}/revisions`, {
      source_session_codes: payload.sourceSessionCodes, contract_version: "content-strategy.v2",
      canvas: { width: 1080, height: 1920, rotation_degrees: 0, pixel_aspect_ratio: "1:1" }, scenes: [], components: [],
      audio_policy: { max_active_speech: 1, max_active_bgm: 1, unknown_audio_default_muted: true, allow_overlapping_bgm_crossfade: false, speech_ducking_db: -9 },
      provenance: {
        review_mode: "manual_content_strategy",
        source_facts_removed: true,
        module_evidence_mode: "source-session-bounded-interval.v1",
      }, content_readiness: "ready",
      layout_fidelity: "none", buildability: "reference_only", layout_reference: {}, confidence: 0.8,
      created_by: "assetgraph_content_strategy_reviewer",
      content_strategy: {
        target_category: payload.targetCategory, compatibility_tags: [],
        program_outline: payload.modules.map((module) => ({
          module_key: module.moduleKey,
          title: module.title,
          purpose: module.purpose,
          source_session_code: module.sourceSessionCode,
          start_ms: Math.round(module.startMs),
          end_ms: Math.round(module.endMs),
        })),
        duration_policy: {}, module_recipes: [], product_rotation_policy: {}, interaction_policy: {}, conversion_policy: {}, host_style: {},
        material_cues: payload.materialCues,
        reviewed_examples: payload.reviewedExamples.map((example) => ({
          module_key: example.moduleKey,
          example_text: example.exampleText,
          source_session_code: example.sourceSessionCode,
          start_ms: Math.round(example.startMs),
          end_ms: Math.round(example.endMs),
        })),
        removed_source_fact_categories: ["price", "promotion", "inventory", "product_identity", "source_brand", "host_identity"],
      },
    });
    return normalizeTemplate(await requestJson(`${ROOT}/room-templates/${encodeURIComponent(created.template_code)}`));
  },
  createTemplateRevision: async (templateCode: string, payload: RevisionRequest) => postJson<unknown>(`${ROOT}/room-templates/${encodeURIComponent(templateCode)}/revisions`, backendRevisionPayload(payload)),
  materializeAnalysisTemplate: async (run: AnalysisRun) => {
    const rawRuns = asArray(await requestJson<unknown>(`${ROOT}/analysis-runs?session_code=${encodeURIComponent(run.session_code)}`)).filter(isRecord);
    const aggregation = rawRuns.find((item) => asString(item.analysis_type) === "template_aggregation" && asString(item.status) === "succeeded");
    const output = aggregation && isRecord(aggregation.output_payload) ? aggregation.output_payload : {};
    const hypothesis = isRecord(output.template) ? output.template : isRecord(output.layout_hypothesis) ? output.layout_hypothesis : output;
    const revision = normalizeRevision({ revision_number: 1, status: "draft", scenes: hypothesis.scenes, components: hypothesis.components });
    if (!revision?.scenes.length) throw new Error("结构分析尚未产出可审核的场景草稿");
    const created = normalizeTemplate(await postJson(`${ROOT}/room-templates`, { name: asString(output.template_name ?? output.title, `场次 ${run.session_code} 结构模板`), description: `由采集场次 ${run.session_code} 多模态分析生成的外部平面视频参考模板` }));
    await postJson(`${ROOT}/room-templates/${encodeURIComponent(created.template_code)}/revisions`, backendRevisionPayload({ expected_revision: 0, reviewer_note: "由 ASR、视觉和结构分析生成的首版草稿", source_session_code: run.session_code, scenes: revision.scenes }));
    return normalizeTemplate(await requestJson(`${ROOT}/room-templates/${encodeURIComponent(created.template_code)}`));
  },
  publishTemplate: async (templateCode: string, revision: number) => normalizeProjection(await postJson(`${ROOT}/room-templates/${encodeURIComponent(templateCode)}/revisions/${revision}/publish`, { reviewed_by: "assetgraph_template_reviewer", review_notes: "已人工确认场景边界、推断布局与参考模板边界", published_by: "assetgraph_template_publisher", publication_reason: "发布供麦兔生产工作台作为结构参考" })),
  getProjection: async (templateCode: string) => normalizeProjection(await requestJson(`${ROOT}/room-templates/${encodeURIComponent(templateCode)}/projection`)),
};

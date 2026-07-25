import {
  asArray,
  asNumber,
  asOptionalString,
  asString,
  isRecord,
  postJson,
  requestJson,
} from "../workbench/api";

const ROOT = "/api/functional-video-plans";

export interface FunctionalVideoPlan {
  planCode: string;
  projectCode: string;
  variantCode: string;
  videoJobCode: string;
  title: string;
  timelineRevision: number;
  productionTimeline: {
    global_end_ms: number;
    poster_time_ms?: number;
    tracks: Array<{
      track_kind: string;
      clips: Array<{
        clip_code: string;
        timeline_range: { start_ms: number; duration_ms: number };
        source_range?: {
          asset_code: string;
          start_seconds?: number;
          end_seconds?: number;
          available_start_seconds?: number;
          available_end_seconds?: number;
        };
        transition?: string;
        fit?: "cover" | "contain";
        crop_x?: number;
        crop_y?: number;
        playback_rate?: number;
        overlay_roles?: string[];
        linked_shot_code?: string;
        subtitle_text?: string;
        headline_text?: string;
        caption_position?: "bottom" | "center";
        gain_db?: number;
      }>;
    }>;
  };
  renderProfile: {
    visual_asset_mode?: string;
    visualAssets?: Array<{ assetCode: string; checksumSha256: string }>;
    target_duration_seconds?: number;
    canvas?: { width: number; height: number; fps: number };
  };
  jobStatus: string;
  currentStage?: string;
  progressPercent: number;
  errorMessage?: string;
  finalAssetId?: string;
  qualityReport: {
    passed?: boolean;
    checks: Record<string, boolean>;
    media?: {
      durationSeconds: number;
      width: number;
      height: number;
      videoCodec?: string;
      audioCodec?: string;
      audioSampleRate?: number;
    };
    loudness?: { integratedLufs?: number; truePeakDb?: number; lra?: number };
    diagnostics: {
      blackSegments: VideoQualitySegment[];
      silenceSegments: VideoQualitySegment[];
      freezeSegments: VideoQualitySegment[];
    };
  };
  workflowStages: Array<{
    stageName: string;
    stageOrder: number;
    status: string;
    attempt: number;
    errorCode?: string;
    errorMessage?: string;
  }>;
  artifacts: Array<{
    artifact_key: string;
    stage_name?: string;
    download_url?: string;
    mime_type?: string;
    file_size?: number;
    checksum_sha256?: string;
  }>;
  releaseCode?: string;
  releaseSnapshotArtifactCode?: string;
  releaseManifestFingerprint?: string;
  release?: {
    releaseCode: string;
    status: string;
    manifestCode: string;
    manifestFingerprint: string;
    snapshotArtifactCode: string;
  };
}

export interface VideoTimelineRevision {
  revisionNumber: number;
  productionTimeline: FunctionalVideoPlan["productionTimeline"];
  actorId: string;
  createdAt: string;
}

export interface VideoQualitySegment {
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
}

function qualitySegments(value: unknown): VideoQualitySegment[] {
  return asArray(value).flatMap((segment) =>
    isRecord(segment)
      ? [
          {
            startSeconds: asNumber(segment.start_seconds),
            endSeconds: asNumber(segment.end_seconds),
            durationSeconds: asNumber(segment.duration_seconds),
          },
        ]
      : [],
  );
}

function qualityReport(value: unknown): FunctionalVideoPlan["qualityReport"] {
  const report = isRecord(value) ? value : {};
  const media = isRecord(report.media) ? report.media : undefined;
  const loudness = isRecord(report.loudness) ? report.loudness : undefined;
  return {
    passed: typeof report.passed === "boolean" ? report.passed : undefined,
    checks: isRecord(report.checks)
      ? Object.fromEntries(
          Object.entries(report.checks).flatMap(([key, check]) =>
            typeof check === "boolean" ? [[key, check]] : [],
          ),
        )
      : {},
    media: media
      ? {
          durationSeconds: asNumber(media.duration_seconds),
          width: asNumber(media.width),
          height: asNumber(media.height),
          videoCodec: asOptionalString(media.video_codec),
          audioCodec: asOptionalString(media.audio_codec),
          audioSampleRate:
            typeof media.audio_sample_rate === "number"
              ? media.audio_sample_rate
              : undefined,
        }
      : undefined,
    loudness: loudness
      ? {
          integratedLufs:
            typeof loudness.integrated_lufs === "number"
              ? loudness.integrated_lufs
              : undefined,
          truePeakDb:
            typeof loudness.true_peak_db === "number"
              ? loudness.true_peak_db
              : undefined,
          lra: typeof loudness.lra === "number" ? loudness.lra : undefined,
        }
      : undefined,
    diagnostics: {
      blackSegments: qualitySegments(report.black_segments),
      silenceSegments: qualitySegments(report.silence_segments),
      freezeSegments: qualitySegments(report.freeze_segments),
    },
  };
}

function productionTimeline(
  value: unknown,
): FunctionalVideoPlan["productionTimeline"] {
  const timeline = isRecord(value) ? value : {};
  return {
    global_end_ms: asNumber(timeline.global_end_ms),
    poster_time_ms:
      typeof timeline.poster_time_ms === "number"
        ? timeline.poster_time_ms
        : undefined,
    tracks: asArray(timeline.tracks).flatMap((track) =>
      isRecord(track)
        ? [
            {
              track_kind: asString(track.track_kind),
              clips: asArray(track.clips).flatMap((clip) =>
                isRecord(clip) && isRecord(clip.timeline_range)
                  ? [
                      {
                        clip_code: asString(clip.clip_code),
                        timeline_range: {
                          start_ms: asNumber(clip.timeline_range.start_ms),
                          duration_ms: asNumber(
                            clip.timeline_range.duration_ms,
                          ),
                        },
                        source_range: isRecord(clip.source_range)
                          ? {
                              asset_code: asString(
                                clip.source_range.asset_code,
                              ),
                              start_seconds:
                                typeof clip.source_range.start_seconds ===
                                "number"
                                  ? clip.source_range.start_seconds
                                  : undefined,
                              end_seconds:
                                typeof clip.source_range.end_seconds ===
                                "number"
                                  ? clip.source_range.end_seconds
                                  : undefined,
                              available_start_seconds:
                                typeof clip.source_range
                                  .available_start_seconds === "number"
                                  ? clip.source_range.available_start_seconds
                                  : undefined,
                              available_end_seconds:
                                typeof clip.source_range
                                  .available_end_seconds === "number"
                                  ? clip.source_range.available_end_seconds
                                  : undefined,
                            }
                          : undefined,
                        transition: asOptionalString(clip.transition),
                        fit:
                          clip.fit === "cover" || clip.fit === "contain"
                            ? clip.fit
                            : undefined,
                        crop_x:
                          typeof clip.crop_x === "number"
                            ? clip.crop_x
                            : undefined,
                        crop_y:
                          typeof clip.crop_y === "number"
                            ? clip.crop_y
                            : undefined,
                        playback_rate:
                          typeof clip.playback_rate === "number"
                            ? clip.playback_rate
                            : undefined,
                        overlay_roles: Array.isArray(clip.overlay_roles)
                          ? asArray(clip.overlay_roles).flatMap((role) =>
                              typeof role === "string" ? [role] : [],
                            )
                          : undefined,
                        linked_shot_code: asOptionalString(
                          clip.linked_shot_code,
                        ),
                        subtitle_text: asOptionalString(clip.subtitle_text),
                        headline_text: asOptionalString(clip.headline_text),
                        caption_position:
                          clip.caption_position === "bottom" ||
                          clip.caption_position === "center"
                            ? clip.caption_position
                            : undefined,
                        gain_db:
                          typeof clip.gain_db === "number"
                            ? clip.gain_db
                            : undefined,
                      },
                    ]
                  : [],
              ),
            },
          ]
        : [],
    ),
  };
}

function plan(value: unknown): FunctionalVideoPlan {
  if (!isRecord(value)) throw new Error("成片计划响应无效");
  const code = asString(value.plan_code);
  if (!code) throw new Error("成片计划缺少编码");
  const profile = isRecord(value.render_profile) ? value.render_profile : {};
  const quality = isRecord(value.quality_report) ? value.quality_report : {};
  const release = isRecord(value.release) ? value.release : undefined;
  return {
    planCode: code,
    projectCode: asString(value.project_code),
    variantCode: asString(value.variant_code),
    videoJobCode: asString(value.video_job_code),
    title: asString(value.title),
    timelineRevision: asNumber(value.timeline_revision, 1),
    productionTimeline: productionTimeline(value.production_timeline),
    renderProfile: {
      visual_asset_mode: asOptionalString(profile.visual_asset_mode),
      visualAssets: asArray(profile.visual_assets).flatMap((asset) =>
        isRecord(asset) && asString(asset.asset_code) && asString(asset.checksum_sha256)
          ? [{ assetCode: asString(asset.asset_code), checksumSha256: asString(asset.checksum_sha256) }]
          : [],
      ),
      target_duration_seconds:
        typeof profile.target_duration_seconds === "number"
          ? profile.target_duration_seconds
          : undefined,
      canvas: isRecord(profile.canvas)
        ? {
            width: asNumber(profile.canvas.width),
            height: asNumber(profile.canvas.height),
            fps: asNumber(profile.canvas.fps),
          }
        : undefined,
    },
    jobStatus: asString(value.job_status),
    currentStage: asOptionalString(value.current_stage),
    progressPercent: asNumber(value.progress_percent),
    errorMessage: asOptionalString(value.error_message),
    finalAssetId: asOptionalString(value.final_asset_id),
    qualityReport: qualityReport(quality),
    workflowStages: asArray(value.workflow_stages).flatMap((stage) =>
      isRecord(stage)
        ? [
            {
              stageName: asString(stage.stage_name),
              stageOrder: asNumber(stage.stage_order),
              status: asString(stage.status),
              attempt: asNumber(stage.attempt, 1),
              errorCode: asOptionalString(stage.error_code),
              errorMessage: asOptionalString(stage.error_message),
            },
          ]
        : [],
    ),
    artifacts: asArray(value.artifacts).flatMap((artifact) =>
      isRecord(artifact)
        ? [
            {
              artifact_key: asString(artifact.artifact_key),
              stage_name: asOptionalString(artifact.stage_name),
              download_url: asOptionalString(artifact.download_url),
              mime_type: asOptionalString(artifact.mime_type),
              file_size:
                typeof artifact.file_size === "number"
                  ? artifact.file_size
                  : undefined,
              checksum_sha256: asOptionalString(artifact.checksum_sha256),
            },
          ]
        : [],
    ),
    releaseCode: asOptionalString(value.release_code),
    releaseSnapshotArtifactCode: asOptionalString(
      value.release_snapshot_artifact_code,
    ),
    releaseManifestFingerprint: asOptionalString(
      value.release_manifest_fingerprint,
    ),
    release: release
      ? {
          releaseCode: asString(release.release_code),
          status: asString(release.status),
          manifestCode: asString(release.manifest_code),
          manifestFingerprint: asString(release.manifest_fingerprint),
          snapshotArtifactCode: asString(release.snapshot_artifact_code),
        }
      : undefined,
  };
}

function timelineRevision(value: unknown): VideoTimelineRevision {
  if (!isRecord(value)) throw new Error("时间轴修订响应无效");
  return {
    revisionNumber: asNumber(value.revision_number),
    productionTimeline: productionTimeline(value.production_timeline),
    actorId: asString(value.actor_id),
    createdAt: asString(value.created_at),
  };
}

export const functionalVideosApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.map(plan)),
  get: (code: string) => requestJson<unknown>(`${ROOT}/${code}`).then(plan),
  listTimelineRevisions: (code: string) =>
    requestJson<unknown[]>(`${ROOT}/${code}/timeline-revisions`).then((rows) =>
      rows.map(timelineRevision),
    ),
  create: (payload: {
    project_code?: string;
    live_room_plan_code?: string;
    title?: string;
    target_duration_seconds: number;
    visual_asset_codes?: string[];
  }) => postJson<unknown>(ROOT, payload).then(plan),
  updateTimeline: (
    code: string,
    payload: {
      expected_revision: number;
      poster_time_ms?: number;
      video_clips: Array<{
        clip_code: string;
        duration_ms: number;
        transition: string;
        source_start_seconds?: number;
        source_end_seconds?: number;
        fit?: "cover" | "contain";
        crop_x?: number;
        crop_y?: number;
        playback_rate?: number;
        show_product_sticker?: boolean;
      }>;
      subtitle_clips?: Array<{
        clip_code: string;
        subtitle_text: string;
        headline_text: string;
        caption_position: "bottom" | "center";
      }>;
      audio_clips?: Array<{ clip_code: string; gain_db: number }>;
    },
  ) =>
    requestJson<unknown>(`${ROOT}/${code}/timeline`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }).then(plan),
  restoreTimelineRevision: (
    code: string,
    sourceRevision: number,
    expectedRevision: number,
  ) =>
    postJson<unknown>(
      `${ROOT}/${code}/timeline-revisions/${sourceRevision}/restore`,
      { expected_revision: expectedRevision },
    ).then(plan),
  branch: (code: string, payload: { title?: string }) =>
    postJson<unknown>(`${ROOT}/${code}/branch`, payload).then(plan),
  createReleaseCandidate: (code: string) =>
    postJson<unknown>(`${ROOT}/${code}/release-candidate`, {}).then(plan),
  retry: (code: string) =>
    postJson<unknown>(`${ROOT}/${code}/retry`).then(plan),
};

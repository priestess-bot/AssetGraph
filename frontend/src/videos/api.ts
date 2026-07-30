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
  materialSelectionDecisionCode?: string;
  productionTimeline: {
    global_end_ms: number;
    poster_time_ms?: number;
    subtitle_style?: {
      preset: "compact" | "standard" | "large";
      safe_bottom_px: number;
    };
    tracks: Array<{
      track_kind: string;
      clips: Array<{
        clip_code: string;
        source_shot_code?: string;
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
        overlay_z_order?: {
          brand_logo?: number;
          product_sticker?: number;
        };
        product_sticker_layout?: {
          x: number;
          y: number;
          width_ratio: number;
        };
        product_sticker_layout_suggestion?: {
          x: number;
          y: number;
          width_ratio: number;
          source?: string;
          table_surface_name?: string;
          approximate?: boolean;
        };
        audio_roles?: string[];
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
    visualSelection?: {
      directAssetCodes: string[];
      groups: Array<{ groupCode: string; title: string; assetCodes: string[] }>;
      materialPacks: Array<{
        packCode: string;
        role: string;
        revisionNumber: number;
        fingerprintSha256: string;
        assetCodes: string[];
      }>;
    };
    brandLogo?: { assetCode: string; checksumSha256: string };
    productSticker?: { assetCode: string; checksumSha256: string };
    backgroundMusic?: {
      assetCode: string;
      checksumSha256: string;
      gainDb: number;
    };
    soundEffect?: {
      assetCode: string;
      checksumSha256: string;
      gainDb: number;
    };
    inheritedLiveRoomMaterialSnapshot?: {
      liveRoomPlanCode: string;
      productionVariantCode: string;
      productionVariantRevision: number;
      fingerprintSha256: string;
      assetCodes: string[];
    };
    target_duration_seconds?: number;
    canvas?: { width: number; height: number; fps: number };
  };
  jobStatus: string;
  currentStage?: string;
  progressPercent: number;
  errorCode?: string;
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
      frameRate?: number;
      videoStreamDurationSeconds?: number;
      audioStreamDurationSeconds?: number;
      audioVideoDeltaSeconds?: number;
    };
    loudness?: { integratedLufs?: number; truePeakDb?: number; lra?: number };
    diagnostics: {
      blackSegments: VideoQualitySegment[];
      silenceSegments: VideoQualitySegment[];
      freezeSegments: VideoQualitySegment[];
    };
    subtitleLayout?: {
      passed?: boolean;
      checks: Record<string, boolean>;
      safeMargins?: { left?: number; right?: number; bottom?: number; headlineTop?: number };
      requiredScriptBlockCodes: string[];
      coveredScriptBlockCodes: string[];
      missingScriptBlockCodes: string[];
      issues: Array<{ code: string; shotIndex?: number }>;
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
    metadata: Record<string, unknown>;
  }>;
  reproducibility: {
    timelineRevision: number;
    timelineFingerprintSha256: string;
    manifestCovers: string[];
    retryDifferenceRecorded: boolean;
    renderManifest?: VideoReproducibilityArtifact;
    renderManifestDifference?: VideoReproducibilityArtifact;
  };
  timelineSegments: Array<{
    segmentCode: string;
    clipCode: string;
    sourceShotCode: string;
    sourceScriptBlockCodes: string[];
    timelineStartMs: number;
    timelineEndMs: number;
    transition: string;
    fingerprintSha256: string;
    executionArtifactRefs: Array<{
      jobAttempt: number;
      artifactRole: string;
      artifactKey: string;
      relativePath: string;
      checksumSha256: string;
      evidence: Record<string, unknown>;
    }>;
    sourceAssetFileRefs: Array<{
      assetFileId: string;
      assetCode: string;
      fileRole: string;
      objectKey: string;
      checksumSha256: string;
    }>;
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

interface VideoReproducibilityArtifact {
  artifactKey: string;
  checksumSha256?: string;
  downloadUrl?: string;
  metadata: Record<string, unknown>;
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
  const subtitleLayout = isRecord(report.subtitle_layout) ? report.subtitle_layout : undefined;
  const safeMargins = subtitleLayout && isRecord(subtitleLayout.safe_margins)
    ? subtitleLayout.safe_margins
    : undefined;
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
          frameRate:
            typeof media.frame_rate === "number" ? media.frame_rate : undefined,
          videoStreamDurationSeconds:
            typeof media.video_stream_duration_seconds === "number"
              ? media.video_stream_duration_seconds
              : undefined,
          audioStreamDurationSeconds:
            typeof media.audio_stream_duration_seconds === "number"
              ? media.audio_stream_duration_seconds
              : undefined,
          audioVideoDeltaSeconds:
            typeof media.audio_video_delta_seconds === "number"
              ? media.audio_video_delta_seconds
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
    subtitleLayout: subtitleLayout
      ? {
          passed:
            typeof subtitleLayout.passed === "boolean" ? subtitleLayout.passed : undefined,
          checks: isRecord(subtitleLayout.checks)
            ? Object.fromEntries(
                Object.entries(subtitleLayout.checks).flatMap(([key, check]) =>
                  typeof check === "boolean" ? [[key, check]] : [],
                ),
              )
            : {},
          safeMargins: safeMargins
            ? {
                left: typeof safeMargins.left === "number" ? safeMargins.left : undefined,
                right: typeof safeMargins.right === "number" ? safeMargins.right : undefined,
                bottom: typeof safeMargins.bottom === "number" ? safeMargins.bottom : undefined,
                headlineTop:
                  typeof safeMargins.headline_top === "number"
                    ? safeMargins.headline_top
                    : undefined,
              }
            : undefined,
          requiredScriptBlockCodes: asArray(subtitleLayout.required_script_block_codes)
            .filter((code): code is string => typeof code === "string"),
          coveredScriptBlockCodes: asArray(subtitleLayout.covered_script_block_codes)
            .filter((code): code is string => typeof code === "string"),
          missingScriptBlockCodes: asArray(subtitleLayout.missing_script_block_codes)
            .filter((code): code is string => typeof code === "string"),
          issues: asArray(subtitleLayout.issues).flatMap((issue) =>
            isRecord(issue) && typeof issue.code === "string"
              ? [{
                  code: issue.code,
                  shotIndex:
                    typeof issue.shot_index === "number" ? issue.shot_index : undefined,
                }]
              : [],
          ),
        }
      : undefined,
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
    subtitle_style:
      isRecord(timeline.subtitle_style) &&
      (timeline.subtitle_style.preset === "compact" ||
        timeline.subtitle_style.preset === "standard" ||
        timeline.subtitle_style.preset === "large") &&
      typeof timeline.subtitle_style.safe_bottom_px === "number"
        ? {
            preset: timeline.subtitle_style.preset,
            safe_bottom_px: timeline.subtitle_style.safe_bottom_px,
          }
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
                        source_shot_code: asOptionalString(
                          clip.source_shot_code,
                        ),
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
                        overlay_z_order: isRecord(clip.overlay_z_order)
                          ? {
                              ...(typeof clip.overlay_z_order.brand_logo ===
                              "number"
                                ? {
                                    brand_logo:
                                      clip.overlay_z_order.brand_logo,
                                  }
                                : {}),
                              ...(typeof clip.overlay_z_order
                                .product_sticker === "number"
                                ? {
                                    product_sticker:
                                      clip.overlay_z_order.product_sticker,
                                  }
                                : {}),
                            }
                          : undefined,
                        product_sticker_layout: isRecord(
                          clip.product_sticker_layout,
                        ) &&
                          typeof clip.product_sticker_layout.x === "number" &&
                          typeof clip.product_sticker_layout.y === "number" &&
                          typeof clip.product_sticker_layout.width_ratio ===
                            "number"
                          ? {
                              x: clip.product_sticker_layout.x,
                              y: clip.product_sticker_layout.y,
                              width_ratio:
                                clip.product_sticker_layout.width_ratio,
                            }
                          : undefined,
                        product_sticker_layout_suggestion: isRecord(
                          clip.product_sticker_layout_suggestion,
                        ) &&
                          typeof clip.product_sticker_layout_suggestion.x ===
                            "number" &&
                          typeof clip.product_sticker_layout_suggestion.y ===
                            "number" &&
                          typeof clip.product_sticker_layout_suggestion
                            .width_ratio === "number"
                          ? {
                              x: clip.product_sticker_layout_suggestion.x,
                              y: clip.product_sticker_layout_suggestion.y,
                              width_ratio:
                                clip.product_sticker_layout_suggestion
                                  .width_ratio,
                              source: asOptionalString(
                                clip.product_sticker_layout_suggestion.source,
                              ),
                              table_surface_name: asOptionalString(
                                clip.product_sticker_layout_suggestion
                                  .table_surface_name,
                              ),
                              approximate:
                                clip.product_sticker_layout_suggestion
                                  .approximate === true,
                            }
                          : undefined,
                        audio_roles: Array.isArray(clip.audio_roles)
                          ? asArray(clip.audio_roles).flatMap((role) =>
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
  const visualSelection = isRecord(profile.visual_selection)
    ? profile.visual_selection
    : {};
  const inheritedLiveRoomSnapshot = isRecord(
    profile.inherited_live_room_material_snapshot,
  )
    ? profile.inherited_live_room_material_snapshot
    : undefined;
  const quality = isRecord(value.quality_report) ? value.quality_report : {};
  const release = isRecord(value.release) ? value.release : undefined;
  const reproducibility = isRecord(value.reproducibility)
    ? value.reproducibility
    : {};
  const reproducibilityArtifact = (
    artifact: unknown,
  ): VideoReproducibilityArtifact | undefined =>
    isRecord(artifact) && asString(artifact.artifact_key)
      ? {
          artifactKey: asString(artifact.artifact_key),
          checksumSha256: asOptionalString(artifact.checksum_sha256),
          downloadUrl: asOptionalString(artifact.download_url),
          metadata: isRecord(artifact.metadata) ? artifact.metadata : {},
        }
      : undefined;
  return {
    planCode: code,
    projectCode: asString(value.project_code),
    variantCode: asString(value.variant_code),
    videoJobCode: asString(value.video_job_code),
    title: asString(value.title),
    timelineRevision: asNumber(value.timeline_revision, 1),
    materialSelectionDecisionCode: asOptionalString(
      value.material_selection_decision_code,
    ),
    productionTimeline: productionTimeline(value.production_timeline),
    renderProfile: {
      visual_asset_mode: asOptionalString(profile.visual_asset_mode),
      visualAssets: asArray(profile.visual_assets).flatMap((asset) =>
        isRecord(asset) && asString(asset.asset_code) && asString(asset.checksum_sha256)
          ? [{ assetCode: asString(asset.asset_code), checksumSha256: asString(asset.checksum_sha256) }]
          : [],
      ),
      visualSelection: {
        directAssetCodes: asArray(visualSelection.direct_asset_codes).flatMap(
          (code) => (typeof code === "string" ? [code] : []),
        ),
        groups: asArray(visualSelection.group_refs).flatMap((group) =>
          isRecord(group) && asString(group.group_code)
            ? [{
                groupCode: asString(group.group_code),
                title: asString(group.title, asString(group.group_code)),
                assetCodes: asArray(group.asset_codes).flatMap((code) =>
                  typeof code === "string" ? [code] : [],
                ),
              }]
            : [],
        ),
        materialPacks: asArray(visualSelection.material_pack_refs).flatMap(
          (pack) =>
            isRecord(pack) && asString(pack.pack_code)
              ? [{
                  packCode: asString(pack.pack_code),
                  role: asString(pack.role),
                  revisionNumber: asNumber(pack.revision_number),
                  fingerprintSha256: asString(pack.fingerprint_sha256),
                  assetCodes: asArray(pack.resolved_asset_codes).flatMap(
                    (code) => (typeof code === "string" ? [code] : []),
                  ),
                }]
              : [],
        ),
      },
      brandLogo:
        isRecord(profile.brand_logo) &&
        asString(profile.brand_logo.asset_code) &&
        asString(profile.brand_logo.checksum_sha256)
          ? {
              assetCode: asString(profile.brand_logo.asset_code),
              checksumSha256: asString(profile.brand_logo.checksum_sha256),
            }
          : undefined,
      productSticker:
        isRecord(profile.product_sticker) &&
        asString(profile.product_sticker.asset_code) &&
        asString(profile.product_sticker.checksum_sha256)
          ? {
              assetCode: asString(profile.product_sticker.asset_code),
              checksumSha256: asString(profile.product_sticker.checksum_sha256),
            }
          : undefined,
      backgroundMusic:
        isRecord(profile.background_music) &&
        asString(profile.background_music.asset_code) &&
        asString(profile.background_music.checksum_sha256)
          ? {
              assetCode: asString(profile.background_music.asset_code),
              checksumSha256: asString(profile.background_music.checksum_sha256),
              gainDb: asNumber(profile.background_music.gain_db),
            }
          : undefined,
      soundEffect:
        isRecord(profile.sound_effect) &&
        asString(profile.sound_effect.asset_code) &&
        asString(profile.sound_effect.checksum_sha256)
          ? {
              assetCode: asString(profile.sound_effect.asset_code),
              checksumSha256: asString(profile.sound_effect.checksum_sha256),
              gainDb: asNumber(profile.sound_effect.gain_db),
            }
          : undefined,
      inheritedLiveRoomMaterialSnapshot:
        inheritedLiveRoomSnapshot &&
        asString(inheritedLiveRoomSnapshot.live_room_plan_code) &&
        asString(inheritedLiveRoomSnapshot.fingerprint_sha256)
          ? {
              liveRoomPlanCode: asString(
                inheritedLiveRoomSnapshot.live_room_plan_code,
              ),
              productionVariantCode: asString(
                inheritedLiveRoomSnapshot.production_variant_code,
              ),
              productionVariantRevision: asNumber(
                inheritedLiveRoomSnapshot.production_variant_revision,
              ),
              fingerprintSha256: asString(
                inheritedLiveRoomSnapshot.fingerprint_sha256,
              ),
              assetCodes: asArray(
                inheritedLiveRoomSnapshot.asset_codes,
              ).flatMap((code) => (typeof code === "string" ? [code] : [])),
            }
          : undefined,
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
    errorCode: asOptionalString(value.error_code),
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
              metadata: isRecord(artifact.metadata) ? artifact.metadata : {},
            },
          ]
          : [],
    ),
    reproducibility: {
      timelineRevision: asNumber(
        reproducibility.timeline_revision,
        asNumber(value.timeline_revision, 1),
      ),
      timelineFingerprintSha256: asString(
        reproducibility.timeline_fingerprint_sha256,
      ),
      manifestCovers: asArray(reproducibility.manifest_covers).flatMap(
        (item) => (typeof item === "string" ? [item] : []),
      ),
      retryDifferenceRecorded:
        reproducibility.retry_difference_recorded === true,
      renderManifest: reproducibilityArtifact(
        reproducibility.render_manifest,
      ),
      renderManifestDifference: reproducibilityArtifact(
        reproducibility.render_manifest_difference,
      ),
    },
    timelineSegments: asArray(value.timeline_segments).flatMap((segment) =>
      isRecord(segment) &&
      asString(segment.segment_code) &&
      asString(segment.clip_code) &&
      asString(segment.source_shot_code)
        ? [
            {
              segmentCode: asString(segment.segment_code),
              clipCode: asString(segment.clip_code),
              sourceShotCode: asString(segment.source_shot_code),
              sourceScriptBlockCodes: asArray(
                segment.source_script_block_codes,
              ).flatMap((code) => (typeof code === "string" ? [code] : [])),
              timelineStartMs: asNumber(segment.timeline_start_ms),
              timelineEndMs: asNumber(segment.timeline_end_ms),
              transition: asString(segment.transition, "cut"),
              fingerprintSha256: asString(segment.fingerprint_sha256),
              executionArtifactRefs: asArray(
                segment.execution_artifact_refs,
              ).flatMap((artifact) =>
                isRecord(artifact) &&
                asString(artifact.artifact_role) &&
                asString(artifact.artifact_key) &&
                asString(artifact.relative_path) &&
                asString(artifact.checksum_sha256)
                  ? [{
                      jobAttempt: asNumber(artifact.job_attempt, 1),
                      artifactRole: asString(artifact.artifact_role),
                      artifactKey: asString(artifact.artifact_key),
                      relativePath: asString(artifact.relative_path),
                      checksumSha256: asString(artifact.checksum_sha256),
                      evidence: isRecord(artifact.evidence) ? artifact.evidence : {},
                    }]
                  : [],
              ),
              sourceAssetFileRefs: asArray(
                segment.source_asset_file_refs,
              ).flatMap((assetFile) =>
                isRecord(assetFile) &&
                asString(assetFile.asset_file_id) &&
                asString(assetFile.asset_code) &&
                asString(assetFile.file_role) &&
                asString(assetFile.object_key) &&
                asString(assetFile.checksum_sha256)
                  ? [{
                      assetFileId: asString(assetFile.asset_file_id),
                      assetCode: asString(assetFile.asset_code),
                      fileRole: asString(assetFile.file_role),
                      objectKey: asString(assetFile.object_key),
                      checksumSha256: asString(assetFile.checksum_sha256),
                    }]
                  : [],
              ),
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
    visual_group_codes?: string[];
    visual_material_pack_codes?: string[];
    brand_logo_asset_code?: string;
    product_sticker_asset_code?: string;
    background_music_asset_code?: string;
    background_music_gain_db?: number;
    sound_effect_asset_code?: string;
    sound_effect_gain_db?: number;
  }) => postJson<unknown>(ROOT, payload).then(plan),
  updateTimeline: (
    code: string,
    payload: {
      expected_revision: number;
      poster_time_ms?: number;
      subtitle_style?: {
        preset: "compact" | "standard" | "large";
        safe_bottom_px: number;
      };
      video_clips: Array<{
        clip_code: string;
        duration_ms: number;
        transition: string;
        source_asset_code?: string;
        source_start_seconds?: number;
        source_end_seconds?: number;
        fit?: "cover" | "contain";
        crop_x?: number;
        crop_y?: number;
        playback_rate?: number;
        show_brand_logo?: boolean;
        show_product_sticker?: boolean;
        product_sticker_x?: number;
        product_sticker_y?: number;
        product_sticker_width_ratio?: number;
        play_sound_effect?: boolean;
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

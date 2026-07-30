import type { Tone } from "../workbench/components";

export type WatchTargetStatus = "enabled" | "paused" | "blocked" | "deleted";
export type CaptureSessionStatus = "starting" | "recording" | "finalizing" | "completed" | "failed" | "abandoned";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type TemplateRevisionStatus = "draft" | "published" | "superseded" | "rejected";
export type TemplateStatus = "draft" | "published" | "archived";
export type LayoutFidelity = "none" | "approximate" | "verified_layout";
export type Buildability = "reference_only" | "executable";
export type ContentReadiness = "blocked" | "review_required" | "ready";
export type TemplateKind = "layout_hypothesis" | "content_strategy";

export interface ResearchOverview {
  enabled_target_count: number;
  live_target_count: number;
  recording_session_count: number;
  analysis_queue_count: number;
  draft_template_count: number;
  expiring_recording_count: number;
}

export interface WatchTarget {
  target_code: string;
  platform: "douyin";
  display_name: string;
  room_url: string;
  room_id?: string;
  account_name?: string;
  status: WatchTargetStatus;
  live_state: "offline" | "live_detected" | "recording" | "unknown";
  recorder_health: "healthy" | "degraded" | "offline" | "unknown";
  interaction_health: "healthy" | "degraded" | "offline" | "unknown";
  last_live_at?: string;
  last_checked_at?: string;
  next_retry_at?: string;
  failure_reason?: string;
  created_at?: string;
}

export interface CaptureSession {
  session_code: string;
  target_code: string;
  title: string;
  status: CaptureSessionStatus;
  started_at?: string;
  finalized_at?: string;
  duration_seconds: number;
  playback_url?: string;
  poster_url?: string;
  expires_at?: string;
  recording_available: boolean;
  recorder_health: "healthy" | "degraded" | "failed";
  interaction_health: "healthy" | "degraded" | "failed";
  interaction_event_count: number;
  analysis_status?: JobStatus;
  template_code?: string;
  source_type?: "uploaded_recording" | "platform_capture";
  analysis_status_counts?: Record<string, number>;
  media_chunks?: Array<{
    chunk_code: string;
    media_url: string;
    global_start_seconds: number;
    global_end_seconds: number;
    chunk_start_seconds: number;
  }>;
}

export interface RecordingUploadReceipt {
  session_code: string;
  target_code: string;
  source_room_id: string;
  source_room_title: string;
  file_name: string;
  file_size: number;
  checksum_sha256: string;
  duration_seconds: number;
  upload_status: "stored";
  analysis_status: "queued";
  queued_analysis_types: string[];
  created_at: string;
}

export interface AsrSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
  confidence?: number;
}

export interface VisualSegment {
  start_seconds: number;
  end_seconds: number;
  label: string;
  confidence?: number;
  composition?: string;
}

export interface InteractionBucket {
  start_seconds: number;
  end_seconds: number;
  total_count: number;
  dominant_type?: string;
  summary?: string;
}

export interface Keyframe {
  at_seconds: number;
  thumbnail_url?: string;
  label?: string;
}

export interface CaptureTimeline {
  session_code: string;
  duration_seconds: number;
  asr_segments: AsrSegment[];
  visual_segments: VisualSegment[];
  interaction_buckets: InteractionBucket[];
  keyframes: Keyframe[];
  media_gaps: Array<{ start_seconds: number; end_seconds: number; reason?: string }>;
}

export interface ClipJob {
  clip_job_code: string;
  session_code: string;
  in_seconds: number;
  out_seconds: number;
  title: string;
  status: JobStatus;
  permanent: boolean;
  clip_code?: string;
  playback_url?: string;
  checksum_sha256?: string;
  error_message?: string;
  created_at?: string;
}

export interface AnalysisRun {
  analysis_run_code: string;
  session_code: string;
  status: JobStatus;
  progress_percent: number;
  asr_status: JobStatus;
  visual_status: JobStatus;
  structure_status: JobStatus;
  result_template_code?: string;
  error_message?: string;
  failed_steps?: Array<{
    analysis_run_code: string;
    analysis_type: string;
    error_message: string;
    can_retry: boolean;
  }>;
  updated_at?: string;
}

export interface InferredComponent {
  component_code?: string;
  role: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  confidence?: number;
}

export interface TemplateScene {
  scene_code?: string;
  title: string;
  start_seconds: number;
  end_seconds: number;
  purpose: string;
  script_pattern?: string;
  interaction_cue?: string;
  material_slots: string[];
  components: InferredComponent[];
}

export interface TemplateRevision {
  revision: number;
  status: TemplateStatus;
  layout_fidelity: LayoutFidelity;
  buildability: Buildability;
  contentReadiness: ContentReadiness;
  sourceSessionCodes: string[];
  contentStrategy: ContentStrategy;
  scenes: TemplateScene[];
  reviewer_note?: string;
  created_at?: string;
  published_at?: string;
}

export interface ContentStrategy {
  targetCategory: string;
  compatibilityTags: string[];
  programOutline: Array<{ moduleKey: string; title: string; purpose: string; sourceSessionCode?: string; startMs: number; endMs: number }>;
  durationPolicy: {
    targetDurationSeconds?: number;
    pacing?: string;
  };
  moduleRecipes: Array<{ moduleKey: string; guidance: string }>;
  productRotationPolicy: {
    cadence?: string;
    maxProductsPerModule?: number;
  };
  interactionPolicy: {
    cadence?: string;
    promptFocus?: string;
  };
  conversionPolicy: {
    ctaStyle?: string;
    ctaCadence?: string;
  };
  hostStyle: {
    tone?: string;
    delivery?: string;
  };
  materialCues: string[];
  reviewedExamples: Array<{ moduleKey: string; exampleText: string; sourceSessionCode: string; startMs: number; endMs: number }>;
  removedSourceFactCategories: string[];
}

export interface RoomTemplate {
  template_code: string;
  title: string;
  source_session_code: string;
  source_type: "external_flat_video" | "maitu_verified";
  templateKind: TemplateKind;
  sourceTargetCode?: string;
  latest_revision: number;
  published_revision?: number;
  status: TemplateStatus;
  layout_fidelity: LayoutFidelity;
  buildability: Buildability;
  contentReadiness: ContentReadiness;
  contentStrategy: ContentStrategy;
  scenes: TemplateScene[];
  source_playback_url?: string;
  published_version_code?: string;
  archived_at?: string;
  archive_reason?: string;
  updated_at?: string;
}

export interface TemplateProjection {
  template_code: string;
  revision: number;
  source_session_code?: string;
  projection_fingerprint?: string;
  production_eligible: boolean;
  reference_capabilities: string[];
  executable_capabilities: string[];
  blocked_operations: string[];
  warnings: string[];
  scenes?: TemplateScene[];
}

export const SESSION_STATUS_META: Record<CaptureSessionStatus, { label: string; tone: Tone }> = {
  starting: { label: "启动采集", tone: "warning" },
  recording: { label: "录制中", tone: "info" },
  finalizing: { label: "正在封装", tone: "warning" },
  completed: { label: "可分析", tone: "success" },
  failed: { label: "采集失败", tone: "danger" },
  abandoned: { label: "已放弃", tone: "neutral" },
};

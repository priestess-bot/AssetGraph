import type { Tone } from "../workbench/components";

export type FactVersionStatus = "draft" | "approved" | "rejected" | "superseded";
export type InventoryJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type RunStatus = "draft" | "planning" | "ready" | "blocked" | "replan_required" | "preflight_passed" | "execution_queued" | "executing" | "completed" | "failed";
export type RequirementDecisionKind = "selected" | "deferred" | "waived";
export type PlanStatus = "ready" | "blocked" | "failed" | "superseded";
export type DraftExecutionStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface FactCardVersion {
  version: number;
  status: FactVersionStatus;
  verified_facts: string[];
  selling_points: string[];
  prohibited_claims: string[];
  source_notes?: string;
  approved_at?: string;
  created_at?: string;
}

export interface ProductFactCard {
  fact_card_code: string;
  title: string;
  product_name: string;
  product_code?: string;
  current_version: number;
  approved_version?: number;
  status: FactVersionStatus;
  verified_facts: string[];
  positioning: string;
  versions?: FactCardVersion[];
  updated_at?: string;
}

export interface InventorySnapshot {
  snapshot_code: string;
  fingerprint: string;
  quality: "complete" | "partial";
  item_count: number;
  category_counts: Record<string, number>;
  created_at?: string;
}

export interface InventorySyncJob {
  sync_job_code: string;
  status: InventoryJobStatus;
  source: string;
  progress_percent: number;
  discovered_count: number;
  imported_count: number;
  failed_count: number;
  error_message?: string;
  snapshot?: InventorySnapshot;
  created_at?: string;
  updated_at?: string;
}

export interface AssetCandidate {
  asset_code?: string;
  material_key?: string;
  title: string;
  category?: string;
  match_score?: number;
  analysis_source?: string;
}

export interface RequirementDecision {
  revision: number;
  decision: RequirementDecisionKind;
  selected_asset_code?: string;
  selected_material_key?: string;
  reason?: string;
  decided_at?: string;
}

export interface ProductionRequirement {
  requirement_code: string;
  scene_name: string;
  label: string;
  need_type: string;
  category?: string;
  priority: "critical" | "required" | "optional";
  status: "open" | "decided" | "blocked";
  description?: string;
  candidates: AssetCandidate[];
  decision?: RequirementDecision;
}

export interface PlanGap {
  code: string;
  severity: "critical" | "warning" | "info";
  message: string;
  requirement_code?: string;
}

export interface PlanRevision {
  revision: number;
  status: PlanStatus;
  input_fingerprint?: string;
  build_plan_code?: string;
  can_execute: boolean;
  scene_count: number;
  selected_count: number;
  missing_count: number;
  gaps: PlanGap[];
  scenes: Array<{
    scene_name: string;
    scene_goal: string;
    duration_seconds: number;
    script: string;
    composition_intent?: string;
    material_intents: string[];
  }>;
  generation?: {
    provider: string;
    model: string;
    prompt_version: string;
    latency_ms: number;
  };
  created_at?: string;
}

export interface PreflightCheck {
  check_code: string;
  label: string;
  status: "passed" | "blocked" | "warning";
  detail?: string;
}

export interface PreflightResult {
  status: "passed" | "blocked";
  expected_plan_revision: number;
  checks: PreflightCheck[];
  checked_at?: string;
}

export interface DraftExecutionJob {
  execution_job_code: string;
  status: DraftExecutionStatus;
  plan_revision: number;
  build_plan_code?: string;
  result_summary?: string;
  ready_for_go_live: false;
  created_at?: string;
  updated_at?: string;
}

export interface ProductionRun {
  run_code: string;
  title: string;
  topic?: string;
  status: RunStatus;
  fact_card_code: string;
  fact_card_version?: number;
  inventory_snapshot_code: string;
  target_live_room_id?: string;
  target_duration_minutes: number;
  build_mode: string;
  current_plan_revision: number;
  reference_template_code?: string;
  reference_template_revision_number?: number;
  reference_template_projection_fingerprint?: string;
  open_requirement_count: number;
  critical_conflict_count: number;
  preflight?: PreflightResult;
  draft_execution?: DraftExecutionJob;
  created_at?: string;
  updated_at?: string;
}

export interface ReferenceTemplatePin {
  reference_template_code: string;
  reference_template_revision_number?: number;
  reference_template_projection_fingerprint?: string;
}

export type GeminiJobStatus = "not_requested" | "queued" | "running" | "succeeded" | "failed";

export interface VideoAnalysisItem {
  analysis_code: string;
  run_code: string;
  requirement_code?: string;
  asset_code: string;
  asset_fingerprint?: string;
  asset_title: string;
  selected: boolean;
  provisional_source: "keyframe" | "gpt_5_6_sol" | "none";
  provisional_summary?: string;
  gemini_status: GeminiJobStatus;
  gemini_summary?: string;
  conflict_count: number;
  updated_at?: string;
}

export interface AnalysisConflict {
  conflict_code: string;
  analysis_code: string;
  field: string;
  severity: "critical" | "warning";
  provisional_value?: string;
  gemini_value?: string;
  resolution?: "provisional" | "gemini" | "replace_asset";
}

export const RUN_STATUS_META: Record<RunStatus, { label: string; tone: Tone }> = {
  draft: { label: "待规划", tone: "neutral" },
  planning: { label: "规划中", tone: "info" },
  ready: { label: "计划就绪", tone: "success" },
  blocked: { label: "存在阻断", tone: "danger" },
  replan_required: { label: "需要重新规划", tone: "warning" },
  preflight_passed: { label: "预检通过", tone: "success" },
  execution_queued: { label: "草稿排队中", tone: "warning" },
  executing: { label: "写入草稿", tone: "info" },
  completed: { label: "草稿已写入", tone: "success" },
  failed: { label: "执行失败", tone: "danger" },
};

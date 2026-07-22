import {
  asArray,
  asBoolean,
  asNumber,
  asOptionalString,
  asString,
  isRecord,
  patchJson,
  postJson,
  requestJson,
} from "../workbench/api";
import type {
  AnalysisConflict,
  AssetCandidate,
  DraftExecutionJob,
  FactCardVersion,
  GeminiJobStatus,
  InventorySnapshot,
  InventorySyncJob,
  PlanGap,
  PlanRevision,
  PreflightCheck,
  PreflightResult,
  ProductFactCard,
  ProductionRequirement,
  ProductionRun,
  RequirementDecision,
  VideoAnalysisItem,
} from "./types";

const ROOT = "/api/maitu/workbench";

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
}

function normalizeFactVersion(value: unknown): FactCardVersion | undefined {
  if (!isRecord(value)) return undefined;
  const content = isRecord(value.content) ? value.content : value;
  const status = asString(value.status, "draft") as FactCardVersion["status"];
  return {
    version: asNumber(value.version ?? value.version_number, 1),
    status,
    verified_facts: strings(content.verified_facts ?? content.facts),
    selling_points: strings(content.asset_keywords ?? content.selling_points),
    prohibited_claims: strings(content.compliance_notes ?? content.prohibited_claims),
    source_notes: asOptionalString(value.change_reason ?? content.source_notes),
    approved_at: asOptionalString(value.approved_at),
    created_at: asOptionalString(value.created_at),
  };
}

export function normalizeFactCard(value: unknown): ProductFactCard {
  if (!isRecord(value)) throw new Error("Invalid fact card response");
  const versions = asArray(value.versions).flatMap((item) => {
    const version = normalizeFactVersion(item);
    return version ? [version] : [];
  });
  const approvedVersion = asNumber(value.current_approved_version);
  const latestPersistedVersion = versions.reduce<FactCardVersion | undefined>(
    (latest, item) => !latest || item.version > latest.version ? item : latest,
    undefined,
  );
  const current = normalizeFactVersion(value.current_version_payload ?? value.latest_version)
    ?? latestPersistedVersion
    ?? versions.find((item) => item.version === approvedVersion);
  const currentRaw = asArray(value.versions).find((item) => isRecord(item) && asNumber(item.version_number) === current?.version);
  const content = isRecord(currentRaw) && isRecord(currentRaw.content) ? currentRaw.content : isRecord(value.content) ? value.content : {};
  return {
    fact_card_code: asString(value.fact_card_code ?? value.card_code),
    title: asString(value.title, asString(value.product_name, "未命名事实卡")),
    product_name: asString(value.product_name ?? content.product_name, "未命名商品"),
    product_code: asOptionalString(value.product_code),
    current_version: asNumber(value.current_version ?? current?.version ?? value.current_approved_version, 1),
    approved_version: approvedVersion || undefined,
    status: (current?.status ?? (approvedVersion > 0 ? "approved" : "draft")) as ProductFactCard["status"],
    verified_facts: strings(value.verified_facts ?? content.verified_facts ?? current?.verified_facts),
    positioning: asString(value.positioning ?? content.positioning, "待补充商品定位"),
    versions,
    updated_at: asOptionalString(value.updated_at),
  };
}

function normalizeSnapshot(value: unknown): InventorySnapshot | undefined {
  if (!isRecord(value)) return undefined;
  const categoryCounts: Record<string, number> = {};
  const summary = isRecord(value.summary) ? value.summary : {};
  const rawCategoryCounts = isRecord(value.category_counts) ? value.category_counts : isRecord(summary.category_counts) ? summary.category_counts : {};
  if (isRecord(rawCategoryCounts)) {
    Object.entries(rawCategoryCounts).forEach(([key, item]) => { categoryCounts[key] = asNumber(item); });
  }
  return {
    snapshot_code: asString(value.snapshot_code),
    fingerprint: asString(value.fingerprint ?? value.snapshot_fingerprint ?? value.fingerprint_sha256),
    quality: asString(value.quality ?? value.snapshot_quality ?? value.quality_status, "partial") === "complete" ? "complete" : "partial",
    item_count: asNumber(value.item_count ?? value.total_count),
    category_counts: categoryCounts,
    created_at: asOptionalString(value.created_at),
  };
}

export function normalizeInventoryJob(value: unknown): InventorySyncJob {
  if (!isRecord(value)) throw new Error("Invalid inventory job response");
  const resultSummary = isRecord(value.result_summary) ? value.result_summary : {};
  const status = asString(value.status, "queued") as InventorySyncJob["status"];
  return {
    sync_job_code: asString(value.sync_job_code ?? value.job_code),
    status,
    source: asString(value.source ?? value.source_system, "maitu"),
    progress_percent: Math.min(100, Math.max(0, asNumber(value.progress_percent, status === "succeeded" ? 100 : status === "running" ? 50 : 0))),
    discovered_count: asNumber(value.discovered_count ?? value.total_count ?? resultSummary.discovered_count ?? (isRecord(value.snapshot) ? value.snapshot.item_count : undefined)),
    imported_count: asNumber(value.imported_count ?? value.succeeded_count ?? resultSummary.imported_count ?? (isRecord(value.snapshot) ? value.snapshot.item_count : undefined)),
    failed_count: asNumber(value.failed_count ?? resultSummary.failed_count),
    error_message: asOptionalString(value.error_message),
    snapshot: normalizeSnapshot(value.snapshot ?? value.inventory_snapshot),
    created_at: asOptionalString(value.created_at),
    updated_at: asOptionalString(value.updated_at),
  };
}

function normalizeCandidate(value: unknown): AssetCandidate | undefined {
  if (!isRecord(value)) return undefined;
  return {
    asset_code: asOptionalString(value.asset_code ?? value.selected_asset_code),
    material_key: asOptionalString(value.material_key ?? value.maitu_material_key ?? value.selected_material_key),
    title: asString(value.title ?? value.asset_title ?? value.selected_asset_title ?? value.original_filename ?? value.selected_asset_original_filename, "未命名素材"),
    category: asOptionalString(value.category ?? value.maitu_category ?? value.required_category ?? value.selected_asset_source_material_type),
    match_score: typeof value.match_score === "number" ? value.match_score : undefined,
    analysis_source: asOptionalString(value.analysis_source ?? value.selected_asset_analysis_source),
  };
}

function normalizeDecision(value: unknown): RequirementDecision | undefined {
  if (!isRecord(value)) return undefined;
  return {
    revision: asNumber(value.revision ?? value.decision_revision ?? value.revision_number, 1),
    decision: asString(value.decision, "deferred") as RequirementDecision["decision"],
    selected_asset_code: asOptionalString(value.selected_asset_code),
    selected_material_key: asOptionalString(value.selected_material_key),
    reason: asOptionalString(value.reason),
    decided_at: asOptionalString(value.decided_at ?? value.created_at),
  };
}

export function normalizeRequirement(value: unknown): ProductionRequirement {
  if (!isRecord(value)) throw new Error("Invalid requirement response");
  const pipelineSelection = isRecord(value.pipeline_selection) ? value.pipeline_selection : {};
  const rawCandidates = asArray(value.candidates ?? pipelineSelection.candidates);
  const selectedCandidate = normalizeCandidate(pipelineSelection);
  const decisions = asArray(value.decisions).flatMap((item) => { const decision = normalizeDecision(item); return decision ? [decision] : []; });
  const currentDecision = normalizeDecision(value.decision ?? value.current_decision) ?? decisions.at(-1);
  const rawPriority = asString(value.priority, "medium");
  const priority = rawPriority === "high" ? "critical" : rawPriority === "low" ? "optional" : "required";
  const rawStatus = asString(value.status, currentDecision ? "selected" : "pending");
  return {
    requirement_code: asString(value.requirement_code ?? value.code),
    scene_name: asString(value.scene_name, "全局"),
    label: asString(value.label ?? value.description ?? value.need_type, "素材需求"),
    need_type: asString(value.need_type, "material"),
    category: asOptionalString(value.category ?? value.required_category),
    priority,
    status: (rawStatus === "missing" ? "blocked" : currentDecision || ["selected", "deferred", "waived"].includes(rawStatus) ? "decided" : "open") as ProductionRequirement["status"],
    description: asOptionalString(value.description),
    candidates: rawCandidates.flatMap((item) => {
      const candidate = normalizeCandidate(item);
      return candidate ? [candidate] : [];
    }).concat(selectedCandidate?.asset_code || selectedCandidate?.material_key ? [selectedCandidate] : []),
    decision: currentDecision,
  };
}

function normalizeGap(value: unknown): PlanGap | undefined {
  if (!isRecord(value)) return undefined;
  const needType = asString(value.need_type, "material");
  const requiredCategory = asString(value.required_category, needType);
  const blocksAutoBuild = asBoolean(value.blocks_auto_build);
  const descriptions = strings(value.descriptions);
  const fallback = asOptionalString(value.fallback_strategy);
  return {
    code: asString(value.code ?? value.gap_code, `missing_${needType}_${requiredCategory}`),
    severity: asString(value.severity, blocksAutoBuild ? "critical" : "warning") as PlanGap["severity"],
    message: asString(value.message ?? value.description ?? fallback ?? descriptions[0], `缺少 ${requiredCategory} 素材`),
    requirement_code: asOptionalString(value.requirement_code),
  };
}

export function normalizePlanRevision(value: unknown): PlanRevision {
  if (!isRecord(value)) throw new Error("Invalid plan response");
  const gapReport = isRecord(value.gap_report) ? value.gap_report : {};
  const pipelineOutput = isRecord(value.pipeline_output) ? value.pipeline_output : {};
  const modelPlan = isRecord(pipelineOutput.model_plan) ? pipelineOutput.model_plan : {};
  const assetSelections = isRecord(pipelineOutput.asset_selection_plan) ? pipelineOutput.asset_selection_plan : {};
  const modelScenes = asArray(modelPlan.scenes).flatMap((item) => {
    if (!isRecord(item)) return [];
    const materialIntents = asArray(item.material_intents).flatMap((intent) => {
      if (typeof intent === "string") return intent.trim() ? [intent] : [];
      if (!isRecord(intent)) return [];
      const label = asString(intent.label ?? intent.description ?? intent.need_type ?? intent.role);
      return label ? [label] : [];
    });
    return [{
      scene_name: asString(item.scene_name, "未命名场景"),
      scene_goal: asString(item.scene_goal, "待确认"),
      duration_seconds: asNumber(item.duration_seconds),
      script: asString(item.script),
      composition_intent: asOptionalString(item.composition_intent),
      material_intents: materialIntents,
    }];
  });
  const gapSource = value.gaps ?? gapReport.gaps;
  const blockedReasons = strings(value.blocked_reasons);
  const status = asString(value.status, "blocked") as PlanRevision["status"];
  return {
    revision: asNumber(value.revision ?? value.plan_revision ?? value.revision_number, 1),
    status,
    input_fingerprint: asOptionalString(value.input_fingerprint),
    build_plan_code: asOptionalString(value.build_plan_code ?? value.source_build_plan_code ?? (isRecord(value.build_plan) ? value.build_plan.build_plan_code : undefined)),
    can_execute: asBoolean(value.can_execute, status === "ready" && blockedReasons.length === 0),
    scene_count: asNumber(value.scene_count ?? pipelineOutput.scene_count ?? modelPlan.scene_count, modelScenes.length),
    selected_count: asNumber(value.selected_count ?? pipelineOutput.selected_count ?? assetSelections.selected_count),
    missing_count: asNumber(value.missing_count ?? pipelineOutput.missing_count ?? assetSelections.missing_count ?? gapReport.missing_count),
    gaps: asArray(gapSource).flatMap((item) => {
      const gap = normalizeGap(item);
      return gap ? [gap] : [];
    }).concat(blockedReasons.map((message, index) => ({ code: `BLOCKED_${index + 1}`, severity: "critical" as const, message }))),
    scenes: modelScenes,
    generation: {
      provider: asString(value.generation_provider, "unknown"),
      model: asString(value.generation_actual_model ?? value.generation_requested_model, "unknown"),
      prompt_version: asString(value.generation_prompt_version, "unknown"),
      latency_ms: asNumber(value.generation_latency_ms),
    },
    created_at: asOptionalString(value.created_at),
  };
}

function normalizeCheck(value: unknown): PreflightCheck | undefined {
  if (!isRecord(value)) return undefined;
  const checkCode = asString(value.check_code ?? value.code);
  const labels: Record<string, string> = {
    active_plan: "当前计划",
    approved_facts: "已批准事实",
    current_inventory: "最新素材快照",
    target_room: "空白草稿房间",
    materials: "素材可用性",
    draft_only_build_plan: "草稿安全操作",
    material_analysis_conflicts: "素材分析冲突",
  };
  return {
    check_code: checkCode,
    label: asString(value.label ?? value.name, labels[checkCode] ?? checkCode ?? "预检项"),
    status: asString(value.status, asBoolean(value.passed) ? "passed" : "blocked") as PreflightCheck["status"],
    detail: asOptionalString(value.detail ?? value.message),
  };
}

export function normalizePreflight(value: unknown): PreflightResult {
  if (!isRecord(value)) throw new Error("Invalid preflight response");
  return {
    status: asString(value.status, "blocked") === "passed" ? "passed" : "blocked",
    expected_plan_revision: asNumber(value.expected_plan_revision ?? value.plan_revision ?? value.plan_revision_number),
    checks: asArray(value.checks).flatMap((item) => {
      const check = normalizeCheck(item);
      return check ? [check] : [];
    }),
    checked_at: asOptionalString(value.checked_at ?? value.created_at),
  };
}

export function normalizeDraftExecution(value: unknown): DraftExecutionJob {
  if (!isRecord(value)) throw new Error("Invalid draft execution response");
  return {
    execution_job_code: asString(value.execution_job_code ?? value.job_code),
    status: asString(value.status, "queued") as DraftExecutionJob["status"],
    plan_revision: asNumber(value.plan_revision ?? value.expected_plan_revision ?? value.plan_revision_number),
    build_plan_code: asOptionalString(value.build_plan_code),
    result_summary: asOptionalString(value.result_summary) ?? (isRecord(value.result) ? asOptionalString(value.result.summary ?? value.result.result_summary) : undefined),
    ready_for_go_live: false,
    created_at: asOptionalString(value.created_at),
    updated_at: asOptionalString(value.updated_at),
  };
}

export function normalizeRun(value: unknown): ProductionRun {
  if (!isRecord(value)) throw new Error("Invalid run response");
  const preflight = isRecord(value.preflight ?? value.latest_preflight) ? normalizePreflight(value.preflight ?? value.latest_preflight) : undefined;
  const factVersion = isRecord(value.fact_card_version) ? value.fact_card_version : {};
  const execution = isRecord(value.draft_execution ?? value.latest_draft_execution_job)
    ? normalizeDraftExecution(value.draft_execution ?? value.latest_draft_execution_job)
    : undefined;
  return {
    run_code: asString(value.run_code),
    title: asString(value.title, "未命名生产运行"),
    topic: asOptionalString(value.topic),
    status: asString(value.status, "draft") as ProductionRun["status"],
    fact_card_code: asString(value.fact_card_code ?? factVersion.fact_card_code ?? value.fact_card_version_code),
    fact_card_version: typeof value.fact_card_version === "number" ? value.fact_card_version : typeof value.fact_card_version_number === "number" ? value.fact_card_version_number : typeof factVersion.version_number === "number" ? factVersion.version_number : undefined,
    inventory_snapshot_code: asString(value.inventory_snapshot_code),
    target_live_room_id: asOptionalString(value.target_live_room_id),
    target_duration_minutes: asNumber(value.target_duration_minutes, 30),
    build_mode: asString(value.build_mode, "draft_with_placeholders"),
    current_plan_revision: asNumber(value.current_plan_revision ?? value.plan_revision ?? value.active_plan_revision),
    reference_template_code: asOptionalString(value.reference_template_code),
    reference_template_revision_number: typeof value.reference_template_revision_number === "number" ? value.reference_template_revision_number : undefined,
    reference_template_projection_fingerprint: asOptionalString(value.reference_template_projection_fingerprint),
    open_requirement_count: asNumber(value.open_requirement_count),
    critical_conflict_count: asNumber(value.critical_conflict_count),
    preflight,
    draft_execution: execution,
    created_at: asOptionalString(value.created_at),
    updated_at: asOptionalString(value.updated_at),
  };
}

function normalizeAnalysis(value: unknown): VideoAnalysisItem | undefined {
  if (!isRecord(value)) return undefined;
  return {
    analysis_code: asString(value.analysis_code),
    run_code: asString(value.run_code),
    requirement_code: asOptionalString(value.requirement_code),
    asset_code: asString(value.asset_code),
    asset_fingerprint: asOptionalString(value.asset_fingerprint ?? value.checksum_sha256),
    asset_title: asString(value.asset_title ?? value.title, "视频素材"),
    selected: asBoolean(value.selected),
    provisional_source: asString(value.provisional_source, "none") as VideoAnalysisItem["provisional_source"],
    provisional_summary: asOptionalString(value.provisional_summary),
    gemini_status: asString(value.gemini_status, "not_requested") as GeminiJobStatus,
    gemini_summary: asOptionalString(value.gemini_summary),
    conflict_count: asNumber(value.conflict_count),
    updated_at: asOptionalString(value.updated_at),
  };
}

function normalizeConflict(value: unknown): AnalysisConflict | undefined {
  if (!isRecord(value)) return undefined;
  return {
    conflict_code: asString(value.conflict_code),
    analysis_code: asString(value.analysis_code),
    field: asString(value.field, "unknown"),
    severity: asString(value.severity, "warning") as AnalysisConflict["severity"],
    provisional_value: asOptionalString(value.provisional_value),
    gemini_value: asOptionalString(value.gemini_value),
    resolution: asOptionalString(value.resolution) as AnalysisConflict["resolution"],
  };
}

export const maituApi = {
  listFactCards: async () => asArray(await requestJson<unknown>(`${ROOT}/product-fact-cards`)).map(normalizeFactCard),
  createFactCard: async (payload: { title: string; product_name: string; product_code?: string; positioning: string; verified_facts: string[] }) => normalizeFactCard(await postJson(`${ROOT}/product-fact-cards`, {
    title: payload.title,
    product_code: payload.product_code,
    content: { product_name: payload.product_name, product_code: payload.product_code, positioning: payload.positioning, verified_facts: payload.verified_facts },
    change_reason: "创建生产事实卡",
    created_by: "maitu_workbench_operator",
  })),
  createFactVersion: async (cardCode: string, payload: { product_name: string; product_code?: string; positioning: string; verified_facts: string[]; selling_points: string[]; prohibited_claims: string[]; source_notes?: string }) => postJson<unknown>(`${ROOT}/product-fact-cards/${encodeURIComponent(cardCode)}/versions`, {
    content: { product_name: payload.product_name, product_code: payload.product_code, positioning: payload.positioning, verified_facts: payload.verified_facts, asset_keywords: payload.selling_points, compliance_notes: payload.prohibited_claims },
    change_reason: payload.source_notes || "人工更新已核验事实",
    created_by: "maitu_workbench_operator",
  }),
  approveFactVersion: async (cardCode: string, version: number) => postJson<unknown>(`${ROOT}/product-fact-cards/${encodeURIComponent(cardCode)}/versions/${version}/approve`, { approved_by: "maitu_workbench_reviewer" }),

  listInventoryJobs: async () => asArray(await requestJson<unknown>(`${ROOT}/inventory-sync-jobs`)).map(normalizeInventoryJob),
  createInventoryJob: async () => normalizeInventoryJob(await postJson(`${ROOT}/inventory-sync-jobs`, { source_system: "maitu", sync_mode: "full", requested_by: "maitu_workbench_operator" })),
  retryInventoryJob: async (code: string) => normalizeInventoryJob(await postJson(`${ROOT}/inventory-sync-jobs/${encodeURIComponent(code)}/retry`, { requested_by: "maitu_workbench_operator" })),

  listRuns: async () => asArray(await requestJson<unknown>(`${ROOT}/runs`)).map(normalizeRun),
  getRun: async (runCode: string) => normalizeRun(await requestJson(`${ROOT}/runs/${encodeURIComponent(runCode)}`)),
  createRun: async (payload: { title: string; topic?: string; fact_card_code: string; inventory_snapshot_code: string; target_live_room_id?: string; target_duration_minutes: number; build_mode: string; reference_template_code?: string; reference_template_revision_number?: number; reference_template_projection_fingerprint?: string }) => normalizeRun(await postJson(`${ROOT}/runs`, {
    title: payload.title,
    topic: payload.topic || payload.title,
    fact_card_code: payload.fact_card_code,
    inventory_snapshot_code: payload.inventory_snapshot_code,
    target_live_room_id: payload.target_live_room_id,
    target_duration_minutes: payload.target_duration_minutes,
    build_mode: payload.build_mode,
    reference_template_code: payload.reference_template_code,
    reference_template_revision_number: payload.reference_template_revision_number,
    reference_template_projection_fingerprint: payload.reference_template_projection_fingerprint,
    created_by: "maitu_workbench_operator",
  })),
  updateRunTargetRoom: async (runCode: string, targetLiveRoomId: string) => normalizeRun(await patchJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/target-live-room`, { target_live_room_id: targetLiveRoomId })),
  listRequirements: async (runCode: string) => asArray(await requestJson<unknown>(`${ROOT}/runs/${encodeURIComponent(runCode)}/material-requirements`)).map(normalizeRequirement),
  decideRequirement: async (runCode: string, requirementCode: string, payload: { decision: RequirementDecision["decision"]; selected_asset_code?: string; selected_material_key?: string; reason: string }) => normalizeDecision(await postJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/material-requirements/${encodeURIComponent(requirementCode)}/decisions`, { ...payload, decided_by: "maitu_workbench_operator" })),
  createInitialPlan: async (runCode: string) => normalizePlanRevision(await postJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/plans`, { reason: "根据固定事实版本和素材快照生成初始计划", requested_by: "maitu_workbench_operator" })),
  listPlanRevisions: async (runCode: string) => asArray(await requestJson<unknown>(`${ROOT}/runs/${encodeURIComponent(runCode)}/plan-revisions`)).map(normalizePlanRevision),
  replan: async (runCode: string, payload: { reason: string; expected_plan_revision: number; inventory_snapshot_code?: string }) => normalizePlanRevision(await postJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/replan`, payload)),
  preflight: async (runCode: string, expectedRevision: number) => normalizePreflight(await postJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/preflight`, { expected_plan_revision: expectedRevision })),
  createDraftExecution: async (runCode: string, expectedRevision: number) => normalizeDraftExecution(await postJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/draft-execution-jobs`, { expected_plan_revision: expectedRevision })),

  listVideoAnalyses: async (runCode: string) => asArray(await requestJson<unknown>(`${ROOT}/runs/${encodeURIComponent(runCode)}/video-analyses`)).flatMap((item) => { const value = normalizeAnalysis(item); return value ? [value] : []; }),
  submitGeminiBackfill: async (runCode: string, analysisCode: string, payload: { raw_json: unknown; asset_code: string; asset_fingerprint: string }) => normalizeAnalysis(await postJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/video-analyses/${encodeURIComponent(analysisCode)}/gemini-backfill`, payload)),
  listConflicts: async (runCode: string) => asArray(await requestJson<unknown>(`${ROOT}/runs/${encodeURIComponent(runCode)}/analysis-conflicts`)).flatMap((item) => { const value = normalizeConflict(item); return value ? [value] : []; }),
  resolveConflict: async (runCode: string, conflictCode: string, resolution: NonNullable<AnalysisConflict["resolution"]>) => normalizeConflict(await patchJson(`${ROOT}/runs/${encodeURIComponent(runCode)}/analysis-conflicts/${encodeURIComponent(conflictCode)}`, { resolution })),
};

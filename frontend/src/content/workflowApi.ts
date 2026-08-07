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
  WorkbenchApiError,
} from "../workbench/api";


const ROOT = "/api/content-projects";

export interface GuidedJob {
  jobCode: string;
  stage: string;
  operation?: string;
  targetSectionKey?: string;
  status: string;
  totalItems: number;
  completedItems: number;
  attempts: number;
  maxAttempts: number;
  errorCode?: string;
  errorMessage?: string;
  resultRefs: Record<string, unknown>;
  createdAt?: string;
  updatedAt: string;
}

export interface GuidedCitation {
  citationCode?: string;
  sourceType: string;
  title: string;
  excerpt?: string;
  referenceCode?: string;
  status?: string;
}

export interface GuidedOutlineKeyPoint {
  text: string;
  citations: GuidedCitation[];
}

export interface GuidedOutlineSection {
  sectionKey: string;
  title: string;
  objective: string;
  keyPoints: GuidedOutlineKeyPoint[];
}

export interface GuidedScriptBlock {
  blockCode: string;
  sortOrder: number;
  sectionKey: string;
  content: string;
}

export interface GuidedMaterialRequirement {
  requirementCode: string;
  blockSortOrder: number;
  sectionKey: string;
  materialRole: string;
  description: string;
  priority: "required" | "optional";
  keywords: string[];
  matchedAssetCode?: string;
  status: "matched" | "missing" | "waived";
  waivedBy?: string;
  waivedAt?: string;
}

export interface GuidedStoryboardLayer {
  role: string;
  assetCode: string;
  geometry: { x: number; y: number; width: number; height: number };
  zOrder: number;
}

export interface GuidedStoryboardScene {
  shotCode: string;
  title: string;
  script: string;
  layers: GuidedStoryboardLayer[];
}

export interface GuidedKnowledgeReference {
  knowledgeCode: string;
  title: string;
  excerpt?: string;
  sourceType?: string;
  kind?: "fact_card" | "fact_claim" | "content_rule";
  versionNumber?: number;
  version?: string;
}

export interface GuidedMaterialRecommendation {
  assetCode: string;
  title: string;
  rationale?: string;
  materialRoles: string[];
}

export interface GuidedSetupRecommendations {
  knowledge: GuidedKnowledgeReference[];
  materials: GuidedMaterialRecommendation[];
}

export interface GuidedThemeCandidate {
  theme: string;
  rationale?: string;
  generatedAt?: string;
}

export interface GuidedMaituRoomConfiguration {
  status: string;
  ready: boolean;
  hostName?: string;
  voiceName?: string;
  sceneName?: string;
  checkedAt?: string;
  message?: string;
}

export interface GuidedRevisionArchive {
  revisionCode: string;
  revisionNumber: number;
  stage: string;
  status: string;
  title?: string;
  createdAt?: string;
  restorable: boolean;
  compatible: boolean;
  details: Record<string, unknown>;
}

export interface GuidedRevisions {
  outline: GuidedRevisionArchive[];
  script: GuidedRevisionArchive[];
}

export interface GuidedHistoryItem {
  eventCode: string;
  stage: string;
  kind: string;
  referenceCode: string;
  revisionNumber?: number;
  status: string;
  actor: string;
  occurredAt: string;
  details: Record<string, unknown>;
}

export interface GuidedWorkflow {
  workflowVersion: string;
  project: {
    projectCode: string;
    title: string;
    revisionNumber: number;
    status: string;
    targetLiveRoomId: string;
    theme: string;
    updatedAt: string;
  };
  materialPool: {
    poolRevisionCode: string;
    revisionNumber: number;
    selectedAssetCodes: string[];
    fingerprintSha256: string;
  };
  setup: {
    selectedKnowledgeCodes: string[];
    knowledgeReferences: GuidedKnowledgeReference[];
    themeCandidate?: GuidedThemeCandidate;
    recommendations?: GuidedSetupRecommendations;
  };
  revisions: GuidedRevisions;
  outline?: {
    storyBriefCode: string;
    revisionNumber: number;
    status: string;
    sections: GuidedOutlineSection[];
    createdAt: string;
    confirmedAt?: string;
  };
  script?: {
    scriptRevisionCode: string;
    revisionNumber: number;
    status: string;
    title: string;
    sourceOutlineRevision: number;
    sourceMaterialPoolRevision: number;
    blocks: GuidedScriptBlock[];
    requirements: GuidedMaterialRequirement[];
    createdAt: string;
    confirmedAt?: string;
  };
  storyboard?: {
    planCode: string;
    reviewStatus: string;
    status: string;
    blockedReasons: string[];
    templateCode?: string;
    manualOnly: boolean;
    scenes: GuidedStoryboardScene[];
    createdAt: string;
    updatedAt: string;
    confirmedAt?: string;
  };
  jobs: Record<string, GuidedJob>;
  history: GuidedHistoryItem[];
  gates: {
    setupEditable: boolean;
    outlineCurrent: boolean;
    outlineConfirmed: boolean;
    scriptCurrent: boolean;
    scriptConfirmed: boolean;
    requiredMaterialMissingCount: number;
    waivedMaterialCount: number;
    storyboardCurrent: boolean;
    storyboardConfirmed: boolean;
    storyboardManualOnly: boolean;
  };
}

function strings(value: unknown): string[] {
  return asArray(value).flatMap((item) => typeof item === "string" && item.trim() ? [item] : []);
}

function citation(value: unknown): GuidedCitation | undefined {
  if (typeof value === "string" && value.trim()) {
    return { citationCode: value, sourceType: "reference", title: value };
  }
  if (!isRecord(value)) return undefined;
  const citationCode = asOptionalString(value.citation_code ?? value.reference_code ?? value.knowledge_code ?? value.code ?? value.id);
  const title = asString(value.title ?? value.name ?? value.label ?? value.reference ?? citationCode, "引用内容");
  return {
    ...(citationCode ? { citationCode } : {}),
    sourceType: asString(value.source_type ?? value.kind ?? value.type, "knowledge"),
    title,
    excerpt: asOptionalString(value.excerpt ?? value.quote ?? value.content ?? value.summary),
    referenceCode: asOptionalString(value.reference_code ?? value.source_code ?? value.fact_code),
    status: asOptionalString(value.status),
  };
}

function keyPoint(value: unknown): GuidedOutlineKeyPoint | undefined {
  if (typeof value === "string" && value.trim()) return { text: value, citations: [] };
  if (!isRecord(value)) return undefined;
  const text = asString(value.text ?? value.content ?? value.value ?? value.point);
  if (!text) return undefined;
  const rawCitations = value.citations ?? value.knowledge_citations ?? value.references ?? value.source_refs ?? value.evidence;
  return {
    text,
    citations: asArray(rawCitations).flatMap((item) => citation(item) ?? []),
  };
}

function outlineSection(value: unknown, index: number): GuidedOutlineSection | undefined {
  if (!isRecord(value)) return undefined;
  return {
    sectionKey: asString(value.section_key, `section-${index + 1}`),
    title: asString(value.title),
    objective: asString(value.objective),
    keyPoints: asArray(value.key_points).flatMap((item) => keyPoint(item) ?? []),
  };
}

export function normalizeGuidedJob(value: unknown): GuidedJob | undefined {
  const source = isRecord(value) && isRecord(value.job) ? value.job : value;
  if (!isRecord(source)) return undefined;
  const jobCode = asString(source.job_code ?? source.code);
  if (!jobCode) return undefined;
  const resultRefs = isRecord(source.result_refs) ? source.result_refs : isRecord(source.result) ? source.result : {};
  return {
    jobCode,
    stage: asString(source.stage, "generation"),
    operation: asOptionalString(source.operation ?? source.job_type ?? source.kind),
    targetSectionKey: asOptionalString(source.target_section_key ?? source.section_key ?? resultRefs.section_key ?? resultRefs.target_section_key),
    status: asString(source.status, "queued"),
    totalItems: asNumber(source.total_items, 1),
    completedItems: asNumber(source.completed_items),
    attempts: asNumber(source.attempts),
    maxAttempts: asNumber(source.max_attempts, 3),
    errorCode: asOptionalString(source.error_code),
    errorMessage: asOptionalString(source.error_message),
    resultRefs,
    createdAt: asOptionalString(source.created_at),
    updatedAt: asString(source.updated_at ?? source.created_at),
  };
}

function knowledgeReference(value: unknown): GuidedKnowledgeReference | undefined {
  if (typeof value === "string" && value.trim()) return { knowledgeCode: value, title: value };
  if (!isRecord(value)) return undefined;
  const knowledgeCode = asString(value.knowledge_code ?? value.reference_code ?? value.fact_code ?? value.code ?? value.source_id ?? value.id);
  if (!knowledgeCode) return undefined;
  const rawKind = asOptionalString(value.kind ?? value.source_type ?? value.type);
  const kind = rawKind === "fact_card" || rawKind === "fact_claim" || rawKind === "content_rule" ? rawKind : undefined;
  const versionNumber = asNumber(value.version_number ?? value.revision_number);
  return {
    knowledgeCode,
    title: asString(value.title ?? value.name ?? value.label, knowledgeCode),
    excerpt: asOptionalString(value.excerpt ?? value.summary ?? value.content ?? value.statement),
    sourceType: rawKind,
    ...(kind ? { kind } : {}),
    ...(versionNumber ? { versionNumber } : {}),
    version: asOptionalString(value.version ?? value.version_code ?? value.fingerprint),
  };
}

function materialRecommendation(value: unknown): GuidedMaterialRecommendation | undefined {
  if (!isRecord(value)) return undefined;
  const assetCode = asString(value.asset_code ?? value.code ?? value.id);
  if (!assetCode) return undefined;
  return {
    assetCode,
    title: asString(value.title ?? value.name ?? value.label, assetCode),
    rationale: asOptionalString(value.rationale ?? value.reason ?? value.match_reason),
    materialRoles: strings(value.material_roles ?? value.roles),
  };
}

function recommendations(value: unknown): GuidedSetupRecommendations | undefined {
  const source = isRecord(value) && isRecord(value.recommendations) ? value.recommendations
    : isRecord(value) && isRecord(value.setup_recommendations) ? value.setup_recommendations
      : isRecord(value) ? value : undefined;
  if (!source) return undefined;
  const knowledgeResult = isRecord(source.recommend_knowledge) ? source.recommend_knowledge : {};
  const materialResult = isRecord(source.recommend_materials) ? source.recommend_materials : {};
  const knowledge = asArray(source.knowledge_candidates ?? source.knowledge ?? source.knowledge_recommendations ?? knowledgeResult.recommendations)
    .flatMap((item) => knowledgeReference(item) ?? []);
  const materials = asArray(source.material_candidates ?? source.materials ?? source.material_recommendations ?? materialResult.recommendations)
    .flatMap((item) => materialRecommendation(item) ?? []);
  return knowledge.length || materials.length ? { knowledge, materials } : undefined;
}

function themeCandidate(value: unknown): GuidedThemeCandidate | undefined {
  if (!isRecord(value)) return undefined;
  const setupResults = isRecord(value.recommendations) ? value.recommendations : {};
  const optimization = isRecord(setupResults.optimize_theme) ? setupResults.optimize_theme : {};
  const raw = value.theme_candidate ?? value.optimized_theme_candidate ?? value.theme_optimization ?? value.candidate ?? optimization.theme_candidate;
  if (typeof raw === "string" && raw.trim()) return { theme: raw };
  if (!isRecord(raw)) return undefined;
  const theme = asString(raw.theme ?? raw.optimized_theme ?? raw.text ?? raw.value);
  if (!theme) return undefined;
  return {
    theme,
    rationale: asOptionalString(raw.rationale ?? raw.reason ?? raw.explanation),
    generatedAt: asOptionalString(raw.generated_at ?? raw.created_at),
  };
}

function storyboardScene(value: unknown): GuidedStoryboardScene | undefined {
  if (!isRecord(value)) return undefined;
  const shotCode = asString(value.shot_code);
  if (!shotCode) return undefined;
  return {
    shotCode,
    title: asString(value.title, shotCode),
    script: asString(value.script),
    layers: asArray(value.layers).flatMap((raw) => {
      if (!isRecord(raw)) return [];
      const geometry = isRecord(raw.normalized_geometry) ? raw.normalized_geometry : isRecord(raw.geometry) ? raw.geometry : {};
      const role = asString(raw.role ?? raw.material_role);
      const assetCode = asString(raw.asset_code);
      if (!role || !assetCode) return [];
      return [{
        role,
        assetCode,
        geometry: {
          x: asNumber(geometry.x),
          y: asNumber(geometry.y),
          width: asNumber(geometry.width),
          height: asNumber(geometry.height),
        },
        zOrder: asNumber(raw.z_order),
      }];
    }),
  };
}

function normalizedJobs(value: Record<string, unknown>): Record<string, GuidedJob> {
  const result: Record<string, GuidedJob> = {};
  const rawJobs = isRecord(value.jobs) ? value.jobs : {};
  Object.entries(rawJobs).forEach(([key, raw]) => {
    const normalized = normalizeGuidedJob(raw);
    if (normalized) result[key] = normalized;
  });
  asArray(value.active_jobs).forEach((raw, index) => {
    const normalized = normalizeGuidedJob(raw);
    if (normalized) result[normalized.jobCode || `job-${index + 1}`] = normalized;
  });
  return result;
}

export function normalizeGuidedWorkflow(value: unknown): GuidedWorkflow {
  if (!isRecord(value) || !isRecord(value.project) || !isRecord(value.material_pool)) {
    throw new Error("引导式直播项目响应无效");
  }
  const rawProject = value.project;
  const rawPool = value.material_pool;
  const rawSetup = isRecord(value.setup) ? value.setup : {};
  const rawOutline = isRecord(value.outline) ? value.outline : undefined;
  const rawScript = isRecord(value.script) ? value.script : undefined;
  const rawStoryboard = isRecord(value.storyboard) ? value.storyboard : undefined;
  const gates = isRecord(value.gates) ? value.gates : {};
  const knowledgeReferences = asArray(rawSetup.knowledge_references ?? rawSetup.selected_knowledge ?? rawProject.selected_knowledge_refs ?? value.knowledge_references)
    .flatMap((item) => knowledgeReference(item) ?? []);
  const selectedKnowledgeCodes = Array.from(new Set([
    ...strings(rawSetup.selected_knowledge_codes ?? rawSetup.selected_knowledge_reference_codes ?? value.selected_knowledge_codes),
    ...knowledgeReferences.map((item) => item.knowledgeCode),
  ]));
  return {
    workflowVersion: asString(value.workflow_version),
    project: {
      projectCode: asString(rawProject.project_code),
      title: asString(rawProject.title),
      revisionNumber: asNumber(rawProject.revision_number),
      status: asString(rawProject.status),
      targetLiveRoomId: asString(rawProject.target_live_room_id),
      theme: asString(rawProject.theme),
      updatedAt: asString(rawProject.updated_at),
    },
    materialPool: {
      poolRevisionCode: asString(rawPool.pool_revision_code),
      revisionNumber: asNumber(rawPool.revision_number),
      selectedAssetCodes: strings(rawPool.selected_asset_codes),
      fingerprintSha256: asString(rawPool.fingerprint_sha256),
    },
    setup: {
      selectedKnowledgeCodes,
      knowledgeReferences,
      themeCandidate: themeCandidate(rawSetup) ?? themeCandidate(value),
      recommendations: recommendations(rawSetup) ?? recommendations(value),
    },
    revisions: normalizeGuidedRevisions({
      ...(isRecord(value.revisions) ? value.revisions : {}),
      ...(value.script_archives !== undefined ? { script: value.script_archives } : {}),
    }),
    outline: rawOutline ? {
      storyBriefCode: asString(rawOutline.story_brief_code),
      revisionNumber: asNumber(rawOutline.revision_number),
      status: asString(rawOutline.status),
      sections: asArray(rawOutline.sections).flatMap((item, index) => outlineSection(item, index) ?? []),
      createdAt: asString(rawOutline.created_at),
      confirmedAt: asOptionalString(rawOutline.confirmed_at),
    } : undefined,
    script: rawScript ? {
      scriptRevisionCode: asString(rawScript.script_revision_code),
      revisionNumber: asNumber(rawScript.revision_number),
      status: asString(rawScript.status),
      title: asString(rawScript.title),
      sourceOutlineRevision: asNumber(rawScript.source_outline_revision),
      sourceMaterialPoolRevision: asNumber(rawScript.source_material_pool_revision),
      blocks: asArray(rawScript.blocks).flatMap((item) => isRecord(item) ? [{
        blockCode: asString(item.block_code),
        sortOrder: asNumber(item.sort_order),
        sectionKey: asString(item.section_key),
        content: asString(item.content),
      }] : []),
      requirements: asArray(rawScript.requirements).flatMap((item) => isRecord(item) ? [{
        requirementCode: asString(item.requirement_code),
        blockSortOrder: asNumber(item.block_sort_order),
        sectionKey: asString(item.section_key),
        materialRole: asString(item.material_role),
        description: asString(item.description),
        priority: asString(item.priority, "optional") as "required" | "optional",
        keywords: strings(item.keywords),
        matchedAssetCode: asOptionalString(item.matched_asset_code),
        status: asString(item.status, "missing") as "matched" | "missing" | "waived",
        waivedBy: asOptionalString(item.waived_by),
        waivedAt: asOptionalString(item.waived_at),
      }] : []),
      createdAt: asString(rawScript.created_at),
      confirmedAt: asOptionalString(rawScript.confirmed_at),
    } : undefined,
    storyboard: rawStoryboard ? {
      planCode: asString(rawStoryboard.plan_code),
      reviewStatus: asString(rawStoryboard.review_status),
      status: asString(rawStoryboard.status),
      blockedReasons: strings(rawStoryboard.blocked_reasons),
      templateCode: asOptionalString(rawStoryboard.template_code),
      manualOnly: isRecord(rawStoryboard.revision_context) && rawStoryboard.revision_context.manual_only === true,
      scenes: isRecord(rawStoryboard.blueprint) ? asArray(rawStoryboard.blueprint.scenes).flatMap((item) => storyboardScene(item) ?? []) : [],
      createdAt: asString(rawStoryboard.created_at),
      updatedAt: asString(rawStoryboard.updated_at),
      confirmedAt: asOptionalString(rawStoryboard.confirmed_at),
    } : undefined,
    jobs: normalizedJobs(value),
    history: asArray(value.history).flatMap((item) => {
      if (!isRecord(item) || !asString(item.event_code)) return [];
      const revisionNumber = asNumber(item.revision_number);
      return [{
        eventCode: asString(item.event_code),
        stage: asString(item.stage),
        kind: asString(item.kind),
        referenceCode: asString(item.reference_code),
        ...(revisionNumber ? { revisionNumber } : {}),
        status: asString(item.status),
        actor: asString(item.actor),
        occurredAt: asString(item.occurred_at),
        details: isRecord(item.details) ? item.details : {},
      }];
    }),
    gates: {
      setupEditable: gates.setup_editable === true,
      outlineCurrent: gates.outline_current === true,
      outlineConfirmed: gates.outline_confirmed === true,
      scriptCurrent: gates.script_current === true,
      scriptConfirmed: gates.script_confirmed === true,
      requiredMaterialMissingCount: asNumber(gates.required_material_missing_count),
      waivedMaterialCount: asNumber(gates.waived_material_count),
      storyboardCurrent: gates.storyboard_current === true,
      storyboardConfirmed: gates.storyboard_confirmed === true,
      storyboardManualOnly: gates.storyboard_manual_only === true,
    },
  };
}

function normalizeThemeOptimization(value: unknown): { job?: GuidedJob; candidate?: GuidedThemeCandidate } {
  const source = isRecord(value) ? value : {};
  const job = normalizeGuidedJob(source);
  const candidate = themeCandidate(source) ?? (job ? themeCandidate(job.resultRefs) : undefined);
  return { ...(job ? { job } : {}), ...(candidate ? { candidate } : {}) };
}

function normalizeRecommendations(value: unknown): { job?: GuidedJob; recommendations?: GuidedSetupRecommendations } {
  const source = isRecord(value) ? value : {};
  const job = normalizeGuidedJob(source);
  const normalized = recommendations(source) ?? (job ? recommendations(job.resultRefs) : undefined);
  return { ...(job ? { job } : {}), ...(normalized ? { recommendations: normalized } : {}) };
}

export function normalizeMaituRoomConfiguration(value: unknown): GuidedMaituRoomConfiguration {
  const source = isRecord(value) && isRecord(value.configuration) ? value.configuration : value;
  if (!isRecord(source)) return { status: "unknown", ready: false };
  const host = isRecord(source.digital_human) ? source.digital_human : isRecord(source.host) ? source.host : {};
  const voice = isRecord(source.voice) ? source.voice : isRecord(source.voice_profile) ? source.voice_profile : {};
  const hosts = asArray(source.hosts).filter(isRecord);
  const selectedHost = hosts.find((item) => item.ready === true) ?? hosts[0] ?? {};
  const scene = isRecord(source.scene) ? source.scene : {};
  const hostName = asOptionalString(host.name ?? host.title ?? selectedHost.clip_name ?? source.digital_human_name ?? source.host_name ?? source.avatar_name ?? selectedHost.digital_human_image_id);
  const voiceName = asOptionalString(voice.name ?? voice.title ?? selectedHost.speaker_id ?? source.voice_name ?? source.voice_profile_name);
  const ready = asBoolean(source.ready ?? source.configured ?? source.has_ready_host, Boolean(hostName && voiceName));
  return {
    status: asString(source.status, ready ? "ready" : "unconfigured"),
    ready,
    hostName,
    voiceName,
    sceneName: asOptionalString(source.scene_name ?? scene.name ?? selectedHost.clip_name),
    checkedAt: asOptionalString(source.checked_at ?? source.last_checked_at ?? source.updated_at),
    message: asOptionalString(source.message ?? source.error_message),
  };
}

function revisionArchive(value: unknown, stage: string, index: number): GuidedRevisionArchive | undefined {
  if (!isRecord(value)) return undefined;
  const revisionNumber = asNumber(value.revision_number ?? value.revision);
  const revisionCode = asString(value.revision_code ?? value.script_revision_code ?? value.story_brief_code ?? value.code, `${stage}-${revisionNumber || index + 1}`);
  return {
    revisionCode,
    revisionNumber,
    stage: asString(value.stage, stage),
    status: asString(value.status, "archived"),
    title: asOptionalString(value.title ?? value.name),
    createdAt: asOptionalString(value.created_at ?? value.archived_at ?? value.updated_at),
    restorable: asBoolean(value.restorable ?? value.can_restore, asString(value.status) === "superseded"),
    compatible: asBoolean(value.compatible ?? value.is_compatible, true),
    details: isRecord(value.details) ? value.details : {},
  };
}

export function normalizeGuidedRevisions(value: unknown): GuidedRevisions {
  const source = isRecord(value) && isRecord(value.revisions) ? value.revisions : isRecord(value) ? value : {};
  const outline = asArray(source.outline ?? source.outline_revisions).flatMap((item, index) => revisionArchive(item, "outline", index) ?? []);
  const script = asArray(source.script ?? source.script_revisions).flatMap((item, index) => revisionArchive(item, "script", index) ?? []);
  return { outline, script };
}

function put(path: string, payload: unknown): Promise<GuidedWorkflow> {
  return requestJson<unknown>(path, { method: "PUT", body: JSON.stringify(payload) }).then(normalizeGuidedWorkflow);
}

export const guidedContentApi = {
  create: (payload: { title: string; target_live_room_id: string }, idempotencyKey?: string) =>
    requestJson<unknown>(`${ROOT}/guided`, {
      method: "POST",
      body: JSON.stringify(payload),
      ...(idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    }).then(normalizeGuidedWorkflow),
  get: (projectCode: string) => requestJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow`).then(normalizeGuidedWorkflow),
  updateSetup: (projectCode: string, payload: {
    expected_project_revision: number;
    expected_material_pool_revision: number;
    theme: string;
    selected_asset_codes: string[];
    selected_knowledge_codes?: string[];
    selected_knowledge_refs?: Array<{ kind: "fact_card" | "fact_claim" | "content_rule"; code: string; version_number?: number }>;
  }) => patchJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/setup`, payload).then(normalizeGuidedWorkflow),
  optimizeTheme: (projectCode: string, payload: { theme: string }) =>
    postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/setup/theme-optimize`, payload).then(normalizeThemeOptimization),
  recommendSetup: (projectCode: string, payload: { theme: string; selected_asset_codes: string[]; selected_knowledge_codes: string[]; kind?: "knowledge" | "materials" }) =>
    postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/setup/recommendations`, payload).then(normalizeRecommendations),
  getMaituRoomConfiguration: (projectCode: string) =>
    requestJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/maitu-room-configuration`).then(normalizeMaituRoomConfiguration),
  updateMaterialPool: (projectCode: string, payload: { expected_revision: number; selected_asset_codes: string[] }) =>
    put(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/material-pool`, payload),
  generateOutline: (projectCode: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/outline/generate`).then((value) => normalizeGuidedJob(value)),
  regenerateOutlineSection: (projectCode: string, sectionKey: string, expectedRevision: number, guidance?: string) =>
    postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/outline/sections/${encodeURIComponent(sectionKey)}/regenerate`, { expected_revision: expectedRevision, ...(guidance?.trim() ? { guidance: guidance.trim() } : {}) }).then((value) => normalizeGuidedJob(value)),
  reviseOutline: (projectCode: string, expectedRevision: number, sections: GuidedOutlineSection[]) =>
    put(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/outline`, {
      expected_revision: expectedRevision,
      sections: sections.map((section) => ({
        section_key: section.sectionKey,
        title: section.title,
        objective: section.objective,
        key_points: section.keyPoints.map((point) => point.citations.length ? ({ text: point.text, citations: point.citations.map((citation) => ({
          citation_code: citation.citationCode,
          source_type: citation.sourceType,
          title: citation.title,
          excerpt: citation.excerpt,
          reference_code: citation.referenceCode,
        })) }) : point.text),
      })),
    }),
  confirmOutline: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/outline/confirm`, { expected_revision: expectedRevision }).then(normalizeGuidedWorkflow),
  reopenOutline: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/outline/reopen`, { expected_revision: expectedRevision }).then(normalizeGuidedWorkflow),
  generateScript: (projectCode: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/script/generate`).then((value) => normalizeGuidedJob(value)),
  reviseScript: (projectCode: string, expectedRevision: number, blocks: GuidedScriptBlock[]) =>
    put(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/script`, {
      expected_revision: expectedRevision,
      blocks: blocks.map((block) => ({ section_key: block.sectionKey, content: block.content })),
    }),
  waiveRequirement: (projectCode: string, requirementCode: string, expectedScriptRevision: number) =>
    postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/script/requirements/${encodeURIComponent(requirementCode)}/waive`, { expected_script_revision: expectedScriptRevision }).then(normalizeGuidedWorkflow),
  confirmScript: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/script/confirm`, { expected_revision: expectedRevision }).then(normalizeGuidedWorkflow),
  reopenScript: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/script/reopen`, { expected_revision: expectedRevision }).then(normalizeGuidedWorkflow),
  getRevisions: async (projectCode: string) => {
    const path = `${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow`;
    try {
      return normalizeGuidedRevisions(await requestJson<unknown>(`${path}/revisions`));
    } catch (error) {
      if (!(error instanceof WorkbenchApiError) || error.status !== 404) throw error;
      try {
        return normalizeGuidedRevisions(await requestJson<unknown>(`${path}/script/revisions`));
      } catch (fallbackError) {
        if (!(fallbackError instanceof WorkbenchApiError) || fallbackError.status !== 404) throw fallbackError;
        return (await guidedContentApi.get(projectCode)).revisions;
      }
    }
  },
  restoreScriptRevision: (projectCode: string, revisionNumber: number, expectedCurrentRevision?: number) =>
    postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/script/revisions/${encodeURIComponent(String(revisionNumber))}/restore`, expectedCurrentRevision ? { expected_current_revision: expectedCurrentRevision } : undefined).then(normalizeGuidedWorkflow),
  generateStoryboard: (projectCode: string, template: { template_code: string; revision: number; projection_fingerprint: string }) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/storyboard/generate`, template).then((value) => normalizeGuidedJob(value)),
  reviseStoryboard: (projectCode: string, expectedPlanCode: string, scenes: GuidedStoryboardScene[]) => put(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/storyboard`, {
    expected_plan_code: expectedPlanCode,
    scenes: scenes.map((scene, sortOrder) => ({
      shot_code: scene.shotCode,
      sort_order: sortOrder,
      title: scene.title,
      script: scene.script,
      layers: scene.layers.map((layer) => ({ role: layer.role, asset_code: layer.assetCode, geometry: layer.geometry, z_order: layer.zOrder })),
    })),
  }),
  confirmStoryboard: (projectCode: string, expectedPlanCode: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/storyboard/confirm`, { expected_plan_code: expectedPlanCode }).then(normalizeGuidedWorkflow),
  retryJob: (projectCode: string, jobCode: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(projectCode)}/guided-workflow/jobs/${encodeURIComponent(jobCode)}/retry`).then(normalizeGuidedWorkflow),
};

import { asArray, asNumber, asOptionalString, asString, isRecord, patchJson, postJson, requestJson } from "../workbench/api";

const ROOT = "/api/content-projects";

export interface ContentProjectSummary {
  projectCode: string;
  title: string;
  revisionNumber: number;
  status: string;
  generationGoal: string;
  updatedAt: string;
}

export interface ProjectWorkspaceSummary {
  projectCode: string;
  title: string;
  status: string;
  revisionNumber: number;
  generationGoal: string;
  brief: ProjectWorkspaceOutput;
  script: ProjectWorkspaceOutput;
  liveRoom: ProjectWorkspaceOutput;
  video: ProjectWorkspaceOutput;
  delivery: ProjectWorkspaceOutput;
  operations: ProjectWorkspaceOutput;
  activity: Array<{ kind: string; title: string; detail: string; status: string; occurredAt: string }>;
  updatedAt: string;
}

export interface ProjectWorkspaceOutput {
  available: boolean;
  status: string;
  updatedAt?: string;
  title?: string;
  progressPercent?: number;
  referenceCode?: string;
}

export interface ContentProgramSegment {
  segment_code: string;
  semantic_goal: string;
  program_phase: string;
  estimated_duration_ms?: number;
  entry_condition?: string;
  exit_condition?: string;
  product_refs: string[];
  interaction_actions: Record<string, unknown>[];
  cta_actions: Record<string, unknown>[];
  branch_applicability: string[];
  metadata: Record<string, unknown>;
  script_block_codes: string[];
}

export interface ContentShot {
  shot_code: string;
  shot_goal: string;
  program_segment_code: string;
  composition_intent: Record<string, unknown>;
  material_role_requirements: string[];
  audio_actions: Record<string, unknown>[];
  continuity: Record<string, unknown>;
  acceptance_criteria: string[];
  estimated_duration_ms?: number;
  branch_applicability: string[];
  must_include: string[];
  must_avoid: string[];
  script_block_codes: string[];
}

export interface ScriptContentRuleReference {
  ruleCode: string;
  ruleKind?: string;
  directive: string;
  ruleText: string;
  fingerprintSha256?: string;
}

export interface ContentProjectDetail extends ContentProjectSummary {
  content: Record<string, unknown>;
  templateContributionDecisions: Array<{ templateCode: string; revision: number; selectionRole: string; availableModules: string[]; acceptedModules: string[]; rejectedModules: string[]; materialCues: string[]; programOutline: Array<{ moduleKey: string; title: string; purpose: string; sourceSessionCode: string; startMs: number; endMs: number }>; reviewedExamples: Array<{ moduleKey: string; exampleText: string; sourceSessionCode: string; startMs: number; endMs: number }>; contentStrategyPolicy: Record<string, unknown> }>;
  factCards: Array<{ fact_card_code: string; version_number: number; version_code: string; content_sha256: string }>;
  factClaims: Array<{ claim_code: string; fact_code: string; source_evidence_code: string; claim: string; citation_excerpt: string; citation_start_offset?: number; citation_end_offset?: number; fingerprint_sha256: string }>;
  contentRules: Array<{ rule_code: string; rule_kind: string; directive: string; title: string; rule_text: string; source_evidence_code?: string; fingerprint_sha256: string }>;
  designBrief?: { design_brief_code: string; revision_number: number; status: string; raw_input: string; parsed_brief: Record<string, unknown>; user_overrides: Record<string, unknown>; open_questions: Array<{ field: string; question: string; recommended_answer: string; blocking: boolean }> };
  generated: boolean;
  generationMode?: string;
  storyBrief?: { story_brief_code: string; revision_number: number; content: Record<string, unknown> };
  script?: { script_revision_code: string; revision_number: number; title: string; blocks: Array<{ block_code: string; module_type: string; content: string; estimated_duration_ms?: number; fact_citations: Array<{ fact_card_code?: string; version_number?: number; claim_code?: string; fact_code?: string; source_evidence_code?: string; field_path?: string; claim_text?: string; start_offset?: number; end_offset?: number }>; template_sources: Array<{ template_code: string; revision: number; contribution?: string; moduleGuidance: string[]; contentStrategyPolicy: Record<string, unknown>; strategyStage?: { moduleKey: string; title: string; purpose: string; sourceSessionCode: string; startMs: number; endMs: number }; referenceExamples: Array<{ moduleKey: string; exampleText: string; sourceSessionCode: string; startMs: number; endMs: number }> }>; contentRuleRefs: ScriptContentRuleReference[]; interaction_intent?: Record<string, unknown>; cta_intent?: Record<string, unknown> }> };
  program?: { program_revision_code: string; revision_number: number; segments: ContentProgramSegment[] };
  shotList?: { shot_list_revision_code: string; revision_number: number; shots: ContentShot[] };
}

export interface ContentChainRevision {
  objectType: string;
  objectCode: string;
  revisionNumber: number;
  status: string;
  createdAt: string;
  createdBy?: string;
  confirmedAt?: string;
  fingerprintSha256?: string;
  sources: string[];
}

function summary(value: unknown): ContentProjectSummary | undefined {
  if (!isRecord(value)) return undefined;
  const projectCode = asString(value.project_code);
  if (!projectCode) return undefined;
  return { projectCode, title: asString(value.title, projectCode), revisionNumber: asNumber(value.revision_number, 1), status: asString(value.status, "draft"), generationGoal: asString(value.generation_goal), updatedAt: asString(value.updated_at) };
}

function workspaceOutput(value: unknown): ProjectWorkspaceOutput {
  const item = isRecord(value) ? value : {};
  return { available: item.available === true, status: asString(item.status, "pending"), updatedAt: asOptionalString(item.updated_at), title: asOptionalString(item.title), progressPercent: typeof item.progress_percent === "number" ? asNumber(item.progress_percent) : undefined, referenceCode: asOptionalString(item.reference_code) };
}

function workspaceSummary(value: unknown): ProjectWorkspaceSummary {
  if (!isRecord(value)) throw new Error("项目工作区响应无效");
  return {
    projectCode: asString(value.project_code), title: asString(value.title), status: asString(value.status), revisionNumber: asNumber(value.revision_number), generationGoal: asString(value.generation_goal),
    brief: workspaceOutput(value.brief), script: workspaceOutput(value.script), liveRoom: workspaceOutput(value.live_room), video: workspaceOutput(value.video), delivery: workspaceOutput(value.delivery), operations: workspaceOutput(value.operations),
    activity: asArray(value.activity).flatMap((item) => isRecord(item) ? [{ kind: asString(item.kind), title: asString(item.title), detail: asString(item.detail), status: asString(item.status), occurredAt: asString(item.occurred_at) }] : []),
    updatedAt: asString(value.updated_at),
  };
}

function strings(value: unknown): string[] { return asArray(value).flatMap((item) => typeof item === "string" ? [item] : []); }
function records(value: unknown): Record<string, unknown>[] { return asArray(value).flatMap((item) => isRecord(item) ? [item] : []); }

function detail(value: unknown): ContentProjectDetail {
  const base = summary(value);
  if (!base || !isRecord(value)) throw new Error("内容项目响应无效");
  const script = isRecord(value.script) ? {
    script_revision_code: asString(value.script.script_revision_code), revision_number: asNumber(value.script.revision_number), title: asString(value.script.title),
    blocks: asArray(value.script.blocks).flatMap((item) => isRecord(item) ? [{ block_code: asString(item.block_code), module_type: asString(item.module_type), content: asString(item.content), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined, fact_citations: asArray(item.fact_citations).flatMap((citation) => isRecord(citation) && (asString(citation.fact_card_code) || asString(citation.claim_code)) ? [{ fact_card_code: asOptionalString(citation.fact_card_code), version_number: typeof citation.version_number === "number" ? asNumber(citation.version_number) : undefined, claim_code: asOptionalString(citation.claim_code), fact_code: asOptionalString(citation.fact_code), source_evidence_code: asOptionalString(citation.source_evidence_code), field_path: asOptionalString(citation.field_path), claim_text: asOptionalString(citation.claim_text), start_offset: typeof citation.start_offset === "number" ? asNumber(citation.start_offset) : undefined, end_offset: typeof citation.end_offset === "number" ? asNumber(citation.end_offset) : undefined }] : []), template_sources: asArray(item.template_sources).flatMap((source) => isRecord(source) && asString(source.template_code) && typeof source.revision === "number" ? [{ template_code: asString(source.template_code), revision: asNumber(source.revision), contribution: asOptionalString(source.contribution), moduleGuidance: strings(source.module_guidance), contentStrategyPolicy: isRecord(source.content_strategy_policy) ? source.content_strategy_policy : {}, strategyStage: isRecord(source.strategy_stage) ? { moduleKey: asString(source.strategy_stage.module_key), title: asString(source.strategy_stage.title), purpose: asString(source.strategy_stage.purpose), sourceSessionCode: asString(source.strategy_stage.source_session_code), startMs: asNumber(source.strategy_stage.start_ms), endMs: asNumber(source.strategy_stage.end_ms) } : undefined, referenceExamples: asArray(source.reference_examples).flatMap((example) => isRecord(example) ? [{ moduleKey: asString(example.module_key), exampleText: asString(example.example_text), sourceSessionCode: asString(example.source_session_code), startMs: asNumber(example.start_ms), endMs: asNumber(example.end_ms) }] : []) }] : []), contentRuleRefs: asArray(item.content_rule_refs).flatMap((reference) => isRecord(reference) && asString(reference.rule_code) && asString(reference.rule_text) ? [{ ruleCode: asString(reference.rule_code), ruleKind: asOptionalString(reference.rule_kind), directive: asString(reference.directive), ruleText: asString(reference.rule_text), fingerprintSha256: asOptionalString(reference.fingerprint_sha256) }] : []), interaction_intent: isRecord(item.interaction_intent) ? item.interaction_intent : {}, cta_intent: isRecord(item.cta_intent) ? item.cta_intent : {} }] : []),
  } : undefined;
  const program = isRecord(value.program) ? { program_revision_code: asString(value.program.program_revision_code), revision_number: asNumber(value.program.revision_number), segments: asArray(value.program.segments).flatMap((item) => isRecord(item) ? [{ segment_code: asString(item.segment_code), semantic_goal: asString(item.semantic_goal), program_phase: asString(item.program_phase), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined, entry_condition: asOptionalString(item.entry_condition), exit_condition: asOptionalString(item.exit_condition), product_refs: strings(item.product_refs), interaction_actions: records(item.interaction_actions), cta_actions: records(item.cta_actions), branch_applicability: strings(item.branch_applicability), metadata: isRecord(item.metadata) ? item.metadata : {}, script_block_codes: strings(item.script_block_codes) }] : []) } : undefined;
  const shotList = isRecord(value.shot_list) ? { shot_list_revision_code: asString(value.shot_list.shot_list_revision_code), revision_number: asNumber(value.shot_list.revision_number), shots: asArray(value.shot_list.shots).flatMap((item) => isRecord(item) ? [{ shot_code: asString(item.shot_code), shot_goal: asString(item.shot_goal), program_segment_code: asString(item.program_segment_code), composition_intent: isRecord(item.composition_intent) ? item.composition_intent : {}, material_role_requirements: strings(item.material_role_requirements), audio_actions: records(item.audio_actions), continuity: isRecord(item.continuity) ? item.continuity : {}, acceptance_criteria: strings(item.acceptance_criteria), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined, branch_applicability: strings(item.branch_applicability), must_include: strings(item.must_include), must_avoid: strings(item.must_avoid), script_block_codes: strings(item.script_block_codes) }] : []) } : undefined;
  const storyBrief = isRecord(value.story_brief) ? { story_brief_code: asString(value.story_brief.story_brief_code), revision_number: asNumber(value.story_brief.revision_number), content: isRecord(value.story_brief.content) ? value.story_brief.content : {} } : undefined;
  const factCards = asArray(value.fact_cards).flatMap((item) => isRecord(item) ? [{ fact_card_code: asString(item.fact_card_code), version_number: asNumber(item.version_number), version_code: asString(item.version_code), content_sha256: asString(item.content_sha256) }] : []).filter((item) => Boolean(item.fact_card_code && item.version_number));
  const factClaims = asArray(value.fact_claims).flatMap((item) => isRecord(item) ? [{ claim_code: asString(item.claim_code), fact_code: asString(item.fact_code), source_evidence_code: asString(item.source_evidence_code), claim: asString(item.claim), citation_excerpt: asString(item.citation_excerpt), citation_start_offset: typeof item.citation_start_offset === "number" ? item.citation_start_offset : undefined, citation_end_offset: typeof item.citation_end_offset === "number" ? item.citation_end_offset : undefined, fingerprint_sha256: asString(item.fingerprint_sha256) }] : []).filter((item) => Boolean(item.claim_code && item.fingerprint_sha256));
  const contentRules = asArray(value.content_rules).flatMap((item) => isRecord(item) ? [{ rule_code: asString(item.rule_code), rule_kind: asString(item.rule_kind), directive: asString(item.directive), title: asString(item.title), rule_text: asString(item.rule_text), source_evidence_code: asOptionalString(item.source_evidence_code), fingerprint_sha256: asString(item.fingerprint_sha256) }] : []).filter((item) => Boolean(item.rule_code && item.fingerprint_sha256));
  const designBrief = isRecord(value.design_brief) ? { design_brief_code: asString(value.design_brief.design_brief_code), revision_number: asNumber(value.design_brief.revision_number), status: asString(value.design_brief.status), raw_input: asString(value.design_brief.raw_input), parsed_brief: isRecord(value.design_brief.parsed_brief) ? value.design_brief.parsed_brief : {}, user_overrides: isRecord(value.design_brief.user_overrides) ? value.design_brief.user_overrides : {}, open_questions: asArray(value.design_brief.open_questions).flatMap((item) => isRecord(item) ? [{ field: asString(item.field), question: asString(item.question), recommended_answer: asString(item.recommended_answer), blocking: item.blocking === true }] : []) } : undefined;
  const content = isRecord(value.content) ? value.content : {};
  const templateContributionDecisions = asArray(content.template_contribution_decisions).flatMap((item) => isRecord(item) && asString(item.template_code) ? [{
    templateCode: asString(item.template_code), revision: asNumber(item.revision), selectionRole: asString(item.selection_role),
    availableModules: asArray(item.available_modules).flatMap((entry) => typeof entry === "string" ? [entry] : []),
    acceptedModules: asArray(item.accepted_modules).flatMap((entry) => typeof entry === "string" ? [entry] : []),
    rejectedModules: asArray(item.rejected_modules).flatMap((entry) => typeof entry === "string" ? [entry] : []),
    materialCues: asArray(item.material_cues).flatMap((entry) => typeof entry === "string" ? [entry] : []),
    programOutline: asArray(item.program_outline).flatMap((stage) => isRecord(stage) && asString(stage.module_key) ? [{ moduleKey: asString(stage.module_key), title: asString(stage.title), purpose: asString(stage.purpose), sourceSessionCode: asString(stage.source_session_code), startMs: asNumber(stage.start_ms), endMs: asNumber(stage.end_ms) }] : []),
    reviewedExamples: asArray(item.reviewed_examples).flatMap((example) => isRecord(example) && asString(example.module_key) ? [{ moduleKey: asString(example.module_key), exampleText: asString(example.example_text), sourceSessionCode: asString(example.source_session_code), startMs: asNumber(example.start_ms), endMs: asNumber(example.end_ms) }] : []),
    contentStrategyPolicy: isRecord(item.content_strategy_policy) ? item.content_strategy_policy : {},
  }] : []);
  return { ...base, content, templateContributionDecisions, factCards, factClaims, contentRules, designBrief, generated: value.generated === true, generationMode: asOptionalString(value.generation_mode), storyBrief, script, program, shotList };
}

function chainRevision(value: unknown): ContentChainRevision {
  if (!isRecord(value)) throw new Error("内容链修订响应无效");
  return {
    objectType: asString(value.object_type), objectCode: asString(value.object_code), revisionNumber: asNumber(value.revision_number),
    status: asString(value.status), createdAt: asString(value.created_at), createdBy: asOptionalString(value.created_by),
    confirmedAt: asOptionalString(value.confirmed_at), fingerprintSha256: asOptionalString(value.fingerprint_sha256),
    sources: asArray(value.sources).flatMap((source) => typeof source === "string" ? [source] : []),
  };
}

export const contentProjectsApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.flatMap((row) => summary(row) ?? [])),
  get: (projectCode: string) => requestJson<unknown>(`${ROOT}/${projectCode}`).then(detail),
  workspaceSummary: (projectCode: string) => requestJson<unknown>(`${ROOT}/${projectCode}/workspace-summary`).then(workspaceSummary),
  listChainRevisions: (projectCode: string) => requestJson<unknown[]>(`${ROOT}/${projectCode}/content-chain-revisions`).then((rows) => rows.map(chainRevision)),
  create: (payload: Record<string, unknown>) => postJson<unknown>(ROOT, payload).then((value) => {
    const result = summary(value);
    if (!result) throw new Error("内容项目创建响应无效");
    return result;
  }),
  update: (projectCode: string, payload: Record<string, unknown>) => patchJson<unknown>(`${ROOT}/${projectCode}`, payload).then(detail),
  confirm: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${projectCode}/confirm`, { expected_revision: expectedRevision }).then(detail),
  parseBrief: (projectCode: string, expectedRevision: number, rawInput: string) => postJson<unknown>(`${ROOT}/${projectCode}/parse-brief`, { expected_revision: expectedRevision, raw_input: rawInput }).then(detail),
  reviseBrief: (projectCode: string, expectedRevision: number, overrides: Record<string, unknown>) => patchJson<unknown>(`${ROOT}/${projectCode}/design-brief`, { expected_revision: expectedRevision, overrides }).then(detail),
  reviseScript: (projectCode: string, expectedRevision: number, blocks: Array<{ module_type: string; content: string; estimated_duration_ms?: number; fact_citations: Array<Record<string, unknown>>; template_sources: Array<Record<string, unknown>>; interaction_intent?: Record<string, unknown>; cta_intent?: Record<string, unknown> }>) => postJson<unknown>(`${ROOT}/${projectCode}/script-revision`, { expected_revision: expectedRevision, blocks }).then(detail),
  reviseProgramAndShots: (projectCode: string, expectedRevision: number, segments: Array<Record<string, unknown>>, shots: Array<Record<string, unknown>>) => postJson<unknown>(`${ROOT}/${projectCode}/program-shot-revision`, { expected_revision: expectedRevision, segments, shots }).then(detail),
  confirmBrief: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${projectCode}/design-brief/confirm`, { expected_revision: expectedRevision }).then(detail),
  generate: (projectCode: string) => postJson<unknown>(`${ROOT}/${projectCode}/generate`).then(detail),
};

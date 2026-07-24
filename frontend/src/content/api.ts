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

export interface ContentProjectDetail extends ContentProjectSummary {
  content: Record<string, unknown>;
  templateContributionDecisions: Array<{ templateCode: string; revision: number; selectionRole: string; availableModules: string[]; acceptedModules: string[]; rejectedModules: string[]; materialCues: string[] }>;
  factCards: Array<{ fact_card_code: string; version_number: number; version_code: string; content_sha256: string }>;
  designBrief?: { design_brief_code: string; revision_number: number; status: string; raw_input: string; parsed_brief: Record<string, unknown>; open_questions: Array<{ field: string; question: string; recommended_answer: string; blocking: boolean }> };
  generated: boolean;
  generationMode?: string;
  storyBrief?: { story_brief_code: string; revision_number: number; content: Record<string, unknown> };
  script?: { script_revision_code: string; revision_number: number; title: string; blocks: Array<{ block_code: string; module_type: string; content: string; estimated_duration_ms?: number; fact_citations: Array<{ fact_card_code: string; version_number: number; field_path?: string; claim_text?: string }>; template_sources: Array<{ template_code: string; revision: number; contribution?: string }> }> };
  program?: { program_revision_code: string; revision_number: number; segments: Array<{ segment_code: string; semantic_goal: string; program_phase: string; estimated_duration_ms?: number }> };
  shotList?: { shot_list_revision_code: string; revision_number: number; shots: Array<{ shot_code: string; shot_goal: string; material_role_requirements: string[]; estimated_duration_ms?: number }> };
}

function summary(value: unknown): ContentProjectSummary | undefined {
  if (!isRecord(value)) return undefined;
  const projectCode = asString(value.project_code);
  if (!projectCode) return undefined;
  return { projectCode, title: asString(value.title, projectCode), revisionNumber: asNumber(value.revision_number, 1), status: asString(value.status, "draft"), generationGoal: asString(value.generation_goal), updatedAt: asString(value.updated_at) };
}

function detail(value: unknown): ContentProjectDetail {
  const base = summary(value);
  if (!base || !isRecord(value)) throw new Error("内容项目响应无效");
  const script = isRecord(value.script) ? {
    script_revision_code: asString(value.script.script_revision_code), revision_number: asNumber(value.script.revision_number), title: asString(value.script.title),
    blocks: asArray(value.script.blocks).flatMap((item) => isRecord(item) ? [{ block_code: asString(item.block_code), module_type: asString(item.module_type), content: asString(item.content), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined, fact_citations: asArray(item.fact_citations).flatMap((citation) => isRecord(citation) && asString(citation.fact_card_code) ? [{ fact_card_code: asString(citation.fact_card_code), version_number: asNumber(citation.version_number), field_path: asOptionalString(citation.field_path), claim_text: asOptionalString(citation.claim_text) }] : []), template_sources: asArray(item.template_sources).flatMap((source) => isRecord(source) && asString(source.template_code) && typeof source.revision === "number" ? [{ template_code: asString(source.template_code), revision: asNumber(source.revision), contribution: asOptionalString(source.contribution) }] : []) }] : []),
  } : undefined;
  const program = isRecord(value.program) ? { program_revision_code: asString(value.program.program_revision_code), revision_number: asNumber(value.program.revision_number), segments: asArray(value.program.segments).flatMap((item) => isRecord(item) ? [{ segment_code: asString(item.segment_code), semantic_goal: asString(item.semantic_goal), program_phase: asString(item.program_phase), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined }] : []) } : undefined;
  const shotList = isRecord(value.shot_list) ? { shot_list_revision_code: asString(value.shot_list.shot_list_revision_code), revision_number: asNumber(value.shot_list.revision_number), shots: asArray(value.shot_list.shots).flatMap((item) => isRecord(item) ? [{ shot_code: asString(item.shot_code), shot_goal: asString(item.shot_goal), material_role_requirements: asArray(item.material_role_requirements).flatMap((role) => typeof role === "string" ? [role] : []), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined }] : []) } : undefined;
  const storyBrief = isRecord(value.story_brief) ? { story_brief_code: asString(value.story_brief.story_brief_code), revision_number: asNumber(value.story_brief.revision_number), content: isRecord(value.story_brief.content) ? value.story_brief.content : {} } : undefined;
  const factCards = asArray(value.fact_cards).flatMap((item) => isRecord(item) ? [{ fact_card_code: asString(item.fact_card_code), version_number: asNumber(item.version_number), version_code: asString(item.version_code), content_sha256: asString(item.content_sha256) }] : []).filter((item) => Boolean(item.fact_card_code && item.version_number));
  const designBrief = isRecord(value.design_brief) ? { design_brief_code: asString(value.design_brief.design_brief_code), revision_number: asNumber(value.design_brief.revision_number), status: asString(value.design_brief.status), raw_input: asString(value.design_brief.raw_input), parsed_brief: isRecord(value.design_brief.parsed_brief) ? value.design_brief.parsed_brief : {}, open_questions: asArray(value.design_brief.open_questions).flatMap((item) => isRecord(item) ? [{ field: asString(item.field), question: asString(item.question), recommended_answer: asString(item.recommended_answer), blocking: item.blocking === true }] : []) } : undefined;
  const content = isRecord(value.content) ? value.content : {};
  const templateContributionDecisions = asArray(content.template_contribution_decisions).flatMap((item) => isRecord(item) && asString(item.template_code) ? [{
    templateCode: asString(item.template_code), revision: asNumber(item.revision), selectionRole: asString(item.selection_role),
    availableModules: asArray(item.available_modules).flatMap((entry) => typeof entry === "string" ? [entry] : []),
    acceptedModules: asArray(item.accepted_modules).flatMap((entry) => typeof entry === "string" ? [entry] : []),
    rejectedModules: asArray(item.rejected_modules).flatMap((entry) => typeof entry === "string" ? [entry] : []),
    materialCues: asArray(item.material_cues).flatMap((entry) => typeof entry === "string" ? [entry] : []),
  }] : []);
  return { ...base, content, templateContributionDecisions, factCards, designBrief, generated: value.generated === true, generationMode: asOptionalString(value.generation_mode), storyBrief, script, program, shotList };
}

export const contentProjectsApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.flatMap((row) => summary(row) ?? [])),
  get: (projectCode: string) => requestJson<unknown>(`${ROOT}/${projectCode}`).then(detail),
  create: (payload: Record<string, unknown>) => postJson<unknown>(ROOT, payload).then((value) => {
    const result = summary(value);
    if (!result) throw new Error("内容项目创建响应无效");
    return result;
  }),
  update: (projectCode: string, payload: Record<string, unknown>) => patchJson<unknown>(`${ROOT}/${projectCode}`, payload).then(detail),
  confirm: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${projectCode}/confirm`, { expected_revision: expectedRevision }).then(detail),
  parseBrief: (projectCode: string, expectedRevision: number, rawInput: string) => postJson<unknown>(`${ROOT}/${projectCode}/parse-brief`, { expected_revision: expectedRevision, raw_input: rawInput }).then(detail),
  confirmBrief: (projectCode: string, expectedRevision: number) => postJson<unknown>(`${ROOT}/${projectCode}/design-brief/confirm`, { expected_revision: expectedRevision }).then(detail),
  generate: (projectCode: string) => postJson<unknown>(`${ROOT}/${projectCode}/generate`).then(detail),
};

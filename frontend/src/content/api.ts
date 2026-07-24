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
  factCards: Array<{ fact_card_code: string; version_number: number; version_code: string; content_sha256: string }>;
  generated: boolean;
  generationMode?: string;
  storyBrief?: { story_brief_code: string; revision_number: number; content: Record<string, unknown> };
  script?: { script_revision_code: string; revision_number: number; title: string; blocks: Array<{ block_code: string; module_type: string; content: string; estimated_duration_ms?: number }> };
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
    blocks: asArray(value.script.blocks).flatMap((item) => isRecord(item) ? [{ block_code: asString(item.block_code), module_type: asString(item.module_type), content: asString(item.content), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined }] : []),
  } : undefined;
  const program = isRecord(value.program) ? { program_revision_code: asString(value.program.program_revision_code), revision_number: asNumber(value.program.revision_number), segments: asArray(value.program.segments).flatMap((item) => isRecord(item) ? [{ segment_code: asString(item.segment_code), semantic_goal: asString(item.semantic_goal), program_phase: asString(item.program_phase), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined }] : []) } : undefined;
  const shotList = isRecord(value.shot_list) ? { shot_list_revision_code: asString(value.shot_list.shot_list_revision_code), revision_number: asNumber(value.shot_list.revision_number), shots: asArray(value.shot_list.shots).flatMap((item) => isRecord(item) ? [{ shot_code: asString(item.shot_code), shot_goal: asString(item.shot_goal), material_role_requirements: asArray(item.material_role_requirements).flatMap((role) => typeof role === "string" ? [role] : []), estimated_duration_ms: typeof item.estimated_duration_ms === "number" ? item.estimated_duration_ms : undefined }] : []) } : undefined;
  const storyBrief = isRecord(value.story_brief) ? { story_brief_code: asString(value.story_brief.story_brief_code), revision_number: asNumber(value.story_brief.revision_number), content: isRecord(value.story_brief.content) ? value.story_brief.content : {} } : undefined;
  const factCards = asArray(value.fact_cards).flatMap((item) => isRecord(item) ? [{ fact_card_code: asString(item.fact_card_code), version_number: asNumber(item.version_number), version_code: asString(item.version_code), content_sha256: asString(item.content_sha256) }] : []).filter((item) => Boolean(item.fact_card_code && item.version_number));
  return { ...base, content: isRecord(value.content) ? value.content : {}, factCards, generated: value.generated === true, generationMode: asOptionalString(value.generation_mode), storyBrief, script, program, shotList };
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
  generate: (projectCode: string) => postJson<unknown>(`${ROOT}/${projectCode}/generate`).then(detail),
};

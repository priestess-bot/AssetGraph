import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  BookOpenText,
  CheckCircle2,
  Clapperboard,
  FilePenLine,
  FolderPlus,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  EmptyBlock,
  InlineNotice,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../workbench/components";
import {
  contentProjectsApi,
  type ContentChainRevision,
  type ContentProgramSegment,
  type ContentProjectDetail,
  type ContentShot,
} from "./api";
import { liveResearchApi } from "../live-research/api";
import type { RoomTemplate } from "../live-research/types";
import { knowledgeApi, type ProductFactCard } from "../knowledge/api";

function list(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未完成";
}
function lines(value: unknown): string {
  return Array.isArray(value)
    ? value
        .filter((item): item is string => typeof item === "string")
        .join("\n")
    : "";
}
function actionLines(value: Array<Record<string, unknown>>): string {
  return value
    .map((action) => {
      const code =
        typeof action.action === "string"
          ? action.action
          : typeof action.type === "string"
            ? action.type
            : typeof action.name === "string"
              ? action.name
              : "";
      const detail =
        typeof action.detail === "string"
          ? action.detail
          : typeof action.value === "string"
            ? action.value
            : "";
      return code ? (detail ? `${code} | ${detail}` : code) : "";
    })
    .filter(Boolean)
    .join("\n");
}
function actions(value: string): Array<Record<string, string | undefined>> {
  return list(value).map((entry) => {
    const [action, ...detail] = entry.split("|").map((part) => part.trim());
    return detail.length ? { action, detail: detail.join(" | ") } : { action };
  });
}
function recordText(value: Record<string, unknown>, key: string): string {
  return typeof value[key] === "string" ? value[key] : "";
}
function policySummary(value: Record<string, unknown>): string {
  const duration = typeof value.duration_policy === "object" && value.duration_policy ? value.duration_policy as Record<string, unknown> : {};
  const interaction = typeof value.interaction_policy === "object" && value.interaction_policy ? value.interaction_policy as Record<string, unknown> : {};
  const conversion = typeof value.conversion_policy === "object" && value.conversion_policy ? value.conversion_policy as Record<string, unknown> : {};
  const hostStyle = typeof value.host_style === "object" && value.host_style ? value.host_style as Record<string, unknown> : {};
  const text = (item: unknown) => typeof item === "string" ? item : "";
  const parts = [
    typeof duration.target_duration_seconds === "number" ? `${duration.target_duration_seconds} 秒` : "",
    text(duration.pacing),
    text(interaction.cadence),
    text(conversion.cta_style),
    text(hostStyle.tone),
  ].filter(Boolean);
  return parts.join(" / ") || "未额外声明";
}
function actionPolicySummary(value?: Record<string, unknown>): string {
  if (!value) return "";
  const policy = typeof value.policy === "object" && value.policy ? value.policy as Record<string, unknown> : {};
  const parts = Object.entries(policy).flatMap(([key, item]) => typeof item === "string" || typeof item === "number" ? [`${key}: ${item}`] : []);
  return parts.join(" / ");
}
function templateEvidenceHref(
  sourceSessionCode: string,
  startMs: number,
  endMs: number,
): string {
  const query = new URLSearchParams({
    view: "sessions",
    session: sourceSessionCode,
    in: String(startMs / 1000),
    out: String(endMs / 1000),
  });
  return `/research/live-sources?${query.toString()}`;
}
function templateEvidenceLinks(
  sources: NonNullable<ContentProjectDetail["script"]>["blocks"][number]["template_sources"],
): Array<{ key: string; label: string; sourceSessionCode: string; startMs: number; endMs: number }> {
  return sources.flatMap((source) => [
    ...(source.strategyStage ? [{
      key: `stage:${source.template_code}:${source.strategyStage.moduleKey}:${source.strategyStage.startMs}`,
      label: `阶段证据：${source.strategyStage.title}`,
      sourceSessionCode: source.strategyStage.sourceSessionCode,
      startMs: source.strategyStage.startMs,
      endMs: source.strategyStage.endMs,
    }] : []),
    ...source.referenceExamples.map((example, index) => ({
      key: `example:${source.template_code}:${example.moduleKey}:${example.startMs}:${index}`,
      label: `例证：${example.exampleText}`,
      sourceSessionCode: example.sourceSessionCode,
      startMs: example.startMs,
      endMs: example.endMs,
    })),
  ]);
}
function toggleBranch(
  value: string[],
  branch: "live_room" | "rendered_video",
): string[] {
  return value.includes(branch)
    ? value.filter((item) => item !== branch)
    : [...value, branch];
}
function BranchApplicabilityField({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <fieldset className="content-branch-field">
      <legend>适用分支</legend>
      <label>
        <input
          type="checkbox"
          checked={value.includes("live_room")}
          onChange={() => onChange(toggleBranch(value, "live_room"))}
        />
        直播间
      </label>
      <label>
        <input
          type="checkbox"
          checked={value.includes("rendered_video")}
          onChange={() => onChange(toggleBranch(value, "rendered_video"))}
        />
        成片
      </label>
    </fieldset>
  );
}

type ScriptBlock = NonNullable<
  ContentProjectDetail["script"]
>["blocks"][number];
type ScriptBlockDraft = ScriptBlock & { editorKey: string };
type ProgramSegmentDraft = ContentProgramSegment & { editorKey: string };
type ShotDraft = ContentShot & {
  editorKey: string;
  programSegmentIndex: number;
};
type ProgramShotPayload = {
  segments: Array<Record<string, unknown>>;
  shots: Array<Record<string, unknown>>;
};
let scriptDraftSequence = 1;
function scriptBlockDraft(block: ScriptBlock): ScriptBlockDraft {
  return { ...block, editorKey: block.block_code };
}
function newScriptBlockDraft(): ScriptBlockDraft {
  const editorKey = `new-script-block-${scriptDraftSequence++}`;
  return {
    block_code: editorKey,
    editorKey,
    module_type: "story",
    content: "",
    estimated_duration_ms: 30_000,
    fact_citations: [],
    template_sources: [],
    contentRuleRefs: [],
    interaction_intent: {},
    cta_intent: {},
  };
}
let programShotDraftSequence = 1;
function programSegmentDraft(
  segment: ContentProgramSegment,
): ProgramSegmentDraft {
  return { ...segment, editorKey: segment.segment_code };
}
function newProgramSegmentDraft(
  scriptBlockCodes: string[],
): ProgramSegmentDraft {
  const editorKey = `new-program-segment-${programShotDraftSequence++}`;
  return {
    segment_code: editorKey,
    editorKey,
    semantic_goal: "",
    program_phase: "body",
    estimated_duration_ms: undefined,
    entry_condition: undefined,
    exit_condition: undefined,
    product_refs: [],
    interaction_actions: [],
    cta_actions: [],
    branch_applicability: ["live_room", "rendered_video"],
    metadata: {},
    script_block_codes: scriptBlockCodes.slice(0, 1),
  };
}
function shotDraft(shot: ContentShot, programSegmentIndex: number): ShotDraft {
  return { ...shot, editorKey: shot.shot_code, programSegmentIndex };
}
function newShotDraft(
  programSegmentIndex: number,
  scriptBlockCodes: string[],
): ShotDraft {
  const editorKey = `new-shot-${programShotDraftSequence++}`;
  return {
    shot_code: editorKey,
    editorKey,
    programSegmentIndex,
    shot_goal: "",
    program_segment_code: "",
    composition_intent: { style: "talking_head" },
    material_role_requirements: ["digital_human", "background"],
    audio_actions: [],
    continuity: {},
    acceptance_criteria: ["script_visible", "required_materials_present"],
    estimated_duration_ms: undefined,
    branch_applicability: ["live_room", "rendered_video"],
    must_include: [],
    must_avoid: [],
    script_block_codes: scriptBlockCodes.slice(0, 1),
  };
}

export interface ContentTemplateRecommendation {
  templateCode: string;
  score: number;
  signals: string[];
}

export function recommendContentTemplates(
  templates: RoomTemplate[],
  input: string,
): ContentTemplateRecommendation[] {
  const normalized = input.trim().toLocaleLowerCase();
  if (!normalized) return [];
  return templates
    .map((template) => {
      const signals: string[] = [];
      let score = 0;
      const category = template.contentStrategy.targetCategory.trim();
      if (category && normalized.includes(category.toLocaleLowerCase())) {
        score += 100;
        signals.push(`品类：${category}`);
      }
      for (const module of template.contentStrategy.programOutline) {
        for (const value of [module.title, module.purpose]) {
          const term = value.trim();
          if (
            term.length >= 2 &&
            normalized.includes(term.toLocaleLowerCase())
          ) {
            score += 20;
            signals.push(`模块：${module.title || module.moduleKey}`);
            break;
          }
        }
      }
      for (const tag of template.contentStrategy.compatibilityTags) {
        const term = tag.trim();
        if (term.length >= 2 && normalized.includes(term.toLocaleLowerCase())) {
          score += 12;
          signals.push(`标签：${term}`);
        }
      }
      return {
        templateCode: template.template_code,
        score,
        signals: Array.from(new Set(signals)),
      };
    })
    .filter((item) => item.score > 0)
    .sort(
      (left, right) =>
        right.score - left.score ||
        left.templateCode.localeCompare(right.templateCode),
    );
}

function approvedFactVersion(fact: ProductFactCard) {
  return fact.versions.find(
    (version) =>
      version.versionNumber === fact.currentApprovedVersion &&
      version.status === "approved",
  );
}
function factContentString(fact: ProductFactCard, key: string): string {
  const value = approvedFactVersion(fact)?.content[key];
  return typeof value === "string" ? value : "";
}
function factContentList(fact: ProductFactCard, key: string): string[] {
  const value = approvedFactVersion(fact)?.content[key];
  return Array.isArray(value)
    ? value.filter(
        (item): item is string =>
          typeof item === "string" && Boolean(item.trim()),
      )
    : [];
}
function factScopeSummary(fact: ProductFactCard): string {
  const platforms = factContentList(fact, "applicable_platforms");
  const validFrom = factContentString(fact, "valid_from");
  const validUntil = factContentString(fact, "valid_until");
  return `${platforms.length ? platforms.join("/") : "不限平台"} · ${validFrom || "未限制"} 至 ${validUntil || "未限制"}`;
}
function factSourceSummary(fact: ProductFactCard): string {
  const source = approvedFactVersion(fact)?.content.source_references;
  if (
    !Array.isArray(source) ||
    !source.length ||
    typeof source[0] !== "object" ||
    source[0] === null
  )
    return "未登记来源";
  const item = source[0] as Record<string, unknown>;
  return typeof item.url === "string"
    ? item.url
    : typeof item.kind === "string"
      ? item.kind
      : "已登记来源";
}

export function findFactCardConflicts(
  facts: ProductFactCard[],
  selectedCodes: string[],
  platform = "",
): string[] {
  const selected = facts.filter((fact) =>
    selectedCodes.includes(fact.factCardCode),
  );
  const conflicts: string[] = [];
  const byProduct = new Map<string, ProductFactCard[]>();
  for (const fact of selected) {
    const productCode =
      fact.productCode || factContentString(fact, "product_code");
    if (productCode)
      byProduct.set(productCode, [...(byProduct.get(productCode) ?? []), fact]);
    const platforms = factContentList(fact, "applicable_platforms").map(
      (item) => item.toLowerCase(),
    );
    if (
      platform &&
      platforms.length &&
      !platforms.includes("all") &&
      !platforms.includes(platform.toLowerCase())
    )
      conflicts.push(`${fact.factCardCode} 不适用于 ${platform}`);
  }
  for (const [productCode, productFacts] of byProduct) {
    if (productFacts.length < 2) continue;
    for (const key of ["product_name", "brand", "category", "positioning"]) {
      const values = Array.from(
        new Set(
          productFacts
            .map((fact) => factContentString(fact, key))
            .filter(Boolean),
        ),
      );
      if (values.length > 1)
        conflicts.push(
          `${productCode} 的 ${key} 在 ${productFacts.map((fact) => fact.factCardCode).join("/")} 中不一致`,
        );
    }
  }
  return conflicts;
}

function ProjectCreate({ onCreated }: { onCreated: (code: string) => void }) {
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [theme, setTheme] = useState("");
  const [story, setStory] = useState("");
  const [design, setDesign] = useState("");
  const [platform, setPlatform] = useState("douyin");
  const [audience, setAudience] = useState("");
  const [persona, setPersona] = useState("");
  const [tone, setTone] = useState("");
  const [duration, setDuration] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [mustAvoid, setMustAvoid] = useState("");
  const [interactions, setInteractions] = useState("");
  const [productOrder, setProductOrder] = useState("");
  const [conversion, setConversion] = useState("");
  const [staging, setStaging] = useState("");
  const [visual, setVisual] = useState("");
  const [audio, setAudio] = useState("");
  const [factCodes, setFactCodes] = useState<string[]>([]);
  const [claimCodes, setClaimCodes] = useState<string[]>([]);
  const [ruleCodes, setRuleCodes] = useState<string[]>([]);
  const [primaryTemplate, setPrimaryTemplate] = useState("");
  const [secondaryTemplates, setSecondaryTemplates] = useState<string[]>([]);
  const [acceptedModules, setAcceptedModules] = useState<
    Record<string, string[]>
  >({});
  const templates = useQuery({
    queryKey: ["live-research", "templates"],
    queryFn: liveResearchApi.listTemplates,
  });
  const facts = useQuery({
    queryKey: ["product-fact-cards"],
    queryFn: knowledgeApi.listProductFactCards,
  });
  const claims = useQuery({
    queryKey: ["knowledge-fact-claims"],
    queryFn: knowledgeApi.listFactClaims,
  });
  const rules = useQuery({
    queryKey: ["knowledge-content-rules"],
    queryFn: knowledgeApi.listContentRules,
  });
  const usableTemplates = useMemo(
    () =>
      (templates.data ?? []).filter(
        (template) =>
          template.templateKind === "content_strategy" &&
          Boolean(template.published_revision) &&
          template.contentReadiness === "ready" &&
          template.buildability === "reference_only",
      ),
    [templates.data],
  );
  const recommendedTemplates = useMemo(
    () =>
      recommendContentTemplates(
        usableTemplates,
        [goal, theme, story, design].filter(Boolean).join("\n"),
      ).slice(0, 3),
    [design, goal, story, theme, usableTemplates],
  );
  const approvedFacts = (facts.data ?? []).filter(
    (fact) =>
      fact.currentApprovedVersion &&
      fact.versions.some(
        (version) =>
          version.versionNumber === fact.currentApprovedVersion &&
          version.status === "approved",
      ),
  );
  const approvedClaims = (claims.data ?? []).filter(
    (claim) => claim.status === "approved" && claim.sourceStatus === "approved",
  );
  const approvedRules = (rules.data ?? []).filter(
    (rule) => rule.status === "approved" && (!rule.sourceEvidenceCode || rule.sourceStatus === "approved"),
  );
  const factConflicts = findFactCardConflicts(
    approvedFacts,
    factCodes,
    platform,
  );
  const selectedTemplateCodes = [primaryTemplate, ...secondaryTemplates].filter(
    Boolean,
  );
  const conflictingModules = selectedTemplateCodes
    .flatMap((code) => acceptedModules[code] ?? [])
    .filter(
      (module, _index, values) =>
        values.filter((item) => item === module).length > 1,
    );
  const moduleKeys = (templateCode: string) =>
    usableTemplates
      .find((template) => template.template_code === templateCode)
      ?.contentStrategy.programOutline.map((module) => module.moduleKey)
      .filter(Boolean) ?? [];
  const toggleSecondary = (templateCode: string) =>
    setSecondaryTemplates((current) =>
      current.includes(templateCode)
        ? current.filter((code) => code !== templateCode)
        : [...current, templateCode],
    );
  const toggleFact = (factCardCode: string) =>
    setFactCodes((current) =>
      current.includes(factCardCode)
        ? current.filter((code) => code !== factCardCode)
        : [...current, factCardCode],
    );
  const toggleClaim = (claimCode: string) =>
    setClaimCodes((current) =>
      current.includes(claimCode)
        ? current.filter((code) => code !== claimCode)
        : [...current, claimCode],
    );
  const toggleRule = (ruleCode: string) =>
    setRuleCodes((current) =>
      current.includes(ruleCode)
        ? current.filter((code) => code !== ruleCode)
        : [...current, ruleCode],
    );
  const choosePrimary = (templateCode: string) => {
    setPrimaryTemplate(templateCode);
    setSecondaryTemplates((current) =>
      current.filter((code) => code !== templateCode),
    );
    if (templateCode)
      setAcceptedModules((current) => ({
        ...current,
        [templateCode]: moduleKeys(templateCode),
      }));
  };
  const toggleModule = (templateCode: string, moduleKey: string) =>
    setAcceptedModules((current) => ({
      ...current,
      [templateCode]: current[templateCode]?.includes(moduleKey)
        ? current[templateCode].filter((item) => item !== moduleKey)
        : [...(current[templateCode] ?? []), moduleKey],
    }));
  const mutation = useMutation({
    mutationFn: () =>
      contentProjectsApi.create({
        title,
        generation_goal: goal,
        theme: theme || undefined,
        story: story || undefined,
        detailed_design: design || undefined,
        platform: platform || undefined,
        audience: audience || undefined,
        persona: persona || undefined,
        tone: tone || undefined,
        target_duration_seconds: duration ? Number(duration) : undefined,
        must_include: list(mustInclude),
        must_avoid: list(mustAvoid),
        interaction_requirements: list(interactions),
        product_order: list(productOrder),
        conversion_requirements: list(conversion),
        staging_requirements: list(staging),
        visual_requirements: list(visual),
        audio_requirements: list(audio),
        fact_card_codes: factCodes,
        fact_claim_codes: claimCodes,
        content_rule_codes: ruleCodes,
        primary_template_code: primaryTemplate || undefined,
        secondary_template_codes: secondaryTemplates,
        template_contribution_decisions: selectedTemplateCodes.map(
          (templateCode) => ({
            template_code: templateCode,
            accepted_modules: acceptedModules[templateCode] ?? [],
          }),
        ),
      }),
    onSuccess: (project) => onCreated(project.projectCode),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() && goal.trim()) mutation.mutate();
  };
  return (
    <form className="content-project-form" onSubmit={submit}>
      <div className="wb-form-grid">
        <label className="wb-field">
          <span>内容项目名称</span>
          <input
            className="wb-input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="夏日聚餐选酒直播"
          />
        </label>
        <label className="wb-field">
          <span>生成目标</span>
          <input
            className="wb-input"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="帮助观众在三分钟内选出适合聚会的酒"
          />
        </label>
        <label className="wb-field">
          <span>平台</span>
          <input
            className="wb-input"
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
          />
        </label>
        <label className="wb-field">
          <span>目标时长（秒）</span>
          <input
            className="wb-input"
            type="number"
            min="30"
            value={duration}
            onChange={(event) => setDuration(event.target.value)}
          />
        </label>
        <label className="wb-field">
          <span>受众</span>
          <input
            className="wb-input"
            value={audience}
            onChange={(event) => setAudience(event.target.value)}
          />
        </label>
        <label className="wb-field">
          <span>主播人设与语气</span>
          <input
            className="wb-input"
            value={`${persona}${persona && tone ? " / " : ""}${tone}`}
            onChange={(event) => {
              const [nextPersona, nextTone = ""] =
                event.target.value.split("/");
              setPersona(nextPersona.trim());
              setTone(nextTone.trim());
            }}
          />
        </label>
        <label className="wb-field">
          <span>主题</span>
          <input
            className="wb-input"
            value={theme}
            onChange={(event) => setTheme(event.target.value)}
          />
        </label>
        <label className="wb-field">
          <span>故事</span>
          <input
            className="wb-input"
            value={story}
            onChange={(event) => setStory(event.target.value)}
          />
        </label>
        <label className="wb-field wide">
          <span>详细直播间设计</span>
          <textarea
            className="wb-textarea"
            value={design}
            onChange={(event) => setDesign(event.target.value)}
            placeholder="可填写舞台、节奏、互动和视觉要求。"
          />
        </label>
        <label className="wb-field">
          <span>必含 / 禁用要求</span>
          <textarea
            className="wb-textarea"
            value={`${mustInclude}${mustInclude && mustAvoid ? "\n---\n" : ""}${mustAvoid}`}
            onChange={(event) => {
              const [include, avoid = ""] = event.target.value.split("---");
              setMustInclude(include);
              setMustAvoid(avoid);
            }}
            placeholder="必含项逐行填写；用 --- 分隔禁用项"
          />
        </label>
        <label className="wb-field">
          <span>互动要求</span>
          <textarea
            className="wb-textarea"
            value={interactions}
            onChange={(event) => setInteractions(event.target.value)}
            placeholder="每行一项"
          />
        </label>
        <label className="wb-field">
          <span>商品讲解顺序</span>
          <textarea
            className="wb-textarea"
            value={productOrder}
            onChange={(event) => setProductOrder(event.target.value)}
            placeholder="每行一个商品编码或名称"
          />
        </label>
        <label className="wb-field">
          <span>促单要求</span>
          <textarea
            className="wb-textarea"
            value={conversion}
            onChange={(event) => setConversion(event.target.value)}
            placeholder="每行一项"
          />
        </label>
        <label className="wb-field">
          <span>舞台要求</span>
          <textarea
            className="wb-textarea"
            value={staging}
            onChange={(event) => setStaging(event.target.value)}
            placeholder="每行一项"
          />
        </label>
        <label className="wb-field">
          <span>视觉要求</span>
          <textarea
            className="wb-textarea"
            value={visual}
            onChange={(event) => setVisual(event.target.value)}
            placeholder="每行一项"
          />
        </label>
        <label className="wb-field">
          <span>音频要求</span>
          <textarea
            className="wb-textarea"
            value={audio}
            onChange={(event) => setAudio(event.target.value)}
            placeholder="每行一项"
          />
        </label>
        <section className="wb-field wide">
          <span>已批准事实卡</span>
          {facts.isLoading ? (
            <small>正在读取可用事实卡。</small>
          ) : facts.error ? (
            <InlineNotice tone="warning" title="事实卡列表暂不可用">
              仍可创建无事实卡内容项目。
            </InlineNotice>
          ) : approvedFacts.length ? (
        <div className="content-template-options">
              {approvedFacts.map((fact) => (
                <label key={fact.factCardCode}>
                  <input
                    type="checkbox"
                    checked={factCodes.includes(fact.factCardCode)}
                    onChange={() => toggleFact(fact.factCardCode)}
                  />
                  {fact.title}{" "}
                  <code>
                    {fact.factCardCode} · v{fact.currentApprovedVersion}
                  </code>
                  <small>
                    {factScopeSummary(fact)} · {factSourceSummary(fact)}
                  </small>
                </label>
              ))}
            </div>
          ) : (
            <small>暂无已批准事实卡。</small>
          )}
          {factConflicts.length ? (
            <InlineNotice tone="warning" title="事实卡选择冲突">
              {factConflicts.join("；")}
            </InlineNotice>
          ) : null}
        </section>
        <section className="wb-field wide">
          <span>已批准事实声明</span>
          {claims.isLoading ? (
            <small>正在读取可用事实声明。</small>
          ) : claims.error ? (
            <InlineNotice tone="warning" title="事实声明列表暂不可用">
              仍可创建无事实声明内容项目。
            </InlineNotice>
          ) : approvedClaims.length ? (
            <div className="content-template-options">
              {approvedClaims.map((claim) => (
                <label key={claim.claimCode}>
                  <input
                    type="checkbox"
                    checked={claimCodes.includes(claim.claimCode)}
                    onChange={() => toggleClaim(claim.claimCode)}
                  />
                  {claim.factTitle} <code>{claim.claimCode}</code>
                  <small>
                    {claim.claim} · 证据 {claim.sourceEvidenceCode}
                  </small>
                </label>
              ))}
            </div>
          ) : (
            <small>暂无已批准事实声明。</small>
          )}
        </section>
        <section className="wb-field wide">
          <span>已批准内容规则</span>
          {rules.isLoading ? <small>正在读取内容规则。</small> : rules.error ? <InlineNotice tone="warning" title="内容规则暂不可用">仍可创建不使用规则的内容项目。</InlineNotice> : approvedRules.length ? <div className="content-template-options">{approvedRules.map((rule) => <label key={rule.ruleCode}><input type="checkbox" checked={ruleCodes.includes(rule.ruleCode)} onChange={() => toggleRule(rule.ruleCode)} />{rule.title}<code>{rule.ruleKind} · {rule.directive}</code><small>{rule.ruleText}</small></label>)}</div> : <small>暂无已批准内容规则。</small>}
        </section>
        <section className="wb-field wide">
          <span>内容策略参考模板</span>
          {templates.isLoading ? (
            <small>正在读取已发布内容策略。</small>
          ) : templates.error ? (
            <InlineNotice tone="warning" title="模板列表暂不可用">
              仍可创建无模板内容项目。
            </InlineNotice>
          ) : usableTemplates.length ? (
            <div className="content-template-options">
              <label>
                <input
                  type="radio"
                  name="primary-template"
                  checked={!primaryTemplate}
                  onChange={() => choosePrimary("")}
                />
                不选主模板
              </label>
              {recommendedTemplates.length ? (
                <div className="content-template-recommendations">
                  <span>按当前目标匹配</span>
                  {recommendedTemplates.map((recommendation) => {
                    const template = usableTemplates.find(
                      (item) =>
                        item.template_code === recommendation.templateCode,
                    );
                    if (!template) return null;
                    const repeatedModules =
                      template.contentStrategy.programOutline
                        .map((module) => module.moduleKey)
                        .filter((moduleKey) =>
                          selectedTemplateCodes.some(
                            (code) =>
                              code !== template.template_code &&
                              (acceptedModules[code] ?? []).includes(moduleKey),
                          ),
                        );
                    return (
                      <div
                        key={recommendation.templateCode}
                        className="content-template-recommendation"
                      >
                        <div>
                          <strong>{template.title}</strong>
                          <small>
                            {recommendation.signals.join(" / ")}
                            {repeatedModules.length
                              ? ` · 与已采纳模块重复：${repeatedModules.join("、")}`
                              : ""}
                          </small>
                        </div>
                        {primaryTemplate === template.template_code ? (
                          <StatusBadge label="当前主模板" tone="success" />
                        ) : (
                          <button
                            type="button"
                            className="wb-button"
                            onClick={() =>
                              choosePrimary(template.template_code)
                            }
                          >
                            设为主模板
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {usableTemplates.map((template) => {
                const selected =
                  template.template_code === primaryTemplate ||
                  secondaryTemplates.includes(template.template_code);
                return (
                  <div
                    key={template.template_code}
                    className="content-template-choice"
                  >
                    <label>
                      <input
                        type="radio"
                        name="primary-template"
                        checked={primaryTemplate === template.template_code}
                        onChange={() => choosePrimary(template.template_code)}
                      />
                      主模板：{template.title}{" "}
                      <code>
                        {template.template_code} · r
                        {template.published_revision}
                      </code>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={secondaryTemplates.includes(
                          template.template_code,
                        )}
                        disabled={primaryTemplate === template.template_code}
                        onChange={() => toggleSecondary(template.template_code)}
                      />
                      作为次要补充
                    </label>
                    <small>
                      {template.contentStrategy.targetCategory || "未标注品类"}{" "}
                      ·{" "}
                      {template.contentStrategy.programOutline
                        .map((module) => module.title)
                        .join(" / ") || "未标注模块"}
                    </small>
                    {selected ? (
                      <div className="content-module-options">
                        {template.contentStrategy.programOutline.map(
                          (module) => (
                            <label key={module.moduleKey}>
                              <input
                                type="checkbox"
                                checked={(
                                  acceptedModules[template.template_code] ?? []
                                ).includes(module.moduleKey)}
                                onChange={() =>
                                  toggleModule(
                                    template.template_code,
                                    module.moduleKey,
                                  )
                                }
                              />
                              采纳模块：{module.title || module.moduleKey}
                            </label>
                          ),
                        )}
                      </div>
                    ) : null}
                  </div>
                );
              })}
              {conflictingModules.length ? (
                <InlineNotice tone="warning" title="模块贡献冲突">
                  同一模块不能同时从多个模板采纳：
                  {Array.from(new Set(conflictingModules)).join("、")}
                  。请保留一个来源，或取消次要模板的对应模块。
                </InlineNotice>
              ) : null}
            </div>
          ) : (
            <small>暂无可选的已发布内容策略模板。</small>
          )}
        </section>
      </div>
      {mutation.error ? (
        <InlineNotice tone="danger" title="内容项目创建失败">
          {errorMessage(mutation.error)}
        </InlineNotice>
      ) : null}
      <div className="wb-form-actions">
        <button
          className="wb-button wb-button-primary"
          disabled={
            mutation.isPending ||
            !title.trim() ||
            !goal.trim() ||
            conflictingModules.length > 0
          }
        >
          <FolderPlus size={15} aria-hidden="true" />
          创建内容项目
        </button>
      </div>
    </form>
  );
}

function DesignBriefPanel({
  detail,
  onParse,
  onRevise,
  onConfirm,
  parsing,
  revising,
  confirming,
}: {
  detail: ContentProjectDetail;
  onParse: (rawInput: string) => void;
  onRevise: (overrides: Record<string, unknown>) => void;
  onConfirm: () => void;
  parsing: boolean;
  revising: boolean;
  confirming: boolean;
}) {
  const [rawInput, setRawInput] = useState(
    detail.designBrief?.raw_input ??
      String(
        detail.content.detailed_design ??
          detail.content.story ??
          detail.generationGoal,
      ),
  );
  const brief = detail.designBrief;
  const parsed = brief?.parsed_brief ?? {};
  const [overrides, setOverrides] = useState<Record<string, unknown>>({});
  useEffect(() => {
    setRawInput(
      detail.designBrief?.raw_input ??
        String(
          detail.content.detailed_design ??
            detail.content.story ??
            detail.generationGoal,
        ),
    );
    setOverrides({});
  }, [
    detail.projectCode,
    detail.designBrief?.design_brief_code,
    detail.designBrief?.revision_number,
    detail.content.detailed_design,
    detail.content.story,
    detail.generationGoal,
  ]);
  const textValue = (key: string) =>
    typeof overrides[key] === "string"
      ? (overrides[key] as string)
      : typeof parsed[key] === "string"
        ? (parsed[key] as string)
        : "";
  const listValue = (key: string) => lines(overrides[key] ?? parsed[key]);
  const durationValue =
    overrides.duration_seconds ?? parsed.duration_seconds ?? "";
  const changeText = (key: string, value: string) =>
    setOverrides((current) => ({ ...current, [key]: value }));
  const changeList = (key: string, value: string) =>
    setOverrides((current) => ({ ...current, [key]: list(value) }));
  const changeDuration = (value: string) =>
    setOverrides((current) => ({
      ...current,
      duration_seconds: value ? Number(value) : 0,
    }));
  const validOverrides = Object.values(overrides).every((value) =>
    Array.isArray(value)
      ? value.every(
          (entry) => typeof entry === "string" && Boolean(entry.trim()),
        )
      : typeof value === "number"
        ? Number.isInteger(value) && value >= 30 && value <= 86_400
        : typeof value === "string" && Boolean(value.trim()),
  );
  return (
    <section className="wb-section">
      <SectionHeader
        kicker="PARSE BRIEF"
        title="设计说明"
        actions={
          brief ? (
            <StatusBadge
              label={brief.status === "confirmed" ? "已确认" : "待确认"}
              tone={brief.status === "confirmed" ? "success" : "warning"}
            />
          ) : undefined
        }
      />
      <div className="wb-section-body">
        <label className="wb-field">
          <span>补充设计说明</span>
          <textarea
            className="wb-textarea"
            value={rawInput}
            onChange={(event) => setRawInput(event.target.value)}
          />
        </label>
        <div className="wb-form-actions">
          <button
            type="button"
            className="wb-button"
            disabled={parsing || !rawInput.trim()}
            onClick={() => onParse(rawInput)}
          >
            <Sparkles size={14} aria-hidden="true" />
            解析说明
          </button>
          {brief?.status === "draft" ? (
            <button
              type="button"
              className="wb-button wb-button-primary"
              disabled={confirming}
              onClick={onConfirm}
            >
              <CheckCircle2 size={14} aria-hidden="true" />
              确认设计说明
            </button>
          ) : null}
        </div>
        {brief ? (
          <>
            <div className="content-key-value">
              <div>
                <span>解析修订</span>
                <strong>
                  {brief.design_brief_code} · r{brief.revision_number}
                </strong>
              </div>
              <div>
                <span>人工覆盖</span>
                <strong>
                  {Object.keys(brief.user_overrides).length
                    ? Object.keys(brief.user_overrides).join("、")
                    : "无"}
                </strong>
              </div>
            </div>
            {brief.status === "draft" ? (
              <div className="content-project-form">
                <div className="wb-form-grid">
                  <label className="wb-field wide">
                    <span>目标</span>
                    <textarea
                      className="wb-textarea"
                      value={textValue("objective")}
                      onChange={(event) =>
                        changeText("objective", event.target.value)
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>主题</span>
                    <input
                      className="wb-input"
                      value={textValue("theme")}
                      onChange={(event) =>
                        changeText("theme", event.target.value)
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>受众</span>
                    <input
                      className="wb-input"
                      value={textValue("audience")}
                      onChange={(event) =>
                        changeText("audience", event.target.value)
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>主播人设</span>
                    <input
                      className="wb-input"
                      value={textValue("persona")}
                      onChange={(event) =>
                        changeText("persona", event.target.value)
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>语气</span>
                    <input
                      className="wb-input"
                      value={textValue("tone")}
                      onChange={(event) =>
                        changeText("tone", event.target.value)
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>平台</span>
                    <input
                      className="wb-input"
                      value={textValue("platform")}
                      onChange={(event) =>
                        changeText("platform", event.target.value)
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>目标时长（秒）</span>
                    <input
                      className="wb-input"
                      type="number"
                      min="30"
                      max="86400"
                      value={String(durationValue)}
                      onChange={(event) => changeDuration(event.target.value)}
                    />
                  </label>
                  <label className="wb-field wide">
                    <span>故事</span>
                    <textarea
                      className="wb-textarea"
                      value={textValue("story")}
                      onChange={(event) =>
                        changeText("story", event.target.value)
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>优先项</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("priorities")}
                      onChange={(event) =>
                        changeList("priorities", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>必含项</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("must_include")}
                      onChange={(event) =>
                        changeList("must_include", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>禁用项</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("must_avoid")}
                      onChange={(event) =>
                        changeList("must_avoid", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>舞台要求</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("staging")}
                      onChange={(event) =>
                        changeList("staging", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>互动要求</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("interaction")}
                      onChange={(event) =>
                        changeList("interaction", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>促单要求</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("conversion")}
                      onChange={(event) =>
                        changeList("conversion", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>视觉要求</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("visual")}
                      onChange={(event) =>
                        changeList("visual", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>音频要求</span>
                    <textarea
                      className="wb-textarea"
                      value={listValue("audio")}
                      onChange={(event) =>
                        changeList("audio", event.target.value)
                      }
                      placeholder="每行一项"
                    />
                  </label>
                </div>
                <div className="wb-form-actions">
                  <button
                    type="button"
                    className="wb-button wb-button-primary"
                    disabled={
                      revising ||
                      !Object.keys(overrides).length ||
                      !validOverrides
                    }
                    onClick={() => onRevise(overrides)}
                  >
                    <FilePenLine size={15} aria-hidden="true" />
                    保存解析修订
                  </button>
                </div>
              </div>
            ) : (
              <div className="content-key-value">
                {Object.entries(parsed)
                  .filter(([key]) => key !== "raw_input_sha256")
                  .map(([key, value]) => (
                    <div key={key}>
                      <span>{key}</span>
                      <strong>
                        {Array.isArray(value)
                          ? value.join("、")
                          : String(value ?? "未填写")}
                      </strong>
                    </div>
                  ))}
              </div>
            )}
            {brief.open_questions.length ? (
              <ol className="content-flow-list">
                {brief.open_questions.map((question) => (
                  <li key={question.field}>
                    <span>{question.blocking ? "阻断" : "待定"}</span>
                    <div>
                      <strong>{question.question}</strong>
                      <small>
                        {question.field} · 建议：{question.recommended_answer}
                      </small>
                    </div>
                  </li>
                ))}
              </ol>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}

function ProjectInputEditor({
  detail,
  onSave,
  saving,
}: {
  detail: ContentProjectDetail;
  onSave: (payload: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const content = detail.content;
  const [title, setTitle] = useState(detail.title);
  const [goal, setGoal] = useState(detail.generationGoal);
  const [theme, setTheme] = useState(String(content.theme ?? ""));
  const [story, setStory] = useState(String(content.story ?? ""));
  const [design, setDesign] = useState(String(content.detailed_design ?? ""));
  const [platform, setPlatform] = useState(String(content.platform ?? ""));
  const [audience, setAudience] = useState(String(content.audience ?? ""));
  const [persona, setPersona] = useState(String(content.persona ?? ""));
  const [tone, setTone] = useState(String(content.tone ?? ""));
  const [duration, setDuration] = useState(
    content.target_duration_seconds
      ? String(content.target_duration_seconds)
      : "",
  );
  const [productOrder, setProductOrder] = useState(lines(content.product_order));
  const [mustInclude, setMustInclude] = useState(lines(content.must_include));
  const [mustAvoid, setMustAvoid] = useState(lines(content.must_avoid));
  const [interactions, setInteractions] = useState(
    lines(content.interaction_requirements),
  );
  const [conversion, setConversion] = useState(
    lines(content.conversion_requirements),
  );
  const [staging, setStaging] = useState(lines(content.staging_requirements));
  const [visual, setVisual] = useState(lines(content.visual_requirements));
  const [audio, setAudio] = useState(lines(content.audio_requirements));
  useEffect(() => {
    setTitle(detail.title);
    setGoal(detail.generationGoal);
    setTheme(String(content.theme ?? ""));
    setStory(String(content.story ?? ""));
    setDesign(String(content.detailed_design ?? ""));
    setPlatform(String(content.platform ?? ""));
    setAudience(String(content.audience ?? ""));
    setPersona(String(content.persona ?? ""));
    setTone(String(content.tone ?? ""));
    setDuration(
      content.target_duration_seconds
        ? String(content.target_duration_seconds)
        : "",
    );
    setProductOrder(lines(content.product_order));
    setMustInclude(lines(content.must_include));
    setMustAvoid(lines(content.must_avoid));
    setInteractions(lines(content.interaction_requirements));
    setConversion(lines(content.conversion_requirements));
    setStaging(lines(content.staging_requirements));
    setVisual(lines(content.visual_requirements));
    setAudio(lines(content.audio_requirements));
  }, [content, detail.generationGoal, detail.revisionNumber, detail.title]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || !goal.trim()) return;
    onSave({
      expected_revision: detail.revisionNumber,
      title: title.trim(),
      generation_goal: goal.trim(),
      theme: theme.trim() || null,
      story: story.trim() || null,
      detailed_design: design.trim() || null,
      platform: platform.trim() || null,
      audience: audience.trim() || null,
      persona: persona.trim() || null,
      tone: tone.trim() || null,
      target_duration_seconds: duration ? Number(duration) : null,
      product_order: list(productOrder),
      must_include: list(mustInclude),
      must_avoid: list(mustAvoid),
      interaction_requirements: list(interactions),
      conversion_requirements: list(conversion),
      staging_requirements: list(staging),
      visual_requirements: list(visual),
      audio_requirements: list(audio),
    });
  };
  return (
    <section className="wb-section">
      <SectionHeader
        kicker={`INPUT REVISION · r${detail.revisionNumber}`}
        title="编辑内容输入"
        actions={
          <StatusBadge
            label={
              detail.status === "confirmed"
                ? "保存将创建草稿修订"
                : "草稿可编辑"
            }
            tone={detail.status === "confirmed" ? "warning" : "info"}
          />
        }
      />
      <form className="content-project-form wb-section-body" onSubmit={submit}>
        <div className="wb-form-grid">
          <label className="wb-field">
            <span>内容项目名称</span>
            <input
              className="wb-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>生成目标</span>
            <input
              className="wb-input"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>平台</span>
            <input
              className="wb-input"
              value={platform}
              onChange={(event) => setPlatform(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>目标时长（秒）</span>
            <input
              className="wb-input"
              type="number"
              min="30"
              value={duration}
              onChange={(event) => setDuration(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>受众</span>
            <input
              className="wb-input"
              value={audience}
              onChange={(event) => setAudience(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>主播人设</span>
            <input
              className="wb-input"
              value={persona}
              onChange={(event) => setPersona(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>语气</span>
            <input
              className="wb-input"
              value={tone}
              onChange={(event) => setTone(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>主题</span>
            <input
              className="wb-input"
              value={theme}
              onChange={(event) => setTheme(event.target.value)}
            />
          </label>
          <label className="wb-field wide">
            <span>故事</span>
            <textarea
              className="wb-textarea"
              value={story}
              onChange={(event) => setStory(event.target.value)}
            />
          </label>
          <label className="wb-field wide">
            <span>详细直播间设计</span>
            <textarea
              className="wb-textarea"
              value={design}
              onChange={(event) => setDesign(event.target.value)}
            />
          </label>
          <label className="wb-field">
            <span>商品讲解顺序</span>
            <textarea
              className="wb-textarea"
              value={productOrder}
              onChange={(event) => setProductOrder(event.target.value)}
              placeholder="每行一个商品编码或名称"
            />
          </label>
          <label className="wb-field">
            <span>必含项</span>
            <textarea
              className="wb-textarea"
              value={mustInclude}
              onChange={(event) => setMustInclude(event.target.value)}
              placeholder="每行一项"
            />
          </label>
          <label className="wb-field">
            <span>禁用项</span>
            <textarea
              className="wb-textarea"
              value={mustAvoid}
              onChange={(event) => setMustAvoid(event.target.value)}
              placeholder="每行一项"
            />
          </label>
          <label className="wb-field">
            <span>互动要求</span>
            <textarea
              className="wb-textarea"
              value={interactions}
              onChange={(event) => setInteractions(event.target.value)}
              placeholder="每行一项"
            />
          </label>
          <label className="wb-field">
            <span>促单要求</span>
            <textarea
              className="wb-textarea"
              value={conversion}
              onChange={(event) => setConversion(event.target.value)}
              placeholder="每行一项"
            />
          </label>
          <label className="wb-field">
            <span>舞台要求</span>
            <textarea
              className="wb-textarea"
              value={staging}
              onChange={(event) => setStaging(event.target.value)}
              placeholder="每行一项"
            />
          </label>
          <label className="wb-field">
            <span>视觉要求</span>
            <textarea
              className="wb-textarea"
              value={visual}
              onChange={(event) => setVisual(event.target.value)}
              placeholder="每行一项"
            />
          </label>
          <label className="wb-field">
            <span>音频要求</span>
            <textarea
              className="wb-textarea"
              value={audio}
              onChange={(event) => setAudio(event.target.value)}
              placeholder="每行一项"
            />
          </label>
        </div>
        <div className="wb-form-actions">
          <button
            className="wb-button wb-button-primary"
            disabled={saving || !title.trim() || !goal.trim()}
          >
            <FilePenLine size={15} aria-hidden="true" />
            {detail.status === "confirmed" ? "创建输入修订" : "保存输入修订"}
          </button>
        </div>
      </form>
    </section>
  );
}

function ProjectFactEditor({
  detail,
  onSave,
  saving,
}: {
  detail: ContentProjectDetail;
  onSave: (payload: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const facts = useQuery({
    queryKey: ["product-fact-cards"],
    queryFn: knowledgeApi.listProductFactCards,
  });
  const claims = useQuery({
    queryKey: ["knowledge-fact-claims"],
    queryFn: knowledgeApi.listFactClaims,
  });
  const approvedFacts = useMemo(
    () =>
      (facts.data ?? []).filter(
        (fact) =>
          fact.currentApprovedVersion &&
          fact.versions.some(
            (version) =>
              version.versionNumber === fact.currentApprovedVersion &&
              version.status === "approved",
          ),
      ),
    [facts.data],
  );
  const approvedCodes = useMemo(
    () => new Set(approvedFacts.map((fact) => fact.factCardCode)),
    [approvedFacts],
  );
  const pinnedCodes = useMemo(
    () => detail.factCards.map((fact) => fact.fact_card_code),
    [detail.factCards],
  );
  const approvedClaims = useMemo(
    () =>
      (claims.data ?? []).filter(
        (claim) =>
          claim.status === "approved" && claim.sourceStatus === "approved",
      ),
    [claims.data],
  );
  const pinnedClaimCodes = useMemo(
    () => detail.factClaims.map((claim) => claim.claim_code),
    [detail.factClaims],
  );
  const pinnedCodeKey = pinnedCodes.join("|");
  const approvedCodeKey = approvedFacts
    .map((fact) => fact.factCardCode)
    .join("|");
  const [factCodes, setFactCodes] = useState<string[]>([]);
  const [claimCodes, setClaimCodes] = useState<string[]>([]);
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    setFactCodes(pinnedCodes.filter((code) => approvedCodes.has(code)));
    setClaimCodes(
      pinnedClaimCodes.filter((code) =>
        approvedClaims.some((claim) => claim.claimCode === code),
      ),
    );
    setTouched(false);
  }, [
    approvedCodeKey,
    detail.projectCode,
    detail.revisionNumber,
    pinnedCodeKey,
    approvedClaims,
    pinnedClaimCodes,
  ]);
  const unavailablePins = detail.factCards.filter(
    (fact) => !approvedCodes.has(fact.fact_card_code),
  );
  const factConflicts = findFactCardConflicts(
    approvedFacts,
    factCodes,
    String(detail.content.platform ?? ""),
  );
  const toggleFact = (factCardCode: string) => {
    setTouched(true);
    setFactCodes((current) =>
      current.includes(factCardCode)
        ? current.filter((code) => code !== factCardCode)
        : [...current, factCardCode],
    );
  };
  const toggleClaim = (claimCode: string) => {
    setTouched(true);
    setClaimCodes((current) =>
      current.includes(claimCode)
        ? current.filter((code) => code !== claimCode)
        : [...current, claimCode],
    );
  };
  const submit = () =>
    onSave({
      expected_revision: detail.revisionNumber,
      fact_card_codes: factCodes,
      fact_claim_codes: claimCodes,
    });
  return (
    <section className="wb-section">
      <SectionHeader
        kicker="FACT CARD PINS"
        title="已批准事实卡"
        actions={
          <StatusBadge
            label={
              detail.status === "confirmed"
                ? "保存将创建草稿修订"
                : "草稿可编辑"
            }
            tone={detail.status === "confirmed" ? "warning" : "info"}
          />
        }
      />
      <div className="wb-section-body">
        {facts.isLoading ? (
          <LoadingBlock label="正在读取可选事实卡" />
        ) : facts.error ? (
          <InlineNotice tone="danger" title="事实卡列表读取失败">
            无法修改事实卡选择。
          </InlineNotice>
        ) : (
          <>
            <div className="content-template-options">
              {approvedFacts.map((fact) => (
                <label key={fact.factCardCode}>
                  <input
                    type="checkbox"
                    checked={factCodes.includes(fact.factCardCode)}
                    onChange={() => toggleFact(fact.factCardCode)}
                  />
                  {fact.title}{" "}
                  <code>
                    {fact.factCardCode} · v{fact.currentApprovedVersion}
                  </code>
                  <small>
                    {factScopeSummary(fact)} · {factSourceSummary(fact)}
                  </small>
                </label>
              ))}
            </div>
            {approvedFacts.length ? null : (
              <EmptyBlock icon={BookOpenText} title="暂无已批准事实卡" />
            )}
            {factConflicts.length ? (
              <InlineNotice tone="warning" title="事实卡选择冲突">
                {factConflicts.join("；")}
              </InlineNotice>
            ) : null}
            {unavailablePins.length ? (
              <InlineNotice
                tone="warning"
                title="当前修订包含不可重新选择的历史事实版本"
              >
                {unavailablePins
                  .map(
                    (fact) => `${fact.fact_card_code} v${fact.version_number}`,
                  )
                  .join("；")}
              </InlineNotice>
            ) : null}
            <div className="content-template-options">
              <strong>已批准事实声明</strong>
              {claims.isLoading ? (
                <small>正在读取事实声明。</small>
              ) : claims.error ? (
                <InlineNotice tone="warning" title="事实声明暂不可用">
                  无法修改声明选择。
                </InlineNotice>
              ) : approvedClaims.length ? (
                approvedClaims.map((claim) => (
                  <label key={claim.claimCode}>
                    <input
                      type="checkbox"
                      checked={claimCodes.includes(claim.claimCode)}
                      onChange={() => toggleClaim(claim.claimCode)}
                    />
                    {claim.factTitle}
                    <code>
                      {claim.claimCode} · {claim.sourceEvidenceCode}
                    </code>
                    <small>{claim.claim}</small>
                  </label>
                ))
              ) : (
                <small>暂无已批准事实声明。</small>
              )}
            </div>
            <div className="wb-form-actions">
              <button
                type="button"
                className="wb-button wb-button-primary"
                disabled={saving || !touched}
                onClick={submit}
              >
                <FilePenLine size={15} aria-hidden="true" />
                更新事实输入
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function ProjectTemplateEditor({
  detail,
  onSave,
  saving,
}: {
  detail: ContentProjectDetail;
  onSave: (payload: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const templates = useQuery({
    queryKey: ["live-research", "templates"],
    queryFn: liveResearchApi.listTemplates,
  });
  const usableTemplates = useMemo(
    () =>
      (templates.data ?? []).filter(
        (template) =>
          template.templateKind === "content_strategy" &&
          Boolean(template.published_revision) &&
          template.contentReadiness === "ready" &&
          template.buildability === "reference_only",
      ),
    [templates.data],
  );
  const initialPrimary =
    detail.templateContributionDecisions.find(
      (decision) => decision.selectionRole === "primary",
    )?.templateCode ?? String(detail.content.primary_template_code ?? "");
  const initialSecondary = detail.templateContributionDecisions
    .filter((decision) => decision.selectionRole === "secondary")
    .map((decision) => decision.templateCode);
  const initialDecisions = Object.fromEntries(
    detail.templateContributionDecisions.map((decision) => [
      decision.templateCode,
      decision.acceptedModules,
    ]),
  );
  const [primaryTemplate, setPrimaryTemplate] = useState("");
  const [secondaryTemplates, setSecondaryTemplates] = useState<string[]>([]);
  const [acceptedModules, setAcceptedModules] = useState<
    Record<string, string[]>
  >({});
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    setPrimaryTemplate(initialPrimary);
    setSecondaryTemplates(initialSecondary);
    setAcceptedModules(initialDecisions);
    setTouched(false);
  }, [detail.projectCode, detail.revisionNumber]);
  const selectedTemplateCodes = [primaryTemplate, ...secondaryTemplates].filter(
    Boolean,
  );
  const availableCodeSet = new Set(
    usableTemplates.map((template) => template.template_code),
  );
  const unavailableSelections = selectedTemplateCodes.filter(
    (code) => !availableCodeSet.has(code),
  );
  const moduleKeys = (templateCode: string) =>
    usableTemplates
      .find((template) => template.template_code === templateCode)
      ?.contentStrategy.programOutline.map((module) => module.moduleKey)
      .filter(Boolean) ??
    detail.templateContributionDecisions.find(
      (decision) => decision.templateCode === templateCode,
    )?.availableModules ??
    [];
  const conflictingModules = selectedTemplateCodes
    .flatMap((code) => acceptedModules[code] ?? [])
    .filter(
      (module, _index, values) =>
        values.filter((item) => item === module).length > 1,
    );
  const choosePrimary = (templateCode: string) => {
    setTouched(true);
    setPrimaryTemplate(templateCode);
    setSecondaryTemplates((current) =>
      current.filter((code) => code !== templateCode),
    );
    if (templateCode)
      setAcceptedModules((current) =>
        current[templateCode]
          ? current
          : { ...current, [templateCode]: moduleKeys(templateCode) },
      );
  };
  const toggleSecondary = (templateCode: string) => {
    setTouched(true);
    setSecondaryTemplates((current) =>
      current.includes(templateCode)
        ? current.filter((code) => code !== templateCode)
        : [...current, templateCode],
    );
    setAcceptedModules((current) =>
      current[templateCode] ? current : { ...current, [templateCode]: [] },
    );
  };
  const toggleModule = (templateCode: string, moduleKey: string) => {
    setTouched(true);
    setAcceptedModules((current) => ({
      ...current,
      [templateCode]: current[templateCode]?.includes(moduleKey)
        ? current[templateCode].filter((item) => item !== moduleKey)
        : [...(current[templateCode] ?? []), moduleKey],
    }));
  };
  const submit = () =>
    onSave({
      expected_revision: detail.revisionNumber,
      primary_template_code: primaryTemplate || null,
      secondary_template_codes: secondaryTemplates,
      template_contribution_decisions: selectedTemplateCodes.map(
        (templateCode) => ({
          template_code: templateCode,
          accepted_modules: acceptedModules[templateCode] ?? [],
        }),
      ),
    });
  return (
    <section className="wb-section">
      <SectionHeader
        kicker="TEMPLATE REFERENCES"
        title="内容策略参考模板"
        actions={
          <StatusBadge
            label={
              detail.status === "confirmed"
                ? "保存将创建草稿修订"
                : "草稿可编辑"
            }
            tone={detail.status === "confirmed" ? "warning" : "info"}
          />
        }
      />
      <div className="wb-section-body">
        {templates.isLoading ? (
          <LoadingBlock label="正在读取可用内容策略" />
        ) : templates.error ? (
          <InlineNotice tone="danger" title="内容策略列表读取失败">
            无法修改模板选择。
          </InlineNotice>
        ) : (
          <>
            <div className="content-template-options">
              <label>
                <input
                  type="radio"
                  name="edit-primary-template"
                  checked={!primaryTemplate}
                  onChange={() => choosePrimary("")}
                />
                不选主模板
              </label>
              {usableTemplates.map((template) => {
                const selected =
                  template.template_code === primaryTemplate ||
                  secondaryTemplates.includes(template.template_code);
                return (
                  <div
                    key={template.template_code}
                    className="content-template-choice"
                  >
                    <label>
                      <input
                        type="radio"
                        name="edit-primary-template"
                        checked={primaryTemplate === template.template_code}
                        onChange={() => choosePrimary(template.template_code)}
                      />
                      主模板：{template.title}{" "}
                      <code>
                        {template.template_code} · r
                        {template.published_revision}
                      </code>
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={secondaryTemplates.includes(
                          template.template_code,
                        )}
                        disabled={primaryTemplate === template.template_code}
                        onChange={() => toggleSecondary(template.template_code)}
                      />
                      作为次要补充
                    </label>
                    <small>
                      {template.contentStrategy.targetCategory || "未标注品类"}{" "}
                      ·{" "}
                      {template.contentStrategy.programOutline
                        .map((module) => module.title)
                        .join(" / ") || "未标注模块"}
                    </small>
                    {selected ? (
                      <div className="content-module-options">
                        {moduleKeys(template.template_code).map((moduleKey) => (
                          <label key={moduleKey}>
                            <input
                              type="checkbox"
                              checked={(
                                acceptedModules[template.template_code] ?? []
                              ).includes(moduleKey)}
                              onChange={() =>
                                toggleModule(template.template_code, moduleKey)
                              }
                            />
                            采纳模块：{moduleKey}
                          </label>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            {usableTemplates.length ? null : (
              <EmptyBlock icon={BookOpenText} title="暂无可选内容策略模板" />
            )}
            {unavailableSelections.length ? (
              <InlineNotice
                tone="warning"
                title="当前修订包含不可重新选择的历史模板"
              >
                {unavailableSelections.join("；")}
              </InlineNotice>
            ) : null}
            {conflictingModules.length ? (
              <InlineNotice tone="warning" title="模块贡献冲突">
                同一模块不能同时从多个模板采纳：
                {Array.from(new Set(conflictingModules)).join("、")}。
              </InlineNotice>
            ) : null}
            <div className="wb-form-actions">
              <button
                type="button"
                className="wb-button wb-button-primary"
                disabled={saving || !touched || conflictingModules.length > 0}
                onClick={submit}
              >
                <FilePenLine size={15} aria-hidden="true" />
                更新模板输入
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function objectLabel(objectType: string): string {
  return (
    (
      {
        content_project: "内容输入",
        design_brief: "设计说明",
        story_brief: "StoryBrief",
        script: "剧本",
        program: "节目段",
        shot_list: "ShotList",
      } as Record<string, string>
    )[objectType] ?? objectType
  );
}
function revisionTone(
  status: string,
): "success" | "warning" | "info" | "neutral" {
  return status === "confirmed"
    ? "success"
    : status === "draft"
      ? "warning"
      : "neutral";
}
function ContentChainRevisionHistory({
  detail,
}: {
  detail: ContentProjectDetail;
}) {
  const revisions = useQuery({
    queryKey: ["content-project", detail.projectCode, "chain-revisions"],
    queryFn: () => contentProjectsApi.listChainRevisions(detail.projectCode),
  });
  if (revisions.isLoading)
    return (
      <section className="wb-section">
        <SectionHeader kicker="REVISION LINEAGE" title="内容链修订" />
        <LoadingBlock label="正在读取内容链修订" />
      </section>
    );
  if (revisions.error)
    return (
      <section className="wb-section">
        <SectionHeader kicker="REVISION LINEAGE" title="内容链修订" />
        <InlineNotice tone="warning" title="内容链修订不可用">
          {errorMessage(revisions.error)}
        </InlineNotice>
      </section>
    );
  const history: ContentChainRevision[] = revisions.data ?? [];
  return (
    <section className="wb-section">
      <SectionHeader
        kicker="REVISION LINEAGE"
        title="内容链修订"
        actions={<StatusBadge label={`${history.length} 个修订`} tone="info" />}
      />
      {history.length ? (
        <ol className="content-flow-list">
          {history.map((revision) => (
            <li
              key={`${revision.objectType}:${revision.objectCode}:${revision.revisionNumber}`}
            >
              <span>{objectLabel(revision.objectType)}</span>
              <div>
                <strong>
                  {revision.objectCode} · r{revision.revisionNumber}
                </strong>
                <small>
                  {revision.sources.join(" / ") || "无上游来源"}
                  {revision.fingerprintSha256
                    ? ` · ${revision.fingerprintSha256.slice(0, 12)}`
                    : ""}
                </small>
              </div>
              <StatusBadge
                label={revision.status}
                tone={revisionTone(revision.status)}
              />
            </li>
          ))}
        </ol>
      ) : (
        <EmptyBlock icon={BookOpenText} title="尚无内容链修订" />
      )}
    </section>
  );
}

function ScriptRevisionEditor({
  detail,
  onSave,
  saving,
}: {
  detail: ContentProjectDetail;
  onSave: (
    blocks: Array<{
      module_type: string;
      content: string;
      estimated_duration_ms?: number;
      fact_citations: Array<Record<string, unknown>>;
      template_sources: Array<Record<string, unknown>>;
      interaction_intent?: Record<string, unknown>;
      cta_intent?: Record<string, unknown>;
    }>,
  ) => void;
  saving: boolean;
}) {
  const script = detail.script;
  const [blocks, setBlocks] = useState<ScriptBlockDraft[]>(() =>
    (script?.blocks ?? []).map(scriptBlockDraft),
  );
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    setBlocks((script?.blocks ?? []).map(scriptBlockDraft));
    setTouched(false);
  }, [script?.script_revision_code, script?.revision_number]);
  if (!script) return null;
  const updateBlock = (
    index: number,
    changes: Partial<(typeof blocks)[number]>,
  ) => {
    setTouched(true);
    setBlocks((current) =>
      current.map((block, blockIndex) =>
        blockIndex === index ? { ...block, ...changes } : block,
      ),
    );
  };
  const moveBlock = (index: number, offset: -1 | 1) => {
    const target = index + offset;
    if (target < 0 || target >= blocks.length) return;
    setTouched(true);
    setBlocks((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };
  const removeBlock = (index: number) => {
    setTouched(true);
    setBlocks((current) =>
      current.filter((_block, blockIndex) => blockIndex !== index),
    );
  };
  const submit = () =>
    onSave(
      blocks.map((block) => ({
        module_type: block.module_type,
        content: block.content,
        estimated_duration_ms: block.estimated_duration_ms,
        fact_citations: block.fact_citations,
        template_sources: block.template_sources,
        interaction_intent: block.interaction_intent,
        cta_intent: block.cta_intent,
      })),
    );
  return (
    <section className="wb-section">
      <SectionHeader
        kicker={`HUMAN SCRIPT REVISION · r${script.revision_number}`}
        title="人工修订剧本"
        actions={
          <StatusBadge label="保存将重建节目段与 ShotList" tone="warning" />
        }
      />
      <div className="wb-section-body">
        <div className="content-project-form">
          {blocks.map((block, index) => {
            const factLocked = block.fact_citations.length > 0;
            return (
              <div key={block.editorKey} className="wb-form-grid">
                <div className="wb-field wide">
                  <span>
                    剧本段 {index + 1}
                    {factLocked ? " · 固定事实引用" : ""}
                  </span>
                  <div className="wb-table-actions">
                    <label className="wb-field">
                      <span>模块类型</span>
                      <select
                        aria-label={`模块类型 ${index + 1}`}
                        className="wb-input"
                        value={block.module_type}
                        disabled={factLocked}
                        onChange={(event) =>
                          updateBlock(index, {
                            module_type: event.target.value,
                          })
                        }
                      >
                        <option value="opening">开场</option>
                        <option value="story">故事</option>
                        <option value="product_fact">产品事实</option>
                        <option value="conversion">转化互动</option>
                      </select>
                    </label>
                    <button
                      type="button"
                      className="wb-icon-button"
                      aria-label={`上移剧本段 ${index + 1}`}
                      title="上移剧本段"
                      disabled={index === 0}
                      onClick={() => moveBlock(index, -1)}
                    >
                      <ArrowUp size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="wb-icon-button"
                      aria-label={`下移剧本段 ${index + 1}`}
                      title="下移剧本段"
                      disabled={index === blocks.length - 1}
                      onClick={() => moveBlock(index, 1)}
                    >
                      <ArrowDown size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="wb-icon-button"
                      aria-label={`删除剧本段 ${index + 1}`}
                      title={
                        factLocked
                          ? "含固定事实引用的段落不可删除"
                          : "删除剧本段"
                      }
                      disabled={factLocked || blocks.length === 1}
                      onClick={() => removeBlock(index)}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <label className="wb-field wide">
                  <span>内容</span>
                  <textarea
                    className="wb-textarea"
                    value={block.content}
                    disabled={factLocked}
                    onChange={(event) =>
                      updateBlock(index, { content: event.target.value })
                    }
                  />
                </label>
                <label className="wb-field">
                  <span>预计时长（毫秒）</span>
                  <input
                    className="wb-input"
                    type="number"
                    min="0"
                    value={block.estimated_duration_ms ?? ""}
                    disabled={factLocked}
                    onChange={(event) =>
                      updateBlock(index, {
                        estimated_duration_ms: event.target.value
                          ? Number(event.target.value)
                          : undefined,
                      })
                    }
                  />
                </label>
                {factLocked ? (
                  <small>
                    {block.fact_citations
                      .map(
                        (citation) =>
                          citation.claim_code ??
                          `${citation.fact_card_code} v${citation.version_number}`,
                      )
                      .join("；")}
                  </small>
                ) : null}
              </div>
            );
          })}
        </div>
        <div className="wb-form-actions">
          <button
            type="button"
            className="wb-button"
            onClick={() => {
              setTouched(true);
              setBlocks((current) => [...current, newScriptBlockDraft()]);
            }}
          >
            <Plus size={15} aria-hidden="true" />
            添加无事实段
          </button>
          <button
            type="button"
            className="wb-button wb-button-primary"
            disabled={
              saving ||
              !touched ||
              !blocks.length ||
              blocks.some((block) => !block.content.trim())
            }
            onClick={submit}
          >
            <FilePenLine size={15} aria-hidden="true" />
            保存人工脚本修订
          </button>
        </div>
      </div>
    </section>
  );
}

function durationLabel(milliseconds: number): string {
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function ProgramShotTimelinePreview({ segments, shots }: { segments: ProgramSegmentDraft[]; shots: ShotDraft[] }) {
  const segmentTimeline = segments.map((segment, index) => {
    const segmentShots = shots.filter((shot) => shot.programSegmentIndex === index);
    const shotDuration = segmentShots.reduce((total, shot) => total + Math.max(0, shot.estimated_duration_ms ?? 0), 0);
    const segmentDuration = Math.max(0, segment.estimated_duration_ms ?? 0);
    const duration = segmentDuration || shotDuration;
    return { segment, index, segmentShots, shotDuration, segmentDuration, duration };
  });
  const total = segmentTimeline.reduce((sum, item) => sum + item.duration, 0);
  const missingShotDurations = shots.filter((shot) => !shot.estimated_duration_ms || shot.estimated_duration_ms <= 0);
  const inconsistentSegments = segmentTimeline.filter((item) => item.segmentDuration && item.shotDuration && item.segmentDuration !== item.shotDuration);
  let cursor = 0;
  return <div className="content-program-timeline" aria-label="节目段与镜头时间线预览"><div className="content-program-timeline-heading"><div><h3>编排时间线</h3><small>{durationLabel(total)} · {segments.length} 段 · {shots.length} 镜头</small></div><StatusBadge label={missingShotDurations.length || inconsistentSegments.length ? "待校准" : "时长一致"} tone={missingShotDurations.length || inconsistentSegments.length ? "warning" : "success"} /></div><div className="content-program-timeline-segments">{segmentTimeline.map((item) => { const start = cursor; cursor += item.duration; return <article key={item.segment.editorKey} style={{ flexGrow: Math.max(1, item.duration) }}><strong>段 {item.index + 1}</strong><span>{item.segment.program_phase}</span><small>{durationLabel(start)} - {durationLabel(cursor)}</small><em>{item.duration ? durationLabel(item.duration) : "未设时长"}</em></article>; })}</div><div className="content-program-timeline-shots">{segmentTimeline.map((item) => <div key={item.segment.editorKey}><header><strong>段 {item.index + 1}</strong><small>{item.segment.semantic_goal || "未填写目标"}</small><span>{item.segmentShots.length} 镜头 · {durationLabel(item.shotDuration)}</span></header><div>{item.segmentShots.map((shot, shotIndex) => <article key={shot.editorKey} style={{ flexGrow: Math.max(1, shot.estimated_duration_ms ?? 0) }}><strong>镜头 {shotIndex + 1}</strong><small>{shot.estimated_duration_ms ? durationLabel(shot.estimated_duration_ms) : "未设时长"}</small></article>)}</div></div>)}</div>{missingShotDurations.length || inconsistentSegments.length ? <div className="content-program-timeline-warnings">{missingShotDurations.length ? <small>{missingShotDurations.length} 个镜头未设置预计时长</small> : null}{inconsistentSegments.length ? <small>{inconsistentSegments.map((item) => `段 ${item.index + 1}`).join("、")} 的段落时长与镜头合计不一致</small> : null}</div> : null}</div>;
}

function ProgramShotRevisionEditor({
  detail,
  onSave,
  saving,
}: {
  detail: ContentProjectDetail;
  onSave: (payload: ProgramShotPayload) => void;
  saving: boolean;
}) {
  const program = detail.program;
  const shotList = detail.shotList;
  const script = detail.script;
  const [segments, setSegments] = useState<ProgramSegmentDraft[]>(() =>
    (program?.segments ?? []).map(programSegmentDraft),
  );
  const [shots, setShots] = useState<ShotDraft[]>(() => {
    const indexByCode = new Map(
      (program?.segments ?? []).map((segment, index) => [
        segment.segment_code,
        index,
      ]),
    );
    return (shotList?.shots ?? []).map((shot) =>
      shotDraft(shot, indexByCode.get(shot.program_segment_code) ?? 0),
    );
  });
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    const indexByCode = new Map(
      (program?.segments ?? []).map((segment, index) => [
        segment.segment_code,
        index,
      ]),
    );
    setSegments((program?.segments ?? []).map(programSegmentDraft));
    setShots(
      (shotList?.shots ?? []).map((shot) =>
        shotDraft(shot, indexByCode.get(shot.program_segment_code) ?? 0),
      ),
    );
    setTouched(false);
  }, [
    program?.program_revision_code,
    program?.revision_number,
    shotList?.shot_list_revision_code,
    shotList?.revision_number,
  ]);
  if (!program || !shotList || !script) return null;
  const updateSegment = (
    index: number,
    changes: Partial<ProgramSegmentDraft>,
  ) => {
    setTouched(true);
    setSegments((current) =>
      current.map((segment, segmentIndex) =>
        segmentIndex === index ? { ...segment, ...changes } : segment,
      ),
    );
  };
  const moveSegment = (index: number, offset: -1 | 1) => {
    const target = index + offset;
    if (target < 0 || target >= segments.length) return;
    setTouched(true);
    setSegments((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setShots((current) =>
      current.map((shot) => {
        if (shot.programSegmentIndex === index) {
          return { ...shot, programSegmentIndex: target };
        }
        if (shot.programSegmentIndex === target) {
          return { ...shot, programSegmentIndex: index };
        }
        return shot;
      }),
    );
  };
  const addSegment = () => {
    const segment = newProgramSegmentDraft(
      script.blocks.map((block) => block.block_code),
    );
    const newIndex = segments.length;
    setTouched(true);
    setSegments((current) => [...current, segment]);
    setShots((current) => [
      ...current,
      newShotDraft(newIndex, segment.script_block_codes),
    ]);
  };
  const removeSegment = (index: number) => {
    if (segments.length === 1) return;
    setTouched(true);
    setSegments((current) =>
      current.filter((_segment, segmentIndex) => segmentIndex !== index),
    );
    setShots((current) =>
      current
        .filter((shot) => shot.programSegmentIndex !== index)
        .map((shot) =>
          shot.programSegmentIndex > index
            ? { ...shot, programSegmentIndex: shot.programSegmentIndex - 1 }
            : shot,
        ),
    );
  };
  const toggleSegmentBlock = (segmentIndex: number, blockCode: string) => {
    setTouched(true);
    setSegments((current) =>
      current.map((segment, index) =>
        index !== segmentIndex
          ? segment
          : {
              ...segment,
              script_block_codes: segment.script_block_codes.includes(blockCode)
                ? segment.script_block_codes.filter(
                    (code) => code !== blockCode,
                  )
                : [...segment.script_block_codes, blockCode],
            },
      ),
    );
    setShots((current) =>
      current.map((shot) =>
        shot.programSegmentIndex !== segmentIndex
          ? shot
          : {
              ...shot,
              script_block_codes: shot.script_block_codes.filter(
                (code) => code !== blockCode,
              ),
            },
      ),
    );
  };
  const updateShot = (index: number, changes: Partial<ShotDraft>) => {
    setTouched(true);
    setShots((current) =>
      current.map((shot, shotIndex) =>
        shotIndex === index ? { ...shot, ...changes } : shot,
      ),
    );
  };
  const moveShot = (index: number, offset: -1 | 1) => {
    const target = index + offset;
    if (target < 0 || target >= shots.length) return;
    setTouched(true);
    setShots((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };
  const changeShotSegment = (index: number, programSegmentIndex: number) => {
    const allowed = new Set(
      segments[programSegmentIndex]?.script_block_codes ?? [],
    );
    updateShot(index, {
      programSegmentIndex,
      script_block_codes: shots[index].script_block_codes.filter((code) =>
        allowed.has(code),
      ),
    });
  };
  const toggleShotBlock = (shotIndex: number, blockCode: string) => {
    setTouched(true);
    setShots((current) =>
      current.map((shot, index) =>
        index !== shotIndex
          ? shot
          : {
              ...shot,
              script_block_codes: shot.script_block_codes.includes(blockCode)
                ? shot.script_block_codes.filter((code) => code !== blockCode)
                : [...shot.script_block_codes, blockCode],
            },
      ),
    );
  };
  const invalid =
    segments.some(
      (segment) =>
        !segment.semantic_goal.trim() || !segment.script_block_codes.length,
    ) ||
    shots.some(
      (shot) =>
        !shot.shot_goal.trim() ||
        !segments[shot.programSegmentIndex] ||
        !shot.script_block_codes.length ||
        shot.script_block_codes.some(
          (code) =>
            !segments[shot.programSegmentIndex].script_block_codes.includes(
              code,
            ),
        ),
    ) ||
    segments.some(
      (_segment, index) =>
        !shots.some((shot) => shot.programSegmentIndex === index),
    );
  const submit = () =>
    onSave({
      segments: segments.map(
        ({ editorKey: _editorKey, segment_code: _segmentCode, ...segment }) =>
          segment,
      ),
      shots: shots.map(
        ({
          editorKey: _editorKey,
          shot_code: _shotCode,
          program_segment_code: _segmentCode,
          programSegmentIndex,
          ...shot
        }) => ({ ...shot, program_segment_index: programSegmentIndex }),
      ),
    });
  return (
    <section className="wb-section">
      <SectionHeader
        kicker={`HUMAN PROGRAM / SHOT REVISION · r${program.revision_number}`}
        title="人工编排节目段与镜头"
        actions={
          <StatusBadge
            label="保存将创建 Program 与 ShotList 修订"
            tone="warning"
          />
        }
      />
      <div className="wb-section-body">
        <div className="content-project-form">
          <ProgramShotTimelinePreview segments={segments} shots={shots} />
          <div className="content-program-editor">
            <h3>节目段</h3>
            {segments.map((segment, index) => (
              <div key={segment.editorKey} className="wb-form-grid">
                <label className="wb-field wide">
                  <span>节目段 {index + 1} 目标</span>
                  <input
                    className="wb-input"
                    value={segment.semantic_goal}
                    onChange={(event) =>
                      updateSegment(index, {
                        semantic_goal: event.target.value,
                      })
                    }
                  />
                </label>
                <div className="wb-form-actions">
                  <button
                    type="button"
                    className="wb-icon-button"
                    aria-label={`上移节目段 ${index + 1}`}
                    title="上移节目段"
                    disabled={index === 0}
                    onClick={() => moveSegment(index, -1)}
                  >
                    <ArrowUp size={15} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="wb-icon-button"
                    aria-label={`下移节目段 ${index + 1}`}
                    title="下移节目段"
                    disabled={index === segments.length - 1}
                    onClick={() => moveSegment(index, 1)}
                  >
                    <ArrowDown size={15} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="wb-icon-button"
                    aria-label={`删除节目段 ${index + 1}`}
                    title={
                      segments.length === 1
                        ? "至少保留一个节目段"
                        : "删除节目段及其镜头"
                    }
                    disabled={segments.length === 1}
                    onClick={() => removeSegment(index)}
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                </div>
                <label className="wb-field">
                  <span>阶段</span>
                  <select
                    className="wb-input"
                    value={segment.program_phase}
                    onChange={(event) =>
                      updateSegment(index, {
                        program_phase: event.target.value,
                      })
                    }
                  >
                    <option value="opening">开场</option>
                    <option value="body">主体</option>
                    <option value="conversion">转化互动</option>
                    <option value="closing">收尾</option>
                  </select>
                </label>
                <label className="wb-field">
                  <span>预计时长（毫秒）</span>
                  <input
                    className="wb-input"
                    type="number"
                    min="0"
                    value={segment.estimated_duration_ms ?? ""}
                    onChange={(event) =>
                      updateSegment(index, {
                        estimated_duration_ms: event.target.value
                          ? Number(event.target.value)
                          : undefined,
                      })
                    }
                  />
                </label>
                <label className="wb-field">
                  <span>进入条件</span>
                  <input
                    className="wb-input"
                    value={segment.entry_condition ?? ""}
                    onChange={(event) =>
                      updateSegment(index, {
                        entry_condition: event.target.value || undefined,
                      })
                    }
                  />
                </label>
                <label className="wb-field">
                  <span>退出条件</span>
                  <input
                    className="wb-input"
                    value={segment.exit_condition ?? ""}
                    onChange={(event) =>
                      updateSegment(index, {
                        exit_condition: event.target.value || undefined,
                      })
                    }
                  />
                </label>
                <label className="wb-field wide">
                  <span>关联商品</span>
                  <input
                    className="wb-input"
                    value={segment.product_refs.join(", ")}
                    onChange={(event) =>
                      updateSegment(index, {
                        product_refs: list(event.target.value),
                      })
                    }
                  />
                </label>
                <label className="wb-field">
                  <span>互动动作</span>
                  <textarea
                    className="wb-textarea"
                    value={actionLines(segment.interaction_actions)}
                    onChange={(event) =>
                      updateSegment(index, {
                        interaction_actions: actions(event.target.value),
                      })
                    }
                    placeholder="动作 | 补充说明，每行一项"
                  />
                </label>
                <label className="wb-field">
                  <span>CTA 动作</span>
                  <textarea
                    className="wb-textarea"
                    value={actionLines(segment.cta_actions)}
                    onChange={(event) =>
                      updateSegment(index, {
                        cta_actions: actions(event.target.value),
                      })
                    }
                    placeholder="动作 | 补充说明，每行一项"
                  />
                </label>
                <BranchApplicabilityField
                  value={segment.branch_applicability}
                  onChange={(branch_applicability) =>
                    updateSegment(index, { branch_applicability })
                  }
                />
                <div className="wb-field wide">
                  <span>采纳剧本段</span>
                  <div className="content-template-options">
                    {script.blocks.map((block) => (
                      <label key={block.block_code}>
                        <input
                          type="checkbox"
                          checked={segment.script_block_codes.includes(
                            block.block_code,
                          )}
                          onChange={() =>
                            toggleSegmentBlock(index, block.block_code)
                          }
                        />
                        {block.module_type} · {block.content}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="content-program-editor">
            <h3>镜头</h3>
            {shots.map((shot, index) => {
              const selectedSegment = segments[shot.programSegmentIndex];
              const segmentShotCount = shots.filter(
                (item) => item.programSegmentIndex === shot.programSegmentIndex,
              ).length;
              return (
                <div key={shot.editorKey} className="wb-form-grid">
                  <label className="wb-field">
                    <span>所属节目段</span>
                    <select
                      className="wb-input"
                      value={shot.programSegmentIndex}
                      onChange={(event) =>
                        changeShotSegment(index, Number(event.target.value))
                      }
                    >
                      {segments.map((segment, segmentIndex) => (
                        <option key={segment.editorKey} value={segmentIndex}>
                          段 {segmentIndex + 1} · {segment.semantic_goal}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wb-field wide">
                    <span>镜头目标</span>
                    <input
                      className="wb-input"
                      value={shot.shot_goal}
                      onChange={(event) =>
                        updateShot(index, { shot_goal: event.target.value })
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>素材角色</span>
                    <input
                      className="wb-input"
                      value={shot.material_role_requirements.join(", ")}
                      onChange={(event) =>
                        updateShot(index, {
                          material_role_requirements: list(event.target.value),
                        })
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>预计时长（毫秒）</span>
                    <input
                      className="wb-input"
                      type="number"
                      min="0"
                      value={shot.estimated_duration_ms ?? ""}
                      onChange={(event) =>
                        updateShot(index, {
                          estimated_duration_ms: event.target.value
                            ? Number(event.target.value)
                            : undefined,
                        })
                      }
                    />
                  </label>
                  <label className="wb-field wide">
                    <span>必须包含</span>
                    <input
                      className="wb-input"
                      value={shot.must_include.join(", ")}
                      onChange={(event) =>
                        updateShot(index, {
                          must_include: list(event.target.value),
                        })
                      }
                    />
                  </label>
                  <label className="wb-field wide">
                    <span>必须避免</span>
                    <input
                      className="wb-input"
                      value={shot.must_avoid.join(", ")}
                      onChange={(event) =>
                        updateShot(index, {
                          must_avoid: list(event.target.value),
                        })
                      }
                    />
                  </label>
                  <label className="wb-field">
                    <span>构图风格</span>
                    <input
                      className="wb-input"
                      value={recordText(shot.composition_intent, "style")}
                      onChange={(event) =>
                        updateShot(index, {
                          composition_intent: {
                            ...shot.composition_intent,
                            style: event.target.value,
                          },
                        })
                      }
                      placeholder="例如 product_close_up"
                    />
                  </label>
                  <label className="wb-field">
                    <span>画面焦点</span>
                    <input
                      className="wb-input"
                      value={recordText(shot.composition_intent, "focus")}
                      onChange={(event) =>
                        updateShot(index, {
                          composition_intent: {
                            ...shot.composition_intent,
                            focus: event.target.value,
                          },
                        })
                      }
                      placeholder="例如 product"
                    />
                  </label>
                  <label className="wb-field">
                    <span>音频动作</span>
                    <textarea
                      className="wb-textarea"
                      value={actionLines(shot.audio_actions)}
                      onChange={(event) =>
                        updateShot(index, {
                          audio_actions: actions(event.target.value),
                        })
                      }
                      placeholder="动作 | 补充说明，每行一项"
                    />
                  </label>
                  <label className="wb-field">
                    <span>验收条件</span>
                    <textarea
                      className="wb-textarea"
                      value={shot.acceptance_criteria.join("\n")}
                      onChange={(event) =>
                        updateShot(index, {
                          acceptance_criteria: list(event.target.value),
                        })
                      }
                      placeholder="每行一项"
                    />
                  </label>
                  <div className="content-continuity-field">
                    <label>
                      <input
                        type="checkbox"
                        checked={shot.continuity.from_previous === true}
                        onChange={(event) =>
                          updateShot(index, {
                            continuity: {
                              ...shot.continuity,
                              from_previous: event.target.checked,
                            },
                          })
                        }
                      />
                      与前一镜头连续
                    </label>
                    <label className="wb-field">
                      <span>转场提示</span>
                      <input
                        className="wb-input"
                        value={recordText(shot.continuity, "transition_cue")}
                        onChange={(event) =>
                          updateShot(index, {
                            continuity: {
                              ...shot.continuity,
                              transition_cue: event.target.value,
                            },
                          })
                        }
                        placeholder="例如保持商品位置"
                      />
                    </label>
                  </div>
                  <BranchApplicabilityField
                    value={shot.branch_applicability}
                    onChange={(branch_applicability) =>
                      updateShot(index, { branch_applicability })
                    }
                  />
                  <div className="wb-field wide">
                    <span>镜头来源剧本段</span>
                    <div className="content-template-options">
                      {(selectedSegment?.script_block_codes ?? []).map(
                        (blockCode) => {
                          const block = script.blocks.find(
                            (item) => item.block_code === blockCode,
                          );
                          return (
                            <label key={blockCode}>
                              <input
                                type="checkbox"
                                checked={shot.script_block_codes.includes(
                                  blockCode,
                                )}
                                onChange={() =>
                                  toggleShotBlock(index, blockCode)
                                }
                              />
                              {block?.module_type ?? "未知段"} ·{" "}
                              {block?.content ?? blockCode}
                            </label>
                          );
                        },
                      )}
                    </div>
                  </div>
                  <div className="wb-form-actions">
                    <button
                      type="button"
                      className="wb-icon-button"
                      aria-label={`上移镜头 ${index + 1}`}
                      title="上移镜头"
                      disabled={index === 0}
                      onClick={() => moveShot(index, -1)}
                    >
                      <ArrowUp size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="wb-icon-button"
                      aria-label={`下移镜头 ${index + 1}`}
                      title="下移镜头"
                      disabled={index === shots.length - 1}
                      onClick={() => moveShot(index, 1)}
                    >
                      <ArrowDown size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="wb-icon-button"
                      aria-label={`删除镜头 ${index + 1}`}
                      title={
                        segmentShotCount === 1
                          ? "每个节目段至少保留一个镜头"
                          : "删除镜头"
                      }
                      disabled={segmentShotCount === 1}
                      onClick={() => {
                        setTouched(true);
                        setShots((current) =>
                          current.filter(
                            (_shot, shotIndex) => shotIndex !== index,
                          ),
                        );
                      }}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="wb-form-actions">
            <button
              type="button"
              className="wb-button"
              disabled={!script.blocks.length}
              onClick={addSegment}
            >
              <Plus size={15} aria-hidden="true" />
              添加节目段
            </button>
            <button
              type="button"
              className="wb-button"
              disabled={!segments.length}
              onClick={() => {
                setTouched(true);
                setShots((current) => [
                  ...current,
                  newShotDraft(0, segments[0].script_block_codes),
                ]);
              }}
            >
              <Plus size={15} aria-hidden="true" />
              添加镜头
            </button>
            <button
              type="button"
              className="wb-button wb-button-primary"
              disabled={saving || !touched || invalid}
              onClick={submit}
            >
              <FilePenLine size={15} aria-hidden="true" />
              保存节目段与镜头修订
            </button>
          </div>
          {invalid ? (
            <InlineNotice tone="warning" title="编排待修正">
              每个节目段必须采纳至少一个剧本段并保留至少一个镜头；每个镜头必须引用其节目段已采纳的剧本段。
            </InlineNotice>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function Chain({
  detail,
  onSaveInputs,
  savingInputs,
  onParseBrief,
  onReviseBrief,
  onReviseScript,
  onReviseProgramShots,
  onConfirmBrief,
  parsingBrief,
  revisingBrief,
  revisingScript,
  revisingProgramShots,
  confirmingBrief,
}: {
  detail: ContentProjectDetail;
  onSaveInputs: (payload: Record<string, unknown>) => void;
  savingInputs: boolean;
  onParseBrief: (rawInput: string) => void;
  onReviseBrief: (overrides: Record<string, unknown>) => void;
  onReviseScript: (
    blocks: Array<{
      module_type: string;
      content: string;
      estimated_duration_ms?: number;
      fact_citations: Array<Record<string, unknown>>;
      template_sources: Array<Record<string, unknown>>;
      interaction_intent?: Record<string, unknown>;
      cta_intent?: Record<string, unknown>;
    }>,
  ) => void;
  onReviseProgramShots: (payload: ProgramShotPayload) => void;
  onConfirmBrief: () => void;
  parsingBrief: boolean;
  revisingBrief: boolean;
  revisingScript: boolean;
  revisingProgramShots: boolean;
  confirmingBrief: boolean;
}) {
  return (
    <div className="content-chain">
      <ProjectInputEditor
        detail={detail}
        onSave={onSaveInputs}
        saving={savingInputs}
      />
      <ProjectFactEditor
        detail={detail}
        onSave={onSaveInputs}
        saving={savingInputs}
      />
      <ProjectTemplateEditor
        detail={detail}
        onSave={onSaveInputs}
        saving={savingInputs}
      />
      <section className="wb-section">
        <SectionHeader
          kicker="DESIGN BRIEF"
          title="目标与事实"
          actions={
            <StatusBadge
              label={
                detail.status === "confirmed" ? "输入已确认" : "草稿待确认"
              }
              tone={detail.status === "confirmed" ? "success" : "warning"}
            />
          }
        />
        <div className="content-brief">
          <strong>{detail.generationGoal}</strong>
          <span>{String(detail.content.theme ?? "未填写主题")}</span>
          <small>
            {String(
              detail.content.story ??
                detail.content.detailed_design ??
                "未填写故事或详细设计",
            )}
          </small>
        </div>
        <div className="content-key-value">
          <div>
            <span>平台</span>
            <strong>{String(detail.content.platform ?? "未指定")}</strong>
          </div>
          <div>
            <span>受众 / 人设</span>
            <strong>
              {String(detail.content.audience ?? "未指定")} /{" "}
              {String(detail.content.persona ?? "未指定")}
            </strong>
          </div>
          <div>
            <span>时长</span>
            <strong>
              {detail.content.target_duration_seconds
                ? `${String(detail.content.target_duration_seconds)} 秒`
                : "未指定"}
            </strong>
          </div>
          <div>
            <span>事实版本</span>
            <strong>
              {[
                ...detail.factCards.map(
                  (fact) => `${fact.fact_card_code} v${fact.version_number}`,
                ),
                ...detail.factClaims.map((claim) => claim.claim_code),
              ].join("；") || "未选择"}
            </strong>
          </div>
        </div>
      </section>
      <DesignBriefPanel
        detail={detail}
        onParse={onParseBrief}
        onRevise={onReviseBrief}
        onConfirm={onConfirmBrief}
        parsing={parsingBrief}
        revising={revisingBrief}
        confirming={confirmingBrief}
      />
      {detail.templateContributionDecisions.length ? (
        <section className="wb-section">
          <SectionHeader kicker="TEMPLATE CONTRIBUTIONS" title="模板模块贡献" />
          <div className="content-template-contributions">
            {detail.templateContributionDecisions.map((decision) => (
              <article key={decision.templateCode}>
                <header>
                  <code>
                    {decision.templateCode} · r{decision.revision}
                  </code>
                  <StatusBadge
                    label={
                      decision.selectionRole === "primary"
                        ? "主模板"
                        : "次要补充"
                    }
                    tone={
                      decision.selectionRole === "primary" ? "success" : "info"
                    }
                  />
                </header>
                <div>
                  <span>采纳</span>
                  <strong>
                    {decision.acceptedModules.join(" / ") || "未采纳模块"}
                  </strong>
                </div>
                <div>
                  <span>未采纳</span>
                  <strong>
                    {decision.rejectedModules.join(" / ") || "无"}
                  </strong>
                </div>
                <div>
                  <span>素材提示</span>
                  <strong>{decision.materialCues.join(" / ") || "无"}</strong>
                </div>
                <div>
                  <span>节目策略</span>
                  <strong>{policySummary(decision.contentStrategyPolicy)}</strong>
                </div>
                <div>
                  <span>固定阶段</span>
                  <strong>{decision.programOutline.filter((stage) => decision.acceptedModules.includes(stage.moduleKey)).map((stage) => `${stage.title} (${stage.moduleKey})`).join(" / ") || "无"}</strong>
                </div>
                <div>
                  <span>清洗例证</span>
                  <strong>{decision.reviewedExamples.filter((example) => decision.acceptedModules.includes(example.moduleKey)).map((example) => example.exampleText).join(" / ") || "无"}</strong>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
      {detail.storyBrief ? (
        <section className="wb-section">
          <SectionHeader
            kicker={`${detail.storyBrief.story_brief_code} · r${detail.storyBrief.revision_number}`}
            title="StoryBrief"
          />
          <div className="content-key-value">
            {Object.entries(detail.storyBrief.content)
              .filter(([key]) =>
                ["theme", "story", "audience", "tone"].includes(key),
              )
              .map(([key, value]) => (
                <div key={key}>
                  <span>{key}</span>
                  <strong>
                    {Array.isArray(value) ? value.join("、") : String(value)}
                  </strong>
                </div>
              ))}
          </div>
        </section>
      ) : null}
      {detail.script ? (
        <>
          <section className="wb-section">
            <SectionHeader
              kicker={`${detail.script.script_revision_code} · r${detail.script.revision_number}`}
              title="剧本"
            />
            <ol className="content-flow-list">
              {detail.script.blocks.map((block) => (
                <li key={block.block_code}>
                  <span>{block.module_type}</span>
                  <div>
                    <strong>{block.content}</strong>
                    <small>
                      {block.block_code}
                      {block.fact_citations.length
                        ? ` · 事实：${block.fact_citations.map((citation) => citation.claim_code ?? `${citation.fact_card_code} v${citation.version_number}`).join("、")}`
                        : ""}
                    {block.template_sources.length
                      ? ` · 模板：${block.template_sources.map((source) => `${source.template_code} r${source.revision}`).join("、")}`
                      : ""}
                    {block.contentRuleRefs.length
                      ? ` · 规则：${block.contentRuleRefs.map((rule) => `${rule.ruleCode} ${rule.directive}`).join("、")}`
                      : ""}
                      {block.template_sources.flatMap((source) => source.moduleGuidance).length
                        ? ` · 配方：${block.template_sources.flatMap((source) => source.moduleGuidance).join("；")}`
                        : ""}
                      {block.template_sources.flatMap((source) => source.strategyStage ? [`${source.strategyStage.title} (${source.strategyStage.sourceSessionCode} ${source.strategyStage.startMs}-${source.strategyStage.endMs}ms)`] : []).length
                        ? ` · 阶段：${block.template_sources.flatMap((source) => source.strategyStage ? [`${source.strategyStage.title} (${source.strategyStage.sourceSessionCode} ${source.strategyStage.startMs}-${source.strategyStage.endMs}ms)`] : []).join("；")}`
                        : ""}
                      {block.template_sources.flatMap((source) => source.referenceExamples.map((example) => `${example.exampleText} (${example.sourceSessionCode} ${example.startMs}-${example.endMs}ms)`)).length
                        ? ` · 例证：${block.template_sources.flatMap((source) => source.referenceExamples.map((example) => `${example.exampleText} (${example.sourceSessionCode} ${example.startMs}-${example.endMs}ms)`)).join("；")}`
                        : ""}
                      {actionPolicySummary(block.interaction_intent)
                        ? ` · 互动：${actionPolicySummary(block.interaction_intent)}`
                        : ""}
                      {actionPolicySummary(block.cta_intent)
                        ? ` · 转化：${actionPolicySummary(block.cta_intent)}`
                        : ""}
                    </small>
                    {templateEvidenceLinks(block.template_sources).length ? (
                      <span className="content-template-evidence-links">
                        {templateEvidenceLinks(block.template_sources).map((evidence) => (
                          <a
                            key={evidence.key}
                            href={templateEvidenceHref(
                              evidence.sourceSessionCode,
                              evidence.startMs,
                              evidence.endMs,
                            )}
                          >
                            {evidence.label}
                          </a>
                        ))}
                      </span>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
          <ScriptRevisionEditor
            detail={detail}
            onSave={onReviseScript}
            saving={revisingScript}
          />
        </>
      ) : null}
      {detail.program ? (
        <section className="wb-section">
          <SectionHeader
            kicker={`${detail.program.program_revision_code} · r${detail.program.revision_number}`}
            title="节目段"
          />
          <ol className="content-flow-list">
            {detail.program.segments.map((segment) => (
              <li key={segment.segment_code}>
                <span>{segment.program_phase}</span>
                <div>
                  <strong>{segment.semantic_goal}</strong>
                  <small>{segment.segment_code}</small>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {detail.shotList ? (
        <section className="wb-section">
          <SectionHeader
            kicker={`${detail.shotList.shot_list_revision_code} · r${detail.shotList.revision_number}`}
            title="ShotList"
          />
          <ol className="content-flow-list">
            {detail.shotList.shots.map((shot) => (
              <li key={shot.shot_code}>
                <span>SHOT</span>
                <div>
                  <strong>{shot.shot_goal}</strong>
                  <small>
                    {shot.material_role_requirements.join(" / ")} ·{" "}
                    {shot.shot_code}
                  </small>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <ProgramShotRevisionEditor
        detail={detail}
        onSave={onReviseProgramShots}
        saving={revisingProgramShots}
      />
      <ContentChainRevisionHistory detail={detail} />
    </div>
  );
}

export function ContentProjectsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedCode, setSelectedCode] = useState("");
  const projects = useQuery({
    queryKey: ["content-projects"],
    queryFn: contentProjectsApi.list,
  });
  const activeCode = projects.data?.some(
    (item) => item.projectCode === selectedCode,
  )
    ? selectedCode
    : (projects.data?.[0]?.projectCode ?? "");
  useEffect(() => {
    if (selectedCode !== activeCode) setSelectedCode(activeCode);
  }, [activeCode, selectedCode]);
  const detail = useQuery({
    queryKey: ["content-project", activeCode],
    queryFn: () => contentProjectsApi.get(activeCode),
    enabled: Boolean(activeCode),
  });
  const refreshDetail = (result: ContentProjectDetail) => {
    queryClient.setQueryData(["content-project", activeCode], result);
    void queryClient.invalidateQueries({ queryKey: ["content-projects"] });
    void queryClient.invalidateQueries({
      queryKey: ["content-project", activeCode, "chain-revisions"],
    });
  };
  const update = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      contentProjectsApi.update(activeCode, payload),
    onSuccess: refreshDetail,
  });
  const confirm = useMutation({
    mutationFn: () =>
      contentProjectsApi.confirm(activeCode, detail.data?.revisionNumber ?? 0),
    onSuccess: refreshDetail,
  });
  const parseBrief = useMutation({
    mutationFn: (rawInput: string) =>
      contentProjectsApi.parseBrief(
        activeCode,
        detail.data?.revisionNumber ?? 0,
        rawInput,
      ),
    onSuccess: refreshDetail,
  });
  const reviseBrief = useMutation({
    mutationFn: (overrides: Record<string, unknown>) =>
      contentProjectsApi.reviseBrief(
        activeCode,
        detail.data?.revisionNumber ?? 0,
        overrides,
      ),
    onSuccess: refreshDetail,
  });
  const reviseScript = useMutation({
    mutationFn: (
      blocks: Parameters<typeof contentProjectsApi.reviseScript>[2],
    ) =>
      contentProjectsApi.reviseScript(
        activeCode,
        detail.data?.revisionNumber ?? 0,
        blocks,
      ),
    onSuccess: refreshDetail,
  });
  const reviseProgramShots = useMutation({
    mutationFn: (payload: ProgramShotPayload) =>
      contentProjectsApi.reviseProgramAndShots(
        activeCode,
        detail.data?.revisionNumber ?? 0,
        payload.segments,
        payload.shots,
      ),
    onSuccess: refreshDetail,
  });
  const confirmBrief = useMutation({
    mutationFn: () =>
      contentProjectsApi.confirmBrief(
        activeCode,
        detail.data?.revisionNumber ?? 0,
      ),
    onSuccess: refreshDetail,
  });
  const generate = useMutation({
    mutationFn: () => contentProjectsApi.generate(activeCode),
    onSuccess: refreshDetail,
  });
  return (
    <div className="content-project-layout">
      <aside className="wb-section content-project-rail">
        <SectionHeader
          kicker="CONTENT PROJECTS"
          title="内容项目"
          actions={
            <button
              type="button"
              className="wb-button wb-button-primary"
              onClick={() => setShowCreate((value) => !value)}
            >
              <FolderPlus size={14} aria-hidden="true" />
              新建
            </button>
          }
        />
        {showCreate ? (
          <ProjectCreate
            onCreated={(code) => {
              setSelectedCode(code);
              setShowCreate(false);
              void queryClient.invalidateQueries({
                queryKey: ["content-projects"],
              });
            }}
          />
        ) : null}
        {projects.isLoading ? (
          <LoadingBlock />
        ) : projects.data?.length ? (
          <div className="content-project-list">
            {projects.data.map((project) => (
              <button
                key={project.projectCode}
                type="button"
                className={
                  project.projectCode === activeCode ? "active" : undefined
                }
                onClick={() => setSelectedCode(project.projectCode)}
              >
                <span>
                  <strong>{project.title}</strong>
                  <small>{project.generationGoal}</small>
                  <code>{project.projectCode}</code>
                </span>
                <StatusBadge
                  label={`r${project.revisionNumber}`}
                  tone={project.status === "confirmed" ? "success" : "warning"}
                />
              </button>
            ))}
          </div>
        ) : (
          <EmptyBlock
            icon={BookOpenText}
            title="尚无内容项目"
            detail="创建目标后即可生成剧本与 Shot。"
          />
        )}
      </aside>
      <div className="content-project-main">
        {detail.isLoading ? (
          <LoadingBlock label="正在读取内容链" />
        ) : detail.error ? (
          <InlineNotice tone="danger" title="内容项目读取失败">
            {errorMessage(detail.error)}
          </InlineNotice>
        ) : detail.data ? (
          <>
            <div className="content-project-actions">
              <div>
                <span>从目标到镜头</span>
                <strong>
                  {detail.data.generated
                    ? "已生成内容链"
                    : detail.data.status === "confirmed" &&
                        detail.data.designBrief?.status === "confirmed"
                      ? "输入已确认，等待生成"
                      : "等待确认输入与设计说明"}
                </strong>
              </div>
              <div className="wb-table-actions">
                {detail.data.status !== "confirmed" ? (
                  <button
                    type="button"
                    className="wb-button"
                    disabled={confirm.isPending}
                    onClick={() => confirm.mutate()}
                  >
                    <CheckCircle2 size={15} aria-hidden="true" />
                    确认输入
                  </button>
                ) : null}
                <button
                  type="button"
                  className="wb-button wb-button-primary"
                  disabled={
                    generate.isPending ||
                    detail.data.status !== "confirmed" ||
                    detail.data.designBrief?.status !== "confirmed"
                  }
                  onClick={() => generate.mutate()}
                >
                  <Sparkles size={15} aria-hidden="true" />
                  {detail.data.generated ? "生成新修订" : "生成内容链"}
                </button>
              </div>
            </div>
            {update.error ||
            confirm.error ||
            parseBrief.error ||
            reviseBrief.error ||
            reviseScript.error ||
            reviseProgramShots.error ||
            confirmBrief.error ? (
              <InlineNotice tone="danger" title="内容输入操作失败">
                {errorMessage(
                  update.error ??
                    confirm.error ??
                    parseBrief.error ??
                    reviseBrief.error ??
                    reviseScript.error ??
                    reviseProgramShots.error ??
                    confirmBrief.error,
                )}
              </InlineNotice>
            ) : null}
            {generate.error ? (
              <InlineNotice tone="danger" title="内容生成失败">
                {errorMessage(generate.error)}
              </InlineNotice>
            ) : null}
            <Chain
              detail={detail.data}
              onSaveInputs={(payload) => update.mutate(payload)}
              savingInputs={update.isPending}
              onParseBrief={(rawInput) => parseBrief.mutate(rawInput)}
              onReviseBrief={(overrides) => reviseBrief.mutate(overrides)}
              onReviseScript={(blocks) => reviseScript.mutate(blocks)}
              onReviseProgramShots={(payload) =>
                reviseProgramShots.mutate(payload)
              }
              onConfirmBrief={() => confirmBrief.mutate()}
              parsingBrief={parseBrief.isPending}
              revisingBrief={reviseBrief.isPending}
              revisingScript={reviseScript.isPending}
              revisingProgramShots={reviseProgramShots.isPending}
              confirmingBrief={confirmBrief.isPending}
            />
          </>
        ) : (
          <EmptyBlock icon={Clapperboard} title="选择内容项目" />
        )}
      </div>
    </div>
  );
}

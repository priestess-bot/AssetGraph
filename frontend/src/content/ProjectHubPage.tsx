import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpenText,
  Check,
  ChevronRight,
  Clapperboard,
  Clock3,
  FileText,
  FolderKanban,
  Link2,
  MonitorUp,
  PackageCheck,
  Plus,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { z } from "zod";
import { assetLibraryApi } from "../assets/api";
import { PageHeader, ProgressSteps } from "../product/components";
import { DeliveryProductPanel } from "../releases/DeliveryProductPanel";
import { VideoEditorProductPage } from "../videos/VideoEditorProductPage";
import { LiveRoomEditorProductPage } from "../live-rooms/LiveRoomEditorProductPage";
import { liveResearchApi } from "../live-research/api";
import { knowledgeApi } from "../knowledge/api";
import { EmptyBlock, InlineNotice, LoadingBlock, StatusBadge, formatDate } from "../workbench/components";
import { productCopy, productLabel, productTitle } from "../workbench/productLanguage";
import { contentProjectsApi, type ContentProjectDetail, type ContentProjectSummary } from "./api";
import { GuidedProjectCreateDialog, GuidedProjectWorkspace } from "./GuidedProjectWorkspace";

const projectSchema = z.object({
  title: z.string().trim().min(1, "请填写直播间标题").max(255),
  targetLiveRoomId: z.string().trim().min(1, "请填写直播间 ID").max(128),
  generationGoal: z.string().trim().min(10, "请用至少 10 个字说明生成目标").max(4000),
  theme: z.string().trim().max(1000),
  story: z.string().trim().max(4000),
  detailedDesign: z.string().trim().max(8000),
  audience: z.string().trim().max(500),
  targetDurationMinutes: z.number().min(1).max(1440),
});
type ProjectForm = z.infer<typeof projectSchema>;

const PROJECT_TABS = [
  { value: "brief", label: "简报", icon: BookOpenText },
  { value: "script", label: "剧本", icon: FileText },
  { value: "live-room", label: "直播间", icon: MonitorUp },
  { value: "video", label: "成片", icon: Clapperboard },
  { value: "delivery", label: "交付", icon: PackageCheck },
  { value: "activity", label: "动态", icon: Clock3 },
] as const;

function replaceProjectQuery(values: Record<string, string | undefined>) {
  const query = new URLSearchParams(window.location.search);
  Object.entries(values).forEach(([key, value]) => value ? query.set(key, value) : query.delete(key));
  window.history.pushState(null, "", `${window.location.pathname}?${query.toString()}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function SelectionRow({ checked, primary, title, detail, onChange }: { checked: boolean; primary?: boolean; title: string; detail: string; onChange: () => void }) {
  return <button type="button" className={`project-selection-row ${checked ? "selected" : ""}`} onClick={onChange}>
    <span className="project-check">{checked ? <Check size={13} aria-hidden="true" /> : null}</span>
    <span><strong>{productTitle(title, "未命名内容")}</strong><small>{detail}</small></span>
    {primary ? <em>主参考</em> : null}
  </button>;
}

export function ProjectCreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [primaryTemplate, setPrimaryTemplate] = useState("");
  const [secondaryTemplates, setSecondaryTemplates] = useState<string[]>([]);
  const [groupCodes, setGroupCodes] = useState<string[]>([]);
  const [assetCodes, setAssetCodes] = useState<string[]>([]);
  const templates = useQuery({ queryKey: ["live-research", "templates"], queryFn: liveResearchApi.listTemplates, enabled: open });
  const groups = useQuery({ queryKey: ["assets", "groups"], queryFn: assetLibraryApi.listGroups, enabled: open });
  const assets = useQuery({ queryKey: ["assets", "library"], queryFn: assetLibraryApi.listAssets, enabled: open });
  const form = useForm<ProjectForm>({
    resolver: zodResolver(projectSchema),
    defaultValues: { title: "", targetLiveRoomId: "", generationGoal: "", theme: "", story: "", detailedDesign: "", audience: "", targetDurationMinutes: 60 },
  });
  const create = useMutation({
    mutationFn: (value: ProjectForm) => contentProjectsApi.create({
      title: value.title,
      target_live_room_id: value.targetLiveRoomId,
      generation_goal: value.generationGoal,
      theme: value.theme || undefined,
      story: value.story || undefined,
      detailed_design: value.detailedDesign || undefined,
      audience: value.audience || undefined,
      target_duration_seconds: value.targetDurationMinutes * 60,
      platform: "maitu",
      primary_template_code: primaryTemplate || undefined,
      secondary_template_codes: secondaryTemplates,
      selected_group_codes: groupCodes,
      selected_asset_codes: assetCodes,
    }),
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ["content-projects"] });
      onClose();
      replaceProjectQuery({ project: project.projectCode, tab: "brief", create: undefined });
    },
  });
  const next = async () => {
    if (step === 0 && !(await form.trigger(["title", "targetLiveRoomId", "generationGoal"]))) return;
    if (step === 1 && !(await form.trigger(["theme", "story", "detailedDesign", "audience", "targetDurationMinutes"]))) return;
    setStep((current) => Math.min(3, current + 1));
  };
  const close = () => { setStep(0); create.reset(); onClose(); };
  const publishedTemplates = (templates.data ?? []).filter((item) => item.status === "published");
  const usableAssets = (assets.data ?? []).filter((item) => item.rightsStatus === "approved" && item.executionCapability !== "unavailable");

  return <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) close(); }}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="project-create-dialog">
    <header><div><Dialog.Title>新建直播内容项目</Dialog.Title><Dialog.Description>先填写生成目标，再选择参考模板和素材。创建后仍可自由修改。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header>
    <div className="project-create-body"><ProgressSteps current={step} items={["基本信息", "创意补充", "参考模板", "素材选择"]} />
      <form id="project-create-form" onSubmit={form.handleSubmit((value) => create.mutate(value))}>
        {step === 0 ? <section className="project-form-section"><div className="project-form-heading"><h2>从直播间和目标开始</h2><p>直播间 ID、标题和生成目标是必填项。</p></div><div className="project-form-grid">
          <label className="wb-field"><span>直播间 ID</span><input aria-label="直播间 ID" {...form.register("targetLiveRoomId")} placeholder="填写麦兔直播间 ID" />{form.formState.errors.targetLiveRoomId ? <small>{form.formState.errors.targetLiveRoomId.message}</small> : null}</label>
          <label className="wb-field"><span>直播间标题</span><input aria-label="直播间标题" {...form.register("title")} placeholder="例如：盛夏清凉家居专场" />{form.formState.errors.title ? <small>{form.formState.errors.title.message}</small> : null}</label>
          <label className="wb-field project-span-all"><span>生成目标</span><textarea aria-label="生成目标" rows={5} {...form.register("generationGoal")} placeholder="说明这场直播希望面向谁、讲清什么、推动观众完成什么动作" />{form.formState.errors.generationGoal ? <small>{form.formState.errors.generationGoal.message}</small> : null}</label>
        </div></section> : null}
        {step === 1 ? <section className="project-form-section"><div className="project-form-heading"><h2>补充创意方向</h2><p>主题、故事和详细设计可以只填写其中一部分。</p></div><div className="project-form-grid">
          <label className="wb-field"><span>主题</span><input aria-label="主题" {...form.register("theme")} placeholder="这场直播围绕什么展开" /></label>
          <label className="wb-field"><span>目标观众</span><input {...form.register("audience")} placeholder="主要面向哪些观众" /></label>
          <label className="wb-field"><span>预计时长（分钟）</span><input type="number" min={1} max={1440} {...form.register("targetDurationMinutes", { valueAsNumber: true })} /></label>
          <label className="wb-field project-span-all"><span>故事线</span><textarea rows={3} {...form.register("story")} placeholder="希望直播如何开场、展开和收束" /></label>
          <label className="wb-field project-span-all"><span>详细设计</span><textarea rows={5} {...form.register("detailedDesign")} placeholder="补充场景、陈列、互动、话术或不能出现的内容" /></label>
        </div></section> : null}
        {step === 2 ? <section className="project-form-section"><div className="project-form-heading"><h2>选择参考模板</h2><p>最多选择一个主参考；次要参考用于补充局部策略。</p></div><div className="project-template-columns"><div><h3>主参考</h3>{publishedTemplates.length ? publishedTemplates.map((template) => <SelectionRow key={`primary:${template.template_code}`} checked={primaryTemplate === template.template_code} primary={primaryTemplate === template.template_code} title={template.title} detail={`${productLabel(template.contentReadiness)} · ${productLabel(template.buildability)}`} onChange={() => { const next = primaryTemplate === template.template_code ? "" : template.template_code; setPrimaryTemplate(next); setSecondaryTemplates((current) => current.filter((code) => code !== next)); }} />) : <EmptyBlock title="暂无已发布模板" detail="可以先创建项目，之后再到简报中补充模板。" />}</div><div><h3>次要参考（最多 5 个）</h3>{publishedTemplates.filter((template) => template.template_code !== primaryTemplate).map((template) => <SelectionRow key={`secondary:${template.template_code}`} checked={secondaryTemplates.includes(template.template_code)} title={template.title} detail={`${productLabel(template.contentReadiness)} · ${productLabel(template.layout_fidelity)}`} onChange={() => setSecondaryTemplates((current) => current.includes(template.template_code) ? current.filter((code) => code !== template.template_code) : current.length < 5 ? [...current, template.template_code] : current)} />)}</div></div></section> : null}
        {step === 3 ? <section className="project-form-section"><div className="project-form-heading"><h2>选择项目素材</h2><p>素材组和零散素材分别选择；项目内调整不会覆盖素材库的全局约束。</p></div><div className="project-template-columns"><div><h3>素材组</h3>{groups.data?.length ? groups.data.map((group) => <SelectionRow key={group.groupCode} checked={groupCodes.includes(group.groupCode)} title={group.title} detail={`${group.assetCount} 份素材`} onChange={() => setGroupCodes((current) => current.includes(group.groupCode) ? current.filter((code) => code !== group.groupCode) : [...current, group.groupCode])} />) : <EmptyBlock title="暂无素材组" />}</div><div><h3>零散素材</h3>{usableAssets.length ? usableAssets.map((asset) => <SelectionRow key={asset.assetCode} checked={assetCodes.includes(asset.assetCode)} title={asset.title} detail={`${productLabel(asset.mediaKind ?? asset.assetType)} · ${asset.materialRoles.map((role) => productLabel(role, "待设定用途")).join("、") || "待设定用途"}`} onChange={() => setAssetCodes((current) => current.includes(asset.assetCode) ? current.filter((code) => code !== asset.assetCode) : [...current, asset.assetCode])} />) : <EmptyBlock title="暂无可用素材" />}</div></div><div className="project-create-review"><span>已选择</span><strong>{primaryTemplate ? "1 个主模板" : "不使用主模板"} · {secondaryTemplates.length} 个次模板 · {groupCodes.length} 个素材组 · {assetCodes.length} 份零散素材</strong></div></section> : null}
      </form>
      {create.error ? <InlineNotice tone="danger" title="项目没有创建">请检查必填信息和所选模板状态后重试。</InlineNotice> : null}
    </div>
    <footer><button type="button" className="wb-button" onClick={step ? () => setStep((current) => current - 1) : close}>{step ? "上一步" : "取消"}</button><div>{step < 3 ? <button key="next-step" type="button" className="wb-button wb-button-primary" onClick={(event) => { event.preventDefault(); void next(); }}>下一步<ChevronRight size={15} aria-hidden="true" /></button> : <button key="submit-project" form="project-create-form" type="submit" className="wb-button wb-button-primary" disabled={create.isPending}>{create.isPending ? "正在创建" : "创建项目"}</button>}</div></footer>
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}

function ProjectList({ projects, onCreate }: { projects: ContentProjectSummary[]; onCreate: () => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const filtered = projects.filter((project) => (status === "all" || project.status === status) && `${project.title} ${project.generationGoal}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="project-index"><PageHeader eyebrow="内容生产" title="内容项目" description="一个项目集中管理生成目标、剧本、直播间、成片、交付和运营反馈。" actions={<button className="wb-button wb-button-primary" type="button" onClick={onCreate}><Plus size={16} aria-hidden="true" />新建项目</button>} />
    <div className="project-list-toolbar"><label><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目名称或生成目标" aria-label="搜索内容项目" /></label><div role="group" aria-label="项目状态">{[["all", "全部"], ["draft", "草稿"], ["active", "进行中"], ["archived", "已停用"]].map(([value, label]) => <button type="button" key={value} className={status === value ? "active" : undefined} onClick={() => setStatus(value)}>{label}</button>)}</div><span>{filtered.length} 个项目</span></div>
    {filtered.length ? <div className="project-table"><div className="project-table-head"><span>项目</span><span>生成目标</span><span>当前状态</span><span>最近更新</span><span /></div>{filtered.map((project) => <a href={`/projects?project=${encodeURIComponent(project.projectCode)}&tab=brief`} key={project.projectCode}><span><strong>{project.title}</strong><small>第 {project.revisionNumber} 版</small></span><p>{project.generationGoal}</p><StatusBadge label={project.status} tone={project.status === "confirmed" || project.status === "active" ? "success" : "neutral"} /><time>{formatDate(project.updatedAt)}</time><ChevronRight size={16} aria-hidden="true" /></a>)}</div> : <EmptyBlock icon={FolderKanban} title="没有匹配的项目" detail={projects.length ? "调整搜索词或状态筛选。" : "创建项目后，从生成目标开始组织整场直播内容。"} />}
  </div>;
}

function BriefPanel({ project, onUpdated }: { project: ContentProjectDetail; onUpdated: () => void }) {
  const prepare = useMutation({ mutationFn: async () => {
    let current = project;
    if (current.status !== "confirmed") current = await contentProjectsApi.confirm(current.projectCode, current.revisionNumber);
    const raw = [current.generationGoal, current.content.theme, current.content.story, current.content.detailed_design].filter((item) => typeof item === "string" && item.trim()).join("\n\n");
    current = await contentProjectsApi.parseBrief(current.projectCode, current.revisionNumber, raw);
    return current;
  }, onSuccess: onUpdated });
  const confirm = useMutation({ mutationFn: () => contentProjectsApi.confirmBrief(project.projectCode, project.revisionNumber), onSuccess: onUpdated });
  const generate = useMutation({ mutationFn: () => contentProjectsApi.generate(project.projectCode), onSuccess: onUpdated });
  const content = project.content;
  const blockers = project.designBrief?.open_questions.filter((item) => item.blocking) ?? [];
  return <div className="project-brief-workspace"><section className="project-brief-main"><header><div><h2>生成目标</h2><p>确认系统理解的方向，再生成剧本和节目结构。</p></div><StatusBadge label={project.designBrief?.status ?? "draft"} tone={project.designBrief?.status === "confirmed" ? "success" : "warning"} /></header><div className="project-goal"><p>{project.generationGoal}</p></div><dl className="project-brief-fields"><div><dt>目标直播间</dt><dd>{typeof content.target_live_room_id === "string" ? content.target_live_room_id : "尚未填写"}</dd></div><div><dt>主题</dt><dd>{typeof content.theme === "string" && content.theme ? content.theme : "尚未补充"}</dd></div><div><dt>目标观众</dt><dd>{typeof content.audience === "string" && content.audience ? content.audience : "尚未补充"}</dd></div><div><dt>预计时长</dt><dd>{typeof content.target_duration_seconds === "number" ? `${Math.round(content.target_duration_seconds / 60)} 分钟` : "尚未设置"}</dd></div><div className="wide"><dt>故事线</dt><dd>{typeof content.story === "string" && content.story ? content.story : "尚未补充"}</dd></div><div className="wide"><dt>详细设计</dt><dd>{typeof content.detailed_design === "string" && content.detailed_design ? content.detailed_design : "尚未补充"}</dd></div></dl>{blockers.length ? <InlineNotice tone="warning" title="生成前还有信息需要确认">{blockers.map((item) => item.question).join("；")}</InlineNotice> : null}<footer>{!project.designBrief ? <button className="wb-button wb-button-primary" type="button" disabled={prepare.isPending} onClick={() => prepare.mutate()}><Sparkles size={15} aria-hidden="true" />{prepare.isPending ? "正在整理" : "整理生成简报"}</button> : project.designBrief.status !== "confirmed" ? <button className="wb-button wb-button-primary" type="button" disabled={confirm.isPending || blockers.length > 0} onClick={() => confirm.mutate()}><Check size={15} aria-hidden="true" />确认简报</button> : !project.generated ? <button className="wb-button wb-button-primary" type="button" disabled={generate.isPending} onClick={() => generate.mutate()}><Sparkles size={15} aria-hidden="true" />{generate.isPending ? "正在生成" : "生成剧本与场景"}</button> : <a className="wb-button wb-button-primary" href={`/projects?project=${encodeURIComponent(project.projectCode)}&tab=script`}>查看剧本<ChevronRight size={15} aria-hidden="true" /></a>}</footer>{prepare.error || confirm.error || generate.error ? <InlineNotice tone="danger" title="这一步没有完成">请检查简报中的必填内容和事实状态后重试。</InlineNotice> : null}</section><aside className="project-reference-summary"><h3>本项目参考</h3><div><span>主模板</span><strong>{typeof content.primary_template_code === "string" && content.primary_template_code ? "已选择" : "未选择"}</strong></div><div><span>次要模板</span><strong>{Array.isArray(content.secondary_template_codes) ? content.secondary_template_codes.length : 0} 个</strong></div><div><span>素材组</span><strong>{Array.isArray(content.selected_group_codes) ? content.selected_group_codes.length : 0} 个</strong></div><div><span>零散素材</span><strong>{Array.isArray(content.selected_asset_codes) ? content.selected_asset_codes.length : 0} 份</strong></div><div><span>已批准事实</span><strong>{project.factCards.length + project.factClaims.length} 条</strong></div></aside></div>;
}

function ScriptPanel({ project, onUpdated }: { project: ContentProjectDetail; onUpdated: () => void }) {
  const [blocks, setBlocks] = useState(project.script?.blocks ?? []);
  const cards = useQuery({ queryKey: ["product-fact-cards"], queryFn: knowledgeApi.listProductFactCards, enabled: Boolean(project.script) });
  const sources = useQuery({ queryKey: ["knowledge-source-evidences"], queryFn: knowledgeApi.listSourceEvidences, enabled: Boolean(project.script) });
  useEffect(() => setBlocks(project.script?.blocks ?? []), [project.script]);
  const save = useMutation({ mutationFn: () => contentProjectsApi.reviseScript(project.projectCode, project.revisionNumber, blocks.map((block) => ({ module_type: block.module_type, content: block.content, estimated_duration_ms: block.estimated_duration_ms, fact_citations: block.fact_citations, template_sources: block.template_sources, interaction_intent: block.interaction_intent, cta_intent: block.cta_intent }))), onSuccess: onUpdated });
  if (!project.script) return <EmptyBlock icon={FileText} title="还没有剧本" detail="请先在简报页确认目标并生成内容。" />;
  return <section className="project-script-workspace"><header><div><h2>{project.script.title || "直播剧本"}</h2><p>{project.script.blocks.length} 个话术块，可直接修改后保存为新版本。</p></div><button className="wb-button wb-button-primary" type="button" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "正在保存" : "保存新版本"}</button></header><div className="project-script-blocks">{blocks.map((block, index) => <article key={block.block_code || index}><div><b>{index + 1}</b><span><strong>{productLabel(block.module_type, `话术 ${index + 1}`)}</strong><small>{block.estimated_duration_ms ? `约 ${Math.round(block.estimated_duration_ms / 1000)} 秒` : "时长待定"} · {block.fact_citations.length} 条事实引用</small></span></div><textarea aria-label={`话术 ${index + 1}`} rows={5} value={block.content} onChange={(event) => setBlocks((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, content: event.target.value } : item))} />{block.fact_citations.length ? <div className="project-script-citations"><strong>事实依据</strong>{block.fact_citations.map((citation, citationIndex) => {
    const card = cards.data?.find((item) => item.factCardCode === citation.fact_card_code);
    const claim = project.factClaims.find((item) => item.claim_code === citation.claim_code);
    const source = sources.data?.find((item) => item.evidenceCode === (citation.source_evidence_code ?? claim?.source_evidence_code));
    const href = card ? `/knowledge?fact=${encodeURIComponent(card.factCardCode)}` : source ? `/knowledge?view=sources&source=${encodeURIComponent(source.evidenceCode)}` : "/knowledge";
    return <a key={`${citation.fact_card_code ?? citation.claim_code ?? citationIndex}:${citationIndex}`} href={href}><Link2 size={14} aria-hidden="true" /><span><b>{card?.title ?? source?.title ?? "已核验事实"}</b><small>{citation.claim_text ?? claim?.claim ?? "打开知识库查看引用内容"}</small></span><ChevronRight size={14} aria-hidden="true" /></a>;
  })}</div> : null}</article>)}</div>{save.error ? <InlineNotice tone="danger" title="剧本没有保存">项目内容可能已更新，请刷新后再试。</InlineNotice> : null}</section>;
}

function ActivityPanel({ activity }: { activity: Array<{ kind: string; title: string; detail: string; status: string; occurredAt: string }> }) {
  return <section className="project-activity"><header><h2>项目动态</h2><p>只展示影响内容生产和交付的关键变化。</p></header>{activity.length ? <div>{activity.map((item, index) => <article key={`${item.kind}:${item.occurredAt}:${index}`}><span className="project-activity-dot" /><time>{formatDate(item.occurredAt)}</time><div><strong>{productCopy(item.title, "项目内容已更新")}</strong><p>{productCopy(item.detail, "打开对应页面查看最新内容。")}</p></div><StatusBadge label={item.status} tone={item.status === "failed" || item.status === "blocked" ? "danger" : item.status === "confirmed" || item.status === "completed" ? "success" : "neutral"} /></article>)}</div> : <EmptyBlock title="还没有项目动态" />}</section>;
}

function ProjectWorkspace({ projectCode, tab }: { projectCode: string; tab: string }) {
  const queryClient = useQueryClient();
  const project = useQuery({ queryKey: ["content-project", projectCode], queryFn: () => contentProjectsApi.get(projectCode) });
  const summary = useQuery({ queryKey: ["content-project", projectCode, "workspace-summary"], queryFn: () => contentProjectsApi.workspaceSummary(projectCode) });
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ["content-project", projectCode] }); };
  if (project.isLoading) return <LoadingBlock label="正在打开项目工作区" />;
  if (project.data?.content.workflow_version === "guided-live.v1") return <GuidedProjectWorkspace projectCode={projectCode} tab={tab} />;
  if (summary.isLoading) return <LoadingBlock label="正在打开项目工作区" />;
  if (!project.data || !summary.data) return <EmptyBlock title="项目无法打开" detail="该项目不存在或暂时无法读取。" />;
  const activeTab = PROJECT_TABS.some((item) => item.value === tab) ? tab : "brief";
  const outputByTab = { brief: summary.data.brief, script: summary.data.script, "live-room": summary.data.liveRoom, video: summary.data.video, delivery: summary.data.delivery, activity: summary.data.operations };
  return <div className={`project-workspace is-${activeTab}`}><a className="project-back" href="/projects"><ArrowLeft size={15} aria-hidden="true" />返回项目列表</a><PageHeader eyebrow="内容项目" title={project.data.title} description={project.data.generationGoal} actions={<StatusBadge label={project.data.status} tone={project.data.status === "confirmed" || project.data.status === "active" ? "success" : "warning"} />} />
    <nav className="project-tabs" aria-label="项目工作区">{PROJECT_TABS.map((item) => { const Icon = item.icon; const output = outputByTab[item.value]; return <a key={item.value} className={activeTab === item.value ? "active" : undefined} href={`/projects?project=${encodeURIComponent(projectCode)}&tab=${item.value}`}><Icon size={15} aria-hidden="true" /><span>{item.label}</span>{output.available ? <i className="ready" /> : <i />}</a>; })}</nav>
    <div className="project-tab-content">{activeTab === "brief" ? <BriefPanel project={project.data} onUpdated={refresh} /> : activeTab === "script" ? <ScriptPanel project={project.data} onUpdated={refresh} /> : activeTab === "live-room" ? <LiveRoomEditorProductPage search={`?project=${encodeURIComponent(projectCode)}${summary.data.liveRoom.referenceCode ? `&run=${encodeURIComponent(summary.data.liveRoom.referenceCode)}` : ""}`} /> : activeTab === "video" ? <VideoEditorProductPage search={`?project=${encodeURIComponent(projectCode)}${summary.data.video.referenceCode ? `&plan=${encodeURIComponent(summary.data.video.referenceCode)}` : ""}`} /> : activeTab === "delivery" ? summary.data.delivery.referenceCode ? <DeliveryProductPanel search={`?release=${encodeURIComponent(summary.data.delivery.referenceCode)}`} /> : <EmptyBlock icon={PackageCheck} title="还没有可交付内容" detail="生成直播间方案或成片，并通过相应检查后，交付内容会出现在这里。" /> : <ActivityPanel activity={summary.data.activity} />}</div>
  </div>;
}

export function ProjectHubPage({ search }: { search: string }) {
  const params = new URLSearchParams(search);
  const selected = params.get("project") ?? "";
  const tab = params.get("tab") ?? (params.get("view") === "activity" ? "activity" : params.get("view") === "delivery" ? "delivery" : "brief");
  const [createOpen, setCreateOpen] = useState(params.get("create") === "1");
  const projects = useQuery({ queryKey: ["content-projects"], queryFn: contentProjectsApi.list, enabled: !selected });
  return <><GuidedProjectCreateDialog open={createOpen} onClose={() => { setCreateOpen(false); replaceProjectQuery({ create: undefined }); }} />{selected ? <ProjectWorkspace projectCode={selected} tab={tab} /> : projects.isLoading ? <LoadingBlock label="正在读取内容项目" /> : projects.error ? <EmptyBlock title="项目列表暂时无法读取" detail="请检查服务连接后刷新页面。" /> : <ProjectList projects={projects.data ?? []} onCreate={() => setCreateOpen(true)} />}</>;
}

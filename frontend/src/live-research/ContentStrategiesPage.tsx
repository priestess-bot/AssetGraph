import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, CheckCircle2, CircleAlert, ExternalLink, Plus, Send, Sparkles, Trash2 } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge } from "../workbench/components";
import { liveResearchApi } from "./api";
import { DEMO_CAPTURE_SESSIONS, DEMO_TEMPLATES, DEMO_WATCH_TARGETS } from "./demoData";
import type { CaptureSession, RoomTemplate } from "./types";

interface DraftModule {
  moduleKey: string;
  title: string;
  purpose: string;
  sourceSessionCode: string;
  startMs: number;
  endMs: number;
}

interface DraftExample {
  moduleKey: string;
  exampleText: string;
  sourceSessionCode: string;
  startMs: number;
  endMs: number;
}

const SOURCE_FACT_CATEGORIES = ["商品身份", "价格", "促销活动", "库存", "来源品牌", "主播身份"];

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : "操作未完成"; }
function toggle(values: string[], value: string): string[] { return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]; }
function nextModuleKey(modules: DraftModule[]): string {
  const largest = Math.max(0, ...modules.map((module) => Number(module.moduleKey.match(/^module-(\d+)$/)?.[1]) || 0));
  return `module-${largest + 1}`;
}
function emptyModule(key: string): DraftModule { return { moduleKey: key, title: "", purpose: "", sourceSessionCode: "", startMs: 0, endMs: 30_000 }; }
function readinessTone(value: string): "success" | "warning" | "danger" | "neutral" { return value === "ready" ? "success" : value === "blocked" ? "danger" : "warning"; }

export function sourceEvidenceHref(sourceSessionCode: string, startMs: number, endMs: number): string {
  const query = new URLSearchParams({ view: "sessions", session: sourceSessionCode });
  if (Number.isFinite(startMs) && Number.isFinite(endMs) && startMs >= 0 && endMs > startMs) {
    query.set("in", String(startMs / 1000));
    query.set("out", String(endMs / 1000));
  }
  return `/research/live-sources?${query.toString()}`;
}

function EvidenceLink({ sourceSessionCode, startMs, endMs }: { sourceSessionCode?: string; startMs: number; endMs: number }) {
  if (!sourceSessionCode) return <span>缺少来源证据</span>;
  return <a href={sourceEvidenceHref(sourceSessionCode, startMs, endMs)} title="打开来源录屏并定位到证据区间"><ExternalLink size={13} aria-hidden="true" />{sourceSessionCode} · {startMs / 1000}-{endMs / 1000} 秒</a>;
}

function StrategyList({ templates, selected, onSelect }: { templates: RoomTemplate[]; selected: string; onSelect: (value: string) => void }) {
  if (!templates.length) return <EmptyBlock icon={BookOpenCheck} title="尚无内容策略模板" />;
  return <ul className="research-template-list wb-list">{templates.map((template) => <li key={template.template_code}><button type="button" className={selected === template.template_code ? "active" : undefined} onClick={() => onSelect(template.template_code)}><div><strong>{template.title}</strong><code>{template.template_code} · r{template.latest_revision}</code><small>{template.sourceTargetCode ?? "来源待补"} · {template.contentStrategy.targetCategory || "未标注品类"}</small></div><span><StatusBadge label={template.published_revision ? "已发布" : "草稿"} tone={template.published_revision ? "success" : "warning"} /></span></button></li>)}</ul>;
}

function boundedIntervalValid(item: { sourceSessionCode: string; startMs: number; endMs: number }, sessions: CaptureSession[]): boolean {
  const source = sessions.find((session) => session.session_code === item.sourceSessionCode);
  return Boolean(source && item.startMs >= 0 && item.endMs > item.startMs && (!source.duration_seconds || item.endMs <= source.duration_seconds * 1000));
}

export function ContentStrategiesPage() {
  const queryClient = useQueryClient();
  const [selectedCode, setSelectedCode] = useState("");
  const [title, setTitle] = useState("");
  const [targetCode, setTargetCode] = useState("");
  const [sessionCodes, setSessionCodes] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [modules, setModules] = useState<DraftModule[]>([emptyModule("module-1")]);
  const [examples, setExamples] = useState<DraftExample[]>([]);
  const [materialCues, setMaterialCues] = useState("background,promotion_text");
  const [factsRemovedConfirmed, setFactsRemovedConfirmed] = useState(false);
  const targets = useQuery({ queryKey: ["live-research", "watch-targets"], queryFn: liveResearchApi.listWatchTargets });
  const sessions = useQuery({ queryKey: ["live-research", "capture-sessions"], queryFn: liveResearchApi.listCaptureSessions });
  const templates = useQuery({ queryKey: ["live-research", "templates"], queryFn: liveResearchApi.listTemplates });
  const demoMode = new URLSearchParams(window.location.search).get("demo") === "1" || targets.isError && sessions.isError && templates.isError;
  const targetData = targets.data ?? (demoMode ? DEMO_WATCH_TARGETS : []);
  const sessionData = sessions.data ?? (demoMode ? DEMO_CAPTURE_SESSIONS : []);
  const templateData = templates.data ?? (demoMode ? DEMO_TEMPLATES : []);
  const strategies = useMemo(() => templateData.filter((item) => item.templateKind === "content_strategy"), [templateData]);
  const availableSessions = useMemo(() => sessionData.filter((item) => item.status === "completed" && item.target_code === targetCode), [sessionData, targetCode]);
  const selectedSessions = useMemo(() => availableSessions.filter((session) => sessionCodes.includes(session.session_code)), [availableSessions, sessionCodes]);

  useEffect(() => { if (!targetCode && targetData[0]) setTargetCode(targetData[0].target_code); }, [targetCode, targetData]);
  useEffect(() => { setSessionCodes((current) => current.filter((code) => availableSessions.some((session) => session.session_code === code))); }, [availableSessions]);
  useEffect(() => {
    const selected = new Set(sessionCodes);
    setModules((current) => current.map((module) => selected.has(module.sourceSessionCode) || !module.sourceSessionCode ? module : { ...module, sourceSessionCode: "" }));
    setExamples((current) => current.map((example) => selected.has(example.sourceSessionCode) || !example.sourceSessionCode ? example : { ...example, sourceSessionCode: "" }));
  }, [sessionCodes]);

  const activeCode = strategies.some((item) => item.template_code === selectedCode) ? selectedCode : strategies[0]?.template_code ?? "";
  useEffect(() => { if (selectedCode !== activeCode) setSelectedCode(activeCode); }, [activeCode, selectedCode]);
  const detail = useQuery({ queryKey: ["live-research", "template", activeCode], queryFn: () => liveResearchApi.getTemplate(activeCode), enabled: Boolean(activeCode) });
  const create = useMutation({
    mutationFn: () => liveResearchApi.createContentStrategyTemplate({
      title: title.trim(), sourceTargetCode: targetCode, sourceSessionCodes: sessionCodes, targetCategory: category.trim(),
      modules: modules.map((module) => ({ ...module, moduleKey: module.moduleKey.trim(), title: module.title.trim(), purpose: module.purpose.trim() })),
      reviewedExamples: examples.map((example) => ({ ...example, exampleText: example.exampleText.trim() })),
      materialCues: materialCues.split(/[,\n]/).map((item) => item.trim()).filter(Boolean),
    }),
    onSuccess: (created) => {
      setSelectedCode(created.template_code); setTitle(""); setSessionCodes([]); setModules([emptyModule("module-1")]); setExamples([]); setFactsRemovedConfirmed(false);
      void queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] });
    },
  });
  const publish = useMutation({ mutationFn: (template: RoomTemplate) => liveResearchApi.publishTemplate(template.template_code, template.latest_revision), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] }); void queryClient.invalidateQueries({ queryKey: ["live-research", "template", activeCode] }); } });
  const active = detail.data ?? strategies.find((item) => item.template_code === activeCode);
  const modulesValid = modules.length > 0 && modules.every((module) => module.moduleKey.trim() && module.title.trim() && module.purpose.trim() && boundedIntervalValid(module, selectedSessions));
  const examplesValid = examples.every((example) => example.moduleKey && modules.some((module) => module.moduleKey === example.moduleKey) && example.exampleText.trim() && boundedIntervalValid(example, selectedSessions));
  const createAllowed = Boolean(title.trim() && targetCode && sessionCodes.length && category.trim() && modulesValid && examplesValid && factsRemovedConfirmed);
  const loading = targets.isLoading || sessions.isLoading || templates.isLoading;
  const problem = demoMode ? undefined : targets.error ?? sessions.error ?? templates.error;
  const updateModule = (index: number, patch: Partial<DraftModule>) => setModules((current) => current.map((module, itemIndex) => itemIndex === index ? { ...module, ...patch } : module));
  const updateExample = (index: number, patch: Partial<DraftExample>) => setExamples((current) => current.map((example, itemIndex) => itemIndex === index ? { ...example, ...patch } : example));

  return <div className="research-strategy-layout">
    <aside className="wb-section research-template-rail"><SectionHeader kicker="CONTENT-STRATEGY.V2" title="内容策略模板" /><StrategyList templates={strategies} selected={activeCode} onSelect={setSelectedCode} /></aside>
    <main className="research-strategy-main">{loading ? <LoadingBlock label="正在读取来源直播间与模板" /> : problem ? <InlineNotice tone="danger" title="内容策略工作台无法加载">{errorMessage(problem)}</InlineNotice> : <>{demoMode ? <InlineNotice tone="warning" title="当前展示内容策略演示数据">连接直播研究服务后会读取真实来源场次、时间线和已发布策略。</InlineNotice> : null}
      <section className="wb-section"><SectionHeader kicker="CLEANED REFERENCE" title="创建内容策略模板" /><div className="wb-section-body research-strategy-form">
        <label className="wb-field"><span>模板名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <label className="wb-field"><span>来源直播间</span><select className="wb-input" value={targetCode} onChange={(event) => setTargetCode(event.target.value)}>{targetData.map((target) => <option key={target.target_code} value={target.target_code}>{target.display_name} · {target.target_code}</option>)}</select></label>
        <div className="research-strategy-sessions"><span>已完成来源录屏</span>{availableSessions.length ? availableSessions.map((session) => <label key={session.session_code}><input type="checkbox" checked={sessionCodes.includes(session.session_code)} onChange={() => setSessionCodes((current) => toggle(current, session.session_code))} /><span><strong>{session.title}</strong><small>{session.session_code} · {Math.round(session.duration_seconds)} 秒</small></span></label>) : <small>该直播间暂无已完成录屏。</small>}</div>
        <label className="wb-field"><span>适用品类</span><input className="wb-input" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="例如：葡萄酒、护肤、家电" /></label>
        <section className="research-strategy-editor"><div className="research-editor-heading"><div><span>节目模块与来源证据</span><small>每个模块必须固定到已勾选录屏的一个半开时间区间。</small></div><button type="button" className="wb-icon-button" title="添加节目模块" onClick={() => setModules((current) => [...current, emptyModule(nextModuleKey(current))])}><Plus size={15} aria-hidden="true" /></button></div>{modules.map((module, index) => <article key={`${module.moduleKey}-${index}`} className="research-strategy-module-card"><label className="wb-field"><span>模块键</span><input className="wb-input" value={module.moduleKey} onChange={(event) => updateModule(index, { moduleKey: event.target.value })} /></label><label className="wb-field"><span>模块名称</span><input className="wb-input" value={module.title} onChange={(event) => updateModule(index, { title: event.target.value })} /></label><label className="wb-field"><span>内容目标</span><input className="wb-input" value={module.purpose} onChange={(event) => updateModule(index, { purpose: event.target.value })} /></label><label className="wb-field"><span>来源场次</span><select className="wb-input" value={module.sourceSessionCode} onChange={(event) => updateModule(index, { sourceSessionCode: event.target.value })}><option value="">选择已勾选场次</option>{selectedSessions.map((session) => <option key={session.session_code} value={session.session_code}>{session.session_code}</option>)}</select></label><label className="wb-field"><span>起点（秒）</span><input className="wb-input" type="number" min="0" step="0.1" value={module.startMs / 1000} onChange={(event) => updateModule(index, { startMs: Math.round(Number(event.target.value) * 1000) })} /></label><label className="wb-field"><span>终点（秒）</span><input className="wb-input" type="number" min="0" step="0.1" value={module.endMs / 1000} onChange={(event) => updateModule(index, { endMs: Math.round(Number(event.target.value) * 1000) })} /></label><button type="button" className="wb-icon-button" title="删除节目模块" disabled={modules.length === 1} onClick={() => setModules((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={15} aria-hidden="true" /></button></article>)}</section>
        <section className="research-strategy-editor"><div className="research-editor-heading"><div><span>清洗后例证（可选）</span><small>仅保留去事实化短摘要，不录入来源原话或价格、品牌、主播特征。</small></div><button type="button" className="wb-icon-button" title="添加清洗后例证" onClick={() => setExamples((current) => [...current, { moduleKey: modules[0]?.moduleKey ?? "", exampleText: "", sourceSessionCode: "", startMs: 0, endMs: 10_000 }])}><Plus size={15} aria-hidden="true" /></button></div>{examples.map((example, index) => <article key={`${example.moduleKey}-${index}`} className="research-strategy-example-card"><label className="wb-field"><span>所属模块</span><select className="wb-input" value={example.moduleKey} onChange={(event) => updateExample(index, { moduleKey: event.target.value })}>{modules.map((module) => <option key={module.moduleKey} value={module.moduleKey}>{module.moduleKey}</option>)}</select></label><label className="wb-field"><span>来源场次</span><select className="wb-input" value={example.sourceSessionCode} onChange={(event) => updateExample(index, { sourceSessionCode: event.target.value })}><option value="">选择已勾选场次</option>{selectedSessions.map((session) => <option key={session.session_code} value={session.session_code}>{session.session_code}</option>)}</select></label><label className="wb-field"><span>起点（秒）</span><input className="wb-input" type="number" min="0" step="0.1" value={example.startMs / 1000} onChange={(event) => updateExample(index, { startMs: Math.round(Number(event.target.value) * 1000) })} /></label><label className="wb-field"><span>终点（秒）</span><input className="wb-input" type="number" min="0" step="0.1" value={example.endMs / 1000} onChange={(event) => updateExample(index, { endMs: Math.round(Number(event.target.value) * 1000) })} /></label><label className="wb-field wide"><span>去事实化短摘要</span><input className="wb-input" value={example.exampleText} onChange={(event) => updateExample(index, { exampleText: event.target.value })} /></label><button type="button" className="wb-icon-button" title="删除清洗后例证" onClick={() => setExamples((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={15} aria-hidden="true" /></button></article>)}</section>
        <label className="wb-field"><span>素材角色提示</span><input className="wb-input" value={materialCues} onChange={(event) => setMaterialCues(event.target.value)} /></label>
        <label className="research-confirm"><input type="checkbox" checked={factsRemovedConfirmed} onChange={(event) => setFactsRemovedConfirmed(event.target.checked)} /><span>我已从策略、模块和例证中移除 {SOURCE_FACT_CATEGORIES.join("、")}，仅保留可复用的节目结构。</span></label>
        <InlineNotice tone="info" title="仅内容参考">发布投影固定为 `reference_only`，模块与例证保留来源场次和时间区间以便复核，不会生成外部直播间的麦兔图层。</InlineNotice>
        <button type="button" className="wb-button wb-button-primary" disabled={!createAllowed || create.isPending} onClick={() => create.mutate()}><Sparkles size={15} aria-hidden="true" />创建策略草稿</button>{create.error ? <InlineNotice tone="danger" title="策略草稿创建失败">{errorMessage(create.error)}</InlineNotice> : null}
      </div></section>
      {active ? <section className="wb-section"><SectionHeader kicker={`${active.template_code} · r${active.latest_revision}`} title={active.title} actions={<><StatusBadge label={active.contentReadiness === "ready" ? "内容可用" : active.contentReadiness} tone={readinessTone(active.contentReadiness)} /><StatusBadge label="reference_only" tone="info" /></>} /><div className="wb-section-body research-strategy-detail"><div><span>来源直播间</span><code>{active.sourceTargetCode}</code></div><div><span>适用品类</span><strong>{active.contentStrategy.targetCategory || "待加载"}</strong></div><div><span>素材提示</span><strong>{active.contentStrategy.materialCues.join(" / ") || "未声明"}</strong></div><section className="research-strategy-outline"><h3>节目结构与媒体证据</h3>{active.contentStrategy.programOutline.map((module) => <article key={module.moduleKey}><code>{module.moduleKey}</code><strong>{module.title}</strong><span>{module.purpose}</span><small>{Math.round((module.endMs - module.startMs) / 1000)} 秒</small><EvidenceLink sourceSessionCode={module.sourceSessionCode} startMs={module.startMs} endMs={module.endMs} /></article>)}</section>{active.contentStrategy.reviewedExamples.length ? <section className="research-strategy-examples"><h3>清洗后例证</h3>{active.contentStrategy.reviewedExamples.map((example, index) => <article key={`${example.moduleKey}-${index}`}><code>{example.moduleKey}</code><span>{example.exampleText}</span><small><EvidenceLink sourceSessionCode={example.sourceSessionCode} startMs={example.startMs} endMs={example.endMs} /></small></article>)}</section> : null}{active.published_revision ? <InlineNotice title="发布版本已固定"><CheckCircle2 size={14} aria-hidden="true" />该策略可作为内容项目的主模板或次要模板，不能作为可执行布局。</InlineNotice> : <button type="button" className="wb-button wb-button-primary" disabled={publish.isPending || active.contentReadiness !== "ready"} onClick={() => publish.mutate(active)}><Send size={15} aria-hidden="true" />发布内容策略模板</button>}{publish.error ? <InlineNotice tone="danger" title="策略模板发布失败">{errorMessage(publish.error)}</InlineNotice> : null}</div></section> : <section className="wb-section"><EmptyBlock icon={CircleAlert} title="创建或选择内容策略模板" /></section>}</>}</main>
  </div>;
}

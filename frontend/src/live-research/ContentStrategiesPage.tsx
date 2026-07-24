import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, CheckCircle2, CircleAlert, Send, Sparkles } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge } from "../workbench/components";
import { liveResearchApi } from "./api";
import type { RoomTemplate } from "./types";

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : "操作未完成"; }
function toggle(values: string[], value: string): string[] { return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]; }

function readinessTone(value: string): "success" | "warning" | "danger" | "neutral" {
  return value === "ready" ? "success" : value === "blocked" ? "danger" : "warning";
}

function StrategyList({ templates, selected, onSelect }: { templates: RoomTemplate[]; selected: string; onSelect: (value: string) => void }) {
  if (!templates.length) return <EmptyBlock icon={BookOpenCheck} title="尚无内容策略模板" />;
  return <ul className="research-template-list wb-list">{templates.map((template) => <li key={template.template_code}><button type="button" className={selected === template.template_code ? "active" : undefined} onClick={() => onSelect(template.template_code)}><div><strong>{template.title}</strong><code>{template.template_code} · r{template.latest_revision}</code><small>{template.sourceTargetCode ?? "来源待补"} · {template.contentStrategy.targetCategory || "未标注品类"}</small></div><span><StatusBadge label={template.published_revision ? "已发布" : "草稿"} tone={template.published_revision ? "success" : "warning"} /></span></button></li>)}</ul>;
}

export function ContentStrategiesPage() {
  const queryClient = useQueryClient();
  const [selectedCode, setSelectedCode] = useState("");
  const [title, setTitle] = useState(""); const [targetCode, setTargetCode] = useState(""); const [sessionCodes, setSessionCodes] = useState<string[]>([]);
  const [category, setCategory] = useState(""); const [moduleTitle, setModuleTitle] = useState("开场建立观看目标"); const [modulePurpose, setModulePurpose] = useState("先说明本场帮助观众完成的选择，再进入内容讲解。"); const [duration, setDuration] = useState(45); const [materialCues, setMaterialCues] = useState("background,promotion_text");
  const targets = useQuery({ queryKey: ["live-research", "watch-targets"], queryFn: liveResearchApi.listWatchTargets });
  const sessions = useQuery({ queryKey: ["live-research", "capture-sessions"], queryFn: liveResearchApi.listCaptureSessions });
  const templates = useQuery({ queryKey: ["live-research", "templates"], queryFn: liveResearchApi.listTemplates });
  const strategies = useMemo(() => (templates.data ?? []).filter((item) => item.templateKind === "content_strategy"), [templates.data]);
  const availableSessions = useMemo(() => (sessions.data ?? []).filter((item) => item.status === "completed" && item.target_code === targetCode), [sessions.data, targetCode]);
  useEffect(() => { if (!targetCode && targets.data?.[0]) setTargetCode(targets.data[0].target_code); }, [targetCode, targets.data]);
  useEffect(() => { setSessionCodes((current) => current.filter((code) => availableSessions.some((session) => session.session_code === code))); }, [availableSessions]);
  const activeCode = strategies.some((item) => item.template_code === selectedCode) ? selectedCode : strategies[0]?.template_code ?? "";
  useEffect(() => { if (selectedCode !== activeCode) setSelectedCode(activeCode); }, [activeCode, selectedCode]);
  const detail = useQuery({ queryKey: ["live-research", "template", activeCode], queryFn: () => liveResearchApi.getTemplate(activeCode), enabled: Boolean(activeCode) });
  const create = useMutation({
    mutationFn: () => liveResearchApi.createContentStrategyTemplate({ title: title.trim(), sourceTargetCode: targetCode, sourceSessionCodes: sessionCodes, targetCategory: category.trim(), moduleTitle: moduleTitle.trim(), modulePurpose: modulePurpose.trim(), moduleDurationSeconds: duration, materialCues: materialCues.split(/[,\n]/).map((item) => item.trim()).filter(Boolean) }),
    onSuccess: (created) => { setSelectedCode(created.template_code); setTitle(""); setSessionCodes([]); void queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] }); },
  });
  const publish = useMutation({ mutationFn: (template: RoomTemplate) => liveResearchApi.publishTemplate(template.template_code, template.latest_revision), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["live-research", "templates"] }); void queryClient.invalidateQueries({ queryKey: ["live-research", "template", activeCode] }); } });
  const active = detail.data ?? strategies.find((item) => item.template_code === activeCode);
  const createAllowed = Boolean(title.trim() && targetCode && sessionCodes.length && category.trim() && moduleTitle.trim() && modulePurpose.trim() && duration > 0);
  const loading = targets.isLoading || sessions.isLoading || templates.isLoading;
  const problem = targets.error ?? sessions.error ?? templates.error;
  return <div className="research-strategy-layout">
    <aside className="wb-section research-template-rail"><SectionHeader kicker="CONTENT-STRATEGY.V2" title="内容策略模板" /><StrategyList templates={strategies} selected={activeCode} onSelect={setSelectedCode} /></aside>
    <main className="research-strategy-main">{loading ? <LoadingBlock label="正在读取来源直播间与模板" /> : problem ? <InlineNotice tone="danger" title="内容策略工作台无法加载">{errorMessage(problem)}</InlineNotice> : <>
      <section className="wb-section"><SectionHeader kicker="CLEANED REFERENCE" title="创建内容策略模板" /><div className="wb-section-body research-strategy-form"><label className="wb-field"><span>模板名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} /></label><label className="wb-field"><span>来源直播间</span><select className="wb-input" value={targetCode} onChange={(event) => setTargetCode(event.target.value)}>{targets.data?.map((target) => <option key={target.target_code} value={target.target_code}>{target.display_name} · {target.target_code}</option>)}</select></label><div className="research-strategy-sessions"><span>已完成来源录屏</span>{availableSessions.length ? availableSessions.map((session) => <label key={session.session_code}><input type="checkbox" checked={sessionCodes.includes(session.session_code)} onChange={() => setSessionCodes((current) => toggle(current, session.session_code))} /><span><strong>{session.title}</strong><small>{session.session_code} · {Math.round(session.duration_seconds)} 秒</small></span></label>) : <small>该直播间暂无已完成录屏。</small>}</div><label className="wb-field"><span>适用品类</span><input className="wb-input" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="例如：葡萄酒、护肤、家电" /></label><div className="research-strategy-module"><label className="wb-field"><span>首个模块</span><input className="wb-input" value={moduleTitle} onChange={(event) => setModuleTitle(event.target.value)} /></label><label className="wb-field"><span>模块目标</span><input className="wb-input" value={modulePurpose} onChange={(event) => setModulePurpose(event.target.value)} /></label><label className="wb-field"><span>预计秒数</span><input className="wb-input" type="number" min="1" value={duration} onChange={(event) => setDuration(Number(event.target.value))} /></label></div><label className="wb-field"><span>素材角色提示</span><input className="wb-input" value={materialCues} onChange={(event) => setMaterialCues(event.target.value)} /></label><InlineNotice tone="info" title="仅内容参考">来源商品事实、价格、活动、品牌和主播身份会被声明为已移除；发布投影固定为 `reference_only`，不会生成外部直播间的麦兔图层。</InlineNotice><button type="button" className="wb-button wb-button-primary" disabled={!createAllowed || create.isPending} onClick={() => create.mutate()}><Sparkles size={15} aria-hidden="true" />创建策略草稿</button>{create.error ? <InlineNotice tone="danger" title="策略草稿创建失败">{errorMessage(create.error)}</InlineNotice> : null}</div></section>
      {active ? <section className="wb-section"><SectionHeader kicker={`${active.template_code} · r${active.latest_revision}`} title={active.title} actions={<><StatusBadge label={active.contentReadiness === "ready" ? "内容可用" : active.contentReadiness} tone={readinessTone(active.contentReadiness)} /><StatusBadge label="reference_only" tone="info" /></>} /><div className="wb-section-body research-strategy-detail"><div><span>来源直播间</span><code>{active.sourceTargetCode}</code></div><div><span>来源场次</span><strong>{active.contentStrategy.programOutline.length ? active.contentStrategy.programOutline.map((item) => item.moduleKey).join(" / ") : "待加载"}</strong></div><div><span>适用品类</span><strong>{active.contentStrategy.targetCategory || "待加载"}</strong></div><div><span>素材提示</span><strong>{active.contentStrategy.materialCues.join(" / ") || "未声明"}</strong></div><section className="research-strategy-outline"><h3>节目结构</h3>{active.contentStrategy.programOutline.map((module) => <article key={module.moduleKey}><code>{module.moduleKey}</code><strong>{module.title}</strong><span>{module.purpose}</span><small>{Math.round((module.endMs - module.startMs) / 1000)} 秒</small></article>)}</section>{active.published_revision ? <InlineNotice title="发布版本已固定"><CheckCircle2 size={14} aria-hidden="true" />该策略可作为内容项目的主模板或次要模板，不能作为可执行布局。</InlineNotice> : <button type="button" className="wb-button wb-button-primary" disabled={publish.isPending || active.contentReadiness !== "ready"} onClick={() => publish.mutate(active)}><Send size={15} aria-hidden="true" />发布内容策略模板</button>}{publish.error ? <InlineNotice tone="danger" title="策略模板发布失败">{errorMessage(publish.error)}</InlineNotice> : null}</div></section> : <section className="wb-section"><EmptyBlock icon={CircleAlert} title="创建或选择内容策略模板" /></section>}</>}</main>
  </div>;
}

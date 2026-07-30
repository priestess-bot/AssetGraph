import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, CopyPlus, Lightbulb, ListChecks, Plus, X } from "lucide-react";
import { contentProjectsApi } from "../content/api";
import { PageHeader, SegmentedTabs } from "../product/components";
import { EmptyBlock, LoadingBlock, StatusBadge } from "../workbench/components";
import { postJson, requestJson } from "../workbench/api";
import { productCopy, productLabel } from "../workbench/productLanguage";

type View = "patterns" | "recommendations";

type TemplateRef = { template_code: string; revision?: number };
type Effect = {
  effect_code: string;
  attribution_report_code: string;
  subject_code: string;
  metric_key: string;
  evidence_level: string;
  status: string;
  note: string;
  effect_payload?: { subject_snapshot?: {
    content?: { theme?: string; story?: string; detailed_design?: string; primary_template_ref?: TemplateRef; secondary_template_refs?: TemplateRef[] };
    script_blocks?: Array<{ block_code: string }>;
    production_variants?: Array<{ material_snapshot_ref?: { asset_codes?: string[] } }>;
  } };
  eligibility_snapshot: { selected_session_count?: number; observed_session_count?: number; recommendation_eligible?: boolean; association_blockers?: string[] };
  revoked_reason?: string;
};

type Report = { report_code: string; metric_key: string; evidence_level: string; session_codes: string[] };
type Candidate = {
  candidate_type: "template" | "material";
  candidate_code: string;
  title: string;
  constraint_score: number;
  content_score: number;
  effect_score: number;
  total_score: number;
  constraint_reasons: string[];
  content_reasons: string[];
  effect_reasons: string[];
  constraint_eligible: boolean;
  effect_signal_used: boolean;
};
type Recommendation = { candidates: Candidate[]; project_effect_hints: Array<{ eligible: boolean; contribution: number; blockers: string[] }> };

const blockerCopy: Record<string, string> = {
  REPORT_NOT_PUBLISHED_DESCRIPTIVE: "分析结果尚未确认",
  EFFECT_SAMPLE_SIZE_BELOW_MINIMUM: "样本场次不足",
  OBSERVED_SAMPLE_SIZE_BELOW_MINIMUM: "有效数据不足",
  METRIC_DEFINITION_NOT_PINNED: "指标口径仍在调整",
  EFFECT_NOT_APPROVED: "规律尚未接受",
  EFFECT_EVIDENCE_NOT_ASSOCIATIONAL: "当前只适合作为观察提示",
};

function score(value: number): number {
  return Math.round(Math.max(0, Math.min(1, value)) * 100);
}

function PatternCreate({ reports, projects, onClose }: { reports: Report[]; projects: Array<{ projectCode: string; title: string }>; onClose: () => void }) {
  const client = useQueryClient();
  const [report, setReport] = useState("");
  const [project, setProject] = useState("");
  const [note, setNote] = useState("");
  const create = useMutation({
    mutationFn: () => postJson("/api/functional-learning/effects", { attribution_report_code: report, subject_type: "content_project", subject_code: project, evidence_level: "descriptive", note }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["learning", "effects"] }); onClose(); },
  });
  return <form className="learning-create-pattern" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
    <header><div><span>归因复盘</span><h2>建立候选规律</h2><p>把一次可解释的表现观察保存下来，经过人工确认后用于后续选材。</p></div><button type="button" className="product-icon-button" aria-label="关闭" onClick={onClose}><X size={18} /></button></header>
    <label className="product-field"><span>依据的表现分析</span><select value={report} onChange={(event) => setReport(event.target.value)} required><option value="">选择指标与样本</option>{reports.map((item) => <option key={item.report_code} value={item.report_code}>{productLabel(item.metric_key, "业务指标")} · {item.session_codes.length} 场数据</option>)}</select></label>
    <label className="product-field"><span>来源内容项目</span><select value={project} onChange={(event) => setProject(event.target.value)} required><option value="">选择项目</option>{projects.map((item) => <option key={item.projectCode} value={item.projectCode}>{item.title}</option>)}</select></label>
    <label className="product-field"><span>观察到的规律</span><textarea rows={5} value={note} onChange={(event) => setNote(event.target.value)} placeholder="例如：商品近景出现后的 30 秒内，点击表现更高；建议在下一版保留这一段结构。" required /></label>
    {create.error ? <small className="product-error-copy">候选规律没有保存，请检查所选分析和项目。</small> : null}
    <footer><button type="button" className="product-secondary-button" onClick={onClose}>取消</button><button type="submit" className="product-primary-button" disabled={!report || !project || !note.trim() || create.isPending}>保存候选规律</button></footer>
  </form>;
}

function PatternCard({ effect, projectTitle }: { effect: Effect; projectTitle: string }) {
  const client = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [reproducing, setReproducing] = useState(false);
  const [hypothesis, setHypothesis] = useState("");
  const refresh = () => void client.invalidateQueries({ queryKey: ["learning", "effects"] });
  const approve = useMutation({ mutationFn: () => postJson(`/api/functional-learning/effects/${effect.effect_code}/approve`, { actor: "functional-operator" }), onSuccess: refresh });
  const revoke = useMutation({ mutationFn: () => postJson(`/api/functional-learning/effects/${effect.effect_code}/revoke`, { actor: "functional-operator", reason }), onSuccess: refresh });
  const reproduce = useMutation({
    mutationFn: () => {
      const snapshot = effect.effect_payload?.subject_snapshot;
      const content = snapshot?.content;
      const templates = [content?.primary_template_ref, ...(content?.secondary_template_refs ?? [])].filter((item): item is TemplateRef => Boolean(item?.template_code));
      return postJson<{ reproduced_project_code: string }>(`/api/functional-learning/effects/${effect.effect_code}/reproduce`, {
        change_hypothesis: hypothesis,
        template_choices: templates.map((item) => ({ source_template_code: item.template_code, action: "preserve" })),
        paragraph_choices: ["theme", "story", "detailed_design"].filter((key) => Boolean(content?.[key as keyof typeof content])).map((key) => ({ field_key: key, action: "preserve" })),
        material_choices: [...new Set(snapshot?.production_variants?.[0]?.material_snapshot_ref?.asset_codes ?? [])].map((code) => ({ source_asset_code: code, action: "preserve" })),
        actor: "functional-operator",
      });
    },
    onSuccess: (result) => { window.history.pushState(null, "", `/console/projects?project=${encodeURIComponent(result.reproduced_project_code)}`); window.dispatchEvent(new PopStateEvent("popstate")); },
  });
  const sample = effect.eligibility_snapshot.observed_session_count ?? effect.eligibility_snapshot.selected_session_count ?? 0;
  const snapshot = effect.effect_payload?.subject_snapshot;
  const scope = [
    snapshot?.content?.primary_template_ref || snapshot?.content?.secondary_template_refs?.length ? "模板结构" : "",
    snapshot?.script_blocks?.length ? "剧本话术" : "",
    snapshot?.production_variants?.[0]?.material_snapshot_ref?.asset_codes?.length ? "素材组合" : "",
  ].filter(Boolean);
  return <article className="learning-pattern-card">
    <header><div><span className="product-section-kicker">{projectTitle}</span><h3>{effect.note || "待补充规律说明"}</h3></div><StatusBadge label={effect.status === "approved" ? "已接受" : effect.status === "revoked" ? "已忽略" : "待判断"} tone={effect.status === "approved" ? "success" : effect.status === "revoked" ? "neutral" : "warning"} /></header>
    <div className="learning-pattern-facts">
      <span><small>观察指标</small><strong>{productLabel(effect.metric_key, "业务表现")}</strong></span>
      <span><small>有效样本</small><strong>{sample} 场</strong></span>
      <span><small>证据强度</small><strong>{effect.evidence_level === "associational" ? "有关联迹象" : "描述性观察"}</strong></span>
      <span><small>可复用范围</small><strong>{scope.join("、") || "内容策略"}</strong></span>
    </div>
    <div className={`learning-pattern-impact ${effect.eligibility_snapshot.recommendation_eligible ? "eligible" : "limited"}`}><Lightbulb size={17} /><span><strong>{effect.eligibility_snapshot.recommendation_eligible ? "可用于后续内容建议" : "暂不自动影响推荐"}</strong><small>{effect.eligibility_snapshot.association_blockers?.map((item) => blockerCopy[item] ?? "需要更多证据").join(" · ") || "运营人员仍需结合业务判断"}</small></span></div>
    {effect.status === "candidate" ? <footer><button className="product-primary-button" type="button" onClick={() => approve.mutate()} disabled={approve.isPending}><Check size={16} />接受规律</button><button className="product-secondary-button" type="button" onClick={() => setRejecting(true)}><X size={16} />忽略</button><a className="product-secondary-button" href={`/projects?project=${encodeURIComponent(effect.subject_code)}`}>查看来源<ArrowRight size={15} /></a></footer> : null}
    {effect.status === "approved" ? <footer><button className="product-primary-button" type="button" onClick={() => setReproducing(true)}><CopyPlus size={16} />用于新项目</button><a className="product-secondary-button" href={`/projects?project=${encodeURIComponent(effect.subject_code)}`}>查看来源<ArrowRight size={15} /></a></footer> : null}
    {effect.status === "revoked" ? <p className="learning-pattern-reason">忽略原因：{effect.revoked_reason || "不适合当前业务"}</p> : null}
    {rejecting ? <form className="learning-inline-action" onSubmit={(event) => { event.preventDefault(); revoke.mutate(); }}><label className="product-field"><span>为什么不采用</span><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="记录判断，避免以后重复评估" required /></label><button className="product-secondary-button" type="button" onClick={() => setRejecting(false)}>取消</button><button className="product-primary-button" disabled={!reason.trim() || revoke.isPending}>确认忽略</button></form> : null}
    {reproducing ? <form className="learning-inline-action" onSubmit={(event) => { event.preventDefault(); reproduce.mutate(); }}><label className="product-field"><span>这次准备验证什么</span><input value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} placeholder="保留有效部分，并说明这次要改变的变量" required /></label><button className="product-secondary-button" type="button" onClick={() => setReproducing(false)}>取消</button><button className="product-primary-button" disabled={!hypothesis.trim() || reproduce.isPending}>创建项目草稿</button></form> : null}
    {approve.error || revoke.error || reproduce.error ? <small className="product-error-copy">操作没有完成，请稍后重试。</small> : null}
  </article>;
}

function PatternLibrary() {
  const [creating, setCreating] = useState(false);
  const effects = useQuery({ queryKey: ["learning", "effects"], queryFn: () => requestJson<Effect[]>("/api/functional-learning/effects") });
  const reports = useQuery({ queryKey: ["operations", "reports"], queryFn: () => requestJson<Report[]>("/api/functional-operations/attribution-reports") });
  const projects = useQuery({ queryKey: ["projects"], queryFn: contentProjectsApi.list });
  if (effects.isLoading || reports.isLoading || projects.isLoading) return <LoadingBlock label="正在读取效果规律" />;
  const projectTitle = (code: string) => projects.data?.find((item) => item.projectCode === code)?.title ?? "来源内容项目";
  return <div className="learning-product-content">
    <div className="learning-toolbar"><div><strong>已沉淀 {effects.data?.length ?? 0} 条规律</strong><span>候选规律只有经过人工接受，才会进入项目建议。</span></div><button className="product-primary-button" type="button" onClick={() => setCreating(true)}><Plus size={16} />建立候选规律</button></div>
    {creating ? <PatternCreate reports={reports.data ?? []} projects={projects.data ?? []} onClose={() => setCreating(false)} /> : null}
    {effects.data?.length ? <div className="learning-pattern-grid">{effects.data.map((item) => <PatternCard key={item.effect_code} effect={item} projectTitle={projectTitle(item.subject_code)} />)}</div> : <EmptyBlock icon={Lightbulb} title="还没有候选规律" detail="先在运营页完成多场次表现分析，再将值得复用的观察沉淀到这里。" />}
  </div>;
}

function Recommendations() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: contentProjectsApi.list });
  const [projectCode, setProjectCode] = useState("");
  const recommendations = useQuery({ queryKey: ["learning", "recommendations", projectCode], queryFn: () => requestJson<Recommendation>(`/api/functional-learning/recommendations/${encodeURIComponent(projectCode)}`), enabled: Boolean(projectCode) });
  return <div className="learning-product-content">
    <section className="product-surface learning-recommendation-head"><div><span className="product-section-kicker">项目辅助选材</span><h2>查看模板与素材建议</h2><p>建议综合当前项目内容匹配、硬约束和已接受的历史规律，最终选择仍由运营人员确认。</p></div><label className="product-field"><span>内容项目</span><select value={projectCode} onChange={(event) => setProjectCode(event.target.value)}><option value="">选择项目</option>{projects.data?.map((item) => <option key={item.projectCode} value={item.projectCode}>{item.title}</option>)}</select></label></section>
    {!projectCode ? <EmptyBlock icon={ListChecks} title="选择一个内容项目" detail="系统会分别展示模板与素材的匹配理由。" /> : recommendations.isLoading ? <LoadingBlock label="正在生成建议" /> : recommendations.data?.candidates.length ? <div className="learning-candidate-grid">{recommendations.data.candidates.map((item) => <article key={`${item.candidate_type}:${item.candidate_code}`} className={!item.constraint_eligible ? "ineligible" : ""}>
      <header><div><span className="product-section-kicker">{item.candidate_type === "template" ? "直播模板" : "素材"}</span><h3>{item.title}</h3></div><strong>{score(item.total_score)}<small>综合分</small></strong></header>
      <div className="learning-score-bars"><span><label>内容匹配</label><i><b style={{ width: `${score(item.content_score)}%` }} /></i><strong>{score(item.content_score)}</strong></span><span><label>约束适配</label><i><b style={{ width: `${score(item.constraint_score)}%` }} /></i><strong>{score(item.constraint_score)}</strong></span><span><label>历史表现</label><i><b style={{ width: `${score(item.effect_score)}%` }} /></i><strong>{score(item.effect_score)}</strong></span></div>
      <ul>{[...item.constraint_reasons, ...item.content_reasons, ...item.effect_reasons].slice(0, 4).map((reason, index) => <li key={index}>{productCopy(reason, "符合当前项目需要")}</li>)}</ul>
      <footer><StatusBadge label={!item.constraint_eligible ? "不满足硬约束" : item.effect_signal_used ? "有历史表现参考" : "按内容推荐"} tone={!item.constraint_eligible ? "warning" : "success"} /><a href={`/projects?project=${encodeURIComponent(projectCode)}`}>回到项目选择<ArrowRight size={14} /></a></footer>
    </article>)}</div> : <EmptyBlock icon={ListChecks} title="当前没有合适建议" detail="可以先补充项目目标、模板或素材约束。" />}
  </div>;
}

export function LearningProductPage() {
  const [view, setView] = useState<View>("patterns");
  const effects = useQuery({ queryKey: ["learning", "effects"], queryFn: () => requestJson<Effect[]>("/api/functional-learning/effects") });
  const counts = useMemo(() => ({ patterns: effects.data?.length ?? 0 }), [effects.data]);
  return <div className="product-page learning-product-page">
    <PageHeader eyebrow="效果驱动再生产" title="效果学习" description="把多场次表现沉淀为可解释的内容规律，并在新项目中作为人工可控的模板与素材建议。" />
    <SegmentedTabs value={view} onValueChange={(value) => setView(value as View)} items={[{ value: "patterns", label: "规律库", count: counts.patterns }, { value: "recommendations", label: "项目建议" }]} />
    {view === "patterns" ? <PatternLibrary /> : <Recommendations />}
  </div>;
}

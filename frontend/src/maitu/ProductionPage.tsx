import { type FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ClipboardCheck,
  FilePenLine,
  GitBranch,
  ListChecks,
  LoaderCircle,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, Metric, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { maituApi } from "./api";
import { DEMO_ANALYSIS_CONFLICTS, DEMO_FACT_CARDS, DEMO_INVENTORY_JOBS, DEMO_PLAN_REVISIONS, DEMO_REQUIREMENTS, DEMO_RUNS } from "./demoData";
import { RUN_STATUS_META, type PlanRevision, type ProductFactCard, type ProductionRequirement, type ProductionRun, type ReferenceTemplatePin, type RequirementDecisionKind } from "./types";

function initialRunCode(): string {
  return new URLSearchParams(window.location.search).get("run")?.trim() ?? "";
}

export function initialReferenceTemplatePin(search = window.location.search): ReferenceTemplatePin | undefined {
  const params = new URLSearchParams(search);
  const code = params.get("reference_template_code")?.trim();
  if (!code) return undefined;
  const revisionValue = params.get("reference_template_revision_number")?.trim();
  const fingerprint = params.get("reference_template_projection_fingerprint")?.trim();
  const revision = revisionValue ? Number(revisionValue) : undefined;
  if (!revision || !Number.isInteger(revision) || revision < 1 || !fingerprint || !/^[0-9a-f]{64}$/.test(fingerprint)) return undefined;
  return {
    reference_template_code: code,
    reference_template_revision_number: revision,
    reference_template_projection_fingerprint: fingerprint,
  };
}

function clearReferenceTemplatePin() {
  const url = new URL(window.location.href);
  url.searchParams.delete("reference_template_code");
  url.searchParams.delete("reference_template_revision_number");
  url.searchParams.delete("reference_template_projection_fingerprint");
  window.history.replaceState(null, "", url);
}

function writeRunCode(runCode: string) {
  const url = new URL(window.location.href);
  if (runCode) url.searchParams.set("run", runCode);
  else url.searchParams.delete("run");
  window.history.replaceState(null, "", url);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未能完成";
}

function RunStatus({ run }: { run: ProductionRun }) {
  const meta = RUN_STATUS_META[run.status] ?? { label: run.status, tone: "neutral" as const };
  return <StatusBadge label={meta.label} tone={meta.tone} />;
}

function RunCreateForm({ cards, snapshotCodes, referenceTemplate, onCreated }: { cards: ProductFactCard[]; snapshotCodes: string[]; referenceTemplate?: ReferenceTemplatePin; onCreated: (run: ProductionRun) => void }) {
  const [title, setTitle] = useState("夏日朋友聚餐选酒");
  const [topic, setTopic] = useState("不讲复杂术语，帮聚餐人群快速选一瓶清爽红酒");
  const [factCardCode, setFactCardCode] = useState(cards.find((item) => item.approved_version || item.status === "approved")?.fact_card_code ?? "");
  const [snapshotCode, setSnapshotCode] = useState(snapshotCodes[0] ?? "");
  const [roomId, setRoomId] = useState("");
  const [duration, setDuration] = useState(1);
  const [buildMode, setBuildMode] = useState("draft_with_placeholders");
  const mutation = useMutation({ mutationFn: maituApi.createRun, onSuccess: onCreated });

  useEffect(() => {
    if (!factCardCode) setFactCardCode(cards.find((item) => item.approved_version || item.status === "approved")?.fact_card_code ?? "");
  }, [cards, factCardCode]);
  useEffect(() => {
    if (!snapshotCode) setSnapshotCode(snapshotCodes[0] ?? "");
  }, [snapshotCode, snapshotCodes]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || !factCardCode || !snapshotCode) return;
    mutation.mutate({
      title: title.trim(),
      topic: topic.trim() || undefined,
      fact_card_code: factCardCode,
      inventory_snapshot_code: snapshotCode,
      target_live_room_id: roomId.trim() || undefined,
      target_duration_minutes: duration,
      build_mode: buildMode,
      ...referenceTemplate,
    });
  };

  return (
    <form className="wb-section-body maitu-create-run" onSubmit={submit}>
      {referenceTemplate ? <InlineNotice title="已固定发布参考模板">{referenceTemplate.reference_template_code}{referenceTemplate.reference_template_revision_number ? ` · r${referenceTemplate.reference_template_revision_number}` : ""}{referenceTemplate.reference_template_projection_fingerprint ? ` · ${referenceTemplate.reference_template_projection_fingerprint.slice(0, 12)}...` : ""}。该版本仅提供近似结构参考。</InlineNotice> : null}
      <div className="wb-form-grid">
        <div className="wb-field"><label htmlFor="run-title">运行名称</label><input id="run-title" className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} /></div>
        <div className="wb-field"><label htmlFor="run-room">空白草稿直播间 ID</label><input id="run-room" className="wb-input" value={roomId} onChange={(event) => setRoomId(event.target.value)} placeholder="先在麦兔新建空白草稿，可稍后绑定" /></div>
        <div className="wb-field wide"><label htmlFor="run-topic">主题 / 内容需求</label><textarea id="run-topic" className="wb-textarea" value={topic} onChange={(event) => setTopic(event.target.value)} /></div>
        <div className="wb-field"><label htmlFor="run-facts">批准的事实版本</label><select id="run-facts" className="wb-select" value={factCardCode} onChange={(event) => setFactCardCode(event.target.value)}><option value="">请选择</option>{cards.filter((item) => item.approved_version || item.status === "approved").map((item) => <option value={item.fact_card_code} key={item.fact_card_code}>{item.title} · v{item.approved_version ?? item.current_version}</option>)}</select></div>
        <div className="wb-field"><label htmlFor="run-snapshot">素材快照</label><select id="run-snapshot" className="wb-select" value={snapshotCode} onChange={(event) => setSnapshotCode(event.target.value)}><option value="">请选择</option>{snapshotCodes.map((code) => <option value={code} key={code}>{code}</option>)}</select></div>
        <div className="wb-field"><label htmlFor="run-duration">目标时长（分钟）</label><input id="run-duration" className="wb-input" type="number" min={1} max={480} value={duration} onChange={(event) => setDuration(Number(event.target.value))} /></div>
        <div className="wb-field"><label htmlFor="run-mode">搭建策略</label><select id="run-mode" className="wb-select" value={buildMode} onChange={(event) => setBuildMode(event.target.value)}><option value="draft_with_placeholders">缺口保留占位</option><option value="strict">严格完整素材</option></select></div>
      </div>
      {mutation.error ? <div className="maitu-form-notice"><InlineNotice tone="danger" title="无法创建运行">{errorMessage(mutation.error)}</InlineNotice></div> : null}
      {!cards.some((item) => item.approved_version || item.status === "approved") || !snapshotCodes.length ? <div className="maitu-form-notice"><InlineNotice tone="warning" title="生产输入尚未就绪">至少需要一个已批准事实卡版本和一个成功的素材快照。</InlineNotice></div> : null}
      <div className="wb-form-actions"><button className="wb-button wb-button-primary" type="submit" disabled={mutation.isPending || !title.trim() || !factCardCode || !snapshotCode}>{mutation.isPending ? <LoaderCircle className="wb-spin" size={15} aria-hidden="true" /> : <Sparkles size={15} aria-hidden="true" />}创建主题运行</button></div>
    </form>
  );
}

function RunList({ runs, selected, onSelect }: { runs: ProductionRun[]; selected?: string; onSelect: (code: string) => void }) {
  if (!runs.length) return <EmptyBlock icon={GitBranch} title="尚无生产运行" detail="创建主题运行后，系统会固定事实版本和素材快照。" />;
  return <ul className="maitu-run-list wb-list">{runs.map((run) => <li key={run.run_code}><button type="button" className={run.run_code === selected ? "active" : undefined} onClick={() => onSelect(run.run_code)}><span><strong>{run.title}</strong><small>{run.run_code}</small></span><RunStatus run={run} /></button></li>)}</ul>;
}

function TargetRoomEditor({ run, onChanged }: { run: ProductionRun; onChanged: () => void }) {
  const [roomId, setRoomId] = useState(run.target_live_room_id ?? "");
  useEffect(() => setRoomId(run.target_live_room_id ?? ""), [run.run_code, run.target_live_room_id]);
  const mutation = useMutation({
    mutationFn: () => maituApi.updateRunTargetRoom(run.run_code, roomId.trim()),
    onSuccess: onChanged,
  });
  const locked = ["planning", "execution_queued", "executing", "completed"].includes(run.status);
  const unchanged = roomId.trim() === (run.target_live_room_id ?? "");
  return <div className="maitu-target-room-editor"><div className="wb-field"><label htmlFor="bound-target-room">空白草稿直播间 ID</label><input id="bound-target-room" className="wb-input" value={roomId} onChange={(event) => setRoomId(event.target.value)} disabled={locked} placeholder="麦兔中已新建且未配置的草稿房间" /></div><button type="button" className="wb-button" disabled={locked || !roomId.trim() || unchanged || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? <LoaderCircle className="wb-spin" size={14} aria-hidden="true" /> : <Save size={14} aria-hidden="true" />}绑定房间</button>{run.current_plan_revision > 0 && !unchanged ? <small>保存后必须 Replan，旧计划不会写入新房间。</small> : <small>系统不会创建直播间；preflight 会验证它是单场景、无素材的空白草稿。</small>}{mutation.error ? <InlineNotice tone="danger" title="无法绑定目标房间">{errorMessage(mutation.error)}</InlineNotice> : null}</div>;
}

function RunProgress({ run, currentPlan }: { run: ProductionRun; currentPlan?: PlanRevision }) {
  const preflightPassed = run.preflight?.status === "passed" || run.status === "preflight_passed" || ["execution_queued", "executing", "completed"].includes(run.status);
  const steps = [
    { label: "输入已固定", done: Boolean(run.fact_card_code && run.inventory_snapshot_code), current: run.status === "draft" },
    { label: "需求已规划", done: run.current_plan_revision > 0, current: run.status === "planning" },
    { label: "人工决策", done: run.open_requirement_count === 0 || Boolean(currentPlan?.can_execute), current: run.status === "blocked" },
    { label: "只读预检", done: preflightPassed, current: run.status === "ready" },
    { label: "二次草稿", done: run.status === "completed", current: ["execution_queued", "executing"].includes(run.status) },
  ];
  return <ol className="maitu-run-progress">{steps.map((step, index) => <li key={step.label} className={step.done ? "done" : step.current ? "current" : "pending"}><span>{step.done ? <Check size={13} strokeWidth={3} aria-hidden="true" /> : index + 1}</span><strong>{step.label}</strong></li>)}</ol>;
}

function RequirementItem({ runCode, requirement, onChanged }: { runCode: string; requirement: ProductionRequirement; onChanged: () => void }) {
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [reason, setReason] = useState(requirement.decision?.reason ?? "");
  const mutation = useMutation({
    mutationFn: (decision: RequirementDecisionKind) => {
      const candidate = requirement.candidates[candidateIndex];
      return maituApi.decideRequirement(runCode, requirement.requirement_code, {
        decision,
        selected_asset_code: decision === "selected" ? candidate?.asset_code : undefined,
        selected_material_key: decision === "selected" ? candidate?.material_key : undefined,
        reason: reason.trim() || (decision === "selected" ? "人工确认候选与场景需求匹配" : decision === "deferred" ? "延后补充，不纳入本轮草稿" : "本轮明确不使用该可选素材"),
      });
    },
    onSuccess: onChanged,
  });
  const priorityLabel = { critical: "关键", required: "必需", optional: "可选" }[requirement.priority];
  const selectedCandidate = requirement.candidates[candidateIndex];

  return <article className="maitu-requirement">
    <div className="maitu-requirement-head"><div><span>{requirement.scene_name}</span><strong>{requirement.label}</strong><small>{requirement.description ?? requirement.need_type}</small></div><div><StatusBadge label={priorityLabel} tone={requirement.priority === "critical" ? "danger" : requirement.priority === "required" ? "warning" : "neutral"} />{requirement.decision ? <StatusBadge label={requirement.decision.decision === "selected" ? "已选素材" : requirement.decision.decision === "deferred" ? "已延后" : "已豁免"} tone={requirement.decision.decision === "selected" ? "success" : "warning"} /> : null}</div></div>
    <div className="maitu-requirement-controls">
      <div className="wb-field"><label htmlFor={`candidate-${requirement.requirement_code}`}>候选素材</label><select id={`candidate-${requirement.requirement_code}`} className="wb-select" value={candidateIndex} onChange={(event) => setCandidateIndex(Number(event.target.value))} disabled={!requirement.candidates.length}>{requirement.candidates.length ? requirement.candidates.map((candidate, index) => <option key={candidate.asset_code ?? candidate.material_key ?? index} value={index}>{candidate.title}{candidate.match_score !== undefined ? ` · ${Math.round(candidate.match_score * 100)}%` : ""}</option>) : <option>无候选</option>}</select></div>
      <div className="wb-field"><label htmlFor={`reason-${requirement.requirement_code}`}>决策理由</label><input id={`reason-${requirement.requirement_code}`} className="wb-input" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="记录为什么选择、延后或豁免" /></div>
    </div>
    {selectedCandidate?.analysis_source ? <span className="maitu-analysis-source">分析策略：{selectedCandidate.analysis_source}</span> : null}
    {mutation.error ? <InlineNotice tone="danger" title="需求决策保存失败">{errorMessage(mutation.error)}</InlineNotice> : null}
    <div className="maitu-requirement-actions"><button type="button" className="wb-button wb-button-primary" disabled={!selectedCandidate || mutation.isPending} onClick={() => mutation.mutate("selected")}><Check size={14} aria-hidden="true" />采用候选</button><button type="button" className="wb-button" disabled={mutation.isPending} onClick={() => mutation.mutate("deferred")}>延后</button><button type="button" className="wb-button" disabled={requirement.priority === "critical" || mutation.isPending} onClick={() => mutation.mutate("waived")}>本轮豁免</button></div>
  </article>;
}

function PlanPanel({ run, revisions, snapshotCodes, onChanged }: { run: ProductionRun; revisions: PlanRevision[]; snapshotCodes: string[]; onChanged: () => void }) {
  const [reason, setReason] = useState("根据最新人工素材决策重新规划");
  const [snapshotCode, setSnapshotCode] = useState(run.inventory_snapshot_code);
  const snapshotOptions = [run.inventory_snapshot_code, ...snapshotCodes.filter((code) => code !== run.inventory_snapshot_code)];
  const current = revisions.find((item) => item.revision === run.current_plan_revision) ?? revisions[0];
  const initialMutation = useMutation({ mutationFn: () => maituApi.createInitialPlan(run.run_code), onSuccess: onChanged });
  const replanMutation = useMutation({
    mutationFn: () => maituApi.replan(run.run_code, {
      reason: reason.trim(),
      expected_plan_revision: run.current_plan_revision,
      ...(snapshotCode !== run.inventory_snapshot_code ? { inventory_snapshot_code: snapshotCode } : {}),
    }),
    onSuccess: onChanged,
  });
  const activeError = initialMutation.error ?? replanMutation.error;

  useEffect(() => setSnapshotCode(run.inventory_snapshot_code), [run.run_code, run.inventory_snapshot_code]);

  return <section className="wb-section">
    <SectionHeader kicker="VERSIONED PLAN" title="计划修订" actions={run.current_plan_revision === 0 ? <button type="button" className="wb-button wb-button-primary" onClick={() => initialMutation.mutate()} disabled={initialMutation.isPending}><Sparkles size={15} aria-hidden="true" />生成初始计划</button> : <StatusBadge label={`当前 r${run.current_plan_revision}`} tone={current?.can_execute ? "success" : "warning"} />} />
    <div className="wb-section-body">
      {current ? <>
        <div className="wb-metrics maitu-plan-metrics"><Metric label="场景" value={current.scene_count} /><Metric label="已选素材" value={current.selected_count} /><Metric label="缺口" value={current.missing_count} /><Metric label="执行门禁" value={current.can_execute ? "可预检" : "阻断"} /></div>
        <div className="maitu-plan-fingerprint"><span>输入指纹</span><code title={current.input_fingerprint}>{current.input_fingerprint?.slice(0, 18) ?? "--"}</code><span>BuildPlan</span><code>{current.build_plan_code ?? "尚未生成"}</code></div>
        {current.scenes.length ? <div className="maitu-generated-scenes"><div className="maitu-generated-scenes-head"><strong>场景规划</strong>{current.generation ? <span>{current.generation.strategy_revision} · {current.generation.prompt_version}</span> : null}</div><ol>{current.scenes.map((scene, index) => <li key={`${scene.scene_name}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><div><strong>{scene.scene_name}</strong><time>{scene.duration_seconds}s</time></div><small>{scene.scene_goal}</small><p>{scene.script}</p>{scene.composition_intent ? <em>{scene.composition_intent}</em> : null}{scene.material_intents.length ? <div className="maitu-material-intents">{scene.material_intents.map((intent) => <span key={intent}>{intent}</span>)}</div> : null}</div></li>)}</ol></div> : null}
        {current.gaps.length ? <ul className="maitu-gap-list">{current.gaps.map((gap) => <li key={`${gap.code}-${gap.requirement_code ?? ""}`} className={`severity-${gap.severity}`}>{gap.severity === "critical" ? <XCircle size={15} aria-hidden="true" /> : <AlertTriangle size={15} aria-hidden="true" />}<div><strong>{gap.message}</strong><small>{gap.code}{gap.requirement_code ? ` · ${gap.requirement_code}` : ""}</small></div></li>)}</ul> : <InlineNotice tone="success" title="当前计划无素材缺口">可以进入只读 preflight。</InlineNotice>}
      </> : <EmptyBlock icon={GitBranch} title="尚无计划修订" detail="初始计划会生成场景、素材需求、缺口报告、布局和 BuildPlan。" />}
      {run.current_plan_revision > 0 ? <div className="maitu-replan"><div className="wb-field"><label htmlFor="replan-snapshot">Replan 素材快照</label><select id="replan-snapshot" className="wb-select" value={snapshotCode} onChange={(event) => setSnapshotCode(event.target.value)}>{snapshotOptions.map((code) => <option value={code} key={code}>{code}{code === run.inventory_snapshot_code ? " · 当前" : ""}</option>)}</select></div><div className="wb-field"><label htmlFor="replan-reason">重新规划原因</label><input id="replan-reason" className="wb-input" value={reason} onChange={(event) => setReason(event.target.value)} /></div><button type="button" className="wb-button" disabled={!reason.trim() || !snapshotCode || replanMutation.isPending} onClick={() => replanMutation.mutate()}><RotateCcw className={replanMutation.isPending ? "wb-spin" : ""} size={15} aria-hidden="true" />Replan</button></div> : null}
      {activeError ? <InlineNotice tone="danger" title="计划操作失败">{errorMessage(activeError)}。旧 revision 不会被覆盖。</InlineNotice> : null}
      {revisions.length > 1 ? <div className="maitu-revision-history"><strong>历史修订</strong>{revisions.map((revision) => <span key={revision.revision}><code>r{revision.revision}</code><StatusBadge label={revision.status === "superseded" ? "已替代" : revision.status === "ready" ? "就绪" : "阻断"} tone={revision.status === "ready" ? "success" : "neutral"} />{formatDate(revision.created_at)}</span>)}</div> : null}
    </div>
  </section>;
}

function GatePanel({ run, currentPlan, criticalConflictCount, onChanged }: { run: ProductionRun; currentPlan?: PlanRevision; criticalConflictCount: number; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const [localPreflight, setLocalPreflight] = useState(run.preflight);
  const [localExecution, setLocalExecution] = useState(run.draft_execution);
  useEffect(() => setLocalPreflight(run.preflight), [run.preflight]);
  useEffect(() => setLocalExecution(run.draft_execution), [run.draft_execution]);
  const preflightMutation = useMutation({
    mutationFn: () => maituApi.preflight(run.run_code, run.current_plan_revision),
    onSuccess: (value) => { setLocalPreflight(value); onChanged(); },
  });
  const executeMutation = useMutation({
    mutationFn: () => maituApi.createDraftExecution(run.run_code, run.current_plan_revision),
    onSuccess: (value) => {
      setLocalExecution(value);
      void queryClient.invalidateQueries({ queryKey: ["maitu", "runs"] });
      onChanged();
    },
  });
  const canPreflight = Boolean(currentPlan?.can_execute && run.current_plan_revision > 0 && criticalConflictCount === 0);
  const canExecute = localPreflight?.status === "passed" && localPreflight.expected_plan_revision === run.current_plan_revision && criticalConflictCount === 0 && !["queued", "running", "succeeded"].includes(localExecution?.status ?? "");

  return <section className="wb-section">
    <SectionHeader kicker="SAFETY GATE" title="预检与二次草稿" />
    <div className="wb-section-body">
      {criticalConflictCount ? <InlineNotice tone="danger" title="选中素材存在关键分析冲突">先在 Gemini 回填页解决 {criticalConflictCount} 个关键冲突；非关键或未选素材不阻断。</InlineNotice> : null}
      <div className="maitu-gate-flow">
        <div className={canPreflight || localPreflight ? "gate-ready" : ""}><span><ClipboardCheck size={18} aria-hidden="true" /></span><div><strong>只读 preflight</strong><small>校验登录态、直播间、场景、素材与脚本面板，不做写操作。</small></div><button type="button" className="wb-button" disabled={!canPreflight || preflightMutation.isPending} onClick={() => preflightMutation.mutate()}>{preflightMutation.isPending ? <LoaderCircle className="wb-spin" size={14} aria-hidden="true" /> : <ShieldCheck size={14} aria-hidden="true" />}执行预检</button></div>
        <ArrowRight size={17} aria-hidden="true" />
        <div className={canExecute || localExecution ? "gate-ready" : ""}><span><FilePenLine size={18} aria-hidden="true" /></span><div><strong>写入二次草稿</strong><small>仅写麦兔草稿并保存证据，永远不会触发正式开播。</small></div><button type="button" className="wb-button wb-button-primary" disabled={!canExecute || executeMutation.isPending} onClick={() => executeMutation.mutate()}>{executeMutation.isPending ? <LoaderCircle className="wb-spin" size={14} aria-hidden="true" /> : <FilePenLine size={14} aria-hidden="true" />}写入草稿</button></div>
      </div>
      {localPreflight ? <div className="maitu-checks"><div className="maitu-checks-title"><strong>Preflight r{localPreflight.expected_plan_revision}</strong><StatusBadge label={localPreflight.status === "passed" ? "全部通过" : "存在阻断"} tone={localPreflight.status === "passed" ? "success" : "danger"} /></div><ul>{localPreflight.checks.map((check) => <li key={check.check_code}>{check.status === "passed" ? <CheckCircle2 size={15} aria-hidden="true" /> : check.status === "warning" ? <AlertTriangle size={15} aria-hidden="true" /> : <XCircle size={15} aria-hidden="true" />}<span><strong>{check.label}</strong>{check.detail ? <small>{check.detail}</small> : null}</span></li>)}</ul></div> : null}
      {localExecution ? <InlineNotice tone={localExecution.status === "failed" ? "danger" : localExecution.status === "succeeded" ? "success" : "info"} title={`草稿任务 ${localExecution.execution_job_code}`}>{localExecution.result_summary ?? `当前状态：${localExecution.status}`}。ready_for_go_live=false</InlineNotice> : null}
      {preflightMutation.error || executeMutation.error ? <InlineNotice tone="danger" title="门禁操作未完成">{errorMessage(preflightMutation.error ?? executeMutation.error)}</InlineNotice> : null}
    </div>
  </section>;
}

export function ProductionPage() {
  const queryClient = useQueryClient();
  const [referenceTemplate, setReferenceTemplate] = useState<ReferenceTemplatePin | undefined>(initialReferenceTemplatePin);
  const [showCreate, setShowCreate] = useState(() => Boolean(initialReferenceTemplatePin()));
  const [selectedRunCode, setSelectedRunCode] = useState(initialRunCode);
  const factsQuery = useQuery({ queryKey: ["maitu", "fact-cards"], queryFn: maituApi.listFactCards });
  const inventoryQuery = useQuery({ queryKey: ["maitu", "inventory-jobs"], queryFn: maituApi.listInventoryJobs });
  const runsQuery = useQuery({ queryKey: ["maitu", "runs"], queryFn: maituApi.listRuns, refetchInterval: (query) => query.state.data?.some((run) => ["planning", "execution_queued", "executing"].includes(run.status)) ? 1500 : false });
  const demoMode = factsQuery.isError && inventoryQuery.isError && runsQuery.isError;
  const cards = factsQuery.data ?? (demoMode ? DEMO_FACT_CARDS : []);
  const inventoryJobs = inventoryQuery.data ?? (demoMode ? DEMO_INVENTORY_JOBS : []);
  const runs = runsQuery.data ?? (demoMode ? DEMO_RUNS : []);

  useEffect(() => {
    if (!selectedRunCode && runs[0]) {
      setSelectedRunCode(runs[0].run_code);
      writeRunCode(runs[0].run_code);
    }
  }, [runs, selectedRunCode]);

  const selectedListRun = runs.find((run) => run.run_code === selectedRunCode);
  const runQuery = useQuery({ queryKey: ["maitu", "run", selectedRunCode], queryFn: () => maituApi.getRun(selectedRunCode), enabled: Boolean(selectedRunCode) && !demoMode });
  const run = runQuery.data ?? selectedListRun;
  const requirementsQuery = useQuery({ queryKey: ["maitu", "requirements", selectedRunCode], queryFn: () => maituApi.listRequirements(selectedRunCode), enabled: Boolean(selectedRunCode) && !demoMode });
  const revisionsQuery = useQuery({ queryKey: ["maitu", "plan-revisions", selectedRunCode], queryFn: () => maituApi.listPlanRevisions(selectedRunCode), enabled: Boolean(selectedRunCode) && !demoMode });
  const conflictsQuery = useQuery({ queryKey: ["maitu", "analysis-conflicts", selectedRunCode], queryFn: () => maituApi.listConflicts(selectedRunCode), enabled: Boolean(selectedRunCode) && !demoMode, retry: false });
  const requirements = requirementsQuery.data ?? (demoMode && run ? DEMO_REQUIREMENTS : []);
  const revisions = revisionsQuery.data ?? (demoMode && run ? DEMO_PLAN_REVISIONS : []);
  const conflicts = conflictsQuery.data ?? (demoMode && run ? DEMO_ANALYSIS_CONFLICTS : []);
  const criticalConflicts = conflicts.filter((item) => item.severity === "critical" && !item.resolution).length || run?.critical_conflict_count || 0;
  const currentPlan = revisions.find((item) => item.revision === run?.current_plan_revision) ?? revisions[0];
  const snapshotCodes = inventoryJobs.flatMap((job) => job.snapshot?.snapshot_code && job.snapshot.quality === "complete" ? [job.snapshot.snapshot_code] : []);

  const selectRun = (code: string) => { setSelectedRunCode(code); writeRunCode(code); };
  const refreshRun = () => {
    void queryClient.invalidateQueries({ queryKey: ["maitu", "runs"] });
    void queryClient.invalidateQueries({ queryKey: ["maitu", "run", selectedRunCode] });
    void queryClient.invalidateQueries({ queryKey: ["maitu", "requirements", selectedRunCode] });
    void queryClient.invalidateQueries({ queryKey: ["maitu", "plan-revisions", selectedRunCode] });
  };
  const created = (createdRun: ProductionRun) => {
    queryClient.setQueryData<ProductionRun[]>(["maitu", "runs"], (current) => [createdRun, ...(current ?? [])]);
    selectRun(createdRun.run_code);
    setShowCreate(false);
    setReferenceTemplate(undefined);
    clearReferenceTemplatePin();
  };

  return <div>
    {demoMode ? <InlineNotice tone="warning" title="当前展示完整流程演示数据">后端工作台 API 可用后会自动读取真实事实版本、素材快照、计划修订与草稿任务。</InlineNotice> : null}
    <div className="wb-grid wb-grid-aside maitu-production-grid">
      <aside className="wb-section maitu-run-rail">
        <SectionHeader kicker="PRODUCTION RUNS" title="主题运行" actions={<button type="button" className="wb-icon-button" onClick={() => setShowCreate((value) => !value)} title="新建主题运行"><Plus size={17} aria-hidden="true" /></button>} />
        {runsQuery.isLoading ? <LoadingBlock /> : <RunList runs={runs} selected={selectedRunCode} onSelect={selectRun} />}
      </aside>
      <div className="maitu-production-main">
        {showCreate ? <section className="wb-section"><SectionHeader kicker="NEW RUN" title="创建主题生产运行" /><RunCreateForm cards={cards} snapshotCodes={snapshotCodes} referenceTemplate={referenceTemplate} onCreated={created} /></section> : null}
        {run ? <>
          <section className="wb-section maitu-run-summary">
            <SectionHeader kicker={run.run_code} title={run.title} actions={<><RunStatus run={run} /><button type="button" className="wb-icon-button" title="刷新运行" onClick={refreshRun}><RefreshCw size={15} aria-hidden="true" /></button></>} />
            <div className="wb-section-body"><p className="maitu-topic">{run.topic ?? "该运行使用已固定事实版本生成剧本、场景、素材选择与麦兔草稿。"}</p><RunProgress run={run} currentPlan={currentPlan} /><div className="maitu-run-inputs"><span><strong>事实</strong>{run.fact_card_code} · v{run.fact_card_version ?? "固定"}</span><span><strong>素材</strong>{run.inventory_snapshot_code}</span>{run.reference_template_code ? <span><strong>参考</strong>{run.reference_template_code} · r{run.reference_template_revision_number} · {run.reference_template_projection_fingerprint?.slice(0, 12)}...</span> : null}<span><strong>直播间</strong>{run.target_live_room_id ?? "待指定"}</span></div><TargetRoomEditor run={run} onChanged={refreshRun} /></div>
          </section>

          <section className="wb-section">
            <SectionHeader kicker="HUMAN DECISIONS" title={`需求决策 · ${requirements.length} 项`} actions={<StatusBadge label={`${requirements.filter((item) => !item.decision).length} 项待确认`} tone={requirements.some((item) => item.priority === "critical" && !item.decision) ? "danger" : "warning"} />} />
            <div className="wb-section-body">{requirementsQuery.isLoading ? <LoadingBlock /> : requirements.length ? <div className="maitu-requirements">{requirements.map((requirement) => <RequirementItem key={requirement.requirement_code} runCode={run.run_code} requirement={requirement} onChanged={refreshRun} />)}</div> : <EmptyBlock icon={ListChecks} title="计划尚未产出需求" detail="先生成初始计划；系统不会擅自替代人工做素材取舍。" />}</div>
          </section>

          <PlanPanel run={run} revisions={revisions} snapshotCodes={snapshotCodes} onChanged={refreshRun} />
          <GatePanel run={run} currentPlan={currentPlan} criticalConflictCount={criticalConflicts} onChanged={refreshRun} />
        </> : showCreate ? null : <section className="wb-section"><EmptyBlock icon={GitBranch} title="选择或创建一个主题运行" detail="每次运行固定事实版本和资源快照，后续所有 replan 都保留历史 revision。" /></section>}
      </div>
    </div>
  </div>;
}

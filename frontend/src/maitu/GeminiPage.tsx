import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Film, RefreshCw, Replace, ShieldAlert, Sparkles } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, Metric, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { maituApi } from "./api";
import { DEMO_ANALYSIS_CONFLICTS, DEMO_RUNS, DEMO_VIDEO_ANALYSES } from "./demoData";
import { RUN_STATUS_META, type AnalysisConflict, type VideoAnalysisItem } from "./types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未能完成";
}

function GeminiStatus({ item }: { item: VideoAnalysisItem }) {
  const status = {
    not_requested: { label: "未回填", tone: "neutral" as const },
    queued: { label: "待校验", tone: "warning" as const },
    running: { label: "正在入库", tone: "info" as const },
    succeeded: { label: "已回填", tone: "success" as const },
    failed: { label: "回填失败", tone: "danger" as const },
  }[item.gemini_status];
  return <StatusBadge label={status.label} tone={status.tone} />;
}

function BackfillCell({ runCode, item, disabled, onSubmitted }: { runCode: string; item: VideoAnalysisItem; disabled: boolean; onSubmitted: () => void }) {
  const [open, setOpen] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [validationError, setValidationError] = useState("");
  const mutation = useMutation({
    mutationFn: () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(rawJson);
      } catch {
        throw new Error("粘贴内容不是有效 JSON");
      }
      if (!item.asset_fingerprint) throw new Error("素材缺少指纹，不能绑定 Gemini 结果");
      return maituApi.submitGeminiBackfill(runCode, item.analysis_code, { raw_json: parsed, asset_code: item.asset_code, asset_fingerprint: item.asset_fingerprint });
    },
    onSuccess: () => { setOpen(false); setRawJson(""); setValidationError(""); onSubmitted(); },
  });
  const submit = () => {
    try { JSON.parse(rawJson); setValidationError(""); mutation.mutate(); }
    catch { setValidationError("粘贴内容不是有效 JSON"); }
  };
  return <div className="maitu-backfill-cell">
    <button type="button" className="wb-button" disabled={disabled || !item.asset_fingerprint} onClick={() => setOpen((value) => !value)}><Sparkles size={14} aria-hidden="true" />{item.gemini_status === "succeeded" ? "更新结果" : "录入结果"}</button>
    {!item.asset_fingerprint ? <small>缺少素材指纹</small> : null}
    {open ? <div className="maitu-backfill-editor"><div><strong>粘贴 Gemini 原始 JSON</strong><code>{item.asset_fingerprint?.slice(0, 16)}</code></div><textarea className="wb-textarea" aria-label={`${item.asset_title} Gemini 原始 JSON`} value={rawJson} onChange={(event) => { setRawJson(event.target.value); setValidationError(""); }} placeholder={'{"summary":"...","segments":[]}'} /><div><button type="button" className="wb-button" onClick={() => setOpen(false)}>取消</button><button type="button" className="wb-button wb-button-primary" disabled={!rawJson.trim() || mutation.isPending} onClick={submit}>校验并回填</button></div>{validationError || mutation.error ? <span role="alert">{validationError || errorMessage(mutation.error)}</span> : null}</div> : null}
  </div>;
}

function ConflictCard({ runCode, conflict, onResolved }: { runCode: string; conflict: AnalysisConflict; onResolved: () => void }) {
  const mutation = useMutation({
    mutationFn: (resolution: NonNullable<AnalysisConflict["resolution"]>) => maituApi.resolveConflict(runCode, conflict.conflict_code, resolution),
    onSuccess: onResolved,
  });
  return <article className={`maitu-conflict conflict-${conflict.severity}`}>
    <div className="maitu-conflict-head"><div><ShieldAlert size={17} aria-hidden="true" /><span><strong>{conflict.field}</strong><small>{conflict.conflict_code}</small></span></div><StatusBadge label={conflict.severity === "critical" ? "关键冲突" : "需确认"} tone={conflict.severity === "critical" ? "danger" : "warning"} /></div>
    <div className="maitu-conflict-values"><div><span>暂定分析</span><p>{conflict.provisional_value ?? "未给出"}</p></div><div><span>Gemini 回填</span><p>{conflict.gemini_value ?? "未给出"}</p></div></div>
    {conflict.resolution ? <InlineNotice tone="success" title="冲突已裁决">当前采用：{conflict.resolution === "gemini" ? "Gemini 回填" : conflict.resolution === "provisional" ? "原暂定结论" : "替换该素材"}</InlineNotice> : <div className="maitu-conflict-actions"><button type="button" className="wb-button" disabled={mutation.isPending} onClick={() => mutation.mutate("provisional")}><Check size={14} aria-hidden="true" />保留暂定</button><button type="button" className="wb-button wb-button-primary" disabled={mutation.isPending} onClick={() => mutation.mutate("gemini")}><Sparkles size={14} aria-hidden="true" />采用 Gemini</button><button type="button" className="wb-button wb-button-danger" disabled={mutation.isPending} onClick={() => mutation.mutate("replace_asset")}><Replace size={14} aria-hidden="true" />标记替换</button></div>}
    {mutation.error ? <InlineNotice tone="danger" title="冲突裁决保存失败">{errorMessage(mutation.error)}</InlineNotice> : null}
  </article>;
}

export function GeminiPage() {
  const queryClient = useQueryClient();
  const [runCode, setRunCode] = useState(new URLSearchParams(window.location.search).get("run")?.trim() ?? "");
  const runsQuery = useQuery({ queryKey: ["maitu", "runs"], queryFn: maituApi.listRuns });
  const demoMode = runsQuery.isError;
  const runs = runsQuery.data ?? (demoMode ? DEMO_RUNS : []);
  useEffect(() => { if (!runCode && runs[0]) setRunCode(runs[0].run_code); }, [runCode, runs]);
  const analysesQuery = useQuery({ queryKey: ["maitu", "video-analyses", runCode], queryFn: () => maituApi.listVideoAnalyses(runCode), enabled: Boolean(runCode) && !demoMode, retry: false });
  const conflictsQuery = useQuery({ queryKey: ["maitu", "analysis-conflicts", runCode], queryFn: () => maituApi.listConflicts(runCode), enabled: Boolean(runCode) && !demoMode, retry: false });
  const analyses = analysesQuery.data ?? (demoMode && runCode ? DEMO_VIDEO_ANALYSES : []);
  const conflicts = conflictsQuery.data ?? (demoMode && runCode ? DEMO_ANALYSIS_CONFLICTS : []);
  const selectedRun = runs.find((run) => run.run_code === runCode);
  const unresolved = conflicts.filter((item) => !item.resolution);
  const critical = unresolved.filter((item) => item.severity === "critical");
  const selectedAnalyses = analyses.filter((item) => item.selected);
  const extensionUnavailable = (analysesQuery.isError || conflictsQuery.isError) && !demoMode;
  const backfillUnavailable = extensionUnavailable || demoMode;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["maitu", "video-analyses", runCode] });
    void queryClient.invalidateQueries({ queryKey: ["maitu", "analysis-conflicts", runCode] });
    void queryClient.invalidateQueries({ queryKey: ["maitu", "runs"] });
  };
  const provisionalCount = useMemo(() => analyses.filter((item) => item.provisional_source !== "none").length, [analyses]);

  return <div>
    <div className="maitu-gemini-mode"><StatusBadge label="人工网页 JSON 回填" tone="info" /><StatusBadge label="可选，不阻断" tone="success" />{demoMode ? <StatusBadge label="回填接口未连接" tone="warning" /> : null}<span>关键冲突仍需人工裁决</span></div>
    <section className="wb-section maitu-gemini-run-picker">
      <SectionHeader kicker="ANALYSIS SCOPE" title="选择生产运行" actions={selectedRun ? <StatusBadge label={RUN_STATUS_META[selectedRun.status]?.label ?? selectedRun.status} tone={RUN_STATUS_META[selectedRun.status]?.tone} /> : null} />
      <div className="wb-section-body"><div className="wb-field"><label htmlFor="gemini-run">主题运行</label><select id="gemini-run" className="wb-select" value={runCode} onChange={(event) => setRunCode(event.target.value)}><option value="">请选择运行</option>{runs.map((run) => <option key={run.run_code} value={run.run_code}>{run.title} · {run.run_code}</option>)}</select></div></div>
    </section>
    {runCode ? <>
      <div className="wb-metrics maitu-analysis-metrics"><Metric label="视频分析项" value={analyses.length} /><Metric label="已有暂定分析" value={provisionalCount} /><Metric label="已选素材" value={selectedAnalyses.length} /><Metric label="未裁决关键冲突" value={critical.length} detail={critical.length ? "阻断草稿写入" : "当前不阻断"} /></div>
      {extensionUnavailable ? <InlineNotice tone="warning" title="Gemini 回填接口未启用">当前只能查看基础分析，人工 JSON 录入暂不可用。</InlineNotice> : null}
      <section className="wb-section">
        <SectionHeader kicker="VIDEO ANALYSIS" title="视频分析与回填" actions={<button type="button" className="wb-icon-button" title="刷新视频分析" onClick={refresh}><RefreshCw size={15} aria-hidden="true" /></button>} />
        {analysesQuery.isLoading ? <LoadingBlock /> : analyses.length ? <div className="wb-table-wrap"><table className="wb-table maitu-analysis-table"><thead><tr><th>素材</th><th>暂定分析</th><th>Gemini</th><th>冲突</th><th>人工回填</th></tr></thead><tbody>{analyses.map((item) => <tr key={item.analysis_code}><td><div className="maitu-video-asset"><span><Film size={17} aria-hidden="true" /></span><div><strong>{item.asset_title}</strong><code>{item.asset_code}</code>{item.selected ? <small>当前计划已选</small> : <small>候选素材</small>}</div></div></td><td><StatusBadge label={item.provisional_source === "gpt_5_6_sol" ? "GPT-5.6 暂定" : item.provisional_source === "keyframe" ? "关键帧暂定" : "无结果"} tone={item.provisional_source === "none" ? "neutral" : "info"} /><small>{item.provisional_summary ?? "等待基础分析"}</small></td><td><GeminiStatus item={item} /><small>{item.gemini_summary ?? formatDate(item.updated_at)}</small></td><td><StatusBadge label={`${item.conflict_count} 项`} tone={item.conflict_count ? "warning" : "success"} /></td><td><BackfillCell runCode={runCode} item={item} disabled={backfillUnavailable} onSubmitted={refresh} /></td></tr>)}</tbody></table></div> : <EmptyBlock icon={Film} title={extensionUnavailable ? "Gemini 回填接口未启用" : "当前运行没有视频分析项"} detail={extensionUnavailable ? "基础分析仍可参与选材，回填功能不会阻断生产。" : "选材阶段出现视频候选后，会先生成关键帧与暂定分析。"} />}
      </section>
      <section className="wb-section">
        <SectionHeader kicker="HUMAN RESOLUTION" title={`分析冲突 · ${unresolved.length} 项待裁决`} actions={critical.length ? <StatusBadge label={`${critical.length} 项关键阻断`} tone="danger" /> : <StatusBadge label="无关键阻断" tone="success" />} />
        <div className="wb-section-body">{conflictsQuery.isLoading ? <LoadingBlock /> : conflicts.length ? <div className="maitu-conflict-list">{conflicts.map((conflict) => <ConflictCard key={conflict.conflict_code} runCode={runCode} conflict={conflict} onResolved={refresh} />)}</div> : <EmptyBlock icon={CheckCircle2} title="没有分析冲突" detail="Gemini 回填与暂定结论一致，或尚未申请回填。" />}</div>
      </section>
    </> : <section className="wb-section"><EmptyBlock icon={Film} title="先选择一个生产运行" /></section>}
  </div>;
}

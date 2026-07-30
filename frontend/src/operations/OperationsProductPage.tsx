import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  BarChart3,
  Check,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Link2,
  Plus,
  Upload,
} from "lucide-react";
import { contentProjectsApi } from "../content/api";
import { dataGovernanceApi } from "../governance/dataApi";
import { functionalLiveRoomsApi } from "../live-rooms/api";
import { PageHeader, ProgressSteps, SegmentedTabs } from "../product/components";
import { functionalVideosApi } from "../videos/api";
import { EmptyBlock, LoadingBlock, StatusBadge, formatDate } from "../workbench/components";
import { productCopy, productLabel } from "../workbench/productLanguage";
import {
  operationsApi,
  type AttributionDimensionGroup,
  type OperationImportBatch,
  type PendingOperationBinding,
} from "./api";

type View = "imports" | "bindings" | "analysis" | "settings";
type AnalysisDimension = "session" | "segment" | "template" | "asset";

function readableError(error: unknown): string {
  if (!error) return "";
  return "操作没有完成，请检查填写内容后重试。";
}

function summaryNumber(batch: OperationImportBatch | undefined, key: string): number {
  return batch?.previewSummary[key] ?? 0;
}

function ImportWorkspace() {
  const client = useQueryClient();
  const [file, setFile] = useState<File>();
  const [batch, setBatch] = useState<OperationImportBatch>();
  const preview = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("请选择文件");
      return operationsApi.previewImport(file);
    },
    onSuccess: setBatch,
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!batch) throw new Error("请先检查文件");
      return operationsApi.confirmImportBatch(batch.batchCode);
    },
    onSuccess: (next) => {
      setBatch(next);
      void client.invalidateQueries({ queryKey: ["operations"] });
    },
  });
  const step = !batch ? 1 : batch.status === "confirmed" ? 3 : 2;
  const importable = summaryNumber(batch, "ready_row_count") + summaryNumber(batch, "pending_binding_row_count");
  return <div className="ops-import-product">
    <ProgressSteps current={step} items={["下载模板", "上传文件", "检查数据", "确认入库"]} />
    <section className="product-surface ops-import-start">
      <div>
        <span className="product-section-kicker">标准数据模板</span>
        <h2>导入直播运营数据</h2>
        <p>先下载模板填写场次与指标。文件会先预览，确认前不会写入正式数据。</p>
      </div>
      <div className="ops-import-actions">
        <a className="product-secondary-button" href={operationsApi.importTemplateUrl("xlsx")}><Download size={16} />下载 Excel 模板</a>
        <label className="product-file-button">
          <Upload size={16} />{file ? file.name : "选择 CSV 或 Excel"}
          <input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => { setFile(event.target.files?.[0]); setBatch(undefined); }} />
        </label>
        <button className="product-primary-button" type="button" disabled={!file || preview.isPending} onClick={() => preview.mutate()}>
          {preview.isPending ? "正在检查" : "检查文件"}
        </button>
      </div>
    </section>
    {readableError(preview.error ?? confirm.error) ? <div className="product-inline-error"><AlertCircle size={17} />{readableError(preview.error ?? confirm.error)}</div> : null}
    {batch ? <section className="product-surface ops-import-review">
      <header>
        <div><span className="product-section-kicker">导入预览</span><h2>{batch.originalFilename}</h2></div>
        {batch.status === "confirmed" ? <StatusBadge label="已入库" tone="success" /> : <button className="product-primary-button" type="button" disabled={!importable || confirm.isPending} onClick={() => confirm.mutate()}><Check size={16} />确认导入 {importable} 行</button>}
      </header>
      <div className="ops-summary-band">
        <span><strong>{summaryNumber(batch, "session_count")}</strong>场直播</span>
        <span><strong>{summaryNumber(batch, "ready_row_count")}</strong>可直接导入</span>
        <span><strong>{summaryNumber(batch, "pending_binding_row_count")}</strong>需补充关联</span>
        <span className={summaryNumber(batch, "invalid_row_count") ? "has-error" : ""}><strong>{summaryNumber(batch, "invalid_row_count")}</strong>行需修复</span>
        <span><strong>{summaryNumber(batch, "duplicate_row_count")}</strong>行重复</span>
      </div>
      <div className="product-table-wrap"><table className="product-table">
        <thead><tr><th>行</th><th>直播场次</th><th>时间</th><th>内容关联</th><th>指标</th><th>检查结果</th></tr></thead>
        <tbody>{batch.rows.map((row) => {
          const payload = row.normalizedPayload;
          const binding = typeof payload.binding === "object" && payload.binding ? payload.binding as Record<string, unknown> : {};
          const metric = typeof payload.metric === "object" && payload.metric ? payload.metric as Record<string, unknown> : {};
          const issues = [...row.validationErrors, ...row.validationWarnings];
          return <tr key={row.rowNumber}>
            <td>{row.rowNumber}</td>
            <td><strong>{String(payload.title ?? "未命名场次")}</strong><small>{String(payload.external_session_id ?? "未填写外部场次 ID")}</small></td>
            <td><span>{formatDate(String(payload.started_at ?? ""))}</span><small>至 {formatDate(String(payload.ended_at ?? ""))}</small></td>
            <td>{binding.content_code ? <span>{productLabel(String(binding.content_kind), "已关联内容")}</span> : <span className="muted">待关联</span>}</td>
            <td>{metric.metric_key ? <span>{productLabel(String(metric.metric_key), "业务指标")}：{String(metric.value ?? "-")}</span> : <span className="muted">无指标</span>}</td>
            <td>{issues.length ? <div className="ops-row-issues">{issues.map((issue, index) => <span key={`${row.rowNumber}:${index}`}>{productCopy(issue.message, "这一行需要检查")}</span>)}</div> : <StatusBadge label={row.importStatus === "imported" ? "已导入" : row.duplicateKind ? "重复数据" : "可以导入"} tone={row.duplicateKind ? "neutral" : "success"} />}</td>
          </tr>;
        })}</tbody>
      </table></div>
    </section> : <section className="product-empty-stage"><FileSpreadsheet size={30} /><strong>选择数据文件后查看导入预览</strong><span>系统会标出缺失、格式错误、重复数据和待关联内容。</span></section>}
  </div>;
}

type ContentChoice = { kind: string; code: string; revision?: number; label: string };

function BindingCard({ item, choices }: { item: PendingOperationBinding; choices: ContentChoice[] }) {
  const client = useQueryClient();
  const suggested = item.candidates.flatMap((candidate) => {
    const known = choices.find((choice) => choice.kind === candidate.contentKind && choice.code === candidate.contentCode);
    return [{ kind: candidate.contentKind, code: candidate.contentCode, revision: candidate.contentRevision, label: candidate.title ?? known?.label ?? "建议内容" }];
  });
  const options = [...suggested, ...choices.filter((choice) => !suggested.some((item) => item.kind === choice.kind && item.code === choice.code))];
  const [selection, setSelection] = useState("");
  const resolve = useMutation({
    mutationFn: () => {
      const selected = options[Number(selection)];
      if (!selected) throw new Error("请选择关联内容");
      return operationsApi.resolveSessionBinding(item.sessionCode, {
        expected_revision: item.revisionNumber,
        content_kind: selected.kind,
        content_code: selected.code,
        content_revision: selected.revision,
        evidence_note: "运营人员根据直播场次和实际使用内容完成关联。",
        actor: "functional-operator",
      });
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ["operations", "pending-bindings"] }),
  });
  return <article className="ops-binding-card">
    <div><span className="product-section-kicker">{item.platform || "直播平台"}</span><h3>{item.title}</h3><p>{item.externalSessionId ? `外部场次 ID：${item.externalSessionId}` : `${formatDate(item.startedAt)} 开始`}</p></div>
    <label className="product-field"><span>本场实际使用的内容</span><select value={selection} onChange={(event) => setSelection(event.target.value)}><option value="">选择项目、直播间方案或成片</option>{options.map((choice, index) => <option key={`${choice.kind}:${choice.code}:${index}`} value={index}>{choice.label} · {productLabel(choice.kind, "内容")}</option>)}</select></label>
    <button className="product-primary-button" type="button" disabled={!selection || resolve.isPending} onClick={() => resolve.mutate()}><Link2 size={16} />确认关联</button>
    {resolve.error ? <small className="product-error-copy">关联没有保存，请重新选择后再试。</small> : null}
  </article>;
}

function BindingsWorkspace() {
  const pending = useQuery({ queryKey: ["operations", "pending-bindings"], queryFn: operationsApi.listPendingBindings });
  const projects = useQuery({ queryKey: ["projects"], queryFn: contentProjectsApi.list });
  const liveRooms = useQuery({ queryKey: ["live-room-plans"], queryFn: functionalLiveRoomsApi.list });
  const videos = useQuery({ queryKey: ["video-plans"], queryFn: functionalVideosApi.list });
  const choices: ContentChoice[] = [
    ...(projects.data ?? []).map((item) => ({ kind: "content_project_revision", code: item.projectCode, revision: item.revisionNumber, label: item.title })),
    ...(liveRooms.data ?? []).map((item) => ({ kind: "live_room_plan", code: item.planCode, label: item.expectedTitle || "直播间方案" })),
    ...(videos.data ?? []).map((item) => ({ kind: "rendered_video_plan", code: item.planCode, label: item.title || "竖屏成片" })),
  ];
  if (pending.isLoading) return <LoadingBlock label="正在读取待关联场次" />;
  return <div className="ops-bindings-product">
    <section className="product-guidance"><CheckCircle2 size={19} /><div><strong>关联完成后，场次数据才会进入内容表现分析</strong><span>只需选择实际使用的业务内容，不需要填写项目编码或版本号。</span></div></section>
    {pending.data?.length ? <div className="ops-binding-grid">{pending.data.map((item) => <BindingCard key={item.sessionCode} item={item} choices={choices} />)}</div> : <EmptyBlock icon={CheckCircle2} title="所有场次都已关联" detail="新导入且无法自动匹配的场次会出现在这里。" />}
  </div>;
}

function evidenceTone(level: string): "success" | "warning" | "neutral" | "info" {
  if (["measured", "verified", "strong"].includes(level)) return "success";
  if (["estimated", "limited", "weak"].includes(level)) return "warning";
  return "neutral";
}

function dimensionMatch(group: AttributionDimensionGroup, view: AnalysisDimension): boolean {
  const kind = group.dimensionType.toLowerCase();
  if (view === "segment") return kind.includes("segment") || kind.includes("scene") || kind.includes("shot");
  if (view === "template") return kind.includes("template");
  return kind.includes("asset") || kind.includes("material");
}

function AnalysisWorkspace() {
  const client = useQueryClient();
  const sessions = useQuery({ queryKey: ["operations", "sessions"], queryFn: operationsApi.listSessions });
  const reports = useQuery({ queryKey: ["operations", "reports"], queryFn: operationsApi.listReports });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: dataGovernanceApi.listMetrics });
  const [dimension, setDimension] = useState<AnalysisDimension>("session");
  const metricOptions = useMemo(() => Array.from(new Set((sessions.data ?? []).flatMap((item) => Object.keys(item.metrics)))), [sessions.data]);
  const [metricKey, setMetricKey] = useState("");
  const selectedMetric = metricKey || metricOptions[0] || "";
  const report = (reports.data ?? []).find((item) => item.metricKey === selectedMetric) ?? reports.data?.[0];
  const create = useMutation({
    mutationFn: () => operationsApi.createReport({ metric_key: selectedMetric, session_codes: (sessions.data ?? []).map((item) => item.sessionCode) }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["operations", "reports"] }),
  });
  const metricName = (key: string) => metrics.data?.find((item) => item.metricCode === key)?.name ?? productLabel(key, "业务指标");
  const sessionRows = (sessions.data ?? []).filter((item) => selectedMetric in item.metrics).map((item) => ({ label: item.title, value: item.metrics[selectedMetric], sampleSize: 1, evidence: item.bindingStatus === "resolved" ? "已关联" : "关联待补充" }));
  const dimensionRows = (report?.dimensionGroups ?? []).filter((item) => dimensionMatch(item, dimension)).map((item) => ({ label: productCopy(item.displayLabel, productLabel(item.dimensionType, "内容")), value: item.averagePerSession, sampleSize: item.sampleSize, evidence: productLabel(item.evidenceLevel, "证据有限") }));
  const rows = dimension === "session" ? sessionRows : dimensionRows;
  const max = Math.max(1, ...rows.map((item) => Math.abs(item.value)));
  return <div className="ops-analysis-product">
    <section className="product-surface ops-analysis-controls">
      <label className="product-field"><span>分析指标</span><select value={selectedMetric} onChange={(event) => setMetricKey(event.target.value)}>{metricOptions.map((item) => <option key={item} value={item}>{metricName(item)}</option>)}</select></label>
      <label className="product-field"><span>数据范围</span><select defaultValue="all"><option value="all">全部已导入场次</option></select></label>
      <div className="ops-analysis-meta"><span>样本 <strong>{sessions.data?.length ?? 0}</strong> 场</span><span>更新于 <strong>{formatDate(report?.createdAt)}</strong></span></div>
      <button className="product-secondary-button" type="button" disabled={!selectedMetric || !(sessions.data?.length) || create.isPending} onClick={() => create.mutate()}><BarChart3 size={16} />重新计算</button>
    </section>
    <div className="ops-analysis-disclaimer"><AlertCircle size={16} /><span>这里展示内容与表现的关联趋势，用于选题和制作复盘，不代表严格因果关系。</span></div>
    <SegmentedTabs value={dimension} onValueChange={(value) => setDimension(value as AnalysisDimension)} items={[{ value: "session", label: "按场次" }, { value: "segment", label: "按内容段" }, { value: "template", label: "按模板" }, { value: "asset", label: "按素材" }]} />
    <section className="product-surface ops-ranking-panel">
      <header><div><span className="product-section-kicker">{metricName(selectedMetric)}</span><h2>{dimension === "session" ? "场次表现" : `${({ segment: "内容段", template: "模板", asset: "素材" } as const)[dimension]}表现`}</h2></div>{report ? <StatusBadge label={productLabel(report.evidenceLevel, "描述性结果")} tone={evidenceTone(report.evidenceLevel)} /> : null}</header>
      {rows.length ? <div className="ops-ranking-list">{rows.sort((a, b) => b.value - a.value).map((item, index) => <article key={`${item.label}:${index}`}>
        <span className="ops-rank-number">{index + 1}</span><div className="ops-rank-copy"><strong>{item.label}</strong><span><i style={{ width: `${Math.max(3, Math.abs(item.value) / max * 100)}%` }} /></span></div><strong className="ops-rank-value">{Number(item.value).toLocaleString()}</strong><small>{item.sampleSize} 个样本 · {item.evidence}</small>
      </article>)}</div> : <EmptyBlock icon={BarChart3} title="当前维度还没有可分析数据" detail="导入并关联更多场次后，这里会按统一口径展示内容表现。" />}
    </section>
    {create.error ? <div className="product-inline-error"><AlertCircle size={17} />分析没有完成，请确认所选场次包含该指标。</div> : null}
  </div>;
}

function generatedMetricCode(): string {
  return `metric-${crypto.randomUUID()}`;
}

function MetricSettings() {
  const client = useQueryClient();
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: dataGovernanceApi.listMetrics });
  const contracts = useQuery({ queryKey: ["data-contracts"], queryFn: dataGovernanceApi.listContracts });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [unit, setUnit] = useState("次");
  const [aggregation, setAggregation] = useState("sum");
  const [contractIndex, setContractIndex] = useState("0");
  const create = useMutation({
    mutationFn: () => {
      const contract = contracts.data?.[Number(contractIndex)];
      if (!contract) throw new Error("请选择数据来源");
      const valueType = unit === "毫秒" ? "duration_ms" : aggregation === "count" ? "integer" : "decimal";
      return dataGovernanceApi.createMetricRevision(generatedMetricCode(), {
        owner_principal: "operations-team",
        expected_revision: 0,
        activate: true,
        definition: {
          name: name.trim(), description: description.trim(), grain: "live_session", unit: unit.trim(), value_type: valueType,
          aggregation, event_time_field: "occurred_at", timezone: "Asia/Shanghai", business_day_boundary: "00:00",
          dimensions: ["content", "template", "asset"], deduplication_keys: ["source_event_id"],
          event_contract_refs: [{ code: contract.contractCode, revision: contract.revisionNumber }],
          null_rule: { action: "exclude" }, outlier_rule: { action: "flag" }, schema_compatibility: { mode: "compatible" }, quality_slo: { completeness: 0.95 },
        },
      });
    },
    onSuccess: () => {
      setCreating(false); setName(""); setDescription("");
      void client.invalidateQueries({ queryKey: ["metrics"] });
    },
  });
  return <div className="ops-settings-product">
    <section className="product-surface">
      <header className="product-section-header"><div><span className="product-section-kicker">运营口径</span><h2>业务指标</h2><p>统一名称、单位和汇总方式，导入和分析会使用同一口径。</p></div><button className="product-primary-button" type="button" onClick={() => setCreating((value) => !value)}><Plus size={16} />新建指标</button></header>
      {creating ? <form className="ops-metric-form" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
        <label className="product-field"><span>指标名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：商品点击次数" required /></label>
        <label className="product-field wide"><span>业务含义</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="说明什么时候计入，以及它反映什么" required /></label>
        <label className="product-field"><span>单位</span><input value={unit} onChange={(event) => setUnit(event.target.value)} required /></label>
        <label className="product-field"><span>汇总方式</span><select value={aggregation} onChange={(event) => setAggregation(event.target.value)}><option value="sum">求和</option><option value="count">计数</option><option value="average">平均值</option><option value="max">最大值</option><option value="last">期末值</option></select></label>
        <label className="product-field"><span>数据来源</span><select value={contractIndex} onChange={(event) => setContractIndex(event.target.value)}>{(contracts.data ?? []).map((item, index) => <option value={index} key={`${item.contractCode}:${item.revisionNumber}`}>{productCopy(item.sourceSystem, "运营数据源")}</option>)}</select></label>
        <div className="ops-metric-form-actions"><button className="product-secondary-button" type="button" onClick={() => setCreating(false)}>取消</button><button className="product-primary-button" type="submit" disabled={!name.trim() || !description.trim() || !contracts.data?.length || create.isPending}>保存指标</button></div>
        {create.error ? <small className="product-error-copy">指标没有保存，请检查名称、单位和数据来源。</small> : null}
      </form> : null}
      {metrics.isLoading ? <LoadingBlock label="正在读取指标" /> : <div className="ops-metric-list">{(metrics.data ?? []).map((metric) => <article key={metric.metricCode}><div><strong>{metric.name}</strong><span>{metric.description}</span></div><span>{metric.unit}</span><span>{productLabel(metric.aggregation, "按口径汇总")}</span><StatusBadge label={productLabel(metric.status, "使用中")} tone={metric.status === "active" ? "success" : "neutral"} /></article>)}</div>}
    </section>
  </div>;
}

export function OperationsProductPage({ initialView }: { initialView?: View }) {
  const [view, setView] = useState<View>(initialView ?? "imports");
  const pending = useQuery({ queryKey: ["operations", "pending-bindings"], queryFn: operationsApi.listPendingBindings });
  return <div className="product-page operations-product-page">
    <PageHeader eyebrow="数据闭环" title="运营与内容表现" description="导入直播数据，将场次关联到实际内容，再从场次、内容段、模板和素材维度复盘表现。" actions={<a className="product-secondary-button" href={operationsApi.importTemplateUrl("xlsx")}><Download size={16} />下载导入模板</a>} />
    <SegmentedTabs value={view} onValueChange={(value) => setView(value as View)} items={[
      { value: "imports", label: "数据导入" },
      { value: "bindings", label: "待关联", count: pending.data?.length ?? 0 },
      { value: "analysis", label: "表现分析" },
      { value: "settings", label: "指标设置" },
    ]} />
    {view === "imports" ? <ImportWorkspace /> : null}
    {view === "bindings" ? <BindingsWorkspace /> : null}
    {view === "analysis" ? <AnalysisWorkspace /> : null}
    {view === "settings" ? <MetricSettings /> : null}
  </div>;
}

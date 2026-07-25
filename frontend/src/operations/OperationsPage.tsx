import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  ChartNoAxesCombined,
  FilePenLine,
  FileUp,
  ListTree,
  Plus,
  Radio,
  RotateCw,
  ScanLine,
  Trash2,
} from "lucide-react";
import { functionalLiveRoomsApi } from "../live-rooms/api";
import {
  EmptyBlock,
  InlineNotice,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../workbench/components";
import {
  operationsApi,
  type AttributionReport,
  type ContentExposure,
  type ContentProjection,
  type ContentTimeline,
  type TimeMapping,
} from "./api";
import { dataGovernanceApi, type MetricRevision } from "../governance/dataApi";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败";
}
function localTime(value: Date): string {
  return value.toISOString().slice(0, 16);
}
function sessionEvidenceState(
  session: { sessionCode: string; releaseCode?: string },
  exposures: Array<{ sessionCode: string; status: string }>,
): string {
  if (
    exposures.some(
      (exposure) =>
        exposure.sessionCode === session.sessionCode &&
        exposure.status === "active",
    )
  )
    return "已观察展示";
  if (session.releaseCode) return "已关联发布修订";
  return "仅计划";
}

type SessionMetricDraft = {
  id: string;
  key: string;
  value: number;
  metricCode?: string;
  revisionNumber?: number;
};
let metricDraftSequence = 1;
function newMetricDraft(
  key = "",
  value = 0,
  metric?: MetricRevision,
): SessionMetricDraft {
  return {
    id: `session-metric-${metricDraftSequence++}`,
    key,
    value,
    metricCode: metric?.metricCode,
    revisionNumber: metric?.revisionNumber,
  };
}

function metricValidation(metrics: SessionMetricDraft[]): string | undefined {
  const seen = new Set<string>();
  for (const metric of metrics) {
    const key = metric.key.trim();
    if (!key) return "每条指标都需要填写名称，或删除该指标行。";
    if (!Number.isFinite(metric.value)) return `指标 ${key} 的数值无效。`;
    if (
      (metric.metricCode && !metric.revisionNumber) ||
      (!metric.metricCode && metric.revisionNumber)
    )
      return `指标 ${key} 的目录修订不完整。`;
    if (seen.has(key)) return `指标 ${key} 重复，请合并为一条。`;
    seen.add(key);
  }
  return undefined;
}

function metricCatalogLabel(metric: MetricRevision): string {
  const unit = metric.currency ? `${metric.unit} ${metric.currency}` : metric.unit;
  return `${metric.name} · ${metric.metricCode} r${metric.revisionNumber} · ${unit}`;
}

function contentProjectionSummary(content: ContentProjection): string {
  if (content.status !== "resolved") return "内容链未解析";
  const labels: string[] = [];
  if (content.programSegment?.segmentCode) {
    labels.push(`节目段 ${content.programSegment.segmentCode}`);
  }
  if (content.scriptBlocks.length) {
    labels.push(`剧本段 ${content.scriptBlocks.map((block) => block.blockCode).join("、")}`);
  }
  const modules = content.scriptBlocks.flatMap((block) => block.templateModules);
  if (modules.length) {
    labels.push(
      `模板 ${modules.map((module) => `${module.templateCode}:${module.moduleKey ?? "模块"}`).join("、")}`,
    );
  }
  const products = [
    ...(content.programSegment?.productRefs ?? []),
    ...content.scriptBlocks.flatMap((block) => (block.productRef ? [block.productRef] : [])),
  ];
  if (products.length) labels.push(`商品 ${products.length} 项`);
  const hasCta = (content.programSegment?.ctaActions.length ?? 0) > 0 || content.scriptBlocks.some((block) => Object.keys(block.ctaIntent).length > 0);
  if (hasCta) labels.push("CTA 已映射");
  return labels.join(" · ") || "内容链无可展示字段";
}

function TimelinePanel({
  timeline,
  loading,
  error,
  mappingHistory,
  savingMapping,
  mappingError,
  onCreateMapping,
}: {
  timeline?: ContentTimeline;
  loading: boolean;
  error: unknown;
  mappingHistory: TimeMapping[];
  savingMapping: boolean;
  mappingError: unknown;
  onCreateMapping: (payload: Record<string, unknown>) => void;
}) {
  if (loading)
    return (
      <div className="operations-timeline-panel">
        <LoadingBlock label="正在构建实际内容时间线" />
      </div>
    );
  if (error)
    return (
      <div className="operations-timeline-panel">
        <InlineNotice tone="danger" title="内容时间线读取失败">
          {errorText(error)}
        </InlineNotice>
      </div>
    );
  if (!timeline) return null;
  return (
    <div className="operations-timeline-panel">
      <div className="operations-timeline-heading">
        <div>
          <span>OBSERVED CONTENT TIMELINE</span>
          <h3>实际内容时间线</h3>
        </div>
        <StatusBadge
          label={`${Math.round(timeline.coverageRatio * 100)}% 已观察`}
          tone={timeline.coverageRatio ? "info" : "warning"}
        />
      </div>
      <div className="operations-timeline-summary">
        <div>
          <span>会话总长</span>
          <strong>{timeline.totalSeconds.toFixed(0)} 秒</strong>
        </div>
        <div>
          <span>实际展示</span>
          <strong>{timeline.observedSeconds.toFixed(0)} 秒</strong>
        </div>
        <div>
          <span>未识别</span>
          <strong>{timeline.unobservedSeconds.toFixed(0)} 秒</strong>
        </div>
        <div>
          <span>已校准</span>
          <strong>{Math.round(timeline.alignmentCoverageRatio * 100)}%</strong>
        </div>
      </div>
      <TimeMappingPanel
        key={`${timeline.sessionCode}:${timeline.timeMapping?.revisionNumber ?? 0}`}
        timeline={timeline}
        history={mappingHistory}
        saving={savingMapping}
        error={mappingError}
        onCreate={onCreateMapping}
      />
      {timeline.missingPlanCodes.length ? (
        <InlineNotice tone="warning" title="计划投影缺失">
          {timeline.missingPlanCodes.join("、")}
        </InlineNotice>
      ) : null}
      <div className="operations-timeline-spans">
        {timeline.spans.length ? (
          timeline.spans.map((span) => (
            <article key={span.exposureCode}>
              <div>
                <strong>{span.scene.title ?? span.sceneCode}</strong>
                <small>
                  {span.scene.shotCode ?? "未映射 Shot"} ·{" "}
                  {span.durationSeconds.toFixed(0)} 秒 · {span.sourceKind} ·{" "}
                  {Math.round(span.confidence * 100)}%
                </small>
                <code>
                  {span.planCode} · {span.exposureCode}
                </code>
                <small>{contentProjectionSummary(span.content)}</small>
                <small>
                  {span.alignmentStatus === "aligned" &&
                  span.sourceStartMs !== undefined &&
                  span.sourceEndMs !== undefined
                    ? `已校准来源区间 ${span.sourceStartMs}-${span.sourceEndMs} ms`
                    : span.alignmentStatus === "partially_aligned"
                      ? "仅部分落在校准覆盖区间"
                      : span.alignmentStatus === "outside_coverage"
                        ? "不在校准覆盖区间"
                        : "尚未建立时间对齐"}
                </small>
              </div>
              <div>
                {span.layers.length ? (
                  span.layers.map((layer) => (
                    <span
                      key={
                        layer.layerBlueprintCode ??
                        `${layer.role}:${layer.assetCode}`
                      }
                    >
                      {layer.role ?? "layer"} · {layer.assetCode ?? "无素材"}
                    </span>
                  ))
                ) : (
                  <span>没有可解析图层</span>
                )}
              </div>
            </article>
          ))
        ) : (
          <EmptyBlock
            icon={ListTree}
            title="尚无实际展示区间"
            detail="登记来源支持的场景区间后，会在这里映射到 Shot 和图层素材。"
          />
        )}
      </div>
    </div>
  );
}

function TimeMappingPanel({
  timeline,
  history,
  saving,
  error,
  onCreate,
}: {
  timeline: ContentTimeline;
  history: TimeMapping[];
  saving: boolean;
  error: unknown;
  onCreate: (payload: Record<string, unknown>) => void;
}) {
  const current = timeline.timeMapping;
  const durationMs = Math.max(1, Math.round(timeline.totalSeconds * 1000));
  const [sourceClock, setSourceClock] = useState(
    current?.sourceClock ?? "recording_elapsed_ms",
  );
  const [sourceKind, setSourceKind] = useState(
    current?.sourceKind ?? "manual_calibration",
  );
  const [offsetMs, setOffsetMs] = useState(current?.sourceOffsetMs ?? 0);
  const [driftPpm, setDriftPpm] = useState(current?.driftPpm ?? 0);
  const [coverageStartMs, setCoverageStartMs] = useState(
    current?.coverageStartMs ?? 0,
  );
  const [coverageEndMs, setCoverageEndMs] = useState(
    current?.coverageEndMs ?? durationMs,
  );
  const [evidenceNote, setEvidenceNote] = useState(current?.evidenceNote ?? "");
  const mappingIssue =
    !sourceClock.trim()
      ? "请填写来源时钟名称。"
      : !evidenceNote.trim()
        ? "请记录校准证据。"
        : coverageEndMs <= coverageStartMs || coverageEndMs > durationMs
          ? "覆盖区间必须在场次范围内，且结束大于开始。"
          : undefined;
  return (
    <section className="operations-time-mapping">
      <div className="operations-time-mapping-heading">
        <div>
          <span>TIME MAPPING</span>
          <strong>
            {current
              ? `${current.sourceClock} · r${current.revisionNumber}`
              : "尚未校准来源时钟"}
          </strong>
        </div>
        <StatusBadge
          label={current ? current.status : "unmapped"}
          tone={current ? "info" : "warning"}
        />
      </div>
      <form
        className="operations-time-mapping-form"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (mappingIssue) return;
          onCreate({
            expected_revision: current?.revisionNumber ?? 0,
            source_clock: sourceClock.trim(),
            source_kind: sourceKind,
            source_offset_ms: offsetMs,
            drift_ppm: driftPpm,
            coverage_start_ms: coverageStartMs,
            coverage_end_ms: coverageEndMs,
            evidence_note: evidenceNote.trim(),
            actor: "functional-operator",
          });
        }}
      >
        <label className="wb-field">
          <span>来源时钟</span>
          <input
            className="wb-input"
            value={sourceClock}
            onChange={(event) => setSourceClock(event.target.value)}
            required
          />
        </label>
        <label className="wb-field">
          <span>校准来源</span>
          <select
            className="wb-input"
            value={sourceKind}
            onChange={(event) => setSourceKind(event.target.value)}
          >
            <option value="manual_calibration">人工校准</option>
            <option value="recording_anchor">录屏锚点</option>
            <option value="platform_anchor">平台锚点</option>
          </select>
        </label>
        <label className="wb-field">
          <span>来源偏移 (ms)</span>
          <input
            className="wb-input"
            type="number"
            value={offsetMs}
            onChange={(event) => setOffsetMs(Number(event.target.value))}
            required
          />
        </label>
        <label className="wb-field">
          <span>漂移 (ppm)</span>
          <input
            className="wb-input"
            type="number"
            value={driftPpm}
            onChange={(event) => setDriftPpm(Number(event.target.value))}
            required
          />
        </label>
        <label className="wb-field">
          <span>覆盖开始 (ms)</span>
          <input
            className="wb-input"
            type="number"
            min="0"
            value={coverageStartMs}
            onChange={(event) => setCoverageStartMs(Number(event.target.value))}
            required
          />
        </label>
        <label className="wb-field">
          <span>覆盖结束 (ms)</span>
          <input
            className="wb-input"
            type="number"
            min="1"
            max={durationMs}
            value={coverageEndMs}
            onChange={(event) => setCoverageEndMs(Number(event.target.value))}
            required
          />
        </label>
        <label className="wb-field wide">
          <span>校准证据</span>
          <textarea
            className="wb-textarea"
            value={evidenceNote}
            onChange={(event) => setEvidenceNote(event.target.value)}
            required
          />
        </label>
        <button
          className="wb-button"
          disabled={saving || Boolean(mappingIssue)}
        >
          <CalendarClock size={15} aria-hidden="true" />
          {current ? "保存新校准修订" : "保存时间对齐"}
        </button>
      </form>
      {mappingIssue ? (
        <InlineNotice tone="warning" title="时间对齐待修正">
          {mappingIssue}
        </InlineNotice>
      ) : null}
      {error ? (
        <InlineNotice tone="danger" title="时间对齐保存失败">
          {errorText(error)}
        </InlineNotice>
      ) : null}
      {history.length ? (
        <div className="operations-time-mapping-history">
          {history.map((mapping) => (
            <small key={mapping.mappingCode}>
              r{mapping.revisionNumber} · {mapping.status} · {mapping.sourceKind} · {mapping.coverageStartMs}-{mapping.coverageEndMs} ms
            </small>
          ))}
        </div>
      ) : null}
    </section>
  );
}

type ComparisonRow = {
  key: string;
  label: string;
  baseline?: number;
  candidate?: number;
};

function reportComparisonRows(
  baseline: AttributionReport,
  candidate: AttributionReport,
): ComparisonRow[] {
  const rows = new Map<string, ComparisonRow>();
  for (const group of baseline.groups) {
    const key = `group:${group.scopeType}:${group.scopeCode}`;
    rows.set(key, { key, label: group.displayLabel, baseline: group.average });
  }
  for (const group of candidate.groups) {
    const key = `group:${group.scopeType}:${group.scopeCode}`;
    const current = rows.get(key);
    rows.set(key, {
      key,
      label: group.displayLabel,
      baseline: current?.baseline,
      candidate: group.average,
    });
  }
  for (const allocation of baseline.measuredSceneAllocations) {
    if (allocation.measuredMetricValue === undefined) continue;
    const key = `scene:${allocation.planCode}:${allocation.sceneCode}`;
    rows.set(key, {
      key,
      label: `场景 ${allocation.sceneCode} · ${allocation.planCode}`,
      baseline: allocation.measuredMetricValue,
    });
  }
  for (const allocation of candidate.measuredSceneAllocations) {
    if (allocation.measuredMetricValue === undefined) continue;
    const key = `scene:${allocation.planCode}:${allocation.sceneCode}`;
    const current = rows.get(key);
    rows.set(key, {
      key,
      label: `场景 ${allocation.sceneCode} · ${allocation.planCode}`,
      baseline: current?.baseline,
      candidate: allocation.measuredMetricValue,
    });
  }
  return [...rows.values()].sort((left, right) => {
    const leftDelta = (left.candidate ?? 0) - (left.baseline ?? 0);
    const rightDelta = (right.candidate ?? 0) - (right.baseline ?? 0);
    return Math.abs(rightDelta) - Math.abs(leftDelta) || left.label.localeCompare(right.label);
  });
}

function displayDifference(value: number | undefined): string {
  if (value === undefined) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function ReportComparisonPanel({ reports }: { reports: AttributionReport[] }) {
  const [baselineCode, setBaselineCode] = useState("");
  const [candidateCode, setCandidateCode] = useState("");
  useEffect(() => {
    if (!reports.length) return;
    if (!reports.some((report) => report.reportCode === baselineCode)) {
      setBaselineCode(reports[1]?.reportCode ?? reports[0].reportCode);
    }
    if (!reports.some((report) => report.reportCode === candidateCode)) {
      setCandidateCode(reports[0].reportCode);
    }
  }, [baselineCode, candidateCode, reports]);
  if (reports.length < 2) return null;
  const baseline = reports.find((report) => report.reportCode === baselineCode);
  const candidate = reports.find((report) => report.reportCode === candidateCode);
  if (!baseline || !candidate || baseline.reportCode === candidate.reportCode) return null;
  const comparable = baseline.metricKey === candidate.metricKey;
  const rows = comparable ? reportComparisonRows(baseline, candidate) : [];
  return <section className="operations-report-comparison">
    <header>
      <div><span>FROZEN REPORT COMPARISON</span><h3>描述性报告比较</h3></div>
      <StatusBadge label={comparable ? "同一指标" : "指标不一致"} tone={comparable ? "info" : "warning"} />
    </header>
    <div className="operations-report-comparison-selectors">
      <label className="wb-field"><span>基准报告</span><select className="wb-input" value={baselineCode} onChange={(event) => setBaselineCode(event.target.value)}>{reports.map((report) => <option key={report.reportCode} value={report.reportCode}>{report.metricKey} · {report.reportCode}</option>)}</select></label>
      <label className="wb-field"><span>对比报告</span><select className="wb-input" value={candidateCode} onChange={(event) => setCandidateCode(event.target.value)}>{reports.map((report) => <option key={report.reportCode} value={report.reportCode}>{report.metricKey} · {report.reportCode}</option>)}</select></label>
    </div>
    <div className="operations-report-comparison-summary">
      <div><span>基准样本</span><strong>{baseline.metadata.selectedSessionCount}</strong><small>{baseline.metadata.observedSessionCount} 场有展示证据</small></div>
      <div><span>对比样本</span><strong>{candidate.metadata.selectedSessionCount}</strong><small>{candidate.metadata.observedSessionCount} 场有展示证据</small></div>
      <div><span>基准状态</span><strong>{baseline.status}</strong><small>{baseline.fingerprintSha256?.slice(0, 12) ?? "历史报告"}</small></div>
      <div><span>对比状态</span><strong>{candidate.status}</strong><small>{candidate.fingerprintSha256?.slice(0, 12) ?? "历史报告"}</small></div>
    </div>
    {!comparable ? <InlineNotice tone="warning" title="不能比较数值">两个冻结报告使用不同指标，仅保留样本与证据状态的结构比较。</InlineNotice> : null}
    {comparable && rows.length ? <ol className="operations-report-comparison-rows">{rows.map((row) => <li key={row.key}><span><strong>{row.label}</strong><small>基准 {row.baseline?.toFixed(2) ?? "--"} · 对比 {row.candidate?.toFixed(2) ?? "--"}</small></span><strong>{row.baseline === undefined || row.candidate === undefined ? "新增/缺失" : displayDifference(row.candidate - row.baseline)}</strong></li>)}</ol> : null}
    {comparable && !rows.length ? <small className="operations-measured-scene-footnote">两个报告没有可比较的分组或事件时刻场景值。</small> : null}
    <small className="operations-measured-scene-footnote">比较只读取已冻结输入和结果，不构成因果解释或发布授权。</small>
  </section>;
}

function ReportEvidencePanel({ report }: { report: AttributionReport }) {
  const evidence = report.inputEvidence;
  return <details className="operations-report-evidence">
    <summary>冻结输入证据 · {evidence.sessions.length} 场次 · {evidence.exposures.length} 展示</summary>
    <div>
      <section>
        <strong>会话与指标快照</strong>
        {evidence.sessions.length ? <ul>{evidence.sessions.map((session) => <li key={session.sessionCode}><code>{session.sessionCode}</code><small>指标 {session.metricValue?.toFixed(4) ?? "--"}{session.snapshotCode ? ` · 快照 ${session.snapshotCode}` : " · 手工会话值"}{session.eventTimeClock ? ` · 时钟 ${session.eventTimeClock}` : ""}{session.timeMappingCode ? ` · 对齐 ${session.timeMappingCode} r${session.timeMappingRevision ?? "--"}` : ""}</small>{session.snapshotFingerprint ? <small>输入 {session.snapshotFingerprint.slice(0, 12)}</small> : null}</li>)}</ul> : <small>历史报告未封存结构化会话输入。</small>}
      </section>
      <section>
        <strong>实际展示输入</strong>
        {evidence.exposures.length ? <ul>{evidence.exposures.map((exposure) => <li key={exposure.exposureCode}><code>{exposure.exposureCode}</code><small>{exposure.planCode} · {exposure.sceneCode} · {exposure.sourceKind}{exposure.releaseCode ? ` · ${exposure.releaseCode}` : " · 无 release"}{exposure.confidence === undefined ? "" : ` · ${Math.round(exposure.confidence * 100)}%`}</small></li>)}</ul> : <small>该报告没有封存活跃展示输入。</small>}
      </section>
    </div>
  </details>;
}

export function OperationsPage({ view }: { view: "sessions" | "attribution" }) {
  const queryClient = useQueryClient();
  const sessions = useQuery({
    queryKey: ["operations", "sessions"],
    queryFn: operationsApi.listSessions,
  });
  const exposures = useQuery({
    queryKey: ["operations", "exposures"],
    queryFn: operationsApi.listExposures,
  });
  const reports = useQuery({
    queryKey: ["operations", "reports"],
    queryFn: operationsApi.listReports,
  });
  const schedules = useQuery({
    queryKey: ["operations", "schedules"],
    queryFn: operationsApi.listSchedules,
  });
  const plans = useQuery({
    queryKey: ["functional-live-room-plans"],
    queryFn: functionalLiveRoomsApi.list,
  });
  const metricCatalog = useQuery({
    queryKey: ["data-governance", "metrics"],
    queryFn: dataGovernanceApi.listMetrics,
  });
  const [title, setTitle] = useState("");
  const [platform, setPlatform] = useState("douyin");
  const [externalSessionId, setExternalSessionId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [targetResourceId, setTargetResourceId] = useState("");
  const [sourceTimezone, setSourceTimezone] = useState("Asia/Shanghai");
  const [sourceEvidence, setSourceEvidence] = useState("");
  const [sessionPlan, setSessionPlan] = useState("");
  const [sessionMetrics, setSessionMetrics] = useState<SessionMetricDraft[]>(
    () => [newMetricDraft("watchers")],
  );
  const [attributionMetric, setAttributionMetric] = useState("watchers");
  const [attributionSessionCodes, setAttributionSessionCodes] = useState<string[]>([]);
  const attributionSelectionInitialized = useRef(false);
  const [sessionStartsAt, setSessionStartsAt] = useState(localTime(new Date()));
  const [sessionEndsAt, setSessionEndsAt] = useState(
    localTime(new Date(Date.now() + 60 * 60 * 1000)),
  );
  const [exposureSession, setExposureSession] = useState("");
  const [exposurePlan, setExposurePlan] = useState("");
  const [sceneCode, setSceneCode] = useState("");
  const [sourceKind, setSourceKind] = useState("manual_observation");
  const [evidenceNote, setEvidenceNote] = useState("");
  const [confidence, setConfidence] = useState(0.8);
  const [startsAt, setStartsAt] = useState(localTime(new Date()));
  const [endsAt, setEndsAt] = useState(
    localTime(new Date(Date.now() + 60_000)),
  );
  const [room, setRoom] = useState("");
  const [scheduleAt, setScheduleAt] = useState("");
  const [timelineSession, setTimelineSession] = useState("");
  const [metricSnapshotSession, setMetricSnapshotSession] = useState("");
  const [metricSnapshotBinding, setMetricSnapshotBinding] = useState("");
  const [metricSnapshotKey, setMetricSnapshotKey] = useState("");
  const [metricEventTimeClock, setMetricEventTimeClock] = useState("session_utc");
  const [metricValuePointer, setMetricValuePointer] = useState("");
  const [metricNumeratorPointer, setMetricNumeratorPointer] = useState("");
  const [metricDenominatorPointer, setMetricDenominatorPointer] = useState("");
  const [correctionSource, setCorrectionSource] = useState<ContentExposure>();
  const [correctionKind, setCorrectionKind] = useState<"supersede" | "retract">(
    "supersede",
  );
  const [correctionReason, setCorrectionReason] = useState("");
  useEffect(() => {
    if (!sessionPlan && plans.data?.[0]) setSessionPlan(plans.data[0].planCode);
  }, [plans.data, sessionPlan]);
  useEffect(() => {
    if (!exposureSession && sessions.data?.[0])
      setExposureSession(sessions.data[0].sessionCode);
  }, [sessions.data, exposureSession]);
  useEffect(() => {
    const linked = sessions.data?.find(
      (session) => session.sessionCode === exposureSession,
    )?.liveRoomPlanCode;
    if (linked) setExposurePlan(linked);
    else if (!exposurePlan && plans.data?.[0])
      setExposurePlan(plans.data[0].planCode);
  }, [exposurePlan, exposureSession, plans.data, sessions.data]);
  useEffect(() => {
    if (!sessions.data) return;
    const available = new Set(sessions.data.map((session) => session.sessionCode));
    if (!attributionSelectionInitialized.current) {
      setAttributionSessionCodes(sessions.data.map((session) => session.sessionCode));
      attributionSelectionInitialized.current = true;
      return;
    }
    setAttributionSessionCodes((current) =>
      current.filter((sessionCode) => available.has(sessionCode)),
    );
  }, [sessions.data]);
  const exposurePlanDetail = useMemo(
    () => plans.data?.find((plan) => plan.planCode === exposurePlan),
    [exposurePlan, plans.data],
  );
  const sessionMetricIssue = useMemo(
    () => metricValidation(sessionMetrics),
    [sessionMetrics],
  );
  const sessionMetricPayload = useMemo(
    () =>
      Object.fromEntries(
        sessionMetrics.map((metric) => [metric.key.trim(), metric.value]),
      ),
    [sessionMetrics],
  );
  const sessionMetricDefinitionRefs = useMemo(
    () =>
      sessionMetrics.flatMap((metric) =>
        metric.metricCode && metric.revisionNumber
          ? [
              {
                metric_key: metric.key.trim(),
                metric_code: metric.metricCode,
                revision_number: metric.revisionNumber,
              },
            ]
          : [],
      ),
    [sessionMetrics],
  );
  const attributionMetricOptions = useMemo(
    () =>
      Array.from(
        new Set([
          ...(sessions.data ?? []).flatMap((session) => Object.keys(session.metrics)),
          ...(metricCatalog.data ?? []).map((metric) => metric.metricCode),
        ]),
      ).sort(),
    [metricCatalog.data, sessions.data],
  );
  const snapshotMetric = useMemo(
    () =>
      metricCatalog.data?.find(
        (metric) =>
          `${metric.metricCode}:${metric.revisionNumber}` ===
          metricSnapshotBinding,
      ),
    [metricCatalog.data, metricSnapshotBinding],
  );
  const snapshotMetricIssue =
    !metricSnapshotSession
      ? "请选择一个运营场次。"
      : !snapshotMetric
        ? "请选择一个 live_session 指标定义。"
        : !metricSnapshotKey.trim()
        ? "请填写归因使用的指标名。"
        : !metricEventTimeClock.trim()
          ? "请填写事件时间时钟。"
        : snapshotMetric.aggregation === "ratio" &&
              (!metricNumeratorPointer.trim() || !metricDenominatorPointer.trim())
            ? "比例指标需要分子和分母 JSON Pointer。"
            : snapshotMetric.aggregation !== "count" &&
                snapshotMetric.aggregation !== "ratio" &&
                !metricValuePointer.trim()
              ? "该聚合方式需要数值 JSON Pointer。"
              : undefined;
  const attributionSessions = useMemo(
    () =>
      (sessions.data ?? []).filter((session) =>
        attributionSessionCodes.includes(session.sessionCode),
      ),
    [attributionSessionCodes, sessions.data],
  );
  const missingAttributionMetricSessions = useMemo(
    () =>
      attributionSessions.filter(
        (session) => !(attributionMetric.trim() in session.metrics),
      ),
    [attributionMetric, attributionSessions],
  );
  useEffect(() => {
    const firstScene = exposurePlanDetail?.blueprint.scenes[0]?.scene_code;
    if (
      firstScene &&
      !exposurePlanDetail.blueprint.scenes.some(
        (scene) => scene.scene_code === sceneCode,
      )
    )
      setSceneCode(firstScene);
  }, [exposurePlanDetail, sceneCode]);
  const exposurePayload = () => ({
    session_code: exposureSession,
    plan_code: exposurePlan,
    scene_code: sceneCode,
    started_at: new Date(startsAt).toISOString(),
    ended_at: new Date(endsAt).toISOString(),
    source_kind: sourceKind,
    evidence_note: evidenceNote,
    confidence,
  });
  const beginExposureCorrection = (exposure: ContentExposure) => {
    setCorrectionSource(exposure);
    setCorrectionKind("supersede");
    setCorrectionReason("");
    setExposureSession(exposure.sessionCode);
    setExposurePlan(exposure.planCode);
    setSceneCode(exposure.sceneCode);
    setSourceKind(exposure.sourceKind);
    setEvidenceNote(exposure.evidenceNote);
    setConfidence(exposure.confidence);
    setStartsAt(localTime(new Date(exposure.startedAt)));
    setEndsAt(localTime(new Date(exposure.endedAt)));
  };
  const clearExposureCorrection = () => {
    setCorrectionSource(undefined);
    setCorrectionKind("supersede");
    setCorrectionReason("");
  };
  const createSession = useMutation({
    mutationFn: () =>
      operationsApi.createSession({
        title,
        platform,
        external_session_id: externalSessionId || undefined,
        account_id: accountId || undefined,
        target_resource_id: targetResourceId || undefined,
        source_timezone: sourceTimezone,
        source_evidence: sourceEvidence.trim()
          ? { note: sourceEvidence.trim() }
          : {},
        live_room_plan_code: sessionPlan || undefined,
        started_at: new Date(sessionStartsAt).toISOString(),
        ended_at: new Date(sessionEndsAt).toISOString(),
        metrics: sessionMetricPayload,
        metric_definition_refs: sessionMetricDefinitionRefs,
      }),
    onSuccess: (session) => {
      setTitle("");
      setExternalSessionId("");
      setSourceEvidence("");
      setSessionMetrics([newMetricDraft("watchers")]);
      setTimelineSession(session.sessionCode);
      void queryClient.invalidateQueries({
        queryKey: ["operations", "sessions"],
      });
    },
  });
  const createExposure = useMutation({
    mutationFn: () => operationsApi.createExposure(exposurePayload()),
    onSuccess: () => {
      setEvidenceNote("");
      void queryClient.invalidateQueries({
        queryKey: ["operations", "exposures"],
      });
    },
  });
  const correctExposure = useMutation({
    mutationFn: () =>
      operationsApi.correctExposure({
        source_exposure_code: correctionSource?.exposureCode,
        correction_kind: correctionKind,
        reason: correctionReason,
        actor: "functional-operator",
        replacement:
          correctionKind === "supersede" ? exposurePayload() : undefined,
      }),
    onSuccess: (exposure) => {
      clearExposureCorrection();
      setEvidenceNote("");
      setTimelineSession(exposure.sessionCode);
      void queryClient.invalidateQueries({
        queryKey: ["operations", "exposures"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["operations", "content-timeline"],
      });
    },
  });
  const createReport = useMutation({
    mutationFn: () =>
      operationsApi.createReport({
        metric_key: attributionMetric,
        session_codes: attributionSessionCodes,
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: ["operations", "reports"],
      }),
  });
  const publishReport = useMutation({
    mutationFn: (reportCode: string) =>
      operationsApi.publishDescriptiveReport(reportCode),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: ["operations", "reports"],
      }),
  });
  const rerunReport = useMutation({
    mutationFn: (reportCode: string) => operationsApi.rerunReport(reportCode),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: ["operations", "reports"],
      }),
  });
  const createSchedule = useMutation({
    mutationFn: () =>
      operationsApi.createSchedule({
        title,
        target_live_room_id: room,
        starts_at: new Date(scheduleAt).toISOString(),
        duration_minutes: 60,
      }),
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: ["operations", "schedules"],
      }),
  });
  const createTimeMapping = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      operationsApi.createTimeMapping(timelineSession, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["operations", "content-timeline", timelineSession],
      });
      void queryClient.invalidateQueries({
        queryKey: ["operations", "time-mappings", timelineSession],
      });
    },
  });
  const createMetricSnapshot = useMutation({
    mutationFn: () => {
      if (!snapshotMetric) throw new Error("请先选择指标定义");
      return operationsApi.createSessionMetricSnapshot(metricSnapshotSession, {
        metric_key: metricSnapshotKey.trim(),
        metric_code: snapshotMetric.metricCode,
        revision_number: snapshotMetric.revisionNumber,
        event_time_clock: metricEventTimeClock.trim(),
        value_json_pointer: metricValuePointer.trim() || undefined,
        numerator_json_pointer: metricNumeratorPointer.trim() || undefined,
        denominator_json_pointer: metricDenominatorPointer.trim() || undefined,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["operations", "metric-snapshots", metricSnapshotSession],
      });
    },
  });
  const contentTimeline = useQuery({
    queryKey: ["operations", "content-timeline", timelineSession],
    queryFn: () => operationsApi.getContentTimeline(timelineSession),
    enabled: view === "sessions" && Boolean(timelineSession),
  });
  const timeMappings = useQuery({
    queryKey: ["operations", "time-mappings", timelineSession],
    queryFn: () => operationsApi.listTimeMappings(timelineSession),
    enabled: view === "sessions" && Boolean(timelineSession),
  });
  const metricSnapshots = useQuery({
    queryKey: ["operations", "metric-snapshots", metricSnapshotSession],
    queryFn: () => operationsApi.listSessionMetricSnapshots(metricSnapshotSession),
    enabled: view === "sessions" && Boolean(metricSnapshotSession),
  });
  const error =
    createSession.error ??
    createExposure.error ??
    correctExposure.error ??
    createReport.error ??
    publishReport.error ??
    rerunReport.error ??
    createSchedule.error ??
    createTimeMapping.error ??
    createMetricSnapshot.error;
  if (
    sessions.isLoading ||
    exposures.isLoading ||
    reports.isLoading ||
    schedules.isLoading ||
    plans.isLoading
  )
    return <LoadingBlock />;
  return (
    <div className="operations-layout">
      <section className="wb-section">
        <SectionHeader
          kicker={
            view === "sessions"
              ? "OPERATION SESSIONS"
              : "DESCRIPTIVE ATTRIBUTION"
          }
          title={view === "sessions" ? "运营场次与实际展示" : "归因与排播"}
        />
        {view === "sessions" ? (
          <div className="operations-form-stack">
            <form
              className="operations-form"
              onSubmit={(event: FormEvent) => {
                event.preventDefault();
                if (!sessionMetricIssue) createSession.mutate();
              }}
            >
              <label className="wb-field">
                <span>场次名称</span>
                <input
                  className="wb-input"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  required
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
                <span>外部场次 ID</span>
                <input
                  className="wb-input"
                  value={externalSessionId}
                  onChange={(event) => setExternalSessionId(event.target.value)}
                />
              </label>
              <label className="wb-field">
                <span>账号 / 主体</span>
                <input
                  className="wb-input"
                  value={accountId}
                  onChange={(event) => setAccountId(event.target.value)}
                />
              </label>
              <label className="wb-field">
                <span>目标资源</span>
                <input
                  className="wb-input"
                  value={targetResourceId}
                  onChange={(event) => setTargetResourceId(event.target.value)}
                />
              </label>
              <label className="wb-field">
                <span>来源时区</span>
                <input
                  className="wb-input"
                  value={sourceTimezone}
                  onChange={(event) => setSourceTimezone(event.target.value)}
                  required
                />
              </label>
              <label className="wb-field">
                <span>场次开始</span>
                <input
                  className="wb-input"
                  type="datetime-local"
                  value={sessionStartsAt}
                  onChange={(event) => setSessionStartsAt(event.target.value)}
                  required
                />
              </label>
              <label className="wb-field">
                <span>场次结束</span>
                <input
                  className="wb-input"
                  type="datetime-local"
                  value={sessionEndsAt}
                  onChange={(event) => setSessionEndsAt(event.target.value)}
                  required
                />
              </label>
              <label className="wb-field wide">
                <span>来源证据</span>
                <textarea
                  className="wb-textarea"
                  value={sourceEvidence}
                  onChange={(event) => setSourceEvidence(event.target.value)}
                />
              </label>
              <label className="wb-field wide">
                <span>关联直播间计划</span>
                <select
                  className="wb-input"
                  value={sessionPlan}
                  onChange={(event) => setSessionPlan(event.target.value)}
                >
                  <option value="">未关联计划</option>
                  {plans.data?.map((plan) => (
                    <option key={plan.planCode} value={plan.planCode}>
                      {plan.expectedTitle} · {plan.planCode}
                    </option>
                  ))}
                </select>
              </label>
              <div className="wb-field wide">
                <span>场次指标</span>
                {metricCatalog.error ? (
                  <InlineNotice tone="warning" title="指标目录暂不可用">
                    仍可登记自定义指标，但本次不会绑定指标定义修订。
                  </InlineNotice>
                ) : null}
                <div className="operations-metric-fields">
                  {sessionMetrics.map((draft, index) => (
                    <div className="operations-metric-row" key={draft.id}>
                      <label className="wb-field">
                        <span>指标目录</span>
                        <select
                          aria-label={`指标目录 ${index + 1}`}
                          className="wb-input"
                          value={
                            draft.metricCode && draft.revisionNumber
                              ? `${draft.metricCode}:${draft.revisionNumber}`
                              : ""
                          }
                          onChange={(event) => {
                            const selected = metricCatalog.data?.find(
                              (metric) =>
                                `${metric.metricCode}:${metric.revisionNumber}` ===
                                event.target.value,
                            );
                            setSessionMetrics((current) =>
                              current.map((item) =>
                                item.id === draft.id
                                  ? selected
                                    ? {
                                        ...item,
                                        key: selected.metricCode,
                                        metricCode: selected.metricCode,
                                        revisionNumber: selected.revisionNumber,
                                      }
                                    : {
                                        ...item,
                                        metricCode: undefined,
                                        revisionNumber: undefined,
                                      }
                                  : item,
                              ),
                            );
                          }}
                        >
                          <option value="">自定义指标（不绑定目录）</option>
                          {metricCatalog.data?.map((metric) => (
                            <option
                              key={`${metric.metricCode}:${metric.revisionNumber}`}
                              value={`${metric.metricCode}:${metric.revisionNumber}`}
                            >
                              {metricCatalogLabel(metric)}
                            </option>
                          ))}
                        </select>
                        {draft.metricCode ? (
                          <small className="operations-metric-catalog-note">
                            已绑定 {draft.metricCode} r{draft.revisionNumber}
                          </small>
                        ) : null}
                      </label>
                      <label className="wb-field">
                        <span>指标名称</span>
                        <input
                          aria-label={`指标名称 ${index + 1}`}
                          className="wb-input"
                          value={draft.key}
                          onChange={(event) =>
                            setSessionMetrics((current) =>
                              current.map((item) =>
                                item.id === draft.id
                                  ? {
                                      ...item,
                                      key: event.target.value,
                                      metricCode:
                                        event.target.value === item.metricCode
                                          ? item.metricCode
                                          : undefined,
                                      revisionNumber:
                                        event.target.value === item.metricCode
                                          ? item.revisionNumber
                                          : undefined,
                                    }
                                  : item,
                              ),
                            )
                          }
                          required
                        />
                      </label>
                      <label className="wb-field">
                        <span>指标数值</span>
                        <input
                          aria-label={`指标数值 ${index + 1}`}
                          className="wb-input"
                          type="number"
                          value={draft.value}
                          onChange={(event) =>
                            setSessionMetrics((current) =>
                              current.map((item) =>
                                item.id === draft.id
                                  ? {
                                      ...item,
                                      value: Number(event.target.value),
                                    }
                                  : item,
                              ),
                            )
                          }
                          required
                        />
                      </label>
                      <button
                        type="button"
                        className="wb-icon-button"
                        aria-label={`删除指标 ${index + 1}`}
                        title="删除指标"
                        onClick={() =>
                          setSessionMetrics((current) =>
                            current.filter((item) => item.id !== draft.id),
                          )
                        }
                        disabled={sessionMetrics.length === 1}
                      >
                        <Trash2 size={15} aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  className="wb-button"
                  onClick={() =>
                    setSessionMetrics((current) => [
                      ...current,
                      newMetricDraft(),
                    ])
                  }
                >
                  <Plus size={15} aria-hidden="true" />
                  添加指标
                </button>
              </div>
              {sessionMetricIssue ? (
                <InlineNotice tone="warning" title="指标待修正">
                  {sessionMetricIssue}
                </InlineNotice>
              ) : null}
              <button
                className="wb-button wb-button-primary"
                disabled={
                  createSession.isPending || Boolean(sessionMetricIssue)
                }
              >
                <FileUp size={15} aria-hidden="true" />
                登记场次
              </button>
            </form>
            <form
              className="operations-form"
              onSubmit={(event: FormEvent) => {
                event.preventDefault();
                if (correctionSource) correctExposure.mutate();
                else createExposure.mutate();
              }}
            >
              {correctionSource ? (
                <>
                  <InlineNotice tone="warning" title="正在校正已登记观察">
                    {correctionSource.exposureCode} 当前为{" "}
                    {correctionSource.sceneCode}
                    。替换会保留原观察并新增一条有效观察；撤销不会创建替代观察。
                  </InlineNotice>
                  <label className="wb-field">
                    <span>校正方式</span>
                    <select
                      className="wb-input"
                      value={correctionKind}
                      onChange={(event) =>
                        setCorrectionKind(
                          event.target.value as "supersede" | "retract",
                        )
                      }
                    >
                      <option value="supersede">替换为更正观察</option>
                      <option value="retract">撤销错误观察</option>
                    </select>
                  </label>
                  <label className="wb-field wide">
                    <span>校正原因</span>
                    <textarea
                      className="wb-textarea"
                      value={correctionReason}
                      onChange={(event) =>
                        setCorrectionReason(event.target.value)
                      }
                      required
                    />
                  </label>
                  <button
                    type="button"
                    className="wb-button"
                    onClick={clearExposureCorrection}
                  >
                    取消校正
                  </button>
                </>
              ) : null}
              <label className="wb-field">
                <span>运营场次</span>
                <select
                  className="wb-input"
                  value={exposureSession}
                  onChange={(event) => setExposureSession(event.target.value)}
                  required
                >
                  {sessions.data?.map((session) => (
                    <option
                      key={session.sessionCode}
                      value={session.sessionCode}
                    >
                      {session.title} · {session.sessionCode}
                    </option>
                  ))}
                </select>
              </label>
              <label className="wb-field">
                <span>直播间计划</span>
                <select
                  className="wb-input"
                  value={exposurePlan}
                  onChange={(event) => setExposurePlan(event.target.value)}
                  required
                >
                  {plans.data?.map((plan) => (
                    <option key={plan.planCode} value={plan.planCode}>
                      {plan.expectedTitle} · {plan.planCode}
                    </option>
                  ))}
                </select>
              </label>
              <label className="wb-field">
                <span>实际场景</span>
                <select
                  className="wb-input"
                  value={sceneCode}
                  onChange={(event) => setSceneCode(event.target.value)}
                  required
                >
                  {exposurePlanDetail?.blueprint.scenes.map((scene) => (
                    <option key={scene.scene_code} value={scene.scene_code}>
                      {scene.title} · {scene.scene_code}
                    </option>
                  ))}
                </select>
              </label>
              <label className="wb-field">
                <span>证据来源</span>
                <select
                  className="wb-input"
                  value={sourceKind}
                  onChange={(event) => setSourceKind(event.target.value)}
                >
                  <option value="manual_observation">人工观察</option>
                  <option value="served_log">平台 served log</option>
                  <option value="recording_match">录屏匹配</option>
                </select>
              </label>
              <label className="wb-field">
                <span>开始时间</span>
                <input
                  className="wb-input"
                  type="datetime-local"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                  required
                />
              </label>
              <label className="wb-field">
                <span>结束时间</span>
                <input
                  className="wb-input"
                  type="datetime-local"
                  value={endsAt}
                  onChange={(event) => setEndsAt(event.target.value)}
                  required
                />
              </label>
              <label className="wb-field">
                <span>置信度</span>
                <input
                  className="wb-input"
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={confidence}
                  onChange={(event) =>
                    setConfidence(Number(event.target.value))
                  }
                />
              </label>
              <label className="wb-field wide">
                <span>证据备注</span>
                <textarea
                  className="wb-textarea"
                  value={evidenceNote}
                  onChange={(event) => setEvidenceNote(event.target.value)}
                  required={correctionKind !== "retract"}
                />
              </label>
              <button
                className="wb-button wb-button-primary"
                disabled={
                  (correctionSource
                    ? correctExposure.isPending || !correctionReason.trim()
                    : createExposure.isPending) ||
                  !exposureSession ||
                  !exposurePlan ||
                  !sceneCode ||
                  (correctionKind !== "retract" && !evidenceNote.trim())
                }
              >
                {correctionSource ? (
                  <FilePenLine size={15} aria-hidden="true" />
                ) : (
                  <ScanLine size={15} aria-hidden="true" />
                )}
                {correctionSource
                  ? correctionKind === "retract"
                    ? "撤销当前观察"
                    : "保存更正观察"
                  : "登记实际展示"}
              </button>
            </form>
          </div>
        ) : (
          <>
            <div className="operations-form">
              <label className="wb-field">
                <span>归因指标</span>
                <input
                  className="wb-input"
                  value={attributionMetric}
                  onChange={(event) => setAttributionMetric(event.target.value)}
                  list="operation-metric-keys"
                />
                <datalist id="operation-metric-keys">
                  {attributionMetricOptions.map((metricKey) => (
                    <option key={metricKey} value={metricKey} />
                  ))}
                </datalist>
              </label>
              <div className="wb-field wide">
                <span>纳入场次</span>
                <div className="operations-attribution-session-picker">
                  {sessions.data?.map((session) => (
                    <label key={session.sessionCode}>
                      <input
                        type="checkbox"
                        aria-label={`归因场次 ${session.sessionCode}`}
                        checked={attributionSessionCodes.includes(
                          session.sessionCode,
                        )}
                        onChange={(event) =>
                          setAttributionSessionCodes((current) =>
                            event.target.checked
                              ? [...new Set([...current, session.sessionCode])]
                              : current.filter(
                                  (sessionCode) =>
                                    sessionCode !== session.sessionCode,
                                ),
                          )
                        }
                      />
                      <span>
                        <strong>{session.title}</strong>
                        <small>
                          {session.sessionCode} · {session.platform} · {session.metrics[attributionMetric.trim()] ?? "无此指标"}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
              {missingAttributionMetricSessions.length ? (
                <InlineNotice tone="warning" title="部分场次未记录该指标">
                  {missingAttributionMetricSessions
                    .map((session) => session.sessionCode)
                    .join("、")}
                  。报告会保留描述性结果，并标记指标定义无法完全对齐。
                </InlineNotice>
              ) : null}
              <button
                type="button"
                className="wb-button wb-button-primary"
                disabled={
                  !attributionSessionCodes.length ||
                  createReport.isPending ||
                  !attributionMetric.trim()
                }
                onClick={() => createReport.mutate()}
              >
                <ChartNoAxesCombined size={15} aria-hidden="true" />
                生成描述性归因
              </button>
            </div>
            <form
              className="operations-form"
              onSubmit={(event: FormEvent) => {
                event.preventDefault();
                createSchedule.mutate();
              }}
            >
              <label className="wb-field">
                <span>排播名称</span>
                <input
                  className="wb-input"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  required
                />
              </label>
              <label className="wb-field">
                <span>直播间 ID</span>
                <input
                  className="wb-input"
                  value={room}
                  onChange={(event) => setRoom(event.target.value)}
                  required
                />
              </label>
              <label className="wb-field">
                <span>计划开始</span>
                <input
                  className="wb-input"
                  type="datetime-local"
                  value={scheduleAt}
                  onChange={(event) => setScheduleAt(event.target.value)}
                  required
                />
              </label>
              <button className="wb-button" disabled={createSchedule.isPending}>
                <CalendarClock size={15} aria-hidden="true" />
                检查并保存排播
              </button>
            </form>
          </>
        )}
        {error ? (
          <InlineNotice tone="danger" title="操作未完成">
            {errorText(error)}
          </InlineNotice>
        ) : null}
      </section>
      <section className="wb-section">
        <SectionHeader
          kicker="OBSERVED EVIDENCE"
          title={view === "sessions" ? "已登记场次与展示" : "归因报告与排播"}
        />
        {view === "sessions" ? (
          <>
            <div className="operations-list">
              {sessions.data?.map((session) => (
                <div key={session.sessionCode}>
                  <span>
                    <strong>{session.title}</strong>
                    <code>{session.sessionCode}</code>
                    <small>
                      {session.platform} ·{" "}
                      {session.externalSessionId ?? "无外部场次 ID"} ·{" "}
                      {session.accountId ?? "无账号"} ·{" "}
                      {session.targetResourceId ?? "无目标资源"} ·{" "}
                      {session.sourceTimezone}
                    </small>
                    <small>
                      {sessionEvidenceState(session, exposures.data ?? [])} ·{" "}
                      {session.liveRoomPlanCode ?? "未关联计划"} ·{" "}
                      {Object.entries(session.metrics)
                        .map(([key, value]) => `${key}: ${value}`)
                        .join(" / ")}
                    </small>
                    {session.metricDefinitionRefs.length ? (
                      <small>
                        指标定义快照：{" "}
                        {session.metricDefinitionRefs
                          .map(
                            (reference) =>
                              `${reference.metricKey} -> ${reference.metricCode} r${reference.revisionNumber}${reference.unit ? ` (${reference.unit}${reference.currency ? ` ${reference.currency}` : ""})` : ""}`,
                          )
                          .join(" / ")}
                      </small>
                    ) : null}
                  </span>
                  <StatusBadge label={session.sourceKind} tone="info" />
                  <button
                    type="button"
                    className="wb-button operations-timeline-button"
                    onClick={() => setTimelineSession(session.sessionCode)}
                  >
                    <ListTree size={14} aria-hidden="true" />
                    查看时间线
                  </button>
                  <button
                    type="button"
                    className="wb-button operations-timeline-button"
                    onClick={() => {
                      setMetricSnapshotSession(session.sessionCode);
                      if (!metricSnapshotBinding) {
                        const firstMetric = metricCatalog.data?.find(
                          (metric) => metric.grain === "live_session",
                        );
                        if (firstMetric) {
                          setMetricSnapshotBinding(
                            `${firstMetric.metricCode}:${firstMetric.revisionNumber}`,
                          );
                          setMetricSnapshotKey(firstMetric.metricCode);
                        }
                      }
                    }}
                  >
                    <ChartNoAxesCombined size={14} aria-hidden="true" />
                    指标快照
                  </button>
                </div>
              ))}
              {exposures.data?.map((exposure) => (
                <div key={exposure.exposureCode}>
                  <span>
                    <strong>{exposure.sceneCode} · 实际展示</strong>
                    <code>{exposure.exposureCode}</code>
                    <small>
                      {exposure.sourceKind} ·{" "}
                      {Math.round(exposure.confidence * 100)}% ·{" "}
                      {exposure.releaseCode
                        ? `release ${exposure.releaseCode}`
                        : "未绑定 release 证据"}
                    </small>
                    {exposure.supersedesExposureCode ? (
                      <small>更正自 {exposure.supersedesExposureCode}</small>
                    ) : null}
                    {exposure.supersededByExposureCode ? (
                      <small>
                        已由 {exposure.supersededByExposureCode} 替代
                      </small>
                    ) : null}
                    {exposure.correctionReason ? (
                      <small>校正原因：{exposure.correctionReason}</small>
                    ) : null}
                  </span>
                  <div className="operations-exposure-status">
                    <StatusBadge
                      label={exposure.status}
                      tone={
                        exposure.status === "active"
                          ? exposure.releaseCode
                            ? "success"
                            : "warning"
                          : "neutral"
                      }
                    />
                    {exposure.status === "active" ? (
                      <button
                        type="button"
                        className="wb-button operations-timeline-button"
                        onClick={() => beginExposureCorrection(exposure)}
                      >
                        <FilePenLine size={14} aria-hidden="true" />
                        校正
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
              {!sessions.data?.length && !exposures.data?.length ? (
                <EmptyBlock icon={Radio} title="尚未登记运营场次" />
              ) : null}
            </div>
            {timelineSession ? (
              <TimelinePanel
                timeline={contentTimeline.data}
                loading={contentTimeline.isLoading}
                error={contentTimeline.error}
                mappingHistory={timeMappings.data ?? []}
                savingMapping={createTimeMapping.isPending}
                mappingError={createTimeMapping.error}
                onCreateMapping={(payload) => createTimeMapping.mutate(payload)}
              />
            ) : null}
            {metricSnapshotSession ? (
              <section className="operations-metric-snapshot-panel">
                <div className="operations-timeline-heading">
                  <div>
                    <span>FROZEN EVENT METRICS</span>
                    <h3>会话指标快照 · {metricSnapshotSession}</h3>
                  </div>
                  <StatusBadge
                    label={`${metricSnapshots.data?.length ?? 0} 个快照`}
                    tone={metricSnapshots.data?.some((item) => item.status === "ready") ? "info" : "warning"}
                  />
                </div>
                <form
                  className="operations-metric-snapshot-form"
                  onSubmit={(event: FormEvent) => {
                    event.preventDefault();
                    if (!snapshotMetricIssue) createMetricSnapshot.mutate();
                  }}
                >
                  <label className="wb-field">
                    <span>指标定义</span>
                    <select
                      className="wb-input"
                      value={metricSnapshotBinding}
                      onChange={(event) => {
                        const selected = metricCatalog.data?.find(
                          (metric) =>
                            `${metric.metricCode}:${metric.revisionNumber}` ===
                            event.target.value,
                        );
                        setMetricSnapshotBinding(event.target.value);
                        if (selected) setMetricSnapshotKey(selected.metricCode);
                      }}
                      required
                    >
                      <option value="">选择 live_session 指标</option>
                      {metricCatalog.data
                        ?.filter((metric) => metric.grain === "live_session")
                        .map((metric) => (
                          <option
                            key={`${metric.metricCode}:${metric.revisionNumber}`}
                            value={`${metric.metricCode}:${metric.revisionNumber}`}
                          >
                            {metricCatalogLabel(metric)}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="wb-field">
                    <span>归因指标名</span>
                    <input
                      className="wb-input"
                      value={metricSnapshotKey}
                      onChange={(event) => setMetricSnapshotKey(event.target.value)}
                      required
                    />
                  </label>
                  <label className="wb-field">
                    <span>事件时间时钟</span>
                    <input
                      className="wb-input"
                      value={metricEventTimeClock}
                      onChange={(event) => setMetricEventTimeClock(event.target.value)}
                      required
                    />
                  </label>
                  {snapshotMetric?.aggregation !== "count" &&
                  snapshotMetric?.aggregation !== "ratio" ? (
                    <label className="wb-field">
                      <span>数值 JSON Pointer</span>
                      <input
                        className="wb-input"
                        placeholder="/amount"
                        value={metricValuePointer}
                        onChange={(event) => setMetricValuePointer(event.target.value)}
                        required
                      />
                    </label>
                  ) : null}
                  {snapshotMetric?.aggregation === "ratio" ? (
                    <>
                      <label className="wb-field">
                        <span>分子 JSON Pointer</span>
                        <input
                          className="wb-input"
                          placeholder="/purchases"
                          value={metricNumeratorPointer}
                          onChange={(event) =>
                            setMetricNumeratorPointer(event.target.value)
                          }
                          required
                        />
                      </label>
                      <label className="wb-field">
                        <span>分母 JSON Pointer</span>
                        <input
                          className="wb-input"
                          placeholder="/visitors"
                          value={metricDenominatorPointer}
                          onChange={(event) =>
                            setMetricDenominatorPointer(event.target.value)
                          }
                          required
                        />
                      </label>
                    </>
                  ) : null}
                  <button
                    className="wb-button wb-button-primary"
                    disabled={createMetricSnapshot.isPending || Boolean(snapshotMetricIssue)}
                  >
                    <ChartNoAxesCombined size={15} aria-hidden="true" />
                    生成冻结快照
                  </button>
                </form>
                {snapshotMetricIssue ? (
                  <InlineNotice tone="warning" title="快照待补全">
                    {snapshotMetricIssue}
                  </InlineNotice>
                ) : null}
                {metricSnapshots.isLoading ? <LoadingBlock label="正在读取指标快照" /> : null}
                {metricSnapshots.error ? (
                  <InlineNotice tone="danger" title="指标快照读取失败">
                    {errorText(metricSnapshots.error)}
                  </InlineNotice>
                ) : null}
                {metricSnapshots.data?.length ? (
                  <div className="operations-metric-snapshot-list">
                    {metricSnapshots.data.map((snapshot) => (
                      <article key={snapshot.snapshotCode}>
                        <div>
                          <strong>
                            {snapshot.metricKey}: {snapshot.value?.toFixed(4) ?? "数据不足"}
                          </strong>
                          <small>
                            {snapshot.metricCode} r{snapshot.metricRevision} · {snapshot.aggregation} · {snapshot.sourceEventCount} 个事件 · {snapshot.eventTimeClock}
                          </small>
                          <code>{snapshot.snapshotCode} · {snapshot.fingerprintSha256.slice(0, 12)}</code>
                        </div>
                        <div>
                          <StatusBadge
                            label={snapshot.status}
                            tone={snapshot.status === "ready" ? "success" : "warning"}
                          />
                          {snapshot.sourceBatches.map((batch) => (
                            <small key={batch.batchCode}>
                              {batch.batchCode} · {batch.includedEventCount} · {batch.sourceChecksum?.slice(0, 10) ?? "无校验和"}
                            </small>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : !metricSnapshots.isLoading && !metricSnapshots.error ? (
                  <EmptyBlock icon={ChartNoAxesCombined} title="尚未冻结会话指标" />
                ) : null}
              </section>
            ) : null}
          </>
        ) : (
          <div className="operations-list">
            <ReportComparisonPanel reports={reports.data ?? []} />
            {reports.data?.map((report) => (
              <div key={report.reportCode}>
                <div className="operations-list-content">
                  <strong>
                    {report.metricKey} · {report.evidenceLevel}
                  </strong>
                  <code>{report.reportCode}</code>
                  <small>
                    {report.groups
                      .map(
                        (group) =>
                          `${group.displayLabel}: ${group.average.toFixed(2)} (${group.sampleSize}) · ${group.sourceEvidence.exposureCount ? `实际展示 ${group.sourceEvidence.exposureCount} 段` : "仅会话指标"}`,
                      )
                      .join(" / ")}
                  </small>
                  <small>
                    指标定义状态：{report.metadata.metricDefinitionState}
                  </small>
                  <small>
                    实际展示场次 {report.metadata.observedSessionCount}/
                    {report.metadata.selectedSessionCount} · 指标粒度{" "}
                    {report.metadata.metricGrain}
                  </small>
                  <small>
                    {report.metricDefinitionRef
                      ? `指标定义快照：${report.metricDefinitionRef.name ?? report.metricDefinitionRef.metricCode} · ${report.metricDefinitionRef.metricCode} r${report.metricDefinitionRef.revisionNumber}`
                      : "指标定义快照：未绑定（手工或跨修订指标）"}
                  </small>
                  <small>
                    运行状态：{report.status} · 输入指纹 {report.fingerprintSha256?.slice(0, 12) ?? "历史报告未冻结"}
                    {report.supersedesReportCode
                      ? ` · 基于 ${report.supersedesReportCode} 复算`
                      : ""}
                  </small>
                  <ReportEvidencePanel report={report} />
                  {report.qualitySnapshot.reasons.length ? (
                    <InlineNotice tone="warning" title="证据尚不足以发布">
                      {report.qualitySnapshot.reasons.join("、")}
                    </InlineNotice>
                  ) : null}
                  {report.measuredSceneAllocations.length ? (
                    <div className="operations-scene-allocations operations-measured-scene-allocations">
                      <header>
                        <strong>场景级实测值（事件时刻）</strong>
                        <small>
                          已分配 {report.measuredSceneAllocationSummary.allocatedBucketCount}/
                          {report.measuredSceneAllocationSummary.candidateBucketCount} 个冻结指标桶 · 描述性
                        </small>
                      </header>
                      <ol>
                        {report.measuredSceneAllocations.map((allocation) => (
                          <li key={`${allocation.planCode}:${allocation.sceneCode}:measured`}>
                            <span>
                              <code>{allocation.sceneCode}</code>
                              <small>
                                {allocation.planCode} · {allocation.aggregation} · {allocation.eventCount} 个事件 · {allocation.sourceSnapshotCodes.map((code) => code.slice(0, 12)).join("、")}{allocation.sourceTimeMappingCodes.length ? ` · 对齐 ${allocation.sourceTimeMappingCodes.join("、")}` : " · session_utc"}
                              </small>
                            </span>
                            <strong>
                              {allocation.measuredMetricValue?.toFixed(2) ?? "数据不足"}
                            </strong>
                          </li>
                        ))}
                      </ol>
                      {report.measuredSceneAllocationSummary.unallocatedBucketCount ||
                      report.measuredSceneAllocationSummary.sessionOnlyBucketCount ? (
                        <small className="operations-measured-scene-footnote">
                          未落入展示区间 {report.measuredSceneAllocationSummary.unallocatedBucketCount} · 仅会话级 {report.measuredSceneAllocationSummary.sessionOnlyBucketCount}
                        </small>
                      ) : null}
                      {report.measuredSceneAllocationSummary.timeMappedBucketCount ||
                      report.measuredSceneAllocationSummary.timeMappingMissingBucketCount ||
                      report.measuredSceneAllocationSummary.timeMappingClockMismatchBucketCount ||
                      report.measuredSceneAllocationSummary.outsideTimeMappingCoverageBucketCount ? (
                        <small className="operations-measured-scene-footnote">
                          来源时钟已对齐 {report.measuredSceneAllocationSummary.timeMappedBucketCount} · 未建立对齐 {report.measuredSceneAllocationSummary.timeMappingMissingBucketCount} · 时钟不匹配 {report.measuredSceneAllocationSummary.timeMappingClockMismatchBucketCount} · 超出覆盖 {report.measuredSceneAllocationSummary.outsideTimeMappingCoverageBucketCount}
                        </small>
                      ) : null}
                    </div>
                  ) : null}
                  {report.sceneAllocations.length ? (
                    <div className="operations-scene-allocations">
                      <header>
                        <strong>场景级估算（观察时长比例）</strong>
                        <small>会话级指标按已观察的实际展示时长分摊，不代表场景真实归因或因果效果。</small>
                      </header>
                      <ol>
                        {report.sceneAllocations.map((allocation) => (
                          <li key={`${allocation.planCode}:${allocation.sceneCode}`}>
                            <span><code>{allocation.sceneCode}</code><small>{allocation.planCode} · 已观察 {allocation.observedDurationSeconds.toFixed(1)} 秒 · {allocation.sourceSessionCount} 场</small></span>
                            <strong>{allocation.estimatedMetricValue.toFixed(2)}</strong>
                          </li>
                        ))}
                      </ol>
                    </div>
                  ) : null}
                  <div className="wb-actions">
                    <button
                      type="button"
                      className="wb-button"
                      disabled={rerunReport.isPending}
                      onClick={() => rerunReport.mutate(report.reportCode)}
                    >
                      <RotateCw size={15} aria-hidden="true" />
                      按当前证据复算
                    </button>
                    {report.status === "review_required" ? (
                      <button
                        type="button"
                        className="wb-button wb-button-primary"
                        disabled={publishReport.isPending}
                        onClick={() => publishReport.mutate(report.reportCode)}
                      >
                        发布描述性结果
                      </button>
                    ) : null}
                  </div>
                </div>
                <StatusBadge
                  label={
                    report.status === "published_descriptive"
                      ? "已发布 · 描述性"
                      : report.status === "review_required"
                        ? "待人工发布 · 描述性"
                        : report.status === "insufficient_data"
                          ? "证据不足 · 描述性"
                          : report.metadata.observedSessionCount
                            ? "描述性 · 有展示证据"
                            : "描述性 · 无展示证据"
                  }
                  tone={
                    report.status === "insufficient_data"
                      ? "warning"
                      : report.status === "published_descriptive" ||
                          report.metadata.observedSessionCount
                        ? "info"
                        : "warning"
                  }
                />
              </div>
            ))}
            {schedules.data?.map((schedule) => (
              <div key={schedule.scheduleCode}>
                <span>
                  <strong>{schedule.title}</strong>
                  <code>{schedule.scheduleCode}</code>
                  <small>
                    {schedule.roomId} · {schedule.startsAt}
                  </small>
                </span>
                <StatusBadge
                  label={schedule.status === "conflict" ? "冲突" : "仅计划"}
                  tone={schedule.status === "conflict" ? "danger" : "info"}
                />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

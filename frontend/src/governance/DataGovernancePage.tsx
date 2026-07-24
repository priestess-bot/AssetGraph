import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, FileDiff, FilePlus2, UsersRound } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import {
  dataGovernanceApi,
  type DataContractRevision,
  type MetricRevision,
} from "./dataApi";

type CatalogKind = "metrics" | "contracts";

interface MetricEditorValues {
  code: string;
  owner: string;
  name: string;
  description: string;
  grain: string;
  unit: string;
  currency: string;
  valueType: string;
  aggregation: string;
  numerator: string;
  denominator: string;
  eventTimeField: string;
  timezone: string;
  dayBoundary: string;
  dimensions: string;
  deduplicationKeys: string;
  refundWindowDays: string;
  contractRefs: string;
  nullRule: string;
  outlierRule: string;
  schemaCompatibility: string;
  qualitySlo: string;
  activate: boolean;
  expectedRevision: number;
}

interface ContractEditorValues {
  code: string;
  revision: string;
  owner: string;
  sourceSystem: string;
  schemaVersion: string;
  jsonSchema: string;
  eventIdPath: string;
  eventTimePath: string;
  operationPath: string;
  primaryKeys: string;
  operations: string;
  maxLateness: string;
  maxFutureSkew: string;
  acceptedRevisions: string;
  enumMappings: string;
  fieldClassifications: string;
  expectedVolume: string;
  qualitySlo: string;
  activate: boolean;
}

const EMPTY_METRIC: MetricEditorValues = {
  code: "", owner: "console_operator", name: "", description: "", grain: "live_session", unit: "count", currency: "", valueType: "integer", aggregation: "count", numerator: "", denominator: "", eventTimeField: "event_time", timezone: "Asia/Shanghai", dayBoundary: "00:00", dimensions: "", deduplicationKeys: "", refundWindowDays: "", contractRefs: "", nullRule: "{}", outlierRule: "{}", schemaCompatibility: "{}", qualitySlo: "{}", activate: true, expectedRevision: 0,
};

const EMPTY_CONTRACT: ContractEditorValues = {
  code: "", revision: "1", owner: "console_operator", sourceSystem: "", schemaVersion: "event.v1", jsonSchema: '{\n  "type": "object",\n  "properties": {},\n  "additionalProperties": false\n}', eventIdPath: "/event_id", eventTimePath: "/event_time", operationPath: "/operation", primaryKeys: "", operations: "insert, upsert", maxLateness: "3600", maxFutureSkew: "60", acceptedRevisions: "1", enumMappings: "{}", fieldClassifications: "{}", expectedVolume: "{}", qualitySlo: "{}", activate: true,
};

function splitList(value: string): string[] {
  return Array.from(new Set(value.split(/\n|,/).map((item) => item.trim()).filter(Boolean)));
}

function jsonObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value || "{}");
  } catch {
    throw new Error(`${label} 必须是 JSON 对象`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(`${label} 必须是 JSON 对象`);
  return parsed as Record<string, unknown>;
}

function contractRefs(value: string): Array<Record<string, unknown>> {
  return splitList(value).map((item) => {
    const [code, revision] = item.split("@").map((part) => part.trim());
    const parsedRevision = Number(revision);
    if (!code || !Number.isInteger(parsedRevision) || parsedRevision < 1) {
      throw new Error("事件契约引用格式为 contract_code@revision，每行一项");
    }
    return { code, revision: parsedRevision };
  });
}

function stringify(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

function metricEditor(metric?: MetricRevision): MetricEditorValues {
  if (!metric) return EMPTY_METRIC;
  return {
    code: metric.metricCode,
    owner: metric.ownerPrincipal,
    name: metric.name,
    description: metric.description,
    grain: metric.grain ?? "",
    unit: metric.unit,
    currency: metric.currency ?? "",
    valueType: metric.valueType,
    aggregation: metric.aggregation,
    numerator: metric.numeratorExpression ?? "",
    denominator: metric.denominatorExpression ?? "",
    eventTimeField: metric.eventTimeField ?? "",
    timezone: metric.timezone ?? "",
    dayBoundary: metric.businessDayBoundary ?? "00:00",
    dimensions: metric.dimensions.join("\n"),
    deduplicationKeys: metric.deduplicationKeys.join("\n"),
    refundWindowDays: metric.refundWindowDays === undefined ? "" : String(metric.refundWindowDays),
    contractRefs: metric.eventContractRefs.map((reference) => `${typeof reference.code === "string" ? reference.code : ""}@${typeof reference.revision === "number" ? reference.revision : ""}`).filter((value) => value !== "@").join("\n"),
    nullRule: stringify(metric.nullRule),
    outlierRule: stringify(metric.outlierRule),
    schemaCompatibility: stringify(metric.schemaCompatibility),
    qualitySlo: stringify(metric.qualitySlo),
    activate: true,
    expectedRevision: metric.revisionNumber,
  };
}

function contractEditor(contract?: DataContractRevision): ContractEditorValues {
  if (!contract) return EMPTY_CONTRACT;
  const operations = Array.isArray(contract.upsertDeleteSemantics.allowed_operations)
    ? contract.upsertDeleteSemantics.allowed_operations.filter((item): item is string => typeof item === "string").join(", ")
    : "";
  const accepted = Array.isArray(contract.compatibilityWindow.accepted_revisions)
    ? contract.compatibilityWindow.accepted_revisions.filter((item): item is number => typeof item === "number").join(", ")
    : "";
  return {
    code: contract.contractCode,
    revision: String(contract.revisionNumber + 1),
    owner: contract.ownerPrincipal,
    sourceSystem: contract.sourceSystem,
    schemaVersion: contract.schemaVersion,
    jsonSchema: stringify(contract.jsonSchema),
    eventIdPath: contract.eventIdPath,
    eventTimePath: contract.eventTimePath ?? "",
    operationPath: contract.operationPath ?? "",
    primaryKeys: contract.primaryKeyPaths.join("\n"),
    operations,
    maxLateness: String(contract.latenessPolicy.max_lateness_seconds ?? ""),
    maxFutureSkew: String(contract.latenessPolicy.max_future_clock_skew_seconds ?? ""),
    acceptedRevisions: accepted,
    enumMappings: stringify(contract.enumMappings),
    fieldClassifications: stringify(contract.fieldClassifications),
    expectedVolume: stringify(contract.expectedVolume),
    qualitySlo: stringify(contract.qualitySlo),
    activate: true,
  };
}

function statusTone(status: string): "neutral" | "success" | "warning" | "danger" {
  if (status === "active") return "success";
  if (status === "draft") return "warning";
  if (status === "retired" || status === "deprecated") return "danger";
  return "neutral";
}

function changedFields(current: Record<string, unknown>, previous?: Record<string, unknown>): string[] {
  if (!previous) return [];
  return Object.keys(current).filter((key) => JSON.stringify(current[key]) !== JSON.stringify(previous[key]));
}

function errorMessage(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

function MetricForm({ values, setValues, pending, onSubmit }: {
  values: MetricEditorValues;
  setValues: (next: MetricEditorValues) => void;
  pending: boolean;
  onSubmit: () => void;
}) {
  const update = (key: keyof MetricEditorValues, value: string | boolean) => setValues({ ...values, [key]: value } as MetricEditorValues);
  return <form className="governance-form" onSubmit={(event: FormEvent) => { event.preventDefault(); onSubmit(); }}>
    <div className="wb-form-grid">
      <label className="wb-field"><span>指标编码</span><input className="wb-input" value={values.code} onChange={(event) => update("code", event.target.value)} required /></label>
      <label className="wb-field"><span>Owner</span><input className="wb-input" value={values.owner} onChange={(event) => update("owner", event.target.value)} required /></label>
      <label className="wb-field"><span>指标名称</span><input className="wb-input" value={values.name} onChange={(event) => update("name", event.target.value)} required /></label>
      <label className="wb-field"><span>统计粒度</span><input className="wb-input" value={values.grain} onChange={(event) => update("grain", event.target.value)} required /></label>
      <label className="wb-field wide"><span>指标含义</span><textarea className="wb-textarea" value={values.description} onChange={(event) => update("description", event.target.value)} required /></label>
      <label className="wb-field"><span>单位</span><input className="wb-input" value={values.unit} onChange={(event) => update("unit", event.target.value)} required /></label>
      <label className="wb-field"><span>值类型</span><select className="wb-select" value={values.valueType} onChange={(event) => update("valueType", event.target.value)}><option value="integer">integer</option><option value="decimal">decimal</option><option value="duration_ms">duration_ms</option><option value="currency">currency</option><option value="ratio">ratio</option></select></label>
      <label className="wb-field"><span>聚合方式</span><select className="wb-select" value={values.aggregation} onChange={(event) => update("aggregation", event.target.value)}><option value="count">count</option><option value="sum">sum</option><option value="average">average</option><option value="min">min</option><option value="max">max</option><option value="ratio">ratio</option><option value="last">last</option></select></label>
      <label className="wb-field"><span>币种</span><input className="wb-input" value={values.currency} onChange={(event) => update("currency", event.target.value.toUpperCase())} placeholder="仅 currency" maxLength={3} /></label>
      <label className="wb-field"><span>事件时间字段</span><input className="wb-input" value={values.eventTimeField} onChange={(event) => update("eventTimeField", event.target.value)} required /></label>
      <label className="wb-field"><span>业务时区</span><input className="wb-input" value={values.timezone} onChange={(event) => update("timezone", event.target.value)} required /></label>
      <label className="wb-field"><span>业务日边界</span><input className="wb-input" value={values.dayBoundary} onChange={(event) => update("dayBoundary", event.target.value)} placeholder="00:00" required /></label>
      <label className="wb-field"><span>维度</span><textarea className="wb-textarea" value={values.dimensions} onChange={(event) => update("dimensions", event.target.value)} placeholder="每行一项" /></label>
      <label className="wb-field"><span>去重键</span><textarea className="wb-textarea" value={values.deduplicationKeys} onChange={(event) => update("deduplicationKeys", event.target.value)} placeholder="每行一项" required /></label>
      <label className="wb-field"><span>退款窗口（天）</span><input className="wb-input" type="number" min="0" value={values.refundWindowDays} onChange={(event) => update("refundWindowDays", event.target.value)} /></label>
      <label className="wb-field"><span>契约引用</span><textarea className="wb-textarea" value={values.contractRefs} onChange={(event) => update("contractRefs", event.target.value)} placeholder="contract_code@revision，每行一项" required /></label>
      {values.aggregation === "ratio" ? <><label className="wb-field"><span>分子表达式</span><input className="wb-input" value={values.numerator} onChange={(event) => update("numerator", event.target.value)} required /></label><label className="wb-field"><span>分母表达式</span><input className="wb-input" value={values.denominator} onChange={(event) => update("denominator", event.target.value)} required /></label></> : null}
      <label className="wb-field"><span>空值规则 JSON</span><textarea className="wb-textarea" value={values.nullRule} onChange={(event) => update("nullRule", event.target.value)} required /></label>
      <label className="wb-field"><span>异常值规则 JSON</span><textarea className="wb-textarea" value={values.outlierRule} onChange={(event) => update("outlierRule", event.target.value)} required /></label>
      <label className="wb-field"><span>Schema 兼容规则 JSON</span><textarea className="wb-textarea" value={values.schemaCompatibility} onChange={(event) => update("schemaCompatibility", event.target.value)} required /></label>
      <label className="wb-field"><span>质量 SLO JSON</span><textarea className="wb-textarea" value={values.qualitySlo} onChange={(event) => update("qualitySlo", event.target.value)} required /></label>
    </div>
    <label className="governance-checkbox"><input type="checkbox" checked={values.activate} onChange={(event) => update("activate", event.target.checked)} /><span>创建后设为现行版本</span></label>
    <div className="wb-form-actions"><button className="wb-button wb-button-primary" disabled={pending}><FilePlus2 size={15} aria-hidden="true" />{values.expectedRevision ? `创建 r${values.expectedRevision + 1}` : "创建指标 r1"}</button></div>
  </form>;
}

function ContractForm({ values, setValues, pending, onSubmit }: {
  values: ContractEditorValues;
  setValues: (next: ContractEditorValues) => void;
  pending: boolean;
  onSubmit: () => void;
}) {
  const update = (key: keyof ContractEditorValues, value: string | boolean) => setValues({ ...values, [key]: value } as ContractEditorValues);
  return <form className="governance-form" onSubmit={(event: FormEvent) => { event.preventDefault(); onSubmit(); }}>
    <div className="wb-form-grid">
      <label className="wb-field"><span>契约编码</span><input className="wb-input" value={values.code} onChange={(event) => update("code", event.target.value)} required /></label>
      <label className="wb-field"><span>新修订号</span><input className="wb-input" type="number" min="1" value={values.revision} onChange={(event) => update("revision", event.target.value)} required /></label>
      <label className="wb-field"><span>Owner</span><input className="wb-input" value={values.owner} onChange={(event) => update("owner", event.target.value)} required /></label>
      <label className="wb-field"><span>来源系统</span><input className="wb-input" value={values.sourceSystem} onChange={(event) => update("sourceSystem", event.target.value)} required /></label>
      <label className="wb-field"><span>Schema 版本</span><input className="wb-input" value={values.schemaVersion} onChange={(event) => update("schemaVersion", event.target.value)} placeholder="commerce-event.v1" required /></label>
      <label className="wb-field"><span>主键路径</span><textarea className="wb-textarea" value={values.primaryKeys} onChange={(event) => update("primaryKeys", event.target.value)} placeholder="/order_id，每行一项" required /></label>
      <label className="wb-field wide"><span>JSON Schema</span><textarea className="wb-textarea governance-code" value={values.jsonSchema} onChange={(event) => update("jsonSchema", event.target.value)} required /></label>
      <label className="wb-field"><span>事件 ID 路径</span><input className="wb-input" value={values.eventIdPath} onChange={(event) => update("eventIdPath", event.target.value)} required /></label>
      <label className="wb-field"><span>事件时间路径</span><input className="wb-input" value={values.eventTimePath} onChange={(event) => update("eventTimePath", event.target.value)} /></label>
      <label className="wb-field"><span>操作路径</span><input className="wb-input" value={values.operationPath} onChange={(event) => update("operationPath", event.target.value)} /></label>
      <label className="wb-field"><span>允许操作</span><input className="wb-input" value={values.operations} onChange={(event) => update("operations", event.target.value)} placeholder="insert, upsert, delete" required /></label>
      <label className="wb-field"><span>最大迟到秒数</span><input className="wb-input" type="number" min="0" value={values.maxLateness} onChange={(event) => update("maxLateness", event.target.value)} required /></label>
      <label className="wb-field"><span>最大未来时钟偏差秒数</span><input className="wb-input" type="number" min="0" value={values.maxFutureSkew} onChange={(event) => update("maxFutureSkew", event.target.value)} required /></label>
      <label className="wb-field"><span>兼容修订号</span><input className="wb-input" value={values.acceptedRevisions} onChange={(event) => update("acceptedRevisions", event.target.value)} placeholder="1, 2" required /></label>
      <label className="wb-field"><span>枚举映射 JSON</span><textarea className="wb-textarea" value={values.enumMappings} onChange={(event) => update("enumMappings", event.target.value)} required /></label>
      <label className="wb-field"><span>字段分类 JSON</span><textarea className="wb-textarea" value={values.fieldClassifications} onChange={(event) => update("fieldClassifications", event.target.value)} required /></label>
      <label className="wb-field"><span>预期量级 JSON</span><textarea className="wb-textarea" value={values.expectedVolume} onChange={(event) => update("expectedVolume", event.target.value)} required /></label>
      <label className="wb-field"><span>质量 SLO JSON</span><textarea className="wb-textarea" value={values.qualitySlo} onChange={(event) => update("qualitySlo", event.target.value)} required /></label>
    </div>
    <label className="governance-checkbox"><input type="checkbox" checked={values.activate} onChange={(event) => update("activate", event.target.checked)} /><span>创建后设为活动契约</span></label>
    <div className="wb-form-actions"><button className="wb-button wb-button-primary" disabled={pending}><FilePlus2 size={15} aria-hidden="true" />创建契约修订</button></div>
  </form>;
}

export function DataGovernancePage() {
  const client = useQueryClient();
  const [kind, setKind] = useState<CatalogKind>("metrics");
  const [selectedMetricCode, setSelectedMetricCode] = useState<string>();
  const [selectedContractCode, setSelectedContractCode] = useState<string>();
  const [showMetricForm, setShowMetricForm] = useState(false);
  const [showContractForm, setShowContractForm] = useState(false);
  const [metricValues, setMetricValues] = useState<MetricEditorValues>(EMPTY_METRIC);
  const [contractValues, setContractValues] = useState<ContractEditorValues>(EMPTY_CONTRACT);
  const [formError, setFormError] = useState<string>();
  const metrics = useQuery({ queryKey: ["data-governance", "metrics"], queryFn: dataGovernanceApi.listMetrics });
  const contracts = useQuery({ queryKey: ["data-governance", "contracts"], queryFn: dataGovernanceApi.listContracts });
  const selectedMetric = metrics.data?.find((item) => item.metricCode === selectedMetricCode) ?? metrics.data?.[0];
  const selectedContract = contracts.data?.find((item) => item.contractCode === selectedContractCode) ?? contracts.data?.[0];
  const metricRevisions = useQuery({ queryKey: ["data-governance", "metric-revisions", selectedMetric?.metricCode], queryFn: () => dataGovernanceApi.listMetricRevisions(selectedMetric!.metricCode), enabled: Boolean(selectedMetric) });
  const contractRevisions = useQuery({ queryKey: ["data-governance", "contract-revisions", selectedContract?.contractCode], queryFn: () => dataGovernanceApi.listContractRevisions(selectedContract!.contractCode), enabled: Boolean(selectedContract) });
  const consumers = useQuery({ queryKey: ["data-governance", "contract-consumers", selectedContract?.contractCode], queryFn: () => dataGovernanceApi.listContractConsumers(selectedContract!.contractCode), enabled: Boolean(selectedContract) });

  useEffect(() => {
    if (!selectedMetricCode && metrics.data?.[0]) setSelectedMetricCode(metrics.data[0].metricCode);
  }, [metrics.data, selectedMetricCode]);
  useEffect(() => {
    if (!selectedContractCode && contracts.data?.[0]) setSelectedContractCode(contracts.data[0].contractCode);
  }, [contracts.data, selectedContractCode]);

  const metricMutation = useMutation({
    mutationFn: () => {
      const definition = {
        name: metricValues.name.trim(), description: metricValues.description.trim(), grain: metricValues.grain.trim(), unit: metricValues.unit.trim(), currency: metricValues.currency.trim() || undefined,
        value_type: metricValues.valueType, aggregation: metricValues.aggregation, numerator_expression: metricValues.numerator.trim() || undefined, denominator_expression: metricValues.denominator.trim() || undefined,
        event_time_field: metricValues.eventTimeField.trim(), timezone: metricValues.timezone.trim(), business_day_boundary: metricValues.dayBoundary.trim(), dimensions: splitList(metricValues.dimensions), deduplication_keys: splitList(metricValues.deduplicationKeys),
        refund_window_days: metricValues.refundWindowDays ? Number(metricValues.refundWindowDays) : undefined, event_contract_refs: contractRefs(metricValues.contractRefs), null_rule: jsonObject(metricValues.nullRule, "空值规则"), outlier_rule: jsonObject(metricValues.outlierRule, "异常值规则"), schema_compatibility: jsonObject(metricValues.schemaCompatibility, "Schema 兼容规则"), quality_slo: jsonObject(metricValues.qualitySlo, "质量 SLO"),
      };
      return dataGovernanceApi.createMetricRevision(metricValues.code.trim(), { owner_principal: metricValues.owner.trim(), expected_revision: metricValues.expectedRevision, activate: metricValues.activate, definition });
    },
    onSuccess: (saved) => { setSelectedMetricCode(saved.metricCode); setShowMetricForm(false); setFormError(undefined); void client.invalidateQueries({ queryKey: ["data-governance", "metrics"] }); void client.invalidateQueries({ queryKey: ["data-governance", "metric-revisions", saved.metricCode] }); },
    onError: (error) => setFormError(errorMessage(error) ?? "指标修订未创建"),
  });
  const contractMutation = useMutation({
    mutationFn: () => {
      const revision = Number(contractValues.revision);
      if (!Number.isInteger(revision) || revision < 1) throw new Error("新修订号必须是正整数");
      const acceptedRevisions = splitList(contractValues.acceptedRevisions).map(Number);
      if (acceptedRevisions.some((item) => !Number.isInteger(item) || item < 1)) throw new Error("兼容修订号必须为正整数");
      const definition = {
        source_system: contractValues.sourceSystem.trim(), schema_version: contractValues.schemaVersion.trim(), json_schema: jsonObject(contractValues.jsonSchema, "JSON Schema"), event_id_path: contractValues.eventIdPath.trim(), event_time_path: contractValues.eventTimePath.trim() || undefined, operation_path: contractValues.operationPath.trim() || undefined,
        primary_key_paths: splitList(contractValues.primaryKeys), upsert_delete_semantics: { allowed_operations: splitList(contractValues.operations) }, lateness_policy: { max_lateness_seconds: Number(contractValues.maxLateness), max_future_clock_skew_seconds: Number(contractValues.maxFutureSkew) }, compatibility_window: { accepted_revisions: acceptedRevisions }, enum_mappings: jsonObject(contractValues.enumMappings, "枚举映射"), field_classifications: jsonObject(contractValues.fieldClassifications, "字段分类"), expected_volume: jsonObject(contractValues.expectedVolume, "预期量级"), quality_slo: jsonObject(contractValues.qualitySlo, "质量 SLO"),
      };
      return dataGovernanceApi.createContractRevision(contractValues.code.trim(), revision, { owner_principal: contractValues.owner.trim(), activate: contractValues.activate, definition });
    },
    onSuccess: (saved) => { setSelectedContractCode(saved.contractCode); setShowContractForm(false); setFormError(undefined); void client.invalidateQueries({ queryKey: ["data-governance", "contracts"] }); void client.invalidateQueries({ queryKey: ["data-governance", "contract-revisions", saved.contractCode] }); void client.invalidateQueries({ queryKey: ["data-governance", "contract-consumers", saved.contractCode] }); },
    onError: (error) => setFormError(errorMessage(error) ?? "数据契约修订未创建"),
  });

  const activeRevisions = kind === "metrics" ? metricRevisions.data : contractRevisions.data;
  const latestRevision = activeRevisions?.[0];
  const previousRevision = activeRevisions?.[1];
  const changes = useMemo(() => latestRevision && previousRevision ? changedFields(latestRevision as unknown as Record<string, unknown>, previousRevision as unknown as Record<string, unknown>) : [], [latestRevision, previousRevision]);
  const loading = metrics.isLoading || contracts.isLoading || (kind === "metrics" && metricRevisions.isLoading) || (kind === "contracts" && contractRevisions.isLoading);
  const queryError = errorMessage(metrics.error ?? contracts.error ?? metricRevisions.error ?? contractRevisions.error ?? consumers.error);

  if (loading) return <LoadingBlock label="正在读取数据治理目录" />;
  return <div className="governance-layout">
    <section className="wb-section governance-catalog">
      <SectionHeader kicker="DATA CATALOG" title="指标与契约" actions={<div className="wb-segmented" role="tablist" aria-label="数据治理目录"><button type="button" className={kind === "metrics" ? "active" : undefined} aria-selected={kind === "metrics"} onClick={() => setKind("metrics")}>指标</button><button type="button" className={kind === "contracts" ? "active" : undefined} aria-selected={kind === "contracts"} onClick={() => setKind("contracts")}>数据契约</button></div>} />
      <div className="governance-catalog-actions"><button className="wb-button" type="button" onClick={() => { setShowMetricForm(true); setShowContractForm(false); setMetricValues(EMPTY_METRIC); setFormError(undefined); }}><FilePlus2 size={14} aria-hidden="true" />新指标</button><button className="wb-button" type="button" onClick={() => { setShowContractForm(true); setShowMetricForm(false); setContractValues(EMPTY_CONTRACT); setFormError(undefined); }}><FilePlus2 size={14} aria-hidden="true" />新契约</button></div>
      <div className="governance-catalog-list">
        {kind === "metrics" ? metrics.data?.map((item) => <button type="button" key={item.metricCode} className={selectedMetric?.metricCode === item.metricCode ? "active" : undefined} onClick={() => { setSelectedMetricCode(item.metricCode); setShowMetricForm(false); }}><span><strong>{item.name}</strong><code>{item.metricCode} · r{item.revisionNumber}</code><small>{item.grain} · {item.unit}</small></span><StatusBadge label={item.status} tone={statusTone(item.status)} /></button>) : contracts.data?.map((item) => <button type="button" key={item.contractCode} className={selectedContract?.contractCode === item.contractCode ? "active" : undefined} onClick={() => { setSelectedContractCode(item.contractCode); setShowContractForm(false); }}><span><strong>{item.contractCode}</strong><code>{item.schemaVersion} · r{item.revisionNumber}</code><small>{item.sourceSystem}</small></span><StatusBadge label={item.status} tone={statusTone(item.status)} /></button>)}
        {kind === "metrics" && !metrics.data?.length ? <EmptyBlock icon={Database} title="尚无指标定义" detail="创建第一个可版本化的指标定义。" /> : null}
        {kind === "contracts" && !contracts.data?.length ? <EmptyBlock icon={Database} title="尚无活动数据契约" detail="创建来源 schema、迟到规则和质量目标。" /> : null}
      </div>
    </section>
    <section className="wb-section governance-detail">
      <SectionHeader kicker={kind === "metrics" ? "METRIC REVISION" : "SOURCE CONTRACT"} title={kind === "metrics" ? selectedMetric?.name ?? "指标详情" : selectedContract?.contractCode ?? "契约详情"} actions={kind === "metrics" && selectedMetric ? <button className="wb-button" type="button" onClick={() => { setMetricValues(metricEditor(selectedMetric)); setShowMetricForm(true); setShowContractForm(false); setFormError(undefined); }}><FilePlus2 size={14} aria-hidden="true" />基于当前修订</button> : kind === "contracts" && selectedContract ? <button className="wb-button" type="button" onClick={() => { setContractValues(contractEditor(selectedContract)); setShowContractForm(true); setShowMetricForm(false); setFormError(undefined); }}><FilePlus2 size={14} aria-hidden="true" />基于当前修订</button> : undefined} />
      {queryError ? <InlineNotice tone="danger" title="目录读取失败">{queryError}</InlineNotice> : null}
      {showMetricForm ? <div className="governance-form-panel"><h3>{metricValues.expectedRevision ? `创建 ${metricValues.code} 的新修订` : "创建指标定义"}</h3><MetricForm values={metricValues} setValues={setMetricValues} pending={metricMutation.isPending} onSubmit={() => { setFormError(undefined); metricMutation.mutate(); }} /></div> : null}
      {showContractForm ? <div className="governance-form-panel"><h3>{contractValues.revision === "1" ? "创建数据契约" : `创建 ${contractValues.code} 的新修订`}</h3><ContractForm values={contractValues} setValues={setContractValues} pending={contractMutation.isPending} onSubmit={() => { setFormError(undefined); contractMutation.mutate(); }} /></div> : null}
      {formError ? <InlineNotice tone="danger" title="修订未创建">{formError}</InlineNotice> : null}
      {!showMetricForm && !showContractForm && kind === "metrics" && selectedMetric ? <MetricDetail metric={selectedMetric} revisions={metricRevisions.data ?? []} changes={changes} /> : null}
      {!showMetricForm && !showContractForm && kind === "contracts" && selectedContract ? <ContractDetail contract={selectedContract} revisions={contractRevisions.data ?? []} consumers={consumers.data ?? []} changes={changes} /> : null}
      {!showMetricForm && !showContractForm && !(kind === "metrics" ? selectedMetric : selectedContract) ? <EmptyBlock icon={Database} title="选择或创建目录项" /> : null}
    </section>
  </div>;
}

function MetricDetail({ metric, revisions, changes }: { metric: MetricRevision; revisions: MetricRevision[]; changes: string[] }) {
  return <div className="governance-detail-body">
    <div className="governance-summary"><div><span>现行修订</span><strong>r{metric.revisionNumber}</strong></div><div><span>Owner</span><strong>{metric.ownerPrincipal}</strong></div><div><span>时间字段</span><strong>{metric.eventTimeField ?? "--"}</strong></div><div><span>质量 SLO</span><strong>{Object.keys(metric.qualitySlo).length ? "已定义" : "未定义"}</strong></div></div>
    <p className="governance-description">{metric.description}</p>
    <dl className="governance-properties"><div><dt>粒度</dt><dd>{metric.grain}</dd></div><div><dt>单位 / 类型</dt><dd>{metric.unit} / {metric.valueType}</dd></div><div><dt>聚合</dt><dd>{metric.aggregation}</dd></div><div><dt>时区 / 业务日</dt><dd>{metric.timezone} / {metric.businessDayBoundary}</dd></div><div><dt>维度</dt><dd>{metric.dimensions.join("、") || "--"}</dd></div><div><dt>去重键</dt><dd>{metric.deduplicationKeys.join("、")}</dd></div><div><dt>退款窗口</dt><dd>{metric.refundWindowDays === undefined ? "--" : `${metric.refundWindowDays} 天`}</dd></div><div><dt>契约引用</dt><dd>{metric.eventContractRefs.map((reference) => `${reference.code ?? "--"}@${reference.revision ?? "--"}`).join("、")}</dd></div></dl>
    <RevisionHistory revisions={revisions} changes={changes} />
    <JsonDetails title="质量与兼容规则" value={{ null_rule: metric.nullRule, outlier_rule: metric.outlierRule, schema_compatibility: metric.schemaCompatibility, quality_slo: metric.qualitySlo }} />
  </div>;
}

function ContractDetail({ contract, revisions, consumers, changes }: { contract: DataContractRevision; revisions: DataContractRevision[]; consumers: Array<{ metricCode: string; revisionNumber: number; status: string; ownerPrincipal: string; name: string }>; changes: string[] }) {
  return <div className="governance-detail-body">
    <div className="governance-summary"><div><span>活动修订</span><strong>r{contract.revisionNumber}</strong></div><div><span>来源系统</span><strong>{contract.sourceSystem}</strong></div><div><span>主键</span><strong>{contract.primaryKeyPaths.length}</strong></div><div><span>消费者</span><strong>{consumers.length}</strong></div></div>
    <dl className="governance-properties"><div><dt>Owner</dt><dd>{contract.ownerPrincipal}</dd></div><div><dt>Schema 版本</dt><dd>{contract.schemaVersion}</dd></div><div><dt>事件 ID 路径</dt><dd>{contract.eventIdPath}</dd></div><div><dt>事件时间路径</dt><dd>{contract.eventTimePath ?? "--"}</dd></div><div><dt>操作路径</dt><dd>{contract.operationPath ?? "--"}</dd></div><div><dt>允许操作</dt><dd>{Array.isArray(contract.upsertDeleteSemantics.allowed_operations) ? contract.upsertDeleteSemantics.allowed_operations.join("、") : "--"}</dd></div><div><dt>迟到规则</dt><dd>{stringify(contract.latenessPolicy)}</dd></div><div><dt>字段分类</dt><dd>{Object.entries(contract.fieldClassifications).map(([key, value]) => `${key}: ${value}`).join("、") || "--"}</dd></div></dl>
    <RevisionHistory revisions={revisions} changes={changes} />
    <section className="governance-consumers"><header><UsersRound size={15} aria-hidden="true" /><strong>指标消费者</strong></header>{consumers.length ? <ul>{consumers.map((consumer) => <li key={`${consumer.metricCode}:${consumer.revisionNumber}`}><span><strong>{consumer.name}</strong><code>{consumer.metricCode} · r{consumer.revisionNumber}</code></span><StatusBadge label={consumer.status} tone={statusTone(consumer.status)} /></li>)}</ul> : <span>当前没有指标修订引用此契约。</span>}</section>
    <JsonDetails title="Schema 与数据质量约束" value={{ json_schema: contract.jsonSchema, compatibility_window: contract.compatibilityWindow, enum_mappings: contract.enumMappings, expected_volume: contract.expectedVolume, quality_slo: contract.qualitySlo }} />
  </div>;
}

function RevisionHistory({ revisions, changes }: { revisions: Array<{ revisionNumber: number; status: string; createdAt?: string; fingerprintSha256: string }>; changes: string[] }) {
  return <section className="governance-history"><header><FileDiff size={15} aria-hidden="true" /><strong>修订与差异</strong></header>{changes.length ? <p>当前修订相对上一版变更：{changes.join("、")}</p> : revisions.length > 1 ? <p>当前修订与上一版无可见字段变化。</p> : <p>这是首个修订，尚无可比较版本。</p>}<ol>{revisions.map((revision) => <li key={revision.revisionNumber}><code>r{revision.revisionNumber}</code><StatusBadge label={revision.status} tone={statusTone(revision.status)} /><span>{formatDate(revision.createdAt)}</span><small>{revision.fingerprintSha256.slice(0, 12)}</small></li>)}</ol></section>;
}

function JsonDetails({ title, value }: { title: string; value: Record<string, unknown> }) {
  return <details className="governance-json"><summary>{title}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}

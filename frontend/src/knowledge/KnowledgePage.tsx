import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, FilePlus2, Search, XCircle } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { knowledgeApi, type ProductFactCard, type ProductFactCardContentInput } from "./api";

interface FactEditorValues {
  title: string;
  productName: string;
  productCode: string;
  brand: string;
  category: string;
  positioning: string;
  verifiedFacts: string;
  scenarios: string;
  assetKeywords: string;
  complianceNotes: string;
  sourceUrl: string;
  validFrom: string;
  validUntil: string;
  applicablePlatforms: string;
  changeReason: string;
  author: string;
}

const EMPTY_EDITOR: FactEditorValues = {
  title: "", productName: "", productCode: "", brand: "", category: "", positioning: "", verifiedFacts: "", scenarios: "", assetKeywords: "", complianceNotes: "", sourceUrl: "", validFrom: "", validUntil: "", applicablePlatforms: "", changeReason: "", author: "console_operator",
};

function lines(value: string): string[] {
  return Array.from(new Set(value.split(/\n|,/).map((item) => item.trim()).filter(Boolean)));
}

function joined(value: unknown): string {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").join("\n") : "";
}

function stringValue(content: Record<string, unknown>, key: string): string {
  return typeof content[key] === "string" ? content[key] : "";
}

function versionContent(card: ProductFactCard): Record<string, unknown> {
  const selected = card.versions.find((version) => version.versionNumber === card.currentApprovedVersion) ?? card.versions[0];
  return selected?.content ?? {};
}

function editorFrom(card: ProductFactCard): FactEditorValues {
  const content = versionContent(card);
  const sourceReference = Array.isArray(content.source_references) && content.source_references[0] && typeof content.source_references[0] === "object"
    ? content.source_references[0] as Record<string, unknown>
    : {};
  return {
    title: card.title,
    productName: stringValue(content, "product_name"),
    productCode: card.productCode ?? stringValue(content, "product_code"),
    brand: stringValue(content, "brand"),
    category: stringValue(content, "category"),
    positioning: stringValue(content, "positioning"),
    verifiedFacts: joined(content.verified_facts),
    scenarios: joined(content.scenarios),
    assetKeywords: joined(content.asset_keywords),
    complianceNotes: joined(content.compliance_notes),
    sourceUrl: typeof sourceReference.url === "string" ? sourceReference.url : "",
    validFrom: stringValue(content, "valid_from"),
    validUntil: stringValue(content, "valid_until"),
    applicablePlatforms: joined(content.applicable_platforms),
    changeReason: "补充已核验事实",
    author: "console_operator",
  };
}

function contentInput(values: FactEditorValues): ProductFactCardContentInput {
  return {
    product_name: values.productName.trim(),
    product_code: values.productCode.trim() || undefined,
    brand: values.brand.trim() || undefined,
    category: values.category.trim() || undefined,
    positioning: values.positioning.trim(),
    verified_facts: lines(values.verifiedFacts),
    scenarios: lines(values.scenarios),
    asset_keywords: lines(values.assetKeywords),
    compliance_notes: lines(values.complianceNotes),
    source_references: values.sourceUrl.trim() ? [{ kind: "url", url: values.sourceUrl.trim() }] : [],
    valid_from: values.validFrom.trim() || undefined,
    valid_until: values.validUntil.trim() || undefined,
    applicable_platforms: lines(values.applicablePlatforms),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未完成";
}

function versionTone(status: string): "neutral" | "success" | "warning" | "danger" {
  if (status === "approved") return "success";
  if (status === "draft") return "warning";
  if (status === "rejected") return "danger";
  return "neutral";
}

function FactEditor({ values, setValues, includeTitle, submitLabel, pending, onSubmit }: {
  values: FactEditorValues;
  setValues: (next: FactEditorValues) => void;
  includeTitle: boolean;
  submitLabel: string;
  pending: boolean;
  onSubmit: () => void;
}) {
  const update = (key: keyof FactEditorValues, value: string) => setValues({ ...values, [key]: value });
  return <form className="knowledge-editor" onSubmit={(event: FormEvent) => { event.preventDefault(); onSubmit(); }}>
    <div className="wb-form-grid">
      {includeTitle ? <label className="wb-field"><span>事实卡标题</span><input className="wb-input" value={values.title} onChange={(event) => update("title", event.target.value)} required /></label> : null}
      <label className="wb-field"><span>商品名称</span><input className="wb-input" value={values.productName} onChange={(event) => update("productName", event.target.value)} required /></label>
      <label className="wb-field"><span>商品编码</span><input className="wb-input" value={values.productCode} onChange={(event) => update("productCode", event.target.value)} /></label>
      <label className="wb-field"><span>品牌</span><input className="wb-input" value={values.brand} onChange={(event) => update("brand", event.target.value)} /></label>
      <label className="wb-field"><span>品类</span><input className="wb-input" value={values.category} onChange={(event) => update("category", event.target.value)} /></label>
      <label className="wb-field wide"><span>商品定位</span><textarea className="wb-textarea" value={values.positioning} onChange={(event) => update("positioning", event.target.value)} required /></label>
      <label className="wb-field wide"><span>已核验事实</span><textarea className="wb-textarea" value={values.verifiedFacts} onChange={(event) => update("verifiedFacts", event.target.value)} required placeholder="每行一项" /></label>
      <label className="wb-field"><span>适用场景</span><textarea className="wb-textarea" value={values.scenarios} onChange={(event) => update("scenarios", event.target.value)} placeholder="每行一项" /></label>
      <label className="wb-field"><span>素材关键词</span><textarea className="wb-textarea" value={values.assetKeywords} onChange={(event) => update("assetKeywords", event.target.value)} placeholder="每行一项" /></label>
      <label className="wb-field"><span>合规备注</span><textarea className="wb-textarea" value={values.complianceNotes} onChange={(event) => update("complianceNotes", event.target.value)} placeholder="每行一项" /></label>
      <label className="wb-field"><span>来源 URL</span><input className="wb-input" type="url" value={values.sourceUrl} onChange={(event) => update("sourceUrl", event.target.value)} /></label>
      <label className="wb-field"><span>有效起始时间</span><input className="wb-input" value={values.validFrom} onChange={(event) => update("validFrom", event.target.value)} placeholder="2026-07-25T00:00:00Z" /></label>
      <label className="wb-field"><span>有效结束时间</span><input className="wb-input" value={values.validUntil} onChange={(event) => update("validUntil", event.target.value)} placeholder="2026-12-31T23:59:59Z" /></label>
      <label className="wb-field"><span>适用平台</span><textarea className="wb-textarea" value={values.applicablePlatforms} onChange={(event) => update("applicablePlatforms", event.target.value)} placeholder="每行一项；留空表示不限制" /></label>
      <label className="wb-field"><span>变更说明</span><input className="wb-input" value={values.changeReason} onChange={(event) => update("changeReason", event.target.value)} required={!includeTitle} /></label>
      <label className="wb-field"><span>登记人</span><input className="wb-input" value={values.author} onChange={(event) => update("author", event.target.value)} required /></label>
    </div>
    <div className="wb-form-actions"><button className="wb-button wb-button-primary" disabled={pending || !values.productName.trim() || !values.positioning.trim() || !lines(values.verifiedFacts).length || (includeTitle && !values.title.trim())}><FilePlus2 size={15} aria-hidden="true" />{submitLabel}</button></div>
  </form>;
}

function VersionList({ card, activeVersion, onSelect }: { card: ProductFactCard; activeVersion?: number; onSelect: (version: number) => void }) {
  return <div className="knowledge-version-list">{card.versions.map((version) => <button type="button" key={version.versionCode} className={version.versionNumber === activeVersion ? "active" : undefined} onClick={() => onSelect(version.versionNumber)}><span><strong>v{version.versionNumber}</strong><small>{version.changeReason ?? "未填写变更说明"}</small><code>{version.createdBy ?? "未标注登记人"} · {formatDate(version.createdAt)}</code></span><StatusBadge label={version.status} tone={versionTone(version.status)} /></button>)}</div>;
}

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [selectedCode, setSelectedCode] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showRevision, setShowRevision] = useState(false);
  const [createValues, setCreateValues] = useState<FactEditorValues>(EMPTY_EDITOR);
  const [revisionValues, setRevisionValues] = useState<FactEditorValues>(EMPTY_EDITOR);
  const [selectedVersion, setSelectedVersion] = useState<number>();
  const [reviewer, setReviewer] = useState("console_reviewer");
  const [rejectionReason, setRejectionReason] = useState("");
  const cards = useQuery({ queryKey: ["product-fact-cards"], queryFn: knowledgeApi.listProductFactCards });
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return cards.data ?? [];
    return (cards.data ?? []).filter((card) => {
      const content = versionContent(card);
      return [card.factCardCode, card.title, card.productCode, stringValue(content, "product_name"), stringValue(content, "positioning"), joined(content.verified_facts)].join(" ").toLowerCase().includes(needle);
    });
  }, [cards.data, query]);
  const selected = (cards.data ?? []).find((card) => card.factCardCode === selectedCode) ?? filtered[0];
  const activeVersion = selected?.versions.find((version) => version.versionNumber === selectedVersion) ?? selected?.versions[0];
  const usage = useQuery({
    queryKey: ["product-fact-card-usage", selected?.factCardCode, activeVersion?.versionNumber],
    queryFn: () => knowledgeApi.listProductFactCardUsage(selected!.factCardCode, activeVersion!.versionNumber),
    enabled: Boolean(selected && activeVersion),
  });

  useEffect(() => {
    if (selected && selected.factCardCode !== selectedCode) setSelectedCode(selected.factCardCode);
  }, [selected, selectedCode]);
  useEffect(() => {
    if (selected && !selected.versions.some((version) => version.versionNumber === selectedVersion)) setSelectedVersion(selected.versions[0]?.versionNumber);
  }, [selected, selectedVersion]);

  const refresh = async (cardCode?: string) => {
    await queryClient.invalidateQueries({ queryKey: ["product-fact-cards"] });
    if (cardCode) setSelectedCode(cardCode);
  };
  const create = useMutation({
    mutationFn: () => knowledgeApi.createProductFactCard({ title: createValues.title.trim(), product_code: createValues.productCode.trim() || undefined, content: contentInput(createValues), change_reason: createValues.changeReason.trim() || undefined, created_by: createValues.author.trim() || undefined }),
    onSuccess: async (card) => { setCreateValues(EMPTY_EDITOR); setShowCreate(false); await refresh(card.factCardCode); },
  });
  const revise = useMutation({
    mutationFn: () => knowledgeApi.createProductFactCardVersion(selectedCode, { content: contentInput(revisionValues), change_reason: revisionValues.changeReason.trim(), created_by: revisionValues.author.trim() || undefined }),
    onSuccess: async () => { setShowRevision(false); await refresh(selectedCode); },
  });
  const approve = useMutation({ mutationFn: () => knowledgeApi.approveProductFactCardVersion(selectedCode, activeVersion?.versionNumber ?? 0, reviewer.trim()), onSuccess: async () => { await refresh(selectedCode); } });
  const reject = useMutation({ mutationFn: () => knowledgeApi.rejectProductFactCardVersion(selectedCode, activeVersion?.versionNumber ?? 0, reviewer.trim(), rejectionReason.trim()), onSuccess: async () => { setRejectionReason(""); await refresh(selectedCode); } });

  if (cards.isLoading) return <LoadingBlock />;
  return <div className="knowledge-layout">
    <aside className="wb-section knowledge-rail">
      <SectionHeader kicker="FACT CARDS" title="事实卡" actions={<button type="button" className="wb-button wb-button-primary" onClick={() => setShowCreate((current) => !current)}><FilePlus2 size={14} aria-hidden="true" />新建</button>} />
      {showCreate ? <div className="knowledge-create"><FactEditor values={createValues} setValues={setCreateValues} includeTitle submitLabel="创建草稿" pending={create.isPending} onSubmit={() => create.mutate()} />{create.error ? <InlineNotice tone="danger" title="事实卡创建失败">{errorMessage(create.error)}</InlineNotice> : null}</div> : null}
      <label className="asset-search"><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索事实卡" /></label>
      {cards.error ? <InlineNotice tone="danger" title="事实卡读取失败">{errorMessage(cards.error)}</InlineNotice> : filtered.length ? <div className="knowledge-card-list">{filtered.map((card) => <button type="button" key={card.factCardCode} className={card.factCardCode === selectedCode ? "active" : undefined} onClick={() => { setSelectedCode(card.factCardCode); setShowRevision(false); }}><span><strong>{card.title}</strong><small>{stringValue(versionContent(card), "product_name") || "未填写商品名称"}</small><code>{card.factCardCode}{card.currentApprovedVersion ? ` · 已批准 v${card.currentApprovedVersion}` : " · 尚无已批准版本"}</code></span><StatusBadge label={card.status} tone="info" /></button>)}</div> : <EmptyBlock icon={BookOpen} title="尚无事实卡" />}
    </aside>
    <main className="knowledge-main">{selected ? <>
      <section className="wb-section"><SectionHeader kicker={selected.factCardCode} title={selected.title} actions={<button type="button" className="wb-button" onClick={() => { setRevisionValues(editorFrom(selected)); setShowRevision((current) => !current); }}><FilePlus2 size={14} aria-hidden="true" />新建修订</button>} />
        <div className="knowledge-summary"><div><span>当前批准</span><strong>{selected.currentApprovedVersion ? `v${selected.currentApprovedVersion}` : "尚无"}</strong></div><div><span>商品</span><strong>{stringValue(versionContent(selected), "product_name") || "未填写"}</strong></div><div><span>定位</span><strong>{stringValue(versionContent(selected), "positioning") || "未填写"}</strong></div></div>
        {showRevision ? <div className="knowledge-create"><FactEditor values={revisionValues} setValues={setRevisionValues} includeTitle={false} submitLabel="保存新修订" pending={revise.isPending} onSubmit={() => revise.mutate()} />{revise.error ? <InlineNotice tone="danger" title="修订创建失败">{errorMessage(revise.error)}</InlineNotice> : null}</div> : null}
      </section>
      <section className="wb-section"><SectionHeader kicker="VERSIONS" title="版本与批准" />
        <VersionList card={selected} activeVersion={activeVersion?.versionNumber} onSelect={setSelectedVersion} />
        {activeVersion ? <div className="knowledge-version-detail"><div className="knowledge-version-heading"><div><span>{activeVersion.versionCode}</span><h3>v{activeVersion.versionNumber} 内容</h3></div><StatusBadge label={activeVersion.status} tone={versionTone(activeVersion.status)} /></div><dl><div><dt>已核验事实</dt><dd>{joined(activeVersion.content.verified_facts) || "未填写"}</dd></div><div><dt>适用场景</dt><dd>{joined(activeVersion.content.scenarios) || "未填写"}</dd></div><div><dt>适用平台</dt><dd>{joined(activeVersion.content.applicable_platforms) || "不限制"}</dd></div><div><dt>有效期</dt><dd>{stringValue(activeVersion.content, "valid_from") || "未限制"} 至 {stringValue(activeVersion.content, "valid_until") || "未限制"}</dd></div><div><dt>合规备注</dt><dd>{joined(activeVersion.content.compliance_notes) || "未填写"}</dd></div><div><dt>来源</dt><dd>{Array.isArray(activeVersion.content.source_references) && activeVersion.content.source_references.length ? JSON.stringify(activeVersion.content.source_references) : "未填写"}</dd></div></dl>{activeVersion.status === "draft" ? <div className="knowledge-review"><label className="wb-field"><span>审批人</span><input className="wb-input" value={reviewer} onChange={(event) => setReviewer(event.target.value)} required /></label><label className="wb-field"><span>驳回原因</span><input className="wb-input" value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} /></label><div className="wb-form-actions"><button type="button" className="wb-button wb-button-primary" disabled={approve.isPending || !reviewer.trim()} onClick={() => approve.mutate()}><CheckCircle2 size={15} aria-hidden="true" />批准版本</button><button type="button" className="wb-button" disabled={reject.isPending || !reviewer.trim() || !rejectionReason.trim()} onClick={() => reject.mutate()}><XCircle size={15} aria-hidden="true" />驳回版本</button></div>{approve.error || reject.error ? <InlineNotice tone="danger" title="版本状态更新失败">{errorMessage(approve.error ?? reject.error)}</InlineNotice> : null}</div> : null}</div> : null}
      </section>
      <section className="wb-section"><SectionHeader kicker="LINEAGE" title="使用记录" />
        {usage.isLoading ? <LoadingBlock label="正在读取使用记录" /> : usage.error ? <InlineNotice tone="danger" title="使用记录读取失败">{errorMessage(usage.error)}</InlineNotice> : usage.data?.length ? <div className="knowledge-usage-list">{usage.data.map((item) => <article key={`${item.objectType}:${item.objectCode}:${item.revisionNumber ?? "current"}`}><span><strong>{item.objectType}</strong><small>{item.relationType}</small><code>{item.objectCode}{item.revisionNumber ? ` · r${item.revisionNumber}` : ""} · {formatDate(item.createdAt)}</code></span><StatusBadge label={item.status} tone={versionTone(item.status)} /></article>)}</div> : <EmptyBlock icon={BookOpen} title="该版本尚未被使用" />}
      </section>
    </> : <EmptyBlock icon={BookOpen} title="选择事实卡" />}</main>
  </div>;
}

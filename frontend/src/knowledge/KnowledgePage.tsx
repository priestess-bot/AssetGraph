import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, FilePlus2, Search, XCircle } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { knowledgeApi, type ContentRule, type FactClaimLineage, type ProductFactCard, type ProductFactCardContentInput } from "./api";

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

function FactClaimLineagePanel({ claimCode }: { claimCode: string }) {
  const lineage = useQuery({
    queryKey: ["knowledge-fact-claim-lineage", claimCode],
    queryFn: () => knowledgeApi.getFactClaimLineage(claimCode),
  });
  const data: FactClaimLineage | undefined = lineage.data;

  return <section className="wb-section">
    <SectionHeader kicker="FACT LINEAGE" title="声明使用链" />
    {lineage.isLoading ? <LoadingBlock label="正在读取使用链" /> : lineage.error ? <InlineNotice tone="danger" title="使用链读取失败">{errorMessage(lineage.error)}</InlineNotice> : data ? <>
      <div className="knowledge-summary">
        <div><span>声明</span><strong>{data.claimStatus}</strong></div>
        <div><span>事实</span><strong>{data.factStatus}</strong></div>
        <div><span>来源</span><strong>{data.sourceStatus}</strong></div>
      </div>
      <div className="knowledge-lineage-source"><strong>{data.factTitle}</strong><code>{data.claimCode} · {data.sourceEvidenceCode}</code></div>
      {data.uses.length ? <div className="knowledge-usage-list">{data.uses.map((item) => <article key={`${item.relationType}:${item.objectType}:${item.objectCode}:${item.revisionNumber ?? "current"}`}><span><strong>{item.objectType}</strong><small>{item.relationType}</small><code>{item.objectCode}{item.revisionNumber ? ` · r${item.revisionNumber}` : ""} · {formatDate(item.createdAt)}</code></span><StatusBadge label={item.status} tone={versionTone(item.status)} /></article>)}</div> : <EmptyBlock icon={BookOpen} title="该声明尚未被内容修订固定引用" />}
    </> : null}
  </section>;
}

function ContentRuleWorkspace({ onShowFactCards, onShowEvidence }: { onShowFactCards: () => void; onShowEvidence: () => void }) {
  const client = useQueryClient();
  const [ruleKind, setRuleKind] = useState<ContentRule["ruleKind"]>("content_guidance");
  const [directive, setDirective] = useState<ContentRule["directive"]>("guidance");
  const [title, setTitle] = useState("");
  const [ruleText, setRuleText] = useState("");
  const [sourceCode, setSourceCode] = useState("");
  const [platforms, setPlatforms] = useState("");
  const [author, setAuthor] = useState("console_operator");
  const [reviewer, setReviewer] = useState("console_reviewer");
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const sources = useQuery({ queryKey: ["knowledge-source-evidences"], queryFn: knowledgeApi.listSourceEvidences });
  const rules = useQuery({ queryKey: ["knowledge-content-rules"], queryFn: knowledgeApi.listContentRules });
  const refresh = async () => client.invalidateQueries({ queryKey: ["knowledge-content-rules"] });
  const create = useMutation({
    mutationFn: () => knowledgeApi.createContentRule({
      rule_kind: ruleKind,
      directive,
      title: title.trim(),
      rule_text: ruleText.trim(),
      scope: platforms.trim() ? { platforms: lines(platforms) } : {},
      source_evidence_code: sourceCode || undefined,
      created_by: author.trim() || undefined,
    }),
    onSuccess: async () => { setTitle(""); setRuleText(""); setPlatforms(""); await refresh(); },
  });
  const approve = useMutation({ mutationFn: (code: string) => knowledgeApi.approveContentRule(code, reviewer.trim()), onSuccess: refresh });
  const reject = useMutation({ mutationFn: ({ code, reason }: { code: string; reason: string }) => knowledgeApi.rejectContentRule(code, reviewer.trim(), reason), onSuccess: async (_value, item) => { setReasons((current) => ({ ...current, [item.code]: "" })); await refresh(); } });
  const revoke = useMutation({ mutationFn: ({ code, reason }: { code: string; reason: string }) => knowledgeApi.revokeContentRule(code, reviewer.trim(), reason), onSuccess: async (_value, item) => { setReasons((current) => ({ ...current, [item.code]: "" })); await refresh(); } });
  const approvedSources = (sources.data ?? []).filter((source) => source.status === "approved");
  const sourceRequired = ruleKind !== "content_guidance";
  const problem = sources.error ?? rules.error ?? create.error ?? approve.error ?? reject.error ?? revoke.error;

  return <div className="knowledge-layout">
    <aside className="wb-section knowledge-rail">
      <SectionHeader kicker="KNOWLEDGE RULES" title="内容规则" actions={<><button type="button" className="wb-button" onClick={onShowEvidence}>来源证据</button><button type="button" className="wb-button" onClick={onShowFactCards}>商品事实卡</button></>} />
      <form className="knowledge-create knowledge-editor" onSubmit={(event: FormEvent) => { event.preventDefault(); create.mutate(); }}>
        <label className="wb-field"><span>规则类型</span><select className="wb-input" value={ruleKind} onChange={(event) => { const next = event.target.value as ContentRule["ruleKind"]; setRuleKind(next); if (next === "expression_ban") setDirective("must_avoid"); }}><option value="content_guidance">内容知识</option><option value="compliance_rule">合规规则</option><option value="term">术语</option><option value="expression_ban">表达禁区</option></select></label>
        <label className="wb-field"><span>应用方式</span><select className="wb-input" value={directive} disabled={ruleKind === "expression_ban"} onChange={(event) => setDirective(event.target.value as ContentRule["directive"])}><option value="guidance">指导</option><option value="must_include">必须包含</option><option value="must_avoid">必须避免</option></select></label>
        <label className="wb-field"><span>规则标题</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
        <label className="wb-field"><span>批准来源</span><select className="wb-input" value={sourceCode} onChange={(event) => setSourceCode(event.target.value)} required={sourceRequired}><option value="">{sourceRequired ? "选择批准来源" : "无需来源（本地内容知识）"}</option>{approvedSources.map((source) => <option key={source.evidenceCode} value={source.evidenceCode}>{source.title}</option>)}</select></label>
        <label className="wb-field"><span>适用平台</span><input className="wb-input" value={platforms} onChange={(event) => setPlatforms(event.target.value)} placeholder="逗号分隔；留空表示不限制" /></label>
        <label className="wb-field"><span>登记人</span><input className="wb-input" value={author} onChange={(event) => setAuthor(event.target.value)} required /></label>
        <label className="wb-field wide"><span>规则正文</span><textarea className="wb-textarea" value={ruleText} onChange={(event) => setRuleText(event.target.value)} required /></label>
        <button className="wb-button wb-button-primary" disabled={create.isPending || !title.trim() || !ruleText.trim() || (sourceRequired && !sourceCode)}><FilePlus2 size={15} aria-hidden="true" />登记规则草稿</button>
      </form>
    </aside>
    <main className="knowledge-main">
      <section className="wb-section"><SectionHeader kicker="RULE REVIEW" title="内容规则审核" actions={<label className="wb-field"><span>审核/撤销操作人</span><input className="wb-input" value={reviewer} onChange={(event) => setReviewer(event.target.value)} required /></label>} />
        {problem ? <InlineNotice tone="danger" title="规则操作未完成">{errorMessage(problem)}</InlineNotice> : null}
        {rules.isLoading ? <LoadingBlock /> : rules.data?.length ? <div className="knowledge-usage-list">{rules.data.map((rule) => { const reason = reasons[rule.ruleCode] ?? ""; return <article key={rule.ruleCode}><span><strong>{rule.title}</strong><small>{rule.ruleKind} · {rule.directive}</small><small>{rule.ruleText}</small><small>来源：{rule.sourceTitle ?? "本地内容知识"} · {rule.sourceStatus ?? "不适用"}</small><code>{rule.ruleCode} · {rule.fingerprint.slice(0, 12)}</code>{rule.status === "rejected" && rule.rejectionReason ? <small>驳回：{rule.rejectionReason}</small> : null}{rule.status === "revoked" && rule.revokedReason ? <small>撤销：{rule.revokedReason}</small> : null}</span><div className="knowledge-source-actions"><StatusBadge label={rule.status} tone={versionTone(rule.status)} />{rule.status === "draft" ? <><button type="button" className="wb-button" disabled={approve.isPending || !reviewer.trim()} onClick={() => approve.mutate(rule.ruleCode)}><CheckCircle2 size={14} aria-hidden="true" />批准规则</button><input aria-label={`${rule.ruleCode} 驳回原因`} className="wb-input" value={reason} onChange={(event) => setReasons((current) => ({ ...current, [rule.ruleCode]: event.target.value }))} placeholder="驳回原因" /><button type="button" className="wb-button" disabled={reject.isPending || !reviewer.trim() || !reason.trim()} onClick={() => reject.mutate({ code: rule.ruleCode, reason: reason.trim() })}><XCircle size={14} aria-hidden="true" />驳回规则</button></> : null}{rule.status === "approved" ? <><input aria-label={`${rule.ruleCode} 撤销原因`} className="wb-input" value={reason} onChange={(event) => setReasons((current) => ({ ...current, [rule.ruleCode]: event.target.value }))} placeholder="撤销原因" /><button type="button" className="wb-button" disabled={revoke.isPending || !reviewer.trim() || !reason.trim()} onClick={() => revoke.mutate({ code: rule.ruleCode, reason: reason.trim() })}><XCircle size={14} aria-hidden="true" />撤销规则</button></> : null}</div></article>; })}</div> : <EmptyBlock icon={BookOpen} title="尚无内容规则" />}
      </section>
    </main>
  </div>;
}

function EvidenceWorkspace({ onShowFactCards }: { onShowFactCards: () => void }) {
  const client = useQueryClient();
  const [sourceType, setSourceType] = useState<"human" | "document" | "webpage" | "export">("document");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceExcerpt, setSourceExcerpt] = useState("");
  const [sourceScope, setSourceScope] = useState("internal");
  const [author, setAuthor] = useState("console_operator");
  const [factTitle, setFactTitle] = useState("");
  const [claimText, setClaimText] = useState("");
  const [sourceCode, setSourceCode] = useState("");
  const [citation, setCitation] = useState("");
  const [fieldPath, setFieldPath] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [claimQuery, setClaimQuery] = useState("");
  const [selectedClaimCode, setSelectedClaimCode] = useState("");
  const [reviewer, setReviewer] = useState("console_reviewer");
  const [revocationReasons, setRevocationReasons] = useState<Record<string, string>>({});
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});
  const sources = useQuery({ queryKey: ["knowledge-source-evidences"], queryFn: knowledgeApi.listSourceEvidences });
  const claims = useQuery({ queryKey: ["knowledge-fact-claims", claimQuery], queryFn: () => claimQuery.trim() ? knowledgeApi.searchFactClaims(claimQuery) : knowledgeApi.listFactClaims() });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["knowledge-source-evidences"] }),
      client.invalidateQueries({ queryKey: ["knowledge-fact-claims"] }),
    ]);
  };
  const createSource = useMutation({
    mutationFn: () => knowledgeApi.createSourceEvidence({ source_type: sourceType, title: sourceTitle.trim(), source_url: sourceUrl.trim() || undefined, excerpt: sourceExcerpt.trim(), access_scope: sourceScope.trim(), created_by: author.trim() || undefined }),
    onSuccess: async () => { setSourceTitle(""); setSourceUrl(""); setSourceExcerpt(""); await refresh(); },
  });
  const approveSource = useMutation({ mutationFn: (code: string) => knowledgeApi.approveSourceEvidence(code, reviewer.trim()), onSuccess: refresh });
  const rejectSource = useMutation({
    mutationFn: ({ code, reason }: { code: string; reason: string }) => knowledgeApi.rejectSourceEvidence(code, reviewer.trim(), reason),
    onSuccess: async (_result, variables) => { setRejectionReasons((current) => ({ ...current, [variables.code]: "" })); await refresh(); },
  });
  const createClaim = useMutation({
    mutationFn: () => knowledgeApi.createFactClaim({ fact_title: factTitle.trim(), claim: claimText.trim(), source_evidence_code: sourceCode, citation_excerpt: citation.trim(), field_path: fieldPath.trim() || undefined, valid_from: validFrom.trim() || undefined, valid_until: validUntil.trim() || undefined, created_by: author.trim() || undefined }),
    onSuccess: async () => { setFactTitle(""); setClaimText(""); setCitation(""); setFieldPath(""); setValidFrom(""); setValidUntil(""); await refresh(); },
  });
  const approveClaim = useMutation({ mutationFn: (code: string) => knowledgeApi.approveFactClaim(code, reviewer.trim()), onSuccess: refresh });
  const rejectClaim = useMutation({
    mutationFn: ({ code, reason }: { code: string; reason: string }) => knowledgeApi.rejectFactClaim(code, reviewer.trim(), reason),
    onSuccess: async (_result, variables) => { setRejectionReasons((current) => ({ ...current, [variables.code]: "" })); await refresh(); },
  });
  const revokeSource = useMutation({
    mutationFn: ({ code, reason }: { code: string; reason: string }) => knowledgeApi.revokeSourceEvidence(code, reviewer.trim(), reason),
    onSuccess: async (_result, variables) => { setRevocationReasons((current) => ({ ...current, [variables.code]: "" })); await refresh(); },
  });
  const revokeClaim = useMutation({
    mutationFn: ({ code, reason }: { code: string; reason: string }) => knowledgeApi.revokeFactClaim(code, reviewer.trim(), reason),
    onSuccess: async (_result, variables) => { setRevocationReasons((current) => ({ ...current, [variables.code]: "" })); await refresh(); },
  });
  const approvedSources = (sources.data ?? []).filter((source) => source.status === "approved");
  const selectedSourceIsApproved = approvedSources.some((source) => source.evidenceCode === sourceCode);
  const problem = sources.error ?? claims.error ?? createSource.error ?? approveSource.error ?? rejectSource.error ?? revokeSource.error ?? createClaim.error ?? approveClaim.error ?? rejectClaim.error ?? revokeClaim.error;

  return <div className="knowledge-layout">
    <aside className="wb-section knowledge-rail">
      <SectionHeader kicker="SOURCE EVIDENCE" title="来源证据" actions={<button type="button" className="wb-button" onClick={onShowFactCards}><BookOpen size={14} aria-hidden="true" />商品事实卡</button>} />
      <form className="knowledge-create knowledge-editor" onSubmit={(event: FormEvent) => { event.preventDefault(); createSource.mutate(); }}>
        <label className="wb-field"><span>来源类型</span><select className="wb-input" value={sourceType} onChange={(event) => setSourceType(event.target.value as typeof sourceType)}><option value="document">文档</option><option value="webpage">网页</option><option value="human">人工确认</option><option value="export">受控导出</option></select></label>
        <label className="wb-field"><span>来源标题</span><input className="wb-input" value={sourceTitle} onChange={(event) => setSourceTitle(event.target.value)} required /></label>
        <label className="wb-field"><span>来源 URL</span><input className="wb-input" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /></label>
        <label className="wb-field"><span>访问范围</span><input className="wb-input" value={sourceScope} onChange={(event) => setSourceScope(event.target.value)} required /></label>
        <label className="wb-field"><span>登记人</span><input className="wb-input" value={author} onChange={(event) => setAuthor(event.target.value)} required /></label>
        <label className="wb-field"><span>可引用摘录</span><textarea className="wb-textarea" value={sourceExcerpt} onChange={(event) => setSourceExcerpt(event.target.value)} required /></label>
        <button className="wb-button wb-button-primary" disabled={createSource.isPending}><FilePlus2 size={15} aria-hidden="true" />登记来源草稿</button>
      </form>
      {sources.isLoading ? <LoadingBlock /> : sources.data?.length ? <div className="knowledge-card-list">{sources.data.map((source) => { const revocationReason = revocationReasons[source.evidenceCode] ?? ""; const rejectionReason = rejectionReasons[source.evidenceCode] ?? ""; return <article key={source.evidenceCode}><span><strong>{source.title}</strong><small>{source.sourceType} · {source.accessScope}</small><code>{source.evidenceCode} · {source.contentChecksum.slice(0, 12)}</code>{source.status === "rejected" && source.rejectionReason ? <small>驳回：{source.rejectionReason}</small> : null}{source.status === "revoked" && source.revokedReason ? <small>撤销：{source.revokedReason}</small> : null}</span><div className="knowledge-source-actions"><StatusBadge label={source.status} tone={versionTone(source.status)} />{source.status === "draft" ? <><button type="button" className="wb-button" disabled={approveSource.isPending || !reviewer.trim()} onClick={() => approveSource.mutate(source.evidenceCode)}>批准来源</button><input aria-label={`${source.evidenceCode} 驳回原因`} className="wb-input" value={rejectionReason} onChange={(event) => setRejectionReasons((current) => ({ ...current, [source.evidenceCode]: event.target.value }))} placeholder="驳回原因" /><button type="button" className="wb-button" disabled={rejectSource.isPending || !reviewer.trim() || !rejectionReason.trim()} onClick={() => rejectSource.mutate({ code: source.evidenceCode, reason: rejectionReason.trim() })}><XCircle size={14} aria-hidden="true" />驳回来源</button></> : null}{source.status === "approved" ? <><input aria-label={`${source.evidenceCode} 撤销原因`} className="wb-input" value={revocationReason} onChange={(event) => setRevocationReasons((current) => ({ ...current, [source.evidenceCode]: event.target.value }))} placeholder="撤销原因" /><button type="button" className="wb-button" disabled={revokeSource.isPending || !reviewer.trim() || !revocationReason.trim()} onClick={() => revokeSource.mutate({ code: source.evidenceCode, reason: revocationReason.trim() })}><XCircle size={14} aria-hidden="true" />撤销来源</button></> : null}</div></article>; })}</div> : <EmptyBlock icon={BookOpen} title="尚无来源证据" />}
    </aside>
    <main className="knowledge-main">
      <section className="wb-section"><SectionHeader kicker="FACT CLAIM" title="事实声明" />
        <form className="knowledge-create knowledge-editor" onSubmit={(event: FormEvent) => { event.preventDefault(); createClaim.mutate(); }}><div className="wb-form-grid">
          <label className="wb-field"><span>事实标题</span><input className="wb-input" value={factTitle} onChange={(event) => setFactTitle(event.target.value)} required /></label>
          <label className="wb-field"><span>批准来源</span><select className="wb-input" value={sourceCode} onChange={(event) => { const selected = approvedSources.find((source) => source.evidenceCode === event.target.value); setSourceCode(event.target.value); if (selected) setCitation(selected.excerpt); }} required><option value="">选择批准来源</option>{approvedSources.map((source) => <option key={source.evidenceCode} value={source.evidenceCode}>{source.title} · {source.evidenceCode}</option>)}</select></label>
          <label className="wb-field"><span>字段路径</span><input className="wb-input" value={fieldPath} onChange={(event) => setFieldPath(event.target.value)} placeholder="product.warranty" /></label>
          <label className="wb-field"><span>有效开始时间 (UTC)</span><input className="wb-input" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} placeholder="2026-07-25T00:00:00Z" /></label>
          <label className="wb-field"><span>有效结束时间 (UTC)</span><input className="wb-input" value={validUntil} onChange={(event) => setValidUntil(event.target.value)} placeholder="2026-12-31T23:59:59Z" /></label>
          <label className="wb-field wide"><span>事实声明</span><textarea className="wb-textarea" value={claimText} onChange={(event) => setClaimText(event.target.value)} required /></label>
          <label className="wb-field wide"><span>引用摘录</span><textarea className="wb-textarea" value={citation} onChange={(event) => setCitation(event.target.value)} required /></label>
        </div><button className="wb-button wb-button-primary" disabled={createClaim.isPending || !selectedSourceIsApproved}><FilePlus2 size={15} aria-hidden="true" />创建事实声明</button></form>
      </section>
      <section className="wb-section"><SectionHeader kicker="CLAIM REVIEW" title="声明与引用" actions={<><label className="asset-search"><Search size={15} aria-hidden="true" /><input aria-label="搜索事实声明" value={claimQuery} onChange={(event) => setClaimQuery(event.target.value)} placeholder="搜索声明或事实标题" /></label><label className="wb-field"><span>审核/撤销操作人</span><input className="wb-input" value={reviewer} onChange={(event) => setReviewer(event.target.value)} required /></label></>} />
        {problem ? <InlineNotice tone="danger" title="知识操作未完成">{errorMessage(problem)}</InlineNotice> : null}
        {claims.isLoading ? <LoadingBlock /> : claims.data?.length ? <div className="knowledge-usage-list">{claims.data.map((claim) => { const revocationReason = revocationReasons[claim.claimCode] ?? ""; const rejectionReason = rejectionReasons[claim.claimCode] ?? ""; return <article key={claim.claimCode}><span><strong>{claim.factTitle}</strong><small>{claim.claim}</small><small>引用：{claim.citationExcerpt}</small>{claim.citationStartOffset !== undefined && claim.citationEndOffset !== undefined ? <small>引用区间：{claim.citationStartOffset}-{claim.citationEndOffset}</small> : <small>引用区间：历史记录未固定</small>}<small>来源状态：{claim.sourceStatus}</small><small>有效期：{claim.validFrom ? formatDate(claim.validFrom) : "未限制"} 至 {claim.validUntil ? formatDate(claim.validUntil) : "未限制"}</small><code>{claim.claimCode} · {claim.sourceEvidenceCode} · {claim.fingerprint.slice(0, 12)}</code>{claim.status === "rejected" && claim.rejectionReason ? <small>驳回：{claim.rejectionReason}</small> : null}{claim.status === "revoked" && claim.revokedReason ? <small>撤销：{claim.revokedReason}</small> : null}</span><div className="knowledge-source-actions"><button type="button" className="wb-button" onClick={() => setSelectedClaimCode(claim.claimCode)}>查看使用链</button><StatusBadge label={claim.status} tone={versionTone(claim.status)} />{claim.status === "draft" ? <><button type="button" className="wb-button" disabled={approveClaim.isPending || !reviewer.trim()} onClick={() => approveClaim.mutate(claim.claimCode)}><CheckCircle2 size={14} aria-hidden="true" />批准声明</button><input aria-label={`${claim.claimCode} 驳回原因`} className="wb-input" value={rejectionReason} onChange={(event) => setRejectionReasons((current) => ({ ...current, [claim.claimCode]: event.target.value }))} placeholder="驳回原因" /><button type="button" className="wb-button" disabled={rejectClaim.isPending || !reviewer.trim() || !rejectionReason.trim()} onClick={() => rejectClaim.mutate({ code: claim.claimCode, reason: rejectionReason.trim() })}><XCircle size={14} aria-hidden="true" />驳回声明</button></> : null}{claim.status === "approved" ? <><input aria-label={`${claim.claimCode} 撤销原因`} className="wb-input" value={revocationReason} onChange={(event) => setRevocationReasons((current) => ({ ...current, [claim.claimCode]: event.target.value }))} placeholder="撤销原因" /><button type="button" className="wb-button" disabled={revokeClaim.isPending || !reviewer.trim() || !revocationReason.trim()} onClick={() => revokeClaim.mutate({ code: claim.claimCode, reason: revocationReason.trim() })}><XCircle size={14} aria-hidden="true" />撤销声明</button></> : null}</div></article>; })}</div> : <EmptyBlock icon={BookOpen} title={claimQuery.trim() ? "未找到匹配声明" : "尚无事实声明"} />}
      </section>
      {selectedClaimCode ? <FactClaimLineagePanel claimCode={selectedClaimCode} /> : null}
    </main>
  </div>;
}

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [workspace, setWorkspace] = useState<"fact_cards" | "evidence" | "rules">("fact_cards");
  const [query, setQuery] = useState("");
  const [selectedCode, setSelectedCode] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showRevision, setShowRevision] = useState(false);
  const [createValues, setCreateValues] = useState<FactEditorValues>(EMPTY_EDITOR);
  const [revisionValues, setRevisionValues] = useState<FactEditorValues>(EMPTY_EDITOR);
  const [selectedVersion, setSelectedVersion] = useState<number>();
  const [reviewer, setReviewer] = useState("console_reviewer");
  const [rejectionReason, setRejectionReason] = useState("");
  const cards = useQuery({ queryKey: ["product-fact-cards"], queryFn: knowledgeApi.listProductFactCards, enabled: workspace === "fact_cards" });
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

  if (workspace === "evidence") return <EvidenceWorkspace onShowFactCards={() => setWorkspace("fact_cards")} />;
  if (workspace === "rules") return <ContentRuleWorkspace onShowFactCards={() => setWorkspace("fact_cards")} onShowEvidence={() => setWorkspace("evidence")} />;
  if (cards.isLoading) return <LoadingBlock />;
  return <div className="knowledge-layout">
    <aside className="wb-section knowledge-rail">
      <SectionHeader kicker="FACT CARDS" title="事实卡" actions={<><button type="button" className="wb-button" onClick={() => setWorkspace("evidence")}>来源证据</button><button type="button" className="wb-button" onClick={() => setWorkspace("rules")}>内容规则</button><button type="button" className="wb-button wb-button-primary" onClick={() => setShowCreate((current) => !current)}><FilePlus2 size={14} aria-hidden="true" />新建</button></>} />
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

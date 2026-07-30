import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, FilePlus2, Link2, Plus, Search, ShieldCheck, X } from "lucide-react";
import { PageHeader } from "../product/components";
import { EmptyBlock, InlineNotice, LoadingBlock, StatusBadge, formatDate } from "../workbench/components";
import { entityLabel, productLabel } from "../workbench/productLanguage";
import { knowledgeApi, type ProductFactCard, type ProductFactCardContentInput, type SourceEvidence } from "./api";
import { knowledgeText, knowledgeTextList } from "./presentation";

function lines(value: string): string[] {
  return value.split(/\n|,/).map((item) => item.trim()).filter(Boolean);
}

function text(value: Record<string, unknown>, key: string): string {
  return typeof value[key] === "string" ? String(value[key]) : "";
}

interface FactDraft { title: string; productName: string; brand: string; category: string; positioning: string; verifiedFacts: string; scenarios: string; complianceNotes: string; changeReason: string }
const EMPTY_FACT: FactDraft = { title: "", productName: "", brand: "", category: "", positioning: "", verifiedFacts: "", scenarios: "", complianceNotes: "", changeReason: "" };

function factContent(value: FactDraft): ProductFactCardContentInput {
  return { product_name: value.productName.trim(), brand: value.brand.trim() || undefined, category: value.category.trim() || undefined, positioning: value.positioning.trim(), verified_facts: lines(value.verifiedFacts), scenarios: lines(value.scenarios), compliance_notes: lines(value.complianceNotes), source_references: [] };
}

function FactDialog({ open, card, onClose }: { open: boolean; card?: ProductFactCard; onClose: () => void }) {
  const queryClient = useQueryClient();
  const latest = card?.versions[0];
  const [draft, setDraft] = useState<FactDraft>(EMPTY_FACT);
  useEffect(() => {
    if (!open) return;
    const content = latest?.content ?? {};
    setDraft(card ? { title: card.title, productName: knowledgeText(text(content, "product_name"), ""), brand: knowledgeText(text(content, "brand"), ""), category: knowledgeText(text(content, "category"), ""), positioning: knowledgeText(text(content, "positioning"), ""), verifiedFacts: knowledgeTextList(content.verified_facts).join("\n"), scenarios: knowledgeTextList(content.scenarios).join("\n"), complianceNotes: knowledgeTextList(content.compliance_notes).join("\n"), changeReason: "更新商品事实" } : EMPTY_FACT);
  }, [card, latest?.content, open]);
  const save = useMutation({
    mutationFn: () => card ? knowledgeApi.createProductFactCardVersion(card.factCardCode, { content: factContent(draft), change_reason: draft.changeReason.trim(), created_by: "console_operator" }) : knowledgeApi.createProductFactCard({ title: draft.title.trim(), content: factContent(draft), change_reason: "创建商品事实", created_by: "console_operator" }),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["product-fact-cards"] }); onClose(); },
  });
  const field = (key: keyof FactDraft, label: string, placeholder: string) => <label className="wb-field"><span>{label}</span><input className="wb-input" value={draft[key]} onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))} placeholder={placeholder} /></label>;
  return <Dialog.Root open={open} onOpenChange={(value) => { if (!value) onClose(); }}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="knowledge-editor-dialog"><header><div><Dialog.Title>{card ? "创建事实新版本" : "新建商品事实"}</Dialog.Title><Dialog.Description>只记录可核验、可引用的商品信息；草稿批准后才能用于生成。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header><div className="knowledge-editor-body"><div className="knowledge-form-grid">{field("title", "事实卡名称", "例如：轻食早餐新品信息")}{field("productName", "商品名称", "消费者看到的正式名称")}{field("brand", "品牌", "品牌名称")}{field("category", "品类", "例如：即食食品")}</div><label className="wb-field"><span>商品定位</span><textarea rows={3} value={draft.positioning} onChange={(event) => setDraft((current) => ({ ...current, positioning: event.target.value }))} placeholder="这款商品适合谁、解决什么需求" /></label><label className="wb-field"><span>已核验事实（每行一条）</span><textarea rows={6} value={draft.verifiedFacts} onChange={(event) => setDraft((current) => ({ ...current, verifiedFacts: event.target.value }))} placeholder="配料、规格、产地、使用方式等可核验事实" /></label><div className="knowledge-form-grid"><label className="wb-field"><span>适用场景</span><textarea rows={3} value={draft.scenarios} onChange={(event) => setDraft((current) => ({ ...current, scenarios: event.target.value }))} /></label><label className="wb-field"><span>合规备注</span><textarea rows={3} value={draft.complianceNotes} onChange={(event) => setDraft((current) => ({ ...current, complianceNotes: event.target.value }))} /></label></div>{card ? field("changeReason", "本次修改说明", "说明为何创建新版本") : null}{save.error ? <InlineNotice tone="danger" title="事实没有保存">检查商品名称、定位和已核验事实后重试。</InlineNotice> : null}</div><footer><button className="wb-button" type="button" onClick={onClose}>取消</button><button className="wb-button wb-button-primary" type="button" disabled={!draft.title.trim() || !draft.productName.trim() || !draft.positioning.trim() || !lines(draft.verifiedFacts).length || (Boolean(card) && !draft.changeReason.trim()) || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "正在保存" : card ? "创建新版本" : "创建事实卡"}</button></footer></Dialog.Content></Dialog.Portal></Dialog.Root>;
}

function FactInspector({ card, onClose, onRevise }: { card: ProductFactCard; onClose: () => void; onRevise: () => void }) {
  const queryClient = useQueryClient();
  const [reviewReason, setReviewReason] = useState("");
  const active = card.versions[0];
  const usage = useQuery({ queryKey: ["product-fact-card-usage", card.factCardCode, active?.versionNumber], queryFn: () => knowledgeApi.listProductFactCardUsage(card.factCardCode, active!.versionNumber), enabled: Boolean(active) });
  const approve = useMutation({ mutationFn: () => knowledgeApi.approveProductFactCardVersion(card.factCardCode, active.versionNumber, "console_operator"), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["product-fact-cards"] }) });
  const reject = useMutation({ mutationFn: () => knowledgeApi.rejectProductFactCardVersion(card.factCardCode, active.versionNumber, "console_operator", reviewReason.trim()), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["product-fact-cards"] }) });
  if (!active) return null;
  const content = active.content;
  const verifiedFacts = knowledgeTextList(content.verified_facts);
  return <aside className="knowledge-inspector"><header><div><h2>{card.title}</h2><p>第 {active.versionNumber} 版 · {formatDate(active.createdAt)}</p></div><button className="product-icon-button" type="button" title="关闭详情" onClick={onClose}><X size={18} aria-hidden="true" /></button></header><div className="knowledge-inspector-status"><StatusBadge label={active.status} tone={active.status === "approved" ? "success" : active.status === "rejected" ? "danger" : "warning"} /><span>{active.status === "approved" ? "可以用于内容生成" : active.status === "draft" ? "批准后才能用于生成" : "该版本不会用于生成"}</span></div><div className="knowledge-inspector-body"><section><h3>商品信息</h3><dl><div><dt>商品名称</dt><dd>{knowledgeText(text(content, "product_name"))}</dd></div><div><dt>品牌</dt><dd>{knowledgeText(text(content, "brand"))}</dd></div><div><dt>品类</dt><dd>{knowledgeText(text(content, "category"))}</dd></div><div className="wide"><dt>定位</dt><dd>{knowledgeText(text(content, "positioning"))}</dd></div></dl></section><section><h3>已核验事实</h3>{verifiedFacts.length ? <ul>{verifiedFacts.map((item, index) => <li key={`${item}:${index}`}><Check size={13} aria-hidden="true" />{item}</li>)}</ul> : <EmptyBlock title="尚未填写已核验事实" />}</section><section><h3>适用场景</h3><p>{knowledgeTextList(content.scenarios).join("、") || "未限制"}</p></section><section><h3>被哪些内容使用</h3>{usage.isLoading ? <LoadingBlock /> : usage.data?.length ? <div className="knowledge-usage-product">{usage.data.map((item, index) => <article key={`${item.objectCode}:${index}`}><Link2 size={14} aria-hidden="true" /><span><strong>{entityLabel(item.objectType)}</strong><small>{formatDate(item.createdAt)}</small></span><StatusBadge label={item.status} tone="neutral" /></article>)}</div> : <p>当前版本还没有被内容项目使用。</p>}</section>{active.status === "draft" ? <section className="knowledge-review-actions"><h3>审核这个版本</h3><label className="wb-field"><span>驳回原因（仅驳回时填写）</span><textarea rows={3} value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} /></label><div><button className="wb-button wb-button-primary" type="button" disabled={approve.isPending} onClick={() => approve.mutate()}>批准版本</button><button className="wb-button" type="button" disabled={!reviewReason.trim() || reject.isPending} onClick={() => reject.mutate()}>驳回版本</button></div></section> : null}</div><footer><button className="wb-button" type="button" onClick={onRevise}><Plus size={14} aria-hidden="true" />创建新版本</button></footer></aside>;
}

function FactLibrary({ cards, onSelect }: { cards: ProductFactCard[]; onSelect: (card: ProductFactCard) => void }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const filtered = useMemo(() => cards.filter((card) => (status === "all" || card.versions[0]?.status === status) && `${card.title} ${knowledgeText(text(card.versions[0]?.content ?? {}, "product_name"), "")}`.toLowerCase().includes(query.toLowerCase())), [cards, query, status]);
  return <><div className="knowledge-toolbar"><label><Search size={15} aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索商品或事实" aria-label="搜索商品事实" /></label><div>{[["all", "全部"], ["approved", "已批准"], ["draft", "待审核"], ["rejected", "已驳回"]].map(([value, label]) => <button type="button" key={value} className={status === value ? "active" : undefined} onClick={() => setStatus(value)}>{label}</button>)}</div><span>{filtered.length} 张事实卡</span></div>{filtered.length ? <div className="knowledge-fact-grid">{filtered.map((card) => { const active = card.versions[0]; const facts = knowledgeTextList(active?.content.verified_facts); return <button type="button" key={card.factCardCode} onClick={() => onSelect(card)}><header><div><BookOpen size={17} aria-hidden="true" /></div><StatusBadge label={active?.status ?? card.status} tone={active?.status === "approved" ? "success" : "warning"} /></header><strong>{card.title}</strong><small>{knowledgeText(text(active?.content ?? {}, "product_name"), "未填写商品名称")}</small><p>{facts[0] || knowledgeText(text(active?.content ?? {}, "positioning"), "尚未补充已核验事实")}</p><footer><span>{facts.length} 条已核验事实</span><span>{card.versions.length} 个版本</span></footer></button>; })}</div> : <EmptyBlock icon={BookOpen} title="没有匹配的事实卡" />}</>;
}

function SourceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [type, setType] = useState<"human" | "document" | "webpage" | "export">("document");
  const [url, setUrl] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const create = useMutation({ mutationFn: () => knowledgeApi.createSourceEvidence({ source_type: type, title: title.trim(), source_url: url.trim() || undefined, excerpt: excerpt.trim(), access_scope: "internal", created_by: "console_operator" }), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["knowledge-source-evidences"] }); onClose(); } });
  return <Dialog.Root open={open} onOpenChange={(value) => { if (!value) onClose(); }}><Dialog.Portal><Dialog.Overlay className="product-dialog-overlay" /><Dialog.Content className="knowledge-source-dialog"><header><div><Dialog.Title>添加事实来源</Dialog.Title><Dialog.Description>保存可回看的原文摘录，后续事实声明可以引用这份来源。</Dialog.Description></div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header><div><label className="wb-field"><span>来源标题</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} /></label><div className="knowledge-form-grid"><label className="wb-field"><span>来源类型</span><select className="wb-input" value={type} onChange={(event) => setType(event.target.value as typeof type)}><option value="document">文档</option><option value="webpage">网页</option><option value="export">平台导出</option><option value="human">人工确认</option></select></label><label className="wb-field"><span>来源地址（可选）</span><input className="wb-input" value={url} onChange={(event) => setUrl(event.target.value)} /></label></div><label className="wb-field"><span>原文摘录</span><textarea rows={8} value={excerpt} onChange={(event) => setExcerpt(event.target.value)} placeholder="粘贴支持事实的原文片段" /></label>{create.error ? <InlineNotice tone="danger" title="来源没有保存">请补充标题和原文摘录。</InlineNotice> : null}</div><footer><button className="wb-button" type="button" onClick={onClose}>取消</button><button className="wb-button wb-button-primary" type="button" disabled={!title.trim() || !excerpt.trim() || create.isPending} onClick={() => create.mutate()}>保存来源</button></footer></Dialog.Content></Dialog.Portal></Dialog.Root>;
}

function SourceLibrary({ sources, requestedSource }: { sources: SourceEvidence[]; requestedSource?: string }) {
  const queryClient = useQueryClient();
  const approve = useMutation({ mutationFn: (code: string) => knowledgeApi.approveSourceEvidence(code, "console_operator"), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge-source-evidences"] }) });
  const ordered = requestedSource ? [...sources].sort((a, b) => Number(b.evidenceCode === requestedSource) - Number(a.evidenceCode === requestedSource)) : sources;
  return <section className="knowledge-source-list"><header><span>来源</span><span>来源内容</span><span>状态</span><span>最近更新</span><span /></header>{ordered.length ? ordered.map((source) => <article key={source.evidenceCode} className={source.evidenceCode === requestedSource ? "selected" : undefined}><span><div><FilePlus2 size={16} aria-hidden="true" /></div><strong>{source.title}</strong><small>{productLabel(source.sourceType, "资料")}</small></span><p>{knowledgeText(source.excerpt)}</p><StatusBadge label={source.status} tone={source.status === "approved" ? "success" : "warning"} /><time>{formatDate(source.updatedAt ?? source.createdAt)}</time>{source.status === "draft" ? <button className="wb-button" type="button" disabled={approve.isPending} onClick={() => approve.mutate(source.evidenceCode)}>批准</button> : source.sourceUrl ? <a className="wb-button" href={source.sourceUrl} target="_blank" rel="noreferrer">查看原文</a> : <span />}</article>) : <EmptyBlock icon={ShieldCheck} title="还没有事实来源" detail="添加文档、网页、平台导出或人工确认记录。" />}</section>;
}

export function KnowledgeProductPage({ search = window.location.search }: { search?: string }) {
  const params = new URLSearchParams(search);
  const requestedFact = params.get("fact") ?? undefined;
  const requestedSource = params.get("source") ?? undefined;
  const [tab, setTab] = useState<"facts" | "sources">(params.get("view") === "sources" ? "sources" : "facts");
  const [factDialog, setFactDialog] = useState(false);
  const [sourceDialog, setSourceDialog] = useState(false);
  const [selected, setSelected] = useState<ProductFactCard>();
  const [revisionCard, setRevisionCard] = useState<ProductFactCard>();
  const cards = useQuery({ queryKey: ["product-fact-cards"], queryFn: knowledgeApi.listProductFactCards, enabled: tab === "facts" });
  const sources = useQuery({ queryKey: ["knowledge-source-evidences"], queryFn: knowledgeApi.listSourceEvidences, enabled: tab === "sources" });
  useEffect(() => {
    if (requestedFact && cards.data) setSelected(cards.data.find((item) => item.factCardCode === requestedFact));
  }, [cards.data, requestedFact]);
  useEffect(() => setTab(params.get("view") === "sources" ? "sources" : "facts"), [search]);
  return <div className={`knowledge-product-page ${selected ? "has-inspector" : ""}`}><FactDialog open={factDialog || Boolean(revisionCard)} card={revisionCard} onClose={() => { setFactDialog(false); setRevisionCard(undefined); }} /><SourceDialog open={sourceDialog} onClose={() => setSourceDialog(false)} /><PageHeader eyebrow="内容基础" title="知识库" description="管理可核验商品事实、原文来源和内容引用，批准后的信息才能用于生成。" actions={<button className="wb-button wb-button-primary" type="button" onClick={() => tab === "facts" ? setFactDialog(true) : setSourceDialog(true)}><Plus size={16} aria-hidden="true" />{tab === "facts" ? "新建事实卡" : "添加来源"}</button>} /><nav className="knowledge-product-tabs"><button type="button" className={tab === "facts" ? "active" : undefined} onClick={() => setTab("facts")}><BookOpen size={15} aria-hidden="true" />商品事实</button><button type="button" className={tab === "sources" ? "active" : undefined} onClick={() => setTab("sources")}><ShieldCheck size={15} aria-hidden="true" />事实来源</button></nav>{tab === "facts" ? cards.isLoading ? <LoadingBlock /> : <FactLibrary cards={cards.data ?? []} onSelect={setSelected} /> : sources.isLoading ? <LoadingBlock /> : <SourceLibrary sources={sources.data ?? []} requestedSource={requestedSource} />}{selected ? <FactInspector card={selected} onClose={() => setSelected(undefined)} onRevise={() => setRevisionCard(selected)} /> : null}</div>;
}

import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Database, FilePlus2, Play, Plus, RefreshCw, RotateCcw } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, Metric, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { maituApi } from "./api";
import { DEMO_FACT_CARDS, DEMO_INVENTORY_JOBS } from "./demoData";
import type { InventorySyncJob, ProductFactCard } from "./types";

function mutationMessage(error: unknown): string {
  return error instanceof Error ? error.message : "操作未能完成";
}

function jobTone(status: InventorySyncJob["status"]) {
  if (status === "succeeded") return "success" as const;
  if (status === "failed") return "danger" as const;
  if (status === "running") return "info" as const;
  return "warning" as const;
}

function jobLabel(status: InventorySyncJob["status"]) {
  return { queued: "等待同步", running: "同步中", succeeded: "同步完成", failed: "同步失败", cancelled: "已取消" }[status];
}

function FactCardEditor({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [productName, setProductName] = useState("");
  const [productCode, setProductCode] = useState("");
  const [positioning, setPositioning] = useState("");
  const [verifiedFacts, setVerifiedFacts] = useState("");
  const mutation = useMutation({
    mutationFn: maituApi.createFactCard,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["maitu", "fact-cards"] });
      onDone();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const facts = verifiedFacts.split("\n").map((item) => item.trim()).filter(Boolean);
    if (!title.trim() || !productName.trim() || !positioning.trim() || !facts.length) return;
    mutation.mutate({ title: title.trim(), product_name: productName.trim(), product_code: productCode.trim() || undefined, positioning: positioning.trim(), verified_facts: facts });
  };

  return (
    <form onSubmit={submit} className="wb-section-body">
      <div className="wb-form-grid">
        <div className="wb-field"><label htmlFor="fact-title">事实卡名称</label><input id="fact-title" className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} required /></div>
        <div className="wb-field"><label htmlFor="product-name">商品名称</label><input id="product-name" className="wb-input" value={productName} onChange={(event) => setProductName(event.target.value)} required /></div>
        <div className="wb-field wide"><label htmlFor="product-code">商品编号</label><input id="product-code" className="wb-input" value={productCode} onChange={(event) => setProductCode(event.target.value)} placeholder="可选，例如 AG-PROD-*" /></div>
        <div className="wb-field wide"><label htmlFor="fact-positioning">商品定位</label><textarea id="fact-positioning" className="wb-textarea" value={positioning} onChange={(event) => setPositioning(event.target.value)} placeholder="说明商品面向谁、解决什么选择问题" /></div>
        <div className="wb-field wide"><label htmlFor="fact-verified-list">首版已核验事实（每行一条）</label><textarea id="fact-verified-list" className="wb-textarea" value={verifiedFacts} onChange={(event) => setVerifiedFacts(event.target.value)} /></div>
      </div>
      {mutation.error ? <div className="maitu-form-notice"><InlineNotice tone="danger" title="事实卡创建失败">{mutationMessage(mutation.error)}</InlineNotice></div> : null}
      <div className="wb-form-actions"><button type="button" className="wb-button" onClick={onDone}>取消</button><button type="submit" className="wb-button wb-button-primary" disabled={mutation.isPending || !title.trim() || !productName.trim() || !positioning.trim() || !verifiedFacts.trim()}><FilePlus2 size={15} aria-hidden="true" />创建事实卡</button></div>
    </form>
  );
}

function VersionEditor({ card, onDone }: { card: ProductFactCard; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [facts, setFacts] = useState(card.verified_facts.join("\n"));
  const [positioning, setPositioning] = useState(card.positioning);
  const [sellingPoints, setSellingPoints] = useState("");
  const [prohibitedClaims, setProhibitedClaims] = useState("");
  const [sourceNotes, setSourceNotes] = useState("");
  const mutation = useMutation({
    mutationFn: () => maituApi.createFactVersion(card.fact_card_code, {
      product_name: card.product_name,
      product_code: card.product_code,
      positioning: positioning.trim(),
      verified_facts: facts.split("\n").map((item) => item.trim()).filter(Boolean),
      selling_points: sellingPoints.split("\n").map((item) => item.trim()).filter(Boolean),
      prohibited_claims: prohibitedClaims.split("\n").map((item) => item.trim()).filter(Boolean),
      source_notes: sourceNotes.trim() || undefined,
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["maitu", "fact-cards"] });
      onDone();
    },
  });
  return (
    <section className="wb-section maitu-version-editor">
      <SectionHeader kicker="NEW VERSION" title={`${card.title} · 新版本`} />
      <div className="wb-section-body">
        <InlineNotice title="事实版本在生产运行中不可变">保存后先进入草稿，只有人工批准的版本才可用于新运行。</InlineNotice>
        <div className="wb-form-grid maitu-editor-grid">
          <div className="wb-field wide"><label htmlFor="version-positioning">商品定位</label><textarea id="version-positioning" className="wb-textarea" value={positioning} onChange={(event) => setPositioning(event.target.value)} /></div>
          <div className="wb-field"><label htmlFor="verified-facts">已核验事实（每行一条）</label><textarea id="verified-facts" className="wb-textarea" value={facts} onChange={(event) => setFacts(event.target.value)} /></div>
          <div className="wb-field"><label htmlFor="selling-points">素材关键词（每行一条）</label><textarea id="selling-points" className="wb-textarea" value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} /></div>
          <div className="wb-field"><label htmlFor="prohibited-claims">合规备注 / 禁用表达</label><textarea id="prohibited-claims" className="wb-textarea" value={prohibitedClaims} onChange={(event) => setProhibitedClaims(event.target.value)} /></div>
          <div className="wb-field"><label htmlFor="source-notes">来源说明</label><textarea id="source-notes" className="wb-textarea" value={sourceNotes} onChange={(event) => setSourceNotes(event.target.value)} /></div>
        </div>
        {mutation.error ? <InlineNotice tone="danger" title="版本保存失败">{mutationMessage(mutation.error)}</InlineNotice> : null}
        <div className="wb-form-actions"><button type="button" className="wb-button" onClick={onDone}>取消</button><button type="button" className="wb-button wb-button-primary" onClick={() => mutation.mutate()} disabled={mutation.isPending || !facts.trim() || !positioning.trim()}><FilePlus2 size={15} aria-hidden="true" />保存草稿版本</button></div>
      </div>
    </section>
  );
}

export function ResourcesPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editingCard, setEditingCard] = useState<ProductFactCard>();
  const factsQuery = useQuery({ queryKey: ["maitu", "fact-cards"], queryFn: maituApi.listFactCards });
  const inventoryQuery = useQuery({ queryKey: ["maitu", "inventory-jobs"], queryFn: maituApi.listInventoryJobs, refetchInterval: (query) => query.state.data?.some((item) => item.status === "running" || item.status === "queued") ? 1500 : false });
  const demoMode = factsQuery.isError && inventoryQuery.isError;
  const cards = factsQuery.data ?? (demoMode ? DEMO_FACT_CARDS : []);
  const jobs = inventoryQuery.data ?? (demoMode ? DEMO_INVENTORY_JOBS : []);
  const latestSnapshot = jobs.find((job) => job.snapshot)?.snapshot;

  const syncMutation = useMutation({
    mutationFn: maituApi.createInventoryJob,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["maitu", "inventory-jobs"] }),
  });
  const retryMutation = useMutation({
    mutationFn: maituApi.retryInventoryJob,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["maitu", "inventory-jobs"] }),
  });
  const approveMutation = useMutation({
    mutationFn: ({ code, version }: { code: string; version: number }) => maituApi.approveFactVersion(code, version),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["maitu", "fact-cards"] }),
  });

  const categoryCounts = useMemo(() => latestSnapshot?.category_counts ?? {}, [latestSnapshot]);

  return (
    <div className="wb-grid wb-grid-2 maitu-resource-grid">
      {demoMode ? <div className="wide-panel"><InlineNotice tone="warning" title="当前展示接口演示数据">连接 `/api/maitu/workbench` 后，列表和操作会自动切换到真实持久化数据。</InlineNotice></div> : null}
      <section className="wb-section">
        <SectionHeader kicker="IMMUTABLE INPUT" title="商品事实卡" actions={<button type="button" className="wb-button wb-button-primary" onClick={() => setShowCreate((value) => !value)}><Plus size={15} aria-hidden="true" />新建事实卡</button>} />
        {showCreate ? <FactCardEditor onDone={() => setShowCreate(false)} /> : null}
        {factsQuery.isLoading ? <LoadingBlock /> : cards.length ? (
          <div className="wb-table-wrap">
            <table className="wb-table"><thead><tr><th>事实卡</th><th>版本</th><th>已核验事实</th><th>更新时间</th><th>操作</th></tr></thead>
              <tbody>{cards.map((card) => <tr key={card.fact_card_code}>
                <td><strong>{card.title}</strong><small>{card.product_name}</small><code>{card.fact_card_code}</code></td>
                <td><StatusBadge label={`v${card.current_version} · ${card.status === "approved" ? "已批准" : "草稿"}`} tone={card.status === "approved" ? "success" : "warning"} /></td>
                <td><strong>{card.verified_facts.length} 条</strong><small>{card.verified_facts[0] ?? "尚未录入"}</small></td>
                <td>{formatDate(card.updated_at)}</td>
                <td><div className="wb-table-actions"><button type="button" className="wb-button" onClick={() => setEditingCard(card)}><FilePlus2 size={14} aria-hidden="true" />新版本</button>{card.status === "draft" ? <button type="button" className="wb-button" disabled={approveMutation.isPending} onClick={() => approveMutation.mutate({ code: card.fact_card_code, version: card.current_version })}><Check size={14} aria-hidden="true" />批准</button> : null}</div></td>
              </tr>)}</tbody>
            </table>
          </div>
        ) : <EmptyBlock title="尚无事实卡" detail="先建立人工核验的商品事实，再创建生产运行。" />}
      </section>

      <section className="wb-section">
        <SectionHeader kicker="PINNED SNAPSHOT" title="麦兔资源同步" actions={<button type="button" className="wb-button wb-button-primary" disabled={syncMutation.isPending || jobs.some((job) => job.status === "running" || job.status === "queued")} onClick={() => syncMutation.mutate()}><RefreshCw className={syncMutation.isPending ? "wb-spin" : ""} size={15} aria-hidden="true" />同步资源</button>} />
        <div className="wb-section-body">
          <div className="wb-metrics maitu-category-metrics">
            {["背景", "装饰", "视频", "模版"].map((category) => <Metric key={category} label={category} value={categoryCounts[category] ?? 0} detail="当前不可变快照" />)}
          </div>
          {latestSnapshot ? <div className="maitu-snapshot-line"><Database size={16} aria-hidden="true" /><div><strong>{latestSnapshot.snapshot_code}</strong><span>{latestSnapshot.item_count} 项 · {latestSnapshot.quality === "complete" ? "完整快照" : "部分快照"}</span></div><code title={latestSnapshot.fingerprint}>{latestSnapshot.fingerprint.slice(0, 12)}</code></div> : null}
          {syncMutation.error ? <InlineNotice tone="danger" title="无法启动资源同步">{mutationMessage(syncMutation.error)}</InlineNotice> : null}
        </div>
        {inventoryQuery.isLoading ? <LoadingBlock /> : jobs.length ? <div className="wb-table-wrap"><table className="wb-table"><thead><tr><th>同步任务</th><th>进度</th><th>数量</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.sync_job_code}><td><code>{job.sync_job_code}</code><small>{job.source}</small></td><td><StatusBadge label={jobLabel(job.status)} tone={jobTone(job.status)} /><small>{Math.round(job.progress_percent)}%</small></td><td><strong>{job.imported_count} / {job.discovered_count}</strong>{job.failed_count ? <small>{job.failed_count} 项失败</small> : null}</td><td>{formatDate(job.updated_at)}</td><td>{job.status === "failed" ? <button type="button" className="wb-button" onClick={() => retryMutation.mutate(job.sync_job_code)}><RotateCcw size={14} aria-hidden="true" />重试</button> : job.status === "queued" ? <StatusBadge label="等待 Worker" tone="warning" /> : <Play size={15} aria-label="已处理" />}</td></tr>)}</tbody></table></div> : <EmptyBlock icon={Database} title="尚未同步麦兔资源" detail="同步完成后会生成带指纹的不可变资源快照。" />}
      </section>
      {editingCard ? <div className="wide-panel"><VersionEditor card={editingCard} onDone={() => setEditingCard(undefined)} /></div> : null}
    </div>
  );
}

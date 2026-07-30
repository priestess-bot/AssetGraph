import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Download, PackageCheck, RotateCcw, Send, ShieldCheck, X } from "lucide-react";
import { consoleApi } from "../console/api";
import { EmptyBlock, LoadingBlock, StatusBadge, formatDate } from "../workbench/components";
import { productLabel } from "../workbench/productLanguage";
import { releasesApi, type ReleaseDetail } from "./api";

function statusTone(status: string): "neutral" | "info" | "success" | "warning" | "danger" {
  if (["approved", "delivered", "succeeded"].includes(status)) return "success";
  if (["revoked", "failed", "delivery_failed", "reconcile_required"].includes(status)) return "danger";
  if (["candidate", "validating", "awaiting_approval", "delivery_pending", "prepared"].includes(status)) return "warning";
  return "neutral";
}

function checkTitle(code: string): string {
  const key = code.toLowerCase();
  if (key.includes("right")) return "素材使用范围完整";
  if (key.includes("quality") || key.includes("qc")) return "制作质量符合要求";
  if (key.includes("lineage") || key.includes("source")) return "内容与素材来源完整";
  if (key.includes("authorization")) return "目标交付已确认";
  if (key.includes("readback")) return "草稿结果已回读";
  return "交付内容检查";
}

function ReleaseChecks({ release }: { release: ReleaseDetail }) {
  const quality = release.manifest.qualitySnapshot;
  const gates = Array.isArray(quality.gates) ? quality.gates.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
  const rights = release.manifest.rightsSnapshot;
  const lineage = release.manifest.lineageSnapshot;
  const checks = [
    { title: "交付产物已固定", pass: release.manifest.artifactRefs.length > 0, detail: `${release.manifest.artifactRefs.length} 份交付产物` },
    { title: "素材使用范围完整", pass: ["valid", "approved"].includes(String(rights.status)), detail: ["valid", "approved"].includes(String(rights.status)) ? "所选素材可用于本次交付" : "仍需补充素材使用依据" },
    { title: "内容来源完整", pass: lineage.complete === true, detail: lineage.complete === true ? "项目、剧本和制作版本已关联" : "来源信息尚不完整" },
    ...gates.map((gate) => ({ title: checkTitle(String(gate.code ?? "")), pass: gate.status === "pass", detail: gate.status === "pass" ? "已通过" : "需要处理后再交付" })),
  ];
  return <div className="delivery-check-list">{checks.map((item,index) => <article key={`${item.title}:${index}`} className={item.pass ? "pass" : "pending"}>{item.pass ? <CheckCircle2 size={17} /> : <ShieldCheck size={17} />}<span><strong>{item.title}</strong><small>{item.detail}</small></span><StatusBadge label={item.pass ? "通过" : "待处理"} tone={item.pass ? "success" : "warning"} /></article>)}</div>;
}

function ApprovalActions({ release, onUpdated }: { release: ReleaseDetail; onUpdated: () => void }) {
  const [summary, setSummary] = useState("");
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") => consoleApi.decideRelease(release.releaseCode, { expectedManifestRevision: release.manifest.revisionNumber, decision, reasonCode: decision === "approve" ? "CONTENT_DELIVERY_APPROVED" : "CONTENT_DELIVERY_REJECTED", summary, approvedScope: { carrier: release.carrierKind }, idempotencyKey: `release-${decision}-${crypto.randomUUID()}` }),
    onSuccess: onUpdated,
  });
  return <section className="delivery-action-panel"><header><span className="product-section-kicker">人工确认</span><h3>批准交付内容</h3><p>确认标题、画面、话术或成片符合本次交付目标。</p></header><label className="product-field"><span>确认说明</span><textarea rows={3} value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="记录批准依据或需要退回修改的内容" /></label><div><button className="product-secondary-button" type="button" disabled={summary.trim().length < 3 || decide.isPending} onClick={() => decide.mutate("reject")}><X size={15} />退回修改</button><button className="product-primary-button" type="button" disabled={summary.trim().length < 3 || decide.isPending} onClick={() => decide.mutate("approve")}><Check size={15} />批准交付</button></div>{decide.error ? <small className="product-error-copy">决定没有保存，请刷新后重试。</small> : null}</section>;
}

function DeliveryActions({ release, onUpdated }: { release: ReleaseDetail; onUpdated: () => void }) {
  const [target, setTarget] = useState("");
  const prepare = useMutation({ mutationFn: () => releasesApi.prepareDeliveryPackage(release.releaseCode, target.trim(), `delivery-${crypto.randomUUID()}`), onSuccess: onUpdated });
  return <section className="delivery-action-panel"><header><span className="product-section-kicker">交付目标</span><h3>生成交付包</h3><p>填写接收方名称，系统会记录这次交付并固定下载包。当前版本不调用外部发布平台。</p></header><label className="product-field"><span>接收方或使用场景</span><input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="例如：品牌直播运营组" /></label><div><a className="product-secondary-button" href={releasesApi.deliveryPackageUrl(release.releaseCode)}><Download size={15} />下载当前交付包</a><button className="product-primary-button" type="button" disabled={target.trim().length < 2 || prepare.isPending} onClick={() => prepare.mutate()}><Send size={15} />记录并生成交付包</button></div>{prepare.error ? <small className="product-error-copy">交付包没有生成，请确认内容已经批准。</small> : null}</section>;
}

function DeliveryDetail({ release, onUpdated }: { release: ReleaseDetail; onUpdated: () => void }) {
  const [revoking, setRevoking] = useState(false);
  const [reason, setReason] = useState("");
  const validate = useMutation({ mutationFn: () => releasesApi.validate(release.releaseCode), onSuccess: onUpdated });
  const revoke = useMutation({ mutationFn: () => releasesApi.revoke(release.releaseCode, reason), onSuccess: () => { setRevoking(false); onUpdated(); } });
  const carrier = release.carrierKind === "rendered_video" ? "竖屏成片" : "麦兔直播间草稿";
  return <div className="delivery-product-detail">
    <section className="delivery-summary-product"><header><div><span className="product-section-kicker">项目交付</span><h2>{carrier}</h2><p>创建于 {formatDate(release.createdAt)} · 已记录 {release.deliveryCount} 次交付</p></div><StatusBadge label={productLabel(release.status, "准备交付")} tone={statusTone(release.status)} /></header><div><span><small>交付内容</small><strong>{carrier}</strong></span><span><small>固定产物</small><strong>{release.manifest.artifactRefs.length} 份</strong></span><span><small>确认记录</small><strong>{release.approvals.length} 条</strong></span><span><small>交付记录</small><strong>{release.deliveries.length} 次</strong></span></div></section>
    <section className="delivery-checks-product"><header><div><span className="product-section-kicker">交付检查</span><h3>内容是否可以交付</h3></div>{release.status === "candidate" ? <button className="product-primary-button" type="button" disabled={validate.isPending} onClick={() => validate.mutate()}><ShieldCheck size={15} />运行交付检查</button> : null}</header><ReleaseChecks release={release} />{validate.error ? <div className="delivery-check-help">还有必要信息未通过。回到直播间或成片页补齐素材使用范围、制作质量或草稿回读后，再重新检查。</div> : null}</section>
    {release.status === "awaiting_approval" ? <ApprovalActions release={release} onUpdated={onUpdated} /> : null}
    {["approved", "delivery_pending", "delivery_failed", "reconcile_required", "delivered"].includes(release.status) ? <DeliveryActions release={release} onUpdated={onUpdated} /> : null}
    {release.deliveries.length ? <section className="delivery-history-product"><header><span className="product-section-kicker">交付记录</span><h3>接收与处理状态</h3></header>{release.deliveries.map((item) => <article key={item.deliveryCode}><PackageCheck size={17} /><span><strong>{item.targetId || "未命名接收方"}</strong><small>{formatDate(item.createdAt)} · {item.completedAt ? `完成于 ${formatDate(item.completedAt)}` : "交付包已准备"}</small></span><StatusBadge label={productLabel(item.status, "已准备")} tone={statusTone(item.status)} /></article>)}</section> : null}
    {release.status !== "revoked" ? <section className="delivery-revoke-product">{revoking ? <><label className="product-field"><span>撤回原因</span><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明为什么不再使用这份交付内容" /></label><button className="product-secondary-button" type="button" onClick={() => setRevoking(false)}>取消</button><button className="product-primary-button" type="button" disabled={reason.trim().length < 3 || revoke.isPending} onClick={() => revoke.mutate()}><RotateCcw size={15} />确认撤回</button></> : <><div><strong>停止使用这份交付内容</strong><span>撤回后不能再次批准或交付。</span></div><button className="product-secondary-button" type="button" onClick={() => setRevoking(true)}><RotateCcw size={15} />撤回</button></>}</section> : <section className="delivery-revoked-note"><RotateCcw size={18} /><span><strong>这份交付内容已撤回</strong><small>它将保留在历史记录中，但不能再次用于交付。</small></span></section>}
    {revoke.error ? <small className="product-error-copy">撤回没有完成，请刷新后重试。</small> : null}
  </div>;
}

export function DeliveryProductPanel({ search }: { search: string }) {
  const requested = new URLSearchParams(search).get("release") ?? "";
  const [selected, setSelected] = useState(requested);
  const releases = useQuery({ queryKey: ["releases"], queryFn: releasesApi.list });
  useEffect(() => { if (requested) setSelected(requested); }, [requested]);
  const available = useMemo(() => releases.data?.find((item) => item.releaseCode === selected)?.releaseCode ?? releases.data?.[0]?.releaseCode ?? "", [releases.data, selected]);
  const detail = useQuery({ queryKey: ["release", available], queryFn: () => releasesApi.get(available), enabled: Boolean(available) });
  const client = useQueryClient();
  const refresh = () => { void client.invalidateQueries({ queryKey: ["releases"] }); void detail.refetch(); };
  if (releases.isLoading || detail.isLoading) return <LoadingBlock label="正在读取交付内容" />;
  if (!detail.data) return <EmptyBlock icon={PackageCheck} title="还没有可交付内容" detail="在直播间或成片制作完成后创建交付候选，交付内容会出现在这里。" />;
  return <div className="delivery-product-workspace">{(releases.data?.length ?? 0) > 1 ? <aside><header><strong>交付内容</strong><span>{releases.data?.length} 份</span></header>{releases.data?.map((item) => <button key={item.releaseCode} type="button" className={item.releaseCode === available ? "active" : ""} onClick={() => setSelected(item.releaseCode)}><span><strong>{item.carrierKind === "rendered_video" ? "竖屏成片" : "直播间草稿"}</strong><small>{formatDate(item.updatedAt)}</small></span><StatusBadge label={productLabel(item.status, "准备中")} tone={statusTone(item.status)} /></button>)}</aside> : null}<main><DeliveryDetail release={detail.data} onUpdated={refresh} /></main></div>;
}

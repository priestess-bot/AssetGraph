import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileCheck2, PackageCheck, ShieldCheck, Truck } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { releasesApi, type ReleaseDetail } from "./api";

function message(error: unknown): string { return error instanceof Error ? error.message : "无法读取发布记录"; }
function tone(status: string): "neutral" | "info" | "success" | "warning" | "danger" {
  if (["delivered", "succeeded", "approve", "approved"].includes(status)) return "success";
  if (["revoked", "failed", "delivery_failed", "reconcile_required"].includes(status)) return "danger";
  if (["candidate", "validating", "awaiting_approval", "delivery_pending", "prepared", "authorized", "committing"].includes(status)) return "warning";
  return "info";
}
function label(status: string): string {
  const resolved = ({ candidate: "候选", validating: "校验中", awaiting_approval: "待批准", approved: "已批准", delivery_pending: "待投递", delivered: "已投递", delivery_failed: "投递失败", reconcile_required: "待对账", revoked: "已撤销", prepared: "已准备", authorized: "已授权", committing: "提交中", succeeded: "已成功", failed: "失败", approve: "批准", reject: "拒绝" } as Record<string, string>)[status] ?? status;
  return resolved || "未知";
}
function json(value: Record<string, unknown>): string { return JSON.stringify(value, null, 2); }

function ManifestDetail({ release }: { release: ReleaseDetail }) {
  const { manifest } = release;
  return <div className="release-detail">
    <section className="wb-section">
      <SectionHeader kicker={release.releaseCode} title="发布概览" actions={<StatusBadge label={label(release.status)} tone={tone(release.status)} />} />
      <div className="release-summary">
        <div><span>载体</span><strong>{release.carrierKind || "--"}</strong></div>
        <div><span>主体</span><code>{release.subjectCode || "--"}</code><small>{release.subjectType} r{release.subjectRevision}</small></div>
        <div><span>当前清单</span><code>{manifest.manifestCode || "--"}</code><small>r{manifest.revisionNumber}</small></div>
        <div><span>投递尝试</span><strong>{release.deliveries.length}</strong><small>创建于 {formatDate(release.createdAt)}</small></div>
      </div>
    </section>
    <section className="wb-section">
      <SectionHeader kicker="IMMUTABLE MANIFEST" title="固定输入与产物" actions={<StatusBadge label="不可变快照" tone="info" />} />
      <div className="release-manifest-columns">
        <div><h3>来源修订</h3><pre>{json(manifest.subjectRefs)}</pre></div>
        <div><h3>载体投影</h3><pre>{json(manifest.carrierFacet)}</pre></div>
      </div>
      <div className="release-artifact-table">
        <h3>产物引用</h3>
        {manifest.artifactRefs.length ? manifest.artifactRefs.map((artifact, index) => <div key={`${String(artifact.artifact_code)}:${index}`}><code>{String(artifact.artifact_code ?? "未编码产物")}</code><span>{String(artifact.role ?? "artifact")}</span><small>{String(artifact.checksum_sha256 ?? "缺少校验和")}</small></div>) : <span className="release-empty-note">当前清单未包含产物引用。</span>}
      </div>
      <div className="release-manifest-columns release-snapshot-columns">
        <div><h3>权利快照</h3><pre>{json(manifest.rightsSnapshot)}</pre></div>
        <div><h3>质量门禁</h3><pre>{json(manifest.qualitySnapshot)}</pre></div>
        <div><h3>来源链路</h3><pre>{json(manifest.lineageSnapshot)}</pre></div>
      </div>
    </section>
    <section className="wb-section">
      <SectionHeader kicker="APPROVAL" title="批准记录" actions={<StatusBadge label={`${release.approvals.length} 条`} tone={release.approvals.length ? "success" : "warning"} />} />
      {release.approvals.length ? <div className="release-evidence-list">{release.approvals.map((approval) => <article key={approval.approvalCode}><FileCheck2 size={17} aria-hidden="true" /><div><strong>{label(approval.decision)}</strong><small>{approval.decidedBy || "未知审批人"} · {formatDate(approval.decidedAt)}</small><code>{approval.approvalCode}</code></div><pre>{json(approval.structuredReason)}</pre></article>)}</div> : <EmptyBlock icon={ShieldCheck} title="尚无批准记录" detail="候选发布需要通过既有审批流程后才能进入投递。" />}
    </section>
    <section className="wb-section">
      <SectionHeader kicker="DELIVERY" title="投递与回读证据" actions={<StatusBadge label={`${release.deliveries.length} 次`} tone={release.deliveries.some((item) => item.status === "succeeded") ? "success" : "warning"} />} />
      {release.deliveries.length ? <div className="release-evidence-list">{release.deliveries.map((delivery) => <article key={delivery.deliveryCode}><Truck size={17} aria-hidden="true" /><div><strong>{delivery.targetType || "目标未记录"}</strong><small>{delivery.targetId || "--"} · {delivery.adapterType || "--"}</small><code>{delivery.deliveryCode}</code></div><StatusBadge label={label(delivery.status)} tone={tone(delivery.status)} /><pre>{json({ external_identity: delivery.externalIdentity, readback_evidence: delivery.readbackEvidence, error_code: delivery.errorCode ?? null })}</pre></article>)}</div> : <EmptyBlock icon={Truck} title="尚无投递尝试" detail="批准和投递是独立事实，候选或批准状态不代表已经交付。" />}
    </section>
  </div>;
}

export function ReleaseWorkspacePage({ search }: { search: string }) {
  const requestedCode = new URLSearchParams(search).get("release") ?? "";
  const [selectedCode, setSelectedCode] = useState(requestedCode);
  const releases = useQuery({ queryKey: ["releases"], queryFn: releasesApi.list });
  useEffect(() => setSelectedCode(requestedCode), [requestedCode]);
  const availableCode = releases.data?.some((item) => item.releaseCode === selectedCode) ? selectedCode : releases.data?.[0]?.releaseCode ?? selectedCode;
  const detail = useQuery({ queryKey: ["release", availableCode], queryFn: () => releasesApi.get(availableCode), enabled: Boolean(availableCode) });
  return <div className="release-workspace">
    <aside className="wb-section release-rail">
      <SectionHeader kicker="RELEASE MANIFESTS" title="发布记录" />
      {releases.isLoading ? <LoadingBlock /> : releases.error ? <InlineNotice tone="danger" title="发布列表读取失败">{message(releases.error)}</InlineNotice> : releases.data?.length ? <div className="release-list">{releases.data.map((release) => <button type="button" key={release.releaseCode} className={release.releaseCode === availableCode ? "active" : undefined} onClick={() => setSelectedCode(release.releaseCode)}><span><strong>{release.subjectCode || release.releaseCode}</strong><small>{release.carrierKind} · {formatDate(release.updatedAt)}</small><code>{release.releaseCode}</code></span><StatusBadge label={label(release.status)} tone={tone(release.status)} /></button>)}</div> : <EmptyBlock icon={PackageCheck} title="尚无发布记录" detail="创建候选发布后，固定清单与审批、投递证据会在这里展示。" />}
    </aside>
    <main className="release-main">
      {detail.isLoading ? <LoadingBlock label="正在读取固定发布清单" /> : detail.error ? <InlineNotice tone="danger" title="发布详情读取失败">{message(detail.error)}</InlineNotice> : detail.data ? <ManifestDetail release={detail.data} /> : <EmptyBlock icon={PackageCheck} title="选择发布记录" detail="从左侧选择记录，查看不可变清单、批准和投递回读。" />}
    </main>
  </div>;
}

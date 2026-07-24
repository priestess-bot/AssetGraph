import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, GitCompareArrows, History, Link2, Network, X } from "lucide-react";
import { WorkbenchApiError, type WorkbenchProblem } from "../workbench/api";
import { EmptyBlock, ProblemNotice, StatusBadge, formatDate } from "../workbench/components";
import { consoleApi } from "./api";
import { DEMO_ENTITIES, DEMO_ENTITY } from "./demoData";
import { EntityCommands } from "./EntityCommands";
import { EntityDraftEditor, type DraftSaveState } from "./EntityDraftEditor";
import type { ConsoleDraft, ConsoleEntityDetail, ConsoleEntityRelation } from "./types";


export interface EntitySelection {
  entityType: string;
  entityCode: string;
  queryKey: string;
}


function displayValue(value: unknown): string {
  if (value === undefined) return "--";
  const serialized = typeof value === "string" ? value : JSON.stringify(value);
  return serialized.length > 160 ? `${serialized.slice(0, 157)}...` : serialized;
}


function relationRows(rows: ConsoleEntityRelation[], emptyTitle: string) {
  if (!rows.length) return <EmptyBlock icon={Network} title={emptyTitle} />;
  return <div className="console-relation-list">{rows.map((row) => {
    const content = <><span><strong>{row.entityCode}</strong><small>{row.relationType} · {row.entityType}{row.revision ? ` · r${row.revision}` : ""}</small></span><StatusBadge label={row.mappingQuality} tone={row.mappingQuality === "verified" ? "success" : "warning"} />{row.href ? <ArrowRight size={15} aria-hidden="true" /> : null}</>;
    return row.href ? <a key={`${row.relationType}:${row.entityType}:${row.entityCode}:${row.revision ?? 0}`} href={row.href}>{content}</a> : <div key={`${row.relationType}:${row.entityType}:${row.entityCode}:${row.revision ?? 0}`}>{content}</div>;
  })}</div>;
}


function problemFromError(error: unknown): WorkbenchProblem | undefined {
  if (error instanceof WorkbenchApiError && error.problem) return error.problem;
  return error instanceof Error ? {
    code: "ENTITY_DETAIL_UNAVAILABLE",
    state: "error",
    message: error.message,
    impact: "实体版本与使用关系未显示。",
    evidence: [],
    nextStep: "检查实体深链和读取权限。",
    retryable: false,
  } : undefined;
}


function demoEntity(entityCode: string, fromRevision?: number, toRevision?: number): ConsoleEntityDetail {
  const entity = DEMO_ENTITIES[entityCode] ?? DEMO_ENTITY;
  const from = fromRevision ?? entity.diff.fromRevision;
  const to = toRevision ?? entity.diff.toRevision;
  const before = entity.revisions.find((row) => row.revision === from)?.snapshot;
  const after = entity.revisions.find((row) => row.revision === to)?.snapshot;
  const changes = entity === DEMO_ENTITY && from === 2 && to === 3 ? entity.diff.changes : before && after && JSON.stringify(before) !== JSON.stringify(after)
    ? [{ path: "$", change: "changed" as const, before, after }]
    : [];
  return { ...entity, diff: { fromRevision: from, toRevision: to, available: Boolean(before && after), changes } };
}


export function EntityInspector({ selection, demoMode, onClose }: { selection: EntitySelection; demoMode: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [fromRevision, setFromRevision] = useState<number>();
  const [toRevision, setToRevision] = useState<number>();
  const [draft, setDraft] = useState<ConsoleDraft>();
  const [draftState, setDraftState] = useState<DraftSaveState>();
  useEffect(() => {
    setFromRevision(undefined);
    setToRevision(undefined);
    setDraft(undefined);
    setDraftState(undefined);
  }, [selection.entityType, selection.entityCode]);
  const detailQuery = useQuery({
    queryKey: ["console", "entity", selection.entityType, selection.entityCode, fromRevision, toRevision, demoMode],
    queryFn: () => demoMode && DEMO_ENTITIES[selection.entityCode]
      ? Promise.resolve(demoEntity(selection.entityCode, fromRevision, toRevision))
      : consoleApi.entity(selection.entityType, selection.entityCode, fromRevision, toRevision),
  });
  const detail = detailQuery.data;
  const problem = problemFromError(detailQuery.error);
  const selectedFrom = fromRevision ?? detail?.diff.fromRevision;
  const selectedTo = toRevision ?? detail?.diff.toRevision;
  return <aside className="console-entity-inspector" aria-label="实体版本详情">
    <header><div><span>ENTITY REVISION</span><h2>{detail?.title ?? selection.entityCode}</h2><code>{selection.entityCode}</code></div><button type="button" className="console-icon" title="关闭实体详情" onClick={onClose}><X size={18} aria-hidden="true" /></button></header>
    {problem ? <ProblemNotice problem={problem} /> : detailQuery.isLoading || !detail ? <div className="console-loading">正在读取版本与血缘</div> : <>
      <div className="console-entity-summary"><StatusBadge label={detail.status} tone="info" /><span>当前 r{detail.currentRevision}</span><span>事实源 {detail.sourceOfTruth}</span></div>
      {detail.entityType === "content_project" ? <EntityDraftEditor detail={detail} demoMode={demoMode} onDraftChange={(nextDraft, nextState) => { setDraft(nextDraft); setDraftState(nextState); }} /> : null}
      <EntityCommands
        detail={detail}
        draft={draft}
        draftState={draftState}
        demoMode={demoMode}
        onCompleted={() => {
          void queryClient.invalidateQueries({ queryKey: ["console", "entity", selection.entityType, selection.entityCode] });
          void queryClient.invalidateQueries({ queryKey: ["console", "draft", selection.entityType, selection.entityCode] });
        }}
      />
      <section className="console-inspector-section"><h3><History size={15} aria-hidden="true" />Revision 时间线</h3><div className="console-revision-timeline">{detail.revisions.map((revision) => <button type="button" key={revision.revision} className={revision.revision === selectedTo ? "active" : undefined} onClick={() => setToRevision(revision.revision)}><strong>r{revision.revision}</strong><span>{revision.status}</span><small>{formatDate(revision.createdAt)} · {revision.createdBy ?? "system"}</small><code>{revision.fingerprint?.slice(0, 12) ?? revision.schemaVersion}</code></button>)}</div></section>
      <section className="console-inspector-section"><h3><GitCompareArrows size={15} aria-hidden="true" />结构化 Diff</h3><div className="console-diff-controls"><label>从<select value={selectedFrom ?? ""} onChange={(event) => setFromRevision(Number(event.target.value))}>{detail.revisions.map((row) => <option key={row.revision} value={row.revision}>r{row.revision}</option>)}</select></label><ArrowRight size={15} aria-hidden="true" /><label>到<select value={selectedTo ?? ""} onChange={(event) => setToRevision(Number(event.target.value))}>{detail.revisions.map((row) => <option key={row.revision} value={row.revision}>r{row.revision}</option>)}</select></label></div>{detail.diff.available && detail.diff.changes.length ? <div className="console-diff-table">{detail.diff.changes.map((change, index) => <div key={`${change.path}:${index}`}><code>{change.path}</code><StatusBadge label={change.change} tone={change.change === "removed" ? "danger" : change.change === "added" ? "success" : "warning"} /><span title={displayValue(change.before)}>{displayValue(change.before)}</span><ArrowRight size={13} aria-hidden="true" /><span title={displayValue(change.after)}>{displayValue(change.after)}</span></div>)}</div> : <EmptyBlock icon={GitCompareArrows} title="所选版本没有结构变化" />}</section>
      <section className="console-inspector-section"><h3><Link2 size={15} aria-hidden="true" />来源</h3>{relationRows(detail.sources, "没有已证明的来源关系")}</section>
      <section className="console-inspector-section"><h3><Network size={15} aria-hidden="true" />被运行与发布使用</h3>{relationRows(detail.usedBy, "没有已证明的下游使用关系")}</section>
    </>}
  </aside>;
}

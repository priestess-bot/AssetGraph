import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, ClipboardList, ListChecks, XCircle } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import type { ConsoleNotification, ConsoleTask } from "../console/types";
import { workflowRunsApi } from "./runsApi";

function tone(status: string): "neutral" | "info" | "success" | "warning" | "danger" {
  if (["succeeded", "approved", "decided"].includes(status)) return "success";
  if (["failed", "cancelled", "reconcile_required", "escalated"].includes(status)) return "danger";
  if (["waiting_human", "queued", "claimed"].includes(status)) return "warning";
  return "info";
}
function message(error: unknown): string { return error instanceof Error ? error.message : "运行操作未完成"; }
function json(value: Record<string, unknown>): string { return Object.keys(value).length ? JSON.stringify(value, null, 2) : "--"; }

export function GovernanceRunsPage({ search, tasks, notifications, loading }: { search: string; tasks: ConsoleTask[]; notifications: ConsoleNotification[]; loading: boolean }) {
  const client = useQueryClient();
  const params = new URLSearchParams(search);
  const runCode = params.get("run")?.trim() || tasks[0]?.runCode;
  const focusedTask = params.get("task")?.trim();
  const [reason, setReason] = useState("");
  const run = useQuery({ queryKey: ["workflow-run", runCode], queryFn: () => workflowRunsApi.get(runCode!), enabled: Boolean(runCode) });
  const cancel = useMutation({
    mutationFn: () => workflowRunsApi.cancel(runCode!, reason.trim()),
    onSuccess: async () => { setReason(""); await Promise.all([client.invalidateQueries({ queryKey: ["workflow-run", runCode] }), client.invalidateQueries({ queryKey: ["console", "tasks"] })]); },
  });
  const data = run.data;
  const selectedTask = data?.humanTasks.find((task) => task.taskCode === focusedTask);
  const canCancel = data && !["cancelled", "succeeded", "failed"].includes(data.status);
  const issue = run.error ?? cancel.error;
  return <div className="governance-layout">
    <section className="wb-section governance-catalog">
      <SectionHeader kicker="CONTROL PLANE" title="任务与运行" />
      {loading ? <LoadingBlock /> : tasks.length ? <div className="governance-catalog-list">{tasks.map((task) => <a className={task.runCode === runCode ? "active" : undefined} key={task.itemCode} href={`/governance/runs?run=${encodeURIComponent(task.runCode)}${task.itemType === "human_task" ? `&task=${encodeURIComponent(task.itemCode)}` : ""}`}><span><strong>{task.title}</strong><code>{task.itemCode} · {task.runCode}</code><small>{task.summary}</small></span><StatusBadge label={task.status} tone={tone(task.status)} /></a>)}</div> : <EmptyBlock icon={ClipboardList} title="当前没有待处理运行" />}
      <SectionHeader kicker="ALERTS" title="异常" />
      {notifications.length ? <div className="governance-catalog-list">{notifications.map((item) => <a key={item.notificationCode} href={item.href}><span><strong>{item.title}</strong><code>{item.notificationCode}</code><small>{item.summary}</small></span><StatusBadge label={item.state} tone={tone(item.state)} /></a>)}</div> : <EmptyBlock icon={CircleAlert} title="当前没有未处理异常" />}
    </section>
    <main className="knowledge-main">
      {issue ? <InlineNotice tone="danger" title="运行读取或操作失败">{message(issue)}</InlineNotice> : null}
      {!runCode ? <EmptyBlock icon={ClipboardList} title="选择一个运行" /> : run.isLoading ? <LoadingBlock label="正在读取运行详情" /> : data ? <>
        <section className="wb-section"><SectionHeader kicker={data.runCode} title={`${data.workflowType} / ${data.subjectCode}`} actions={<StatusBadge label={data.status} tone={tone(data.status)} />} />
          <div className="knowledge-summary"><div><span>进度</span><strong>{data.progressCompleted}/{data.progressTotal}</strong></div><div><span>优先级</span><strong>{data.priority}</strong></div><div><span>请求人</span><strong>{data.requestedBy ?? "--"}</strong></div></div>
          <dl className="governance-run-details"><div><dt>队列原因</dt><dd>{data.queueReason ?? "--"}</dd></div><div><dt>等待原因</dt><dd>{data.waitingReason ?? "--"}</dd></div><div><dt>错误</dt><dd>{data.errorCode ? `${data.errorCode}: ${data.errorSummary ?? ""}` : "--"}</dd></div><div><dt>更新</dt><dd>{formatDate(data.updatedAt)}</dd></div></dl>
          <details><summary>预算与实际成本</summary><pre>{json({ budget: data.budget, actual_cost: data.actualCost })}</pre></details>
          {canCancel ? <form className="wb-form-actions" onSubmit={(event: FormEvent) => { event.preventDefault(); cancel.mutate(); }}><label className="wb-field"><span>取消原因</span><input className="wb-input" value={reason} onChange={(event) => setReason(event.target.value)} required /></label><button className="wb-button" disabled={cancel.isPending || !reason.trim()}><XCircle size={15} aria-hidden="true" />取消运行</button></form> : null}
        </section>
        <section className="wb-section"><SectionHeader kicker="STEPS" title="步骤" />
          {data.steps.length ? <div className="knowledge-usage-list">{data.steps.map((step) => <article key={step.stepCode}><span><strong>{step.stepType}</strong><small>{step.stepCode} · 尝试 {step.attempt}/{step.maxAttempts} · {step.sideEffectLevel}</small><code>依赖：{step.dependsOn.join(", ") || "无"}{step.claimedBy ? ` · ${step.claimedBy}` : ""}</code>{step.errorCode ? <small>{step.errorCode}: {step.errorSummary}</small> : null}</span><StatusBadge label={step.status} tone={tone(step.status)} /></article>)}</div> : <EmptyBlock icon={ListChecks} title="没有步骤投影" />}
        </section>
        <section className="wb-section"><SectionHeader kicker="HUMAN TASKS" title="人工任务" />
          {data.humanTasks.length ? <div className="knowledge-usage-list">{data.humanTasks.map((task) => <article className={task.taskCode === selectedTask?.taskCode ? "active" : undefined} key={task.taskCode}><span><strong>{task.taskType}</strong><small>{task.taskCode} · r{task.revision} · {task.ownerPrincipal ?? "未分配"}</small><code>{task.claimedBy ? `已领取：${task.claimedBy}` : "未领取"}{task.dueAt ? ` · 截止 ${formatDate(task.dueAt)}` : ""}{task.decision ? ` · ${task.decision}` : ""}</code>{task.structuredReason ? <small>{JSON.stringify(task.structuredReason)}</small> : null}</span><StatusBadge label={task.status} tone={tone(task.status)} /></article>)}</div> : <EmptyBlock icon={ClipboardList} title="没有人工任务" />}
        </section>
      </> : <EmptyBlock icon={CircleAlert} title="运行不存在" />}
    </main>
  </div>;
}

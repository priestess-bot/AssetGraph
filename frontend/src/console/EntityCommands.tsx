import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { BadgeCheck, KeyRound, Send, ShieldCheck, X } from "lucide-react";
import { WorkbenchApiError, type WorkbenchProblem } from "../workbench/api";
import { ProblemNotice, StatusBadge } from "../workbench/components";
import { consoleApi } from "./api";
import type { DraftSaveState } from "./EntityDraftEditor";
import type { ConsoleCommandResult, ConsoleDraft, ConsoleEntityDetail } from "./types";


type CommandKind = ConsoleCommandResult["command"];


function newIdempotencyKey(command: CommandKind): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${command}-${random}`;
}


function commandProblem(error: unknown): WorkbenchProblem | undefined {
  if (error instanceof WorkbenchApiError && error.problem) return error.problem;
  if (!(error instanceof Error)) return undefined;
  return {
    code: "CONSOLE_COMMAND_FAILED",
    state: "error",
    message: error.message,
    impact: "命令没有完成，当前 revision 和外部状态不应视为已变化。",
    evidence: [],
    nextStep: "检查固定 revision、理由和审批证据后重新提交。",
    retryable: false,
  };
}


function availableCommand(detail: ConsoleEntityDetail): CommandKind | undefined {
  if (detail.entityType === "content_project") return "confirm";
  if (detail.entityType === "live_room_template" && ["draft", "rejected"].includes(detail.revisions[0]?.status)) return "publish";
  if (detail.entityType === "release" && detail.status === "awaiting_approval") return "approve";
  if (detail.entityType === "workflow_run" && ["waiting_human", "running"].includes(detail.status)) return "authorize";
  return undefined;
}


const LABELS: Record<CommandKind, string> = {
  confirm: "确认输入",
  publish: "发布模板",
  approve: "审批 Release",
  reject: "驳回 Release",
  authorize: "签发执行授权",
};


const IMPACTS: Record<CommandKind, string> = {
  confirm: "将共享草稿固定为不可变 ContentProjectRevision，并允许后续生成使用该 revision。",
  publish: "将当前模板 revision 发布为可选的内容/参考投影；外部录屏布局仍保持 reference_only。",
  approve: "批准固定 ReleaseManifest；这不会自动交付，也不表示已经发生曝光。",
  reject: "把 Release 退回 candidate，当前 manifest 不再满足交付批准条件。",
  authorize: "基于已批准 HumanTask 签发短期、目标/hash 绑定且单次使用的 token；这不会执行外部写入。",
};


export function EntityCommands({
  detail,
  draft,
  draftState,
  demoMode,
  onCompleted,
}: {
  detail: ConsoleEntityDetail;
  draft?: ConsoleDraft;
  draftState?: DraftSaveState;
  demoMode: boolean;
  onCompleted: (result: ConsoleCommandResult) => void;
}) {
  const available = availableCommand(detail);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [command, setCommand] = useState<CommandKind>(available ?? "confirm");
  const [reasonCode, setReasonCode] = useState("REVIEW_COMPLETE");
  const [summary, setSummary] = useState("");
  const [taskCode, setTaskCode] = useState("");
  const [taskRevision, setTaskRevision] = useState(1);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [result, setResult] = useState<ConsoleCommandResult>();

  const execute = async (): Promise<ConsoleCommandResult> => {
    if (demoMode) return {
      command,
      entityType: detail.entityType,
      entityCode: detail.entityCode,
      entityRevision: detail.currentRevision,
      status: command === "confirm" ? "confirmed" : command === "publish" ? "published" : command === "reject" ? "candidate" : command === "authorize" ? "issued" : "approved",
      impact: IMPACTS[command],
      receiptCode: `COMMAND-DEMO-${command.toUpperCase()}`,
      replayed: false,
      draftRevision: draft?.draftRevision,
    };
    if (command === "confirm") {
      if (!draft) throw new Error("必须先保存共享输入草稿");
      return consoleApi.confirmContentProject(detail.entityCode, {
        expectedEntityRevision: detail.currentRevision,
        expectedDraftRevision: draft.draftRevision,
        idempotencyKey,
      });
    }
    if (command === "publish") return consoleApi.publishTemplate(detail.entityCode, {
      expectedRevision: detail.currentRevision,
      reasonCode,
      summary,
      idempotencyKey,
    });
    if (command === "approve" || command === "reject") return consoleApi.decideRelease(detail.entityCode, {
      expectedManifestRevision: detail.currentRevision,
      decision: command,
      reasonCode,
      summary,
      approvedScope: {},
      idempotencyKey,
    });
    return consoleApi.issueAuthorization(detail.entityCode, { taskCode, expectedTaskRevision: taskRevision, idempotencyKey });
  };
  const mutation = useMutation({
    mutationFn: execute,
    onSuccess: (value) => {
      setResult(value);
      onCompleted(value);
    },
  });
  if (!available) return null;
  const draftReady = detail.entityType !== "content_project" || (draftState === "saved" && draft?.status === "active");
  const open = () => {
    const next = available;
    setCommand(next);
    setReasonCode(next === "approve" || next === "reject" ? "ALL_GATES_REVIEWED" : "REVIEW_COMPLETE");
    setSummary("");
    setResult(undefined);
    mutation.reset();
    setIdempotencyKey(newIdempotencyKey(next));
    setDialogOpen(true);
  };
  const close = () => {
    setDialogOpen(false);
    setResult(undefined);
    mutation.reset();
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };
  const problem = commandProblem(mutation.error);
  const CommandIcon = available === "authorize" ? KeyRound : available === "confirm" ? BadgeCheck : Send;

  return <section className="console-inspector-section console-command-section" aria-label="显式命令">
    <h3><ShieldCheck size={15} aria-hidden="true" />命令</h3>
    <button type="button" className="wb-button wb-button-primary" disabled={!draftReady} onClick={open}><CommandIcon size={14} aria-hidden="true" />{LABELS[available]}</button>
    {!draftReady ? <span className="console-command-blocked">共享草稿保存成功后才可确认</span> : null}
    {dialogOpen ? <div className="console-command-backdrop" role="presentation">
      <form className="console-command-dialog" role="dialog" aria-modal="true" aria-label={LABELS[command]} onSubmit={submit}>
        <header><div><span>EXPLICIT COMMAND</span><h2>{LABELS[command]}</h2></div><button type="button" className="console-icon" title="关闭命令" onClick={close}><X size={18} aria-hidden="true" /></button></header>
        {result ? <div className="console-command-result"><BadgeCheck size={24} aria-hidden="true" /><h3>命令已记录</h3><StatusBadge label={result.status} tone="success" /><code>{result.receiptCode}</code><p>{result.impact}</p>{result.authorizationToken ? <div><strong>一次性显示的授权 token</strong><code>{result.authorizationToken}</code></div> : null}<button type="button" className="wb-button wb-button-primary" onClick={close}>完成</button></div> : <>
          <div className="console-command-impact"><span>固定对象</span><strong>{detail.entityCode} · r{detail.currentRevision}</strong><p>{IMPACTS[command]}</p></div>
          {detail.entityType === "release" ? <div className="console-command-segment" role="group" aria-label="Release 决定"><button type="button" className={command === "approve" ? "active" : undefined} onClick={() => setCommand("approve")}>批准</button><button type="button" className={command === "reject" ? "active" : undefined} onClick={() => setCommand("reject")}>驳回</button></div> : null}
          {command === "authorize" ? <div className="console-command-fields"><label><span>HumanTask 编码</span><input value={taskCode} required maxLength={80} onChange={(event) => setTaskCode(event.target.value)} /></label><label><span>Task revision</span><input type="number" min={1} value={taskRevision} required onChange={(event) => setTaskRevision(Number(event.target.value))} /></label></div> : command !== "confirm" ? <div className="console-command-fields"><label><span>理由码</span><input value={reasonCode} required pattern="[A-Z][A-Z0-9_]+" maxLength={64} onChange={(event) => setReasonCode(event.target.value.toUpperCase())} /></label><label><span>结构化理由</span><textarea value={summary} required minLength={3} maxLength={4000} rows={4} onChange={(event) => setSummary(event.target.value)} /></label></div> : null}
          {problem ? <ProblemNotice problem={problem} /> : null}
          <footer><button type="button" className="wb-button wb-button-secondary" onClick={close}>取消</button><button type="submit" className="wb-button wb-button-primary" disabled={mutation.isPending}>{mutation.isPending ? "正在提交" : LABELS[command]}</button></footer>
        </>}
      </form>
    </div> : null}
  </section>;
}

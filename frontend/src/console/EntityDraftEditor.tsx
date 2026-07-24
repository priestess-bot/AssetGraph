import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, LoaderCircle, Pencil, RefreshCw, Save } from "lucide-react";
import { WorkbenchApiError, type WorkbenchProblem } from "../workbench/api";
import { ProblemNotice } from "../workbench/components";
import { consoleApi } from "./api";
import type { ConsoleDraft, ConsoleEntityDetail } from "./types";


export type DraftSaveState = "loading" | "saved" | "editing" | "saving" | "conflict" | "error";


function problemFromSave(error: unknown): WorkbenchProblem | undefined {
  if (error instanceof WorkbenchApiError && error.problem) return error.problem;
  if (!(error instanceof Error)) return undefined;
  return {
    code: "CONSOLE_DRAFT_SAVE_FAILED",
    state: "error",
    message: error.message,
    impact: "本地编辑尚未写入共享草稿，确认命令保持禁用。",
    evidence: [],
    nextStep: "保留当前页面，检查连接后重试保存。",
    retryable: true,
  };
}


function draftValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}


function demoDraft(
  detail: ConsoleEntityDetail,
  document: Record<string, unknown>,
  expectedRevision: number,
): ConsoleDraft {
  const now = new Date().toISOString();
  return {
    draftCode: `DRAFT-DEMO-${detail.entityCode}`,
    entityType: detail.entityType,
    entityCode: detail.entityCode,
    draftKind: "input",
    schemaVersion: "console-draft.v1",
    draftRevision: expectedRevision + 1,
    baseEntityRevision: detail.currentRevision,
    status: "active",
    document,
    contentFingerprint: "d".repeat(64),
    createdBy: "operator.demo",
    updatedBy: "operator.demo",
    createdAt: now,
    updatedAt: now,
  };
}


export function EntityDraftEditor({
  detail,
  demoMode,
  onDraftChange,
}: {
  detail: ConsoleEntityDetail;
  demoMode: boolean;
  onDraftChange: (draft: ConsoleDraft | undefined, state: DraftSaveState) => void;
}) {
  const queryClient = useQueryClient();
  const latest = detail.revisions.find((row) => row.revision === detail.currentRevision) ?? detail.revisions[0];
  const [draft, setDraft] = useState<ConsoleDraft>();
  const [title, setTitle] = useState(detail.title);
  const [goal, setGoal] = useState(draftValue(latest?.snapshot.generation_goal, ""));
  const [state, setState] = useState<DraftSaveState>("loading");
  const [dirty, setDirty] = useState(false);
  const [problem, setProblem] = useState<WorkbenchProblem>();
  const generation = useRef(0);
  const initializedFor = useRef("");
  const queryKey = ["console", "draft", detail.entityType, detail.entityCode, "input", demoMode] as const;
  const draftQuery = useQuery({
    queryKey,
    queryFn: async (): Promise<ConsoleDraft | null> => demoMode
      ? null
      : (await consoleApi.draft(detail.entityType, detail.entityCode, "input")) ?? null,
  });

  const applyServerDraft = (serverDraft: ConsoleDraft | undefined) => {
    const document = serverDraft?.document;
    setDraft(serverDraft);
    setTitle(draftValue(document?.title, detail.title));
    setGoal(draftValue(document?.generation_goal, draftValue(latest?.snapshot.generation_goal, "")));
    setDirty(false);
    setProblem(undefined);
    setState("saved");
    onDraftChange(serverDraft, "saved");
  };

  useEffect(() => {
    const key = `${detail.entityType}:${detail.entityCode}`;
    if (draftQuery.isLoading || initializedFor.current === key) return;
    initializedFor.current = key;
    applyServerDraft(draftQuery.data ?? undefined);
  }, [detail.entityCode, detail.entityType, draftQuery.data, draftQuery.isLoading]);

  const saveMutation = useMutation({
    mutationFn: async (input: { editGeneration: number; document: Record<string, unknown>; expectedRevision: number }) => {
      if (demoMode) return demoDraft(detail, input.document, input.expectedRevision);
      return consoleApi.saveDraft(detail.entityType, detail.entityCode, "input", {
        expectedRevision: input.expectedRevision,
        baseEntityRevision: detail.currentRevision,
        document: input.document,
      });
    },
    onMutate: () => {
      setState("saving");
      setProblem(undefined);
      onDraftChange(draft, "saving");
    },
    onSuccess: (saved, input) => {
      setDraft(saved);
      queryClient.setQueryData(queryKey, saved);
      const hasNewerEdits = generation.current !== input.editGeneration;
      setDirty(hasNewerEdits);
      setState(hasNewerEdits ? "editing" : "saved");
      onDraftChange(saved, hasNewerEdits ? "editing" : "saved");
    },
    onError: (error) => {
      const conflict = error instanceof WorkbenchApiError && error.status === 409;
      const nextState = conflict ? "conflict" : "error";
      setState(nextState);
      setProblem(problemFromSave(error));
      onDraftChange(draft, nextState);
    },
  });

  useEffect(() => {
    if (!dirty || saveMutation.isPending || !title.trim() || !goal.trim()) return;
    const timer = window.setTimeout(() => {
      const snapshotContent = latest?.snapshot.content;
      const snapshotSources = latest?.snapshot.source_revision_refs;
      saveMutation.mutate({
        editGeneration: generation.current,
        expectedRevision: draft?.draftRevision ?? 0,
        document: {
          title: title.trim(),
          generation_goal: goal.trim(),
          content: typeof snapshotContent === "object" && snapshotContent !== null ? snapshotContent : {},
          source_revision_refs: Array.isArray(snapshotSources) ? snapshotSources : [],
        },
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [dirty, draft?.draftRevision, goal, latest?.snapshot.content, latest?.snapshot.source_revision_refs, saveMutation.isPending, title]);

  const edit = (setter: (value: string) => void, value: string) => {
    generation.current += 1;
    setter(value);
    setDirty(true);
    setState("editing");
    setProblem(undefined);
    onDraftChange(draft, "editing");
  };
  const reload = async () => {
    const result = await draftQuery.refetch();
    applyServerDraft(result.data ?? undefined);
  };
  const status = {
    loading: { icon: LoaderCircle, label: "正在读取草稿" },
    editing: { icon: Pencil, label: "本地编辑中" },
    saving: { icon: LoaderCircle, label: "保存中" },
    saved: { icon: Check, label: draft ? `已保存 · d${draft.draftRevision}` : "尚未修改" },
    conflict: { icon: AlertTriangle, label: "版本冲突" },
    error: { icon: AlertTriangle, label: "保存失败" },
  }[state];
  const StatusIcon = status.icon;

  return <section className="console-inspector-section console-draft-editor" aria-label="内容项目输入草稿">
    <header><h3><Save size={15} aria-hidden="true" />输入草稿</h3><span className={`console-save-state is-${state}`}><StatusIcon className={state === "loading" || state === "saving" ? "spin" : undefined} size={13} aria-hidden="true" />{status.label}</span></header>
    <label><span>项目标题</span><input value={title} maxLength={255} disabled={state === "loading"} onChange={(event) => edit(setTitle, event.target.value)} /></label>
    <label><span>生成目标</span><textarea value={goal} maxLength={4000} rows={4} disabled={state === "loading"} onChange={(event) => edit(setGoal, event.target.value)} /></label>
    {problem ? <ProblemNotice problem={problem} /> : null}
    {state === "conflict" ? <button type="button" className="wb-button wb-button-secondary" onClick={reload}><RefreshCw size={14} aria-hidden="true" />载入服务器草稿</button> : null}
    {state === "error" ? <button type="button" className="wb-button wb-button-secondary" onClick={() => setDirty(true)}><RefreshCw size={14} aria-hidden="true" />重试保存</button> : null}
  </section>;
}

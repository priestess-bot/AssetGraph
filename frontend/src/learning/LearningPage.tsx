import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CopyPlus, FlaskConical, Lightbulb } from "lucide-react";
import {
  EmptyBlock,
  InlineNotice,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../workbench/components";
import { postJson, requestJson } from "../workbench/api";

type Decision = {
  decision_code: string;
  attribution_report_code?: string;
  observation: string;
  recommendation: string;
};

type Experiment = {
  experiment_code: string;
  title: string;
  metric_key: string;
  variants: string[];
  results: Record<string, { average: number; sample_size: number }>;
};

type AttributionReport = {
  report_code: string;
  metric_key: string;
  evidence_level: string;
  session_codes: string[];
};

type ContentProject = {
  project_code: string;
  title: string;
};

type EffectEstimate = {
  effect_code: string;
  attribution_report_code: string;
  subject_code: string;
  metric_key: string;
  evidence_level: string;
  status: string;
  note: string;
  eligibility_snapshot: {
    qualification?: string;
    selected_session_count?: number;
  };
};

type EffectReproduction = {
  effect_code: string;
  source_project_code: string;
  reproduced_project_code: string;
};

export function LearningPage() {
  const queryClient = useQueryClient();
  const [observation, setObservation] = useState("");
  const [recommendation, setRecommendation] = useState("");
  const [attributionReportCode, setAttributionReportCode] = useState("");
  const [effectReportCode, setEffectReportCode] = useState("");
  const [effectSubjectCode, setEffectSubjectCode] = useState("");
  const [effectNote, setEffectNote] = useState("");
  const [reproduction, setReproduction] = useState<EffectReproduction | null>(null);
  const [title, setTitle] = useState("");
  const [metric, setMetric] = useState("watchers");
  const [variants, setVariants] = useState("control,treatment");
  const [subject, setSubject] = useState("");
  const [value, setValue] = useState(0);

  const decisions = useQuery({
    queryKey: ["learning", "decisions"],
    queryFn: () => requestJson<Decision[]>("/api/functional-learning/decisions"),
  });
  const effects = useQuery({
    queryKey: ["learning", "effects"],
    queryFn: () => requestJson<EffectEstimate[]>("/api/functional-learning/effects"),
  });
  const experiments = useQuery({
    queryKey: ["learning", "experiments"],
    queryFn: () => requestJson<Experiment[]>("/api/functional-learning/experiments"),
  });
  const reports = useQuery({
    queryKey: ["operations", "reports"],
    queryFn: () => requestJson<AttributionReport[]>("/api/functional-operations/attribution-reports"),
  });
  const projects = useQuery({
    queryKey: ["content-projects"],
    queryFn: () => requestJson<ContentProject[]>("/api/content-projects"),
  });

  const decision = useMutation({
    mutationFn: () =>
      postJson("/api/functional-learning/decisions", {
        observation,
        recommendation,
        attribution_report_code: attributionReportCode || undefined,
      }),
    onSuccess: () => {
      setObservation("");
      setRecommendation("");
      setAttributionReportCode("");
      void queryClient.invalidateQueries({ queryKey: ["learning", "decisions"] });
    },
  });
  const createEffect = useMutation({
    mutationFn: () =>
      postJson<EffectEstimate>("/api/functional-learning/effects", {
        attribution_report_code: effectReportCode,
        subject_type: "content_project",
        subject_code: effectSubjectCode,
        note: effectNote,
      }),
    onSuccess: () => {
      setEffectReportCode("");
      setEffectSubjectCode("");
      setEffectNote("");
      void queryClient.invalidateQueries({ queryKey: ["learning", "effects"] });
    },
  });
  const approveEffect = useMutation({
    mutationFn: (effectCode: string) =>
      postJson<EffectEstimate>(`/api/functional-learning/effects/${effectCode}/approve`, {
        actor: "functional-operator",
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["learning", "effects"] }),
  });
  const reproduceEffect = useMutation({
    mutationFn: (effectCode: string) =>
      postJson<EffectReproduction>(`/api/functional-learning/effects/${effectCode}/reproduce`, {}),
    onSuccess: (result) => {
      setReproduction(result);
      void queryClient.invalidateQueries({ queryKey: ["content-projects"] });
    },
  });
  const experiment = useMutation({
    mutationFn: () =>
      postJson("/api/functional-learning/experiments", {
        title,
        metric_key: metric,
        variants: variants.split(",").map((item) => item.trim()).filter(Boolean),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["learning", "experiments"] }),
  });
  const outcome = useMutation({
    mutationFn: (code: string) =>
      postJson(`/api/functional-learning/experiments/${code}/outcomes`, {
        subject_key: subject,
        metric_value: value,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["learning", "experiments"] }),
  });

  if (
    decisions.isLoading || effects.isLoading || experiments.isLoading || reports.isLoading || projects.isLoading
  ) {
    return <LoadingBlock />;
  }
  const error =
    decision.error ?? createEffect.error ?? approveEffect.error ?? reproduceEffect.error ?? experiment.error ??
    outcome.error ?? reports.error ?? projects.error;

  return (
    <div className="operations-layout">
      <section className="wb-section">
        <SectionHeader kicker="DECISION LOG" title="学习与实验" />
        <form
          className="operations-form"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            decision.mutate();
          }}
        >
          <label className="wb-field">
            <span>观察</span>
            <textarea className="wb-textarea" value={observation} onChange={(event) => setObservation(event.target.value)} required />
          </label>
          <label className="wb-field">
            <span>再生产建议</span>
            <textarea className="wb-textarea" value={recommendation} onChange={(event) => setRecommendation(event.target.value)} required />
          </label>
          <label className="wb-field">
            <span>归因报告</span>
            <select className="wb-input" value={attributionReportCode} onChange={(event) => setAttributionReportCode(event.target.value)}>
              <option value="">不关联归因报告</option>
              {reports.data?.map((report) => (
                <option key={report.report_code} value={report.report_code}>
                  {report.metric_key} · {report.evidence_level} · {report.report_code}
                </option>
              ))}
            </select>
          </label>
          <button className="wb-button wb-button-primary" disabled={decision.isPending}>
            <Lightbulb size={15} aria-hidden="true" />
            记录决策
          </button>
        </form>
        <form
          className="operations-form"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            experiment.mutate();
          }}
        >
          <label className="wb-field"><span>实验名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
          <label className="wb-field"><span>指标</span><input className="wb-input" value={metric} onChange={(event) => setMetric(event.target.value)} /></label>
          <label className="wb-field"><span>两个版本</span><input className="wb-input" value={variants} onChange={(event) => setVariants(event.target.value)} /></label>
          <button className="wb-button" disabled={experiment.isPending}><FlaskConical size={15} aria-hidden="true" />创建 A/B</button>
        </form>
        {error ? <InlineNotice tone="danger" title="学习操作失败">{error instanceof Error ? error.message : "请求失败"}</InlineNotice> : null}
      </section>

      <section className="wb-section">
        <SectionHeader kicker="EFFECT EVIDENCE" title="效果证据" />
        <form
          className="operations-form"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            createEffect.mutate();
          }}
        >
          <label className="wb-field">
            <span>效果归因报告</span>
            <select className="wb-input" value={effectReportCode} onChange={(event) => setEffectReportCode(event.target.value)} required>
              <option value="">选择报告</option>
              {reports.data?.map((report) => (
                <option key={report.report_code} value={report.report_code}>
                  {report.metric_key} · {report.evidence_level} · {report.report_code}
                </option>
              ))}
            </select>
          </label>
          <label className="wb-field">
            <span>再生产源项目</span>
            <select className="wb-input" value={effectSubjectCode} onChange={(event) => setEffectSubjectCode(event.target.value)} required>
              <option value="">选择内容项目</option>
              {projects.data?.map((project) => (
                <option key={project.project_code} value={project.project_code}>
                  {project.title} · {project.project_code}
                </option>
              ))}
            </select>
          </label>
          <label className="wb-field">
            <span>人工判断</span>
            <textarea className="wb-textarea" value={effectNote} onChange={(event) => setEffectNote(event.target.value)} required />
          </label>
          <button className="wb-button wb-button-primary" disabled={createEffect.isPending}>
            <Lightbulb size={15} aria-hidden="true" />
            建立效果证据
          </button>
        </form>
        {reproduction ? (
          <InlineNotice tone="success" title="已建立再生产草稿">
            {reproduction.reproduced_project_code} 源自 {reproduction.source_project_code} / {reproduction.effect_code}
          </InlineNotice>
        ) : null}
      </section>

      <section className="wb-section">
        <SectionHeader kicker="DESCRIPTIVE RESULTS" title="决策、效果与结果" />
        {effects.data?.map((item) => (
          <div className="operations-list" key={item.effect_code}>
            <div>
              <span>
                <strong>{item.subject_code} · {item.metric_key}</strong>
                <small>{item.note}</small>
                <small>{item.attribution_report_code} · {item.eligibility_snapshot.qualification ?? item.evidence_level} · {item.eligibility_snapshot.selected_session_count ?? 0} 场</small>
                <code>{item.effect_code}</code>
              </span>
              <div className="operations-list-actions">
                {item.status === "approved" ? (
                  <button className="wb-button" onClick={() => reproduceEffect.mutate(item.effect_code)} disabled={reproduceEffect.isPending}>
                    <CopyPlus size={15} aria-hidden="true" />
                    建立草稿
                  </button>
                ) : (
                  <button className="wb-button" onClick={() => approveEffect.mutate(item.effect_code)} disabled={approveEffect.isPending}>
                    <Check size={15} aria-hidden="true" />
                    确认效果
                  </button>
                )}
                <StatusBadge label={item.status === "approved" ? "已确认" : "候选"} tone={item.status === "approved" ? "success" : "warning"} />
              </div>
            </div>
          </div>
        ))}
        {decisions.data?.map((item) => (
          <div className="operations-list" key={item.decision_code}>
            <div><span><strong>{item.observation}</strong><small>{item.recommendation}</small>{item.attribution_report_code ? <small>归因报告：{item.attribution_report_code}</small> : null}<code>{item.decision_code}</code></span><StatusBadge label="建议" tone="info" /></div>
          </div>
        ))}
        {experiments.data?.map((item) => (
          <div className="operations-list" key={item.experiment_code}>
            <div><span><strong>{item.title} · {item.metric_key}</strong><small>{Object.entries(item.results).map(([key, result]) => `${key}: ${result.average.toFixed(2)} (${result.sample_size})`).join(" / ")}</small><code>{item.experiment_code}</code></span><StatusBadge label="A/B 描述性" tone="warning" /></div>
            <form className="operations-form" onSubmit={(event: FormEvent) => { event.preventDefault(); outcome.mutate(item.experiment_code); }}>
              <input className="wb-input" aria-label={`实验主体 ${item.experiment_code}`} value={subject} onChange={(event) => setSubject(event.target.value)} required />
              <input className="wb-input" aria-label={`实验指标值 ${item.experiment_code}`} type="number" value={value} onChange={(event) => setValue(Number(event.target.value))} />
              <button className="wb-button" disabled={outcome.isPending}>回填结果</button>
            </form>
          </div>
        ))}
        {!effects.data?.length && !decisions.data?.length && !experiments.data?.length ? <EmptyBlock icon={FlaskConical} title="尚无学习记录" /> : null}
      </section>
    </div>
  );
}

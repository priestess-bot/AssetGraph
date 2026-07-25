import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CircleAlert, ShieldOff } from "lucide-react";
import { EmptyBlock, InlineNotice, LoadingBlock, SectionHeader, StatusBadge, formatDate } from "../workbench/components";
import { releasesApi } from "../releases/api";
import { broadcastSchedulesApi, type BroadcastScheduleCreate } from "./api";

function split(value: string): string[] { return value.split(/\n|,/).map((item) => item.trim()).filter(Boolean); }
function message(error: unknown): string { return error instanceof Error ? error.message : "排播操作未完成"; }
function tone(status: string): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "validated") return "success";
  if (status === "approval_required") return "warning";
  if (["rejected", "canceled"].includes(status)) return "danger";
  return "info";
}
function label(status: string): string {
  return ({ draft: "草稿", validated: "已验证", approval_required: "需要批准", approved: "已批准", active: "执行中", rejected: "已拒绝", canceled: "已取消", completed: "已完成" } as Record<string, string>)[status] ?? status;
}

export function SchedulesPage() {
  const client = useQueryClient();
  const [title, setTitle] = useState("");
  const [releaseCode, setReleaseCode] = useState("");
  const [accountId, setAccountId] = useState("");
  const [roomId, setRoomId] = useState("");
  const [platform, setPlatform] = useState("douyin");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [owner, setOwner] = useState("functional-operator");
  const [promotions, setPromotions] = useState("");
  const [inventory, setInventory] = useState("");
  const [stopConditions, setStopConditions] = useState("");
  const releases = useQuery({ queryKey: ["releases"], queryFn: releasesApi.list });
  const schedules = useQuery({ queryKey: ["broadcast-schedules"], queryFn: broadcastSchedulesApi.list });
  const create = useMutation({
    mutationFn: () => {
      const payload: BroadcastScheduleCreate = {
        title,
        release_code: releaseCode,
        target_account_id: accountId,
        target_room_id: roomId,
        platform,
        timezone,
        starts_at: `${startsAt}:00Z`,
        ends_at: `${endsAt}:00Z`,
        owner,
        promotion_dependencies: split(promotions),
        inventory_dependencies: split(inventory),
        conflict_strategy: "manual_reschedule",
        stop_conditions: split(stopConditions),
      };
      return broadcastSchedulesApi.create(payload);
    },
    onSuccess: () => {
      setTitle(""); setReleaseCode(""); setAccountId(""); setRoomId(""); setStartsAt(""); setEndsAt(""); setPromotions(""); setInventory(""); setStopConditions("");
      void client.invalidateQueries({ queryKey: ["broadcast-schedules"] });
    },
  });
  const validate = useMutation({
    mutationFn: (scheduleCode: string) => broadcastSchedulesApi.validate(scheduleCode),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["broadcast-schedules"] }),
  });
  const problem = releases.error ?? schedules.error ?? create.error ?? validate.error;

  return <div className="operations-layout">
    <section className="wb-section">
      <SectionHeader kicker="BROADCAST SCHEDULE" title="排播计划" />
      <InlineNotice tone="info" title="开播能力关闭"><ShieldOff size={15} aria-hidden="true" />本工作区只创建和验证计划，不会请求任何外部平台操作。</InlineNotice>
      <form className="operations-form" onSubmit={(event: FormEvent) => { event.preventDefault(); create.mutate(); }}>
        <label className="wb-field"><span>计划名称</span><input className="wb-input" value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
        <label className="wb-field"><span>固定 Release</span><select className="wb-input" value={releaseCode} onChange={(event) => setReleaseCode(event.target.value)} required><option value="">选择发布记录</option>{releases.data?.map((release) => <option key={release.releaseCode} value={release.releaseCode}>{release.subjectCode} · {release.releaseCode} · {release.status}</option>)}</select></label>
        <label className="wb-field"><span>目标账号</span><input className="wb-input" value={accountId} onChange={(event) => setAccountId(event.target.value)} required /></label>
        <label className="wb-field"><span>目标直播间</span><input className="wb-input" value={roomId} onChange={(event) => setRoomId(event.target.value)} required /></label>
        <label className="wb-field"><span>平台</span><input className="wb-input" value={platform} onChange={(event) => setPlatform(event.target.value)} required /></label>
        <label className="wb-field"><span>目标时区</span><input className="wb-input" value={timezone} onChange={(event) => setTimezone(event.target.value)} required /></label>
        <label className="wb-field"><span>开始窗口（UTC）</span><input className="wb-input" type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} required /></label>
        <label className="wb-field"><span>结束窗口（UTC）</span><input className="wb-input" type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} required /></label>
        <label className="wb-field"><span>负责人</span><input className="wb-input" value={owner} onChange={(event) => setOwner(event.target.value)} required /></label>
        <label className="wb-field"><span>促销依赖</span><input className="wb-input" value={promotions} onChange={(event) => setPromotions(event.target.value)} /></label>
        <label className="wb-field"><span>库存依赖</span><input className="wb-input" value={inventory} onChange={(event) => setInventory(event.target.value)} /></label>
        <label className="wb-field"><span>停止条件</span><textarea className="wb-textarea" value={stopConditions} onChange={(event) => setStopConditions(event.target.value)} /></label>
        <button className="wb-button wb-button-primary" disabled={create.isPending || releases.isLoading}><CalendarClock size={15} aria-hidden="true" />创建排播草稿</button>
      </form>
      {problem ? <InlineNotice tone="danger" title="排播计划未完成">{message(problem)}</InlineNotice> : null}
    </section>

    <section className="wb-section">
      <SectionHeader kicker="SCHEDULE REVISIONS" title="本地验证" />
      {schedules.isLoading ? <LoadingBlock /> : schedules.data?.length ? <div className="operations-list">{schedules.data.map((schedule) => <div key={schedule.scheduleCode}><span><strong>{schedule.title}</strong><small>{schedule.targetAccountId} / {schedule.targetRoomId} · {formatDate(schedule.startsAt)} - {formatDate(schedule.endsAt)}</small><small>{schedule.releaseCode} · r{schedule.revisionNumber} · {schedule.timezone}</small><code>{schedule.scheduleCode}</code></span><div className="operations-list-actions"><button className="wb-button" onClick={() => validate.mutate(schedule.scheduleCode)} disabled={validate.isPending}>验证</button><StatusBadge label={label(schedule.status)} tone={tone(schedule.status)} /></div><details><summary>验证证据</summary><pre>{JSON.stringify(schedule.validationResult, null, 2)}</pre></details></div>)}</div> : <EmptyBlock icon={CircleAlert} title="尚无排播计划" />}
    </section>
  </div>;
}

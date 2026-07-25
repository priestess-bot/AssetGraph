import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  Copy,
  FileCheck2,
  GitFork,
  MonitorUp,
  Send,
  WandSparkles,
} from "lucide-react";
import {
  assetLibraryApi,
  type AssetGap,
  type LibraryAsset,
} from "../assets/api";
import { contentProjectsApi } from "../content/api";
import {
  EmptyBlock,
  InlineNotice,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../workbench/components";
import {
  functionalLiveRoomsApi,
  type FunctionalLiveRoomPlan,
  type RoomConstraintOverride,
} from "./api";

function message(error: unknown): string {
  return error instanceof Error ? error.message : "操作未完成";
}
function toggle(values: string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}

function tone(
  status: string,
): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "ready" || status === "maitu_complete") return "success";
  if (status === "blocked") return "danger";
  if (status === "requested") return "warning";
  return "neutral";
}

function label(status: string): string {
  return (
    (
      {
        ready: "可生成草稿",
        blocked: "素材或约束阻断",
        not_requested: "尚未请求",
        requested: "等待麦兔 Worker",
        maitu_complete: "已由麦兔完成",
      } as Record<string, string>
    )[status] ?? status
  );
}

function gateTone(
  status: string,
): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "pass") return "success";
  if (status === "blocked") return "danger";
  if (status === "warning") return "warning";
  return "neutral";
}

function inheritedTemplates(
  project: Awaited<ReturnType<typeof contentProjectsApi.get>> | undefined,
) {
  return (
    project?.templateContributionDecisions.map((decision) => ({
      templateCode: decision.templateCode,
      revision: decision.revision,
      selectionRole: decision.selectionRole,
      acceptedModules: decision.acceptedModules,
    })) ?? []
  );
}

function defaultRoomGeometry(
  role: string | undefined,
): NonNullable<RoomConstraintOverride["geometry"]> {
  if (role === "background") return { x: 0, y: 0, width: 1, height: 1 };
  if (role === "digital_human")
    return { x: 0.08, y: 0.18, width: 0.36, height: 0.64 };
  if (role === "promotion_text")
    return { x: 0.08, y: 0.78, width: 0.84, height: 0.14 };
  return { x: 0.52, y: 0.28, width: 0.4, height: 0.4 };
}

function RoomConstraintOverrideEditor({
  assets,
  overrides,
  onChange,
}: {
  assets: Array<{ assetCode: string; title: string; materialRoles: string[] }>;
  overrides: Record<string, RoomConstraintOverride>;
  onChange: (next: Record<string, RoomConstraintOverride>) => void;
}) {
  if (!assets.length) return null;
  const update = (
    assetCode: string,
    change: (current: RoomConstraintOverride) => RoomConstraintOverride,
  ) => {
    const current = overrides[assetCode];
    if (!current) return;
    onChange({ ...overrides, [assetCode]: change(current) });
  };
  return (
    <div className="live-room-constraint-overrides">
      <span>房间私有位置与图层</span>
      <small>
        仅写入当前直播间计划；素材库的 Profile
        不会被修改，且其中的硬约束仍会生效。
      </small>
      {assets.map((asset) => {
        const override = overrides[asset.assetCode];
        const geometry = override?.geometry;
        return (
          <article key={asset.assetCode}>
            <label className="live-room-constraint-toggle">
              <input
                type="checkbox"
                aria-label={`${asset.assetCode} 仅当前直播间位置与图层`}
                checked={Boolean(override)}
                onChange={(event) => {
                  if (event.target.checked)
                    onChange({
                      ...overrides,
                      [asset.assetCode]: {
                        reason: "",
                        geometry: defaultRoomGeometry(asset.materialRoles[0]),
                      },
                    });
                  else {
                    const next = { ...overrides };
                    delete next[asset.assetCode];
                    onChange(next);
                  }
                }}
              />
              <span>
                <strong>{asset.title}</strong>
                <code>{asset.assetCode}</code>
              </span>
            </label>
            {override ? (
              <div className="live-room-constraint-fields">
                <label className="wb-field wide">
                  <span>覆盖原因</span>
                  <input
                    className="wb-input"
                    aria-label={`${asset.assetCode} 覆盖原因`}
                    value={override.reason}
                    onChange={(event) =>
                      update(asset.assetCode, (current) => ({
                        ...current,
                        reason: event.target.value,
                      }))
                    }
                    placeholder="例如：适配当前直播间的商品陈列区域"
                  />
                </label>
                <div className="live-room-geometry-fields">
                  {(["x", "y", "width", "height"] as const).map((key) => (
                    <label className="wb-field" key={key}>
                      <span>
                        {key === "x"
                          ? "X"
                          : key === "y"
                            ? "Y"
                            : key === "width"
                              ? "宽"
                              : "高"}
                      </span>
                      <input
                        className="wb-input"
                        aria-label={`${asset.assetCode} 覆盖 ${key}`}
                        type="number"
                        min="0"
                        max="1"
                        step="0.01"
                        value={geometry?.[key] ?? ""}
                        onChange={(event) =>
                          update(asset.assetCode, (current) => ({
                            ...current,
                            geometry: {
                              ...(current.geometry ??
                                defaultRoomGeometry(asset.materialRoles[0])),
                              [key]: Number(event.target.value),
                            },
                          }))
                        }
                      />
                    </label>
                  ))}
                </div>
                <label className="wb-field">
                  <span>图层顺序</span>
                  <input
                    className="wb-input"
                    aria-label={`${asset.assetCode} 覆盖图层顺序`}
                    type="number"
                    min="-999"
                    max="999"
                    step="1"
                    value={override.zOrder ?? ""}
                    onChange={(event) =>
                      update(asset.assetCode, (current) => ({
                        ...current,
                        zOrder:
                          event.target.value === ""
                            ? undefined
                            : Number(event.target.value),
                      }))
                    }
                    placeholder="可选"
                  />
                </label>
                {!override.reason.trim() ? (
                  <small className="live-room-constraint-warning">
                    填写原因后才能生成计划
                  </small>
                ) : null}
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function BranchGapWaiverFields({
  gaps,
  selectedGapCodes,
  waivers,
  onChange,
}: {
  gaps: AssetGap[];
  selectedGapCodes: string[];
  waivers: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const eligibleGaps = gaps.filter(
    (gap) =>
      selectedGapCodes.includes(gap.gapCode) &&
      ["open", "candidate_found"].includes(gap.status),
  );
  if (!eligibleGaps.length) return null;
  return (
    <div className="live-room-constraint-overrides">
      <span>当前计划的缺口豁免</span>
      <small>
        仅影响本次计划冻结的缺口引用，不会修改素材库缺口状态，也不会被克隆到新计划。
      </small>
      {eligibleGaps.map((gap) => (
        <label className="wb-field" key={gap.gapCode}>
          <span>
            {gap.gapCode} · {gap.title}
          </span>
          <input
            className="wb-input"
            aria-label={`${gap.gapCode} 当前计划豁免原因`}
            value={waivers[gap.gapCode] ?? ""}
            onChange={(event) => {
              const reason = event.target.value;
              const next = { ...waivers };
              if (reason) next[gap.gapCode] = reason;
              else delete next[gap.gapCode];
              onChange(next);
            }}
            placeholder="可选：说明为何当前计划允许继续"
          />
        </label>
      ))}
    </div>
  );
}

function RequiredLooseAssetFields({
  assets,
  selectedAssetCodes,
  requiredAssetCodes,
  onChange,
}: {
  assets: LibraryAsset[];
  selectedAssetCodes: string[];
  requiredAssetCodes: string[];
  onChange: (next: string[]) => void;
}) {
  const selectedAssets = assets.filter((asset) =>
    selectedAssetCodes.includes(asset.assetCode),
  );
  if (!selectedAssets.length) return null;
  return (
    <div className="live-selection">
      <span>零散素材使用要求</span>
      <small>
        未勾选的零散素材只进入候选白名单；勾选后必须在本次生成的至少一个图层中实际出现。
      </small>
      {selectedAssets.map((asset) => (
        <label key={asset.assetCode}>
          <input
            type="checkbox"
            aria-label={`${asset.assetCode} 至少使用一次`}
            checked={requiredAssetCodes.includes(asset.assetCode)}
            onChange={() =>
              onChange(toggle(requiredAssetCodes, asset.assetCode))
            }
          />
          <span>
            <strong>{asset.title}</strong>
            <small>{asset.assetCode} · 至少使用一次</small>
          </span>
        </label>
      ))}
    </div>
  );
}

function PlanDetail({ plan }: { plan: FunctionalLiveRoomPlan }) {
  const queryClient = useQueryClient();
  const [confirmed, setConfirmed] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloneRoomId, setCloneRoomId] = useState("");
  const [cloneTitle, setCloneTitle] = useState("");
  const [traceVisible, setTraceVisible] = useState(false);
  const [promotionReasons, setPromotionReasons] = useState<
    Record<string, string>
  >({});
  const [promotionConfirmed, setPromotionConfirmed] = useState<
    Record<string, boolean>
  >({});
  const request = useMutation({
    mutationFn: () => functionalLiveRoomsApi.confirmExecution(plan.planCode),
    onSuccess: (next) => {
      queryClient.setQueryData(
        ["functional-live-room-plan", plan.planCode],
        next,
      );
      void queryClient.invalidateQueries({
        queryKey: ["functional-live-room-plans"],
      });
    },
  });
  const release = useMutation({
    mutationFn: () =>
      functionalLiveRoomsApi.createReleaseCandidate(plan.planCode),
    onSuccess: (next) => {
      queryClient.setQueryData(
        ["functional-live-room-plan", plan.planCode],
        next,
      );
      void queryClient.invalidateQueries({
        queryKey: ["functional-live-room-plans"],
      });
    },
  });
  const clone = useMutation({
    mutationFn: () =>
      functionalLiveRoomsApi.clone(plan.planCode, {
        target_live_room_id: cloneRoomId,
        expected_title: cloneTitle,
      }),
    onSuccess: (next) => {
      setCloneOpen(false);
      setCloneRoomId("");
      setCloneTitle("");
      queryClient.setQueryData(
        ["functional-live-room-plan", next.planCode],
        next,
      );
      void queryClient.invalidateQueries({
        queryKey: ["functional-live-room-plans"],
      });
    },
  });
  const promote = useMutation({
    mutationFn: ({
      assetCode,
      expectedRevision,
      reason,
    }: {
      assetCode: string;
      expectedRevision: number;
      reason: string;
    }) =>
      assetLibraryApi.promoteRoomConstraintOverride(assetCode, {
        plan_code: plan.planCode,
        expected_revision: expectedRevision,
        actor: "functional-operator",
        reason,
      }),
    onSuccess: async (_profile, variables) => {
      setPromotionReasons((current) => ({
        ...current,
        [variables.assetCode]: "",
      }));
      setPromotionConfirmed((current) => ({
        ...current,
        [variables.assetCode]: false,
      }));
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["assets", "constraint-profile", variables.assetCode],
        }),
        queryClient.invalidateQueries({
          queryKey: [
            "assets",
            "constraint-profile",
            variables.assetCode,
            "revisions",
          ],
        }),
      ]);
    },
  });
  const trace = useQuery({
    queryKey: ["functional-live-room-trace", plan.planCode],
    queryFn: () => functionalLiveRoomsApi.getTrace(plan.planCode),
    enabled: traceVisible,
  });
  return (
    <div className="live-plan-detail">
      <section className="wb-section">
        <SectionHeader
          kicker={plan.planCode}
          title={plan.expectedTitle}
          actions={
            <div className="live-plan-badges">
              <StatusBadge
                label={label(plan.status)}
                tone={tone(plan.status)}
              />
              <StatusBadge
                label={label(plan.executionStatus)}
                tone={tone(plan.executionStatus)}
              />
            </div>
          }
        />
        <div className="live-plan-summary">
          <div>
            <span>目标直播间</span>
            <strong>{plan.targetLiveRoomId}</strong>
          </div>
          <div>
            <span>生产变体</span>
            <code>{plan.variantCode}</code>
          </div>
          <div>
            <span>直播间配置</span>
            <code>{plan.configurationCode}</code>
          </div>
          <div>
            <span>开播动作</span>
            <strong>已关闭</strong>
          </div>
        </div>
        {plan.blockedReasons.length ? (
          <InlineNotice tone="danger" title="BuildPlan 已阻断">
            {plan.blockedReasons.join("；")}
          </InlineNotice>
        ) : (
          <InlineNotice tone="info" title="当前计划仅生成草稿">
            计划中不包含开播操作。请求后仍须由已配置的麦兔 Worker
            校验空白草稿并写入。
          </InlineNotice>
        )}
      </section>
      <section className="wb-section">
        <SectionHeader kicker="STATIC GATES" title="输入与分支质量" />
        <div className="live-plan-summary">
          {plan.gateResults.map((gate) => (
            <div key={gate.gate}>
              <span>{gate.gate}</span>
              <strong>{gate.ruleCode}</strong>
              <StatusBadge label={gate.status} tone={gateTone(gate.status)} />
            </div>
          ))}
          <div>
            <span>预计时长</span>
            <strong>
              {typeof plan.qualityReport.estimated_total_duration_ms ===
              "number"
                ? `${Math.round(plan.qualityReport.estimated_total_duration_ms / 1000)} 秒`
                : "未计算"}
            </strong>
          </div>
        </div>
      </section>
      <section className="wb-section">
        <SectionHeader
          kicker="RESOLVED MATERIAL SNAPSHOT"
          title="已选素材与来源"
        />
        <div className="live-material-snapshot">
          {plan.materialSnapshot.assets.map((asset) => {
            const override =
              plan.materialSnapshot.roomConstraintOverrides[asset.assetCode];
            const reason = promotionReasons[asset.assetCode] ?? "";
            const confirmedPromotion =
              promotionConfirmed[asset.assetCode] ?? false;
            return (
              <article key={asset.assetCode}>
                <header>
                  <code>{asset.assetCode}</code>
                  <StatusBadge
                    label={asset.executionCapability || "未声明"}
                    tone={
                      asset.executionCapability === "maitu_bound"
                        ? "success"
                        : "neutral"
                    }
                  />
                </header>
                <small>{asset.materialRoles.join(" / ") || "未分类"}</small>
                <div>
                  {asset.selectionSources.length ? (
                    asset.selectionSources.map((source) => (
                      <span key={`${source.kind}:${source.code}`}>
                        {source.kind}: <code>{source.code}</code>
                      </span>
                    ))
                  ) : (
                    <span>历史快照未记录选择来源</span>
                  )}
                </div>
                <small>
                  {asset.constraintProfile
                    ? `约束 ${asset.constraintProfile.profileCode} · r${asset.constraintProfile.revision}`
                    : "未绑定约束 Profile"}
                </small>
                {override?.geometry ? (
                  <div className="live-room-constraint-promotion">
                    <small>房间覆盖：{override.reason}</small>
                    <label className="wb-field">
                      <span>提升原因</span>
                      <input
                        className="wb-input"
                        aria-label={`${asset.assetCode} 提升原因`}
                        value={reason}
                        onChange={(event) =>
                          setPromotionReasons((current) => ({
                            ...current,
                            [asset.assetCode]: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        aria-label={`${asset.assetCode} 确认提升为全局约束`}
                        checked={confirmedPromotion}
                        onChange={(event) =>
                          setPromotionConfirmed((current) => ({
                            ...current,
                            [asset.assetCode]: event.target.checked,
                          }))
                        }
                      />
                      我理解这会创建新的全局硬约束修订
                    </label>
                    <button
                      type="button"
                      className="wb-button"
                      disabled={
                        promote.isPending ||
                        !reason.trim() ||
                        !confirmedPromotion
                      }
                      onClick={() =>
                        promote.mutate({
                          assetCode: asset.assetCode,
                          expectedRevision:
                            asset.constraintProfile?.revision ?? 0,
                          reason: reason.trim(),
                        })
                      }
                    >
                      提升为全局约束
                    </button>
                  </div>
                ) : override ? (
                  <small>
                    该房间覆盖仅含图层顺序，无法安全提升为全局 Profile。
                  </small>
                ) : null}
              </article>
            );
          })}
        </div>
        {promote.error ? (
          <InlineNotice tone="danger" title="全局约束修订未创建">
            {message(promote.error)}
          </InlineNotice>
        ) : null}
        {plan.materialSnapshot.materialPackRefs.length ? (
          <div className="live-material-pack-refs">
            {plan.materialSnapshot.materialPackRefs.map((pack) => (
              <span key={pack.packCode}>
                <code>{pack.packCode}</code> r{pack.revisionNumber} ·{" "}
                {pack.role}
              </span>
            ))}
          </div>
        ) : null}
        {Object.keys(plan.materialRoleModes).length ? (
          <div className="live-material-pack-refs">
            {Object.entries(plan.materialRoleModes).map(([role, mode]) => (
              <span key={role}>
                <strong>{role}</strong> ·{" "}
                {mode === "inherit"
                  ? "沿用"
                  : mode === "append"
                    ? "追加"
                    : "替换"}
              </span>
            ))}
          </div>
        ) : null}
        {plan.requiredLooseAssetCodes.length ? (
          <div className="live-material-pack-refs">
            {plan.requiredLooseAssetCodes.map((assetCode) => (
              <span key={assetCode}>
                <strong>{assetCode}</strong> · 至少使用一次
              </span>
            ))}
          </div>
        ) : null}
        {plan.materialSnapshot.assetGapRefs.length ? (
          <div className="live-material-gap-refs">
            {plan.materialSnapshot.assetGapRefs.map((gap) => (
              <span key={gap.gapCode}>
                <code>{gap.gapCode}</code>
                <strong>{gap.title}</strong>
                <small>
                  {gap.role} · {gap.gapType}
                </small>
                <StatusBadge
                  label={gap.status}
                  tone={
                    ["open", "candidate_found"].includes(gap.status)
                      ? "warning"
                      : "success"
                  }
                />
              </span>
            ))}
          </div>
        ) : null}
      </section>
      {Object.keys(plan.materialSnapshot.roomConstraintOverrides).length ? (
        <section className="wb-section">
          <SectionHeader
            kicker="ROOM-PRIVATE CONSTRAINTS"
            title="本房间素材位置与图层覆盖"
          />
          <div className="live-room-override-summary">
            {Object.entries(plan.materialSnapshot.roomConstraintOverrides).map(
              ([assetCode, override]) => (
                <article key={assetCode}>
                  <code>{assetCode}</code>
                  <span>
                    {override.geometry
                      ? `x ${override.geometry.x} · y ${override.geometry.y} · ${override.geometry.width} x ${override.geometry.height}`
                      : "未覆盖位置"}
                  </span>
                  <span>
                    {typeof override.zOrder === "number"
                      ? `图层 ${override.zOrder}`
                      : "未覆盖图层"}
                  </span>
                  <small>
                    {override.reason}
                    {override.actorId ? ` · ${override.actorId}` : ""}
                  </small>
                </article>
              ),
            )}
          </div>
        </section>
      ) : null}
      <section className="wb-section">
        <SectionHeader kicker="MATERIAL SELECTION" title="角色选材结果" />
        {plan.materialSelectionDecisions.length ? (
          <div className="live-material-selection-list">
            {plan.materialSelectionDecisions.map((decision, index) => (
              <article
                key={`${decision.shotCode ?? "global"}:${decision.role}:${index}`}
              >
                <span>
                  <strong>{decision.role}</strong>
                  <small>
                    {decision.shotCode ?? "全局"} · {decision.strategy}
                  </small>
                </span>
                <code>{decision.selectedAssetCode}</code>
                <b>{decision.selectedScore}</b>
                <small>
                  {decision.selectionReasons.join(" / ")}
                  {Object.keys(decision.selectedScoreParts).length
                    ? ` · ${Object.entries(decision.selectedScoreParts)
                        .map(([key, value]) => `${key}:${value}`)
                        .join("，")}`
                    : ""}
                  {decision.candidateScores.length
                    ? ` · ${decision.candidateScores
                        .map(
                          (candidate) =>
                            `${candidate.assetCode}:${candidate.score}${
                              Object.keys(candidate.scoreParts).length
                                ? `(${Object.entries(candidate.scoreParts)
                                    .map(([key, value]) => `${key}:${value}`)
                                    .join("/")})`
                                : ""
                            }`,
                        )
                        .join("，")}`
                    : ""}
                </small>
              </article>
            ))}
          </div>
        ) : (
          <EmptyBlock icon={CircleAlert} title="尚无选材决策" />
        )}
      </section>
      <section className="wb-section">
        <SectionHeader kicker="MAITU SCENE BLUEPRINT" title="场景与图层" />
        <div className="live-scene-list">
          {plan.blueprint.scenes.map((scene) => (
            <article key={scene.scene_code}>
              <header>
                <span>{scene.scene_code}</span>
                <strong>{scene.title}</strong>
                <code>{scene.shot_code}</code>
              </header>
              <p>{scene.script}</p>
              <div>
                {scene.layers.map((layer) => (
                  <span
                    key={`${scene.scene_code}:${layer.role}:${layer.asset_code}`}
                  >
                    <b>{layer.z_order}</b>
                    {layer.role}
                    <code>{layer.asset_code}</code>
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
      <section className="wb-section">
        <SectionHeader
          kicker={plan.buildPlan.build_plan_code ?? "BUILD PLAN"}
          title="麦兔草稿操作"
          actions={
            <StatusBadge
              label={plan.buildPlan.go_live ? "包含开播" : "不含开播"}
              tone={plan.buildPlan.go_live ? "danger" : "success"}
            />
          }
        />
        <ol className="live-operation-list">
          {plan.buildPlan.operations.map((operation, index) => (
            <li key={`${operation.kind}:${index}`}>
              <b>{index + 1}</b>
              <span>{operation.kind}</span>
              <code>
                {operation.scene_code ??
                  operation.asset_code ??
                  operation.script_block_code ??
                  ""}
              </code>
            </li>
          ))}
        </ol>
      </section>
      <section className="wb-section">
        <SectionHeader
          kicker="PROVENANCE"
          title="操作来源追溯"
          actions={
            <button
              type="button"
              className="wb-icon-button"
              aria-label="加载操作来源追溯"
              title="加载操作来源追溯"
              onClick={() => setTraceVisible((visible) => !visible)}
            >
              <GitFork size={15} aria-hidden="true" />
            </button>
          }
        />
        {traceVisible && trace.isLoading ? (
          <LoadingBlock label="正在加载操作来源" />
        ) : null}
        {traceVisible && trace.data ? (
          <div className="live-trace-list">
            {trace.data.operations.map((operation) => (
              <article key={operation.operationId}>
                <header>
                  <b>{operation.sortOrder}</b>
                  <strong>{operation.operationType}</strong>
                  <span>{operation.operationName}</span>
                </header>
                {operation.targets.map((target) => (
                  <div
                    key={`${operation.operationId}:${target.targetType}:${target.targetCode}`}
                  >
                    <code>{target.targetCode}</code>
                    <span>{target.relationType}</span>
                    {target.shot ? <small>{target.shot.shotCode}</small> : null}
                    {target.programSegment ? (
                      <small>{target.programSegment.segmentCode}</small>
                    ) : null}
                    {target.scriptBlocks.map((block) => (
                      <small key={block.blockCode}>{block.blockCode}</small>
                    ))}
                  </div>
                ))}
              </article>
            ))}
          </div>
        ) : null}
      </section>
      {trace.error ? (
        <InlineNotice tone="danger" title="操作来源无法加载">
          {message(trace.error)}
        </InlineNotice>
      ) : null}
      <section className="live-request-panel">
        <div>
          <span>发布候选</span>
          <strong>
            {plan.release
              ? `${plan.release.releaseCode} · ${plan.release.status}`
              : "尚未创建"}
          </strong>
          <small>
            {plan.release
              ? `Manifest ${plan.release.manifestCode}；仍待权利、执行授权和现场回读。`
              : "创建后固定内容链、素材快照、Blueprint、BuildPlan 和当前质量结果。"}
          </small>
        </div>
        {plan.release ? (
          <div className="live-plan-badges">
            <StatusBadge label={plan.release.status} tone="warning" />
            <code>{plan.release.snapshotArtifactCode}</code>
          </div>
        ) : (
          <button
            type="button"
            className="wb-button wb-button-secondary"
            disabled={plan.status !== "ready" || release.isPending}
            onClick={() => release.mutate()}
          >
            <FileCheck2 size={15} aria-hidden="true" />
            创建发布候选
          </button>
        )}
      </section>
      {release.error ? (
        <InlineNotice tone="danger" title="发布候选未创建">
          {message(release.error)}
        </InlineNotice>
      ) : null}
      <section className="live-request-panel">
        <div>
          <span>克隆到新草稿房间</span>
          <strong>
            {plan.clonedFromPlanCode
              ? `来自 ${plan.clonedFromPlanCode}`
              : "复制业务输入，重新编译"}
          </strong>
          <small>不会复制旧房间的现场、授权、执行、发布或交付状态。</small>
        </div>
        <button
          type="button"
          className="wb-button wb-button-secondary"
          onClick={() => setCloneOpen((open) => !open)}
        >
          <Copy size={15} aria-hidden="true" />
          克隆
        </button>
      </section>
      {cloneOpen ? (
        <section className="live-request-panel">
          <div className="live-clone-fields">
            <label className="wb-field">
              <span>新直播间 ID</span>
              <input
                className="wb-input"
                value={cloneRoomId}
                onChange={(event) => setCloneRoomId(event.target.value)}
              />
            </label>
            <label className="wb-field">
              <span>新直播间标题</span>
              <input
                className="wb-input"
                value={cloneTitle}
                onChange={(event) => setCloneTitle(event.target.value)}
              />
            </label>
          </div>
          <button
            type="button"
            className="wb-button wb-button-primary"
            disabled={
              clone.isPending || !cloneRoomId.trim() || !cloneTitle.trim()
            }
            onClick={() => clone.mutate()}
          >
            <Copy size={15} aria-hidden="true" />
            创建新计划
          </button>
        </section>
      ) : null}
      {clone.error ? (
        <InlineNotice tone="danger" title="克隆计划未创建">
          {message(clone.error)}
        </InlineNotice>
      ) : null}
      <section className="live-request-panel">
        <div>
          <span>人工确认后的 Worker 请求</span>
          <strong>
            {plan.executionStatus === "requested"
              ? "已提交，等待麦兔 Worker 回读"
              : "尚未请求"}
          </strong>
          <small>
            {typeof plan.executionEvidence.message === "string"
              ? plan.executionEvidence.message
              : "仅在指定空白、未开播草稿中执行。"}
          </small>
        </div>
        {plan.executionStatus === "not_requested" ? (
          <div className="live-request-action">
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              我已确认该目标是指定的空白未开播草稿
            </label>
            <button
              type="button"
              className="wb-button wb-button-primary"
              disabled={
                !confirmed || request.isPending || plan.status !== "ready"
              }
              onClick={() => request.mutate()}
            >
              <Send size={15} aria-hidden="true" />
              请求写入草稿
            </button>
          </div>
        ) : null}
      </section>
      {request.error ? (
        <InlineNotice tone="danger" title="草稿请求未提交">
          {message(request.error)}
        </InlineNotice>
      ) : null}
    </div>
  );
}

export function LiveRoomPlannerPage({
  search = window.location.search,
}: {
  search?: string;
}) {
  const queryClient = useQueryClient();
  const handoffQuery = new URLSearchParams(search);
  const requestedPlanCode = handoffQuery.get("run") ?? "";
  const referenceTemplateCode =
    handoffQuery.get("reference_template_code")?.trim() ?? "";
  const referenceTemplateRevision = Number(
    handoffQuery.get("reference_template_revision_number"),
  );
  const referenceTemplateFingerprint =
    handoffQuery.get("reference_template_projection_fingerprint")?.trim() ?? "";
  const hasReferenceTemplateHandoff = Boolean(
    referenceTemplateCode ||
    referenceTemplateFingerprint ||
    handoffQuery.has("reference_template_revision_number"),
  );
  const referenceTemplateHandoff =
    referenceTemplateCode &&
    Number.isInteger(referenceTemplateRevision) &&
    referenceTemplateRevision > 0 &&
    referenceTemplateFingerprint.length === 64
      ? {
          templateCode: referenceTemplateCode,
          revision: referenceTemplateRevision,
          fingerprint: referenceTemplateFingerprint,
        }
      : undefined;
  const [selectedPlan, setSelectedPlan] = useState(requestedPlanCode);
  const [projectCode, setProjectCode] = useState("");
  const [roomId, setRoomId] = useState("");
  const [title, setTitle] = useState("");
  const [assetCodes, setAssetCodes] = useState<string[]>([]);
  const [requiredLooseAssetCodes, setRequiredLooseAssetCodes] = useState<
    string[]
  >([]);
  const [groupCodes, setGroupCodes] = useState<string[]>([]);
  const [materialPackCodes, setMaterialPackCodes] = useState<string[]>([]);
  const [assetGapCodes, setAssetGapCodes] = useState<string[]>([]);
  const [assetGapWaivers, setAssetGapWaivers] = useState<
    Record<string, string>
  >({});
  const [materialRoleOverrides, setMaterialRoleOverrides] = useState<
    Record<string, string>
  >({});
  const [materialRoleModes, setMaterialRoleModes] = useState<
    Record<string, "inherit" | "append" | "replace">
  >({});
  const [roomConstraintOverrides, setRoomConstraintOverrides] = useState<
    Record<string, RoomConstraintOverride>
  >({});
  const projects = useQuery({
    queryKey: ["content-projects"],
    queryFn: contentProjectsApi.list,
  });
  const selectedProject = useQuery({
    queryKey: ["content-project", projectCode],
    queryFn: () => contentProjectsApi.get(projectCode),
    enabled: Boolean(projectCode),
  });
  const assets = useQuery({
    queryKey: ["assets", "library"],
    queryFn: assetLibraryApi.listAssets,
  });
  const groups = useQuery({
    queryKey: ["assets", "groups"],
    queryFn: assetLibraryApi.listGroups,
  });
  const materialPacks = useQuery({
    queryKey: ["assets", "packs"],
    queryFn: assetLibraryApi.listPacks,
  });
  const materialPackResolution = useQuery({
    queryKey: [
      "assets",
      "pack-resolution",
      materialPackCodes,
      materialRoleModes,
    ],
    queryFn: () =>
      assetLibraryApi.resolvePacks(materialPackCodes, materialRoleModes),
    enabled: materialPackCodes.length > 0,
  });
  const assetGaps = useQuery({
    queryKey: ["assets", "gaps"],
    queryFn: assetLibraryApi.listGaps,
  });
  const plans = useQuery({
    queryKey: ["functional-live-room-plans"],
    queryFn: functionalLiveRoomsApi.list,
  });
  const usableProjects = useMemo(() => projects.data ?? [], [projects.data]);
  const selectedTemplates = useMemo(
    () => inheritedTemplates(selectedProject.data),
    [selectedProject.data],
  );
  const primaryTemplate = useMemo(
    () =>
      selectedTemplates.find(
        (template) => template.selectionRole === "primary",
      ),
    [selectedTemplates],
  );
  const secondaryTemplates = useMemo(
    () =>
      selectedTemplates.filter(
        (template) => template.selectionRole === "secondary",
      ),
    [selectedTemplates],
  );
  const referenceTemplateMatched =
    !hasReferenceTemplateHandoff ||
    Boolean(
      referenceTemplateHandoff &&
      selectedTemplates.some(
        (template) =>
          template.templateCode === referenceTemplateHandoff.templateCode &&
          template.revision === referenceTemplateHandoff.revision,
      ),
    );
  const roleCandidates = useMemo(() => {
    const selectedCodes = new Set(assetCodes);
    (groups.data ?? [])
      .filter((group) => groupCodes.includes(group.groupCode))
      .forEach((group) =>
        group.assetCodes.forEach((code) => selectedCodes.add(code)),
      );
    (materialPackResolution.data?.resolvedAssetCodes ?? []).forEach((code) =>
      selectedCodes.add(code),
    );
    const byRole: Record<
      string,
      Array<{ assetCode: string; title: string }>
    > = {};
    (assets.data ?? [])
      .filter((asset) => selectedCodes.has(asset.assetCode))
      .forEach((asset) =>
        asset.materialRoles.forEach((role) => {
          (byRole[role] ??= []).push({
            assetCode: asset.assetCode,
            title: asset.title,
          });
        }),
      );
    return Object.entries(byRole).sort(([left], [right]) =>
      left.localeCompare(right),
    );
  }, [
    assetCodes,
    assets.data,
    groupCodes,
    groups.data,
    materialPackResolution.data,
  ]);
  const selectedOverrideAssets = useMemo(() => {
    const selectedCodes = new Set(assetCodes);
    (groups.data ?? [])
      .filter((group) => groupCodes.includes(group.groupCode))
      .forEach((group) =>
        group.assetCodes.forEach((code) => selectedCodes.add(code)),
      );
    (materialPackResolution.data?.resolvedAssetCodes ?? []).forEach((code) =>
      selectedCodes.add(code),
    );
    return (assets.data ?? []).filter((asset) =>
      selectedCodes.has(asset.assetCode),
    );
  }, [
    assetCodes,
    assets.data,
    groupCodes,
    groups.data,
    materialPackResolution.data,
  ]);
  const activeGaps = useMemo(
    () =>
      (assetGaps.data ?? []).filter((gap) =>
        ["open", "candidate_found"].includes(gap.status),
      ),
    [assetGaps.data],
  );
  useEffect(() => {
    setMaterialRoleOverrides((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([role, assetCode]) =>
          roleCandidates.some(
            ([candidateRole, candidates]) =>
              candidateRole === role &&
              candidates.some((candidate) => candidate.assetCode === assetCode),
          ),
        ),
      ),
    );
  }, [roleCandidates]);
  useEffect(() => {
    setRequiredLooseAssetCodes((current) =>
      current.filter((assetCode) => assetCodes.includes(assetCode)),
    );
  }, [assetCodes]);
  useEffect(() => {
    setRoomConstraintOverrides((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([assetCode]) =>
          selectedOverrideAssets.some((asset) => asset.assetCode === assetCode),
        ),
      ),
    );
  }, [selectedOverrideAssets]);
  useEffect(() => {
    if (!projectCode && usableProjects[0])
      setProjectCode(usableProjects[0].projectCode);
  }, [projectCode, usableProjects]);
  useEffect(() => {
    if (requestedPlanCode) setSelectedPlan(requestedPlanCode);
  }, [requestedPlanCode]);
  const activePlanCode = plans.data?.some(
    (item) => item.planCode === selectedPlan,
  )
    ? selectedPlan
    : (plans.data?.[0]?.planCode ?? "");
  useEffect(() => {
    if (selectedPlan !== activePlanCode) setSelectedPlan(activePlanCode);
  }, [activePlanCode, selectedPlan]);
  const detail = useQuery({
    queryKey: ["functional-live-room-plan", activePlanCode],
    queryFn: () => functionalLiveRoomsApi.get(activePlanCode),
    enabled: Boolean(activePlanCode),
  });
  const hasIncompleteRoomOverride = Object.values(roomConstraintOverrides).some(
    (override) => !override.reason.trim(),
  );
  const create = useMutation({
    mutationFn: () =>
      functionalLiveRoomsApi.create({
        project_code: projectCode,
        target_live_room_id: roomId,
        expected_title: title,
        primary_template_code: primaryTemplate?.templateCode,
        secondary_template_codes: secondaryTemplates.map(
          (template) => template.templateCode,
        ),
        asset_codes: assetCodes,
        required_loose_asset_codes: requiredLooseAssetCodes.filter(
          (assetCode) => assetCodes.includes(assetCode),
        ),
        group_codes: groupCodes,
        material_pack_codes: materialPackCodes,
        asset_gap_codes: assetGapCodes,
        asset_gap_waivers: Object.fromEntries(
          Object.entries(assetGapWaivers).filter(
            ([gapCode, reason]) =>
              assetGapCodes.includes(gapCode) && reason.trim(),
          ),
        ),
        material_role_overrides: materialRoleOverrides,
        material_role_modes: materialRoleModes,
        room_constraint_overrides: roomConstraintOverrides,
      }),
    onSuccess: (plan) => {
      setSelectedPlan(plan.planCode);
      void queryClient.invalidateQueries({
        queryKey: ["functional-live-room-plans"],
      });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (
      !hasIncompleteRoomOverride &&
      referenceTemplateMatched &&
      projectCode &&
      roomId.trim() &&
      title.trim() &&
      (assetCodes.length || groupCodes.length || materialPackCodes.length)
    )
      create.mutate();
  };
  const publishedMaterialPacks = (materialPacks.data ?? []).filter(
    (pack) =>
      pack.publishedRevisionNumber !== undefined ||
      pack.revisionStatus === "published",
  );
  const totalMaterialPacks = publishedMaterialPacks.filter(
    (pack) => pack.packKind === "total",
  );
  const classificationMaterialPacks = publishedMaterialPacks.filter(
    (pack) => pack.packKind === "classification",
  );
  const materialPackRoles = [
    ...new Set(
      (materialPackResolution.data?.entryRequirements ?? []).flatMap(
        (requirement) =>
          requirement.materialRole ? [requirement.materialRole] : [],
      ),
    ),
  ].sort();
  const materialPackConflicts = materialPackResolution.data?.conflicts ?? [];
  const loading =
    projects.isLoading ||
    selectedProject.isLoading ||
    assets.isLoading ||
    groups.isLoading ||
    materialPacks.isLoading ||
    assetGaps.isLoading ||
    plans.isLoading;
  const problem =
    projects.error ??
    selectedProject.error ??
    assets.error ??
    groups.error ??
    materialPacks.error ??
    assetGaps.error ??
    plans.error;
  return (
    <div className="live-room-layout">
      <aside className="wb-section live-plan-rail">
        <SectionHeader kicker="LIVE ROOM PLANS" title="直播间配置" />
        <form className="live-plan-form" onSubmit={submit}>
          <label className="wb-field">
            <span>内容项目</span>
            <select
              className="wb-input"
              value={projectCode}
              onChange={(event) => setProjectCode(event.target.value)}
            >
              <option value="">选择已创建内容项目</option>
              {usableProjects.map((project) => (
                <option key={project.projectCode} value={project.projectCode}>
                  {project.title} · {project.projectCode}
                </option>
              ))}
            </select>
          </label>
          <div className="live-template-selection">
            <span>继承内容模板</span>
            {selectedProject.isLoading ? (
              <small>正在读取固定模板修订</small>
            ) : selectedTemplates.length ? (
              selectedTemplates.map((template) => (
                <article key={template.templateCode}>
                  <div>
                    <strong>
                      {template.selectionRole === "primary"
                        ? "主参考模板"
                        : "次要参考模板"}
                    </strong>
                    <code>
                      {template.templateCode} · r{template.revision}
                    </code>
                  </div>
                  <small>
                    {template.acceptedModules.length
                      ? `采用模块：${template.acceptedModules.join(" / ")}`
                      : "未采用额外模块"}
                  </small>
                </article>
              ))
            ) : (
              <small>当前内容项目未选择内容策略模板</small>
            )}
            <small>
              模板只能在内容项目中修改；直播间计划会固定继承当前修订。
            </small>
          </div>
          {hasReferenceTemplateHandoff ? (
            referenceTemplateHandoff ? (
              <InlineNotice
                tone={referenceTemplateMatched ? "info" : "danger"}
                title="固定参考模板交接"
              >
                {referenceTemplateMatched
                  ? `当前内容项目已固定 ${referenceTemplateHandoff.templateCode} · r${referenceTemplateHandoff.revision}；参考投影只参与内容策略，不会写入可执行布局。`
                  : `当前内容项目未固定 ${referenceTemplateHandoff.templateCode} · r${referenceTemplateHandoff.revision}；请先在内容项目中选择该发布模板。`}
              </InlineNotice>
            ) : (
              <InlineNotice tone="danger" title="固定参考模板交接无效">
                模板编码、修订号或投影指纹不完整，不能生成直播间计划。
              </InlineNotice>
            )
          ) : null}
          <label className="wb-field">
            <span>直播间 ID</span>
            <input
              className="wb-input"
              value={roomId}
              onChange={(event) => setRoomId(event.target.value)}
              required
            />
          </label>
          <label className="wb-field">
            <span>直播间标题</span>
            <input
              className="wb-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
            />
          </label>
          <div className="live-selection">
            <span>总体素材包</span>
            {totalMaterialPacks.length ? (
              totalMaterialPacks.map((pack) => (
                <label key={pack.packCode}>
                  <input
                    type="checkbox"
                    checked={materialPackCodes.includes(pack.packCode)}
                    onChange={() =>
                      setMaterialPackCodes((current) =>
                        toggle(current, pack.packCode),
                      )
                    }
                  />
                  <span>
                    <strong>{pack.title}</strong>
                    <small>
                      已发布 r
                      {pack.publishedRevisionNumber ?? pack.revisionNumber} ·{" "}
                      {pack.resolvedAssetCodes.length} 项
                    </small>
                  </span>
                </label>
              ))
            ) : (
              <small>没有可选的已发布总体包</small>
            )}
          </div>
          <div className="live-selection">
            <span>分类素材包</span>
            {classificationMaterialPacks.length ? (
              classificationMaterialPacks.map((pack) => (
                <label key={pack.packCode}>
                  <input
                    type="checkbox"
                    checked={materialPackCodes.includes(pack.packCode)}
                    onChange={() =>
                      setMaterialPackCodes((current) =>
                        toggle(current, pack.packCode),
                      )
                    }
                  />
                  <span>
                    <strong>{pack.title}</strong>
                    <small>
                      {pack.role} · 已发布 r
                      {pack.publishedRevisionNumber ?? pack.revisionNumber} ·{" "}
                      {pack.resolvedAssetCodes.length} 项
                    </small>
                  </span>
                </label>
              ))
            ) : (
              <small>没有可选的已发布分类包</small>
            )}
          </div>
          {materialPackRoles.length ? (
            <div className="live-selection live-role-selection">
              <span>角色域合并方式</span>
              {materialPackRoles.map((role) => (
                <div key={role}>
                  <strong>{role}</strong>
                  <div
                    className="wb-tabs"
                    role="group"
                    aria-label={`${role} 素材包合并方式`}
                  >
                    {(["inherit", "append", "replace"] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        className={
                          (materialRoleModes[role] ?? "append") === mode
                            ? "active"
                            : undefined
                        }
                        onClick={() =>
                          setMaterialRoleModes((current) => ({
                            ...current,
                            [role]: mode,
                          }))
                        }
                      >
                        {mode === "inherit"
                          ? "沿用"
                          : mode === "append"
                            ? "追加"
                            : "替换"}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
          {materialPackResolution.isFetching ? (
            <small>正在解析素材包规则...</small>
          ) : null}
          {materialPackResolution.data && !materialPackConflicts.length ? (
            <div className="live-selection">
              <span>素材包解析快照</span>
              <small>
                {materialPackResolution.data.resolvedAssetCodes.length} 项白名单
                · {materialPackResolution.data.entryRequirements.length}{" "}
                条使用规则 ·{" "}
                {materialPackResolution.data.fingerprintSha256.slice(0, 12)}
              </small>
            </div>
          ) : null}
          {materialPackConflicts.length ? (
            <InlineNotice tone="danger" title="素材包规则冲突">
              {materialPackConflicts
                .map(
                  (conflict) =>
                    `${conflict.code}${conflict.remediation ? `：${conflict.remediation}` : ""}`,
                )
                .join("；")}
            </InlineNotice>
          ) : null}
          {materialPackResolution.error ? (
            <InlineNotice tone="danger" title="素材包无法解析">
              {message(materialPackResolution.error)}
            </InlineNotice>
          ) : null}
          <div className="live-selection">
            <span>零散素材</span>
            {assets.data?.map((asset) => (
              <label key={asset.assetCode}>
                <input
                  type="checkbox"
                  checked={assetCodes.includes(asset.assetCode)}
                  onChange={() =>
                    setAssetCodes((current) => toggle(current, asset.assetCode))
                  }
                />
                <span>
                  <strong>{asset.title}</strong>
                  <small>
                    {asset.materialRoles.join(" / ") || "未分类"} ·{" "}
                    {asset.executionCapability}
                  </small>
                </span>
              </label>
            ))}
          </div>
          <RequiredLooseAssetFields
            assets={assets.data ?? []}
            selectedAssetCodes={assetCodes}
            requiredAssetCodes={requiredLooseAssetCodes}
            onChange={setRequiredLooseAssetCodes}
          />
          <div className="live-selection">
            <span>素材分组</span>
            {groups.data?.map((group) => (
              <label key={group.groupCode}>
                <input
                  type="checkbox"
                  checked={groupCodes.includes(group.groupCode)}
                  onChange={() =>
                    setGroupCodes((current) => toggle(current, group.groupCode))
                  }
                />
                <span>
                  <strong>{group.title}</strong>
                  <small>
                    {group.assetCount} 项 · {group.groupCode}
                  </small>
                </span>
              </label>
            ))}
          </div>
          <div className="live-selection">
            <span>关联素材缺口</span>
            {activeGaps.length ? (
              activeGaps.map((gap) => (
                <label key={gap.gapCode}>
                  <input
                    type="checkbox"
                    checked={assetGapCodes.includes(gap.gapCode)}
                    onChange={() =>
                      setAssetGapCodes((current) =>
                        toggle(current, gap.gapCode),
                      )
                    }
                  />
                  <span>
                    <strong>{gap.title}</strong>
                    <small>
                      {gap.gapCode} · {gap.role} · {gap.severity} · {gap.status}
                    </small>
                  </span>
                </label>
              ))
            ) : (
              <small>没有待处理缺口</small>
            )}
          </div>
          <BranchGapWaiverFields
            gaps={activeGaps}
            selectedGapCodes={assetGapCodes}
            waivers={assetGapWaivers}
            onChange={setAssetGapWaivers}
          />
          <RoomConstraintOverrideEditor
            assets={selectedOverrideAssets}
            overrides={roomConstraintOverrides}
            onChange={setRoomConstraintOverrides}
          />
          {roleCandidates.length ? (
            <div className="live-selection live-role-selection">
              <span>角色选材</span>
              {roleCandidates.map(([role, candidates]) => (
                <label key={role}>
                  <span>
                    <strong>{role}</strong>
                    <small>
                      {materialRoleOverrides[role]
                        ? `固定 ${materialRoleOverrides[role]}`
                        : "自动选择"}
                    </small>
                  </span>
                  <select
                    className="wb-input"
                    value={materialRoleOverrides[role] ?? ""}
                    onChange={(event) =>
                      setMaterialRoleOverrides((current) => {
                        const next = { ...current };
                        if (event.target.value) next[role] = event.target.value;
                        else delete next[role];
                        return next;
                      })
                    }
                  >
                    <option value="">自动选择</option>
                    {candidates.map((candidate) => (
                      <option
                        key={candidate.assetCode}
                        value={candidate.assetCode}
                      >
                        {candidate.title} · {candidate.assetCode}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          ) : null}
          {create.error ? (
            <InlineNotice tone="danger" title="无法生成 BuildPlan">
              {message(create.error)}
            </InlineNotice>
          ) : null}
          <button
            className="wb-button wb-button-primary"
            disabled={
              create.isPending ||
              selectedProject.isLoading ||
              hasIncompleteRoomOverride ||
              !referenceTemplateMatched ||
              materialPackResolution.isFetching ||
              materialPackConflicts.length > 0 ||
              !projectCode ||
              !roomId.trim() ||
              !title.trim() ||
              (!assetCodes.length &&
                !groupCodes.length &&
                !materialPackCodes.length)
            }
          >
            <WandSparkles size={15} aria-hidden="true" />
            生成场景与 BuildPlan
          </button>
        </form>
        <div className="live-plan-list">
          {plans.data?.map((plan) => (
            <button
              key={plan.planCode}
              type="button"
              className={
                plan.planCode === activePlanCode ? "active" : undefined
              }
              onClick={() => setSelectedPlan(plan.planCode)}
            >
              <span>
                <strong>{plan.expectedTitle}</strong>
                <code>{plan.planCode}</code>
                <small>{plan.targetLiveRoomId}</small>
              </span>
              <StatusBadge
                label={label(plan.status)}
                tone={tone(plan.status)}
              />
            </button>
          ))}
        </div>
      </aside>
      <main className="live-room-main">
        {loading ? (
          <LoadingBlock label="正在读取直播间配置数据" />
        ) : problem ? (
          <InlineNotice tone="danger" title="直播间工作台无法加载">
            {message(problem)}
          </InlineNotice>
        ) : detail.data ? (
          <PlanDetail plan={detail.data} />
        ) : (
          <EmptyBlock
            icon={plans.data?.length ? CircleAlert : MonitorUp}
            title={
              plans.data?.length ? "选择一个直播间计划" : "创建第一个直播间计划"
            }
            detail="先完成内容项目和素材选择，系统会生成场景蓝图与草稿操作序列。"
          />
        )}
      </main>
    </div>
  );
}

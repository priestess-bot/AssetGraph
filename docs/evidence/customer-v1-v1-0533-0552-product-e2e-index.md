# 41172 产品端到端证据索引

证据等级：`product_e2e`

最终通过目录：`docs/evidence/live-room-41172-product-e2e-2026-07-31T14-48-54-818Z`

## 产品流程

- 输入和六份素材选择：`01-input-and-material-selection.png`、`material-report.json`
- 三场景画布：`02-generated-three-scene-canvas.png`、`canvas-outline.json`
- 房间权威回读：`04-room-inspection-readback.png`
- 删除范围与确认：`05-delete-confirmation-all-scenes.png`、`06-ready-to-replace-test-draft.png`、`runtime-reset-plan.json`
- 真实队列阶段：`execution-01-preparing_materials.png` 到 `execution-06-succeeded.png`
- BuildPlan：`build-plan-from-ui-response.json`、`final-plan.json`
- Job 事件与 checkpoint：`final-execution.json`
- 麦兔最终回读：`final-maitu-readback.json`、`final-validation.json`
- 工作台刷新回读：`08-console-after-refresh.png`、`console-refresh-verification.json`
- 页面操作和请求来源摘要：`run-report.json`。完整原始网络转录仅保留在验收机，不进入版本库。
- 测试和体验：`test-gates.json`、`experience-baseline.json`

## 验收结论

- Console 页面触发全部 9 个 mutation；自动化没有直接调用生成或执行 mutation API。
- 41172 标题精确为 `asser测试`，现场为 working/offline，清空前展示并确认两个场景。
- 常驻 worker 自动领取 `MT-WB-EXEC-20260731-000015`，执行 41 个 operation，0 placeholder、0 failure、0 人工介入。
- 最终恰好 3 个场景，分别有 4、6、5 个视觉图层和 1 段话术；层号从 1 连续递增，来源、几何和话术均匹配。
- 视频不在最高层；背景置底、数字人在商品内容之上、品牌标题置顶。
- `go_live=false`、`ready_for_go_live=false`、`non_releasable=true`，本次没有排播、授权或正式开播。

此前 `V1-0107`、`V1-0108`、`V1-0502`、`V1-0503`、`V1-0506` 的直接适配器验证继续保持 `adapter_validation`，不升级为产品端到端证据。

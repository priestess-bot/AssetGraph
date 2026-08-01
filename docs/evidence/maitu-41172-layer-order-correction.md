# 麦兔 41172 图层顺序修正证据

日期：2026-07-31

## 问题与根因

旧测试房重建流程把参考场景 `390069` 的完整视觉快照当作目标真值。参考场景自身将全屏产品视频放在 `z=9`，所以流程虽然通过“与参考一致”验收，却把视频稳定复制到了最顶层并遮挡数字人和装饰。

历史文件 `maitu-41172-zhangyu-pro-rebuild-result.json` 保存的是本次修正前的执行结果，只可用于说明旧问题，不能作为修正后的层序证据。

## 系统修正

- 素材约束中的硬置底、硬置顶分别编译为不可穿越的底部层级带和顶部层级带。
- `above_role / below_role` 与层级带共同编译为从低到高的有向图；硬冲突或环直接阻断。
- 成功结果稳定压缩为唯一连续的 `1..N`，并写入约束证据。
- Blueprint 使用 `z_order`，脚本布局和 Browser-use 使用 `z_index`；两个执行契约现在同步采用同一最终顺序。
- 测试房复制只继承参考素材身份和几何，层序来自计划；验收比较计划层序，不再比较参考层序。

## 素材限制样例

- 背景 `AG-IMG-20260729-000002`：硬置底。
- 产品视频 `AG-VID-20260729-000016`：必须位于背景上方，并优先位于数字人和前景装饰下方。
- 标题 `AG-IMG-20260729-000007`：硬置顶。

这些规则已写为素材约束 Profile 修订；标准选材和 BuildPlan 链会读取并编译该修订。41172 的受控测试重建计划显式采用同一层序。

## 真实房间回读

房间 `41172` 的三个场景为 `437569 / 451296 / 451297`。每场包含 9 个视觉图层和 1 段话术，实际从底到顶均为：

1. 背景-3
2. 品酒大师 PRO 全屏产品视频
3. 张裕定制数字人
4. 底图
5. gif-01
6. png
7. icon
8. logo
9. 张裕百年标题

每场 `layer_n` 与 `style_front.zIndex` 完全一致并连续为 `1..9`。视频不再位于顶层，标题位于最顶层，背景位于最底层。

权威结构化回读：`docs/evidence/maitu-41172-zhangyu-pro-final-readback.json`。

页面截图：

- `docs/evidence/screenshots/maitu-41172-zhangyu-pro-layer-fixed.png`
- `docs/evidence/screenshots/maitu-41172-zhangyu-pro-layer-fixed-scene-02.png`
- `docs/evidence/screenshots/maitu-41172-zhangyu-pro-layer-fixed-scene-03.png`

## 验证结果

- 后端全量：`782 passed, 138 skipped`。
- Browser-use 全量：`413 passed`。
- 前端全量：`90 passed`；TypeScript 与生产构建通过。
- Ruff 定向检查和 `git diff --check` 通过。
- 三份素材约束 Profile 均从真实本地 API 回读；素材页只读验收未创建新修订。

## 开播状态与预览边界

回读为 `status=0`、`live_session_id=null`、`latest_live_time=null`、`environment=working`，且执行断言 `go_live_clicked=false`。本次没有点击正式开播。

麦兔网页右侧脚本三角按钮仅播放单段 TTS，不驱动画布、数字人或视频；旁边方形图标是增加 0.5 秒停顿，不是停止键。完整动态画面需要麦兔桌面客户端 2.4.0 及以上逐场点击“实时预览”，当前没有一次连续预览全部三个场景的非开播入口。

# 麦兔 41172 张裕品酒大师 PRO 重建记录

日期：2026-07-31
目标直播间：`41172`
主题：介绍张裕品酒大师 PRO
最终结果：真实测试草稿已清空并重建，独立刷新回读通过，未排播、未授权、未开播。

## 内容与计划

- ContentProject：`CONTENT-20260731-000001`
- DesignBrief：`DBR-6902155CFBDF`，已确认
- StoryBrief：`STORY-20260731-000001` r1
- Script：`SCRIPT-20260731-000002` r2
- Program：`PROGRAM-20260731-000002` r2
- ShotList：`SHOTLIST-20260731-000002` r2
- 三段时长：45 秒 / 90 秒 / 45 秒，合计 180 秒
- 参考蓝图：`MT-BP-20260709-38336-TEMPLATE`
- 只读参考：直播间 `38336` / clip `390069`，共 9 个视觉图层，不含选购的旧促销贴片
- BuildPlan：`MT-BUILD-20260731-000006`、`MT-BUILD-20260731-000007`、`MT-BUILD-20260731-000005`
- 执行输入：`docs/evidence/maitu-41172-zhangyu-pro-rebuild-spec.json`

## 执行边界

- 只修改直播间 `41172`；参考直播间 `38336` 始终只读。
- 每次写入前都重新核对 ID、精确标题 `asser测试`、`working` 环境、明确未开播且无开播痕迹。
- 清空后回读确认 `1 clip / 0 materials`，再写入新场景。
- 首次错误立即停止，不盲目重试；必须先用权威回读对齐现状。
- 流程不包含创建直播间、商品/互动配置、排播、授权或开播操作。

## 执行过程

1. 变更前只读回读：房间 `41172`，标题 `asser测试`，`status=0`，`live_session_id=null`，`latest_live_time=null`，3 个旧场景。
2. 第一次预检发现麦兔的顶层画布坐标和 `style_front` 缩放坐标是两套正常坐标系；流程在任何修改前停止。修复后对两套坐标分别冻结和校验。
3. 第二次已删除两个非保留旧场景，随后 Browser-use 命名会话脱离指定 CDP，流程在清空保留场景前停止。权威回读确认剩余场景 `437569` 及其 5 个旧图层仍完整。
4. 关闭错误会话，新会话连续 5 次读取相同权威状态后，从已对齐的单场景状态继续。
5. 清空场景 `437569` 的 5 个旧图层，回读确认为空。
6. 复用 `437569` 并新建 `451221`、`451222`，写入三个场景、每场 9 个视觉图层和唯一话术。
7. 执行器最终回读与独立新会话刷新回读均通过。

## 最终状态

| 顺序 | 场景 ID | 场景名 | 视觉图层 | 话术 |
| --- | --- | --- | --- | --- |
| 1 | `437569` | 开场引入 | 9 | 1 段，完整匹配 |
| 2 | `451221` | 产品画面与选择 | 9 | 1 段，完整匹配 |
| 3 | `451222` | 场景建议与互动 | 9 | 1 段，完整匹配 |

独立回读同时确认：房间 ID/标题匹配、`status=0`、无开播会话/时间、三场景顺序和名称匹配、图层数匹配、三段话术逐字匹配，`go_live_clicked=false`。

## 证据

- 变更前截图：`docs/evidence/screenshots/maitu-41172-zhangyu-pro-before.png`
- 刷新后截图：`docs/evidence/screenshots/maitu-41172-zhangyu-pro-after.png`
- 最终执行结果：`docs/evidence/maitu-41172-zhangyu-pro-rebuild-result.json`
- 独立刷新回读：`docs/evidence/maitu-41172-zhangyu-pro-final-readback.json`
- 两次可追溯的中止记录：`maitu-41172-zhangyu-pro-rebuild-attempt-1-preflight-failed.json`、`maitu-41172-zhangyu-pro-rebuild-attempt-2-partial.json`
- 适配器契约：`maitu-web-working-room.internal.v1`
- 验收时契约指纹：`c19b5ca196033d248df2419d9dec56348a67100ea2c9a30abccfb69c4a4c1213`
- Browser-use worker 全量测试：`410 passed`；Ruff 与 `git diff --check` 通过。

## 校验和

- 变更前截图：`82fea9389f3967fac01cbb2dc187ebbc207c54299c6fd4b748078e7d982850a9`
- 刷新后截图：`03eb8d6730d32a86910270b32dd27562f9d64c15ec003d71b3b1cdde0333c93b`
- 最终执行结果：`020c86ee5843b286ba6284079b15b7f4687768ccf10f57852e2625fb2a6254b3`
- 独立刷新回读：`369ab244c0a7a797fc7e04e5d7585a045f076dd915d30e54c09bc3abc0dc115f`
- 执行输入：`8b0794e995b9012cf46b2541034e0bc7afadf7e4f01fce629af82c1adcce59b4`

## 保留限制

- 本次验证了已有图片/视频、数字人和音色的复用；普通图片/视频自动上传未验证，能力矩阵仍为 `manual_only`。
- 本次通过专用的受控测试房重建执行器完成；前端“写入麦兔草稿”生产队列还没有用同一真实任务走通，所以产品能力矩阵暂不整体升为 `verified`。

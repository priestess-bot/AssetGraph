# AssetGraph 功能快线 Checklist

> 状态：执行中
> 目标：在不宣称生产化验收完成的前提下，优先交付可由内部运营人员实际操作的 Phase 1-7 功能。
> 权威设计与生产化门禁仍以 `2026-07-22-live-content-production-operations-closed-loop-design.md` 和 `2026-07-23-live-content-production-operations-implementation-checklist.md` 为准。

## 使用规则

- [x] `FT-0001` 每个完成项同时记录 commit、测试命令、截图或可复现演示数据，并关联原 `CHK-*`。
- [x] `FT-0002` 快线完成不勾选原生产化 checklist；原 checklist 的安全、可靠性和签字要求仍保持真实状态。
- [x] `FT-0003` 正式开播在 UI、API、BuildPlan 和 Worker 中持续关闭；快线只允许人工确认后写入指定空白草稿。

## F1 素材与模板

- [x] `FT-1101` 素材三维分类、版本兼容投影和筛选。关联：`CHK-2101`-`CHK-2109`。
- [x] `FT-1102` 素材分组，多对多成员和批量替换。关联：`CHK-2180`、`CHK-2181`。
- [x] `FT-1103` 表单化约束 profile：区域、缩放、图层关系和桌面摆放。关联：`CHK-2140`-`CHK-2149`。
- [x] `FT-1104` 素材包、直接/分组条目和解析预览。关联：`CHK-2182`-`CHK-2189`。
- [x] `FT-1105` 素材缺口创建、列表与处理状态。关联：`CHK-2206`-`CHK-2209`。
- [x] `FT-1106` `/assets/library` 完整工作区与 API 交互。关联：`CHK-2108`、`CHK-2190`、`CHK-7240`。
- [ ] `FT-1110` 单来源录屏内容模板、主次模板选择与生产交接。关联：`CHK-2260`-`CHK-2293`。

## F2 内容与草稿

- [x] `FT-2101` ContentProject、DesignBrief、事实、剧本、节目段和 Shot 的连续编辑。关联：`CHK-1101`-`CHK-1149`。
- [x] `FT-2102` 直播间配置、素材选择、约束覆盖和 BuildPlan 可视化。关联：`CHK-1160`-`CHK-1188`。
- [ ] `FT-2103` 人工确认后写入空白麦兔草稿并展示基本回读。关联：`CHK-1202`-`CHK-1226`。

## F3 成片

- [x] `FT-3101` 从 ContentProject 创建视频分支、时间轴和渲染任务。关联：`CHK-3101`-`CHK-3189`。
- [x] `FT-3102` `/production/videos` 预览、进度、下载与重渲染。关联：`CHK-3200`-`CHK-3249`。

## F4 运营与排播计划

- [x] `FT-4101` 版本化导入/采集实际场次、曝光和基础指标。关联：`CHK-4101`-`CHK-4149`。
- [x] `FT-4102` 运营看板、描述性对比和人工归因下钻。关联：`CHK-4160`-`CHK-4167`。
- [x] `FT-4103` 仅规划型排播日历与冲突提示，无开播动作。关联：`CHK-7140`-`CHK-7144`。

## F5-F6 学习与实验

- [ ] `FT-5101` DecisionLog、表现卡片和效果驱动再生产建议。关联：`CHK-5120`-`CHK-5188`。
- [ ] `FT-6101` 内容/策略 A/B 定义、稳定分配、曝光回填和对比报告。关联：`CHK-6101`-`CHK-6145`。

## F7 知识与产品壳

- [ ] `FT-7101` 知识事实、来源、搜索和关系下钻。关联：`CHK-7101`-`CHK-7105`。
- [ ] `FT-7102` 关系查询/向量检索投影与影响分析，不引入 Neo4j。关联：`CHK-7120`-`CHK-7128`。
- [ ] `FT-7103` 稳定路由、全局搜索、任务深链与旧入口渐进迁移。关联：`CHK-7240`-`CHK-7248`。

## 执行日志

| check_id | status | commit | test/evidence | original checklist mapping |
| --- | --- | --- | --- | --- |
| `FT-0001`-`FT-0003` | done | pending implementation batch | 本文件 | 快线执行规则 |
| `FT-1101`-`FT-1106` | done | pending implementation batch | migration `045_functional_fast_track_assets.sql`; `backend/tests/test_material_library_postgres.py` (`2 passed`); Console API schema smoke; `npm run build:console`; focused Ruff | `CHK-2101`-`CHK-2109`、`CHK-2140`-`CHK-2149`、`CHK-2180`-`CHK-2209`、`CHK-7240`；生产化退出门禁仍未勾选 |
| `FT-2101` | done | pending implementation batch | `backend/tests/test_functional_content_postgres.py` plus `test_content_core_postgres.py` (`3 passed`); ContentProject OpenAPI smoke; `npm run build:console`; focused Ruff | `CHK-1101`-`CHK-1149`；当前生成策略明确为 `deterministic_demo`，不替代后续 provider 生产策略 |
| `FT-2102` | done | pending implementation batch | migration `046_functional_live_room_plans.sql`; `test_material_library_postgres.py`、`test_content_core_postgres.py`、`test_functional_content_postgres.py`、`test_functional_live_rooms_postgres.py` (`7 passed`); migration/closed-loop parsing (`24 passed`); Functional API OpenAPI smoke; `npm run typecheck`; `npm run build:console`; focused Ruff | `CHK-1160`-`CHK-1188`；BuildPlan 明确 `go_live=false`。确认仅创建 `awaiting_maitu_worker` 请求，未宣称或模拟平台写入。 |
| `FT-3101`-`FT-3102` | done | pending implementation batch | migration `047_functional_video_plans.sql`; `test_functional_videos_postgres.py`; functional suite (`8 passed`); Functional Video OpenAPI smoke; `npm run typecheck`; `npm run build:console`; focused Ruff | `CHK-3101`-`CHK-3249`；内容项目文本会预置为渲染任务的前三阶段输入，Worker 从素材选择继续。视觉源目前明确为已验证的基线素材；实际产物仅在 Worker 成功后显示预览和下载。 |
| `FT-4101`-`FT-4103` | done | pending implementation batch | migration `048_functional_operations.sql`; `test_functional_operations_postgres.py` (`1 passed`); Functional Operations OpenAPI smoke; `npm run typecheck`; `npm run build:console`; focused Ruff | `CHK-4101`-`CHK-4167`、`CHK-7140`-`CHK-7144`；归因固定为 `descriptive`，排播仅保存计划与冲突，不创建开播命令。 |

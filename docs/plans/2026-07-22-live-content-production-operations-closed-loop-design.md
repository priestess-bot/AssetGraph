# AssetGraph 直播内容生产与运营闭环设计

> 状态：生产级目标设计；v1 执行范围由 [ADR-0003](../adr/0003-customer-experience-v1-scope.md) 收敛
> 日期：2026-07-23
> 修订：补齐独立内容聚合根、生产分支、发布与曝光、统一控制面、可信归因、权利治理和非功能目标
> 当前安全边界：允许生成麦兔草稿和竖屏成片；正式开播 capability 关闭，未来只能经独立评审和短期 GoLiveAuthorization 启用
> 适用对象：内部可信运营人员
> 关联目标：[AssetGraph 最终目标](../final-goal.md)
> v1 实施清单：[客户体验优先 v1 落地 Checklist](./2026-07-26-customer-experience-v1-implementation-checklist.md)
> 生产级参考清单：[完整生产与运营闭环 Checklist（归档参考）](./2026-07-23-live-content-production-operations-implementation-checklist.md)

## v1 执行口径（2026-07-26）

本文仍是长期领域模型和生产级能力的权威目标，但不再要求先完成全部
治理、可靠性与企业级条目才向客户交付。v1 面向单个可信内容运营团队，
分两批完成可使用闭环：第一批交付素材、录屏模板、内容生成、麦兔草稿和
本地成片；第二批交付文件导入的运营数据、归因、知识投影和效果驱动复用。

v1 冻结现有鉴权与审计基础，不新增复杂 RBAC、对象 ACL、双人审批或权限
管理界面。事实、素材权利和麦兔目标房间是保留的三类硬门禁。正式排播、
开播授权、点击开播、数字人/音色训练、像素级复刻、因果实验和企业级灾备
不在 v1 范围。本文中相关章节是未来生产化参考，不能计入 v1 未完成分母。

麦兔自动化以能力矩阵为准。客户先在麦兔创建空白未开播草稿并填写 ID 和
标题；未经过真实账号 canary 与刷新回读验证的变更能力只能显示为人工交接，
不能因为适配器代码存在就宣称可自动执行。详细决策见 ADR-0003。

## 1. 目标

把现有分散的素材同步、商品知识、外部直播研究、内容生产、成片渲染、BuildPlan、Browser-use 草稿写入、运营数据和效果学习能力，整理为一个运营人员可以持续使用且能够形成反馈闭环的直播内容生产平台。

三个已有工作台是近期生产入口，不是长期产品边界。长期信息架构允许新增知识库、成片生产、运营场次与归因、效果学习等一级工作区；各工作区共享稳定领域对象、版本、证据和权限边界，而不是把所有功能继续堆入 `/maitu/`。

用户不需要只填主题后一键完成。完整主流程是：

```text
整理麦兔素材与约束
  -> 建立素材分组和素材模板包
  -> 采集外部直播并提炼内容策略模板
  -> 新建 ContentProject
  -> 填写生成目标、事实、主题、故事和通用约束
  -> 确认结构化 DesignBrief
  -> 固化 StoryBrief 修订
  -> 选择主/次内容模板
  -> 生成 Script、ScriptBlock、ProgramSegment 和最小 ShotList
  -> 创建 live_room / rendered_video ProductionVariant
  -> 为分支选择素材并固化输入快照
  -> 生成 BuildPlan 或 ProductionTimeline
  -> 通过分支质量门禁并创建不可变 ReleaseManifest
  -> 写入麦兔草稿或生成竖屏成片
  -> LiveSession 绑定实际 release 并记录 ContentExposureEvent
  -> 回收运营数据，形成分级归因证据和再生产决策
```

第一版不负责创建麦兔直播间。用户必须先在麦兔建立未开播、无业务素材的空白草稿，再把 `liveRoomId` 交给 AssetGraph。

## 2. 已确认的产品决策

1. 前端长期采用一个 AssetGraph Console 和可扩展的一级产品域，不按每个功能拆成独立部署应用。
2. 素材管理、直播模板配置、直播间配置是近期优先交付的三个生产工作区；知识库、成片生产、运营与归因、效果学习作为独立一级工作区逐步接入。
3. 麦兔是媒体文件、数字人、音色和可执行素材身份的主数据源；AssetGraph 保存 `/DATA` 分析副本、语义、约束、分组、素材包和执行证据。
4. 内容模板的第一来源是外部直播录屏，第一版优先接入抖音，后端保留平台适配器边界。
5. 内容模板最重要的产物是话术骨架和整个直播剧本的安排，画面布局只是近似参考。
6. 一个内容模板可以聚合同一来源直播间的多场录屏，表达“模仿某直播间售卖某类商品的内容策略”。
7. 模板保存语义骨架和少量去事实化例句，不保存可直接复制的来源商品事实。
8. 一个直播间最多有一个主内容模板；次要模板不设业务数量上限。
9. 用户不必手动为每个次要模板勾选贡献模块，系统先提出推荐，用户修改是可选的。
10. 素材选择采用硬白名单。生成器不得在未说明的情况下使用白名单外素材。
11. 素材分组只负责集合和批量选择，不承担约束继承。
12. 素材模板包支持总体包和分类包，支持必用、可选和按角色域排他。
13. 素材包编辑阶段跟随最新已发布版本，确认生成时必须固化解析结果和指纹。
14. 直播间内的素材约束覆盖默认只影响当前配置，可显式提升为素材全局约束新版本。
15. 生成目标先解析成结构化 DesignBrief，再由用户确认；原始输入不得作为不受控系统指令直接拼接。
16. ContentProject 必须有生成目标和适用的已批准事实；只有创建 live_room variant 时，直播间标题和目标 `liveRoomId` 才是必填项。
17. 目标时长是大致指导值，不要求秒级精确；偏离约 50% 时产生质量警告。
18. 无硬阻断时默认自动执行只读 preflight 并写入草稿，不再增加人工确认门。
19. 自动写入后的普通房间方案修改通过复制配置并绑定新的空白房间完成；第一版不对普通非空房间做增量重建。客户体验 v1 允许仅对白名单离线测试房执行显式确认、现场指纹绑定的整房清空重建，首期仅为 `41172`，该例外不得扩展到生产房间。
20. 素材和效果缺口只有在确定破坏完整性或安全性时才阻断，一般效果提升需求只告警。
21. `DesignBrief` 是工作台交互模型；确认后必须投影为不可变 `StoryBriefRevision`，后续剧本、ProgramSegment、Shot、麦兔草稿和成片共用该内容源。
22. 每个事实句、剧本块、Shot、载体投影、素材选择和执行结果必须保留可机读来源边，支持从结果反查目标、模板、事实和证据。
23. 麦兔草稿和竖屏成片是同一内容修订的两个独立生产分支；二者共享内容与素材来源，但使用不同执行计划和质量门禁。
24. 运营数据先形成版本化归因事实，再进入素材检索和再生产；原始互动量、GMV 或单场相关性不得直接改写硬约束或自动发布模板。
25. 业务数据库是事实源；Milvus 和后续 Neo4j 都是可按投影版本重建的检索/图谱派生层。
26. `ContentProject` 是跨载体业务聚合根；StoryBrief、Script 和通用内容结构不得由 `LiveRoomConfiguration` 创建或拥有。
27. `ProgramSegment` 表达节目语义段，`Shot` 表达导演镜头，`MaituSceneBlueprint` 表达麦兔可执行场景，`TimelineSegment` 表达剪辑区间，四者不得继续共用 `Scene` 名称。
28. 任何真实播出、投放或交付都必须绑定不可变 `ReleaseManifest`；生成成功不等于已经发布或实际曝光。
29. 所有长任务共享 `WorkflowRun / StepRun / HumanTask / ArtifactRef` 控制面和统一 lineage/trace，不再各自发明父子运行、取消、超时和人工等待语义。
30. 运营证据分为描述统计、关联估计、准实验和随机实验四级；只有达到策略规定证据等级的结果才能自动影响生产排序。
31. 编辑时间使用帧率感知的有理数时间和 OTIO 兼容结构；直播观测、互动和指标继续使用会话毫秒时间，两者通过显式 TimeMapping 关联。
32. 素材可用性同时受技术能力、版权/许可、肖像/声音授权、渠道/地域/时间范围和撤销状态约束，并向所有衍生 release 传播。

## 3. 范围与非目标

### 3.1 本规划覆盖

- 同步和索引麦兔素材、数字人、音色及其可执行身份。
- 配置素材全局约束、直播间覆盖、素材分组和素材模板包。
- 管理多商品已批准事实卡。
- 监听抖音直播间、保存录屏、运行 ASR/OCR/视觉/结构分析。
- 从同一直播间的多场录屏提炼、审核和发布内容策略模板。
- 创建版本化直播间配置，解析目标，选择内容模板和素材范围。
- 生成 StoryBrief、Script/ScriptBlock、ProgramSegment/ShotList、载体场景、素材分配、素材需求和 BuildPlan。
- 自动执行空白草稿 preflight 和安全写入，回写证据。
- 从同一 `StoryBriefRevision` 可选生成竖屏成片、确定性时间轴、字幕、音频和渲染质量证据。
- 接收录屏互动、麦兔/JD 指标和人工标注，按内容时间区间形成版本化归因结果。
- 建立素材、事实、模板、剧本、Shot/载体投影、发布、曝光和效果之间的可重建知识图谱投影，并将合格效果证据用于推荐和再生产。
- 建立跨业务域统一运行、artifact、lineage、trace、人工任务、策略决策和成本控制面。
- 建立不可变发布清单、麦兔/视频交付、实际曝光日志以及数据/权利/保留治理。

### 3.2 当前阶段明确不做

- 不点击“正式开播”，所有结果保持 `ready_for_go_live=false`。
- 不在第一版支持普通非空房间增量更新、差异回滚或破坏性清空；仅保留 ADR-0003 定义的白名单离线测试房整房重建例外。
- 不把外部直播平面录屏推断成真实麦兔图层、material ID 或精确 z-index。
- 不做素材文件的双向上传、改名和删除管理；需要新增媒体时先在麦兔处理，再同步 AssetGraph。
- 不做交互式非线性视频剪辑器或手工拖拽式直播画布编辑器；系统生成并允许表单化调整确定性时间轴与剪辑决策。
- 不在第一版同时接入多个外部直播平台。
- 不做多租户、组织隔离或复杂 RBAC。
- 不允许任意自然语言或任意 JSON 直接变成 Browser-use 执行动作。
- 不在本阶段实现正式排播、开播授权或点击开播；相关对象只能被引用，不能触发现场副作用。
- 不在近期建设镜头级手工导演编辑器；但最小 `Shot/ShotListRevision` 作为两个生产分支的统一中间层必须先落地。
- 不在近期自动执行 RoleStrategy 淘汰、A/B 分流、排播或开播；其完整对象、日志、统计门禁和授权状态机纳入长期规划，未达准入条件时保持禁用。

## 4. 产品与前端信息架构

### 4.1 全局应用壳与路由

长期使用统一 AssetGraph Console，一级导航按业务域扩展，路由保存稳定实体深链：

```text
/assets/library?asset=AG-...
/knowledge/facts?fact_card=FACT-...
/research/live-sources?session=CAP-...
/content/projects?project=CONTENT-...
/production/live-rooms?config=MT-ROOM-CONFIG-...
/production/videos?job=VID-PROD-...
/production/releases?release=RELEASE-...
/operations/live-sessions?session=LIVE-...
/operations/attribution?result=ATTR-...
/operations/schedules?schedule=SCHEDULE-...
/learning/effects?estimate=EFFECT-...
/learning/experiments?experiment=EXP-...
/governance/runs?run=RUN-...
/governance/metrics?metric=METRIC-...
```

所有工作区共享登录态、命令/任务中心、通知、全局搜索、审计操作者和错误处理，但不共享未保存的表单状态。首页进入“我的任务/异常”，而不是固定进入某个生产表单。

近期不要求一次性重写现有前端。`/maitu/` 内的素材、模板、直播间三个标签先完成业务闭环，再逐步迁移到上述稳定路由；后端领域 API 不依赖临时查询参数。

旧入口迁移规则：

- `/live-research/` 在功能迁移完成后重定向到 `/research/live-sources`，不再先绕入 `/maitu/`。
- 当前“生产运行”近期迁入 `/maitu/` 的直播间配置，长期迁入 `/production/live-rooms`。
- 当前“资源与事实”近期迁入素材管理，长期拆到 `/assets` 与 `/knowledge`。
- 当前“Gemini 回填”迁入素材详情中的分析与冲突审阅，不再作为顶层视图。
- 迁移期间保留旧实体查询能力，旧运行作为只读历史展示。

### 4.2 内容项目工作区

内容项目是两个生产分支的共同入口，包含：

1. **目标与事实**：generation goal、DesignBrief、目标商品、已批准事实引用和待确认问题。
2. **内容模板**：主/次模板、模块贡献、冲突和最终采用投影。
3. **StoryBrief 与剧本**：不可变 StoryBriefRevision、ScriptRevision、ScriptBlock、事实引用和质量门禁。
4. **节目结构与镜头**：ProgramSegment、最小 ShotListRevision、素材角色需求和分支适用性。
5. **生产分支**：创建 live_room 或 rendered_video ProductionVariant，查看各自输入快照、运行和 release。
6. **来源关系**：从内容结果回溯原始目标、事实、模板、操作者、策略和运行证据。

内容项目不要求填写 `liveRoomId`。目标房间、麦兔 inventory、房间覆盖和 BuildPlan 只属于 live_room 分支；画布、帧率、RenderProfile 和 ProductionTimeline 只属于 rendered_video 分支。

### 4.3 素材管理工作区

子页固定为：

1. **素材库**：密集列表、筛选、预览、麦兔绑定状态、业务角色、全局约束和分析状态。
2. **素材分组**：分组列表、成员管理、批量添加/移除、跨组重复成员提示。
3. **素材模板包**：总体包、分类包、版本、发布和排他域配置。
4. **商品知识迁移入口**：近期保留事实卡管理；知识库工作区上线后跳转到 `/knowledge/facts`。
5. **同步任务**：麦兔 inventory 同步、快照质量、失败重试和差异摘要。
6. **效果与关系**：按素材查看使用场景、版本化效果事实、归因置信度和上下游关系；低样本结果明确标记为不可用于自动推荐。

素材详情使用右侧详情面板或独立详情区，不把多个卡片嵌套。详情分为基础信息、约束、锚点/区域、图层关系、播放/音频、分组、使用历史和分析证据。

### 4.4 直播模板配置工作区

子页固定为：

1. **来源直播间**：新增抖音直播间 URL、显示名、商品品类、监听状态和最近采集结果。
2. **录屏场次**：录制状态、媒体、时间线、ASR、互动摘要和保留期限。
3. **数据清洗**：转写校正、场景边界、模块类型、商品事实去除、例句和来源证据。
4. **模板草稿**：策略结构编辑、来源场次、置信度、问题和发布门禁。
5. **已发布模板**：不可变版本、适用品类、内容能力、近似视觉参考、生产使用记录和合格效果摘要。

### 4.5 直播间生产工作区

左侧是配置列表和状态筛选，右侧是当前配置的连续工作区：

1. 选择 ContentProject、StoryBrief/Script/ShotList 固定修订。
2. 填写目标 `liveRoomId`、期望标题和麦兔分支覆盖。
3. 选择总体素材包、分类素材来源、分组和零散素材。
4. 查看有效素材白名单、素材覆盖、约束冲突和缺口。
5. 查看 MaituSceneBlueprint、LayerBlueprint 和 BuildPlan。
6. 运行 preflight、短期执行授权、麦兔写入和回读证据。
7. 创建并检查 `ReleaseManifest(kind=live_room_draft)`，绑定后续 LiveSession。
8. 查看实际曝光、运营归因和效果反馈。

页面自动保存可编辑草稿，但只有“确认输入”才创建不可变配置修订并允许生成。

### 4.6 知识库工作区

知识库不附属于单个直播间，包含：

1. **商品事实**：事实卡、字段级来源、有效期、批准状态、冲突和使用记录。
2. **内容知识**：品类知识、合规规则、术语、表达禁区和经审核内容模块。
3. **来源证据**：文档/网页/人工录入来源、抽取运行、校验和及引用区间。
4. **关系浏览**：从事实反查剧本、场景、成片、直播场次与效果结果。

知识库编辑与生产引用分离。只有已批准、在有效期内且适用范围匹配的修订进入生产；搜索命中不等于事实授权。

### 4.7 成片生产工作区

成片工作区管理 rendered_video ProductionVariant、兼容的 `VideoProductionJob`、确定性时间轴、配音、字幕、渲染、质量检查和 release/delivery。界面提供结构化片段顺序、起止时间、转场、音轨和字幕调整，不建设通用 NLE。用户从 ContentProject 创建成片分支，也可以显式复用某个 live_room variant 的内容修订，但不依赖麦兔房间配置。

### 4.8 运营与归因工作区

运营工作区按 `LiveSession` 聚合外部录屏、麦兔/JD 指标、互动事件摘要、实际曝光、内容时间区间、异常和归因结果。页面必须同时显示 release、时间对齐质量、数据缺失、样本量、归因方法、置信度和可用于学习的资格，避免把相关性展示成确定因果。长期排播作为同域独立视图管理 Schedule、冲突和授权；capability 关闭时只允许设计/验证计划，不显示可误触的开播命令。

### 4.9 效果学习工作区

效果学习工作区分别展示素材、内容模块、模板、Shot/载体投影和商品的 `PerformanceProfile`、`AssociationalEstimate` 与 `CausalEstimate`，支持比较适用上下文、证据等级、样本量、区间估计、漂移和决策使用记录。实验视图管理预注册设计、分配、曝光对账、SRM/护栏和分析。运营可以批准、冻结或撤销合格估计进入选材/生成；系统不根据单场数据、描述统计或未批准相关性自动提升全局规则。

### 4.10 治理与任务中心

治理工作区提供跨域运行、人工任务、发布审批、策略/实验、指标目录、数据质量、权利到期、保留删除、SLO、成本和投影重建。它不复制各业务表单，而是按 `WorkflowRun`、`ReleaseManifest`、`PolicyDecision`、`DataQualityIncident` 和 owner 聚合待处理事项。

### 4.11 跨工作区交互规范

- 可编辑对象默认自动保存 draft，并显示“本地编辑中/已保存/保存失败”；只有确认、发布、批准、授权等显式命令创建不可变 revision 或副作用。
- 所有详情页提供 revision 时间线、结构化 diff、操作者、来源和“此版本被哪些运行/release 使用”；禁止用“最新值”覆盖历史引用。
- 列表支持 URL 深链、保存筛选、批量选择和后台批量任务。高风险批量操作先显示影响数量、阻断项和示例 diff，执行后进入 WorkflowRun。
- 素材约束提供表单化规则构建、命名区域可视预览、常用规则模板、当前房间覆盖 diff 和“提升为全局新修订”；用户不直接编辑任意执行 JSON。
- 模板清洗把播放器、ASR/OCR、内容模块和来源证据按同一时间轴联动；发布前同时预览内容投影、被去除事实和 layout/buildability 状态。
- 生产页在生成前显示有效事实、模板贡献、素材白名单和权利/约束快照；生成后显示 Shot 到载体投影、缺口、冲突及可执行修复，不只展示总分。
- 长任务离开页面后继续运行；全局任务中心显示排队原因、当前 step、成本、重试、等待人工和取消结果。通知必须深链到具体实体 revision/证据。
- 错误信息使用稳定规则码、影响、证据和下一步；warning 不被折叠成成功，`insufficient_data`、`stale`、`reconcile_required` 不冒充失败或完成。
- 所有批准/拒绝/豁免先展示将固定的 revision 与影响范围，要求结构化理由；不可通过浏览器刷新、重复点击或多标签页产生重复副作用。

## 5. 素材分类模型

素材必须同时具备三个互不替代的分类维度。

### 5.1 媒体类型 `media_kind`

```text
image / video / audio / digital_human / text / template_preview / document
```

媒体类型回答“它是什么文件或对象”。麦兔“模版”页同步下来的预览或模板入口使用 `template_preview`，默认只能作为参考，不能伪装成背景或装饰插入。

### 5.2 业务角色 `material_role`

一个素材可拥有多个业务角色：

```text
background
set_surface
product_display
digital_human
brand_title
promotion_text
decoration_foreground
supporting_video
voice
background_music
sound_effect
```

业务角色回答“它在直播间里做什么”。`set_surface` 专门表示背景之上的底图、桌面和承托面，不能借用 `background` 或 `decoration_foreground`，否则会破坏桌面商品的层级关系。素材包排他、房间分类选择、约束关系和生成器需求都以业务角色为边界，不直接使用文件扩展名或麦兔页签作为业务含义。

### 5.3 执行能力 `execution_capability`

```text
maitu_bound / local_only / reference_only / unavailable
```

- `maitu_bound`：有唯一、已验证的麦兔素材身份，可进入自动写入。
- `local_only`：只有 `/DATA` 文件，可分析但第一版不能自动写入。
- `reference_only`：只作模板或视觉参考。
- `unavailable`：麦兔已删除、失效或本轮同步无法确认。

必用素材不是 `maitu_bound` 时构成硬阻断；普通候选不是 `maitu_bound` 时从可执行候选中排除并产生提示。

### 5.4 检索属性

素材还可以保存品牌、商品品类、商品编号、主题、画面风格、透明背景、绿幕、是否可循环、是否带声音、宽高比和适用场景等属性。它们用于检索和兼容性判断，不承担硬约束语义。

### 5.5 素材身份、生命周期与质量

每个逻辑素材使用稳定 `asset_code`；二进制文件、麦兔绑定和语义分析分别版本化，不能用文件名作为身份。至少保存：

- `AssetFile` 的内容校验和、MIME、尺寸/时长、存储相对路径和派生关系。
- 麦兔 `material_id`、来源页签、最近确认时间和 inventory 快照；一次同步不得凭“本轮没看到”立即删除绑定。
- 分析模型、提示、参数、输出校验和、质量分和人工覆盖；模型更新不原地覆盖旧结果。
- 版权/许可、品牌、敏感内容、过期时间和人工可用状态；不满足授权或合规要求时从所有可执行候选排除。
- 感知哈希和内容校验和形成的重复候选；重复合并必须保留别名、来源和历史引用。

同步采用“发现 -> 对账 -> 软失效 -> 人工确认/再次发现”的生命周期。只有连续快照或明确现场证据确认删除后才置为 `unavailable`；历史配置修订仍引用原身份和当时证据，不级联改写。

### 5.6 检索、选材与可解释排序

选材分成不可交换的两步：

1. **确定性候选过滤**：只保留输入快照白名单内、执行能力满足目标、授权有效且所有硬约束有解的素材。
2. **候选排序**：在剩余集合内综合业务角色匹配、语义相似度、画幅/时长适配、质量、软偏好、重复惩罚和满足准入条件的效果分。

排序结果必须返回每项分数、证据版本、排除码和最终选择理由。效果分只能来自第 23 节定义的、满足当前 `LearningPolicy` 的批准估计；缺少样本时回退为中性值，不能惩罚新素材。必用项和排他规则先于排序执行，模型不得用高相似度绕过它们。

### 5.7 逻辑素材、版本、rendition 与权利

`Asset` 表达可被业务引用的逻辑作品；`AssetVersion` 表达内容修订；`AssetFile/Rendition` 表达原始文件、转码、缩略图、抠图、音频提取等技术表现。所有 rendition 通过 `derived_from` 指向源版本，拥有独立校验和、技术元数据和生成运行，但继承并收紧源权利，不能自行扩大授权。

`RightsGrant` 至少包含权利主体、许可来源、允许用途、平台/渠道、地域、有效时间、是否允许修改/衍生、是否允许 AI 分析/生成、署名要求、模型/肖像/声音授权、凭证 artifact 和撤销状态。权利判断按 `deny/revoked > narrower grant > broader grant` 合并；未知权利的素材可以分析但不能进入可交付 release。

RightsGrant 状态为 `draft -> active -> expired|revoked|superseded`。只有 `active` 且当前用途落在授权范围内才通过；到期由时间判定但仍物化 `expired` 便于查询。撤销必须记录原因、权限主体和证据，不能物理删除旧 grant。

权利 preflight 在选材、生成 release candidate 和实际交付前分别重验。授权到期或撤销不会删除历史证据，但使未交付分支、未来 release 和推荐候选立即失效，并产生影响分析任务。

## 6. 素材约束模型

### 6.1 约束版本

每个素材可以有一个当前全局 `AssetConstraintProfile`，每次保存产生新修订。生成运行固定约束修订和内容指纹，不读取运行期间发生的新修改。

约束规则采用受控契约：

```json
{
  "constraint_key": "product-on-table",
  "rule_type": "require_named_region",
  "hardness": "hard",
  "scope": {"material_role": "product_display"},
  "parameters": {
    "region_name": "table_surface",
    "subject_anchor": "bottom_center",
    "region_anchor": "surface_line"
  }
}
```

`constraint_key` 在素材全局约束、素材包规则和直播间覆盖之间保持稳定，用于明确替换或禁用某条规则。

### 6.2 支持的规则类型

第一版规则构建器必须覆盖：

- `allowed_region`：图层边界或锚点必须位于归一化矩形/多边形内。
- `forbidden_region`：不得进入指定区域。
- `provide_named_region`：背景或框架素材向其他素材提供命名区域。
- `require_named_region`：要求使用另一个素材提供的命名区域。
- `preserve_aspect_ratio`：必须等比缩放。
- `size_range`：归一化宽高或相对原始尺寸的最小/最大值。
- `scale_range`：统一缩放倍数范围。
- `crop_policy`：禁止裁剪、允许 cover、允许 contain 或人工处理。
- `rotation_policy`：禁止旋转或限制角度集合。
- `pin_layer_top` / `pin_layer_bottom`：定义不可穿越的硬层级带。置顶素材必须高于所有非置顶素材，置底素材必须低于所有非置底素材；同一素材同时硬置顶和硬置底直接判为冲突。多个同带素材可按同带内的相对规则和稳定次序排列，但不能离开该层级带。
- `forbid_layer_top`：素材不得成为场景最高图层；若场景没有可合法位于其上的素材则布局无解，不能把该规则降级为偏好。
- `above_role` / `below_role`：相对当前场景中某类素材的图层关系。关系作用于实际选中的全部匹配图层，并与置顶/置底规则共同编译，不能靠数组顺序或最后一次赋值覆盖。
- `avoid_overlap`：不得遮挡指定角色或命名区域，可设置允许遮挡比例。
- `align_anchor`：左右、上下、中心或基线对齐。
- `distance_range`：两个素材锚点之间的最小/最大距离。
- `loop_policy`：视频/BGM 是否循环。
- `mute_policy`：视频默认静音或必须保留声音。
- `volume_range`：BGM、语音和音效的音量范围。

归一化坐标范围为 `[0, 1]`，执行时按目标画布换算。原始素材像素和麦兔实际回读像素均保留作证据，但不能作为跨画布的唯一约束。

### 6.3 命名区域与桌面效果

“商品摆在背景桌面上”由两端共同表达：

1. 背景素材提供 `table_surface` 区域和 `surface_line` 锚点。
2. 商品素材要求 `bottom_center` 位于 `table_surface`，底边贴合 `surface_line`。
3. 商品要求位于背景之上、前景框架之下。
4. 商品可追加不遮挡 `digital_human` 和 `promotion_text` 的规则。

背景没有所需区域时，系统可以推荐另一个背景，但不得猜测桌面位置并继续自动执行。必用商品明确要求桌面效果时，该冲突是硬阻断。

### 6.4 硬约束、软偏好与覆盖

- `hard`：生成器和布局求解器不得违反；无解时产生冲突。
- `soft`：允许偏离，但必须写入警告和偏离原因。
- 系统安全规则不可覆盖。
- 直播间覆盖可以替换素材全局规则，但必须记录操作者、原因和前后差异。
- 素材包必用/排他不能通过普通素材覆盖静默取消，只能通过该角色域的显式“替换”模式移除原包内容。
- 从直播间点击“另存为全局约束新版本”需要二次确认，不修改其他运行已经固定的快照。

多个有效来源对同一素材添加规则时，硬约束取交集而不是按任意顺序覆盖。交集为空即阻断。直播间通过相同 `constraint_key` 做的显式覆盖除外。

### 6.5 约束求解器契约

约束规则先编译为与求解器无关的 `ConstraintProblem`，再由版本化 solver adapter 执行。第一阶段评估 OR-Tools CP-SAT/MIP：离散选择、角色次数、z-order 和互斥使用整数/布尔变量；归一化几何按配置精度缩放为整数或交给支持连续变量的 MIP。不得在业务服务中手写回溯求解器。

每次求解固定模型版本、变量/约束清单、软目标权重、随机种子、时间/内存上限和 warm-start。结果状态统一为：

```text
optimal / feasible / infeasible / unknown / invalid_model
```

`feasible` 可以继续但记录最优差距；`unknown` 不得被当作无解，也不能自动执行硬约束未证实的布局；`infeasible` 必须返回最小或近似冲突约束集合、来源实体和可执行修复建议。软约束使用分层目标，不得以总分抵消任何硬约束。

图层关系先编译为从低到高的偏序图：`lower -> upper`。硬置底为所有非置底图层的前驱，硬置顶为所有非置顶图层的后继，`above_role / below_role` 增加角色关系边。无条件硬关系引用缺失角色、硬规则产生环、同一素材进入两个硬层级带或顺序无法满足时，场景必须阻断并返回冲突规则和素材来源。对“目标角色出现时必须遵守，但不要求每场都出现目标角色”的关系使用 `parameters.when_present=true`；目标存在时它仍生成硬边，目标不存在时记录为不适用证据。软关系只有在不破坏硬图时才采用，否则记录偏离证据。该确定性拓扑编译是 ConstraintProblem 的预处理，不替代几何和选材 solver。

求解成功后必须稳定压缩成唯一、连续、从底到顶的 `1..N` 平台层级，并同时生成层级策略版本、每层所在层级带、硬前驱和软偏离证据。模板原始 z-index、素材数组顺序和人工输入的裸数值只可作为同一可行层级带内的排序偏好；它们不是执行真值，也不得把置底素材抬到普通/置顶素材之上，或把置顶素材压到普通/置底素材之下。

## 7. 素材分组与素材模板包

### 7.1 素材分组

素材分组是人工集合：

- 一个素材可加入多个分组。
- 分组不嵌套。
- 分组不保存位置、层级或播放约束。
- 分组成员变化不会反向修改已经确认的直播间输入快照。
- 分组可以在素材包编辑器中用于批量添加，但素材包修订保存解析后的明确素材编码，不保存动态分组引用。

### 7.2 素材模板包类型

- **总体素材包**：可包含所有业务角色的素材，也可以引用分类素材包。
- **分类素材包**：只能属于一个 `material_role`，例如背景包、商品包、数字人包或 BGM 包。

总体包不得引用另一个总体包。分类包不得递归引用分类包。这样可以表达两级组合，同时从模型上消除循环依赖。

### 7.3 素材包条目

每个条目必须声明：

```text
asset_code 或 category_pack_code
material_role
usage: required / optional / alternative
min_occurrences / max_occurrences
applicable_scope: whole_room / scene_types / scene_codes
pack_constraints
alternative_set_key（仅备选项）
```

- `required`：至少满足次数要求，否则阻断。
- `optional`：进入白名单，由生成器按内容选择。
- `alternative`：同一备选集合只需选择满足数量的成员。

### 7.4 排他域

素材包可对一个或多个业务角色声明排他：

```text
exclusive_roles = [background, brand_title]
```

排他只禁止同角色域的包外素材，不影响其他角色域。两个追加素材包对同一角色域都声明排他且内容不兼容时，不自动决定胜负，必须报告冲突。

### 7.5 总体包与分类选择合并

每个角色域提供三种模式：

- **沿用**：只使用总体包在该角色域的解析结果。
- **追加**：总体包结果加分类包、素材分组和零散素材。
- **替换**：明确移除总体包在该角色域的内容与排他声明，改用当前分类配置。

同一素材通过多个来源进入白名单时只保留一次；使用强度按 `required > alternative > optional` 合并，来源列表全部保留。多个包产生的硬约束同时生效，无解时阻断。

### 7.6 最新版本与运行快照

素材包逻辑引用默认指向“最新已发布版本”：

1. 编辑直播间配置时自动显示最新发布版本和更新提示。
2. 点击“确认输入”时解析总体包、分类包和所有成员。
3. 配置修订保存包编码、实际修订号、素材清单、约束和整体指纹。
4. 生成和执行只使用快照。
5. 需要采用新版本时，用户点击“刷新输入”，创建新的配置修订并重新生成。

### 7.7 素材缺口生命周期

`AssetGap` 不是一次性文本提示，而是可追踪对象：

```text
open -> candidate_found -> resolved
     -> waived          -> obsolete
```

缺口保存 `gap_type`、业务角色、来源 StoryBrief/ScriptBlock/ProgramSegment/Shot/ProductionVariant、期望规格、约束、严重度、替代素材、影响说明和创建运行。`candidate_found` 只有在候选完成目标分支绑定、RightsGrant、授权检查和约束预检后才能进入；`resolved` 必须固定所用 `asset_code`、版本/rendition/绑定和处理人。`waived` 要记录原因并只对当前分支修订生效。新素材入库后可以重跑匹配，但不能静默修改已确认运行。

## 8. 内容策略模板

### 8.1 来源边界

第一版一个内容策略模板只能绑定一个来源直播间，但可以选择该直播间的多场已完成录屏作为证据。跨直播间组合只发生在直播间配置的主/次模板选择阶段，不能在模板清洗时隐藏来源主次。

模板必须填写适用商品品类。可选保存销售模式、目标受众、价格带和直播风格标签，用于兼容性推荐，但这些字段不能成为目标商品事实。

### 8.2 清洗流水线

```text
CaptureSession
  -> 媒体时间线和校验和
  -> ASR + OCR + 关键帧 + 互动摘要
  -> 转写校正和噪声清理
  -> 商品事实句、平台噪声和一次性活动信息识别
  -> 内容模块切分
  -> 同直播间多场聚合
  -> 内容策略模板草稿
  -> 运营整体确认
  -> 不可变发布版本
```

数据清洗必须保留来源场次、时间区间、原始证据摘要和分析模型版本。删除模板中的商品事实不删除来源证据，只是不允许它进入生产投影。

每个 `CaptureSession` 先建立统一媒体时钟和 `media-timeline.v1`。录屏分片、音频、ASR token/segment、OCR、关键帧、视觉区间和互动摘要都映射到同一 `[start_ms, end_ms)` 坐标；发生掉帧、断流、时钟漂移或缺失通道时记录校准方式和置信度，不以数组下标拼接多模态结果。

清洗结果分三层保存：

1. 原始层：媒体分片、原始事件批次、校验和、抓取工具版本和保留策略，只允许受控访问。
2. 标准层：时间轴区间、ASR/OCR、画面变化、互动桶和质量标记，可重复计算。
3. 发布层：去来源商品事实后的内容模块、例句槽位、节奏和近似布局，只暴露生产所需投影。

模板发布门禁必须覆盖媒体完整性、时间轴覆盖率、ASR/OCR 质量、来源事实去除、模块证据覆盖、人工整体审核和投影 schema 校验。任一发布字段都能反查到标准层区间和分析运行；原始互动事件不直接暴露给模板编辑前端。

### 8.3 `content-strategy.v2` 契约

发布模板至少包含：

- `target_category`：适用品类和兼容性标签。
- `program_outline`：开场、建立信任、讲品循环、互动、促单、过渡、收尾等阶段。
- `duration_policy`：各阶段相对时长、允许范围、是否可重复。
- `module_recipes`：每类话术模块的目标、输入槽位、表达动作、转场和退出条件。
- `product_rotation_policy`：商品顺序、单品讲解循环和回到主线的方式。
- `interaction_policy`：提问、评论回应、关注提醒和互动频率。
- `conversion_policy`：CTA 位置、重复节奏和合规边界。
- `host_style`：主播人设、语气、语速、句式和禁止表达。
- `material_cues`：各内容模块需要的业务角色，不绑定具体目标素材。
- `reviewed_examples`：经整体确认、商品事实已替换为槽位的少量例句。
- `layout_reference`：可选的近似画面区域和视觉节奏。
- `provenance`：来源直播间、场次、证据、模型和人工审核信息。

例句示例：

```text
来源句：这款具体商品的产区和活动信息……
模板句：先用【已核验产地事实】建立可信度，再用【适用场景】帮助观众判断是否适合自己。
```

模板例句只能影响表达方式，不能进入事实白名单。

### 8.4 内容能力与视觉能力解耦

发布投影分别声明：

```text
content_readiness: blocked / review_required / ready
layout_fidelity: none / approximate / verified_layout
buildability: reference_only / executable
```

外部平面录屏通常可以达到 `content_readiness=ready`，同时保持 `layout_fidelity=approximate` 和 `buildability=reference_only`。没有可识别画面组件不能再阻止一个合格话术模板发布。

### 8.5 主模板和次要模板

- 主模板可不选，最多一个；选中后决定总体阶段顺序、节奏和默认模块。
- 次要模板不设业务数量上限。
- 系统根据 DesignBrief、商品品类和主模板缺口，为每个次要模板提出模块贡献建议。
- 用户可以接受默认建议，也可以修改某个模板贡献的话术模块、互动策略或视觉风格。
- 冲突时主模板优先；次要模板只能补充缺失模块或在明确记录的模块级决策中替换。

次要模板不设数量上限不等于无限模型上下文。上下文编译器必须：

1. 先按品类和目标过滤不相关模板。
2. 按模块检索最相关贡献。
3. 对等价话术骨架去重。
4. 只发送结构摘要和已采用例句。
5. 在结果中列出采用、未采用和冲突的模板来源。

### 8.6 采集、版权与模板相似性治理

每个 WatchTarget/CaptureSession 必须记录采集授权依据、平台条款审阅版本、用途、保留策略、访问级别和 owner。没有合法采集/分析依据时不得启动；来源撤销后停止后续采集，并按保留策略删除或隔离原始媒体和个人数据。

模板发布除事实去除外，还要执行连续文本重合、品牌/主播特征模仿、受版权保护画面和敏感信息检查。发布投影只保留抽象内容结构、经过阈值检查的短例句和必要证据引用；高相似片段进入人工审阅，不能因为“已去商品事实”就自动视为可复用。

## 9. ContentProject 与 ProductionVariant

### 9.1 聚合对象

`ContentProject` 是跨载体业务聚合根；`ContentProjectRevision` 固定一次目标、事实和模板选择；`StoryBriefRevision`、`ScriptRevision`、`ShotListRevision` 是它的内容产物。`ProductionVariant` 引用这些固定修订，并选择 `live_room` 或 `rendered_video` 分支。

`LiveRoomConfiguration` / `LiveRoomConfigurationRevision` 作为 live_room variant 的分支配置继续存在；`VideoProductionJob` 作为 rendered_video variant 的执行聚合继续存在。`WorkflowRun` 承载一次跨域编排，现有 `WorkbenchRun` 迁移为其 live-room 兼容投影。这样避免运行任务反向拥有业务输入，也避免视频生产依赖麦兔房间。

### 9.2 基础输入

必填字段：

- `project_title`：内容项目名称。
- `generation_goal`：一个大文本框，可写主题、故事、受众、风格、限制或详细设计。
- `fact_card_refs`：至少一份已批准事实卡及固定版本。

可选字段：

- 大致目标时长。
- 平台、受众、主播人设和语气。
- 商品优先级和讲解顺序。
- 必须包含和禁止出现的内容。
- 互动、促单、画面和音频要求。
- 默认素材/模板偏好；生产分支可以覆盖。

`target_live_room_id`、麦兔标题、是否只生成方案、画布/帧率和 RenderProfile 都不是 ContentProject 必填项，只在对应 ProductionVariant 创建时填写。

### 9.3 DesignBrief 解析

自由文本先由受限模型解析为：

```text
objective
theme_and_story
target_audience
product_priorities
host_persona
tone
target_duration_minutes
must_include
must_avoid
visual_staging_requirements
interaction_requirements
conversion_requirements
visual_requirements
audio_requirements
open_questions
```

原文永久保留。结构化结果可编辑，修改必须记录为用户确认值。解析器最多提出 1 至 3 个真正影响结果的问题，并给出推荐答案；用户可以跳过非阻断问题。

原始目标必须作为带边界的用户数据传入模型，不能覆盖系统安全、事实白名单、模板来源和素材硬约束。

### 9.4 模板选择

模板选择区显示：

- 与商品品类和目标的兼容分。
- 主模板候选及其节目阶段摘要。
- 已选次要模板及系统建议贡献。
- 品类不一致、内容重复和策略冲突。
- 最终送入生成上下文的模块和来源。

模板不包含目标商品事实。主次模板都只能决定结构、表达动作、节奏和素材需求。

### 9.5 分支素材选择

素材选择明确分成四层：

1. 可选总体素材包。
2. 每个业务角色域的沿用/追加/替换模式及分类素材包。
3. 分组素材多选。
4. 零散素材多选。

分组和零散素材在 UI 中独立选择，解析后形成该 ProductionVariant 的统一白名单。每个素材可设置“可选”或“至少使用一次”；live_room 分支可建立房间私有覆盖，rendered_video 分支可建立时间轴/画幅私有覆盖。

页面必须提供“有效配置”视图，显示每个素材为什么被纳入、来自哪个包/分组、最终使用强度、麦兔执行能力、约束来源和覆盖差异。

### 9.6 输入确认

内容确认与分支确认是两个独立动作。

确认 ContentProject 输入时：

1. 验证 generation goal、事实批准/有效期和模板兼容性。
2. 固定主次内容模板发布版本及贡献决策。
3. 固定事实卡/FactClaim 修订和 DesignBrief 用户确认值。
4. 创建 `ContentProjectRevision`、不可变 `StoryBriefRevision` 和内容输入指纹。

确认 ProductionVariant 输入时：

1. 固定所用 StoryBrief、Script、ShotList 修订和分支目标。
2. 解析已发布素材包，展开分组和零散素材并去重。
3. 合并约束、权利和分支覆盖，运行静态冲突检查。
4. live_room 分支固定麦兔 inventory 和现场目标；rendered_video 分支固定 AssetFile、RenderProfile 和可用区间。
5. 创建分支配置修订、`ResolvedMaterialSnapshot` 和分支输入指纹。

继续编辑只产生新修订；任何已确认内容、分支、运行和 release 都保持不变。

### 9.7 `DesignBrief -> StoryBrief` 权威转换

`DesignBrief` 是面向用户的可编辑解释层；`StoryBriefRevision` 是内容生产的权威输入。确认操作由确定性服务完成 schema 校验、事实引用检查和版本固化，不能让生成模型自行决定使用哪个修订。

`StoryBriefRevision` 至少包含：

```text
story_brief_code / revision / status
objective / theme / narrative_premise / audience / host_persona
product_priorities / required_fact_refs[]
program_outline / content_requirements / visual_staging_requirements
interaction_policy / conversion_policy
visual_policy / audio_policy / duration_policy
must_include[] / must_avoid[]
template_contribution_refs[] / default_material_policy_ref?
source_design_brief_revision / input_fingerprint
producer_role_code / strategy_code / strategy_version
```

状态只允许 `draft -> confirmed -> superseded`。`confirmed` 后不可原地修改；生成失败重试引用同一修订，业务输入变化创建新修订。新产物必须记录实际 role/strategy revision；确定性服务使用显式 `system_baseline` 策略，历史空字段只在兼容投影中显示为 `unknown`，不参与自动评价。

### 9.8 ProductionVariant 分支契约

每个 ProductionVariant 至少固定 `variant_code`、`variant_kind`、ContentProjectRevision、StoryBrief/Script/ShotList 修订、分支目标、素材/约束快照和预期交付类型。

- `live_room`：必须提供目标麦兔空白草稿房间、期望标题、inventory 快照、现场保护策略和 `auto_write_draft/plan_only`。
- `rendered_video`：必须提供画布、帧率、目标时长策略、RenderProfile、音频/字幕策略和目标交付渠道。

同一内容项目可以有多个分支和多个分支修订。分支间不共享可变状态；复用只通过固定内容修订、素材版本和 lineage 完成。

## 10. 生成、校验与执行

### 10.1 生成阶段

```text
Stage 1  编译 StoryBriefRevision、事实、模板和素材上下文
Stage 2  生成 Script、ScriptBlock、ProgramSegment 和 ShotListRevision
Stage 3  创建 ProductionVariant 并从分支硬白名单选材
Stage 4a live_room 求解 MaituScene/Layer 布局并生成 BuildPlan
Stage 4b rendered_video 生成 OTIO 兼容 ProductionTimeline 和 RenderManifest
Stage 5  生成素材需求单、冲突报告和分支质量报告
Stage 6  通过门禁后创建 candidate，经批准固化不可变 ReleaseManifest
Stage 7  经短期执行授权交付 release、写入草稿/上传产物并回读 DeliveryAttempt
```

大模型负责内容策略、场景意图和候选组合；确定性服务负责事实验证、白名单验证、约束求解、冲突判断、操作生成和安全门禁。模型不能直接输出可执行 Browser-use 点击序列。

### 10.2 事实与话术规则

- 事实性陈述只能来自固定的批准事实卡。
- 模板允许提供修辞、表达步骤和去事实化例句。
- 模型可以生成新的连接语和非事实性表达，不再要求所有句子只能复制事实卡原句。
- 每个事实性句子必须记录事实卡、版本和字段来源。
- 促销、价格、库存、赠品和功效没有批准事实时不得生成。

### 10.3 时长规则

目标时长是指导值。生成器按主模板阶段比例和目标时长伸缩内容，不要求场景秒数之和精确相等。

- 有目标时长时，结果必须给出估算总时长和偏差比例。
- 偏差不超过约 50% 时不因时长单独阻断。
- 偏差超过约 50% 时产生明显质量警告。
- 时长偏差与内容空洞、必讲商品缺失等问题共同出现时，质量门禁可以阻断。

### 10.4 素材缺口与阻断标准

阻断门槛保持较高，只阻断确定影响安全或完整性的情况：

- 目标房间不存在、不是空白草稿、已开播或现场状态不确定。
- 必用素材、必用备选集合或关键数字人/语音不可用。
- 所选素材包的角色域排他冲突无法消解。
- 硬位置、层级、锚点或音频约束无解。
- 已确认必讲内容没有批准事实支撑。
- 生成结果不满足结构契约或事实门禁。
- BuildPlan 使用白名单外素材或包含禁止操作。

以下默认只告警并生成素材需求：

- 有更合适背景、装饰或辅助视频可提升效果。
- 可选素材不足或软偏好无法全部满足。
- 模板建议的互动/视觉模块没有对应素材。
- 时长单独偏离约 50%。
- 画面可读性合格但未达到模板近似参考的最佳效果。

需求单必须说明期望角色、用途、画面特征、尺寸/时长、位置关系、优先级和当前替代结果。

### 10.5 自动 preflight 与写入

配置确认后的默认策略是 `auto_write_draft=true`：

1. 生成完成后自动运行静态门禁。
2. 静态门禁通过后自动执行麦兔只读 preflight。
3. preflight 验证登录态、URL、目标房间 ID、未开播、空白场景、现场指纹和素材可用性。
4. 通过后自动排队执行草稿写入。
5. 失败进入可重试任务或人工事项，不能盲目重放不确定写操作。

BuildPlan 可以包含 `rename_live_room`、填充默认场景、创建后续场景、插入素材、设置位置层级、写脚本、验证场景和保存草稿。操作白名单永远不包含正式开播。

### 10.6 写入后的修订

成功写入后，原配置修订和运行只读。普通房间需要修改时使用“复制到新空白房间”：

1. 复制 DesignBrief、事实卡引用、模板选择、素材选择和覆盖。
2. 清除原执行状态和目标现场指纹。
3. 要求填写新的空白 `liveRoomId` 和期望标题。
4. 重新解析最新素材包并创建新配置修订。
5. 重新生成和执行，不修改旧房间。

ADR-0003 的白名单测试房是独立例外：用户必须先看到当前场景清单并确认整房替换，执行确认绑定现场指纹；Worker 先完成全部素材解析，再保留平台要求的首个场景、清空并删除其余已确认场景，随后执行新 BuildPlan。该模式永久保持测试、不可发布且不可开播。

### 10.7 `StoryBrief -> Script -> ProgramSegment -> Shot` 内容链

每次生成产出版本化 `Script`，其 `ScriptBlock` 是事实、模板、节目结构和运营归因的最小稳定内容单元：

- `Script` 固定 `story_brief_revision`、生成运行、模型/提示版本、结构校验结果和内容指纹。
- `ScriptBlock` 使用稳定 `script_block_code`，保存模块类型、顺序、台词、预计时长、商品、CTA/互动意图、模板贡献来源和事实引用。
- 每个事实性语句使用 `FactCitation` 指向事实卡修订、字段和可选原始证据区间；无法引用的事实句阻断发布。
- `ContentProgramRevision` 把 ScriptBlock 映射为有序 `ProgramSegment`，保存节目阶段、语义目标、预计时长、商品、CTA/互动动作和进入/退出条件。
- `ShotListRevision` 把 ProgramSegment 拆为最小 `Shot`；Shot 保存稳定 `shot_code`、来源 ScriptBlock/ProgramSegment、镜头目标、构图意图、预计时长、素材角色需求、音频动作和分支适用性。
- Shot 不直接保存可变文件路径或麦兔列表序号，只引用素材需求和后续固定选择；一个 Shot 可以投影成一个或多个 MaituScene/Layer 或 TimelineSegment。
- 同一 ScriptBlock 可以跨多个 ProgramSegment/Shot，但必须记录采用的文本区间或内容动作；未映射必讲块、无来源镜头和循环映射构成结构阻断。

每一层都保存 `derived_from` 来源边和独立指纹。人工修改剧本、节目结构或镜头创建新修订，并使依赖它的 ProductionVariant、BuildPlan、成片时间轴、release 和归因映射进入 `stale`，不能继续伪装为最新结果。

### 10.8 麦兔场景、图层与 BuildPlan

`LiveRoomBlueprint` 是 live_room variant 的目标状态，包含有序 `MaituSceneBlueprint`；每个场景包含有序 `LayerBlueprint`。麦兔场景保存来源 ProgramSegment/Shot、触发/切换策略和预计活跃区间。图层至少保存 `layer_code`、业务角色、`asset_code`、麦兔绑定修订、归一化几何、z-order、裁剪/循环/静音/音量、约束求解证据和来源 Shot/ScriptBlock。背景、商品、数字人、标题和音频均通过稳定图层身份关联，不能用显示名称或列表序号代替。

Blueprint 中的 z-order 是第 6.5 节层序编译后的结果，不是模板层序的直拷贝。每个场景必须满足：平台层级唯一且连续，数值越大越靠近视觉顶层；硬置底层低于全部非置底层，硬置顶层高于全部非置顶层，角色相对关系全部成立。任何模板、参考直播间或生成模型给出的顺序与素材硬约束冲突时，约束优先；无解时阻断，禁止“忠实复制参考模板”绕过素材规则。

`BuildPlan` 只由确定性编译器从已通过门禁的 Blueprint 生成，至少固定：

```text
build_plan_code / revision / schema_version / content_fingerprint
production_variant_revision / story_brief_revision / script_revision / shot_list_revision
inventory_snapshot / resolved_material_snapshot / constraint_snapshot
resolved_layer_order[] / layer_order_policy_version / layer_constraint_evidence[]
target_live_room_id / expected_site_fingerprint
ordered_operations[] / operation_preconditions[] / postconditions[]
required_capabilities[] / policy_bundle_version
ready_for_go_live=false
```

允许的操作类型仅为改草稿标题、使用默认空场景、创建场景、插入白名单素材、写入脚本块、调整受控属性、保存和只读验证。编译器拒绝未知操作、任意选择器、任意 URL、白名单外素材、创建/清空非目标房间和开播动作。正式执行还必须取得第 25.4 节定义的、绑定 plan hash 与目标房间的短期 ExecutionAuthorization。

执行器只能消费 `resolved_layer_order` 产生的最终 `z_index`，不得重新采用参考模板顺序、调用顺序或本地列表序号。写入完成后必须逐层回读平台层级并校验其与 Blueprint 完全一致；仅素材身份和几何相同、层级不同不能判为成功。

白名单测试房的清空动作不写入静态内容 BuildPlan，因为待删除场景和素材身份只能来自执行时现场快照。Draft Job 必须另存带指纹的 runtime reset plan：先解析全部素材，再复核房间，保留平台要求的最后一个可用场景并清空，删除其余已确认场景，然后才执行原 BuildPlan。静态 BuildPlan 仍禁止清空操作，普通房间仍必须为空白。

### 10.9 草稿执行与回读证据

执行采用现有 `lease -> checkpoint -> reconcile -> finalize` 协议：

1. Worker 获取有期限 lease，校验 plan 指纹、目标房间和登录主体。
2. 每个有副作用操作先验证前置条件，再记录幂等键、尝试号、开始/结束时间和结构化结果。
3. 操作后回读房间、场景、图层和脚本的现场身份与属性；图层回读至少包含平台图层 ID、素材身份、几何、`layer_n/zIndex` 和从底到顶的完整顺序，并保存截图/DOM 摘要/必要网络证据及校验和。
4. 超时或响应不确定时进入 `reconcile_required`，先观察现场再决定完成、重试或人工处理。
5. finalize 比较实际房间快照与 Blueprint，输出逐场景/逐图层偏差、证据完整率和最终现场指纹。

只有全部硬后置条件满足且证据齐全才能标记 `completed`。软视觉偏差可以带警告完成；缺层、错素材、错房间、未保存、现场变化或出现开播态必须失败并停止。成功结果仍保持草稿状态，不能生成开播授权。

## 11. 确定性优先级

不同来源发生冲突时按以下顺序处理：

1. 系统安全和禁止开播规则，不可覆盖。
2. 已批准事实白名单和合规规则，不可被模板或目标原文覆盖。
3. 当前直播间显式硬约束覆盖。
4. 当前角色域最终选中的素材包必用、备选和排他规则。
5. 素材全局硬约束。
6. 当前直播间软偏好和素材全局软偏好。
7. 主内容模板的节目阶段和节奏。
8. 次要内容模板已采用的模块贡献。
9. 生成模型默认策略。

这不是简单的“后者覆盖前者”。同一优先级的硬规则必须同时满足；无法同时满足时报告冲突。只有显式的角色域“替换”或稳定 `constraint_key` 覆盖可以移除既有规则。

## 12. 数据对象

### 12.1 新增对象

- `AssetConstraintProfile` / `AssetConstraintRevision`：素材全局约束版本。
- `AssetVersion` / `Rendition` / `RightsGrant`：逻辑素材版本、技术表现和可执行权利范围。
- `AssetNamedRegion`：素材提供的命名区域和锚点。
- `AssetGroup` / `AssetGroupMember`：人工多对多分组。
- `AssetGap` / `AssetGapResolution`：可追踪素材缺口及处理证据。
- `MaterialPack` / `MaterialPackRevision`：素材包及不可变发布版本。
- `MaterialPackEntry`：素材、分类包、使用强度、次数和适用范围。
- `MaterialPackExclusivity`：按业务角色生效的排他规则。
- `ContentStrategyTemplateProjection`：`content-strategy.v2` 发布投影。
- `ContentProject` / `ContentProjectRevision`：跨视频和直播间的内容业务聚合根及确认输入。
- `ProductionVariant` / `ProductionVariantRevision`：`live_room` 或 `rendered_video` 分支及不可变输入。
- `LiveRoomConfiguration` / `LiveRoomConfigurationRevision`：live_room 分支的可编辑配置和固定输入。
- `LiveRoomMaterialSelection`：包、分组和零散素材的来源选择。
- `LiveRoomAssetOverride`：直播间私有素材约束覆盖。
- `ResolvedMaterialSnapshot`：展开、去重、合并后的有效素材白名单。
- `TemplateContributionDecision`：主次模板的模块贡献与来源。
- `StoryBrief` / `StoryBriefRevision`：可持续业务身份与不可变权威内容输入。
- `FactCitation`：事实性语句到事实卡修订、字段和来源证据的引用。
- `ContentProgramRevision` / `ProgramSegment`：节目语义结构及 ScriptBlock 采用区间。
- `ShotListRevision` / `Shot`：两个生产分支共享的最小导演镜头模型。
- `ShotProjectionLink`：Shot 到 MaituScene/Layer 或 TimelineSegment 的显式投影关系。
- `ProductionTimeline` / `TimelineSegment`：面向成片的确定性剪辑时间轴。
- `TimeMapping`：编辑有理数时间、媒体 PTS 和 LiveSession 毫秒时钟之间的版本化转换。
- `Release` / `ReleaseManifest` / `ReleaseApproval` / `DeliveryAttempt`：发布聚合、不可变交付清单、批准和外部交付证据。
- `ContentExposureEvent`：真实会话中实际激活/可见/可听内容的 served log。
- `ContentTimelineSpan`：直播媒体时钟上的内容区间及 Shot/ProgramSegment/ScriptBlock 映射。
- `MetricDefinition` / `MetricDefinitionRevision` / `DataContract`：业务指标语义、版本和数据质量契约。
- `AttributionRun` / `AttributionResult`：版本化归因计算和实体效果结果。
- `PerformanceProfile` / `AssociationalEstimate` / `CausalEstimate`：按证据等级分离的表现与效应结果。
- `DecisionLog`：推荐/选材时的候选集、特征、策略、propensity 和最终决策。
- `FeatureSnapshot` / `LearningPolicy` / `EffectEligibilityPolicy`：点时特征与效果证据准入规则。
- `Experiment` / `ExperimentRevision` / `ExperimentAssignment` / `ExperimentAnalysis`：随机或准实验设计、分流和可信分析。
- `Role` / `RoleStrategy` / `RoleStrategyRevision` / `RoleEvaluation`：角色契约、版本化策略和基于合格证据的评价。
- `BroadcastSchedule` / `BroadcastScheduleRevision` / `GoLiveAuthorization`：长期排播和短期、可撤销的开播授权。
- `WorkflowRun` / `StepRun` / `HumanTask` / `ArtifactRef`：跨域任务控制面。
- `PolicyDecision` / `ExecutionAuthorization`：版本化策略决策和提交时能力授权。
- `ProtectedResourceRegistry`：目标房间、账号和外部资源的版本化保护/只读登记。
- `DataQualityIncident` / `DeletionRun`：数据合同异常和删除传播运行。
- `GraphProjectionVersion`：关系事实到 Neo4j/检索层的可重建投影版本。

### 12.2 复用对象

- `Asset`、`AssetFile` 和麦兔素材绑定继续作为素材身份底座。
- `ProductFactCard` 继续作为事实来源，但直播间配置改为引用多个批准版本。
- `InventorySnapshot` 继续作为麦兔资源现场的不可变输入。
- `CaptureSession`、`AnalysisRun`、模板修订和发布表继续承载外部直播研究。
- `WorkbenchRun`、计划修订、素材需求、preflight、执行任务和 `MT-EXEC-*` 作为统一 WorkflowRun 的兼容投影继续可读。
- `Script` / `ScriptBlock` 继续作为剧本底座，增加修订、来源、ProgramSegment 和 Shot 关联，不创建第二套剧本表。
- `LiveRoomBlueprint`、现有场景数据、`LayerBlueprint`、`BuildPlan`、执行 lease/checkpoint/reconcile/finalize 继续承载麦兔目标状态与执行证据；新契约使用 `MaituSceneBlueprint` 消除歧义。
- `VideoProductionJob` 及其 story/script/shot-list/asset/voice/subtitle/render/QC artifacts 继续承载成片任务；时间轴作为新增确定性 artifact 接入。
- `LiveSession`、JD 指标会话/样本和录屏互动摘要继续作为运营观测底座。

### 12.3 不能复用的旧概念

- `assets.duplicate_group` 是重复文件检测结果，不是用户素材分组。
- `assets.layer_left/top/width/height/z_index` 是历史观察或单次摆放，不是可复用全局约束。
- `MaituMaterialSlot` 描述具体直播间槽位，不能代替素材自身约束。
- `layout-hypothesis.v1` 不能冒充内容策略模板。

## 13. API 契约方向

### 13.1 素材

在现有 `/api/assets` 基础上增加：

```text
GET/PUT  /api/assets/{asset_code}/constraint-profile
GET      /api/assets/{asset_code}/constraint-revisions
GET      /api/assets/{asset_code}/versions
GET      /api/assets/{asset_code}/renditions
GET/POST /api/assets/{asset_code}/rights-grants
POST     /api/rights-grants/{grant_code}/revoke
GET      /api/rights-grants/{grant_code}/impact
GET      /api/assets/{asset_code}/effects
GET      /api/assets/{asset_code}/relations
POST     /api/asset-groups
GET/PATCH/DELETE /api/asset-groups/{group_code}
PUT      /api/asset-groups/{group_code}/members
POST     /api/material-packs
POST     /api/material-packs/{pack_code}/revisions
POST     /api/material-packs/{pack_code}/revisions/{revision}/publish
POST     /api/material-packs/resolve
GET/PATCH /api/asset-gaps/{gap_code}
POST     /api/asset-gaps/{gap_code}/resolve
```

`resolve` 接收总体包、每个角色域模式、分类包、分组和零散素材，返回版本固定前的有效白名单、来源、规则、排他冲突和指纹。

### 13.2 内容模板

复用 `/api/live-observations` 的来源、录屏和分析任务接口。现有 `room-templates` 增加：

```text
template_kind = content_strategy
contract_version = content-strategy.v2
target_category
source_session_codes[]
content_strategy
content_readiness
layout_fidelity
buildability
layout_reference
```

旧 `layout-hypothesis.v1` 请求和响应继续可读，不原地改写。发布接口根据 contract version 生成对应投影。

### 13.3 直播间配置

先增加载体无关的内容与生产分支资源：

```text
POST/GET /api/content-projects
GET/PATCH /api/content-projects/{project_code}
POST      /api/content-projects/{project_code}/parse-brief
POST      /api/content-projects/{project_code}/confirm
POST      /api/content-projects/{project_code}/generate-script
POST      /api/content-projects/{project_code}/generate-shot-list
POST/GET  /api/content-projects/{project_code}/variants
POST      /api/production-variants/{variant_code}/confirm
POST      /api/production-variants/{variant_code}/generate
GET       /api/production-variants/{variant_code}/lineage
```

现有 `/api/maitu/workbench/configurations` 保留为 live_room variant 兼容接口，并逐步收敛为：

```text
POST   /configurations
GET    /configurations
GET    /configurations/{configuration_code}
PATCH  /configurations/{configuration_code}
POST   /configurations/{configuration_code}/resolve-materials
POST   /configurations/{configuration_code}/confirm-inputs
POST   /configurations/{configuration_code}/generate
POST   /configurations/{configuration_code}/authorize-execution
POST   /configurations/{configuration_code}/execute
POST   /configurations/{configuration_code}/clone
POST   /configurations/{configuration_code}/asset-overrides/{asset_code}/promote
GET    /configurations/{configuration_code}/runs
GET    /configurations/{configuration_code}/lineage
```

`generate` 只能引用已确认 variant 修订。自动推进到 preflight 后必须取得目标绑定的 ExecutionAuthorization 才能执行；`plan_only=true` 永远不请求授权。

所有写接口使用预期修订号或 idempotency key，避免重复确认、重复生成和重复创建执行任务。

### 13.4 知识、成片、运营与学习

在复用现有事实、视频生产和直播观测 API 的前提下，补充以下稳定资源：

```text
GET      /api/knowledge/facts/{fact_code}/lineage
GET      /api/knowledge/search
POST     /api/video-productions/from-story-brief
GET/PUT  /api/video-productions/{job_code}/timeline
POST     /api/video-productions/{job_code}/render
GET      /api/video-productions/{job_code}/quality-report
POST     /api/production-variants/{variant_code}/release-candidates
POST     /api/releases/{release_code}/approve
POST     /api/releases/{release_code}/deliver
POST     /api/releases/{release_code}/revoke
GET      /api/releases/{release_code}/manifest
GET      /api/releases/{release_code}/delivery-attempts
POST     /api/operations/live-sessions
POST     /api/operations/live-sessions/{session_code}/ingest
POST     /api/operations/live-sessions/{session_code}/exposures
GET/PUT  /api/operations/live-sessions/{session_code}/content-timeline
POST     /api/operations/attribution-runs
GET      /api/operations/attribution-runs/{run_code}/results
GET      /api/metrics/definitions
POST     /api/metrics/definitions/{metric_code}/revisions
GET/POST /api/data-contracts
POST     /api/experiments
POST     /api/experiments/{experiment_code}/assignments
GET      /api/experiments/{experiment_code}/analysis
GET      /api/learning/performance-profiles
GET      /api/learning/effect-estimates
POST     /api/learning/effect-estimates/{estimate_code}/approve
POST     /api/learning/effect-estimates/{estimate_code}/revoke
GET      /api/workflow-runs/{run_code}
POST     /api/workflow-runs/{run_code}/cancel
GET/POST /api/human-tasks
POST     /api/execution-authorization-requests
GET      /api/execution-authorizations/{authorization_code}
GET/POST /api/broadcast-schedules
POST     /api/broadcast-schedules/{schedule_code}/request-go-live-authorization
POST     /api/go-live-authorizations/{authorization_code}/revoke
POST     /api/deletion-runs
GET      /api/graph/entities/{entity_type}/{entity_code}
POST     /api/graph/projections/rebuild
```

采集写入接口接收 `source_event_id`、来源系统、事件时间、接收时间、schema version 和幂等键。归因、效果证据、图谱重建都只读不可变输入快照，任务完成后返回方法/代码版本和输出指纹。请求接口只能请求策略评估，不能由调用方自行铸造授权；GoLiveAuthorization 的请求 API 在 capability 关闭时稳定返回策略拒绝，不能因路由存在就推断功能已启用。

## 14. 状态机

### 14.1 素材包

```text
draft -> published -> superseded
                  -> archived
```

只有 `published` 可被直播间配置解析。新发布版本把旧发布版本标为 `superseded`，但旧快照仍可读取。

### 14.2 内容策略模板

```text
draft -> review_required -> published -> superseded
      -> rejected                     -> archived
```

发布需要至少一个有效内容模块、来源证据、品类、整体审核说明和通过事实去除检查。近似布局缺失不阻止内容模板发布。

### 14.3 内容项目与生产分支

```text
content project revision:
draft -> brief_ready -> confirmed -> superseded

production variant revision:
draft -> input_confirmed -> generating -> quality_blocked
                                 -> release_candidate -> released
                                 -> failed
```

配置发生修改不会倒退旧运行或 release，只产生新的修订。`quality_blocked` 必须包含机器可读规则码和人工可读处理建议。

### 14.4 成片、归因和效果证据

```text
video production:
draft -> queued -> running -> quality_failed
                         -> completed
                         -> failed

attribution run:
queued -> validating -> computing -> review_required -> published
                   -> insufficient_data       -> failed

performance/effect evidence:
candidate -> eligible -> approved -> superseded
          -> rejected
approved -> review_required -> approved
                            -> revoked
```

`quality_failed` 的渲染产物保留供诊断但不可发布。`insufficient_data` 不是失败。PerformanceProfile 只能展示/建议；只有达到策略要求证据等级、`approved` 且未过期的 AssociationalEstimate/CausalEstimate 才能按受控权重进入第 5.6 节排序。

### 14.5 Workflow、release、实验与授权

```text
workflow run:
queued -> running -> waiting_for_human -> running -> succeeded
                -> blocked / canceled / failed

release:
candidate -> validating -> approval_required -> approved -> delivering -> delivered
                    -> rejected                          -> delivery_failed
approved / delivery_failed / delivered -> revoked

delivery attempt:
queued -> executing -> readback_pending -> succeeded
                  -> reconcile_required -> succeeded / failed
                  -> failed / canceled

human task:
open -> claimed -> completed
              -> rejected / canceled / expired

experiment:
draft -> design_review -> ready -> running -> stopped -> analyzing -> concluded
                     -> rejected       -> aborted

execution authorization:
issued -> consumed
      -> expired / revoked
```

WorkflowRun 终态不等于 release 已交付；release delivered 也不等于发生实际曝光。GoLiveAuthorization 与普通 ExecutionAuthorization 分属不同 capability，前者在启用正式排播阶段前始终无法签发。

## 15. 安全、审计和可复现性

- 内部可信运营不等于无审计。保存约束、发布素材包、发布内容模板、提升房间覆盖、确认输入和执行都记录操作者与时间。
- 所有配置修订记录事实卡、inventory、内容模板、素材包、素材约束和解析结果的版本及指纹。
- 原始目标、模板例句和外部转写都是不可信数据，使用结构化 schema 和明确边界进入模型。
- 模板来源句不得成为目标商品事实；生成后执行事实来源扫描。
- Browser-use 仅执行 BuildPlan 白名单动作，每个有副作用的操作回写现场身份、前后状态和截图证据。
- 目标房间现场指纹从 preflight 到执行必须保持一致；变化时停止并重新 preflight。
- 不确定某个写操作是否已生效时先 reconcile，不自动重放。
- `/DATA` 路径、麦兔素材身份和本地软链接关系继续由现有可复现性脚本校验。

### 15.1 统一版本清单与指纹

每个生产或分析运行必须生成 `RunManifest`，至少固定：输入实体修订、文件校验和、inventory/素材白名单/约束/权利快照、模板投影、事实卡、StoryBrief/Script/ProgramSegment/Shot 修订、ProductionVariant、模型与提示模板、代码提交、容器/系统依赖、随机种子、工具适配器、schema version 和配置。`input_fingerprint` 由规范化清单计算；输出 artifact、BuildPlan、时间轴、release、归因结果和图谱投影分别计算内容指纹。

同一清单和可确定组件应产生等价结构结果；外部模型或 Browser-use 无法字节级确定时，必须至少能够重放输入、保留原始响应/现场证据并解释差异。任何依赖更新都创建新运行，禁止覆盖旧 artifact。

### 15.2 统一门禁顺序

所有生产分支按以下门禁顺序执行并保存每项结果：

1. 身份与版本完整性：实体存在、修订不可变、校验和匹配。
2. 授权与事实安全：许可有效、事实批准、敏感/合规规则通过。
3. 输入可信边界：原始目标、外部转写、OCR、互动和模板例句按数据处理，不能覆盖系统指令。
4. 结构与引用完整性：schema、必讲内容、事实引用、ScriptBlock/ProgramSegment/Shot/载体投影/素材来源边齐全。
5. 执行能力与约束：白名单、麦兔绑定、硬布局/音频约束和目标现场 preflight 通过。
6. 分支质量：麦兔回读一致性或视频编解码、黑帧、静音、响度、字幕安全区等检查通过。
7. 证据完整性：manifest、日志、操作结果、截图/媒体、QC 和输出指纹达到要求。

门禁结果统一为 `pass / warning / blocked / not_applicable`，包含稳定规则码、规则版本、证据引用和处理建议。只有 `blocked` 停止该生产分支；warning 不得被 UI 隐藏。

### 15.3 权限、隐私与外部副作用

- 生产编辑、模板/事实发布、效果估计批准、执行麦兔草稿和图谱重建使用独立能力权限；内部用户也执行最小权限。
- Cookie、token、个人信息和原始互动 payload 不进入提示、截图公开索引、效果证据或图谱；日志按字段脱敏并执行保留/删除策略。
- 所有外部副作用经过受控适配器、目标 allowlist、操作 schema 和审计；生成模型无网络凭据且不能直接调用 Browser-use。
- “正式开播”与排播授权在当前系统中没有可执行 API、BuildPlan 操作或隐式 UI 路径。
- 参考房间、生产禁写对象和只读来源维护在版本化 `ProtectedResourceRegistry`，preflight、授权服务和 Worker 都必须独立检查。
- 外部文本、OCR、ASR、网页和工具结果携带 `untrusted_external` 数据标签；任何摘要、模板或模型输出不能自动移除该标签，只有确定性抽取加人工/规则批准才能产生 `approved_fact`。
- 每个副作用在提交时重新调用策略决策点，校验主体、目标、动作、plan/release hash、现场指纹、授权过期时间和策略版本；preflight 通过不能替代 commit-time authorization。

### 15.4 标准兼容与证据完整性

- 运行血缘提供 OpenLineage 兼容的 Job/Run/Input/Output/Facet 投影；领域对象仍由关系库管理，不把 OpenLineage 当业务数据库。
- API、队列、worker、模型调用和外部适配器传播 OpenTelemetry trace/span context；trace 负责运行观测，不能替代业务 lineage。
- 构建/部署依赖采用 SLSA provenance 思路记录来源和构建环境；输出视频评估生成 C2PA Content Credentials，保留 ingredient 和 AI 生成声明。
- 图片/视频 sidecar 对齐 IPTC 权利、技术和 AI 生成元数据；平台专有字段保存在命名空间扩展中。
- 关键 manifest、release、授权、操作结果和归因发布使用服务端签名或 append-only hash chain；对象存储启用版本/保留锁定时，数据库只保存 URI、校验和和签名状态。
- 每类证据定义 owner、访问级别、保留期限、legal hold 和销毁证明。校验和只能证明内容一致，不能证明声明真实；UI 必须分别显示“完整性已验证”和“业务事实已批准”。

## 16. 现状差距

当前项目已有主链路基础，但还缺少：

1. 素材只有用途分类和单值历史几何，没有版本化约束、命名区域和关系规则。
2. 没有用户素材分组和多对多成员管理。
3. 没有总体/分类素材模板包、必用项、备选项和角色域排他。
4. 当前 inventory 是全量快照，没有直播间选择子集和有效素材快照。
5. 当前 Workbench Run 只支持一份事实卡、一个参考模板，且把内容项目、载体配置、运行和发布混在一起。
6. 缺少跨载体 `ContentProject`、`ProductionVariant`、最小 ProgramSegment/ShotList 和明确的 stale 传播。
7. 当前模板聚合以 `canvas/scenes/components/audio_policy` 为中心，不能表达完整话术策略；内容 readiness、视觉 fidelity 与 buildability 仍需落库和贯通 API。
8. 当前生产提示要求口播逐句复制批准句，不能安全利用去事实化话术骨架生成新表达；任意数量次要模板也缺检索、压缩、去重和贡献追踪。
9. 没有通用约束求解契约、冲突解释、不可行诊断和求解预算。
10. Asset/文件/转码版本边界和 RightsGrant 尚未贯穿选材、衍生、发布与撤销影响分析。
11. 当前生成、preflight 和写入需要人工逐步点击，缺统一 WorkflowRun/HumanTask、提交时授权和“无阻断自动写草稿”的编排器。
12. Worker 需要补齐安全的 `rename_live_room`、配置级自动推进、操作回读和未知结果 reconcile 证据。
13. 当前 `/maitu/` 与 `/live-research/` 是两个工作台，数据清洗、素材分析、内容项目和生产入口割裂。
14. DesignBrief 尚未投影为正式 StoryBrief/Script/ProgramSegment/ShotList 修订，来源边和角色策略标记不完整。
15. Blueprint/BuildPlan 虽已有执行基础，但 Shot 投影、逐层来源、现场回读、ReleaseManifest 和证据完整率尚未形成统一契约。
16. 成片任务已有阶段、artifact、FFmpeg、TTS、字幕和 QC 基础，尚缺 OTIO 兼容 ProductionTimeline、RationalTime、release/delivery 与内容修订关联。
17. 已有录屏互动摘要和 JD 指标采集，但缺实际 ContentExposureEvent、Metric Catalog/DataContract、event-time 水位、版本化归因和证据分级。
18. 归因尚未区分描述、关联和因果，缺实验分配、SRM/护栏、DecisionLog、point-in-time 特征与反馈回路治理。
19. 向量检索已有实现基础，图关系仍缺稳定本体、outbox、采用门槛和可重建投影版本。
20. 缺明确的保留/删除、隐私、SLO、容量、成本、灾备和 error budget；全局 Console 也缺内容项目、发布、治理、运营与学习工作区。

## 17. 迁移策略

1. 数据库只做追加迁移，不修改旧 migration 文件。
2. 旧素材几何字段保留为观察证据，不自动提升为全局硬约束，避免把某次摆放误当通用规则。
3. 旧 `duplicate_group` 保留原语义，新用户分组使用独立表。
4. 旧 `layout-hypothesis.v1` 模板和发布投影保持只读；只有新清洗结果或人工新修订使用 `content-strategy.v2`。
5. 旧 Workbench Run 继续可查并投影为 legacy WorkflowRun；不能可靠恢复的输入显示 `unknown`，不反向猜测。
6. 缺少内容根的旧 StoryBrief/VideoProductionJob 可挂到标记为 `legacy_import` 的合成 ContentProject；原始主键、时间和缺失字段始终保留。
7. 旧 LiveRoomConfiguration 映射为 live_room ProductionVariant；历史 Scene 可映射为 MaituScene，但没有明确证据时不伪造 Shot 或 ShotProjectionLink。
8. 新 release 只为未来发布或能证明精确 artifact/BuildPlan、批准和目标回读的历史交付创建。不能证明的历史对象标为 `legacy_delivery_unknown`，不伪造 ReleaseManifest。
9. 历史 LiveSession 没有实际展示日志时可以保留计划内容和录屏推断，但不得回填成确定性 ContentExposureEvent；所有历史归因显示证据降级。
10. 新直播间配置可以引用现有批准事实卡和 inventory 快照，但首次确认时必须生成不可变 rights/constraint/material snapshot。
11. 现有 JD 指标、互动和录屏数据通过版本化 adapter 映射；无法确认 event time、去重键或指标口径的数据进入隔离或 descriptive-only，不静默补零。
12. 原始录屏和个人互动执行第 26.2 节保留策略；迁移不会因为旧文档写过“永久保留”而无限延长个人数据保留。
13. 图谱和向量索引从关系库/outbox 重建；迁移期间双读对账，禁止以派生索引反写覆盖事实源。
14. 新领域路由达到功能等价、深链迁移和审计验收后再重定向旧视图；每个兼容接口声明 owner、source of truth 和下线条件。

## 18. 建议实现顺序

路线按可演示、可验收的纵向切片推进，不先分别建设所有“底座”。每个 Phase 都必须指定 product/engineering/data/security owner，满足上阶段退出条件，并补充本阶段容量、SLO、成本和回滚基线。在团队人数、平台适配工作量和 Phase 0 容量数据确定前不写虚假日历工期；立项时再把每个 Phase 拆成 2-6 周可验收里程碑，并按依赖和实际吞吐滚动排期。

### Phase 0：不变量与控制面

- 固化 ContentProject/Variant/Revision、Shot、Artifact、Release/Delivery/Exposure、MetricDefinition 和授权契约；建立 ADR、schema 演进与 lineage 规则。
- 实现最小 WorkflowRun/StepRun/HumanTask、RunManifest、outbox、审计、PolicyDecision 和 feature flag，补齐备份恢复基线。
- 退出条件：契约测试覆盖不可变修订、幂等、stale 传播和授权失败关闭；旧主链可通过兼容投影继续运行。

### Phase 1：内容到麦兔草稿的第一条纵向闭环

- 在 `/content/projects` 完成目标/事实 -> StoryBrief -> Script -> ProgramSegment -> ShotList；创建 live_room variant。
- 先复用当前 inventory 与确定性选材，生成 MaituSceneBlueprint/Layer/BuildPlan，通过 ExecutionAuthorization 写入一个保护规则外的空白草稿。
- 创建 release candidate、批准的 `ReleaseManifest(kind=live_room_draft)` 和现场回读，不含开播。
- 退出条件：一条内容链从输入到草稿全程可追溯，未知副作用可 reconcile，release 证据完整率 100%。

### Phase 2：素材约束与外部内容模板

- 建设 `/assets` 和 `/templates`：AssetVersion/Rendition/RightsGrant、约束/分组/素材包、缺口、求解冲突；录屏采集、清洗、内容策略模板 v2 与事实去除。
- 将主次模板和素材快照接入 Phase 1；求解器先走统一 contract，再按第 28.2 节决定实现。
- 退出条件：选材可解释、不可行可诊断、权利撤销可影响分析；reference_only 模板不能进入可执行布局门禁。

### Phase 3：同内容成片分支

- 创建 rendered_video variant，把 Shot 编译为 OTIO 兼容 ProductionTimeline，复用 TTS/字幕/FFmpeg/QC worker。
- 完成 `ReleaseManifest(kind=rendered_video)`、C2PA/IPTC sidecar 和独立麦兔上传 DeliveryAttempt。
- 退出条件：同一 ContentProject 能独立产出草稿和成片；任一分支失败不污染另一分支，帧时间、素材权利和 release checksum 可复现。

### Phase 4：真实发布、曝光与人工归因闭环

- 建设 `/production/releases` 和 `/operations`，LiveSession 绑定 ReleaseManifest，人工/录屏辅助录入 ContentExposureEvent。
- 建立第一批 MetricDefinition/DataContract、质量检查和 descriptive/associational AttributionRun；允许人工导入但不得跳过封存点和口径。
- 退出条件：一个效果结果可下钻到实际曝光、指标桶和内容对象；迟到/删除产生新 revision，历史不被覆盖。

### Phase 5：自动采集与可信关联/准实验

- 接入平台事件、watermark/backfill、退款窗口、曝光对账和数据质量 SLO；实现 point-in-time FeatureSnapshot 和 DecisionLog。
- 建设准实验评审、敏感性分析、批准/撤销与受控排序；不引入图数据库作为前置。
- 退出条件：自动排序只消费符合 LearningPolicy 的结果，离线回放无未来泄漏，漂移/撤销能停止依赖决策。

### Phase 6：随机实验与角色策略学习

- 实现 RoleStrategyRevision、Assignment、A/A、SRM、护栏和 RoleEvaluation；按 shadow -> 小流量 -> 扩量推进。
- 同时完善探索预算、propensity、并发实验命名空间和成本/安全多目标评价。
- 退出条件：至少一次预注册实验完成“策略分配 -> 实际曝光 -> 因果估计 -> 受控策略变更”且可完整重放。

### Phase 7：图谱、排播和高风险自动化

- 只有满足第 28.2 节门槛才建设 Neo4j/在线 Feature Store；否则继续使用关系库/outbox 和可重建搜索投影。
- 完成 BroadcastSchedule、GoLiveAuthorization、双人复核、紧急停止和演练后，才评审是否启用正式开播 capability。
- 退出条件：图谱可完整重建且解决已定义查询；开播在隔离环境通过安全、恢复和证据演练。未启用 capability 不影响此前业务闭环成立。

Console、任务中心、全局搜索和各一级工作区随对应 Phase 增量交付，不留到最后一次性换壳。每阶段结束都清理已达到下线条件的兼容入口，但不删除仍被使用的能力。

## 19. 验收场景

### 19.1 素材管理

- 同一素材可以加入两个分组，从任一分组移除不影响另一个。
- 总体包包含必用背景和商品，分类域可以沿用、追加或显式替换。
- 排他背景包拒绝同域包外背景，但不影响数字人和 BGM。
- 商品可以依赖背景的 `table_surface`，布局满足底边和层级关系。
- 房间覆盖只影响当前配置，提升全局后生成新约束修订。
- 必用本地素材没有麦兔绑定时阻断，普通本地候选只被排除。
- 一次同步缺失不会删除素材绑定；连续证据确认失效后新运行排除它，历史运行仍可复现。
- 选材结果可解释硬过滤、排序特征和效果证据版本；新素材没有效果样本时使用中性分。
- 缺口从 open 到 resolved 固定候选绑定与证据，不能静默改写旧配置。

### 19.2 内容模板

- 同一抖音直播间的多场录屏可以聚合为一个品类内容策略模板。
- 模板保留阶段、话术动作和去事实化例句，不把来源商品价格或促销带入发布投影。
- 没有可恢复精确图层时，内容模板仍可发布为 `content_readiness=ready`，同时明确返回 `layout_fidelity=none|approximate` 和 `buildability=reference_only`。
- 一个主模板和任意数量次要模板可以被选择，生成结果明确列出实际贡献。
- 掉帧或时钟漂移场次在统一媒体时间轴上带质量标记；发布模块能反查 ASR/OCR/画面区间和分析运行。

### 19.3 直播间生成

- ContentProject 可在没有房间 ID/标题时确认内容目标、事实和故事；live_room variant 缺少标题、房间 ID 或目标现场时不能确认载体输入。
- 总体包、分类包、分组和零散素材解析后形成可解释、去重的硬白名单。
- 生成器不会使用白名单外素材，不会使用未批准商品事实。
- 必用素材缺失或硬约束无解时阻断；普通效果素材不足时继续并生成需求单。
- 目标时长偏差超过约 50% 时显示警告，不因单一时长偏差停止。
- 普通空白草稿 preflight 通过后自动写入期望标题、场景、素材和脚本。
- 普通非空、已开播或现场指纹变化的房间拒绝执行；ADR-0003 白名单测试房仅在离线、显式确认且现场指纹未变化时允许整房重建。
- BuildPlan 和 Worker 永远不产生或点击正式开播动作。
- 普通房间完成后修改必须复制配置并绑定新的空白房间，旧运行证据保持不变；测试覆盖每次都产生独立 Job、reset plan、BuildPlan 和回读证据。
- 内容确认后产生不可变 StoryBrief/Script/ProgramSegment/ShotList 修订；每个事实句、Shot、MaituScene、Layer 和操作都能沿来源边回溯。
- 不确定写操作先 reconcile；workflow succeeded 不能替代现场回读、`ReleaseManifest(kind=live_room_draft)` 和证据完整率门禁。

### 19.4 成片生产

- 同一 StoryBrief/Script 可以独立产生麦兔草稿和竖屏成片，任一分支失败不污染另一个分支状态。
- 时间轴使用稳定 segment code、RationalTime/TimeRange，并通过 TimeMapping 导出会话毫秒半开区间；能够回溯 Shot、ScriptBlock、素材文件与音频/字幕 artifact。
- 同一 RenderManifest 重试可解释工具、滤镜、输入和输出差异；黑帧、静音、字幕安全区或必讲覆盖阻断时成片不可发布。
- 渲染完成只产生 release candidate；批准、渠道交付、麦兔上传和实际曝光是互不替代的独立状态。

### 19.5 运营归因

- 重复平台事件按来源幂等；watermark、删除、退款和 backfill 有明确语义，不同指标口径不可静默合并。
- LiveSession 绑定精确 ReleaseManifest，实际曝光区间能映射 Shot、载体投影、ScriptBlock、商品、模板模块和在场素材，并显示时间对齐质量。
- 样本或对齐不足时返回 `insufficient_data`；发布结果能下钻到曝光、指标桶、内容区间、封存点、方法和代码版本。
- 时间窗相关性不得显示为因果；实验存在 SRM、护栏失败或分配/曝光不一致时不能发布随机实验结论。

### 19.6 知识图谱与效果学习

- 删除 Neo4j/Milvus 派生数据后可以从关系库封存点重建相同投影版本，投影滞后不会覆盖事实源。
- 推断关系与确定性关系明显区分；检索命中未批准事实时不能进入生产。
- 单场高 GMV 不产生可用效果估计；只有满足 LearningPolicy 的批准结果才影响软排序，且不能放宽硬约束。
- 决策日志保存点时特征、候选集、排除原因、propensity、实际 release/曝光；离线训练无法读取决策后的未来数据。
- 基于效果再生产创建新内容/variant 修订，固定来源估计并保留探索配额和后续评估。

### 19.7 安全、版本与可复现性

- 任一运行都能导出完整 RunManifest、规则结果、输入/输出指纹、模型/提示/代码/工具版本和证据引用。
- 现场、输入修订或依赖指纹变化会停止旧执行或使下游 artifact stale，不允许在旧版本上继续写入。
- 敏感凭据和原始个人互动数据不进入提示、图谱、效果证据或公开证据；所有副作用使用能力权限和 allowlist。
- 每个副作用在 commit 时复核短期、目标/plan hash 绑定的 ExecutionAuthorization；授权不可跨能力复用。
- 当前阶段所有 API、BuildPlan 和 Worker 路径均无法构造正式开播动作；未来只有独立 GoLiveAuthorization capability 通过评审后才可启用。

### 19.8 控制面、治理与非功能验收

- WorkflowRun 取消、timeout、等待人工、Worker 崩溃和未知外部结果都能恢复或对账，不产生重复副作用。
- release 的 lineage/校验和/批准/权利完整率为 100%；workflow 成功、交付成功和实际曝光在状态与 UI 中明确分开。
- 原始个人数据到期删除会传播 tombstone 到投影；legal hold 有 owner 和到期，权利撤销会阻止新交付并列出受影响 release。
- 在目标峰值 2 倍压测下 backpressure 生效；SLO、成本配额、kill switch、PITR 恢复和投影重建演练均有可审计结果。

## 20. 成片渲染、剪辑与时间轴

### 20.1 生产分支与入口

成片生产复用现有 `VideoProductionJob`，入口有两种：

1. 从 ContentProject 的已确认 StoryBrief/Script/ShotList 创建 rendered_video ProductionVariant。
2. 从已有 live_room variant 派生 rendered_video variant，显式选择要复用的内容修订、Shot 和素材版本。

成片和麦兔草稿互不作为成功前置条件。一个分支失败不回滚另一个分支；二者都记录相同的内容根修订，便于后续比较“同内容、不同载体”的效果。

### 20.2 确定性生产时间轴

`ProductionTimeline` 是渲染的权威输入，不用临时 FFmpeg 参数代替。权威序列化采用或严格映射 OpenTimelineIO：Timeline -> Stack -> Track -> Clip/Gap/Transition，并保留 schema version。内部时间使用 `RationalTime(value, rate)` 和 `TimeRange`，不能只用毫秒表达帧边界、源素材区间或变速。

`TimelineSegment` 是业务投影，至少保存：

```text
segment_code / track_kind / timeline_range / source_range / playback_rate
program_segment_code / script_block_codes[] / shot_code
asset_code / asset_file_checksum / transform / crop / opacity
transition_in / transition_out / volume / ducking
voice_artifact_ref / subtitle_cue_refs[]
source_revision_refs[] / segment_fingerprint
```

轨道至少支持画面、叠加层、数字人口播/配音、BGM、音效和字幕。片段不能出现未定义重叠、负时长、错误 timebase 或越过源文件 available range。对运营数据暴露的毫秒区间必须通过版本化 TimeMapping 从编辑时间计算。人工表单化调整创建时间轴新修订并使旧渲染和 release candidate 过期。

### 20.3 生产阶段与 artifacts

继续使用现有阶段：brief generation、script generation、shot planning、asset selection、voice synthesis、subtitle generation、rendering、quality check。`shot planning` 读取固定 ScriptRevision 并产出 ShotListRevision；时间轴编译器再把 Shot 投影为 Clip/Track/Transition。

每个阶段读取固定输入 artifact，产出内容寻址 artifact 和 manifest，失败可从最近通过的阶段重试。标准产物包括 StoryBrief、Script、ShotList、asset plan、ProductionTimeline、voice、ASS 字幕、poster、render log、quality report 和最终 video。

### 20.4 渲染和质量门禁

默认发布规格为 1080x1920、H.264/AAC；具体编码参数作为版本化 RenderProfile，不硬编码在业务逻辑。渲染使用结构化 FFmpeg 命令构建器，命令、输入校验和、滤镜图、工具版本和资源用量写入 `RenderManifest`。

质量检查至少覆盖 ffprobe 可解码性、分辨率/帧率/时长、音视频同步、黑帧、冻结帧、静音、削波/响度、字幕安全区与可读时长、结尾截断、必讲 ScriptBlock 覆盖、素材许可和文件校验和。阻断项失败时产物保留但不可发布；人工豁免必须限定产物修订并记录理由。

通过质量门禁只产生 `release_candidate`。批准后创建 `ReleaseManifest(kind=rendered_video)`，执行资产库登记、C2PA/IPTC sidecar 生成和目标渠道交付；麦兔上传是独立 DeliveryAttempt，必须回读目标素材身份和校验信息，不能把本地渲染完成误记为“已上传”。

## 21. 运营数据回流、指标与内容归因

### 21.1 发布、真实曝光与 LiveSession

`LiveSession` 是一次真实直播或投放的运营聚合根，但“计划使用了什么”不能作为归因事实。每场会话必须绑定一个不可变 `ReleaseManifest`；平台实际部署回读产生 `DeliveryAttempt`，真正被用户看到的内容由 append-only `ContentExposureEvent` 记录。归因优先读取实际曝光，只有缺少曝光日志且证据策略允许时，才用回读现场或录屏识别补偿，并降低证据等级。

`ContentExposureEvent` 至少包含：平台与外部会话、release/variant/revision、开始与结束事件时间、`program_segment_code`、`shot_code`、载体投影对象、在场素材/商品/CTA、策略分配、来源类型和置信度。切场、断流、重复播出、临时人工替换必须产生新事件或修正事件，禁止回写覆盖历史。一个 `LiveSession` 在同一时刻只能有一个有效发布曝光；切换 release 要显式记录边界。

### 21.2 事件时间、内容时间线与数据封存

所有平台事件使用统一 envelope：

```text
source_system / source_event_id / schema_version
event_time / processing_time / source_timezone
session_code / subject_pseudonym? / payload_ref
ingest_batch / checksum / quality_flags[]
operation = upsert|delete / tombstone_reason?
```

采集按 `(source_system, source_event_id)` 幂等。每个来源定义 watermark、允许迟到窗口和退款/撤销窗口；窗口内重算未封存桶，窗口后只能通过 backfill 批次和新修订修正。`processing_time` 只能用于运维，不能替代 `event_time` 做内容对齐。原始事件、标准事件、汇总桶和已发布指标分别记录封存点，任何结果都能指出读取了哪个封存点。

`ContentTimelineSpan` 由曝光事件投影，使用 `[start_ms, end_ms)` 会话时间映射到 ProgramSegment、Shot、ScriptBlock、商品、模板模块、素材/图层和 CTA。`TimeMapping` 保存 release 时间、平台事件时间、录屏媒体时间之间的偏移、漂移模型和校正证据。覆盖率、断流、漂移和无法识别区间必须量化；未达到策略阈值时只能给出会话级结果或 `insufficient_data`。

### 21.3 Metric Catalog 与 DataContract

标准指标按曝光、停留/留存、互动、点击、加购、成交、退款和内容质量分族。每个 `MetricDefinitionRevision` 必须声明：owner、业务含义、计算 grain、单位/币种、分子、分母、事件时间字段、时区/业务日、允许维度、去重键、退款/撤销窗口、空值规则、异常值规则、schema 兼容范围和质量 SLO。同名但定义或粒度不同的指标必须使用不同 revision，禁止静默拼接。

每个来源适配器绑定版本化 `DataContract`：字段 schema、主键、更新/删除语义、event-time 语义、迟到策略、枚举映射、敏感级别、预期量级和 owner。契约检查覆盖完整性、唯一性、引用完整性、时效、分布漂移和 source-to-standard reconciliation；不合格批次进入隔离区，不能偷偷产生零值。

### 21.4 归因结果与证据等级

系统明确区分三类可学习结果和四级证据：

- `PerformanceProfile`：描述性统计，回答“发生了什么”，不估计影响。
- `AssociationalEstimate`：关联或经明确假设调整的估计，回答“哪些对象与结果共同变化”，不能声称因果。
- `CausalEstimate`：来自合格随机实验或通过方法评审的准实验，回答限定适用域内的增量效果。
- `evidence_tier = descriptive | associational | quasi_experimental | randomized`，等级由方法和证据决定，不能由人工直接抬高。

`AttributionRun` 固定输入封存点、ReleaseManifest、曝光日志修订、指标定义、观察/归因/退款窗口、基线、纳入排除规则、时间对齐策略、方法实现与代码版本。结果可按会话、曝光区间、ProgramSegment、Shot、ScriptBlock、模板模块、素材、商品和 CTA 聚合，保存分子/分母、样本量、场次数、效应或统计量、区间估计、数据质量、假设、限制和 lineage。

时间窗或“切换前后”分析默认只能产生 descriptive/associational 证据。准实验必须保存处理分配机制、可比性诊断、平行趋势或相应识别假设、敏感性分析和负向对照。无法建立可靠反事实时，UI 和 API 均不得使用“提升、带来、导致”等因果表述。

### 21.5 实验治理

`ExperimentRevision` 在启动前固定：假设、随机化单位、处理/对照策略、主指标、护栏指标、最小可检测效应、样本量/功效、运行窗口、曝光定义、排除规则、并发实验命名空间、停止规则和分析计划。分配必须先于曝光，由稳定哈希或实验服务产生并记录 `ExperimentAssignment`；实际展示仍以 `ContentExposureEvent` 为准。

实验平台必须支持 A/A 校验、样本比例不匹配（SRM）检测、分配与曝光不一致检测、跨设备/跨会话污染、干扰效应、重复度量和退款延迟。不得在观察结果后任意改主指标、样本范围或提前停止；紧急护栏停止记录为 `aborted`，不能包装成成功结论。每次分析保存预注册版本、统计方法、置信区间、多重比较处理和完整排除漏斗。

### 21.6 发布、修正与回写

归因结果先进入 `review_required`。指标契约、曝光完整性、时间对齐、异常流量、最小样本和方法检查通过后才能 `published`；修正创建新 revision 并 supersede 旧版。自动排序只允许消费满足 `LearningPolicy` 的 approved 且未过期结果，策略按目标领域明确最低证据等级；原始相关性、单场高 GMV 或模型自评分不能直接驱动生产。

## 22. 知识图谱与检索投影

### 22.1 事实源和投影边界

PostgreSQL 领域表、不可变修订和证据 artifact 是唯一事实源。领域变更通过 transactional outbox 产生投影事件；Neo4j 图谱和向量索引携带 `GraphProjectionVersion`、ontology version 和 embedding version，可丢弃并从封存点重建。投影延迟或失败不阻断事实写入，但查询结果必须显示投影水位和陈旧状态。

### 22.2 节点与关系本体

本体覆盖 Asset/AssetVersion/Rendition/RightsGrant、Product/FactCard/FactClaim、SourceEvidence、ContentStrategyTemplate/Module、ContentProject、StoryBrief、Script/ScriptBlock、ProgramSegment、Shot、ProductionVariant、MaituScene/Layer、TimelineSegment、BuildPlan/Operation、ReleaseManifest/Exposure、LiveSession、MetricDefinition、PerformanceProfile、AssociationalEstimate、CausalEstimate、RoleStrategy 和 Experiment。

核心有向关系包括：

```text
DERIVED_FROM / VERSION_OF / CITES / SUPPORTS
USES_ASSET / REQUIRES_ROLE / SATISFIES_CONSTRAINT
PROJECTED_AS / REALIZED_AS / EXECUTED_AS / RELEASED_AS
OBSERVED_IN / EXPOSED_DURING / MEASURED_BY / ESTIMATED_EFFECT_ON
ASSIGNED_STRATEGY / SUPERSEDES / REVOKES
```

每条边保存来源表主键、修订、有效时间、建立方式、置信度和证据引用。确定性、人工断言、模型推断和统计估计使用不同 `assertion_kind`；查询与 UI 不得把推断或相关性显示为已核验事实。

### 22.3 查询、检索和写入边界

图谱支持来源追溯、变更影响、权利撤销影响、相似组合、缺口候选和“某效果结论由哪些曝光、内容和证据产生”等稳定查询。向量索引保存模型、chunk/预处理版本和源实体修订；召回后必须回事实源校验当前授权、状态、权利和硬约束。

知识搜索采用 lexical + vector + graph rerank，分开展示事实、历史结果、建议和推断。检索分数不是发布资格，图谱/向量层不能反写事实对象；生产事实仍必须引用批准的 FactCardRevision，选材仍先执行权利与硬约束过滤。

## 23. 效果驱动再生产

### 23.1 学习对象与准入

学习层不再使用含糊的单一 `EffectProfile`。`PerformanceProfile` 保存描述性历史；`AssociationalEstimate` 与 `CausalEstimate` 保存效应估计。每个对象都绑定实体 revision、适用上下文、MetricDefinitionRevision、观察窗口、场次/样本、数据封存点、证据等级、方法、区间估计、漂移状态和来源结果。

候选结果只有满足版本化 `EffectEligibilityPolicy` 的指标一致性、曝光完整性、时间对齐、最小场次/样本、跨场稳定性、新鲜度和异常检查，才可进入 `eligible`。不同用途可要求不同证据：界面展示可用 descriptive，人工建议至少 associational，自动提高排序权重默认要求 approved associational；自动策略淘汰或扩大流量默认要求准实验或随机实验，且必须由风险策略明确批准。

### 23.2 决策日志、探索与点时正确性

每次选材、模板选择、策略选择和生成建议都产生不可变 `DecisionLog`，记录候选全集/排除原因摘要、点时特征快照、策略与模型版本、权重、探索机制、选择概率或 propensity、最终选择、后续实际 release 与曝光。训练、离线评估和回放只能使用决策当时可见的特征，禁止读取未来统计或被后续修订覆盖的值。

推荐器先执行第 5.6 节硬过滤，再组合语义、质量、约束余量和合格效果特征。新对象和不确定策略保留受预算控制的探索流量；探索不能绕过权利、事实、安全或硬约束。缺少 propensity 或实际曝光的历史数据只能用于描述性学习，不能伪造反事实训练集。

### 23.3 离线评估、在线验证和反馈回路

新策略先在封存数据上做 point-in-time 回放、覆盖率、校准、分群稳定性和离线策略评估；离线通过不等于可上线。在线依次经过 shadow、人工建议、小流量受控实验、扩量和常态化，每级都有护栏、成本预算和回滚条件。

系统持续监控 selection bias、position bias、survivorship bias、流量漂移、策略改变导致的数据分布变化以及推荐器自我强化。可使用 propensity weighting、doubly robust 等方法时必须保存适用假设和诊断；无法满足时降级证据。离线特征定义、在线决策特征和分析特征共享版本化定义，并通过抽样对账检测训练/服务偏差。

### 23.4 再生产与撤销

“基于效果再生产”创建新的 ContentProjectRevision 或 ProductionVariantRevision，固定来源结果、DecisionLog、旧内容修订和变更假设，明确保留、替换与预期影响。新方案有独立 ReleaseManifest、曝光和评估，不能覆盖旧方案。

效果对象只能提高合格候选排序、建议内容/镜头组合和提示风险；不能覆盖事实、放宽硬约束、修改全局素材配置、自动发布模板、自动执行麦兔写入或开播。指标口径变化、权利撤销、数据删除、漂移或连续在线失效会使结果进入 `review_required` 或 `revoked`；所有依赖决策可通过 lineage 找到并重新评估。

## 24. 统一镜头、排播和角色策略

### 24.1 Shot/ShotList 统一镜头模型

`ShotListRevision` 与 `Shot` 是最小生产主链的必需对象，不再延后。Shot 是内容意图，不等同于麦兔 Scene 或视频 Clip；它至少声明稳定 `shot_code`、ProgramSegment/ScriptBlock 来源、目标、预期时长、构图意图、所需角色与素材、必讲/禁讲、连续性要求和验收标准。

载体编译器把同一 Shot 显式投影为 `MaituSceneBlueprint`/Layer 或 `TimelineSegment`/Clip，并保存 `ShotProjectionLink`。一个 Shot 可投影为多个 scene/clip，一个 scene/clip 也可组合多个 Shot，但必须声明关系类型和时间范围。未来镜头级拍摄参数、takes、多机位、镜头版本和人工镜头编辑器只扩展该对象，不另建平行模型。

### 24.2 BroadcastSchedule 与 GoLiveAuthorization

排播计划完整建模，但当前实施阶段保持执行关闭：

```text
schedule: draft -> validated -> approval_required -> approved -> active
                 -> rejected                    -> canceled / completed
go-live authorization: requested -> approved -> consumed
                                -> rejected / expired / revoked
```

`BroadcastScheduleRevision` 固定目标账号/房间、ReleaseManifest、平台、时区、开始/结束窗口、促销/库存依赖、冲突策略、负责人和停止条件。验证覆盖 release 未撤销、权利地域/渠道/期限、目标空闲、凭据能力、库存/优惠有效期、平台规则和并发冲突。

`GoLiveAuthorization` 是短期、目标绑定、release hash 绑定、窗口绑定且单次使用的高风险 capability；生产者与批准者分离，高风险账号支持双人复核。Worker 提交开播前重新检查授权、现场指纹、时间窗和策略版本；任何变化均失败关闭。未完成独立安全评审、演练和紧急停播能力前，服务不得签发此授权，API/BuildPlan 也不得包含开播动作。

### 24.3 RoleStrategy、分配与 RoleEvaluation

`Role` 固定职责、输入输出 schema、允许工具和质量门禁；`RoleStrategyRevision` 是可替换实现，包含 prompt/规则/模型/代码、参数、成本上限、支持范围和状态。每个生产 artifact 必须记录实际 role/strategy revision，人工编辑以 `human_override` 策略和操作者记录，不用空字段掩盖。

策略选择由显式默认、人工指定或第 21.5 节 Experiment Assignment 决定，并写入 DecisionLog。`RoleEvaluation` 引用明确的策略曝光、结果指标和证据等级，分别报告质量、时延、成本、安全和业务效果；不能把下游总 GMV 全量归给单一角色。只有满足预注册实验或经批准准实验的评价才能自动扩大/收缩流量，描述性结果只供诊断和提出假设。

## 25. 统一运行控制面、发布与执行授权

### 25.1 WorkflowRun、StepRun 与 HumanTask

所有长任务统一投影为 `WorkflowRun`，步骤为 `StepRun`，人工交接为 `HumanTask`。领域聚合仍拥有业务状态；控制面负责 parent/child、依赖、队列、租约、重试、timeout、heartbeat、暂停/恢复、取消、预算、优先级和进度，不用一个通用状态机替代领域状态。

每个 Step 声明幂等键、副作用等级、最大尝试、退避、超时、可取消点、输入/输出 ArtifactRef 和补偿/对账策略。纯计算可以重跑；外部写操作采用 prepare -> authorize -> commit -> read-back/reconcile，未知结果先对账再决定，不盲目重试。等待人工不会占用 Worker，HumanTask 保存 SLA、owner、决定、理由和基于的 revision。

首期复用 PostgreSQL 队列/租约实现并完善一致契约；只有当跨日 workflow 数量、并发、定时器/信号复杂度、运维故障数据证明现有实现不足时，才通过 ADR 评估 Temporal 等 durable execution 引擎。迁移时领域 run code、幂等键和 artifact lineage 不变。

### 25.2 Artifact、lineage 与 trace

`ArtifactRef` 指向内容寻址 artifact，保存 media type、schema、URI、checksum、size、producer StepRun、输入引用和保留策略。`WorkflowRun` 表示过程，artifact 表示产物，`ReleaseManifest` 表示批准交付的精确集合，三者不得混用。

领域 lineage 写关系库并提供 OpenLineage 兼容投影；运行观测使用 OpenTelemetry trace/span。trace ID 可挂到 StepRun，但 trace 丢失不应破坏业务 lineage。每次运行导出 RunManifest；每个 release 从已完成 artifact 创建，不引用“latest”。

### 25.3 Release、Delivery 与 Exposure

`ReleaseManifest` 至少固定 ContentProjectRevision、ProductionVariantRevision、StoryBrief/Script/ProgramSegment/ShotList、素材/权利快照、BuildPlan 或 ProductionTimeline、质量报告、artifact checksum、策略/模型/代码、批准记录和 release fingerprint。live_room 与 rendered_video 使用同一外壳、不同载体 facet。

批准 release 不等于交付；`DeliveryAttempt` 记录目标、适配器、幂等键、授权、请求/响应摘要、外部对象身份、回读状态和证据。交付成功也不等于曝光；LiveSession 绑定 release，ContentExposureEvent 记录实际展示。撤销 release 会阻止新交付并触发影响分析，不能删除既有证据。

### 25.4 PolicyDecision 与 ExecutionAuthorization

执行授权由独立策略决策点签发，至少绑定主体、目标资源、动作/capabilities、BuildPlan 或 release hash、现场指纹、策略版本、批准链、签发/过期时间、nonce 和 single-use 状态。授权不能被换目标、延长或扩大 capability；短期 token 中不携带长期平台凭据。

Worker 在每个副作用 commit 时重新校验授权和 ProtectedResourceRegistry，记录 `PolicyDecision` 输入摘要、规则结果和授权消费。preflight 通过、workflow running 或人工点击都不能替代提交时授权。不同能力分离：`write_draft`、`upload_asset`、`deliver_release`、`go_live` 不能互相代用。

## 26. 数据治理、隐私、权利与保留

### 26.1 数据分类与访问

字段和 artifact 使用 `public / internal / confidential / restricted_personal / credential` 分类。原始评论、用户标识、订单明细和平台 cookie/token 不进入模型提示、向量索引、图谱、公开截图或效果证据。跨平台用户关联默认使用来源内 pseudonym；没有合法目的和批准的数据合同，不建立跨平台身份图。

访问采用角色与用途双重控制，导出、解密、批量查询和删除均审计。训练或第三方模型调用只发送最小必要字段，并记录 processor、区域、模型保留政策和审批；不满足政策时使用脱敏聚合或本地处理。

### 26.2 保留、删除与 legal hold

保留策略按数据类版本化，下面是初始基线而非硬编码：

| 数据类 | 默认保留 | 说明 |
| --- | --- | --- |
| 外部原始录屏 | 30 天 | 有权利/案件需要时 legal hold |
| 原始个人互动与订单级事件 | 30-90 天，由来源合同决定 | 到期删除或不可逆匿名化 |
| 标准化去标识事件/细粒度桶 | 180 天 | 受最小必要性和重算窗口约束 |
| 汇总指标、发布归因和实验结论 | 长期版本化保留 | 不含可逆个人标识 |
| RunManifest、release、授权和关键审计证据 | 按审计政策长期保留 | 敏感 payload 单独短期保存 |
| 中间 artifact、截图、模型原始响应 | 按用途 30-180 天 | 可重建项优先短期 |

删除请求产生 tombstone 和可审计 `DeletionRun`，传播到原始存储、标准事件、特征/向量/图谱投影和可删除派生产物；发布聚合在无法反推个人且政策允许时可保留。legal hold 必须有 owner、范围、到期与解除记录，不能成为永久保留默认值。

`DeletionRun` 使用 `requested -> validating -> blocked_by_legal_hold|approved -> executing -> verifying -> completed|partial_failed`；每个下游处理器回写删除、匿名化、保留依据或失败证据。`partial_failed` 必须重试和升级，不能以主库行已删除视为完成。

### 26.3 权利与发布影响

第 5.7 节 RightsGrant 在选材、衍生、模型使用、渲染、交付和排播时逐层校验。权利即将到期会阻止超出期限的新 schedule；撤销或地域/渠道变化触发 release、派生 Rendition、模板和后续决策的影响分析。历史交付证据保留，但新交付和再生产失败关闭。

## 27. 非功能目标、容量、SLO、成本与灾备

### 27.1 容量基线与压测

实施前必须测量并记录：`asset_count`、每日新增素材、录屏小时/日、并发采集、原始/标准事件峰值每秒、直播并发、渲染任务/日与并发、artifact 日增长、图谱边数、workflow 数量/时长和 Browser-use 账号/房间并发上限。容量文档给出当前值、12 个月预测、峰值系数和单元成本；未测量前不以任意“海量”假设采购复杂基础设施。

每个阶段在目标峰值 2 倍下做队列、数据库、对象存储和适配器压测，并验证 backpressure：录屏不因分析积压丢源文件，事件不因归因积压丢已接收批次，Browser-use 严格遵守账号/房间串行限制，渲染队列受 CPU/GPU/存储预算限流。

### 27.2 用户旅程 SLO

初始目标在获得基线数据后由 owner 批准并逐季调整：

- 元数据读写 API 月可用性 99.9%，成功请求 p95 小于 500 ms；搜索和重查询单列 SLO。
- 已接受异步任务不丢失，99% 在产品声明时限内进入运行或给出明确排队原因。
- 已发布 release 的 manifest、artifact checksum、批准和 lineage 完整率 100%；不完整即阻断发布。
- 外部写操作授权和证据完整率 100%；第三方执行成功率单独观测，不能用重试掩盖未知结果。
- 标准事件摄取新鲜度、归因发布时延和投影滞后按来源设 SLO；陈旧数据必须在 UI 显示。
- 删除请求、权利撤销传播和紧急停用有独立完成时限及升级路径。

SLO 以用户旅程计算并配置 error budget。预算耗尽时暂停扩大流量和新增高风险自动化，优先修复可靠性；单个健康检查成功不能代表闭环可用。

### 27.3 成本、配额和降级

每个 WorkflowRun 记录模型 token、ASR/OCR、渲染 CPU/GPU 秒、对象存储/出口、图数据库和 Browser-use 时间的估算与实际成本。ContentProject、团队和适配器有日/月预算、并发配额和 kill switch；超预算进入人工批准或降级策略，不能悄悄换低质量模型冒充原策略。

降级顺序由领域定义：暂停非必要重分析/embedding，降低预览 Rendition，延后图谱投影和离线学习；不得跳过事实、权利、授权、质量或 release 门禁。关键生产和派生分析使用不同队列，避免批处理挤占草稿写入或紧急撤销。

### 27.4 备份、恢复与灾难演练

关系库采用 point-in-time recovery，初始目标 RPO 不超过 5 分钟、RTO 不超过 4 小时；对象存储开启版本保护并按 artifact 级别定义跨故障域复制。凭据、签名密钥和授权服务有独立备份与轮换流程。Neo4j、向量索引和搜索均视为可重建投影，不以备份代替重建演练。

至少每季度执行数据库恢复、对象校验、outbox 重放、投影重建和关键 release 导出验证；每半年演练第三方平台不可用、授权服务故障、错误 release 撤销和大规模数据删除。恢复后以 manifest checksum、行数/对账和业务不变量验证，不以“服务启动”作为完成标准。

## 28. 标准、演进规则与技术采用门槛

### 28.1 强制兼容边界

- 编辑时间线权威语义采用 OpenTimelineIO 兼容对象和 RationalTime；平台毫秒时间通过 TimeMapping 映射。
- 运行血缘提供 OpenLineage 兼容投影，观测传播 OpenTelemetry context，二者职责分离。
- 发布 provenance 采用 SLSA 思路记录构建来源；对外成片评估 C2PA，并用 IPTC sidecar 表达权利和 AI 生成信息。
- 数据事件、MetricDefinition、DataContract 和领域 API 都有 schema version、兼容窗口、弃用时间和 consumer 测试；未知必需字段失败关闭，新增可选字段向前兼容。

### 28.2 基础设施采用门槛

- 约束求解先以第 6.5 节 solver-independent contract 建模；只有代表性问题集显示收益后，通过 ADR 选用 OR-Tools CP-SAT/MIP，并保留超时、不可行解释和确定性测试。
- Temporal 等 durable workflow 引擎只在第 25.1 节量化门槛触发后引入，不让引擎对象渗入领域 API。
- Neo4j 只在至少三个稳定、关系库实现明显低效的业务查询、本体稳定性、容量压测和完整重建演练通过后成为正式依赖；此前使用关系表和递归查询。
- 在线 Feature Store 只在存在跨服务低延迟在线决策与离线训练一致性需求后评估；在此之前仍必须保存 point-in-time FeatureSnapshot 和定义版本。
- 所有新平台组件都要有 owner、退出方案、成本上限、备份/重建策略和故障注入结果。

### 28.3 架构决策与契约变更

影响聚合边界、不可变 revision、release/exposure 语义、事实/权利门禁、授权能力、时间语义或证据等级的变更必须写 ADR，并附迁移、回滚和历史数据解释。禁止用 nullable 字段长期并存两套语义；兼容投影必须标注 source of truth 和下线条件。

## 29. 最终目标对齐矩阵

| 最终目标领域 | 本设计闭环 | 规划状态 |
| --- | --- | --- |
| 素材库、约束、选材、缺口 | 第 5-7、10.4、12-15、19.1 节 | 100% 规划对齐 |
| 外部录屏解析与内容模板 | 第 4.4、8、13.2、14.2、19.2 节 | 100% 规划对齐 |
| 故事/事实 -> 剧本 -> 场景 | 第 9-10、24.1 节 | 100% 规划对齐 |
| 麦兔场景、图层、BuildPlan、草稿写入 | 第 10.5、10.8-10.9、15、25 节 | 100% 规划对齐 |
| 安全门禁、版本、证据、可复现性 | 第 11、14-15、25-28 节 | 100% 规划对齐 |
| 成片渲染、剪辑、时间轴 | 第 4.7、20、24.1、25.3 节 | 100% 规划对齐；不建设通用 NLE |
| 运营数据回流与内容归因 | 第 4.8、21、26-27 节 | 100% 规划对齐；平台字段由 DataContract 扩展 |
| 知识图谱与效果驱动再生产 | 第 4.6、4.9、22-23、28.2 节 | 100% 规划对齐；图/向量层按门槛采用 |
| Shot/ShotList 统一镜头模型 | 第 10.7、20、24.1 节 | 100% 契约对齐，最小模型进入主链 |
| 排播与开播授权 | 第 14.5、24.2、25.4 节 | 100% 规划对齐，当前阶段执行关闭 |
| RoleStrategy、A/B、RoleEvaluation | 第 21.5、23、24.3 节 | 100% 规划对齐，按证据门槛逐步启用 |

“100% 规划对齐”表示领域对象、来源关系、状态、门禁、API 方向、非功能要求和验收责任在本文中闭合，不表示代码已经实现或所有外部平台适配器已接通。执行关闭表示契约完整但 capability 不签发，不代表用空字段占位。

## 30. 完成定义

该设计全部实现后，内部运营人员能够在统一 Console 的多个业务工作区内：

1. 建立跨载体 ContentProject，管理事实、故事、剧本、ProgramSegment 和 ShotList 的不可变修订。
2. 管理素材版本、Rendition、权利、约束、分组、素材包、选材解释和缺口闭环。
3. 从外部直播录屏提炼可复用、可审计的内容策略模板，严格区分内容准备度、视觉忠实度和可构建性。
4. 从同一内容项目创建 live_room 和 rendered_video ProductionVariant，分别编译麦兔场景/图层/BuildPlan 或 OTIO 时间轴。
5. 经事实、权利、约束、质量、授权和证据门禁生成 ReleaseManifest，并安全写入麦兔草稿或交付成片。
6. 用 WorkflowRun/HumanTask 管理长任务、重试、人工交接和预算，完整保留 RunManifest、artifact、lineage 和 trace。
7. 以实际 release 和 ContentExposureEvent 对齐运营指标，按明确口径产生描述性、关联性、准实验或随机实验结果。
8. 在 point-in-time 正确、带探索概率和证据门槛的前提下，用效果结果驱动受控再生产与 RoleStrategy 评价。
9. 在可重建图谱中追溯素材、权利、事实、模板、内容、执行、发布、曝光和效果，并在撤销/删除时完成影响传播。
10. 在明确 SLO、容量、成本、保留和灾备约束下运行；正式开播只有在独立能力启用且取得短期 GoLiveAuthorization 时才可能发生。

## 31. 成熟实践与标准依据

以下资料用于约束设计原则和后续 ADR，不表示相关产品必须立即引入：

| 主题 | 采用的设计要点 | 主要依据 |
| --- | --- | --- |
| 长任务可靠执行 | durable state、retry/timeout、signal/human wait、幂等 activity；先统一领域无关 contract，再决定是否换引擎 | [Temporal Documentation](https://docs.temporal.io/) |
| 编辑时间线 | Timeline/Stack/Track/Clip/Gap/Transition、RationalTime/TimeRange、schema 演进 | [OpenTimelineIO Documentation](https://opentimelineio.readthedocs.io/en/latest/) |
| 运行血缘与观测 | lineage 的 Job/Run/Input/Output 与 trace/span 分工 | [OpenLineage Specification](https://github.com/OpenLineage/OpenLineage/blob/main/spec/OpenLineage.md)、[OpenTelemetry Traces](https://opentelemetry.io/docs/concepts/signals/traces/) |
| 约束求解 | CP-SAT/MIP、可行/不可行/未知、预算和解释；领域先使用 solver-independent model | [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver) |
| 流式时间语义 | event time、processing time、watermark、迟到与窗口修正分离 | [Apache Flink Time Concepts](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/) |
| 可信实验 | 先分配后曝光、A/A、SRM、护栏、预注册分析与停止规则 | [Microsoft Experimentation Platform](https://www.microsoft.com/en-us/research/group/experimentation-platform-exp/) |
| 点时特征与反馈回路 | point-in-time join、训练/服务一致、先记录决策和 propensity、分阶段上线 | [Feast Point-in-time Joins](https://docs.feast.dev/getting-started/concepts/point-in-time-joins)、[Google Rules of ML](https://developers.google.com/machine-learning/guides/rules-of-ml) |
| 事务投影与本体校验 | transactional outbox、可重建投影、shape validation | [Debezium Outbox Event Router](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html)、[W3C SHACL](https://www.w3.org/TR/shacl/) |
| 供应链与媒体 provenance | 构建来源、ingredient、内容凭证和权利/AI 元数据 | [SLSA Provenance](https://slsa.dev/spec/v1.2/provenance)、[C2PA Specifications](https://c2pa.org/specifications/specifications/2.2/index.html)、[IPTC Video Metadata Hub](https://iptc.org/standards/video-metadata-hub/) |
| AI 与 Agent 安全 | 风险分层、最小权限、human oversight、外部工具的过度代理风险 | [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)、[OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html) |
| 隐私与保留 | 目的限制、数据最小化、风险评估、删除和保留治理 | [NIST Privacy Framework](https://www.nist.gov/privacy-framework) |
| 可靠性治理 | 用户旅程 SLI/SLO、error budget、逐步落地和恢复验证 | [Google SRE Workbook: Implementing SLOs](https://sre.google/workbook/implementing-slos/) |

任何标准映射都必须保存版本；外部标准升级不会自动改写已发布 release、历史指标或归因结果。若标准与麦兔/平台现场能力冲突，先在 ADR 中记录差异和兼容层，不把平台限制污染为通用领域语义。

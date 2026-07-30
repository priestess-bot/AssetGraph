# AssetGraph 客户体验优先 v1 落地 Checklist

> 状态：执行中
> 日期：2026-07-26
> 范围决策：[ADR-0003](../adr/0003-customer-experience-v1-scope.md)
> 长期设计：[直播内容生产与运营闭环设计](./2026-07-22-live-content-production-operations-closed-loop-design.md)
> 归档参考：[577 项生产级 Checklist](./2026-07-23-live-content-production-operations-implementation-checklist.md)
> 前端产品化改造：[2026-07-28 实施 Checklist](./2026-07-28-frontend-product-redesign-implementation-checklist.md)

## 0. 执行规则与范围

- 每完成一个条目，必须立即把 `[ ]` 更新为 `[x]`，并在条目末尾填写测试、截图、API 或文档证据；不得到阶段末统一补勾。
- 只以客户可完成的任务作为功能完成依据。只有文档、模型或安全准备而没有可操作界面/API 时，不得勾选对应功能。
- `Release A -> Release B -> 测试与反思` 顺序推进；不以归档清单的 Phase 门禁阻塞 v1。
- 麦兔变更能力只有经过真实账号 canary、目标校验和刷新回读后才能标记 `verified`。模拟测试只证明契约，不证明真实可用。
- 当前分母只统计本文件的 `V1-*` 条目。范围变化先更新 ADR-0003，再更新本清单。

### 范围映射

| 长期范围 | v1 处置 | v1 交付 |
| --- | --- | --- |
| 素材、约束、选材、缺口 | retain | Release A 完整客户流程 |
| 外部录屏解析与内容模板 | simplify | 保证上传录屏；平台自动采集为增强项 |
| 故事/事实到剧本到场景 | retain | Release A 完整客户流程 |
| 麦兔场景、图层、BuildPlan、草稿 | simplify | 矩形可编辑布局、严格目标校验、能力验证后自动写入，否则人工交接 |
| 成片、剪辑、时间轴 | simplify | 生成确定性本地竖屏成片，不做交互式 NLE |
| 运营数据与归因 | simplify | Release B 文件导入、描述/关联证据，不承诺因果 |
| 知识图谱与效果再生产 | simplify | PostgreSQL 投影必需；Neo4j/Milvus 仅作可选本地增强 |
| 权限、合规、可靠性 | simplify | 保留事实、素材权利、目标房间三类硬门禁和现有基础，不扩展企业控制面 |
| Shot/ShotList、排播开播、RoleStrategy/A-B | defer | 不进入 v1 客户验收 |

### 明确不做

- 多租户、组织隔离、细粒度 RBAC、对象 ACL、双人审批和权限管理 UI。
- 创建麦兔直播间、训练数字人/音色、商品/互动配置、正式排播、开播授权和点击开播。
- 从录屏恢复真实麦兔 material ID、精确 z-index 或像素级布局。
- 无人值守外部平台采集承诺、交互式视频剪辑器、因果实验、自动策略淘汰。
- 把 Neo4j、Milvus、Temporal、云服务、企业 SLO、灾备演练或渗透测试作为 v1 可用前提。

## 1. Release A：素材到可交付内容

### 1.1 范围、入口与麦兔边界

- [x] `V1-0001` 通过 ADR 固化单团队、两批交付、最小硬门禁和延后范围。证据：`docs/adr/0003-customer-experience-v1-scope.md`。
- [x] `V1-0002` 将 577 项清单标记为生产级归档参考，并切换唯一活跃 v1 清单。证据：两份 checklist 顶部状态和互链。
- [x] `V1-0101` 后端提供版本化麦兔能力矩阵，逐项返回 `verified/manual_only/unsupported`、证据和契约指纹。证据：`GET /api/functional-live-room-plans/maitu-capabilities`、`backend/app/services/maitu_capabilities.py`。
- [x] `V1-0102` 能力矩阵默认保守：创建房间、排播和开播为 `unsupported`，未做真实 canary 的变更为 `manual_only`。证据：`backend/tests/test_maitu_capabilities.py`。
- [x] `V1-0103` 直播间配置页清楚显示“客户先创建空白未开播麦兔草稿，AssetGraph 不创建房间且不开播”。证据：`frontend/src/live-rooms/LiveRoomPlannerPage.tsx`、前端页面测试。
- [x] `V1-0104` 自动草稿按钮只在全部必需能力 `verified` 时可用；否则保留方案生成并给出人工交接说明。证据：`LiveRoomPlannerPage.test.tsx` 验证人工模式、禁用写入按钮和保留 BuildPlan 提示。
- [x] `V1-0105` 客户必须填写直播间 ID、标题并确认目标为空白未开播草稿。证据：`FunctionalLiveRoomPlanCreate` 必填 schema、表单提交条件与执行确认控件。
- [x] `V1-0106` 为能力矩阵补齐后端契约测试和前端降级行为测试。证据：`pytest backend/tests/test_maitu_capabilities.py` 2 passed；Vitest live-room API/Page 9 passed；`npm run typecheck` passed。
- [ ] `V1-0107` 在当前真实麦兔账号运行只读 canary，记录房间标题、状态和适配器契约指纹。
- [ ] `V1-0108` 对每项计划启用的变更分别运行真实 canary，并保存变更前、执行后、刷新回读证据；未通过项维持人工模式。

### 1.2 素材库、约束、选材与缺口

- [x] `V1-0201` 客户可同步/导入普通图片和视频，并看到同步状态、缩略图、来源与可执行能力。证据：素材页本地文件导入、对象存储代理预览；2026-07-29 扫描 `/DATA/Downloads/AssetGraph/素材` 得到 63 份当前本地图片/视频并导入验收库，`GET /api/assets?limit=500` 返回 131 条（含历史兼容记录），63 份当前素材预览逐条返回 206；报告见 `docs/asset-numbering/import_report_20260729_current_local_materials.json` 与 `docs/asset-numbering/import_report_20260729_local_materials.json`，后端文件/预览 2 passed，前端 76 passed、TypeScript/生产构建通过。
- [x] `V1-0202` 每份素材独立保存 `media_kind`、多值 `material_role` 和 `execution_capability`，UI 不从文件类型推断业务角色。证据：分类编辑器与批量三轴校正测试；`AssetClassificationUpdate` 独立字段契约。
- [x] `V1-0203` 客户可配置位置范围、宽高/缩放、是否等比、顶层/底层和层级关系约束。证据：素材约束编辑器覆盖 region/size/scale/aspect/layer/relative kinds，并保存不可变 Profile 修订。
- [x] `V1-0204` 客户可表达“商品位于背景桌面区域且在背景之上”等跨素材关系，并获得可理解的冲突反馈。证据：`table_surface`、`above_role/below_role` 结构化编辑器及桌面约束页面/编译测试。
- [x] `V1-0205` 客户可创建、编辑和删除素材分组；同一素材可加入多个分组。证据：分组设置 UI、独立成员关系、软归档 migration 098；backend 2 passed/3 DB skipped，frontend AssetLibrary 11 passed。
- [x] `V1-0206` 客户可创建和发布素材包，配置必用、可选和角色排他规则。证据：素材包创建/发布/新修订 UI，出现次数页面测试及 material-pack route tests。
- [x] `V1-0207` 直播间配置分别复选素材分组和零散素材，并能看到最终解析清单。证据：Live Room 分组/零散/总体包/分类包独立选择器与冻结 `materialSnapshot`。
- [x] `V1-0208` 客户可在当前直播间覆盖素材几何、层级和角色选择，且不会静默改写全局约束。证据：房间私有覆盖编辑器、显式“提升为全局约束”操作及页面测试。
- [x] `V1-0209` 系统在生成前展示缺口、影响、替代素材和可豁免原因；真正破坏完整性的缺口才阻断。证据：素材缺口诊断/登记/豁免 UI 与 Live Room 页面测试。
- [x] `V1-0210` 选材结果保存候选分数、入选原因、约束版本和素材包版本，客户可追溯“为何选它”。证据：`materialSelectionDecisions`、候选分数组成和冻结 pack/profile refs 的 API/UI 投影。
- [x] `V1-0211` 素材权利/使用状态是硬门禁；未知或撤销状态不得进入可执行 BuildPlan。证据：migration 099、素材使用状态 UI、`GATE_ASSET_RIGHTS_*` 和冻结 rights snapshot；backend 6 passed，frontend 21 passed。
- [x] `V1-0212` 用一个包含背景、商品、贴片和数字人的样例完成端到端素材验收并保存截图。证据：`scripts/run_customer_v1_material_acceptance.py` 选择四份 `approved + maitu_bound` 素材，写入桌面区域、尺寸、等比和上下层关系 Profile，创建 4 项分组并回读；JSON 为 `docs/evidence/customer-v1-v1-0212-material-acceptance.json`，实际页面截图为 `docs/evidence/screenshots/customer-v1-v1-0212-material-group.png`。

### 1.3 上传录屏与内容模板

- [x] `V1-0301` 客户可上传一份本地直播录屏并看到校验、上传和解析进度。证据：`POST /api/live-research/capture-sessions/uploads`、内容寻址存储/ffprobe 校验、上传进度 UI、CaptureSession/时间线/四类分析 DAG；backend 9 passed/1 DB skipped，frontend 15 passed，TypeScript passed。
- [x] `V1-0302` 解析产生可回看的 ASR、OCR、画面片段和时间对齐结果；单步失败可重试。证据：FFmpeg 帧采样、ASR/OCR/layout provider、全局时间线投影、失败步骤错误与运营重试 API/UI；Worker 30 passed，backend 聚焦 19 passed/1 DB skipped，frontend 18 passed。
- [x] `V1-0303` 客户可清洗敏感/错误文本、合并片段并选择纳入模板的内容。证据：内容策略页录屏文字清洗器支持勾选、编辑、号码/金额隐去、合并及带来源区间写入 reviewed examples；前端交互测试通过。
- [x] `V1-0304` 一个模板只绑定一个来源直播间；跨房间 CaptureSession 必须拒绝或拆分。证据：`CONTENT_STRATEGY_CROSS_ROOM_SOURCE` 拒绝契约、同房间多场次保留；contract 9 passed，PostgreSQL 集成用例已提供但当前环境跳过。
- [x] `V1-0305` 模板明确展示内容就绪度、布局可信度、可构建性和来源证据。证据：模板 summary/projection API 投影 `content_readiness/layout_fidelity/buildability`，布局与内容模板详情显示三类状态及可定位录屏证据；API/UI 测试通过。
- [x] `V1-0306` 客户可审核、发布、停用和创建模板新版本，旧项目继续引用原版本。证据：模板工坊审核/发布/新修订 UI、软停用 API/UI 与 migration 100；活跃列表隐藏停用模板但直接读取和发布 projection 保留，路由/API/UI 测试通过，PostgreSQL 集成用例待具备测试库时执行。
- [x] `V1-0307` 外部平台自动采集作为可选增强；不可用时上传录屏主流程不受阻。证据：本地上传独立创建 CaptureSession 和分析 DAG，界面明确“平台采集非必需”；上传回退页面测试通过。
- [ ] `V1-0308` 用一份真实录屏完成上传到可选模板的端到端验收并保存截图。

### 1.4 事实、故事、剧本与直播间方案

- [x] `V1-0401` 客户可维护商品事实卡并区分草稿、已批准和不可用事实。证据：知识库事实卡草稿/新版本/批准/驳回 UI 与版本状态；knowledge API/Page 19 passed。
- [x] `V1-0402` 新建内容项目时可填写生成目标，并在同一区域补充主题、故事和详细设计。证据：内容项目新建表单及完整约束提交测试。
- [x] `V1-0403` 原始输入先形成可编辑 DesignBrief，客户确认后再生成内容。证据：解析、结构化覆盖、新修订、显式确认及生成按钮门禁；content API/Page 测试通过。
- [x] `V1-0404` 客户可选择最多一个主模板和多个次模板，并看到各模板贡献建议。证据：主模板 radio、次模板复选、目标匹配推荐、模块采纳/冲突提示及固定贡献投影。
- [x] `V1-0405` 系统从已批准事实和已选模板生成 StoryBrief、剧本块和节目段，事实句可反查来源。证据：版本化 StoryBrief/ScriptBlock/ProgramSegment/ShotList、FactCitation 与模板录屏证据深链；frontend 35 passed、后端无数据库契约 5 passed。
- [x] `V1-0406` 未批准事实、事实冲突或关键事实缺失给出明确修复动作；不得生成虚构销售主张。证据：仅可选择批准事实、冲突预检、FactCitation 生成门禁、稳定错误码及按批准状态/范围/有效期/引用给出的修复步骤；frontend 17 passed，backend schema 3 passed。
- [x] `V1-0407` live-room 分支生成独立 `MaituSceneBlueprint`，不再以泛化 `Scene` 作为验收对象。证据：`maitu_scene_blueprints`/`layer_blueprints` 显式投影、`maitu-scene-blueprint.functional.v2` API 和直播间场景/图层 UI。
- [x] `V1-0408` 客户可表单化调整场景顺序、矩形位置/尺寸、层级、素材和对应话术。证据：场景编辑器、`POST /functional-live-room-plans/{plan_code}/blueprint-revisions`、不可变派生 Plan/Variant/BuildPlan、migration 101；backend 6 passed、frontend 11 passed、TypeScript passed。
- [x] `V1-0409` BuildPlan 只包含白名单动作和固化素材身份，永久保持 `go_live=false`。证据：`_persist_build_plan` 强制关闭开播、8 类动作 allowlist、固定 `asset_code/layer_id` 单测与 PostgreSQL 计划测试。
- [x] `V1-0410` 方案页展示内容、素材、场景和操作的追溯关系以及阻断修复建议。证据：operation-to-Scene/Layer/Shot/ProgramSegment/ScriptBlock trace API/UI、门禁 remediation 可见；页面交互测试通过。
- [x] `V1-0411` 客户可复制方案到新的空白房间，不对已有内容房间做破坏性增量重建。证据：克隆表单与 API 仅复制业务输入并重新编译新 Plan/Variant/Configuration/BuildPlan，清空执行/发布/回读状态、拒绝原房间 ID，页面自动进入新计划。
- [ ] `V1-0412` 用一个真实商品目标完成事实到可审阅直播间方案的端到端验收并保存截图。

### 1.5 麦兔草稿与本地成片

- [x] `V1-0501` 草稿执行前读取并核对目标房间 ID、标题、空白状态和未开播状态，任一不符即停止。证据：BuildPlan 冻结 `target_live_room_id/expected_title`；worker 写前读取 working room 并零副作用拒绝 ID、标题、空白或直播状态不符；后端权威回读重复核对标题；相关 backend/worker 62 passed。
- [ ] `V1-0502` 经验证的适配器可使用已有素材、数字人和音色，并可按能力矩阵上传普通图片/视频。
- [ ] `V1-0503` 经验证的适配器可创建场景、插入图层、设置矩形位置/层级并写入话术。
- [x] `V1-0504` 执行后刷新重读房间，并将场景、图层、话术和目标房间的对比结果展示给客户。证据：每场景 `verify_scene` 重新读取 working room；readback v2 投影目标 ID/标题、场景名、素材/矩形/层级和完整话术的 `matched/mismatch/pending` 对比；页面回读区域与差异测试通过。
- [x] `V1-0505` 任一麦兔能力不可用时，客户可查看完整人工操作清单，且系统不把人工交接记为自动成功。证据：操作清单展示中文动作、状态、指令、房间/场景、素材绑定、矩形/层级、数字人/音色、完整话术及全部冻结字段；能力矩阵未验证时持续显示人工模式，不开放自动写入按钮。
- [ ] `V1-0506` 使用真实空白房间完成一次完整草稿 canary；证据包含前后截图、回读和契约指纹。
- [x] `V1-0510` video 分支与 live-room 分支使用同一已确认内容修订和素材快照。证据：live-room 派生成片固定同一 confirmed ContentProject/StoryBrief/Script/ShotList，并把来源 ProductionVariant 修订、完整 material snapshot 与指纹继承到 rendered_video snapshot；页面展示来源快照，成片本地素材作为独立分支增量。
- [x] `V1-0511` 系统生成确定性竖屏时间轴、字幕、音频和渲染任务，不依赖交互式剪辑器。证据：固定 1080x1920/30fps RenderProfile、确定性 video/audio/subtitle 三轨时间轴、TTS/ASS/FFmpeg 本地任务；聚焦 backend 82 passed。
- [x] `V1-0512` 客户可预览时间轴片段并调整顺序、时长、素材和字幕，然后生成新修订。证据：成片播放/镜头跳转、片段排序与时长、源素材区间/裁切/变速、叠加层、字幕/音量/海报时间编辑、不可变修订和历史恢复；frontend 6 passed。
- [x] `V1-0513` 本地渲染产出可播放 MP4、封面、字幕和 manifest，并展示失败修复建议。证据：成片播放/封面/联系表和中文产物下载入口；按内容、素材、配音、字幕、渲染、质检阶段展示可执行修复动作；backend 83 passed、frontend 8 passed。
- [x] `V1-0514` 相同输入与工具版本可复现相同时间轴/manifest 指纹；媒体编码差异须显式记录。证据：页面展示确定性 timeline 指纹、manifest 指纹及下载入口；manifest 固定素材/语音/字幕校验和、FFmpeg/ffprobe 版本、编码和输出校验和；重试 diff 区分固定输入下输出变化与输入/工具变化。
- [x] `V1-0515` 用同一内容项目完成直播间方案与本地 MP4 双分支验收并保存截图/产物。证据：`CONTENT-20260725-000002 r1` 同源生成 ready 直播间方案与 QC-passed 成片；本地 MP4 为 1080x1920/H.264/AAC/30 秒，五类产物和两张完整页面截图均记录 SHA-256；详见 `docs/evidence/customer-v1-v1-0515-dual-branch.json`。

## 2. Release B：数据反馈与复用

### 2.1 运营数据与内容归因

- [x] `V1-0601` 客户可下载 CSV/XLSX 模板并导入场次、时间区间和运营指标文件。证据：`GET /api/functional-operations/import-template`、文件上传预览/确认工作区、CSV/XLSX 往返解析测试及 PostgreSQL 导入测试。
- [x] `V1-0602` 导入预览展示字段映射、时区/单位、错误行和重复行，确认后才入库。证据：`OPS-IMPORT-*` 批次/行封存、字段别名映射、IANA 时区/数值/区间校验、文件内与数据库重复识别；后端 8 passed、前端 Operations 9 passed。
- [x] `V1-0603` 场次必须绑定实际使用的内容修订/草稿或成片；无法绑定的数据进入待处理列表。证据：三类精确绑定解析、版本化 `functional_operation_session_bindings`、待处理修正 UI/API；验收批次分别产生 resolved 场次和 pending 场次且原文件可下载。
- [x] `V1-0604` 系统把指标按显式 TimeMapping 对齐到节目段/场景/时间轴，而不是按标题猜测。证据：导入文件显式声明来源时钟、偏移、漂移和覆盖区间；内容时间线支持 `MaituSceneBlueprint`、`TimelineSegment/Shot`、`ProgramSegment` 三类投影，事件桶只按匹配的版本化 TimeMapping 落段；时间映射单测及 PostgreSQL 链路测试通过。
- [x] `V1-0605` 客户可查看场次、内容段、模板和素材维度的描述统计与关联结果。证据：归因报告返回 `operation_session/content_segment/content_template/material` 四组独立统计，页面并列展示指标值、场次/区间/时长和成员来源；backend 4 passed、frontend Operations 9 passed。
- [x] `V1-0606` 所有效果结果标注证据等级和样本范围；v1 不把相关性描述成因果结论。证据：报告固定 `descriptive/associational` 证据等级、冻结纳入场次/展示区间/指标定义/TimeMapping，UI 明示“四维不可相加且不代表因果效果”，每个维度成员保持 `effect_eligible=false`。
- [x] `V1-0607` 客户可更正映射并生成新归因版本，原始导入文件和旧结果保持可追溯。证据：TimeMapping、内容绑定和 Exposure 均采用追加修订/替代而不覆盖，报告复算写入 `supersedes_report_code`；导入批次保留原文件、SHA-256、原始行和历史报告，前后端更正测试与 PostgreSQL 6 项集成测试通过。
- [x] `V1-0608` 用一份真实或脱敏运营文件完成导入到内容区间报表的端到端验收。证据：`customer-v1-v1-0608-operations-import.csv` 经预览确认生成 `OPS-20260725-000029`，显式 TimeMapping 将 3 个 MaituScene 区间 100% 对齐，`ATTR-20260725-000016` 展示场次/内容段/素材维度且均不可作为效果信号；原文件往返 SHA-256、API 断言和两张真实 UI 截图详见 `docs/evidence/customer-v1-v1-0608-operations.json`。

### 2.2 知识投影与效果驱动复用

- [x] `V1-0701` PostgreSQL 可查询素材、事实、模板、内容修订、场景、交付和效果之间的来源边。证据：`knowledge-lineage.v2` 投影新增 ProductFactCard、MaituSceneBlueprint、LayerBlueprint、DeliveryAttempt 节点及 `CITES/CONTAINS_SCENE/CONTAINS_LAYER/USES_ASSET/DELIVERED_BY/OBSERVES_SCENE` 来源边；同键多区间关系合并但保留全部 `source_records`；真实库构建 110 节点/104 边。
- [x] `V1-0702` 知识库页面支持按商品/主题/模板/素材查找并打开完整来源链。证据：`GET /api/functional-knowledge/graph-search` 对当前 PostgreSQL 投影执行分范围匹配和双向最多六跳来源链，页面支持结果选择、中文实体/关系、链路节点和证据状态；真实主题与素材查询通过，frontend knowledge 21 passed。
- [x] `V1-0703` 图投影具有版本和重建命令；Neo4j/Milvus 不可用时核心客户流程仍可运行。证据：本地 projection 修订、ontology 版本、source watermark、snapshot fingerprint、stale 比对和 `POST .../graph-projections/rebuild` 均由 PostgreSQL 提供；当前 v2 真实投影 `GRAPH-20260725-000001 r1` 为 current，后端聚焦 6 passed。
- [x] `V1-0704` 推荐同时使用约束匹配、内容相关性和有足够样本的效果信号，并展示各部分理由。证据：`effect-aware-advisory.v1` 按约束 45%、内容 40%、合格效果 15% 计算模板/素材建议，API 和学习页逐项返回并展示三部分得分、理由及证据；真实验收库 `CONTENT-20260725-000002` 返回 7 个素材候选，backend recommendation 3 passed、frontend learning 7 passed。
- [x] `V1-0705` 低证据或小样本效果只作提示，不自动形成硬约束或发布内容。证据：效果信号仅在 `approved + associational + >=3 场 + 报告与指标门禁通过` 时计分；描述性、未批准、小样本及阻断信号仍展示但贡献固定为 0，推荐模式固定 `advisory_only`，无自动写入/发布命令；领域门禁测试通过。
- [x] `V1-0706` 客户可从一个有效项目发起“基于效果再生成”，明确选择保留/替换的模板、段落和素材。证据：学习页对已确认效果提供变更假设及模板、主题/故事/设计、剧本段落、生产素材逐项保留/替换；事实引用段落锁定；替换候选来自当前项目三维建议。frontend learning 7 passed，其中完整请求断言覆盖三类替换。
- [x] `V1-0707` 再生成产生新的内容和生产修订，完整保留原项目、效果证据和人工选择来源。证据：服务从冻结效果快照创建并确认新 ContentProject/DesignBrief/Story/Script/Program/ShotList，再创建 `draft` ProductionVariantRevision；DecisionLog 与 source refs 固定原项目、效果、新项目、生产修订指纹及全部人工选择。真实 PostgreSQL 集成测试通过，且撤销效果不能再次生成。
- [x] `V1-0708` 用一次已导入场次完成效果洞察到新方案的端到端验收并保存截图。证据：`OPS-20260725-000029` / `ATTR-20260725-000016` 创建并确认 `EFFECT-20260725-000009`，显式保留主题、故事、3 个剧本段和 3 份素材，生成 `CONTENT-20260725-000016` 完整内容链与 `VARIANT-20260725-000012` 非执行草稿；效果贡献保持 0。证据 JSON：`docs/evidence/customer-v1-v1-0708-effect-reproduction.json`；截图：`customer-v1-v1-0708-learning.png`、`customer-v1-v1-0708-content-project.png`。

## 3. 测试、体验反思与发布判断

- [x] `V1-0801` 后端单元/契约测试、数据库集成测试和前端单元测试全部通过；环境缺失导致的跳过项单列，不冒充通过。证据：全新数据库顺序重放 103 个迁移后 backend 904、frontend 142、browser-use 388、live-research 30、Kokoro HTTP 4 项全部通过，无跳过；TypeScript、三套生产构建与 Ruff 通过，详见 `docs/evidence/customer-v1-v1-test-matrix.md`。
- [x] `V1-0802` 在桌面和移动视口走查 Release A/B 主流程，无文本溢出、遮挡、空白画布或不可达操作。证据：1440x1000 与 390x844 下逐页深链走查素材、录屏模板、内容、直播间、成片、运营、归因、知识、效果学习共 18 个状态；根级溢出/同级操作重叠/不可达控件/空白画布/运行时错误均为 0，8 张截图经人工复核。同步修复可刷新 `/console/...` 深链、素材筛选布局及移动归因场次高度，详见 `docs/evidence/customer-v1-v1-0802-responsive-walkthrough.json`。
- [ ] `V1-0803` 用新运营用户在不看说明文档的情况下完成五个任务：找素材、做模板、生成方案、产出草稿/视频、导入并查看效果。
- [ ] `V1-0804` 记录每个任务的成功率、耗时、错误次数和需要工程师介入的步骤，形成体验基线。
- [x] `V1-0805` 对 loading、empty、error、partial、stale、冲突和手工降级状态逐一做故障注入验证。证据：七态均有客户可见结果；前端专项 45、后端冲突 2、browser-use 人工降级 3 项通过。partial 保留可用数据并点名缺口，stale 保留本地编辑，人工降级不自动重试或写入，详见 `docs/evidence/customer-v1-v1-0805-fault-injection.md`。
- [x] `V1-0806` 复盘所有对外承诺与真实证据，删除或改写任何“代码存在即能力可用”的呈现。证据：逐领域对照表 `docs/evidence/customer-v1-v1-0806-promise-evidence-audit.md`；平台值守改为待验证增强项，麦兔 `read_room` 因缺少当前契约指纹从 `verified` 降为 `manual_only`；backend 2、frontend 12 项专项测试及 TypeScript 通过。
- [x] `V1-0807` 建立未完成/已知限制清单，按客户影响排序；安全冗余不得挤占 P0/P1 客户问题。证据：`docs/evidence/customer-v1-v1-known-limitations.md` 按 P0 外部结果、P1 首用体验、P2 主动边界排序；所有待提供输入集中在 `docs/evidence/customer-v1-v1-external-acceptance-inputs.md`，不阻塞本地工作。
- [ ] `V1-0808` 产品与实际运营用户完成最终验收，明确 Release A、Release B 的可用结论和下一轮范围。

## 4. 执行记录

| 日期 | 条目 | 结果 | 证据 | 已知限制 |
| --- | --- | --- | --- | --- |
| 2026-07-26 | `V1-0001` | done | ADR-0003 | 单团队 v1，不代表企业生产就绪 |
| 2026-07-26 | `V1-0002` | done | 新旧 checklist 状态与互链 | 原 577 项仍保留供后续生产化 |
| 2026-07-26 | `V1-0101`-`V1-0102` | done | 能力矩阵 API、确定性指纹、2 条后端测试 | `verified` 不等于所有变更已通过 canary |
| 2026-07-26 | `V1-0103`-`V1-0105` | done | 直播间边界带、保守禁用和页面测试 | 自动写入当前明确不可用，方案生成不受阻 |
| 2026-07-26 | `V1-0106` | done | backend 2 passed；frontend 9 passed；TypeScript passed | 数据库集成与全量测试在发布判断阶段统一执行 |
| 2026-07-29 | `V1-0201` | done | 扫描并导入当前本地素材 63 份；当前素材预览 63/63 返回 206；前端真实浏览器首屏展示图片缩略图；导入报告已落盘 | 旧验收/兼容记录仍保留在库中；麦兔自动上传仍受能力矩阵控制 |
| 2026-07-26 | `V1-0202`-`V1-0204` | done | 三轴分类、结构化约束与桌面关系测试 | 素材权利字段尚未完成 |
| 2026-07-26 | `V1-0206`-`V1-0210` | done | 素材包、直播间选材、覆盖、缺口和选择解释测试 | 素材权利门禁与真实样例验收仍开放 |
| 2026-07-26 | `V1-0205` | done | 分组改名/说明/成员/软删除；backend 2 passed，frontend 11 passed | 删除为软归档，历史计划与包引用保留；3 条 DB 测试因未配置 PostgreSQL 跳过 |
| 2026-07-26 | `V1-0211` | done | 四态使用依据、计划硬门禁和 release rights snapshot；backend 6 passed，frontend 21 passed | v1 不建设复杂 RightsGrant/地域渠道策略；状态由可信运营人员维护 |
| 2026-07-26 | `V1-0212` | done | 可重复四角色脚本、4 份约束指纹、分组回读、1440px 实际素材页截图 | 使用验收库的已批准样例；客户真实素材仍需在首次业务验收中确认内容与权利依据 |
| 2026-07-26 | `V1-0301` | done | 本地录屏表单、XHR 上传进度、ffprobe/checksum 校验、上传型 CaptureSession/时间线/分析 DAG；backend 9 passed/1 DB skipped，frontend 15 passed | 真实录屏端到端与 PostgreSQL 集成环境仍在 `V1-0308`/`V1-0801` 验收；自动采集不是前提 |
| 2026-07-26 | `V1-0302` | done | 四步解析 Worker、全局时间线、步骤级错误/重试；Worker 30 passed，focused backend 19 passed/1 skipped，frontend 18 passed | OpenAI/DeepSeek provider 需配置外部 API；真实供应商结果由 `V1-0308` 验收 |
| 2026-07-26 | `V1-0303` | done | ASR 勾选/纠错/脱敏/合并及 reviewed examples 来源区间；前端交互测试通过 | v1 只内置中国手机号和人民币金额辅助隐去，运营人员仍负责最终清洗 |
| 2026-07-26 | `V1-0304` | done | 单来源直播间 repository 门禁与稳定错误码；contract 9 passed | PostgreSQL 集成用例存在但因未配置 `ASSETGRAPH_TEST_DATABASE_URL` 跳过 |
| 2026-07-26 | `V1-0305` | done | summary/projection 三类状态字段、三状态 UI 和录屏证据深链；API/UI 回归通过 | 外部录屏布局仍固定为 approximate/none + reference_only |
| 2026-07-26 | `V1-0306` | done | 审核、发布、新修订、软停用与历史 projection 保留；migration 100、路由/API/UI 测试 | 停用恢复功能不在 v1；数据库集成待测试库执行 |
| 2026-07-26 | `V1-0307` | done | 本地上传与平台采集解耦、可选增强文案和回退测试 | 平台无人值守采集不作为 v1 承诺 |
| 2026-07-26 | `V1-0401` | done | 事实卡草稿、新版本、批准/驳回与版本状态；knowledge 19 passed | v1 由可信运营人员审核，不建设复杂审批权限 |
| 2026-07-26 | `V1-0402`-`V1-0404` | done | 完整目标输入、可编辑 DesignBrief、主/次模板与贡献建议；content frontend 16 passed | 真实业务内容验收保留在 `V1-0412` |
| 2026-07-26 | `V1-0405` | done | StoryBrief/ScriptBlock/ProgramSegment/ShotList、FactCitation 和来源深链 | 相关 PostgreSQL 集成用例存在；本机未配置测试库导致 35 项跳过 |
| 2026-07-26 | `V1-0407` | done | 独立 `MaituSceneBlueprint`/Layer 关系表、投影 API 与可见场景 UI | 麦兔真实写入能力仍按 0501-0506 单独验收 |
| 2026-07-26 | `V1-0406` | done | 批准事实过滤、冲突预检、FactCitation 门禁、稳定错误码与分类型修复提示；frontend 17 passed | 事实真实性仍取决于运营人员批准的来源证据，不由生成器自行断言 |
| 2026-07-26 | `V1-0408` | done | 场景重排、标题/话术、逐场景素材、归一化矩形和层级编辑；保存后重跑硬约束并派生新 Plan/Variant/BuildPlan；backend 6 passed、frontend 11 passed、TypeScript passed | PostgreSQL 集成用例已提供但当前测试库未配置；真实麦兔写入仍由 0501-0506 验收 |
| 2026-07-26 | `V1-0409` | done | 持久化 BuildPlan 动作白名单、固定素材/图层身份和 `go_live=false`；后端构造测试通过 | 仅证明计划契约；麦兔是否能真实完成每类动作由 0501-0506 验收 |
| 2026-07-26 | `V1-0410` | done | 内容链、素材快照、场景/图层和 BuildPlan 操作追溯；门禁 remediation 直接展示；前端交互测试通过 | 原始 compiler reason 仍保留机器码，客户主要按门禁修复建议操作 |
| 2026-07-26 | `V1-0411` | done | 新房间克隆表单/API、重新编译、状态清空、原目标拒绝与自动切换；前端交互及 PostgreSQL 契约测试 | 空白状态在实际执行前读取核对，不在仅生成方案时访问麦兔 |
| 2026-07-26 | `V1-0501` | done | ID/标题/working/空白/未开播五项写前预检，持久化 handoff 一致性与后端回读复核；backend 34 passed、worker 28 passed | 麦兔字段按真实 working-room `name` 契约核对；真实空房 canary 仍由 `V1-0506` 验收 |
| 2026-07-26 | `V1-0504`-`V1-0505` | done | readback v2 逐项对比、完整人工清单与客户可见 UI；backend 4 passed、frontend 12 passed、TypeScript passed | 真实麦兔变更能力仍按 capability matrix 保守标为 manual；不以模拟或人工操作冒充 canary |
| 2026-07-26 | `V1-0510` | done | confirmed 内容链与来源 live-room material snapshot/Variant 修订/指纹共同冻结，Video UI 展示共享来源；backend 28 passed、frontend 6 passed | rendered_video 专用本地媒体是分支增量而非强行复用不可渲染的麦兔素材；PostgreSQL 场景待测试库运行 |
| 2026-07-26 | `V1-0511`-`V1-0512` | done | 1080x1920 确定性三轨时间轴、TTS/ASS/FFmpeg 任务、可播放预览、完整时间轴编辑和不可变修订；backend 82 passed、frontend 6 passed | 本次聚焦测试不替代 `V1-0801` 的全量数据库与工具链验收 |
| 2026-07-26 | `V1-0513`-`V1-0514` | done | MP4/封面/字幕/manifest 客户入口、分阶段失败修复、timeline/manifest 指纹和重试差异 UI；backend 83 passed、frontend 8 passed、TypeScript/Ruff passed | 真实整链 MP4 样例与双分支截图仍由 `V1-0515` 验收 |
| 2026-07-26 | `V1-0515` | done | 同一 confirmed ContentProject r1 生成 LIVEPLAN/VIDPLAN；本地 Kokoro+FFmpeg 输出 13.4 MB QC-passed MP4、封面、字幕、manifest、联系表及 1440px 完整页面截图 | 麦兔分支只验收可审阅 BuildPlan，未执行真实麦兔草稿写入，也未请求开播；首次 55 秒任务因长静音/标点完整性真实失败并保留，修复后以合法 30 秒目标通过 |
| 2026-07-26 | `V1-0601`-`V1-0603` | done | CSV/XLSX 模板、5 MB/5000 行本地解析、预览后确认、字段/时区/单位/错误/重复检查、三类内容绑定与待处理修订；backend 8 passed，frontend 9 passed | 原文件以 BYTEA 保存在 PostgreSQL，适合 v1 小文件；平台自动事件流仍不在本批客户范围 |
| 2026-07-26 | `V1-0604`-`V1-0607` | done | 显式版本化 TimeMapping 对齐三类内容时间线；场次/内容段/模板/素材四维统计；证据等级、样本范围、追加式更正和归因复算；backend 4 passed、PostgreSQL 6 passed、frontend 9 passed、TypeScript/Ruff passed | 当前结果仅描述或关联观察，不提供因果推断；真实脱敏文件端到端截图由 `V1-0608` 单独验收 |
| 2026-07-26 | `V1-0608` | done | 3 行脱敏 CSV -> 1 个 resolved 场次 -> 显式 TimeMapping -> 3 个 aligned MaituScene 区间 -> 描述性报表；源文件往返校验、可重复验收脚本、1440px 导入/归因截图 | 样例没有固定已发布指标定义或真实交付 Release，因此报告如实标为 `insufficient_data/descriptive`，不冒充可发布效果结论 |
| 2026-07-26 | `V1-0701`-`V1-0703` | done | `knowledge-lineage.v2` 本地 PostgreSQL 版本化投影；商品/主题/模板/素材搜索和双向来源链 UI；真实库 110 节点/104 边，backend 6 passed、frontend 21 passed、TypeScript/Ruff passed | 当前验收库没有事实卡、已发布模板、Release/Delivery/Effect 实例，相关边由含完整实体的单元契约验证；核心流程不依赖 Neo4j/Milvus |
| 2026-07-26 | `V1-0704`-`V1-0705` | done | `effect-aware-advisory.v1` 三维建议评分及原因 UI；严格效果证据计分门禁；真实项目返回 7 个候选，backend 7 passed、frontend 7 passed、TypeScript/Ruff passed | 当前真实项目没有合格关联性效果，效果分如实为 0；合格信号加分由领域测试覆盖，不伪造真实效果数据 |
| 2026-07-26 | `V1-0706`-`V1-0707` | done | 效果再生产逐项选择 UI；新内容全链与 `draft` ProductionVariantRevision；来源指纹和人工选择 DecisionLog；backend 8 passed（含 PostgreSQL）、frontend 7 passed、TypeScript/Ruff passed | 再生产结果明确停在不可执行草稿，不自动确认生产变体、不创建 Release/Delivery |
| 2026-07-26 | `V1-0708` | done | 已导入运营场次 → 描述性效果提示 → 人工确认 → 显式保留输入 → 新内容全链与生产草稿；JSON、两张 1440px 实际 UI 截图及 checksum 已保存 | 来源报告仅 1 场且指标未固定，因此效果如实不计分；这正是弱证据门禁的真实验收，不伪造关联性结论 |
| 2026-07-26 | `V1-0801` | done | 全新 PostgreSQL 数据库顺序应用 103 个迁移；backend 904、frontend 142、browser-use 388、live-research 30、Kokoro 4；typecheck/build/Ruff 全通过 | Console 主包 933.85 kB，需在后续做路由级拆包；完整命令和缺陷回归见 `docs/evidence/customer-v1-v1-test-matrix.md` |
| 2026-07-26 | `V1-0802` | done | 两视口 x 九工作区自动审计、8 张实际页面截图及人工复核；可刷新 Console 深链 | 长内容页仍依赖纵向滚动；移动端归因场次已限制为内部滚动区 |
| 2026-07-26 | `V1-0805` | done | loading/empty/error/partial/stale/conflict/manual 七态；frontend 45、backend 2、worker 3 | 外部供应商与真实麦兔故障仍不得以测试替代 canary |
| 2026-07-26 | `V1-0806` | done | 全域承诺/证据审计；平台采集文案降级，麦兔读取降为 `manual_only`；真实登录页探测后修复 SPA 瞬态误判；最终 backend 904、frontend 142、browser-use 388 通过 | 历史截图保留为历史证据，但不再冒充当前契约可用性；只读尝试见 `docs/evidence/customer-v1-v1-0107-maitu-readonly-attempt.md` |
| 2026-07-26 | `V1-0807` | done | P0/P1/P2 已知限制与一次性外部验收输入清单 | P0 外部 canary 和真实业务样例、P1 新用户测试仍保持开放 |

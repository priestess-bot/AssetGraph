# AssetGraph 前端产品化改造实施 Checklist

> 状态：实现完成，等待产品负责人验收
> 日期：2026-07-28
> 上位范围：[客户体验优先 v1 Checklist](./2026-07-26-customer-experience-v1-implementation-checklist.md)
> 产品设计：[直播内容生产与运营闭环设计](./2026-07-22-live-content-production-operations-closed-loop-design.md)
> 目标：把当前面向后端对象的功能集合改造成面向直播运营人员的统一桌面产品。

## 0. 执行规则

- 每完成一个条目，立即将 `[ ]` 更新为 `[x]` 并填写代码、测试、截图或文档证据。
- 正式界面不得显示内部状态码、告警码、数据库主键、指纹、Schema 或原始 JSON；直播间 ID、来源直播间 ID、外部场次 ID 和 SKU 等业务标识除外。
- 资源使用列表/详情，创建任务使用分步流程，直播间与成片使用固定编辑工作区，运营使用概览到下钻的分析界面。
- 只验收桌面端 `1440x900` 与 `1920x1080`；本轮不投入移动端适配。
- 一次性切换统一 Console；不保留新旧界面切换开关，不新增兼容观察期。
- 本清单只改变前端产品表达，不扩大麦兔能力矩阵，不实现正式排播、授权或开播。

## 1. 范围与工程基线

- [x] `FUX-0001` 建立独立实施清单并关联 v1 总清单。证据：本文档。
- [x] `FUX-0002` 盘点所有正式路由、用户任务、原始技术字段和可复用 API。证据：正式页面/API 枚举及 `code/pre/JSON/fingerprint/schema` 扫描结果；旧页面规模与泄漏点已记录到本次实施上下文。
- [x] `FUX-0003` 固化统一信息架构、页面模型与路由映射。证据：`frontend/src/product/routes.ts` 的七个一级业务入口及旧深链归一化映射。
- [x] `FUX-0004` 增加所需前端依赖并将构建收敛为单一 Console。证据：`frontend/package.json`、`frontend/vite.config.ts`；已安装 Router、Table、Form/Zod、Recharts、dnd-kit 与 Radix，构建脚本只产出 Console。
- [x] `FUX-0005` 建立改造前后测试基线并记录已知环境限制。证据：`docs/evidence/frontend-product-redesign-test-baseline-2026-07-28.md` 记录前端 74 项、后端 767 项通过结果、138 项数据库环境跳过及生产包体提醒。

## 2. 产品语言与数据边界

- [x] `FUX-0101` 建立集中式业务状态、对象类型、动作和错误文案注册表。证据：`frontend/src/workbench/productLanguage.ts`。
- [x] `FUX-0102` 未注册状态使用可理解的中文兜底，不回显原始值。证据：`productLabel/productCopy/problemPresentation` 集中兜底。
- [x] `FUX-0103` Problem 展示只包含影响和下一步，不显示错误码、trace、证据引用或后端英文原文。证据：`frontend/src/workbench/components.tsx` 和 API 英文错误截断。
- [x] `FUX-0104` 任务、通知和全局搜索改用业务标题、摘要、动作和目标，不显示内部编号。证据：`frontend/src/console/ConsoleApp.tsx`；任务/通知内部 code DOM 已移除，搜索显示对象名称与更新时间。
- [x] `FUX-0105` 所有页面移除 `<pre>`、`JSON.stringify`、指纹和 Schema 的正式展示。证据：正式页面统一通过业务组件展示，`npm run check:product-copy` 的 AST 门禁覆盖 12 个正式页面并通过。
- [x] `FUX-0106` 表单中的内部 code 输入改为名称输入或实体选择，稳定 code 由系统生成。证据：项目、模板、素材、事实、直播间、成片、场次绑定、指标和效果再生产表单均使用名称输入或业务对象选择器；内部标识只作为隐藏提交值。
- [x] `FUX-0107` 建立禁止技术值泄漏的自动扫描测试。证据：`frontend/scripts/check-product-copy.mjs`、`check:product-copy` npm 命令及 `productLanguage.test.ts`；门禁与 7 项聚焦测试通过。

## 3. 设计系统与统一壳层

- [x] `FUX-0201` 建立颜色、排版、间距、边框、阴影和层级设计变量。证据：`frontend/src/product/product.css`。
- [x] `FUX-0202` 建立 Button、IconButton、Field、Select、Tabs、Badge、Empty、Notice、Drawer、Dialog 等基础组件。证据：`frontend/src/product/components.tsx`、共享 workbench 组件和产品样式覆盖层。
- [x] `FUX-0203` 建立资源表格、筛选栏、批量操作栏、详情检查器和步骤条组件。证据：共享 `product/components.tsx` 及素材/模板/运营页面的资源表、筛选、多选批量操作、固定详情与步骤条。
- [x] `FUX-0204` 重做桌面侧栏、顶部项目搜索、任务抽屉和全局通知。证据：统一 232px 导航、64px 顶栏和 480px 任务抽屉；`npm run typecheck` 通过。
- [x] `FUX-0205` 导航收敛为概览、素材、模板、知识、内容项目、运营和效果学习。证据：`PRODUCT_ROUTES` 为正式导航唯一来源。
- [x] `FUX-0206` 页面统一标题、主操作、面包屑、加载、空状态、错误和保存反馈。证据：共享 `PageHeader/LoadingBlock/EmptyBlock/InlineNotice`、编辑器顶部路径与底部保存区统一承接；20 张双尺寸正式页面截图和逐页主任务复核通过。
- [x] `FUX-0207` 键盘焦点、对比度、弹层关闭和表单标签达到基础可访问性要求。证据：全局 `:focus-visible`、Radix Dialog/Tooltip/Tabs 语义及现有显式 label；视觉验收仍由 FUX-0905/0906 覆盖。

## 4. 概览与全局协作

- [x] `FUX-0301` 后端提供业务概览聚合 API，包含趋势、内容排行、数据覆盖与最近项目。证据：`GET /api/console/business-overview`、`ConsoleRepository.business_overview` 及前端归一化契约。
- [x] `FUX-0302` 首页展示内容产出、直播/成片交付、运营表现和数据覆盖概览。证据：`frontend/src/console/BusinessOverviewPage.tsx` 的指标带、趋势、排行、资料覆盖与最近项目。
- [x] `FUX-0303` 首页趋势和内容排行支持时间范围及业务下钻。证据：30/90 天范围、Recharts 趋势图和项目/运营链接。
- [x] `FUX-0304` 全局任务抽屉以“要做什么、影响什么、去哪里处理”呈现。证据：后端任务投影按业务对象生成中文标题/摘要并统一进入项目动态；前端不显示任务编号。
- [x] `FUX-0305` 全局搜索按素材、模板、知识和项目分组，并使用业务名称。证据：Console 搜索 SQL 只投影四类业务资源，新路由和业务对象标签已接入。

## 5. 素材、模板与知识

- [x] `FUX-0401` 素材页改为筛选区、网格/表格切换、批量工具栏和右侧详情检查器。证据：`AssetLibraryProductPage` 的正式素材视图和固定详情检查器。
- [x] `FUX-0402` 素材详情以“基本信息、用途、约束、分组、使用情况”组织编辑。证据：基本信息/使用状态/布局约束标签及独立素材组工作区。
- [x] `FUX-0403` 素材约束改为图形化位置、尺寸、层级和关系编辑，不要求理解约束枚举。证据：9:16 位置预览、归一化几何输入、等比开关、层级分段控件和桌面摆放开关；保存时转换为结构化规则。
- [x] `FUX-0404` 素材分组、素材包、分析和导入形成清晰的页内视图，不跳独立旧站。证据：`AssetLibraryProductPage` 五个页内视图；真实支持导入、批量分组/用途、素材包创建发布、缺口登记解决和分析分歧裁决；`npm run typecheck` 通过。
- [x] `FUX-0411` 模板页合并来源直播间、录屏、策略、草稿和已发布模板。证据：`TemplateLibraryProductPage` 将状态筛选、模板详情和录屏解析收敛为两个页内视图。
- [x] `FUX-0412` 录屏导入使用“上传、解析、清洗、审核”四步流程。证据：`RecordingWizard` 调用真实上传、解析查询与内容策略模板创建 API。
- [x] `FUX-0413` 清洗界面同步展示视频、转写、画面文字和片段时间位置。证据：解析步骤并列视频/四类分析进度，清洗步骤并列播放器和带时间的可编辑语音片段；录屏视图持续同步视频与转写。
- [x] `FUX-0414` 模板列表与详情以业务就绪度、布局可信度、可构建性和来源证据呈现。证据：模板卡片和右侧详情的三维状态、内容结构、时间区间及外部录屏使用边界。
- [x] `FUX-0421` 知识页使用事实卡列表和来源/引用检查器，隐藏版本内部编号。证据：`KnowledgeProductPage` 的事实卡、来源表和右侧事实/使用检查器。
- [x] `FUX-0422` 事实创建、审核、批准、驳回和新修订具有明确的任务动作与反馈。证据：事实/来源编辑 Dialog、事实批准/驳回和创建新版本操作。

## 6. 内容项目与生成流程

- [x] `FUX-0501` 新建项目使用分步流程，必填直播间 ID、标题和生成目标，可补充主题、故事与详细设计。证据：`ProjectCreateDialog` 的四步表单与 Zod/RHF 校验。
- [x] `FUX-0502` 模板选择限制一个主参考和多个次参考，并解释各模板建议贡献。证据：主参考单选、最多五个次参考及就绪度/可构建性说明。
- [x] `FUX-0503` 素材选择分为素材组和零散素材，支持当前项目覆盖约束。证据：第四步独立选择并写入项目 JSON 快照；项目级覆盖继续由直播间标签承接。
- [x] `FUX-0504` 项目详情建立简报、剧本、直播间、成片、交付和动态六个业务标签。证据：`ProjectWorkspace` 六标签统一入口。
- [x] `FUX-0505` 后端提供项目工作区摘要 API，避免前端拼接内部对象。证据：`GET /api/content-projects/{project_code}/workspace-summary`。
- [x] `FUX-0506` 简报页可确认和新建修订，明确显示生成目标、事实范围和模板贡献。证据：简报整理、确认、生成动作及项目参考摘要。
- [x] `FUX-0507` 剧本页按节目段和话术块编辑，事实引用可从业务来源下钻。证据：话术块编辑器保存新剧本修订，并以事实卡/原文来源名称和引用内容展示事实依据；点击后进入知识库并自动打开对应事实详情或高亮来源；`npm run typecheck` 与产品文案门禁通过。

## 7. 直播间、成片与交付

- [x] `FUX-0601` 直播间使用左侧场景/图层、中央 9:16 画布、右侧属性、底部固定操作区。证据：`LiveRoomEditorProductPage/LiveRoomEditor` 的固定三栏一底布局，同时用于独立深链和项目内标签。
- [x] `FUX-0602` 场景、图层、素材、位置尺寸、层级和话术可在同一工作区编辑。证据：场景增删排序、图层素材/用途/几何/z-order、画布同步预览和话术编辑均保存为 Blueprint 新修订。
- [x] `FUX-0603` 麦兔能力以“可自动完成/需人工完成/暂不支持”呈现，不暴露适配器状态值。证据：`CapabilityPanel` 的三态业务映射；自动不可用时保留人工操作清单。
- [x] `FUX-0604` BuildPlan 转成中文操作清单；自动草稿、人工交接和执行回读有清晰状态。证据：`operationTitle` 将操作投影为中文步骤，底部展示草稿状态、写入与同步回读动作；`npm run typecheck` 通过。
- [x] `FUX-0611` 成片使用播放器、属性检查器和横向时间轴的一体化工作区。证据：`VideoEditorProductPage/VideoEditor` 的播放器、镜头/制作检查器与画面/字幕/音频三轨固定布局。
- [x] `FUX-0612` 镜头顺序、时长、素材、字幕、音量和海报时间可直接编辑并保存新修订。证据：镜头属性与时间轴控件调用真实 `updateTimeline`；已完成成片可建立编辑副本。
- [x] `FUX-0613` 渲染进度、产物、质检和失败修复以制作阶段呈现，不显示任务内部类型。证据：制作阶段中文投影、进度条、成片/封面/镜头总览下载、媒体质检摘要及重新制作动作；`npm run typecheck` 通过。
- [x] `FUX-0621` 发布能力合并到项目交付标签，提供目标、检查、交付和撤回动作。证据：`DeliveryProductPanel` 的业务检查、批准/退回、手工交接目标、交付包下载/记录和撤回；后端补充 validate、delivery-package、revoke 命令，不伪造第三方投递。
- [x] `FUX-0622` 项目动态合并关键版本、生成、渲染、交付和运营关联事件。证据：项目工作区摘要 API 的 `activity` 聚合及 `ActivityPanel` 统一时间线，任务/通知也下钻至该标签；前端 `npm run typecheck` 与后端 `compileall` 通过。

## 8. 运营、归因与效果学习

- [x] `FUX-0701` 场次导入使用下载模板、上传、字段确认、错误修复和入库的分步流程。证据：`OperationsProductPage/ImportWorkspace` 的四步步骤条、真实 CSV/XLSX 预览、逐行业务问题及确认入库动作。
- [x] `FUX-0702` 待关联场次以业务对象选择器修复，不要求输入项目或修订 code。证据：`BindingsWorkspace` 聚合项目、直播间方案和成片名称，内部绑定值不进入可见表单。
- [x] `FUX-0703` 归因页提供场次、内容段、模板和素材四个一致的分析视图。证据：`AnalysisWorkspace` 的四维分段视图和统一排行表达。
- [x] `FUX-0704` 图表明确展示时间范围、指标定义、样本量和证据等级，避免因果化文案。证据：分析控制栏、样本量、更新时间、证据标签及固定“关联趋势不代表因果”提示。
- [x] `FUX-0705` 指标配置合并到运营设置，指标编码由系统生成。证据：`MetricSettings` 只收集业务名称、含义、单位、汇总方式和数据来源，稳定编码由浏览器生成且不展示；`npm run typecheck` 通过。
- [x] `FUX-0711` 效果学习页按证据、影响、建议动作和可复用范围组织候选规律。证据：`LearningProductPage/PatternCard` 的指标、样本、证据强度、推荐影响和模板/剧本/素材复用范围。
- [x] `FUX-0712` 规律接受、拒绝和再生产操作使用业务文案，并能回到来源内容。证据：规律库真实接入接受、忽略、创建项目草稿及来源项目链接；项目建议只显示名称、匹配理由和业务评分；`npm run typecheck` 通过。

## 9. 旧界面退役

- [x] `FUX-0801` 从正式导航和路由移除排播、数据治理、治理运行独立页面。证据：正式导航和 Workspace 均不再注册三类页面。
- [x] `FUX-0802` 治理运行的用户可见任务并入全局任务抽屉和项目动态。证据：`ConsoleRepository.list_tasks/list_notifications` 将人工任务和异常统一投影为中文业务任务并指向 `/projects?view=activity`；Console 对遗留治理链接做同一归一化。
- [x] `FUX-0803` 删除 `/maitu/` 与 `/live-research/` 独立前端构建和静态挂载。证据：`frontend/package.json`/`vite.config.ts` 单入口，`backend/app/main.py` 删除旧重定向与 StaticFiles 挂载。
- [x] `FUX-0804` 删除不再引用的旧路由适配、样式和演示数据。证据：已删除 10 组旧页面、`maitu/live-research` 独立入口及专属样式/演示数据；可复用模板推荐与事实冲突规则迁至 `content/selectionRules.ts`；统一 Console 聚焦测试 17 项和类型检查通过。
- [x] `FUX-0805` 更新入口、运行手册和旧前端退役文档。证据：README 和 `docs/reproducibility.md` 明确唯一 `/console/` 入口、七个业务区及生产深链；`docs/operations/legacy-frontend-retirement-checklist.md` 已改为一次性退役记录。

## 10. 测试、截图与反思

- [x] `FUX-0901` 新增产品语言、路由、组件交互和主要表单自动化测试。证据：`productLanguage.test.ts`、`routes.test.ts`、重写后的 `ConsoleApp.test.tsx/components.test.tsx` 及 `ProjectHubPage.test.tsx` 覆盖文案兜底、七入口、抽屉、搜索、错误边界和四步项目创建。
- [x] `FUX-0902` 新增业务概览与项目摘要 API 契约测试。证据：`test_console_routes.py::test_console_business_overview_returns_only_business_projection` 与 `test_product_workspace_routes.py`；聚焦后端 8 项测试通过并验证内部附加字段被响应模型过滤。
- [x] `FUX-0903` 前端类型检查、单测和生产构建全部通过。证据：`npm test` 13 个测试文件共 76 项全部通过；`npm run build` 完成类型检查并生成统一 Console 产物；`git diff --check` 通过。当前单 JS 包约 1.13 MB，作为后续按路由拆包的性能优化项记录，不阻断本轮功能验收。
- [x] `FUX-0904` 后端聚焦测试与完整回归通过，记录跳过项。证据：在 `backend/` 工作目录执行 `../backend/.venv/bin/pytest -q`，提交前复验结果为 771 passed、138 skipped、0 failed；跳过原因与边界已记录在测试基线文档。
- [x] `FUX-0905` 在 `1440x900` 对每个正式路由截图并检查溢出、遮挡和空白画布。证据：`npm run capture:product` 覆盖 10 个工作区，10 张截图全部通过；结构化结果见 `frontend-product-redesign-visual-audit-2026-07-28.json`。
- [x] `FUX-0906` 在 `1920x1080` 对每个正式路由截图并检查信息密度与视觉层级。证据：同一脚本生成 10 张 `1920x1080` 截图，横向溢出、不可达控件、非画布遮挡、空白和运行时错误均为 0；人工缩略总览通过。
- [x] `FUX-0907` 逐页检查主要任务是否能在不理解内部模型的前提下完成。证据：`frontend-product-redesign-visual-and-ux-review-2026-07-28.md` 记录 10 个工作区的用户主任务和通过结果。
- [x] `FUX-0908` 对照 Shopify 资源表、Figma 编辑器、Premiere 工作区和 Stripe 分析模式做设计复盘。证据：视觉与人机工效复核文档分别记录资源管理、画布编辑、时间轴和分析下钻的采用范围与复杂度边界。
- [x] `FUX-0909` 扫描全部正式页面，确认无内部码、指纹、Schema、原始 JSON 和英文后端错误泄漏。证据：AST 静态门禁覆盖 12 个正式页面且通过；20 个运行时首屏的 `leakedInternalTokens` 均为 0。
- [x] `FUX-0910` 记录仍需真实录屏、真实麦兔账号和产品负责人确认的外部验收项。证据：视觉与人机工效复核文档列出 5 类外部验收；详细输入批次和真用户任务脚本见 `customer-v1-v1-external-acceptance-inputs.md`。
- [x] `FUX-0912` 用真实前后端和验收数据库逐个页面、逐个工作流跑通客户主流程。证据：`frontend/scripts/accept-product-workflows.mjs`、`npm run accept:product-workflows`；18 个工作流 17 个通过、0 个失败、1 个仅因未启用真实麦兔写入而阻塞；结构化结果和截图见 `docs/evidence/frontend-product-workflow-acceptance-2026-07-29.json` 与同名 Markdown 记录。
- [x] `FUX-0913` 修复真实浏览器验收发现的客户可感知功能问题。证据：素材约束/素材包/素材缺口提交修复、素材组从已选素材直接创建并展示禁用原因、批量栏窄宽度换行、素材详情预览溢出修复、入口加载失败占位、内容项目四步向导跳步修复、视频编辑副本持久化编辑锁、MinIO 不可用时本地文件存储降级、录屏详情过滤内部子表外键；素材详情三个标签和素材组创建路径均通过真实浏览器检查，提交前前端 78 项测试与 TypeScript 检查通过。
- [x] `FUX-0914` 固化可重复验收命令和本地服务边界，清理重复项目进程。证据：`frontend/package.json` 的 `accept:product-workflows`、当前仅保留 Vite `5190`、FastAPI `8000` 和验收 PostgreSQL `55432`；真实录屏解析已跑通，只有麦兔写入继续按阻塞项记录，不伪造通过。
- [x] `FUX-0915` 移除未被产品要求的前端登录拦截，将工作台浏览与受保护操作解耦。证据：`frontend/src/console/ConsoleApp.tsx` 默认直接进入统一工作台；无控制台令牌时仅跳过受保护的任务/通知/概览/搜索请求，麦兔写入及控制台命令仍由后端门禁保护；`ConsoleApp.test.tsx` 新增无凭据入口回归测试，真实 Chrome 七个正式入口均确认无登录页、无页面异常。
- [x] `FUX-0916` 修复素材库真实浏览器复查发现的顶部叠层、素材预览和详情放大问题。证据：桌面端菜单按钮不再错误占据顶栏网格，任务/通知/工作区信息与“直播内容工作台、页面标题、搜索”保持同一顶栏区域；图片卡片改为完整显示，视频通过本地 FFmpeg 缓存首帧和 480px/6 秒低清悬浮预览，离开后回到首帧；图片/GIF 详情支持居中放大预览与键盘/关闭按钮退出；前后端聚焦测试和真实浏览器检查通过。
- [x] `FUX-0917` 修复素材预览传输过慢问题。证据：素材网格、分组选择、直播间选材和草稿画布改用服务端 FFmpeg 缓存的 480px WebP 缩略图；GIF 只生成首帧缩略图，详情放大仍请求原图；缩略图使用 checksum + 素材编号缓存并设置 24 小时缓存头，后端缩略图路由测试通过。
- [x] `FUX-0918` 清理真实验收库中反复执行 UI 验收留下的测试素材，避免测试数据污染客户素材库。证据：对 `assetgraph_v1_acceptance_20260726` 中 68 份验收残留执行软删除，保留 63 份实际导入的本地图片/视频；浏览器复查确认 `ui-acceptance`、`Compatibility asset` 等测试标题和无预览占位均不再出现在素材库。
- [x] `FUX-0919` 知识库不再直接展示历史测试数据中的英文标题、商品描述和来源摘录。证据：知识领域展示层对兼容性/追溯/引用测试事实及来源做中文业务投影，不改动后端证据原文与校验值；来源类型和版本状态补齐中文映射，并以单元测试及真实浏览器双标签页检查确认。
- [x] `FUX-0920` 建立面向直播运营人员的逐页操作手册，并以当前正式前端而非规划/API 作为功能边界。证据：`docs/assetgraph-console-operation-manual.md` 覆盖全局操作、7 个一级工作区及直播间/成片/交付生产工作区，共 109 个编号操作点；按适用情况记录入口、前置条件、步骤、成功标志、禁用原因与当前限制，并补充直播间方案、竖屏成片、运营归因再生产 3 条端到端 SOP。手册明确标注交付候选/授权、真实麦兔写入、历史录屏续清洗、事实来源绑定、场景和图层结构不可自由增删、初始成片 Worker 抢占、旧事实 50 条加载范围、专业时间轴、排播开播和实验等边界；细分按钮是否完成真实浏览器验收仍以工作流证据和后续测试记录为准，不以文档覆盖替代测试通过。
- [ ] `FUX-0911` 产品负责人完成最终视觉与人机工效验收。

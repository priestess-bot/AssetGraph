# AssetGraph 最终目标：数字人直播的内容生产线与数据闭环

## 1. 一句话定位

AssetGraph 是一个面向麦兔软件与数字人直播业务的内容生产与数据闭环系统。它的最终目标是两件事：

1. **形成要素，按剧本拼接要素，产出可发布内容。** 业务团队建立内容项目并提供目标、已核验事实和故事，由编剧、导演、影像、剪辑、场控等 AI 角色接力：把故事写成剧本，把节目拆成镜头，再把镜头投影为麦兔直播间草稿或确定性视频时间轴，经质量、权利和安全门禁形成不可变发布清单。
2. **把实际发布、曝光和运营数据挂回内容，形成可信数据 loop，评估角色。** 播出产生的现场状态、执行证据、真实内容曝光、评论互动、点击成交，都必须落到具体内容对象和策略分配上；系统严格区分描述、关联、准实验和随机实验，只有达到证据门槛的结果才能升级策略或影响下一轮生产。

多模态资产库、解析和知识图谱是支撑这两件事的底座，不是目标本身。

更简洁地说：AssetGraph 是数字人直播的 AI 内容剧组和数据大脑。

## 2. 两个业务重心

### 2.1 重心一：故事 → 剧本 → 镜头 → 可播内容

“要素”指一切可被镜头引用、可进入直播内容的标准化资产：

- 数字人形象（人像）与音色（声音）
- 已核验的商品事实、卖点、促销信息
- 剧本与结构化剧本块
- 画面要素：产品图/实拍、标题、背景、气球（促销气泡/挂件贴片）、促销链接、BGM、影像（视频素材）
- 麦兔素材：数字分身、背景、装饰、视频、文本、模版
- 场景模板（TemplateScene / TemplateComponent）与布局信息
- 可替换槽位（MaterialSlot）与替换策略

内容生产主线：

```text
ContentProject（目标、已核验事实、故事、促销节奏）
  -> 剧本（纯口播 + 结构化剧本块 + 质量门禁）
  -> 节目语义段与镜头清单（目标、时长、构图、要素需求）
  -> ProductionVariant
       -> 直播间式：MaituScene/Layer -> BuildPlan -> 麦兔草稿
       -> 视频式：Timeline/Track/Clip -> 渲染成片
  -> ReleaseManifest（精确内容、权利、质量与批准版本）
  -> 交付、排播与开播（正式开播需短期目标绑定授权）
```

剧本是内容拼接的权威来源，FactCardRevision 是商品事实的权威来源：镜头目标、商品关键词、画面主题、促单贴片和写入麦兔的文本都必须追溯到剧本及其 FactCitation，而不是从参考模板反向拼文案。

判断任何子系统价值的标准是：它是否让“从故事到可播内容”更快、更稳、更可追溯。

### 2.2 重心二：现场数据、运营数据与内容挂钩，评估角色

两类数据必须回流：

- **现场数据**：Observe 读取的麦兔页面状态、preflight 结果、`MT-EXEC-*` 执行回写、截图证据、失败分类与 `MT-RETRY-*` 重试记录、版式微调前后的几何状态。
- **运营数据**：评论、弹幕、点赞、点击、下单、观看时长、GMV、直播复盘结论，由数据角色登录运营后台采集。

挂钩的关键是数据不能悬空，也不能把“计划展示”冒充“实际展示”。每场 LiveSession 绑定精确 ReleaseManifest，实际内容由 ContentExposureEvent 记录；指标事件再落到时间段、镜头、剧本块、商品、数字人、音色、载体场景和槽位素材。每个对象带角色与策略版本，策略分配和实际曝光另有 DecisionLog/ExperimentAssignment，因此效果才能在证据边界内评价角色。

由此形成评估角色的数据 loop：

```text
角色接力产出内容（每个产物记录角色与策略版本）
  -> ReleaseManifest -> Delivery -> ContentExposureEvent
  -> 现场数据与运营指标落到镜头 / 剧本块 / 要素 / 时间段
  -> 形成描述统计、关联估计、准实验或随机实验结果
  -> 在合格证据下评价编剧 / 导演 / 影像 / 剪辑 / 场控策略
  -> 受控扩量、降级或淘汰策略
  -> 下一轮生产
```

## 3. 角色化生产分工

从故事到开播由一组 AI 角色接力完成。总原则：**职责归角色，实现归策略**。角色定义固定的职责、输入输出 schema、允许工具和质量门禁；每个角色对应可替换、可版本化的策略，同一角色可并存多个策略做受控实验。所有新产物必须记录实际角色和策略 revision；人工编辑也以 `human_override` 策略留痕。数据 loop 评价的是被实际曝光的策略，不把整场 GMV 简单分摊给所有上游角色。

### 3.1 业务团队（人）：提供故事

输入生成目标、产品要点、已核验事实与卖点、促销节奏（时段、库存、优惠、平台活动窗口），确认结构化 StoryBrief。业务团队是主要人工内容输入者；事实白名单以批准的 FactCardRevision 及 StoryBrief 中固定的 FactClaim 引用为边界。

### 3.2 编剧角色：故事 → 剧本

把 StoryBrief 转成主播可直接口播的剧本和结构化剧本块，受质量门禁约束：只用已核验事实、不推断商品总数、不用未核验促销、不凑目标时长、24 小时循环规则。现有 `jd_wine_livestream_script_rule_v1` 确定性基线是第一个编剧策略；后续 LLM 写作策略必须复用同一契约和门禁。

### 3.3 导演角色：剧本 → 镜头

把剧本拆解为镜头清单（ShotList）：每个镜头声明内容归属的剧本块、镜头目标（种草、讲解、促单、互动、重入）、估算时长、构图意图和要素需求清单。现有的场景计划、素材需求规划能力归入导演角色。

### 3.4 影像角色：要素拼搭镜头

按镜头的要素需求从要素库选材并拼搭画面与声音：人像（数字人形象）、产品（商品图/实拍）、标题、背景、气球（促销气泡/挂件贴片）、促销链接、声音（口播音色）、BGM、影像（视频素材）。产出可渲染的镜头组合，并对缺失要素给出缺口报告。现有的语义选材、候选推荐、缺口报告和布局能力归入影像角色。

### 3.5 剪辑角色：镜头 → 成片

把拼搭好的镜头合并为可播视频：镜头顺序、转场、节奏、总时长控制、音画同步和成片质量检查。产出带镜头级时间轴的成片，时间轴保留“成片时间段 → 镜头 → 剧本块”的映射，供数据归因使用。

### 3.6 场控角色：上传、排播、开播

把 release 交付到麦兔素材库或直播间，按促销节奏生成排播计划。硬性边界不变：**正式开播始终需要短期、目标/release/时间窗绑定的 GoLiveAuthorization**，且在独立安全评审完成前 capability 关闭。上传、草稿写入和未来开播使用不同授权能力；Browser-use worker 沿用 dry-run -> 只读 preflight -> commit-time authorization -> 执行 -> 回读/reconcile -> 证据回写的安全阶梯。

### 3.7 数据角色：采集与归因

登录麦兔与平台运营后台，采集现场数据、实际曝光和运营数据，按版本化 MetricDefinition/DataContract 对齐到 release、成片/会话时间轴、镜头、剧本块和商品讲解时间段。数据角色产出带封存点、质量和证据等级的评估输入；它不生产内容，也不能把相关性包装成因果。

### 3.8 镜头的两种实现形态

镜头是剧本与画面之间的统一中间层，有两种实现形态：

- **视频式**：影像角色拼搭镜头，剪辑角色合成成片，上传麦兔循环播出；
- **直播间式**：镜头映射为麦兔场景/图层组合，走已有 LiveRoomBlueprint / BuildPlan / Browser-use 搭建链路，实时拼装播出。

两种形态共用编剧和导演的产物，共用同一套要素库、编号体系和数据归因。已落地的直播间搭建能力（参考直播间抽取、蓝图、BuildPlan、替换方案、重试闭环）整体归入导演/影像/场控角色在直播间式形态下的实现。

## 4. 为什么不是通用素材库

AssetGraph 不以通用网盘、普通 DAM 或泛素材库为最终目标。存放和检索只是手段，系统设计优先回答内容生产和数据闭环的问题：

- 现有要素能不能支撑一场新直播？缺哪些素材？
- 给定故事和促销节奏，剧本能否自动生成并通过质量门禁？
- 剧本的每个段落，能否拆成镜头并自动拼搭出画面？
- 成片能否自动上传、按节奏排播、安全开播？
- 这场直播里，哪个镜头、哪个剧本块、哪个素材带来了互动和成交？
- 上一场的效果数据，如何评估各角色策略并改变下一场的产出？
- 哪些视频片段、话术、封面、商品素材值得复用和二创？

因此 AssetGraph 的业务中心不是孤立的 `Asset` 文件，而是：

```text
ContentProject -> StoryBrief -> Script -> ProgramSegment -> Shot
  -> ProductionVariant -> 成片 / 直播间 -> ReleaseManifest -> LiveSession / Exposure
  + 要素版本与权利（DigitalHuman / VoiceProfile / Product / Maitu 素材）
  + 现场数据 / 标准指标回流 -> 分级效果证据 -> 角色策略评估
```

同时，因为 AssetGraph 要服务麦兔软件，系统必须记录素材在麦兔项目中的用途分类、场景、图层、槽位和替换策略，并维持“素材库 + Browser-use 现场”的 Observe → Plan → Act → Verify → Learn loop：Observe 读取麦兔真实页面现场，Plan 基于素材库/剧本/商品/参考直播间生成蓝图和计划，Act 由 Browser-use 执行小步 UI 操作，Verify 通过页面状态和截图校验，Learn 将成功路径、失败类型、现场状态和可复用模板回写沉淀。

麦兔相关上下文包括：

```text
MaituProject + MaituScene + MaituLayer + MaterialSlot + ReplacementPolicy
```

## 5. 五个核心子系统

按优先级排列：前两个是业务重心，后三个是不可绕过的支撑底座。

### 5.1 内容拼接与生产系统（重心一）

承载从故事到可播内容的角色接力：

- 接收 StoryBrief：结构化的产品要点、已核验事实、促销节奏
- 编剧：生成 24 小时循环纯口播剧本、结构化段落与质量报告；不推断商品总数，不使用未核验促销，不为凑时长重复内容；质量未过时保留审阅产物但强制 `can_execute=false`
- 导演：把剧本组织为 ProgramSegment 并拆解为 ShotList，声明每个镜头的目标、时长、构图、要素需求和验收标准
- 影像：按剧本上下文和镜头需求自动选材，写入匹配分与匹配原因，产出素材缺口报告
- 剪辑：合成带镜头级时间轴的成片，完成转场、节奏和成片质量检查
- 场控：把批准的 release 交付麦兔并按促销节奏生成排播计划；正式开播需独立 GoLiveAuthorization
- 直播间式形态：从内容模板和 Shot 生成 LiveRoomBlueprint / MaituSceneBlueprint / LayerBlueprint，转换为 BuildPlan（修改空白草稿标题、创建场景、插入图层、设置坐标/层级、添加脚本块、保存草稿）；外部参考直播只提供内容策略和近似视觉参考
- 视频式形态：把 Shot 编译为 OpenTimelineIO 兼容的 ProductionTimeline，以 RationalTime/TimeRange 表达帧边界，再渲染、质检和发布
- 所有 Browser-use 操作经 dry-run、只读 preflight、非破坏性导航逐级放开执行
- 将“往右下挪一点/缩小一点”等自然语言版式反馈转成可验证的图层几何调整计划
- 生成成功只产生 candidate；批准的 ReleaseManifest、DeliveryAttempt 和实际 Exposure 是三个独立状态
- 每个阶段产物记录角色与策略版本，全链路可追溯：ContentProject -> StoryBrief -> 剧本块 -> ProgramSegment -> Shot -> 时间轴片段 / 麦兔场景与图层

### 5.2 数据闭环系统（重心二）

负责把现场数据和运营数据挂回内容，评估角色：

- 接收 Browser-use 执行结果回写（`MT-EXEC-*`）：成功、失败、单槽位错误、截图素材和摘要，形成可追踪执行闭环
- 对失败结果分类，沉淀 `MT-RETRY-*` 重试任务，支持队列领取、租约、过期回收和最小化重试，形成“失败-重试-回写-关闭”的恢复闭环
- 持续读取 Browser-use 现场状态（登录态、URL、场景、图层、素材页签、文本框内容、截图），用于校准蓝图和安全 preflight
- 数据角色按来源事件 ID、event time、watermark、删除/退款语义采集评论、点赞、点击、下单和观看数据，通过 MetricDefinition/DataContract 标准化
- 效果归因以 ReleaseManifest 和 ContentExposureEvent 为起点，把互动和成交对齐到镜头、剧本块、商品讲解时间段、要素和载体投影
- 结果分为 PerformanceProfile、AssociationalEstimate 和 CausalEstimate；没有可靠反事实时只回答“共同变化”，不宣称“带来提升”
- 分角色评估同时看质量、时延、成本、安全和业务效果；只有预注册实验或经批准准实验才能自动扩大/淘汰策略
- 同角色多策略 A/B 必须有先于曝光的 ExperimentAssignment、稳定随机化单位、A/A、SRM、护栏和停止规则
- 只有满足 LearningPolicy 的批准结果能按受控权重影响下一轮选材和生成，且永远不能绕过事实、权利或硬约束
- 自动生成直播复盘，沉淀高效话术、高效镜头结构和商品讲解模板
- Learn 环：把成功路径、失败类型、现场状态和可复用模板回写素材库/知识库

### 5.3 要素资产库（底座）

负责要素的标准化供给，服务于拼搭与归因：

- 统一存放数字人形象、音色、剧本、商品素材、标题/气球/促销链接等画面要素、BGM、麦兔场景/图层素材、可替换槽位
- 统一存放直播录屏、切片、成片、封面、字幕、评论导出和复盘文档，按 `live_code` 聚合
- 稳定编号体系（`AG-*` / `MT-*` / 本地文件码）与双层分类（`asset_type` + `maitu_category`）；StoryBrief、镜头、成片沿用日期加序号的编号风格入库
- 检索文本、embedding 和语义推荐，让各角色策略和 Agent 能按语义找到要素
- 记录素材在麦兔中的场景、图层、位置尺寸和替换策略，保证替换不破坏布局
- 区分逻辑 Asset、内容版本和技术 Rendition；每个版本携带渠道/地域/期限/衍生/AI 使用/肖像声音等 RightsGrant，撤销能追踪所有受影响 release
- 管理版本化位置、缩放、裁剪、图层、命名区域和素材间关系约束；选材先做确定性硬过滤，再做可解释排序，并以 AssetGap 闭环缺失要素

### 5.4 多模态解析与知识图谱（底座）

负责把原始素材变成可理解的要素，并沉淀对象间关系：

- 视频抽帧、镜头/段落切分、ASR 转写、字幕对齐、OCR
- 商品识别、数字人识别、场景识别
- 画面质量、音频质量、口型/音画同步检测，为要素和成片打质量分，服务影像与剪辑角色
- 沉淀关系：故事-剧本、剧本块-镜头、镜头-要素、成片-镜头、数字人-直播、商品-片段、互动-时间段、策略-产物、直播-商品-项目-标签-复盘
- 解析和图谱的产出物都服务两个重心：解析让录屏和成片变成可复用要素，图谱让数据挂钩、角色归因和效果查询可行
- PostgreSQL 不可变修订与 artifact 是事实源；图谱和向量索引通过 outbox 构建、带投影版本、可完整重建且不得反写事实
- 图数据库、在线 Feature Store 和 durable workflow 引擎都按量化门槛引入，不作为第一条业务闭环的前置条件

### 5.5 发布、安全与运行治理（底座）

负责让生产、交付和学习在长期运行中可控、可恢复、可审计：

- 用 WorkflowRun/StepRun/HumanTask 统一长任务、重试、timeout、取消、人工交接和成本预算；领域对象保留各自状态机
- 用内容寻址 Artifact、RunManifest、OpenLineage 兼容血缘和 OpenTelemetry trace 分别记录产物、业务来源和运行观测
- 用不可变 ReleaseManifest、DeliveryAttempt、LiveSession 与 ContentExposureEvent 分开表达批准、交付和真实曝光
- 所有外部副作用经 allowlist、ProtectedResourceRegistry、preflight 和 commit-time ExecutionAuthorization；未知结果先 reconcile，不盲目重放
- 管理数据分类、最小权限、去标识、保留/删除、legal hold 和素材权利撤销传播；凭据和原始个人数据不进入模型、图谱或公开证据
- 建立容量基线、用户旅程 SLO/error budget、逐运行成本、队列配额、kill switch、PITR、对象校验和投影重建演练
- 正式开播是独立高风险能力，只有排播冲突检查、短期单次 GoLiveAuthorization、双人复核和紧急停止通过评审后才可启用

## 6. 核心业务对象

### 6.1 内容与生产聚合

- **ContentProject / ContentProjectRevision**：跨载体内容业务聚合根。固定生成目标、批准事实、内容模板选择和用户确认值；不要求房间 ID。
- **ProductionVariant / ProductionVariantRevision**：某个内容修订的载体分支，首批支持 `live_room` 与 `rendered_video`。房间、inventory、RenderProfile 和分支素材只属于对应 variant。
- **WorkflowRun / StepRun / HumanTask / ArtifactRef**：跨域长任务控制面，负责依赖、租约、重试、timeout、取消、人工等待、预算和内容寻址产物；不替代领域状态。

### 6.2 要素、事实与权利

- **Asset / AssetVersion / Rendition**：逻辑作品、内容版本和原始/转码/缩略/抠图等技术表现。
- **AssetConstraintRevision / AssetGroup / MaterialPack / AssetGap**：版本化约束、多对多人工分组、总体/分类素材包和缺口处理闭环。
- **RightsGrant**：渠道、地域、期限、衍生、AI 使用、署名、肖像/声音授权和证据；未知或撤销权利不能进入可交付 release。
- **DigitalHuman / VoiceProfile / Product / FactCardRevision**：数字人、音色、商品和已核验事实。任何事实性口播必须通过 FactCitation 指向批准修订。
- **Maitu Material Context**：麦兔素材的可执行身份、用途分类、现场绑定和历史观察；历史几何不自动升级为全局约束。

### 6.3 内容和载体产物

- **StoryBriefRevision**：由 DesignBrief 确认后得到的不可变权威内容输入，保存目标、事实、故事、模板贡献和内容政策。
- **Script / ScriptBlock**：编剧产物。剧本块是事实引用、内容拼接和归因的稳定最小话术单元。
- **ContentProgramRevision / ProgramSegment**：节目语义结构，表达阶段、目标、商品、CTA 和进入/退出条件。
- **ShotListRevision / Shot**：导演镜头意图，记录来源剧本块/节目段、目标、构图、时长、要素需求和验收标准；Shot 不等同 Scene 或 Clip。
- **LiveRoomBlueprint / MaituSceneBlueprint / LayerBlueprint / BuildPlan**：Shot 的麦兔载体投影和受控执行计划。
- **ProductionTimeline / TimelineSegment**：Shot 的成片载体投影。时间线采用 OTIO 兼容结构和 RationalTime，并通过 TimeMapping 映射到会话毫秒。
- **RenderedVideo / VideoSegment**：渲染成片与从录屏切出的分析片段；二者保留到 Shot、剧本块、素材和源时间的 lineage。

### 6.4 发布、运营与效果证据

- **ReleaseManifest / DeliveryAttempt**：批准交付的精确内容、artifact、权利和质量版本，以及每次麦兔/渠道交付与回读证据。workflow 成功不等于 release 已交付。
- **LiveSession / ContentExposureEvent**：真实运营场次和实际展示日志。计划内容、交付成功与实际曝光不能互相替代。
- **MetricDefinitionRevision / DataContract**：指标分子分母、grain、时区、退款窗口和来源 schema/事件时间/删除语义。
- **PerformanceProfile / AssociationalEstimate / CausalEstimate**：描述表现、关联估计和合格因果估计，分别携带数据封存点、方法、质量和证据等级。
- **DecisionLog / FeatureSnapshot**：每次推荐/策略选择时的点时候选集、排除原因、特征、propensity、最终选择和后续实际曝光。
- **Experiment / Assignment / Analysis**：预注册实验、先于曝光的分配和带 A/A、SRM、护栏、停止规则的分析。

### 6.5 角色、排播与安全治理

- **Role / RoleStrategyRevision / RoleEvaluation**：固定职责、可替换策略及基于合格曝光和效果证据的评价。质量门禁属于角色契约，任何策略不得绕过。
- **BroadcastSchedule / GoLiveAuthorization**：目标/release/时间窗固定的排播与短期单次开播授权；当前 capability 关闭，启用前需独立安全评审。
- **PolicyDecision / ExecutionAuthorization / ProtectedResourceRegistry**：提交时策略决策、目标/plan hash 绑定授权和保护资源登记。
- **RunManifest / lineage / trace**：固定输入、模型、提示、代码、工具、随机种子、输出和证据；lineage 表达业务来源，trace 表达运行观测。

## 7. 第一阶段闭环

第一阶段按纵向切片打通内容到麦兔草稿，再扩展同内容成片和数据闭环。允许每个角色先只有一个确定性策略，允许人工介入交接点；优先保证聚合边界、不可变 revision、发布/曝光语义和追溯关系正确。完整 Phase 0-7、进入/退出条件见权威设计第 18 节。

### 7.1 内容生产闭环（第一优先级）

```text
业务团队建立 ContentProject（目标、批准事实、故事、约束）
  -> 确认 StoryBriefRevision
  -> 编剧生成 Script，导演生成 ProgramSegment 与 ShotList
  -> 创建 live_room ProductionVariant 并固定素材/约束/权利快照
  -> Shot 投影为 MaituScene/Layer，编译 BuildPlan
  -> 短期 ExecutionAuthorization -> 写入空白麦兔草稿 -> 现场回读
  -> 批准不可变 ReleaseManifest(kind=live_room_draft)（不含开播）
```

控制面、RunManifest、权利/事实/约束门禁、提交时授权和 release 完整性属于第一阶段前置不变量。完成这条闭环后，再从同一 ContentProject 创建 rendered_video variant，复用编剧和导演产物生成 OTIO 时间轴与成片。

### 7.2 数据闭环最小版

```text
LiveSession 绑定准确 ReleaseManifest
  -> 人工/录屏辅助登记 ContentExposureEvent
  -> 数据角色人工导入一场直播的评论与成交数据
  -> 按 MetricDefinition/DataContract 对齐实际曝光、Shot、剧本块和商品时间段
  -> 发布第一份 descriptive/associational 结果及数据质量说明
```

数据闭环最小版允许运营数据人工导入和人工标注对齐，但仍须保存来源 ID、事件时间、封存点、指标口径和方法版本。它优先证明“实际曝光 -> 数据 -> 内容对象 -> 策略”的链路，不追求实时采集，也不基于相关性自动淘汰策略。

### 7.3 录屏解析链路的定位

“上传录屏 → 抽音频 → ASR → 切片 → 关联实体”的链路继续保留，但定位为**要素沉淀的输入通道之一**：它为要素库补充可复用片段和话术，为数据闭环提供时间轴底座，本身不是第一优先级。

### 7.4 主题驱动商业短视频 Demo

现有视频式能力以“只提交主题”的竖版商业短视频 Demo 验证了确定性角色接力：系统从版本化、已核验的商品知识底稿生成 StoryBrief，再依次完成商业剧本、镜头清单、素材选择、配音、字幕、渲染和质量检查。它是迁移种子而不是目标产品交互；正式 Console 统一从可填写目标、事实、故事和约束的 ContentProject 进入。

```text
主题
  -> StoryBrief（固定商品知识底稿 + 内容边界）
  -> 商业视频剧本（旁白 + 屏幕文案 + 质量报告）
  -> ShotList（时间、构图、素材区间、转场、图层）
  -> 真实素材选择与本地 TTS
  -> ASS 字幕与 FFmpeg RenderManifest
  -> 竖版 MP4
  -> ffprobe / 黑帧 / 静音 / 响度 / 字幕安全区检查
```

该现有闭环使用独立 `VideoProductionJob`，不复用 BuildPlan。迁移后它成为 rendered_video ProductionVariant 的执行聚合，接收共同的 ContentProject/StoryBrief/ShotList，并补齐 OTIO ProductionTimeline、`ReleaseManifest(kind=rendered_video)` 和 DeliveryAttempt；阶段重试和既有 artifact 保持兼容。

第一版默认输出约一分钟的 `1080x1920` H.264/AAC 视频，实际时长服从内容和配音节奏；允许使用已授权的本地商品视频、背景、装饰和品牌素材。数字人口型、BGM、麦兔上传、排播和开播不属于该 Demo 的完成条件，不得阻塞本地成片。

Demo 页面是实际生产工作台：提供主题输入、阶段进度、成片播放器以及剧本、分镜、素材和质检视图。页面只通过受控 Artifact API 访问视频和中间产物，不暴露服务器本地绝对路径。

### 7.5 麦兔主题生产工作台

`/maitu/` 是面向真实麦兔素材库的现有生产入口。每次运行固定人工批准的商品事实版本和麦兔资源快照；当前 DeepSeek 直接生成受事实约束的剧本、场景和素材意图，后续确定性流水线完成选材、缺口、布局与 BuildPlan。迁移目标是把它接到 ContentProject/ProductionVariant/Shot 主链，而不是长期保留第二套内容聚合。模型不可用、结构不合法或出现未核验表述时仍然失败关闭。

素材缺口是持久化的一等对象。运营人员可以采用候选、延后、豁免或补充素材，并在每次 Replan 中保留决策与旧 revision。视频素材可保存 GPT 视觉分析、绑定素材指纹的 Gemini 人工 JSON 和冲突裁决；只有被当前计划选用且存在未裁决关键冲突的素材才阻断 preflight。

工作台只写入用户在麦兔中预先建立的全新空白草稿直播间。参考房间 `38336`、`38995` 始终列入 ProtectedResourceRegistry；preflight、授权服务和 Browser-use 都必须再次验证目标不是保护房间、只有默认场景且没有业务素材。执行范围止于草稿保存、回读和内部 `ReleaseManifest(kind=live_room_draft)`，不包含排播或开播。

### 7.6 抖音直播研究工作台

`/live-research/` 使用固定 revision 的 StreamCap 和 douyinLive 完成长期值守、录屏与互动事件采集。调度器全局最多录制一个房间，不抢占；目标质量固定为 720p，TS 分片固定为 600 秒。每个分片经过稳定性、ffprobe、尺寸和 SHA-256 校验后进入统一时间轴。原始视频默认保留 30 天；原始个人互动按来源合同保留 30-90 天，去标识标准事件通常保留 180 天，发布模板、汇总指标和不可逆匿名化结论可以长期版本化保留；legal hold 必须有 owner 和到期。

采集完成后系统按依赖关系排队抽帧、ASR、OCR、布局识别和模板聚合。ASR 与视觉分析使用明确版本的在线模型，模板聚合使用 DeepSeek；缺少凭据时任务明确失败，不生成占位结论。模板必须经过人工审核后发布，外部平面视频在完成麦兔组件重建和证据核验前只能标记为 `reference_only / approximate`。

### 7.7 直播内容生产与运营闭环

长期产品是统一 AssetGraph Console，不局限于 `/maitu/` 或三个页面。近期先交付素材管理、直播模板配置和直播间生产；同时建立 `/content/projects` 作为内容入口，随后增量加入知识库、成片生产、release、运营与归因、效果学习、治理与任务中心。

麦兔继续作为可执行素材身份的主数据源。外部录屏模板只提供内容策略和近似视觉参考，不提供目标商品事实，也不冒充真实麦兔图层。直播间生成必须使用批准事实卡、受控素材约束和不可变输入快照；只有目标房间为未开播空白草稿且不存在硬阻断时，系统才自动执行只读 preflight 并写入草稿，仍然禁止正式开播。

所有工作区共享 ContentProject、StoryBrief、ScriptBlock、ProgramSegment、Shot、ProductionVariant、ReleaseManifest、Exposure、素材/权利、执行证据和 LiveSession 的版本化关系，形成 Observe -> Plan -> Act -> Verify -> Learn 闭环。WorkflowRun 管过程，ArtifactRef 管产物，ReleaseManifest 管被批准交付的精确集合，三者不得混用。

素材/权利、主次内容模板、内容与分支聚合、Shot 投影、草稿写入、成片时间轴、release/exposure、指标/实验、运行控制面、数据治理、非功能目标和 Phase 0-7 的权威设计见 [AssetGraph 直播内容生产与运营闭环设计](plans/2026-07-22-live-content-production-operations-closed-loop-design.md)。

## 8. 成功标准

### 8.1 短期成功标准（角色接力跑通）

- ContentProject -> StoryBrief -> Script -> ProgramSegment -> Shot -> live_room draft 的第一条纵向链路可审计、可追溯。
- 同一内容项目可独立创建 rendered_video variant，生成 OTIO 时间轴和通过质量门禁的成片；两个分支状态互不污染。
- 每个运行产生 RunManifest，每个批准产物产生精确 ReleaseManifest；运行成功、交付成功和实际曝光明确分开。
- 素材选择固定版本、权利、约束和白名单，缺口可处理；每个 Browser-use 副作用有短期授权、回读证据和 reconcile 路径。
- 每个角色至少有一个可运行的显式策略，所有新产物带角色与策略 revision；历史未知值不参与评价。

### 8.2 中期成功标准（数据评估角色成立）

- LiveSession 绑定 release，实际 ContentExposureEvent 与标准运营指标自动采集并对齐到 Shot、剧本块、商品和素材。
- Metric Catalog、DataContract、event-time/迟到/删除/退款语义生效；结果可下钻到封存点、曝光、指标桶、方法和代码版本。
- 描述、关联和因果证据在 API/UI 中严格分开；至少完成一次预注册实验或合格准实验驱动的受控策略迭代。
- DecisionLog 保存点时特征、候选集、propensity 和实际曝光；LearningPolicy 只允许合格结果影响软排序，且保留探索配额。
- 权利撤销、数据删除、漂移和指标修订能传播到依赖结果与未来决策；SLO、成本配额、备份恢复和投影重建通过演练。

### 8.3 长期成功标准（loop 自转）

- 数据驱动的持续优化：自动产出复盘，基于合格证据评价角色，自动建议换素材、改话术、调镜头结构，形成“目标/事实/故事 -> 生产 -> release/exposure -> 数据 -> 评价策略 -> 再生产”的持续 loop。
- 同角色多策略受控实验成为常态，高效话术、镜头结构和商品讲解模板在防止反馈回路、自我强化和未来数据泄漏的前提下沉淀。
- 解析能力（ASR、口型/音画同步、质量检测）完善，保障要素质量、成片质量和归因精度。
- 图谱或在线 Feature Store 只在量化收益门槛成立后采用，且始终可由事实源和 outbox 重建。
- AssetGraph 成为 AI Agent 的数字人直播内容大脑：业务团队提供目标、批准事实、故事和业务约束，角色接力完成生产、发布、数据采集与受控学习；正式开播始终需要目标/release/时间窗绑定的短期授权和紧急停止能力。

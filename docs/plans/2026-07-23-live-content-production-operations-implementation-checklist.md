# AssetGraph 直播内容生产与运营闭环落地 Checklist

> 状态：执行中（Phase 0）
> 日期：2026-07-23
> 权威设计：[AssetGraph 直播内容生产与运营闭环设计](./2026-07-22-live-content-production-operations-closed-loop-design.md)
> 最终目标：[AssetGraph 最终目标](../final-goal.md)
> 适用范围：从当前仓库基线演进到权威设计第 30 节定义的完整系统

## 0. 使用规则

### 0.1 勾选规则

- [x] `CHK-0001` 指定 checklist owner，负责维护任务状态、证据链接、阻断项和设计偏差。
- [ ] `CHK-0002` 为每个 Phase 指定 product、engineering、data、security owner；涉及 UI 的 Phase 同时指定 design owner。
- [x] `CHK-0003` 约定严格按 `Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 7 -> Phase 8` 推进；上一个 Phase 的退出门禁未全绿时，不开始下一个 Phase 的生产启用工作。
- [x] `CHK-0004` 允许为降低风险提前做 spike，但 spike 产物不得作为后续 Phase 已完成的依据，不得绕过当前 Phase 的门禁。
- [x] `CHK-0005` 任务只有在代码、追加迁移、API/schema、权限与审计、观测、文档、测试、回滚或对账方案均适用且完成后才能勾选。
- [x] `CHK-0006` 现有功能必须先通过本清单要求的契约和测试；“代码已经存在”本身不能作为勾选依据。
- [x] `CHK-0007` 每个勾选项在执行记录中填写 `owner / PR或commit / migration / test evidence / artifact或截图 / approved_by / completed_at`。
- [x] `CHK-0008` 父项只有在全部子项完成后勾选；不得以勾选父项代替子项证据。
- [x] `CHK-0009` 不适用项不能直接删除或当作完成；必须写 ADR 说明为何不适用、替代能力、影响和批准人，再将设计与本清单同步修改。
- [x] `CHK-0010` 任何实现偏离权威设计时先更新 ADR 和设计文档，再改 checklist；禁止只改任务措辞来掩盖契约变化。
- [x] `CHK-0011` 每个 Phase 开始前建立 2-6 周可验收里程碑、依赖图、风险清单和容量/成本预算，不预先填写没有依据的日历工期。
- [ ] `CHK-0012` 每个 Phase 结束时归档验收包，至少包含需求追踪矩阵、测试报告、数据迁移报告、安全审查、SLO/成本结果、回滚演练和已知限制。

### 0.2 单项完成定义

每个功能项在勾选前逐项确认；某项不适用时也要在执行记录中说明原因。

- [ ] `DOD-001` 领域行为、状态机、不变量和错误码已实现，失败行为为 fail closed。
- [ ] `DOD-002` 数据库变更使用新 migration；升级、回滚或前向修复、历史数据解释和大表影响已验证。
- [ ] `DOD-003` 写接口支持 expected revision 或 idempotency key；重复请求、并发修改和超时后的结果已测试。
- [ ] `DOD-004` API schema 有版本、示例、兼容窗口、consumer contract test 和弃用策略。
- [ ] `DOD-005` 权限、PolicyDecision、审计、敏感字段脱敏和保留策略已接入。
- [ ] `DOD-006` 领域 lineage、ArtifactRef、RunManifest、trace context、结构化日志和指标已接入。
- [ ] `DOD-007` 前端具备 loading、empty、error、warning、stale、partial、无权限和并发冲突状态，且支持实体 revision 深链。
- [ ] `DOD-008` 单元、属性、契约、集成和端到端测试按风险补齐，关键反例和故障路径已覆盖。
- [ ] `DOD-009` 运维 runbook、告警、kill switch、重试/对账、备份恢复和降级行为已文档化。
- [ ] `DOD-010` 产品、数据、安全和实际运营用户完成验收，验收证据可从任务记录反查。

### 0.3 执行记录模板

每完成一个 `CHK-*`，在项目管理系统或本文件末尾的执行日志按以下字段登记：

```text
check_id:
owner:
status: todo | in_progress | blocked | done
depends_on:
pull_request_or_commit:
migration:
test_command_and_result:
evidence_artifacts:
design_or_adr_refs:
known_limits:
approved_by:
completed_at:
```

---

## Phase 0. 不变量、演进边界与统一控制面

> 目标：先建立后续所有业务功能共享的稳定对象、版本、证据、安全和执行语义。
> 依赖：仅依赖当前仓库基线。

### 0.1 基线盘点与架构决策

- [x] `CHK-0101` 生成当前能力清单，逐项标记 `reuse / extend / migrate / retire`，覆盖 FastAPI、PostgreSQL、`/maitu/`、`/live-research/`、三个 worker、视频链路、Qwen3、MinIO、Milvus 和 Neo4j。
- [x] `CHK-0102` 生成当前数据对象与新领域对象映射，明确每个对象的 source of truth、兼容投影、owner 和下线条件。
- [x] `CHK-0103` 盘点旧 StoryBrief、VideoProductionJob、LiveRoomConfiguration、WorkbenchRun、Scene、layout hypothesis、JD 指标和历史交付数据的可迁移质量。
- [x] `CHK-0104` 为无法证明来源的历史字段定义 `unknown / legacy_import / legacy_delivery_unknown / descriptive_only` 语义，禁止反向猜测。
- [x] `CHK-0105` 建立 ADR 模板和索引，至少覆盖聚合边界、不可变 revision、时间语义、release/delivery/exposure、授权能力和证据等级。
- [x] `CHK-0106` 固定统一领域词汇：ProgramSegment、Shot、MaituSceneBlueprint、TimelineSegment、Artifact、Run、Release、Delivery、Exposure 不得互相代用。
- [x] `CHK-0107` 固定逻辑 ID、revision、schema version、事件 ID、幂等键、内容指纹和审计时间字段规范。
- [x] `CHK-0108` 固定编辑帧时间、媒体 PTS、会话毫秒时间和 event/processing time 的边界及转换规则。
- [x] `CHK-0109` 建立状态机变更规则和合法转移测试框架；非法跳转返回稳定错误码并记录审计。
- [ ] `CHK-0110` 记录当前容量基线：素材数、录屏小时/日、事件峰值、直播并发、渲染并发、artifact 增长、workflow 数量和 Browser-use 并发。
- [x] `CHK-0111` 建立外部 API/平台依赖登记，覆盖麦兔 API、麦兔 Web UI、DeepSeek、OpenAI、抖音采集端点和运营数据来源。
- [x] `CHK-0112` 为每个外部依赖登记用途、发送数据、凭据、配额、费用、超时、限流、数据区域、失败行为、fallback、owner 和退出方案。
- [x] `CHK-0113` 把 DeepSeek/OpenAI/ASR/OCR/视觉能力收敛到 provider adapter；领域 API 和持久化契约不得暴露供应商专有模型名。
- [x] `CHK-0114` 明确麦兔 authoritative API 的硬依赖和 fail-closed 行为；测试环境使用契约稳定的 fake/sandbox，不用宽松 mock 掩盖失败。

### 0.2 核心聚合、修订和 stale 传播

- [x] `CHK-0120` 设计并追加 ContentProject、ContentProjectRevision 表、约束、索引和 repository。
- [x] `CHK-0121` 设计并追加 StoryBrief、StoryBriefRevision 表，落实 `draft -> confirmed -> superseded` 和 confirmed 不可变。
- [x] `CHK-0122` 扩展 Script/ScriptBlock 为版本化内容对象，保留模型、提示、策略、事实引用和内容指纹。
- [x] `CHK-0123` 设计并追加 ContentProgramRevision、ProgramSegment 及 ScriptBlock 采用区间。
- [x] `CHK-0124` 设计并追加 ShotListRevision、Shot、ShotProjectionLink，确保 Shot 不保存可变路径或麦兔序号。
- [x] `CHK-0125` 设计并追加 ProductionVariant、ProductionVariantRevision，支持 `live_room / rendered_video` 且分支状态互不污染。
- [x] `CHK-0126` 将 LiveRoomConfiguration 映射为 live_room 分支配置，将 VideoProductionJob 映射为 rendered_video 执行聚合。
- [x] `CHK-0127` 实现每层 `derived_from`、source revision、producer role/strategy 和独立 fingerprint。
- [x] `CHK-0128` 实现上游修订变化后的 stale 传播图，覆盖 variant、BuildPlan、timeline、render、release candidate 和 attribution mapping。
- [x] `CHK-0129` 实现 immutable revision repository guard，阻止 confirmed/published/released 数据原地更新。
- [x] `CHK-0130` 为 revision 创建、重复确认、并发编辑、supersede 和 stale 传播补齐属性测试与事务测试。

### 0.3 Artifact、运行清单与可重建投影

- [x] `CHK-0140` 设计并追加 ArtifactRef，保存 media type、schema、URI、checksum、size、producer、输入引用、敏感级别和保留策略。
- [x] `CHK-0141` 实现内容寻址 artifact 写入、重复检测、校验、读取授权和对象存储版本保护。
- [x] `CHK-0142` 定义 RunManifest schema，固定输入修订、文件、inventory、素材/约束/权利、模板、事实、内容、模型、提示、代码、工具、随机种子和环境。
- [x] `CHK-0143` 实现规范化 manifest 和 input/output fingerprint 计算，增加跨运行一致性和差异解释工具。
- [x] `CHK-0144` 建立 transactional outbox 表、写事务、投影消费者 checkpoint、幂等消费和死信处理。
- [x] `CHK-0145` 设计 GraphProjectionVersion 和通用 projection watermark，但 Phase 0 不把 Neo4j 设为事实源。
- [x] `CHK-0146` 提供 OpenLineage 兼容投影，验证领域 lineage 在 trace 丢失时仍完整。
- [x] `CHK-0147` 在 API、队列、worker、模型和外部适配器间传播 OpenTelemetry trace/span context。
- [x] `CHK-0148` 对关键 manifest、授权、release 和操作结果实现服务端签名或 append-only hash chain。
- [x] `CHK-0149` 为 artifact 损坏、outbox 重放、重复消费、投影落后和签名失败建立测试与告警。

### 0.4 WorkflowRun、StepRun 与 HumanTask

- [x] `CHK-0160` 设计并追加 WorkflowRun、StepRun、HumanTask、ArtifactRef 关联和状态历史表。
- [x] `CHK-0161` 实现 parent/child、依赖、优先级、预算、排队原因和进度聚合。
- [x] `CHK-0162` 实现 PostgreSQL 队列 lease、heartbeat、claim token、lease version、超时回收和公平领取。
- [x] `CHK-0163` 为每个 Step 固定幂等键、副作用等级、最大尝试、退避、timeout、可取消点和补偿/对账策略。
- [x] `CHK-0164` 实现纯计算安全重试和副作用 `prepare -> authorize -> commit -> read-back/reconcile` 协议。
- [x] `CHK-0165` 实现 workflow 取消、等待人工、恢复和终态聚合，确保等待人工不占 Worker。
- [x] `CHK-0166` 实现 HumanTask claim、SLA、owner、revision、决定、结构化理由、过期和升级。
- [x] `CHK-0167` 将现有 WorkbenchRun、视频任务、直播研究任务和 retry queue 投影为兼容 WorkflowRun/StepRun。
- [x] `CHK-0168` 提供 `GET /api/workflow-runs/{run_code}`、取消接口和 HumanTask 查询/处理接口。
- [x] `CHK-0169` 测试 Worker 崩溃、重复领取、租约过期、取消竞态、超时、人工等待和未知副作用不会产生重复写入。
- [x] `CHK-0170` 用实测复杂度评估是否需要 Temporal；未达到门槛时记录“不引入”ADR，达到时保证领域 run code 和 lineage 不变。

### 0.5 策略决策、权限与执行授权

- [x] `CHK-0180` 建立最小权限能力矩阵，分离生产编辑、事实/模板发布、效果批准、草稿写入、上传、release 交付、图谱重建和开播。
- [x] `CHK-0181` 设计并追加 PolicyDecision、ExecutionAuthorization、ProtectedResourceRegistry。
- [x] `CHK-0182` 实现独立策略决策点，输入主体、目标、动作、plan/release hash、现场指纹、策略版本和批准链。
- [x] `CHK-0183` 实现短期、目标绑定、capability 绑定、nonce、过期、撤销和 single-use 授权。
- [x] `CHK-0184` 实现 Worker 提交时重新授权；preflight、workflow 状态或人工点击均不能替代 commit-time check。
- [x] `CHK-0185` 确保 `write_draft / upload_asset / deliver_release / go_live` 授权互不兼容。
- [x] `CHK-0186` 将参考房间、生产禁写对象、账号和外部资源纳入 ProtectedResourceRegistry，并在 preflight、PDP、Worker 三处独立检查。
- [x] `CHK-0187` 建立 feature flag 与 capability kill switch；当前 `go_live` 全环境默认关闭且无法签发。
- [x] `CHK-0188` 对越权、换目标、换 plan hash、过期、重放、授权服务不可用和注册表变化执行 fail-closed 测试。

### 0.6 Release、Delivery 与 Exposure 基础契约

- [x] `CHK-0200` 设计并追加 Release、ReleaseManifest、ReleaseApproval、DeliveryAttempt 和状态历史。
- [x] `CHK-0201` 固定 ReleaseManifest 通用外壳及 live_room/rendered_video carrier facet，禁止引用 `latest`。
- [x] `CHK-0202` 实现 candidate、validating、approval、delivery、failure、reconcile 和 revoke 合法转移。
- [x] `CHK-0203` 实现 release fingerprint、artifact checksum、批准记录、权利快照和 lineage 完整性门禁。
- [x] `CHK-0204` 实现 DeliveryAttempt 的目标、adapter、幂等键、授权、外部身份、请求/响应摘要、回读和证据契约。
- [x] `CHK-0205` 设计并追加 ContentExposureEvent append-only 基础表，禁止用“计划内容”代替实际曝光。
- [x] `CHK-0206` 用契约测试证明 workflow succeeded、release approved、delivery succeeded、release exposed 是四种独立事实。

### 0.7 指标、数据合同与证据等级基础契约

- [x] `CHK-0220` 设计并追加 MetricDefinition、MetricDefinitionRevision、DataContract 和 owner/version/status 字段。
- [x] `CHK-0221` 固定事件 envelope、event time/processing time、upsert/delete、幂等和 tombstone 语义。
- [x] `CHK-0222` 设计 AttributionRun/Result、PerformanceProfile、AssociationalEstimate、CausalEstimate 的边界。
- [x] `CHK-0223` 固定 `descriptive / associational / quasi_experimental / randomized` 证据等级，禁止人工直接抬级。
- [x] `CHK-0224` 设计 FeatureSnapshot、DecisionLog、LearningPolicy、EffectEligibilityPolicy 及 point-in-time 不变量。
- [x] `CHK-0225` 对同名不同口径指标、迟到事件、删除事件、未知 schema 和不合格数据批次建立 fail-closed 契约测试。

### 0.8 数据治理与保留底座

- [x] `CHK-0240` 给字段和 artifact 接入 `public / internal / confidential / restricted_personal / credential` 分类。
- [x] `CHK-0241` 建立角色加用途访问控制，覆盖导出、解密、批量查询、模型调用、图谱和删除。
- [x] `CHK-0242` 建立日志、截图、提示和模型响应的字段级脱敏规则；cookie/token/原始个人 payload 不可进入这些产物。
- [x] `CHK-0243` 固化原始录屏、个人事件、标准事件、汇总、关键审计和中间 artifact 的版本化保留策略。
- [x] `CHK-0244` 设计 DeletionRun、tombstone、legal hold、下游处理回执和 `partial_failed` 重试语义。
- [x] `CHK-0245` 实现凭据管理、轮换、最小发送字段和第三方 processor/区域/保留政策登记。

### 0.9 兼容迁移与 Console 壳

- [ ] `CHK-0260` 所有数据库变更使用追加 migration，并在真实数据副本验证耗时、锁和前向修复。
- [x] `CHK-0261` 保留旧素材几何和 duplicate_group 原语义，不自动提升为约束或用户分组。
- [x] `CHK-0262` 建立 legacy ContentProject、live_room variant、WorkflowRun 和 delivery unknown 兼容投影。
- [x] `CHK-0263` 保证旧 `layout-hypothesis.v1` 只读兼容，不原地转换成 content-strategy.v2。
- [x] `CHK-0264` 建立统一 Console 应用壳、登录态、一级导航、全局搜索入口、任务/通知中心和错误边界。
- [x] `CHK-0265` 实现稳定实体深链、revision 时间线、结构化 diff、来源与“被哪些运行/release 使用”。
- [x] `CHK-0266` 实现 draft 自动保存状态、expected revision 冲突提示和显式 confirm/publish/approve/authorize 命令。
- [x] `CHK-0267` 制定 `/maitu/`、`/live-research/` 迁移到稳定路由的功能等价、深链重定向和下线检查表。
- [x] `CHK-0268` 建立全局稳定错误码规范，错误展示影响、证据和下一步；warning/stale/insufficient_data 不冒充成功或失败。

### 0.10 Phase 0 退出门禁

- [x] `CHK-0290` 不可变 revision、幂等、并发修改、stale 传播和合法状态机契约测试全绿。
- [x] `CHK-0291` 授权换目标、过期、重放、跨 capability 和服务不可用均失败关闭。
- [x] `CHK-0292` Workflow 崩溃恢复、取消、人工等待和 reconcile 测试无重复副作用。
- [x] `CHK-0293` RunManifest、lineage、trace、outbox、签名和 artifact 校验可生成并可审计。
- [x] `CHK-0294` 旧主链通过兼容投影继续可读、可运行，迁移报告未伪造缺失来源。
- [x] `CHK-0295` 完成数据库 PITR 和对象 artifact 恢复基线演练，记录实际 RPO/RTO。
- [ ] `CHK-0296` Phase 0 产品、工程、数据、安全验收签字并归档验收包。

---

## Phase 1. 内容到麦兔草稿的第一条纵向闭环

> 目标：从目标与事实开始，经过 StoryBrief、剧本、节目段、Shot、麦兔 Blueprint、BuildPlan 和授权执行，得到证据完整的麦兔草稿 release。
> 依赖：Phase 0 全部退出门禁完成。

### 1.1 ContentProject 与目标/事实

- [ ] `CHK-1101` 实现 `POST/GET /api/content-projects`、详情和 expected-revision PATCH。
- [ ] `CHK-1102` 实现 project title、generation goal、目标时长、平台、受众、人设、语气、商品顺序、必含/禁用、互动/促单/视听要求。
- [ ] `CHK-1103` 支持选择多份固定版本的已批准 FactCard，并在确认时重验批准状态、有效期和适用范围。
- [ ] `CHK-1104` 保证 ContentProject 不要求 liveRoomId、麦兔标题、画布、帧率或 RenderProfile。
- [ ] `CHK-1105` 建立 ContentProject 工作区“目标与事实”视图，展示事实字段来源、有效期、冲突和未解决问题。

### 1.2 DesignBrief 解析与确认

- [ ] `CHK-1120` 实现受限 `parse-brief` provider 调用，原始文本按 untrusted user data 传入，不可覆盖系统规则。
- [ ] `CHK-1121` 输出 objective、theme/story、audience、priorities、persona、tone、duration、must include/avoid、staging、interaction、conversion、visual、audio 和 open questions。
- [ ] `CHK-1122` 对解析结果做严格 schema 校验、长度/枚举限制和提示注入防护。
- [ ] `CHK-1123` 最多提出 1-3 个真正影响结果的问题并提供推荐答案，允许跳过非阻断问题。
- [ ] `CHK-1124` 保存原文、模型原始响应 artifact、解析值、用户修改值、provider/model/prompt revision 和 diff。
- [ ] `CHK-1125` 实现 DesignBrief 可编辑界面、自动保存、问题回答和显式确认预览。

### 1.3 StoryBrief、剧本、节目结构与 Shot

- [ ] `CHK-1140` 实现确定性 `DesignBrief -> StoryBriefRevision` 转换，固定事实、模板贡献占位和输入 fingerprint。
- [ ] `CHK-1141` 实现 `POST /content-projects/{code}/confirm`，重复请求幂等，确认后不可原地修改。
- [ ] `CHK-1142` 实现生成上下文编译器，严格分离 system baseline、批准事实、用户目标和外部参考。
- [ ] `CHK-1143` 实现 Script/ScriptBlock 生成，保存模块类型、台词、时长、商品、CTA/互动、事实引用和来源。
- [ ] `CHK-1144` 实现 FactCitation 逐事实句扫描；价格、促销、库存、赠品和功效无批准事实时阻断。
- [ ] `CHK-1145` 允许模型生成非事实连接语和表达，不再要求逐句复制事实卡原句。
- [ ] `CHK-1146` 实现 ContentProgramRevision 和有序 ProgramSegment，记录语义目标、进入/退出条件和 ScriptBlock 区间。
- [ ] `CHK-1147` 实现 `generate-shot-list`，生成稳定 Shot、构图意图、素材角色需求、音频动作、连续性和验收标准。
- [ ] `CHK-1148` 校验必讲块映射完整、来源镜头存在、无循环映射，并确保 Shot 与 `MaituSceneBlueprint`、`TimelineSegment` 概念分离。
- [ ] `CHK-1149` 实现剧本、ProgramSegment 和 ShotList 修订时间线、来源下钻和人工新修订。

### 1.4 live_room ProductionVariant 与输入确认

- [ ] `CHK-1160` 实现 ContentProject 下创建/查询 ProductionVariant。
- [ ] `CHK-1161` live_room 分支要求目标空白草稿 liveRoomId、期望标题、现场保护策略和 `auto_write_draft / plan_only`。
- [ ] `CHK-1162` 实现 authoritative API 的房间存在性、草稿态、未开播、空白状态和目标身份 attestation。
- [ ] `CHK-1163` 先复用当前 inventory 建立确定性执行候选集，固定 InventorySnapshot 和素材绑定修订。
- [ ] `CHK-1164` 实现 ProductionVariant confirm，固定 StoryBrief/Script/ShotList、分支目标、素材输入和 fingerprint。
- [ ] `CHK-1165` liveRoomId、标题、现场或 inventory 缺失时拒绝确认；ContentProject 内容确认不受影响。
- [ ] `CHK-1166` 实现 live_room 配置页连续流程和“有效输入”预览。

### 1.5 MaituSceneBlueprint、LayerBlueprint 与 BuildPlan

- [ ] `CHK-1180` 从固定 ShotList 生成有序 MaituSceneBlueprint，记录 ProgramSegment/Shot、切换策略和预计活跃区间。
- [ ] `CHK-1181` 生成稳定 LayerBlueprint，包含 role、asset/binding revision、归一化几何、z-order、视音频属性和来源。
- [ ] `CHK-1182` 创建 ShotProjectionLink，支持一对多和多对一并保存关系类型和适用区间。
- [ ] `CHK-1183` 实现确定性 BuildPlan 编译器，固定 content/variant/revision/inventory/material/policy/site fingerprint。
- [ ] `CHK-1184` 仅允许 rename、默认空场景、创建场景、插入白名单素材、写脚本、受控属性、保存和只读验证。
- [ ] `CHK-1185` 拒绝未知 operation、任意 selector/URL、白名单外素材、非目标房间、清空房间和开播动作。
- [ ] `CHK-1186` 每个 operation 生成前置条件、后置条件、幂等键、capability、来源 Shot/ScriptBlock 和证据要求。
- [ ] `CHK-1187` 实现时长估算和约 50% 偏差 warning；单一时长偏差不得阻断。
- [ ] `CHK-1188` 生成结构化素材需求、冲突和分支质量报告。

### 1.6 门禁、preflight、授权与草稿执行

- [ ] `CHK-1200` 实现统一七段门禁执行器：身份版本、授权事实、输入边界、结构引用、执行约束、分支质量、证据完整性。
- [ ] `CHK-1201` 每项门禁输出 `pass/warning/blocked/not_applicable`、稳定规则码、规则版本、证据和修复建议。
- [ ] `CHK-1202` 静态门禁通过后自动执行只读 preflight，验证登录、URL、房间 ID、未开播、空白、现场 fingerprint 和素材可用性。
- [ ] `CHK-1203` `plan_only=true` 永不申请执行授权；`auto_write_draft=true` 仅在无 blocked 时请求短期 write_draft 授权。
- [ ] `CHK-1204` 授权绑定 BuildPlan hash、liveRoomId、现场 fingerprint 和单次 capability。
- [ ] `CHK-1205` 扩展 Browser-use Worker 支持安全 rename、创建场景、插入素材、写脚本、受控属性和保存。
- [ ] `CHK-1206` 每个写操作前检查前置条件和授权，操作后回读现场身份/属性并保存截图、DOM 摘要或必要网络证据。
- [ ] `CHK-1207` 对超时或不确定响应进入 reconcile_required，禁止直接重放写操作。
- [ ] `CHK-1208` finalize 逐场景/逐图层比较 Blueprint，输出偏差、证据完整率和现场 fingerprint。
- [ ] `CHK-1209` 缺层、错素材、错房间、未保存、现场变化或开播态必须停止；软视觉偏差只可 warning。
- [ ] `CHK-1210` 完成后保持 `ready_for_go_live=false`，Worker、API 和 UI 均不存在隐式开播路径。

### 1.7 Release、回读与修改流程

- [ ] `CHK-1220` 生成 live_room_draft release candidate，manifest 固定完整内容链、素材、inventory、BuildPlan、QC、授权和证据。
- [ ] `CHK-1221` 实现 release 校验、批准、草稿 DeliveryAttempt、authoritative readback 和 100% 证据完整率门禁。
- [ ] `CHK-1222` 成功写入不等于曝光；不创建虚假的 ContentExposureEvent。
- [ ] `CHK-1223` 实现 `clone` 到新空白房间，复制业务输入但清除旧目标 fingerprint、授权和执行状态。
- [ ] `CHK-1224` 禁止第一版对非空旧房间做增量重建、清空或差异回滚。
- [ ] `CHK-1225` 实现从 operation -> `LayerBlueprint/MaituSceneBlueprint` -> Shot -> ProgramSegment -> ScriptBlock -> StoryBrief -> facts/templates 的全链路下钻。
- [ ] `CHK-1226` 在 live-room UI 分开展示 workflow、quality、release、delivery 和现场 readback 状态。

### 1.8 Phase 1 退出门禁

- [ ] `CHK-1290` 端到端用例从 ContentProject 输入生成一个受保护规则外的空白麦兔草稿，并完成不可变 release。
- [ ] `CHK-1291` 每个事实句、Shot、`MaituSceneBlueprint`、`LayerBlueprint` 和 operation 均通过 `ShotProjectionLink` 显式回溯；旧 Scene/历史场景投影不能代替该验收，release 证据完整率 100%。
- [ ] `CHK-1292` 非空、已开播、错房间、现场变化、白名单外素材和未知操作均被拒绝。
- [ ] `CHK-1293` 注入网络超时和 Worker 崩溃后能够 reconcile，且无重复场景、素材、脚本或保存动作。
- [ ] `CHK-1294` ContentProject 无房间仍可确认；live_room 分支缺 title/ID/现场不能确认。
- [ ] `CHK-1295` 同一输入重放可解释结构结果和外部差异，RunManifest、指纹和现场证据齐全。
- [ ] `CHK-1296` Phase 1 产品、工程、数据、安全和运营验收签字并归档验收包。

---

## Phase 2. 素材约束、选材缺口与外部内容模板

> 目标：补齐要素资产库和外部录屏到内容策略模板，并接入 Phase 1 主链。
> 依赖：Phase 1 全部退出门禁完成。

### 2.1 素材身份、版本、Rendition 与同步生命周期

- [ ] `CHK-2101` 将 Asset 明确为逻辑作品，追加 AssetVersion、AssetFile/Rendition 和 derived_from 关系。
- [ ] `CHK-2102` 为 Asset/AssetVersion 落库三个相互独立的分类维度：单值 `media_kind`、多值 `material_role` 和单值 `execution_capability`；数据库约束、schema 和 revision fingerprint 均包含这三个维度。
- [ ] `CHK-2103` 实现 `media_kind = image/video/audio/digital_human/text/template_preview/document`，禁止以扩展名或麦兔页签作为持久化业务语义。
- [ ] `CHK-2104` 实现多值 `material_role = background/product_display/digital_human/brand_title/promotion_text/decoration_foreground/supporting_video/voice/background_music/sound_effect`，素材包、素材需求和关系约束只引用该维度。
- [ ] `CHK-2105` 实现 `execution_capability = maitu_bound/local_only/reference_only/unavailable`，状态只能由可验证绑定与生命周期证据确定，不得由 `media_kind`、`material_role`、`asset_type` 或 `maitu_category` 推断。
- [ ] `CHK-2106` 迁移现有 `asset_type/maitu_category` 为来源/兼容字段；为无法确定的三维分类创建人工校正任务，禁止通过不可靠映射自动赋予 `maitu_bound` 或可执行业务角色。
- [ ] `CHK-2107` 扩展素材创建、详情、列表、批量更新和筛选 API，分别读写/查询三个维度，并对未知枚举、单值/多值混用和不合法组合返回稳定错误码。
- [ ] `CHK-2108` 在素材库和详情 UI 中分别展示媒体类型、业务角色复选和执行能力；提供迁移待确认筛选、来源证据和批量校正，不把三者合并为一个“类型”控件。
- [ ] `CHK-2109` 选材、素材包解析、ResolvedMaterialSnapshot 和 BuildPlan 门禁只消费已固定的三维分类；`template_preview` 默认 `reference_only`，`local_only/reference_only/unavailable` 均不得冒充可写入麦兔素材。
- [ ] `CHK-2110` 保存内容 checksum、MIME、尺寸/时长、存储相对路径、技术元数据和生成运行。
- [ ] `CHK-2111` 版本化麦兔 material_id、页签、最近确认时间、binding revision 和 inventory evidence。
- [ ] `CHK-2112` 实现 `发现 -> 对账 -> 软失效 -> 人工确认/再次发现`，一次同步缺失不得直接 unavailable。
- [ ] `CHK-2113` 实现连续快照或明确现场证据确认失效，历史配置继续引用原绑定和证据。
- [ ] `CHK-2114` 保存分析模型、提示、参数、输出 checksum、质量和人工覆盖；重分析不覆盖旧结果。
- [ ] `CHK-2115` 用 checksum 和 perceptual hash 标记重复候选，合并时保留别名、来源和历史引用。
- [ ] `CHK-2116` 实现 assets versions/renditions API 和同步任务 UI，展示差异、质量、失败重试和软失效。

### 2.2 RightsGrant 与发布影响

- [ ] `CHK-2120` 实现 RightsGrant 主体、来源、用途、渠道、地域、有效期、修改/衍生、AI、署名、肖像/声音、凭证和撤销字段。
- [ ] `CHK-2121` 实现 `draft -> active -> expired/revoked/superseded` 和 `deny/revoked > narrower > broader` 合并。
- [ ] `CHK-2122` 未知权利素材允许受控分析但不得进入可交付 release。
- [ ] `CHK-2123` 在选材、release candidate、delivery 和后续 schedule 分别重验权利。
- [ ] `CHK-2124` 实现 grant 创建、revoke、impact API 和受影响 variant/release/decision HumanTask。
- [ ] `CHK-2125` 撤销/到期立即排除未来候选，阻止新交付但不删除历史证据。
- [ ] `CHK-2126` Rendition 默认继承并收紧源权利，不得扩大许可。

### 2.3 约束 Profile、命名区域与规则构建器

- [ ] `CHK-2140` 实现 AssetConstraintProfile/Revision、稳定 constraint_key、scope、hardness、parameters 和 fingerprint。
- [ ] `CHK-2141` 实现命名区域、矩形/多边形、锚点和归一化 `[0,1]` 坐标；保留原像素为证据。
- [ ] `CHK-2142` 实现 `allowed_region / forbidden_region / provide_named_region / require_named_region`。
- [ ] `CHK-2143` 实现 `preserve_aspect_ratio / size_range / scale_range / crop_policy / rotation_policy`。
- [ ] `CHK-2144` 实现 `pin_layer_top / pin_layer_bottom / above_role / below_role / avoid_overlap`。
- [ ] `CHK-2145` 实现 `align_anchor / distance_range / loop_policy / mute_policy / volume_range`。
- [ ] `CHK-2146` 实现背景 table_surface/surface_line 与商品 bottom_center 的桌面摆放组合规则。
- [ ] `CHK-2147` 实现多个硬约束取交集、soft 分层目标、系统规则不可覆盖和显式 constraint_key override。
- [ ] `CHK-2148` 实现房间私有覆盖 diff、原因、操作者和“提升为全局新修订”的二次确认。
- [ ] `CHK-2149` 提供约束 profile/revisions API 和表单式规则构建器、区域预览、规则模板及冲突展示。

### 2.4 求解器契约与诊断

- [ ] `CHK-2160` 定义 solver-independent ConstraintProblem、变量、硬/软约束、目标、预算、seed 和 warm-start schema。
- [ ] `CHK-2161` 建立代表性问题集，覆盖角色次数、排他、z-order、几何、桌面区域、音频和无解冲突。
- [ ] `CHK-2162` 通过 ADR 选择 OR-Tools CP-SAT/MIP 或维持等价 adapter；业务服务不得手写回溯求解器。
- [ ] `CHK-2163` 实现 `optimal/feasible/infeasible/unknown/invalid_model`，unknown 不得当作 infeasible 或自动可执行。
- [ ] `CHK-2164` feasible 保存 gap；infeasible 返回近似最小冲突集、来源实体和可执行修复。
- [ ] `CHK-2165` 固定 solver/version/variables/weights/seed/time/memory 并保存求解证据 artifact。
- [ ] `CHK-2166` 对确定性、超时、无解解释、整数精度、软目标不抵消硬约束做回归和属性测试。

### 2.5 素材分组与素材模板包

- [ ] `CHK-2180` 实现 AssetGroup 和多对多成员；允许跨组重复、不允许嵌套、不承载约束。
- [ ] `CHK-2181` 实现分组创建/查询/修改/删除、成员批量替换接口和并发保护。
- [ ] `CHK-2182` 实现 MaterialPack、Revision、Entry、Exclusivity 和 `draft/published/superseded/archived`。
- [ ] `CHK-2183` 分类包只属于一个 role 且不可递归；总体包可引用分类包但不可引用总体包。
- [ ] `CHK-2184` 实现 required/optional/alternative、min/max occurrences、scope、pack constraints 和 alternative_set_key。
- [ ] `CHK-2185` 实现角色域 exclusive_roles，两个不兼容排他包必须报告冲突。
- [ ] `CHK-2186` 实现每个 role 的沿用/追加/替换；替换显式移除总体包该域内容与排他。
- [ ] `CHK-2187` 合并同资产来源、`required > alternative > optional`、硬规则和来源列表。
- [ ] `CHK-2188` 发布修订不可变，编辑跟随 latest published，确认时展开为明确素材编码而不是动态分组引用。
- [ ] `CHK-2189` 实现 material pack create/revision/publish/resolve API，返回白名单、来源、规则、冲突和 fingerprint。
- [ ] `CHK-2190` 实现分组和素材包工作区，支持批量成员、版本 diff、发布、排他和解析预览。

### 2.6 分支选材、解释排序与 AssetGap

- [ ] `CHK-2200` 分支 UI 分开选择总体包、role 模式/分类包、分组和零散素材。
- [ ] `CHK-2201` 每个素材支持 optional 或至少使用一次，分别支持 live_room 约束覆盖和 video 时间轴/画幅覆盖。
- [ ] `CHK-2202` 确认时固定包 revision、展开分组、去重、合并约束/权利、创建 ResolvedMaterialSnapshot。
- [ ] `CHK-2203` 先做白名单、执行能力、权利、必用/排他和硬约束确定性过滤，再执行排序。
- [ ] `CHK-2204` 排序综合 role、语义、画幅/时长、质量、soft、重复惩罚和合格效果证据。
- [ ] `CHK-2205` 返回分项分数、版本、排除码、来源和选择理由；新素材无效果样本时效果分中性。
- [ ] `CHK-2206` 定义 AssetGap 的 open/candidate_found/resolved/waived/obsolete 状态和来源链。
- [ ] `CHK-2207` candidate_found 前完成分支绑定、RightsGrant、授权和约束预检；resolved 固定资产/version/rendition/binding/处理人。
- [ ] `CHK-2208` waived 只对当前分支 revision 生效；新素材匹配不得静默修改已确认输入。
- [ ] `CHK-2209` 实现 gap 查询、修改、resolve API 和缺口修复 UI。
- [ ] `CHK-2210` 实现素材详情“效果与关系”，低样本结果标记不可自动推荐。

### 2.7 外部直播采集与统一媒体时间线

- [ ] `CHK-2240` 实现 WatchTarget 的平台 adapter 边界，首期抖音；记录采集授权、条款版本、用途、owner、访问和保留。
- [ ] `CHK-2241` 无合法依据、来源撤销或 kill switch 开启时不得开始/继续采集。
- [ ] `CHK-2242` 固定 StreamCap/douyinLive 版本，保存 TS 分片、原始事件、checksum、工具版本和采集配置。
- [ ] `CHK-2243` 为 CaptureSession 建立 media-timeline.v1 和统一 `[start_ms,end_ms)` 半开区间。
- [ ] `CHK-2244` 将分片、音频、ASR token/segment、OCR、关键帧、视觉区间和互动摘要映射到统一时钟。
- [ ] `CHK-2245` 检测掉帧、断流、漂移和缺失通道，保存校准方式、置信度和质量 flags。
- [ ] `CHK-2246` 分离原始、标准和发布三层存储与访问，不按数组下标拼接多模态结果。
- [ ] `CHK-2247` 实现 retention worker、删除/隔离、断点恢复、心跳和 sidecar 故障处理。
- [ ] `CHK-2248` 实现来源直播间和录屏场次 UI，展示状态、媒体、质量、互动摘要、保留期限和证据。

### 2.8 清洗与 content-strategy.v2

- [ ] `CHK-2260` 执行 ASR、OCR、关键帧、视觉和互动摘要，保存 provider/model/prompt/schema/checksum 和 AnalysisRun。
- [ ] `CHK-2261` 实现转写校正、噪声清理、场景边界、内容模块和置信度编辑。
- [ ] `CHK-2262` 识别并隔离来源商品事实、价格、促销、平台噪声和一次性活动信息，保留来源证据但不进入发布投影。
- [ ] `CHK-2263` 一个模板草稿和发布 projection 必须且只能绑定一个来源直播间，所选 CaptureSession 必须全部属于该直播间；发现跨房间场次时以稳定规则码阻断确认/发布，并要求拆成不同模板。跨直播间组合只能在 ContentProject 的主/次模板选择阶段发生。
- [ ] `CHK-2264` 实现 content-strategy.v2 的 target_category、program_outline、duration/module/product rotation/interaction/conversion/host/material policies。
- [ ] `CHK-2265` 实现 reviewed_examples 槽位化、layout_reference 和完整 provenance。
- [ ] `CHK-2266` 分别持久化 `content_readiness`、`layout_fidelity`、`buildability`，API/DB/UI 使用定义内状态。
- [ ] `CHK-2267` 实现媒体完整性、时间线、ASR/OCR、事实去除、模块证据、人工审核、相似性和 schema 发布门禁。
- [ ] `CHK-2268` 实现连续文本重合、品牌/主播特征模仿、版权画面、个人与敏感信息检查和人工审阅。
- [ ] `CHK-2269` 允许 `content_readiness=ready`、`layout_fidelity=none|approximate`、`buildability=reference_only` 发布；近似布局缺失不阻断内容模板。
- [ ] `CHK-2270` 保持 layout-hypothesis.v1 只读；新发布接口按 contract version 产生不可变 projection。
- [ ] `CHK-2271` 实现播放器、ASR/OCR、模块和来源证据联动的数据清洗 UI。
- [ ] `CHK-2272` 实现模板草稿、问题、整体审核、发布、不可变版本和生产使用记录 UI。

### 2.9 主次模板与生产主链接入

- [ ] `CHK-2300` 在 ContentProject 支持最多一个主模板、任意数量次要模板和无主模板状态。
- [ ] `CHK-2301` 按品类/目标推荐主模板和次要模块贡献，展示兼容、重复和冲突。
- [ ] `CHK-2302` 允许用户接受或修改模块贡献，并固化 TemplateContributionDecision。
- [ ] `CHK-2303` 实现主模板控制总体阶段，次要模板仅补缺或经显式模块决策替换。
- [ ] `CHK-2304` 上下文编译器按品类过滤、模块检索、骨架去重，只发送结构摘要和采用例句。
- [ ] `CHK-2305` 生成结果列出采用、未采用和冲突来源；模板例句永远不能进入事实白名单。
- [ ] `CHK-2306` 把模板 material_cues 转成 Shot/分支素材需求，不把 reference_only layout 当可执行 Blueprint。
- [ ] `CHK-2307` 将素材 snapshot、constraint solver、rights 和 gap 门禁接入 Phase 1 variant 生成与 release。

### 2.10 Phase 2 退出门禁

- [ ] `CHK-2389` 验证 `media_kind`、多值 `material_role`、`execution_capability` 可独立保存/筛选/修订：同一素材可拥有多个业务角色，`template_preview/reference_only` 和 `local_only` 不能进入麦兔写入，旧 `asset_type/maitu_category` 不能隐式赋予角色或执行能力。
- [ ] `CHK-2390` 验证同一素材可加入两组且独立移除，分组变化不影响历史 snapshot。
- [ ] `CHK-2391` 验证总体/分类包沿用、追加、替换、必用、备选和排他全部行为。
- [ ] `CHK-2392` 验证桌面区域/锚点/层级约束可解，无命名区域或冲突时有可执行诊断。
- [ ] `CHK-2393` 验证未绑定必用素材阻断、普通未绑定候选排除、一次同步缺失不误删。
- [ ] `CHK-2394` 验证完整选材解释和 AssetGap 从 open 到 resolved 的不可变证据。
- [ ] `CHK-2395` 从同一抖音来源直播间的多场录屏发布一个去事实化内容模板，全部模块可反查媒体区间；混入另一个直播间的 CaptureSession 时确认和发布均被拒绝并提示拆分模板。
- [ ] `CHK-2396` reference_only 模板可以贡献内容但无法通过可执行布局身份门禁。
- [ ] `CHK-2397` 权利撤销影响分析完整，未来选材/交付失败关闭且历史证据保留。
- [ ] `CHK-2398` Phase 2 产品、工程、数据、安全和运营验收签字并归档验收包。

---

## Phase 3. 同内容成片、剪辑时间轴与交付

> 目标：同一内容修订独立产出麦兔草稿和竖屏成片，建立确定性时间轴、渲染质量与视频 release。
> 依赖：Phase 2 全部退出门禁完成。

### 3.1 rendered_video 分支与 ProductionTimeline

- [ ] `CHK-3101` 支持从已确认 ContentProject 或 live_room variant 的固定内容修订创建 rendered_video variant。
- [ ] `CHK-3102` 固定画布、帧率、目标时长策略、RenderProfile、音频/字幕策略和交付渠道。
- [ ] `CHK-3103` 确保 video 和 live_room 分支状态、运行、素材覆盖、release 和失败互不污染。
- [ ] `CHK-3104` 实现 ProductionTimeline 权威对象并采用/严格映射 OTIO Timeline/Stack/Track/Clip/Gap/Transition。
- [ ] `CHK-3105` 使用 RationalTime/TimeRange 表达帧边界、source range、变速和 transition，不以毫秒替代编辑时间。
- [ ] `CHK-3106` 实现 TimelineSegment 的 track、timeline/source range、playback、来源内容、asset checksum、transform/crop、转场、音量和 artifact refs。
- [ ] `CHK-3107` 支持画面、overlay、数字人口播/配音、BGM、音效和字幕轨。
- [ ] `CHK-3108` 校验重叠、负时长、timebase、source available range 和连续性。
- [ ] `CHK-3109` 创建 ShotProjectionLink 和 TimeMapping，将编辑时间映射为媒体 PTS 与会话毫秒半开区间。
- [ ] `CHK-3110` 实现 timeline GET/PUT、expected revision、结构化调整和 stale 传播。

### 3.2 阶段化生产与内容寻址 artifacts

- [ ] `CHK-3120` 将 brief、script、shot planning、asset selection、voice、subtitle、render、QC 统一接入 WorkflowRun/StepRun。
- [ ] `CHK-3121` 每个阶段只读固定输入 artifact，输出内容寻址 artifact、manifest 和 lineage。
- [ ] `CHK-3122` 支持从最近成功阶段重试，并保证变更输入后创建新 run/revision。
- [ ] `CHK-3123` 复用并版本化 Kokoro TTS provider，固定声音授权、模型、参数、音频 checksum 和响度目标。
- [ ] `CHK-3124` 生成版本化 ASS 字幕，保存 ScriptBlock/word timing、字体、样式、安全区和 checksum。
- [ ] `CHK-3125` 生成 poster、asset plan、render log、quality report 和最终 video artifacts。
- [ ] `CHK-3126` 记录每步 CPU/GPU、耗时、token、存储和估算/实际成本。

### 3.3 RenderManifest、FFmpeg 与质量门禁

- [ ] `CHK-3140` 版本化 RenderProfile，默认 1080x1920 H.264/AAC 但不在业务逻辑硬编码参数。
- [ ] `CHK-3141` 用结构化 FFmpeg 命令构建器生成滤镜图；禁止拼接未校验的 shell 输入。
- [ ] `CHK-3142` RenderManifest 固定 timeline、输入 checksum、命令、滤镜、工具版本、seed 和资源使用。
- [ ] `CHK-3143` QC 覆盖 ffprobe、编解码、分辨率、帧率、时长和音视频同步。
- [ ] `CHK-3144` QC 覆盖黑帧、冻结帧、静音、削波/响度、结尾截断。
- [ ] `CHK-3145` QC 覆盖字幕安全区/可读时长、必讲 ScriptBlock、素材许可和文件 checksum。
- [ ] `CHK-3146` blocked QC 保留诊断产物但禁止发布；人工 waiver 绑定产物 revision、理由、批准者和有效范围。
- [ ] `CHK-3147` 对同一 RenderManifest 重试生成结构差异报告，解释外部工具造成的输出差异。

### 3.4 视频 release、provenance 与 Delivery

- [ ] `CHK-3160` QC 通过只生成 rendered_video release candidate，不自动视为批准或已交付。
- [ ] `CHK-3161` 批准后创建 ReleaseManifest，固定内容、timeline、素材/权利、render/QC、artifact 和策略版本。
- [ ] `CHK-3162` 生成 IPTC sidecar，包含权利、技术元数据、AI 生成/编辑声明和平台扩展。
- [ ] `CHK-3163` 评估并实现 C2PA Content Credentials，记录 ingredient；不能实现时通过 ADR 明确兼容边界和退出条件。
- [ ] `CHK-3164` 实现资产库登记和目标渠道 DeliveryAttempt，每次提交重验权利和授权。
- [ ] `CHK-3165` 麦兔上传作为独立 upload_asset capability，回读目标 material identity 和 checksum，不等同于本地渲染完成。
- [ ] `CHK-3166` 实现 revoke 对未来交付、排播和效果决策的影响传播。

### 3.5 成片生产 UI

- [ ] `CHK-3180` 建立 `/production/videos` 列表、筛选、运行进度、成本、异常和深链。
- [ ] `CHK-3181` 实现结构化 segment 顺序、起止、转场、音轨和字幕调整，不建设通用 NLE。
- [ ] `CHK-3182` 展示 Shot/ScriptBlock/素材/音频/字幕来源、timeline revision diff 和 stale 状态。
- [ ] `CHK-3183` 分开展示 production completed、quality failed、release candidate、approved、delivered 和 exposed。
- [ ] `CHK-3184` 支持预览、poster、QC 规则下钻、waiver 和产物下载权限。

### 3.6 Phase 3 退出门禁

- [ ] `CHK-3290` 同一 StoryBrief/Script/ShotList 独立产出麦兔草稿和竖屏成片，任一失败不改变另一分支。
- [ ] `CHK-3291` 每个 TimelineSegment 可回溯 Shot、ScriptBlock、AssetFile、voice 和 subtitle artifact。
- [ ] `CHK-3292` 帧率、TimeMapping、素材权利、RenderManifest 和 release checksum 可重放验证。
- [ ] `CHK-3293` 黑帧、静音、字幕安全区、必讲缺失和权利失败均阻止视频 release。
- [ ] `CHK-3294` 本地完成、release 批准、渠道交付、麦兔上传和曝光状态无混淆。
- [ ] `CHK-3295` Phase 3 产品、工程、数据、安全和运营验收签字并归档验收包。

---

## Phase 4. 真实发布、曝光与人工归因闭环

> 目标：将准确 release、实际曝光和版本化指标对齐，产出可下钻的描述性与关联性结果。
> 依赖：Phase 3 全部退出门禁完成。

### 4.1 发布与运营工作区

- [ ] `CHK-4101` 建立 `/production/releases` 列表、manifest、批准、delivery、revoke、影响和证据详情。
- [ ] `CHK-4102` 建立 `/operations/live-sessions`，创建 LiveSession 并绑定精确 ReleaseManifest。
- [ ] `CHK-4103` 录入平台、外部会话、时区、开始/结束、账号、目标资源和 source evidence。
- [ ] `CHK-4104` 在 UI 明确区分 planned、delivered、exposed，未有 served log 时不得默认已曝光。
- [ ] `CHK-4105` 建立异常、人工任务、时间对齐、缺失通道和数据新鲜度视图。

### 4.2 ContentExposureEvent 与内容时间线

- [ ] `CHK-4120` 实现 exposure 写入 API，支持平台 served log、人工录入和录屏识别三种 source type。
- [ ] `CHK-4121` 保存 release/variant/revision、事件起止、ProgramSegment、Shot、载体投影、素材、商品、CTA、策略和置信度。
- [ ] `CHK-4122` 切场、断流、重复、人工替换和 release 切换使用追加/修正事件，不覆盖历史。
- [ ] `CHK-4123` 保证 LiveSession 同一时刻最多一个有效 release exposure，冲突进入 reconcile。
- [ ] `CHK-4124` 实现 ContentTimelineSpan，从实际 exposure 映射内容对象和素材。
- [ ] `CHK-4125` 实现 TimeMapping 的 offset、drift、证据、coverage 和版本；量化无法识别区间。
- [ ] `CHK-4126` 时间对齐不达阈值时降级到 session 级或 insufficient_data。
- [ ] `CHK-4127` 提供 content timeline GET/PUT 和结构化人工校正，校正创建新 revision。

### 4.3 事件摄取、Metric Catalog 与 DataContract

- [ ] `CHK-4140` 实现 LiveSession ingest API，按 `(source_system, source_event_id)` 幂等并保存 ingest batch/checksum。
- [ ] `CHK-4141` 支持 upsert/delete、退款、撤销、tombstone、event/processing time 和 source timezone。
- [ ] `CHK-4142` 首批标准指标覆盖曝光、停留/留存、互动、点击、加购、成交、退款和内容质量。
- [ ] `CHK-4143` 每个 MetricDefinitionRevision 固定 owner、含义、grain、单位/币种、分子/分母、时间、维度、去重、窗口和质量 SLO。
- [ ] `CHK-4144` 每个来源 DataContract 固定 schema、主键、更新/删除、event time、迟到、枚举、敏感级别、量级和 owner。
- [ ] `CHK-4145` 建立原始、标准、汇总、指标封存点，任何 AttributionRun 指明读取的 snapshot。
- [ ] `CHK-4146` 实现完整性、唯一性、引用、时效、分布和 source-to-standard 对账；坏批次隔离而非补零。
- [ ] `CHK-4147` 实现指标目录和 DataContract 治理 UI，支持 revision、diff、owner、质量和 consumer 影响。

### 4.4 描述性与关联性归因

- [ ] `CHK-4160` 实现 AttributionRun 创建、校验、计算、review、publish、insufficient_data 和 failed 状态。
- [ ] `CHK-4161` 固定 input snapshots、release、exposure revision、metric revision、窗口、基线、规则、对齐、方法和代码版本。
- [ ] `CHK-4162` 产出 session/span/ProgramSegment/Shot/ScriptBlock/template module/asset/product/CTA 粒度结果。
- [ ] `CHK-4163` 保存 numerator、denominator、sample、sessions、statistic/effect、interval、quality、assumptions、limits 和 lineage。
- [ ] `CHK-4164` 时间窗和切换前后分析仅标记 descriptive/associational，UI 禁用因果措辞。
- [ ] `CHK-4165` 指标、曝光、对齐、异常、样本和方法门禁通过后才可 published。
- [ ] `CHK-4166` 迟到、backfill、删除、退款和人工校正创建新 result revision 并 supersede，不覆盖旧结果。
- [ ] `CHK-4167` 提供归因列表、比较、下钻和证据资格 UI，展示样本、区间、方法、质量和封存点。

### 4.5 Phase 4 退出门禁

- [ ] `CHK-4290` 一场 LiveSession 绑定精确 release，并通过人工/录屏辅助建立实际 ContentExposureEvent。
- [ ] `CHK-4291` 一个 published 结果可下钻到曝光、指标桶、内容区间、素材/模板、封存点、方法和代码。
- [ ] `CHK-4292` 重复事件不重复计数；退款、删除、迟到和 backfill 产生可解释修订。
- [ ] `CHK-4293` 样本/对齐不足返回 insufficient_data；相关性在 API 和 UI 均不显示为因果。
- [ ] `CHK-4294` 历史无曝光数据只保留计划/推断来源并降低证据等级，不伪造 served log。
- [ ] `CHK-4295` Phase 4 产品、工程、数据、安全和运营验收签字并归档验收包。

---

## Phase 5. 自动采集、可信估计与效果驱动再生产

> 目标：实现自动数据回流、点时正确的决策日志、合格关联/准实验和受控再生产。
> 依赖：Phase 4 全部退出门禁完成。

### 5.1 自动来源适配与数据质量

- [ ] `CHK-5101` 为抖音互动、麦兔/JD 运营指标及后续来源实现版本化 adapter 和 DataContract。
- [ ] `CHK-5102` 明确每个来源使用官方 API、授权导出或受控浏览器采集；记录凭据、条款、限流、成本和退出方案。
- [ ] `CHK-5103` 实现 watermark、allowed lateness、退款/撤销窗口、backfill 和 snapshot sealing。
- [ ] `CHK-5104` 实现 exposure reconciliation，比较计划、delivery readback、served log 和录屏识别。
- [ ] `CHK-5105` 实现 DataQualityIncident、隔离、owner、修复、重放和 source-to-standard 对账。
- [ ] `CHK-5106` 建立 ingest freshness、complete、duplicate、schema drift、distribution drift 和 reconciliation SLO/告警。
- [ ] `CHK-5107` 验证数据积压 backpressure：已接收批次不丢失，分析/归因延迟在 UI 可见。

### 5.2 FeatureSnapshot、DecisionLog 与点时正确性

- [ ] `CHK-5120` 在选材、模板、策略和生成建议时写不可变 DecisionLog。
- [ ] `CHK-5121` 保存候选全集/排除摘要、FeatureSnapshot、策略/模型、权重、探索、propensity 和最终选择。
- [ ] `CHK-5122` 后续关联实际 release 和 exposure，不以计划选择冒充曝光。
- [ ] `CHK-5123` 实现 feature 定义版本、event-time 截止和 point-in-time join。
- [ ] `CHK-5124` 构建离线 replay，证明任何训练/评估样本不能读取决策后的未来数据。
- [ ] `CHK-5125` 对缺 propensity 或缺实际 exposure 的历史数据强制 descriptive-only。
- [ ] `CHK-5126` 评估在线 Feature Store 门槛；未满足时使用关系库 snapshot，满足时通过 ADR 且不改变领域契约。

### 5.3 EffectEligibilityPolicy 与效果对象

- [ ] `CHK-5140` 实现 PerformanceProfile、AssociationalEstimate、CausalEstimate 的查询、revision 和状态机。
- [ ] `CHK-5141` 每个对象固定实体 revision、上下文、metric、窗口、snapshot、tier、方法、interval、drift 和来源结果。
- [ ] `CHK-5142` 实现 EffectEligibilityPolicy：指标一致、曝光完整、时间对齐、最小场次/样本、稳定性、新鲜度和异常。
- [ ] `CHK-5143` 分用途设置证据门槛：展示 descriptive、人工建议 associational、自动排序 approved associational、策略流量变化 quasi/randomized。
- [ ] `CHK-5144` 实现 candidate/eligible/approved/rejected/review_required/revoked/superseded 和过期。
- [ ] `CHK-5145` 实现 estimate approve/revoke API，批准不能修改 evidence tier，撤销传播到依赖 DecisionLog/推荐。
- [ ] `CHK-5146` 建立 `/learning/effects` UI，按对象、上下文、样本、区间、漂移和决策使用记录展示。

### 5.4 准实验与敏感性分析

- [ ] `CHK-5160` 为准实验预先记录处理机制、目标估计量、纳入规则、窗口、协变量、识别假设和分析计划。
- [ ] `CHK-5161` 实现可比性诊断、平行趋势或方法对应假设、负向对照和敏感性分析。
- [ ] `CHK-5162` 保存方法/代码、数据封存、排除漏斗、区间和限制；方法不充分时降级为 associational。
- [ ] `CHK-5163` 评审通过的准实验才能生成 CausalEstimate，未通过不能使用因果表述或策略扩量。
- [ ] `CHK-5164` 对退款延迟、跨会话干扰、策略污染和选择偏差执行模拟测试。

### 5.5 受控排序与再生产

- [ ] `CHK-5180` 推荐器始终先执行权利、事实、白名单和硬约束过滤，再使用软效果权重。
- [ ] `CHK-5181` 只读取当前 LearningPolicy 允许、approved、未过期且上下文匹配的估计。
- [ ] `CHK-5182` 保留新对象和不确定策略的预算化探索，探索不得绕过安全或硬约束。
- [ ] `CHK-5183` 实现 point-in-time 离线回放、覆盖率、校准、分群稳定性和策略评估。
- [ ] `CHK-5184` 监控 selection/position/survivorship bias、自我强化、流量漂移和训练/服务偏差。
- [ ] `CHK-5185` 再生产创建新的 ContentProjectRevision 或 ProductionVariantRevision，固定来源 estimate、DecisionLog、旧 revision 和变更假设。
- [ ] `CHK-5186` 新方案有独立 release/exposure/evaluation，不修改全局约束、不自动发布模板、不自动开播。
- [ ] `CHK-5187` 指标变化、权利撤销、数据删除、漂移或在线失效使结果 review_required/revoked 并重新评估依赖决策。
- [ ] `CHK-5188` 建立效果驱动再生产 UI，展示保留/替换、预期影响、证据门槛、探索配额和回滚。

### 5.6 Phase 5 退出门禁

- [ ] `CHK-5290` 自动来源可在 watermark/backfill/退款/删除下稳定生成版本化标准数据和质量证据。
- [ ] `CHK-5291` 任一自动排序决策可还原候选、排除、点时特征、propensity、release、exposure 和结果。
- [ ] `CHK-5292` 离线 replay 证明无未来泄漏；缺 propensity/exposure 的数据不能进入因果训练。
- [ ] `CHK-5293` 只有满足 LearningPolicy 的批准结果影响软排序，硬约束和事实永远优先。
- [ ] `CHK-5294` 准实验结果具备假设、诊断和敏感性证据；不足结果正确降级。
- [ ] `CHK-5295` 漂移、撤销、数据删除和 kill switch 能停止依赖策略并触发影响任务。
- [ ] `CHK-5296` Phase 5 产品、工程、数据、安全和运营验收签字并归档验收包。

---

## Phase 6. 随机实验、RoleStrategy 与 RoleEvaluation

> 目标：用可信随机实验评价编剧、导演、影像、剪辑、场控和数据角色策略，并受控调整流量。
> 依赖：Phase 5 全部退出门禁完成。

### 6.1 Role 与 RoleStrategyRevision

- [ ] `CHK-6101` 定义 Role 的职责、输入/输出 schema、允许工具、权限、质量门禁和 owner。
- [ ] `CHK-6102` 实现 RoleStrategyRevision 的 prompt/规则/模型/代码、参数、成本、支持范围、状态和 fingerprint。
- [ ] `CHK-6103` 每个生产 artifact 强制记录实际 role/strategy revision；人工编辑使用 human_override 和操作者。
- [ ] `CHK-6104` 实现显式默认、人工指定或 ExperimentAssignment 三种选择路径并写 DecisionLog。
- [ ] `CHK-6105` 策略版本变化不改写旧 artifact、release 或评价。

### 6.2 Experiment 设计、分配与曝光对账

- [ ] `CHK-6120` 实现 Experiment/Revision 的 draft/design_review/ready/running/stopped/analyzing/concluded/rejected/aborted。
- [ ] `CHK-6121` 预注册 hypothesis、randomization unit、treatment/control、primary/guardrail metric、MDE、power/sample、window、exposure、exclusion、namespace、stopping 和 analysis。
- [ ] `CHK-6122` 在曝光前用稳定哈希或实验服务产生 Assignment，保存 propensity 和 assignment revision。
- [ ] `CHK-6123` 实际 treatment 以 ContentExposureEvent 为准，分配与曝光不一致进入质量门禁。
- [ ] `CHK-6124` 实现并发实验 namespace、互斥/正交规则、跨设备/跨会话污染和 interference 记录。
- [ ] `CHK-6125` 实现 A/A、SRM、guardrail、重复度量、退款延迟、多重比较和完整排除漏斗。
- [ ] `CHK-6126` 紧急护栏停止为 aborted 并保留原因，不包装为成功；禁止事后改主指标或样本范围。
- [ ] `CHK-6127` 建立 `/learning/experiments` 设计、审批、分配、对账、监控和分析 UI。

### 6.3 RoleEvaluation 与分阶段上线

- [ ] `CHK-6140` RoleEvaluation 绑定明确策略 exposure、metric revision、effect estimate 和 evidence tier。
- [ ] `CHK-6141` 分别报告质量、时延、成本、安全和业务效果，不把总 GMV 全归单一角色。
- [ ] `CHK-6142` 只有预注册随机实验或批准准实验可以自动扩大/收缩流量；描述结果只提出假设。
- [ ] `CHK-6143` 新策略按 offline -> shadow -> 人工建议 -> 小流量 -> 扩量 -> 常态推进。
- [ ] `CHK-6144` 每一级定义护栏、成本/探索预算、最小证据、回滚条件和 kill switch。
- [ ] `CHK-6145` 监控策略漂移、自我强化和多目标权衡，失败自动降级到最后批准 revision。

### 6.4 Phase 6 退出门禁

- [ ] `CHK-6290` 至少完成一次预注册实验的策略分配 -> 实际曝光 -> 因果估计 -> 受控策略变更。
- [ ] `CHK-6291` A/A、SRM、护栏、assignment/exposure mismatch 和紧急停止反例全部通过。
- [ ] `CHK-6292` 实验可从 revision、Assignment、DecisionLog、Exposure、Metric、Analysis 完整重放。
- [ ] `CHK-6293` RoleEvaluation 不产生错误的单角色总 GMV 归因，流量调整满足证据门槛。
- [ ] `CHK-6294` Phase 6 产品、工程、数据、安全和运营验收签字并归档验收包。

---

## Phase 7. 知识图谱、排播授权、治理与生产化运行

> 目标：补齐可重建知识/关系投影、排播模型、高风险能力评审及完整生产治理。
> 依赖：Phase 6 全部退出门禁完成。

### 7.1 知识库与关系事实源

- [ ] `CHK-7101` 建立 `/knowledge/facts`，管理 FactCard/FactClaim、字段来源、有效期、批准、冲突和使用记录。
- [ ] `CHK-7102` 建立内容知识、合规规则、术语、表达禁区和审核模块，不与目标商品事实混用。
- [ ] `CHK-7103` 建立 SourceEvidence 文档/网页/人工来源、抽取运行、checksum、引用区间和访问控制。
- [ ] `CHK-7104` 搜索命中必须回事实源校验批准、有效期、权利和适用范围，命中本身不是授权。
- [ ] `CHK-7105` 实现 knowledge search 和 fact lineage API，关系浏览可下钻剧本、Shot、载体、release、session 和 effect。

### 7.2 图谱与混合检索投影

- [ ] `CHK-7120` 先记录至少三个稳定业务查询、关系库基线耗时、本体稳定性、容量和完整重建结果。
- [ ] `CHK-7121` 未达到采用门槛时继续使用关系表/outbox；达到后通过 ADR 决定 Neo4j 是否成为正式投影依赖。
- [ ] `CHK-7122` 实现规划本体节点：素材/权利、事实/证据、模板、内容链、分支、载体、计划、release/exposure、metric/effect、strategy/experiment。
- [ ] `CHK-7123` 实现 DERIVED_FROM、CITES、USES_ASSET、PROJECTED_AS、EXECUTED_AS、RELEASED_AS、EXPOSED_DURING、MEASURED_BY、ESTIMATED_EFFECT_ON 等关系。
- [ ] `CHK-7124` 每条边保存来源主键/revision、有效时间、assertion kind、confidence 和 evidence；推断/相关性不显示为事实。
- [ ] `CHK-7125` 实现 GraphProjectionVersion、ontology/embedding version、watermark、full rebuild、增量对账和陈旧状态。
- [ ] `CHK-7126` 实现 lexical + vector + graph rerank，分开显示事实、历史结果、建议和推断。
- [ ] `CHK-7127` 召回后回事实源重验授权、状态、权利和硬约束；派生层禁止反写事实。
- [ ] `CHK-7128` 实现 graph entity API、projection rebuild API 和治理任务。
- [ ] `CHK-7129` 删除 Neo4j/Milvus 后从封存点重建相同版本，checksum、节点/边数和业务查询对账通过。

### 7.3 BroadcastSchedule

- [ ] `CHK-7140` 实现 BroadcastSchedule/Revision 和 draft/validated/approval_required/approved/active/rejected/canceled/completed。
- [ ] `CHK-7141` 固定目标账号/房间、ReleaseManifest、平台、时区、窗口、促销/库存依赖、冲突策略、owner 和停止条件。
- [ ] `CHK-7142` 验证 release 未撤销、权利渠道/地域/期限、目标空闲、凭据能力、库存/优惠、平台规则和并发冲突。
- [ ] `CHK-7143` 建立 `/operations/schedules` 列表、日历/时间窗、冲突、审批和授权状态 UI。
- [ ] `CHK-7144` capability 关闭时允许设计/验证计划，但不显示可误触开播命令，授权请求稳定返回策略拒绝。

### 7.4 GoLiveAuthorization 与高风险能力评审

- [ ] `CHK-7160` 实现 GoLiveAuthorization requested/approved/consumed/rejected/expired/revoked 的独立 capability。
- [ ] `CHK-7161` 授权绑定主体、目标、release hash、现场 fingerprint、时间窗、策略版本、nonce 和 single use。
- [ ] `CHK-7162` 强制生产者/批准者分离，高风险账号启用双人复核和最小权限凭据。
- [ ] `CHK-7163` 实现提交前 release/权利/库存/优惠/现场/时间窗/授权/保护注册表的重新检查。
- [ ] `CHK-7164` 实现紧急停止、授权撤销、账号隔离、现场 readback、未知结果 reconcile 和审计通知。
- [ ] `CHK-7165` 在隔离账号/房间完成错误 release、错时间窗、现场变化、授权服务中断、网络超时和紧急停止演练。
- [ ] `CHK-7166` 完成独立安全评审、平台条款审阅、运营 runbook 和应急值守批准。
- [ ] `CHK-7167` 只有 `CHK-7160` 至 `CHK-7166` 全部完成后，才允许通过受审 ADR 打开生产 go_live feature flag。
- [ ] `CHK-7168` 若业务决定继续关闭生产开播，记录 capability 关闭决策；契约、sandbox、拒绝路径和演练仍必须完成，不能删项。

### 7.5 治理与任务中心

- [ ] `CHK-7180` 建立 `/governance/runs`，按 run/step/task/owner/status/cost/queue 查看和深链。
- [ ] `CHK-7181` 建立发布审批、策略/实验、指标目录、数据质量、权利到期、保留删除和 projection rebuild 待办。
- [ ] `CHK-7182` 提供长任务排队原因、当前 step、重试、timeout、等待人工、取消和 reconcile 结果。
- [ ] `CHK-7183` 高风险批量操作显示影响数量、阻断项和 sample diff，并进入 WorkflowRun。
- [ ] `CHK-7184` 所有 approve/reject/waive 显示固定 revision 和影响，要求结构化理由且防重复副作用。
- [ ] `CHK-7185` 通知深链到实体 revision/证据；warning、stale、insufficient_data、reconcile_required 保持独立视觉语义。

### 7.6 隐私、删除、权利与供应链治理

- [ ] `CHK-7200` 实现 DeletionRun requested/validating/legal_hold/approved/executing/verifying/completed/partial_failed。
- [ ] `CHK-7201` 删除传播到对象存储、事件层、特征、向量、图谱和可删除派生；每个处理器回写结果或保留依据。
- [ ] `CHK-7202` legal hold 具备 owner、范围、证据、到期和解除，不作为永久保留默认值。
- [ ] `CHK-7203` 权利到期/撤销传播到 Rendition、模板、release、schedule 和后续决策，阻止新交付。
- [ ] `CHK-7204` 建立访问、导出、解密、批量查询、模型发送和删除审计报表。
- [ ] `CHK-7205` 生成 SLSA 风格构建 provenance，固定镜像/依赖/工具来源和构建环境。
- [ ] `CHK-7206` 为证据类定义 owner、访问、保留、legal hold 和销毁证明；UI 分开显示完整性验证和业务批准。

### 7.7 容量、SLO、成本与灾备

- [ ] `CHK-7220` 更新当前值、12 个月预测、峰值系数和单元成本容量模型。
- [ ] `CHK-7221` 在目标峰值 2 倍压测 API、队列、数据库、对象存储、采集、渲染和外部 adapter。
- [ ] `CHK-7222` 验证录屏、事件、Browser-use 和渲染 backpressure 及账号/房间串行限制。
- [ ] `CHK-7223` 落实元数据 API 99.9% 月可用性和 p95 500ms 初始目标；搜索/重查询单列 SLO。
- [ ] `CHK-7224` 落实任务不丢、排队原因、release/授权证据完整率 100%、摄取新鲜度、归因时延和 projection lag SLI。
- [ ] `CHK-7225` 为删除、权利撤销和紧急停用设完成时限、升级和 error budget。
- [ ] `CHK-7226` 每个 WorkflowRun 记录模型、ASR/OCR、渲染、存储/出口、图和 Browser-use 成本。
- [ ] `CHK-7227` 实现项目/团队/adapter 预算、并发配额、cost approval 和 kill switch。
- [ ] `CHK-7228` 实现只降级非必要分析、预览、图谱和离线学习，永不跳过事实/权利/授权/质量/release 门禁。
- [ ] `CHK-7229` 分离关键生产和派生分析队列，避免批处理挤占草稿写入、撤销和删除。
- [ ] `CHK-7230` 落实 PostgreSQL PITR，验证 RPO <= 5 分钟、RTO <= 4 小时或由 owner 批准的新目标。
- [ ] `CHK-7231` 对象存储版本/复制、凭据/签名密钥备份轮换、投影重建和关键 release 导出均通过演练。
- [ ] `CHK-7232` 每季度恢复演练、每半年第三方故障/错误 release/大规模删除演练进入治理日历。

### 7.8 路由迁移与完整产品体验

- [ ] `CHK-7240` 完成 `/assets/library`、分组、素材包、同步、效果关系和知识跳转。
- [ ] `CHK-7241` 完成 `/research/live-sources` 的来源、场次、清洗、草稿和已发布模板。
- [ ] `CHK-7242` 完成 `/content/projects` 的目标事实、模板、StoryBrief/剧本、节目/Shot、分支和 lineage。
- [ ] `CHK-7243` 完成 `/production/live-rooms`、`/production/videos` 和 `/production/releases`。
- [ ] `CHK-7244` 完成 `/operations/live-sessions`、attribution、schedules 和 `/learning/effects/experiments`。
- [ ] `CHK-7245` 完成 governance runs/metrics/tasks 和知识库一级工作区。
- [ ] `CHK-7246` 首页进入“我的任务/异常”；全局搜索、保存筛选、批量选择、通知和实体深链可跨域工作。
- [ ] `CHK-7247` 完成桌面与移动视口的文字溢出、遮挡、键盘、焦点、对比度和无障碍检查。
- [ ] `CHK-7248` 新路由功能等价和深链审计通过后重定向旧入口；旧运行保留只读，未达条件的兼容入口不删除。

### 7.9 Phase 7 退出门禁

- [ ] `CHK-7290` 知识搜索、lineage、影响分析和缺口候选查询均回事实源校验，推断不冒充事实。
- [ ] `CHK-7291` 图/向量投影可从封存点完整重建；投影落后不覆盖事实源且 UI 显示水位。
- [ ] `CHK-7292` 排播验证覆盖 release、权利、资源、库存/优惠、平台规则和冲突。
- [ ] `CHK-7293` go_live 在完成独立安全评审前全路径失败关闭；启用后也只能消费短期目标绑定授权。
- [ ] `CHK-7294` 原始个人数据删除、legal hold、权利撤销和 release revoke 的跨存储传播均有完整证据。
- [ ] `CHK-7295` 2 倍峰值压测、SLO、cost quota、kill switch、PITR、对象恢复和投影重建全部达到批准目标。
- [ ] `CHK-7296` 全部稳定路由与跨工作区旅程通过运营验收，旧入口迁移无断链。
- [ ] `CHK-7297` Phase 7 产品、工程、数据、安全、设计和运营验收签字并归档验收包。

---

## Phase 8. 全系统测试、反思与最终验收

> 目标：在逐 Phase 测试之外，额外从完整业务闭环、反例、故障、可复现性和设计假设角度验证系统，并把发现反馈到代码和规划。
> 依赖：Phase 7 全部退出门禁完成；本 Phase 不是补写测试的替代品。

### 8.1 需求追踪与测试资产审计

- [ ] `CHK-8101` 建立“设计章节 -> checklist ID -> 代码模块 -> migration -> API -> UI -> 测试 -> 证据”双向追踪矩阵。
- [ ] `CHK-8102` 逐条映射权威设计第 19 节全部验收场景，不允许用一个 happy-path E2E 代替多个不变量。
- [ ] `CHK-8103` 逐条映射最终目标五个核心子系统、六个角色和短/中/长期成功标准。
- [ ] `CHK-8104` 扫描未被测试覆盖的路由、状态转移、规则码、worker operation、queue handler 和 migration。
- [ ] `CHK-8105` 删除或说明跳过、xfail、flaky quarantine 和无断言测试；每个保留项有 owner、期限和风险。
- [ ] `CHK-8106` 固定测试数据工厂、时钟、随机 seed、provider fake、媒体 fixture 和敏感数据禁入规则。

### 8.2 静态、单元、属性与契约测试

- [ ] `CHK-8120` 后端、worker 完成格式、lint、类型、依赖和 secret scan；前端完成 typecheck、lint 和 build。
- [ ] `CHK-8121` 所有领域状态机完成合法/非法转移单元和属性测试。
- [ ] `CHK-8122` revision 不可变、fingerprint、stale 传播、idempotency 和 expected revision 完成并发属性测试。
- [ ] `CHK-8123` 约束合并、pack 解析、排他、solver status 和选材优先级完成组合/属性测试。
- [ ] `CHK-8124` 事实引用、模板去事实、权利范围、EffectEligibility 和证据等级完成反例测试。
- [ ] `CHK-8125` 时间线 RationalTime、TimeMapping、event-time/window/refund/backfill 完成边界和时区属性测试。
- [ ] `CHK-8126` OpenAPI、队列消息、artifact schema、provider adapter、DataContract 和 OpenLineage consumer contract 全绿。
- [ ] `CHK-8127` 对未知必需字段、旧可选字段、schema 升降级和弃用窗口执行兼容测试。

### 8.3 数据库迁移与数据质量测试

- [ ] `CHK-8140` 从空库顺序应用全部 migrations，schema 与测试期望一致。
- [ ] `CHK-8141` 从生产数据脱敏副本升级，验证耗时、锁、索引、磁盘、失败恢复和前向修复。
- [ ] `CHK-8142` 验证 legacy 投影不伪造 StoryBrief、Shot、ReleaseManifest 或 Exposure。
- [ ] `CHK-8143` 验证 outbox 事务原子性、重复消费、乱序、死信、重放和 full rebuild。
- [ ] `CHK-8144` 验证删除 tombstone、权利撤销、release revoke、stale 和 supersede 不留下可误用孤儿引用。
- [ ] `CHK-8145` 执行主外键、唯一性、revision 连续性、checksum、时间区间和状态不变量巡检。

### 8.4 服务与 Worker 集成测试

- [ ] `CHK-8160` 用真实 PostgreSQL/MinIO 和本地 provider fake 运行 API -> queue -> worker -> artifact -> readback 集成测试。
- [ ] `CHK-8161` Browser-use 在隔离麦兔草稿完成 preflight、write、checkpoint、readback、reconcile、finalize。
- [ ] `CHK-8162` 注入登录失效、错房间、非空、已开播、现场变化、素材失效、网络超时和 authoritative API 不可用。
- [ ] `CHK-8163` 直播研究测试掉帧、断流、时钟漂移、sidecar 崩溃、重复事件、retention 和 resume。
- [ ] `CHK-8164` 视频 worker 测试 TTS、字幕、FFmpeg、QC、阶段重试、坏媒体、无声、黑帧和 checksum mismatch。
- [ ] `CHK-8165` 数据链测试 ingest、watermark、late/backfill、退款、删除、封存、attribution 和 estimate revoke。
- [ ] `CHK-8166` 外部 provider 测试超时、429、5xx、坏 schema、部分响应、数据泄漏防护、成本限制和 fallback。
- [ ] `CHK-8167` 验证所有未知外部副作用先 reconcile，任何 retry 都不会复制现场对象或交付。

### 8.5 前端与完整业务旅程 E2E

- [ ] `CHK-8180` E2E 覆盖素材同步 -> 权利/约束 -> 分组/素材包 -> resolve -> gap。
- [ ] `CHK-8181` E2E 覆盖抖音来源 -> CaptureSession -> 多模态时间线 -> 清洗 -> 模板审核发布。
- [ ] `CHK-8182` E2E 覆盖目标/事实/模板 -> StoryBrief -> Script -> ProgramSegment -> ShotList。
- [ ] `CHK-8183` E2E 覆盖 live_room variant -> snapshot -> Blueprint -> BuildPlan -> authorization -> draft -> release/readback。
- [ ] `CHK-8184` E2E 覆盖 rendered_video variant -> timeline -> voice/subtitle -> render/QC -> release/delivery。
- [ ] `CHK-8185` E2E 覆盖 LiveSession -> Exposure -> ingest -> attribution -> effect approval -> re-production。
- [ ] `CHK-8186` E2E 覆盖 Experiment Assignment -> Exposure reconciliation -> Analysis -> RoleEvaluation -> rollout/rollback。
- [ ] `CHK-8187` E2E 覆盖 rights revoke、release revoke、DeletionRun、projection rebuild、schedule conflict 和授权撤销。
- [ ] `CHK-8188` 验证刷新、重复点击、多标签、返回/前进、深链、并发编辑、离线恢复不会重复副作用或丢 revision。
- [ ] `CHK-8189` 在桌面和移动视口截图审查 loading/empty/error/warning/stale/partial/unauthorized；无文字遮挡、溢出或不可达控件。
- [ ] `CHK-8190` 验证键盘操作、焦点、语义标签、对比度、读屏名称和错误提示达到批准的无障碍基线。

### 8.6 安全、隐私与滥用测试

- [ ] `CHK-8200` 对 generation goal、ASR/OCR、模板例句、网页和 tool result 做提示注入与数据投毒测试。
- [ ] `CHK-8201` 对 IDOR、越权、跨 capability、token 重放、授权换目标/hash、过期和 clock skew 做安全测试。
- [ ] `CHK-8202` 证明模型无平台长期凭据、无任意网络/Browser-use 调用能力、无任意 selector/URL/operation 输出通道。
- [ ] `CHK-8203` 对日志、trace、截图、artifact、向量、图谱、导出和错误响应执行 cookie/token/个人信息泄漏扫描。
- [ ] `CHK-8204` 对素材、肖像、声音、AI 分析、衍生、渠道、地域、期限和撤销执行 rights matrix 测试。
- [ ] `CHK-8205` 对模板连续文本相似、品牌/主播模仿、版权画面和个人敏感信息执行红队测试。
- [ ] `CHK-8206` 对 ProtectedResourceRegistry、只读参考房间、禁写目标和 go_live kill switch 做独立绕过测试。
- [ ] `CHK-8207` 验证 DeletionRun 跨主库、对象存储、事件、feature、Milvus、Neo4j、缓存和备份政策传播。
- [ ] `CHK-8208` 完成第三方渗透/安全评审或内部独立复核，所有高危问题关闭后才继续最终验收。

### 8.7 性能、韧性、灾备与可复现性

- [ ] `CHK-8220` 按目标峰值 2 倍执行 API、数据库、对象存储、queue、采集、渲染、Browser-use 和投影压测。
- [ ] `CHK-8221` 验证 backpressure、priority、quota、budget、kill switch 和关键/派生队列隔离。
- [ ] `CHK-8222` 注入数据库主连接中断、对象存储故障、worker 大量崩溃、provider outage、授权服务故障和图投影损坏。
- [ ] `CHK-8223` 验证 error budget 规则能暂停扩量/高风险自动化，而不跳过安全门禁。
- [ ] `CHK-8224` 在干净机器按 reproducibility 文档启动基础设施、迁移、服务、worker 和前端。
- [ ] `CHK-8225` 用固定 RunManifest 重放内容、BuildPlan、timeline、render、attribution 和 graph projection，解释非字节级差异。
- [ ] `CHK-8226` 执行 PITR、对象版本恢复、outbox replay、projection rebuild、关键 release 导出和签名校验。
- [ ] `CHK-8227` 验证实际 RPO/RTO、恢复后业务不变量、checksum、行数和 release 可交付性，不以“服务启动”作为成功。

### 8.8 运营 UAT 与验收场景复核

- [ ] `CHK-8240` 由非研发运营人员完成素材分组、约束、素材包、选材解释和 gap 闭环。
- [ ] `CHK-8241` 完成多场录屏模板清洗、去事实、发布和主次贡献选择。
- [ ] `CHK-8242` 完成无房间内容确认、live_room 载体确认、草稿写入、clone 新房间和旧证据查看。
- [ ] `CHK-8243` 完成同内容成片、timeline 调整、QC 下钻、release 审批和 delivery readback。
- [ ] `CHK-8244` 完成 exposure 校正、metric/contract 查看、归因下钻、effect 审批和再生产。
- [ ] `CHK-8245` 完成 HumanTask、异常处理、reconcile、权利撤销、删除、projection rebuild 和 schedule 冲突处理。
- [ ] `CHK-8246` 运营人员能准确解释 workflow、release、delivery、exposure、correlation 和 causation 的区别。
- [ ] `CHK-8247` 收集任务完成率、耗时、误操作、求助点和认知错误，关闭阻断性体验问题。

### 8.9 测试反思与设计复盘

- [ ] `CHK-8260` 汇总所有失败用例，区分需求遗漏、设计错误、实现错误、测试错误、环境问题和外部平台变化。
- [ ] `CHK-8261` 复盘哪些 bug 被单元、契约、集成、E2E、UAT 或生产演练发现，找出本应更早发现的缺口。
- [ ] `CHK-8262` 复盘每个 mock/fake 是否忠实模拟外部失败；对过度宽松 mock 补契约或 sandbox 测试。
- [ ] `CHK-8263` 复盘状态机、revision、fingerprint、lineage 和 evidence 是否降低了排障成本；无法回答的问题补可观测性。
- [ ] `CHK-8264` 复盘是否存在“workflow succeeded 当作交付/曝光”“相关性当因果”“检索命中当批准事实”等语义回退。
- [ ] `CHK-8265` 复盘自动化是否出现自动化偏见、反馈回路、自我强化、样本选择偏差或新素材冷启动惩罚。
- [ ] `CHK-8266` 复盘权利、隐私、保留、授权和成本门禁是否存在业务绕过压力，并补技术约束而非只写流程提醒。
- [ ] `CHK-8267` 复盘 SLO 和容量目标是否来自实测；修正虚高、虚低或没有用户价值的指标。
- [ ] `CHK-8268` 对每个设计假设记录 `validated / falsified / still uncertain`、证据、影响和下一步实验。
- [ ] `CHK-8269` 对引入的 OR-Tools、Temporal、Neo4j、Feature Store、C2PA 等组件逐项复核采用门槛、真实收益、运维成本和退出能力。
- [ ] `CHK-8270` 召开跨 product/engineering/data/security/design/operations 复盘，形成 owner 和期限明确的改进项。
- [ ] `CHK-8271` 将证实的设计偏差回写权威设计、ADR、API schema、runbook 和本 checklist，保持文档与实现一致。
- [ ] `CHK-8272` 所有 P0/P1 缺陷关闭；接受的其他缺陷有风险、owner、到期和不影响最终定义的批准依据。

### 8.10 最终完成审计

- [ ] `CHK-8290` 权威设计第 29 节 11 个最终目标领域逐项有代码、UI/API、测试和验收证据。
- [ ] `CHK-8291` 权威设计第 30 节 10 条完成定义逐项演示通过并归档录像/manifest/报告。
- [ ] `CHK-8292` 本清单不存在未勾选项、无证据勾选项、过期 waiver、无人负责风险或无下线条件兼容接口。
- [ ] `CHK-8293` 发布生产 runbook、支持边界、on-call、告警、应急停止、恢复、删除和权利撤销手册。
- [ ] `CHK-8294` 发布最终 schema/API/事件/状态机/领域词汇/数据字典和用户操作文档。
- [ ] `CHK-8295` 执行最终 secret、license、dependency、provenance、数据保留和外部依赖审计。
- [ ] `CHK-8296` Product、Engineering、Data、Security、Design、Operations 最终负责人联合签字。
- [ ] `CHK-8297` 将本文件状态改为“全部完成”，记录最终 release、commit、验收包和签字日期。

---

## 附录 A. 每阶段固定交付物

- [ ] `CHK-A001` 该阶段 ADR 与领域/schema 变更记录。
- [ ] `CHK-A002` 追加 migration、数据回填/兼容报告和前向修复方案。
- [ ] `CHK-A003` OpenAPI、事件/队列 schema、错误码和 consumer contract。
- [ ] `CHK-A004` UI 深链、状态、权限、审计和可访问性验收。
- [ ] `CHK-A005` RunManifest、ArtifactRef、lineage、trace、指标、日志和告警。
- [ ] `CHK-A006` 单元、属性、契约、集成、E2E、性能和安全测试报告。
- [ ] `CHK-A007` 外部依赖、容量、SLO、成本、配额、降级和 kill switch 记录。
- [ ] `CHK-A008` 备份/恢复、回滚/reconcile、删除和权利撤销演练证据。
- [ ] `CHK-A009` 产品、数据、安全、设计和运营验收记录。
- [ ] `CHK-A010` 已知限制、未决问题、风险、owner、期限和下一阶段依赖。

## 附录 B. 执行日志

> 实施时按 `check_id` 追加记录，或填写指向项目管理系统中不可变记录的链接。不得只改 checkbox 而不保留证据。

| check_id | owner | evidence | approved_by | completed_at |
| --- | --- | --- | --- | --- |
| `CHK-0001` | coderdailyone | `docs/architecture/phase-0-baseline.md` | N/A: process ownership | 2026-07-23 |
| `CHK-0002` preparation (item remains open) | coderdailyone | reject-by-default `docs/operations/phase-owner-register.v1.example.json`; `scripts/assemble_phase0_acceptance.py` validates exact Phase 0-8 coverage and required product/engineering/data/security/design owner plus appointment reference for every Phase | N/A: no actual owner identities or appointment decisions are available; example nulls are tested non-approvable and checkbox remains open | 2026-07-23 |
| `CHK-0003`-`CHK-0010` | coderdailyone | 本文件 0.1 规则及本日志；未跨越 Phase 0 门禁 | N/A: process controls | 2026-07-23 |
| `CHK-0011` | coderdailyone | `docs/operations/phase-delivery-readiness-program.md`; Phase 0-8 dependency graph; 2-6 week acceptance slices; per-phase risks and capacity/cost kickoff schema; unknown future budgets fixed as blocking `blocked_unbudgeted`, with no fabricated dates, staffing, traffic or cost figures | N/A: planning control established; each phase's numeric budget and owners still require kickoff approval | 2026-07-23 |
| `CHK-0012`,`CHK-0296` preparation (items remain open) | coderdailyone | `scripts/assemble_phase0_acceptance.py`; `docs/operations/phase-0-acceptance-package.md`; reject-by-default five-party signoff example; fingerprinted full regression and preparation package; package binds checklist, owners, qualified capacity/production-copy migration/compatibility/DR reports and evidence file hashes before product/engineering/data/security/operations decisions; regression 643 backend + 385 browser + 30 research + 32 frontend tests, TypeScript, three builds, four Ruff checks, new-file format check, reproducibility and diff checks passed; package correctly reports `qualifies_for_chk_0296=false` | N/A: owner register, `CHK-0110`, `CHK-0260` and real five-party decisions are absent; examples cannot sign and both checkboxes remain open | 2026-07-23 |
| `CHK-0101`-`CHK-0108` | coderdailyone | `docs/architecture/phase-0-baseline.md`; `docs/adr/0001-closed-loop-domain-invariants.md` | N/A: architecture baseline | 2026-07-23 |
| `CHK-0110` preparation (item remains open) | coderdailyone | read-only `scripts/measure_capacity_baseline.py`; versioned reject-by-default `docs/operations/capacity-baseline-input.v1.example.json`; exact UTC/half-open queries for assets, daily recording hours, event/processing peaks, live/render concurrency, artifact growth, workflows and Browser-use leases; optional full ArtifactRef/object-store reconciliation; fingerprinted `phase-0-capacity-baseline-integration-2026-07-23.json` and four regression tests passed; integration classification is hard-coded `qualifies_for_chk_0110=false` | N/A: operational read-only snapshot/source reference, object-store reconciliation, approved concurrency/forecast/cost/threshold input and engineering/data/operations decisions are unavailable; checkbox remains open | 2026-07-23 |
| `CHK-0111`-`CHK-0112` | coderdailyone | `docs/operations/external-platform-register.md`; 未决区域/费用明确标记 pending | N/A: register only; production approval remains open | 2026-07-23 |
| `CHK-0113` | coderdailyone | migrations `043`-`044`; `docs/architecture/provider-adapter-boundary.md`; `docs/evidence/phase-0-provider-neutral-producers-validation-2026-07-23.md`; provider-neutral domain/OpenAPI contracts, governed processor authorization, pre-serialization redaction, confidential content-addressed invocation evidence, legacy-only supplier columns, and evidence-before-success worker protocol; clean `001`-`044` database migration; backend 625 passed, live-research worker 30 passed, frontend 32 passed, Ruff/typecheck and three Vite builds; runtime health/Console 200 and producer OpenAPI supplier-field scan empty; known limits: real processor regions, terms, credentials, evidence storage and production data/security approval remain deployment gates | N/A: automated technical evidence; production processor approvals explicitly remain open | 2026-07-23 |
| `CHK-0114` | coderdailyone | `app/services/maitu_authority.py`; strict MockTransport failure contract; 42 tests passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0120`,`CHK-0127`-`CHK-0129` | coderdailyone | migrations `027`; `app/repositories/content_core.py`; clean-DB tests 34 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0121`-`CHK-0126` | coderdailyone | migrations `027`,`034`; `app/repositories/content_production.py`; explicit block/shot sources, branch isolation and legacy Workbench/Video mappings; clean `001`-`034` batch 17 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0109`,`CHK-0130`,`CHK-0202`,`CHK-0290` | coderdailyone | audited transition framework; Hypothesis state/revision properties; transaction tests; 8 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0140`-`CHK-0146` | coderdailyone | migrations `028`; artifact/manifest/outbox/lineage services; clean-DB tests 34 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0147`,`CHK-0293` | coderdailyone | OpenTelemetry FastAPI/HTTPX; Workflow trace claim; provider/authority propagation; trace batch 46 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0148`-`CHK-0149` | coderdailyone | migration `035`; signed Run/Release manifests; authorization/effect hash chains; integrity alert/check/consumption ledger; regression 19 passed and migration-DB 7 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0160`-`CHK-0163`,`CHK-0165`,`CHK-0168` | coderdailyone | migration `028`; control-plane API/repository; route and PostgreSQL tests | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0164`,`CHK-0166`,`CHK-0169`,`CHK-0292` | coderdailyone | migration `033`; external Effect protocol; HumanTask SLA/timeout/cancel races; 12 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0167` | coderdailyone | migration `036`; read-only run/step views, compatibility repository/API; Workbench/Video/Capture/Analysis/Retry mapping tests; no fabricated WorkflowRun rows | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0170` | coderdailyone | `docs/adr/0002-defer-temporal-until-measured-thresholds.md`; measured validation complexity and explicit re-evaluation thresholds | N/A: infrastructure adoption decision; operations Phase exit approval remains open | 2026-07-23 |
| `CHK-0181`-`CHK-0185`,`CHK-0187`-`CHK-0188`,`CHK-0291` | coderdailyone | migrations `029`-`030`; policy/authorization services; attack-path tests | N/A: automated technical evidence; security sign-off remains open | 2026-07-23 |
| `CHK-0184` transaction hardening | coderdailyone | commit authorization and external Effect transition share one transaction; conflict rollback/policy-revision/single-use security batch 9 passed | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0180`,`CHK-0186` | coderdailyone | migration `037`; `docs/security/capability-matrix.md`; versioned ProtectedResource API/events; system-locked reference rooms; independent Preflight/PDP/Worker guards; main batch 46 passed and migration-DB batch 13 passed | N/A: automated technical evidence; independent security sign-off remains open | 2026-07-23 |
| `CHK-0200`-`CHK-0201`,`CHK-0203`-`CHK-0206` | coderdailyone | migration `029`; release service/repository; release/delivery/exposure tests | N/A: automated technical evidence | 2026-07-23 |
| `CHK-0220`-`CHK-0225`,`CHK-0240` | coderdailyone | migrations `029`,`031`,`032`; data-governance service; JSON Schema and catalog tests | N/A: automated technical evidence; data sign-off remains open | 2026-07-23 |
| `CHK-0241` | coderdailyone | migration `038`; purpose-bound access policy/service; append-only allow/deny decisions; all six governed actions and anti-role-composition tests; focused batch 6 passed | N/A: automated technical evidence; data/security sign-off remains open | 2026-07-23 |
| `CHK-0242` | coderdailyone | migration `038`; versioned field-redaction policy; recursive log/screenshot/prompt/model-response redactor; ProviderRouter pre-send/pre-return integration and evidence counts; focused batch 8 passed | N/A: automated technical evidence; privacy/security sign-off remains open | 2026-07-23 |
| `CHK-0243` | coderdailyone | migration `038`; six active versioned retention classes; policy-driven fixed/ranged/indefinite resolution and expiry tests; focused governance batch 6 passed | N/A: automated technical evidence; data/privacy sign-off remains open | 2026-07-23 |
| `CHK-0244` | coderdailyone | migrations `038`,`039`; audited DeletionRun state machine; expiring legal hold/release history; requester/approver separation; tombstones; per-target append-only receipt attempts; partial-failure retry/backoff/escalation; validation-DB governance batch 12 passed | N/A: automated technical evidence; privacy/operations sign-off remains open | 2026-07-23 |
| `CHK-0245` | coderdailyone | migration `038`; versioned external-processor terms and append-only call audits; exact minimum-field projection; ProviderRouter mandatory guard; secret-reference-only credential registry with due/rotate/revoke history; main governance batch 15 passed and validation-DB batch 7 passed | N/A: automated technical evidence; production processor approvals remain open | 2026-07-23 |
| `CHK-0261` | coderdailyone | migration `040`; read-only `legacy_asset_observations_v1`; geometry/duplicate semantics flags and mutation rejection; main and independent validation DB compatibility batches each 6 passed | N/A: automated compatibility evidence | 2026-07-23 |
| `CHK-0262` | coderdailyone | migrations `036`,`040`; read-only ContentProject/live-room variant/WorkflowRun/StepRun/delivery-unknown projections and API; explicit missing provenance; zero writes to canonical project/variant/delivery tables; main and validation DB batches each 6 passed | N/A: automated compatibility evidence | 2026-07-23 |
| `CHK-0263` | coderdailyone | migration `040`; `layout-hypothesis.v1`-only read projection fixed to approximate/reference-only/non-convertible; mutation rejection and source contract preservation; main and validation DB batches each 6 passed | N/A: automated compatibility evidence | 2026-07-23 |
| `CHK-0268` | coderdailyone | `docs/architecture/stable-error-contract.md`; global backward-compatible problem envelope; Console parser/presentation; state-semantics tests; clean 40-migration DB backend 598 passed and frontend 22 passed | N/A: automated API/UI contract evidence | 2026-07-23 |
| `CHK-0264` | coderdailyone | `/console/` plus stable SPA routes; memory-only bearer validation; authenticated search/tasks/notifications API; shared navigation and error boundary; backend 603 passed, frontend 27 passed, three Vite builds and desktop/mobile Playwright screenshots | N/A: automated API/UI/accessibility evidence | 2026-07-23 |
| `CHK-0265` | coderdailyone | Working tree (migration N/A: read-only surface); typed `/api/console/entities/{entity_type}/{entity_code}` for asset/content project/template/workflow run/release; canonical query deep links, revision timeline, selected structured diff, verified source/used-by relations; backend 606 passed, frontend 28 passed, three Vite builds; `docs/evidence/screenshots/phase0-console-entity-{desktop,mobile}.png`; known limit: browser requests an absent favicon only | N/A: automated API/UI/accessibility evidence; product approval remains open | 2026-07-23 |
| `CHK-0266` | coderdailyone | migrations `041`-`042`; optimistic shared drafts with append-only events, conflict/rebase protection and sensitive-field rejection; revision-bound idempotent confirm/publish/approve/reject/authorize commands and non-secret receipts; authorization derives scope from one approved HumanTask and exposes its token once; clean `001`-`042` database backend 614 passed, frontend 31 passed, typecheck and three Vite builds; `docs/evidence/screenshots/phase0-console-{draft,command}-{desktop,mobile}.png`; known limits: expired/lost raw authorization tokens require a newly approved task, and the absent favicon still returns 404 | N/A: automated API/UI/security evidence; product/security approval remains open | 2026-07-23 |
| `CHK-0267` | coderdailyone | exact browser-entry `308` redirects from `/maitu[/]` and `/live-research[/]` to stable Console routes; default/resources/Gemini/watch/sessions/drafts/published mappings preserve repeated and immutable-pin deep-link parameters; shared page components prove functional equivalence; production handoff and shared navigation now use stable URLs; `docs/operations/legacy-frontend-retirement-checklist.md`; backend 616 passed, frontend 32 passed, typecheck and three Vite builds; `docs/evidence/screenshots/phase0-console-legacy-redirect-{desktop,mobile}.png`; legacy API prefixes unchanged and static assets retained pending measured zero-use/approval gates | N/A: automated route/UI evidence; product/design/security retirement approval remains open | 2026-07-23 |
| `CHK-0260` preparation (item remains open) | coderdailyone | forward-only migration runner with per-migration receipts, advisory lock, lock/statement timeouts and checksum immutability; `scripts/rehearse_migrations.py`; versioned invariant contract and runbook; lock-timeout/concurrent-runner/retry/checksum tests; `phase-0-migration-rehearsal-synthetic-2026-07-23.json` passed but is hard-coded `qualifies_for_chk_0260=false` | N/A: tooling only; a traceable isolated production data copy, snapshot/sanitization evidence, measured locks/duration/growth and owner acceptance are still required before checkbox update | 2026-07-23 |
| `CHK-0294` | coderdailyone | `scripts/audit_legacy_compatibility.py`; `docs/operations/legacy-compatibility-audit.md`; fingerprinted `docs/evidence/phase-0-legacy-compatibility-audit-2026-07-23.json`; migrations `036`/`040` checksums and 7/7 read-only view guards passed; six legacy workflow source and step cardinalities matched; five domain projection types had representative coverage; eight uncertainty/non-fabrication assertions passed; authenticated paginated API plus all six detail types and stable 404 passed; six canonical fact-table counts unchanged; focused compatibility/audit batch 9 passed and reproducibility validation clean | N/A: representative integration compatibility evidence; explicitly not a production volume/data-quality or `CHK-0260` migration claim | 2026-07-23 |
| `CHK-0295` | coderdailyone | `scripts/rehearse_disaster_recovery.py`; `docs/operations/disaster-recovery-baseline-runbook.md`; `docs/evidence/phase-0-disaster-recovery-validation-2026-07-23.md`; successful fingerprinted report `phase-0-disaster-recovery-baseline-2026-07-23-attempt-4.json`; PostgreSQL 14 checksummed cluster with continuous WAL archive, verified 62,935,669-byte base backup, time-target recovery and promotion; DB RPO 1 ms/RTO 820 ms; versioned MinIO overwrite/delete/original-version restore with 0-byte RPO and 842 ms RTO; composite RTO 842 ms; 44 migration receipts, 12 business invariants, marker exclusion, `pg_verifybackup`, `pg_amcheck`, offline page checksums and ArtifactRef/object checksum all passed; three failed attempts retained and asserted non-qualifying; backend 632 passed and Ruff clean | N/A: automated local recovery baseline; production-scale topology and `CHK-7230` targets explicitly not claimed | 2026-07-23 |
| Phase 0 foundation batch | coderdailyone | `docs/evidence/phase-0-foundation-validation-2026-07-23.md`; migrations `001`-`032` clean apply; 34 passed | N/A: Phase exit approval not claimed | 2026-07-23 |
| `CHK-1101`-`CHK-1105`,`CHK-1141` preparation (items remain open) | coderdailyone | commit `12f2abd`; revision-required content-project PATCH and explicit confirm endpoint; full target document fields; approved FactCard version pinning with confirmation/generation revalidation of approval, validity and platform scope; target-and-facts Console surface; `docs/operations/phase-0-external-input-register.md`; isolated PostgreSQL tests `5 passed`, Ruff, Console TypeScript and build passed | N/A: this is a Phase 1 spike permitted by `CHK-0004`; Phase 0 `CHK-0110`, `CHK-0260`, `CHK-0296` are still open, DesignBrief artifact/provider/audit requirements and full target-and-fact conflict UX remain incomplete, so no Phase 1 checkbox is checked | 2026-07-24 |
| `CHK-1120`-`CHK-1125`,`CHK-1140`,`CHK-1141` preparation (items remain open) | coderdailyone | commits `7be69c8`, `207c4e8`; migration `051`; bounded deterministic DesignBrief parser, raw-input retention, parsed projection, at most three recommended open questions, explicit DesignBrief confirmation and Console view; generation rejects unconfirmed ContentProject or DesignBrief and records the confirmed DesignBrief code/revision/fingerprint in StoryBrief; isolated PostgreSQL tests `7 passed`, Ruff, Console TypeScript and build passed | N/A: local deterministic parsing is deliberately not a provider call and raw response is not persisted as an ArtifactRef; structured editing/diff, external provider authorization and production audit evidence remain incomplete. This remains a Phase 1 spike until Phase 0 exits. | 2026-07-24 |
| `CHK-1142`-`CHK-1145` preparation (items remain open) | coderdailyone | commit `1163ea7`; generation context is serialized as separate system baseline, approved facts, user goal and external-reference sections with a fingerprint; restricted price/promotion/inventory/gift/efficacy markers require a citation to an approved pinned fact; focused content tests `6 passed`, Ruff passed | N/A: the deterministic generator currently emits only constrained baseline copy; per-sentence character spans, provider output artifact and full FactCitation review UI are still absent. No production completion is claimed. | 2026-07-24 |
| `CHK-1142`-`CHK-1145`,`CHK-1160`-`CHK-1166` preparation (items remain open) | coderdailyone | commit `ee32ea0`; ContentProject template selections resolve to immutable published revision references rather than `selected`; ScriptBlock now persists template contributions and FactCitation field/character-span data; citation revision must match an approved pinned FactCard; live-room plans inherit only the ContentProject template set and reject downstream template substitution; content, live-room and rendered-video test fixtures now exercise explicit ContentProject and DesignBrief confirmation; focused PostgreSQL tests `12 passed`, Ruff, Console typecheck and build passed | N/A: external templates are still legacy/reference projections rather than the Phase 2 content-strategy template contract; no provider raw-response ArtifactRef, editable contribution-decision UI, authoritative room preflight, or production execution evidence exists. This is a Phase 1 spike under `CHK-0004`; no Phase 1 checkbox is checked while Phase 0 exit inputs remain open. | 2026-07-24 |
| `CHK-1180`-`CHK-1188` preparation (items remain open) | coderdailyone | commit `d71b50b`; migration `052`; production-only `maitu_scene_blueprints` and `layer_blueprints` separated from observed reference blueprints; live-room plan persists ordered scene/layer projections with geometry, role, selected asset, Shot/ProgramSegment and ScriptBlock provenance; every scene/layer receives an append-only `ShotProjectionLink`; deterministic script-layout BuildPlan is persisted with a real `build_plan_code`, fixed content/variant/configuration/inventory/blueprint/policy fingerprints and an allowlisted no-go-live operation sequence; PostgreSQL focused content/live/video/build-plan suite `16 passed`, Ruff, Console typecheck and build passed | N/A: title rename remains a planned contract gap in the shared script-layout operation schema; this spike has no authoritative room preflight, execution authorization, readback evidence, release candidate or full constraint solver. This is not a Phase 1 completion claim. | 2026-07-24 |
| `CHK-1187`,`CHK-1188`,`CHK-1200`,`CHK-1201` preparation (items remain open) | coderdailyone | commit `caf85bd`; migration `053`; functional live-room plans now persist seven named static gate results with stable rule codes/version/evidence/remediation plus a branch-quality report; input boundary, Shot projection, operation allowlist and no-go-live conditions can block; target-duration deviation over 50% remains warning-only; Console renders gate states and estimated duration; focused PostgreSQL suite `17 passed`, Ruff, Console typecheck and build passed | N/A: static gate evaluation cannot replace authoritative room readback, commit-time authorization, Worker reconciliation or release evidence. The evidence-completeness gate intentionally remains warning until those integrations exist; no Phase 1 checkbox is checked. | 2026-07-24 |
| `CHK-1220`,`CHK-1221` preparation (items remain open) | coderdailyone | migration `054`; ready functional live-room plans can create an idempotent signed `live_room_draft` release candidate. Its local content-addressed PostgreSQL snapshot fixes exact ContentProject/StoryBrief/Script/Program/ShotList/Variant/Configuration revisions, asset/group selection, `MaituSceneBlueprint`/Layer projection, BuildPlan, static gate report and execution state. The manifest references the snapshot ArtifactRef, carries fixed carrier facet and provenance, and Console displays the candidate/manifest/snapshot state. Candidate validation deliberately fails on pending rights, draft authorization and authoritative readback rather than approving or delivering it. Focused PostgreSQL content/live/video/production/build-plan/release suite `22 passed`; Ruff, Console typecheck and build passed. | N/A: this is a reviewable candidate only. No actual rights evidence, Worker preflight, short-lived write authorization, DeliveryAttempt, authoritative readback, execution reconciliation or exposure is created. Deployment signing material and operational evidence are tracked as `EXT-P1-RELEASE-SIGNING` and `EXT-P1-RELEASE-EVIDENCE`; no Phase 1 checkbox is checked while Phase 0 exits remain open. | 2026-07-24 |
| `CHK-1223`,`CHK-1224` preparation (items remain open) | coderdailyone | migration `055`; `/functional-live-room-plans/{plan_code}/clone` and Console clone controls recompile a source plan's current, revision-matched business inputs to a different target room. A clone creates a fresh Variant/Configuration/Blueprint/BuildPlan and records source provenance plus the explicit list of cleared target state. It cannot reuse the source target ID, and refuses a source whose ContentProject has advanced, preventing an old selection from silently mixing with newer content. It never carries release, delivery, authorization, execution or readback state. Focused PostgreSQL live-room suite `6 passed`; Ruff, Console typecheck and build passed. | N/A: this is a plan-only clone, not a confirmed-empty-room copy. Authoritative target identity/empty/unlive preflight, write authorization and Worker execution are still absent, so no non-empty-room protection or Phase 1 completion is claimed. | 2026-07-24 |
| `CHK-1225` preparation (item remains open) | coderdailyone | migration `056`; every generated BuildPlan operation is persistently linked to one or more generated `MaituSceneBlueprint` or `LayerBlueprint` targets with a typed preflight/configure/mutate/write/verify/save relationship. `/functional-live-room-plans/{plan_code}/trace` resolves those links through Shot, ProgramSegment and ScriptBlock to the fixed StoryBrief fact/template revision refs; Console loads the trace on demand. New plans link on compilation; older plans receive the same append-only relation projection when first traced. Focused PostgreSQL live-room and shared BuildPlan suites `8 passed`; Ruff, Console typecheck and build passed. | N/A: the trace proves planned provenance only. It does not yet connect executed operation results, authoritative room readback, delivery or exposure evidence, so the end-to-end Phase 1 trace/evidence gate remains open. | 2026-07-24 |
| `CHK-2140`-`CHK-2146`,`CHK-2307` preparation (items remain open) | coderdailyone | Functional live-room compilation now resolves each selected asset's current `AssetConstraintProfile` revision into the material snapshot and Variant constraint snapshot. It applies normalized allowed regions, forbidden-region rejection, size/scale bounds, named regions, `table_surface`, anchor placement, layer top/bottom and relative z-order, overlap rejection plus crop/rotation/audio policy projections to generated `LayerBlueprint` evidence. Hard profile failures block the branch. Asset Library exposes the added rule vocabulary. PostgreSQL integration proves table-surface product placement and missing hard-region rejection; focused live-room/material-library suites `9 passed`; Ruff and Console build passed. | N/A: this is a deterministic constraint compiler, not the required solver adapter. It lacks room-private override revisions, polygons, distance/objective optimization, minimal conflict sets, execution-side audio/property enforcement and real rights-aware material resolution. No Phase 2 checkbox is checked. | 2026-07-24 |
| `CHK-2180`-`CHK-2190`,`CHK-2200`,`CHK-2202` preparation (items remain open) | coderdailyone | migration `057`; AssetGroup continues to support many-to-many membership. Material packs now expose a `draft -> published` action and only published packs can enter a live-room plan. Planning resolves every selected pack once, records its pack code, revision, fingerprint, entries and exact active asset whitelist in the Variant/Configuration/BuildPlan inventory snapshot, then persists selected pack codes on the plan and release snapshot. Asset Library shows publish state; Live Room only offers published packs alongside separate group and loose-asset selection. PostgreSQL material-library/live-room suites `10 passed`; Ruff, Console typecheck and all three Vite builds passed. | N/A: this is a functional first slice, not full Phase 2 material resolution. It has no pack revision editing/supersession, nested total/classification packs, role-domain merge modes, exclusivity, occurrence enforcement, per-branch overrides, rights filtering, solver evidence, version diff or complete selection explanation. No strict checkbox is checked while Phase 0 exits remain open. | 2026-07-24 |
| `CHK-2263`-`CHK-2266`,`CHK-2269`,`CHK-2270`,`CHK-2272`,`CHK-2300` preparation (items remain open) | coderdailyone | migration `058`; a typed `content-strategy.v2` revision now keeps source CaptureSession bridge rows and rejects incomplete or cross-target session combinations with stable `CONTENT_STRATEGY_CROSS_ROOM_SOURCE`. Its immutable projection is content-only and forces `buildability=reference_only`; `content_readiness`, `layout_fidelity`, `buildability`, category/program outline/material cues/reviewed examples/layout reference/provenance are independently persisted and returned. `layout-hypothesis.v1` remains a separate layout template kind. ContentProject accepts only ready, published `content-strategy.v2` references, pins their revision/fingerprint, and cannot turn a reference layout into an executable Blueprint. Live Research provides a Content Strategy tab for selecting one watched target's completed sessions, creating the strategy template/revision and publishing its projection. Live-room `?run=` deep links now synchronize their selected plan, with a regression test proving `RUN-A -> RUN-B` switches the loaded detail. Clean migrations `001`-`058` and focused PostgreSQL suite `28 passed`; Ruff, Console test, TypeScript and all three Vite builds passed. | N/A: ASR/OCR extraction, timeline/player evidence linkage, source-fact redaction proof, similarity/copyright/PII review and full template review workflow remain unimplemented. This first usable authoring path must not be treated as a released source-analysis or safety-complete template capability; no strict checkbox is checked while Phase 0 exits remain open. | 2026-07-24 |
| `CHK-2206`-`CHK-2209` preparation (items remain open) | coderdailyone | migration `059`; `AssetGap` now persists gap type, impact, alternatives, resolution snapshot/evidence, resolver and waiver reason. An append-only `asset_gap_resolution_events` log records creation and every state change. The first operational lifecycle allows `open -> candidate_found -> resolved`, or scoped waiver/obsolete paths; direct resolution and illegal post-resolution transitions return stable validation errors. Candidate/resolution checks lock the gap and require an active asset with the requested `material_role` and a classified non-unavailable capability; resolution snapshots the asset classification, checksum, binding identifier, updated time and active constraint-profile revision. Asset Library supports creating typed gaps, role-filtered candidate selection, candidate confirmation, fixed resolution and reason-required waiver, with record count and snapshot indication. PostgreSQL material/live/content suites `19 passed`; Ruff, frontend 33 tests, TypeScript and all three Vite builds passed. | N/A: a candidate is not yet bound to a real ProductionVariant revision and has no RightsGrant or solver preflight because those domain capabilities are not implemented. Per-branch waiver scope, source StoryBrief/ScriptBlock/Shot links, alternate-candidate recomputation and release/selection filtering remain incomplete. No strict checkbox is checked while Phase 0 exits remain open. | 2026-07-24 |
| `CHK-2300` preparation update (item remains open) | coderdailyone | Content Project creation now queries Live Research and exposes only published, `content_readiness=ready`, `buildability=reference_only`, `template_kind=content_strategy` templates. The form uses one explicit primary-template radio choice plus independent secondary-template checkboxes, automatically removing the primary from secondary selections; each option shows category, fixed published revision and available program modules. The existing backend validates duplicate selections and pins the selected immutable published revision before confirmation/generation. Frontend TypeScript and focused Console regression passed. | N/A: no category/goal-based recommendation, compatibility scoring, duplicate module conflict explanation, editable module contribution decision or adopted/unadopted explanation exists yet. This is a selection surface only and no strict checkbox is checked. | 2026-07-24 |
| `CHK-2202`,`CHK-2205` preparation update (items remain open) | coderdailyone | Functional live-room material snapshots now preserve each selected asset's immutable selection sources: loose asset, expanded AssetGroup and/or published MaterialPack, in addition to the already fixed classification and constraint-profile revision. The plan detail visualizes the snapshot, source codes, execution capability, active constraint profile and fixed material-pack revisions. A PostgreSQL integration test proves pack-expanded assets carry the material-pack source and remain detached from later group edits; focused live-room suite `8 passed`, Ruff, TypeScript and Console regression passed. | N/A: there is still no resolver score, exclusion-code report, dedup/exclusivity explanation, RightsGrant merge or branch-specific selection override. This is transparent fixed-source evidence, not the full selection-ranking implementation, and no strict checkbox is checked. | 2026-07-24 |

## 附录 C. 权威设计覆盖索引

| 权威设计章节 | 主要 checklist 覆盖 | 最终核验 |
| --- | --- | --- |
| 第 1-4 节：目标、决策、范围、产品信息架构 | 使用规则、Phase 0.9、Phase 7.5、Phase 7.8 | `CHK-8101`、`CHK-8291` |
| 第 5-7 节：素材、约束、分组、素材包、缺口 | Phase 2.1-2.6 | `CHK-2390` 至 `CHK-2397` |
| 第 8 节：外部录屏与内容策略模板 | Phase 2.7-2.9 | `CHK-2395`、`CHK-2396` |
| 第 9-12 节：内容聚合、生成、优先级和数据对象 | Phase 0.2、Phase 1、Phase 2.9 | `CHK-1290` 至 `CHK-1295` |
| 第 13-14 节：API 与状态机 | `DOD-001` 至 `DOD-004`、各 Phase API/状态任务 | `CHK-8121`、`CHK-8126`、`CHK-8127` |
| 第 15 节：安全、审计、版本、证据和可复现性 | Phase 0.3-0.5、Phase 1.6、Phase 8.6-8.7 | `CHK-8200` 至 `CHK-8227` |
| 第 16-17 节：现状差距与迁移 | Phase 0.1、Phase 0.9、Phase 8.3 | `CHK-0294`、`CHK-8140` 至 `CHK-8145` |
| 第 18-19 节：实施顺序与验收场景 | Phase 0-7 退出门禁、Phase 8.1、Phase 8.8 | `CHK-8102`、`CHK-8240` 至 `CHK-8247` |
| 第 20 节：成片、剪辑与时间轴 | Phase 3 | `CHK-3290` 至 `CHK-3294` |
| 第 21 节：运营、指标、归因和实验 | Phase 4、Phase 5.1、Phase 6.2 | `CHK-4290` 至 `CHK-4294`、`CHK-6290` 至 `CHK-6292` |
| 第 22-23 节：知识图谱、效果学习与再生产 | Phase 5.2-5.5、Phase 7.1-7.2 | `CHK-5291` 至 `CHK-5295`、`CHK-7290`、`CHK-7291` |
| 第 24 节：Shot、排播和角色策略 | Phase 0.2、Phase 1.3/1.5、Phase 6、Phase 7.3-7.4 | `CHK-1291`、`CHK-6290`、`CHK-7292`、`CHK-7293` |
| 第 25 节：运行、发布与执行授权 | Phase 0.3-0.6、Phase 1.6-1.7 | `CHK-0291` 至 `CHK-0293`、`CHK-1293` |
| 第 26 节：隐私、权利、保留和删除 | Phase 0.8、Phase 2.2、Phase 7.6、Phase 8.6 | `CHK-7294`、`CHK-8203` 至 `CHK-8207` |
| 第 27-28 节：容量、SLO、成本、灾备、标准和采用门槛 | Phase 0.1、Phase 3.4、Phase 7.7、Phase 8.7/8.9 | `CHK-7295`、`CHK-8220` 至 `CHK-8227`、`CHK-8269` |
| 第 29-31 节：最终对齐、完成定义和成熟实践 | Phase 8.9-8.10 | `CHK-8290` 至 `CHK-8297` |

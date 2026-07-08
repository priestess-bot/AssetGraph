# AssetGraph 多模态素材库 MVP 架构设计

## 1. 项目定位

AssetGraph 面向麦兔软件与数字人直播业务的多模态视频资产管理、智能分析、检索与关系沉淀。系统以 Weknora 作为核心知识库与检索编排框架，结合 MinIO、PostgreSQL、Milvus、Neo4j，形成“对象存储 + 结构化元数据 + 多模态向量检索 + 数字人直播知识图谱 + 麦兔素材替换上下文”的资产平台。

核心目标：

- 对数字人直播录屏、视频切片、字幕、脚本、封面、商品素材、评论数据、复盘内容等资产统一入库。
- 为每个底层素材生成全局唯一且可读的 `asset_code`。
- 为每场数字人直播生成全局唯一的 `live_code`，并通过直播编号索引组成该场直播的所有素材。
- 管理数字人形象、音色、商品、脚本、脚本块和视频片段等直播业务对象。
- 记录麦兔素材分类、场景、图层、槽位和替换策略，使 Agent 能按麦兔模板位置查找并替换素材。
- 将麦兔替换方案转换为 Browser use 可理解的操作步骤；实际打开麦兔软件并执行搭建/替换由 Browser use 完成。
- 接收 Browser use 执行结果回写，记录执行状态、单槽位结果、错误信息和截图素材编号。
- 对 Browser use 失败结果进行分类，记录是否可重试和重试指令，并生成可追踪的重试任务。
- 将单个重试任务转换为 Browser use 最小化重试操作计划，只重试失败槽位并保持麦兔原布局。
- 接收 Browser use 重试执行结果，自动更新 retry task 状态、重试次数、最近执行编号、截图和结果摘要。
- 提供重试队列视图，批量返回 pending、retryable、未超过最大尝试次数的 retry task 及麦兔上下文。
- 提供重试任务领取/释放机制，记录 worker、领取时间和锁过期时间，避免多 worker 重复执行同一任务。
- 提供过期领取回收机制，将超时 `in_progress` retry task 自动释放回 `pending`。
- 提供 worker 一站式取活入口，自动回收过期任务、领取下一条任务并返回 Browser use 操作计划。
- 提供 Browser use retry worker 执行协议文档，约束 worker 只重试失败槽位、保持麦兔原布局并按结果回写。
- 支持关键词检索、向量相似检索、图谱关系检索。
- 支持直播视频解析、语音转写、片段切分、标签生成、实体抽取、关系沉淀。
- 为后续直播复盘、短视频二创、话术优化、素材推荐和 AI Agent 内容生产工作流提供数据底座。

## 2. 技术选型

| 模块 | 技术 | 职责 |
| --- | --- | --- |
| 核心框架 | Weknora | 知识库接入、检索编排、RAG、多路召回融合 |
| 对象存储 | MinIO | 存储原始素材、缩略图、转码文件、抽帧、字幕等文件 |
| 结构化数据库 | PostgreSQL | 存储素材元数据、编号、标签、任务状态、权限、项目归属 |
| 向量数据库 | Milvus | 存储文本、图片、视频帧、音频转写等 embedding |
| 图数据库 | Neo4j | 存储素材、人物、地点、事件、品牌、项目、场景等关系 |

## 3. MVP 范围

第一阶段优先支持数字人直播视频资产闭环。

MVP 功能：

1. 创建数字人、音色、商品、脚本和直播场次。
2. 上传数字人直播录屏并生成素材编号。
3. 原始文件写入 MinIO。
4. 元数据写入 PostgreSQL。
5. 维护直播与录屏、切片、封面、字幕、评论导出和复盘文档的关联。
6. 入库素材时记录麦兔分类、场景、图层、槽位、位置尺寸和替换策略。
7. 创建视频片段记录，记录起止时间、字幕、讲解商品、数字人、音色和脚本块。
8. 支持按 `live_code`、商品、数字人、字幕关键词和时间段检索片段。
9. 支持 Agent 按 `asset_code`、名称、麦兔分类、场景、槽位检索可替换素材。
10. 为后续 ASR、视频抽帧、向量化和图谱写入预留任务状态与关系字段。
11. 文本和视觉向量写入 Milvus。
12. 数字人、音色、商品、脚本、视频片段关系写入 Neo4j。

第二阶段再扩展：

- 自动 ASR 转写与字幕对齐。
- 视频自动切片和高光推荐。
- 数字人口型/音画同步检测。
- 画面质量、音频质量和异常片段检测。
- 短视频二创素材包生成。
- 自动直播复盘与话术优化。

## 4. 素材编号规范

### 4.1 编号定位

系统同时保留两类标识：

- `id`：系统内部主键，建议使用 UUID。
- `asset_code`：用户可见的素材业务编号，全局唯一，不可修改。

`asset_code` 是跨 PostgreSQL、MinIO、Milvus、Neo4j 的统一关联字段。

### 4.2 编号格式

推荐格式：

```text
AG-{TYPE}-{YYYYMMDD}-{SEQ}
```

字段说明：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `AG` | `AG` | AssetGraph 固定前缀，可后续按素材库调整 |
| `TYPE` | `IMG` | 素材类型编码 |
| `YYYYMMDD` | `20260706` | 入库日期 |
| `SEQ` | `000001` | 当日同类型递增流水号，6 位补零 |

类型编码：

| 类型 | 编码 | 示例 |
| --- | --- | --- |
| 图片 | `IMG` | `AG-IMG-20260706-000001` |
| 视频 | `VID` | `AG-VID-20260706-000001` |
| 音频 | `AUD` | `AG-AUD-20260706-000001` |
| 文档 | `DOC` | `AG-DOC-20260706-000001` |
| 其他 | `OTH` | `AG-OTH-20260706-000001` |

### 4.3 编号生成规则

1. 上传请求进入系统后，先判断素材类型。
2. 在 PostgreSQL 事务中锁定当天、同类型的编号序列。
3. 生成新的 `asset_code`。
4. 创建 `assets` 主记录。
5. 使用 `asset_code` 构造 MinIO 对象路径。
6. 文件上传成功后更新素材状态为 `stored`。
7. 后续解析、向量化、图谱写入均引用同一个 `asset_code`。

编号一旦生成，不允许修改或复用。即使素材删除，也保留编号审计记录，避免历史引用失效。

## 5. 直播编号与直播素材索引

### 5.1 直播编号定位

直播是比单个素材更高一层的内容集合。每场直播拥有独立的 `live_code`，用于索引组成该场直播的所有素材，例如直播录屏、直播切片、封面图、商品图、讲解音频、字幕、评论数据、复盘文档等。

系统同时保留两类直播标识：

- `id`：直播内部主键，建议使用 UUID。
- `live_code`：用户可见的直播业务编号，全局唯一，不可修改。

`live_code` 与 `asset_code` 是一对多关系：一场直播可以包含多个素材，一个素材也可以按业务需要关联到一场或多场直播。

### 5.2 直播编号格式

推荐格式：

```text
AG-LIVE-{YYYYMMDD}-{SEQ}
```

示例：

```text
AG-LIVE-20260706-000001
```

字段说明：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `AG` | `AG` | AssetGraph 固定前缀 |
| `LIVE` | `LIVE` | 直播内容单元编码 |
| `YYYYMMDD` | `20260706` | 直播创建或开播日期 |
| `SEQ` | `000001` | 当日直播递增流水号，6 位补零 |

### 5.3 直播-素材关系

直播和素材之间通过关联表维护，不建议只依赖文件路径推断。

关系属性建议：

- `relation_type`：素材在直播中的角色。
- `sort_order`：展示或播放顺序。
- `start_time_seconds`：素材对应直播时间线起点。
- `end_time_seconds`：素材对应直播时间线终点。
- `segment_label`：片段名称，例如“开场”“产品讲解”“答疑”“福利口播”。

`relation_type` 示例：

| 角色 | 说明 |
| --- | --- |
| `recording` | 完整直播录屏 |
| `clip` | 直播切片 |
| `cover` | 直播封面 |
| `product_image` | 商品图或素材图 |
| `audio` | 直播音频 |
| `transcript` | 字幕或转写文本 |
| `comment_export` | 评论、弹幕、互动数据 |
| `analysis_doc` | 复盘、脚本、分析文档 |

### 5.4 直播入库链路

```text
创建直播场次
  -> 生成 live_code
  -> 写入 PostgreSQL live_sessions 记录
  -> 上传或关联直播素材
  -> 为每个素材生成 asset_code
  -> 写入 live_assets 关联关系
  -> 按直播时间线补充素材角色、顺序、起止时间
  -> 素材解析、向量化、图谱写入
  -> Neo4j 写入 LiveSession -> Asset 关系
  -> 通过 live_code 聚合检索该场直播所有素材
```

## 6. 入库流程

### 5.1 标准入库链路

```text
用户上传
  -> 文件校验
  -> 判断素材类型
  -> 生成 asset_code
  -> 创建 PostgreSQL assets 记录
  -> 上传原始文件到 MinIO
  -> 写入 asset_files 记录
  -> 创建 processing_jobs 解析任务
  -> 图片/视频解析
  -> 写入标签、实体、OCR/ASR 结果
  -> 生成 embedding 写入 Milvus
  -> 写入 Neo4j 图谱关系
  -> 素材状态变更为 ready
```

### 5.2 状态流转

| 状态 | 说明 |
| --- | --- |
| `created` | 已生成编号和主记录，文件尚未完全存储 |
| `stored` | 原始文件已写入 MinIO |
| `processing` | 正在解析、抽帧、OCR、ASR、向量化 |
| `ready` | 可检索、可查看、可参与图谱关系查询 |
| `failed` | 入库或解析失败 |
| `archived` | 已归档，不参与默认检索 |
| `deleted` | 逻辑删除，编号不复用 |

## 7. 麦兔素材分类与替换上下文

### 7.1 双层分类

AssetGraph 对素材采用双层分类：

```text
asset_type      = IMG / VID / AUD / DOC / OTH
maitu_category  = product_image / background_image / digital_human_video / ...
```

`asset_type` 表示文件类型，用于编号、存储、转码和基础处理；`maitu_category` 表示素材在麦兔软件中的业务用途，用于 Agent 查找可替换素材。

### 7.2 第一批 maitu_category

| 分类 | 说明 |
| --- | --- |
| `digital_human_video` | 数字人口播视频 |
| `background_video` | 背景视频 |
| `background_image` | 背景图片 |
| `product_image` | 商品图片 |
| `product_video` | 商品展示视频 |
| `banner_image` | 横幅图 |
| `price_card` | 价格牌/优惠信息图 |
| `floating_sticker` | 贴片/角标 |
| `subtitle_file` | 字幕文件 |
| `voice_audio` | 音色/配音音频 |
| `bgm_audio` | 背景音乐 |
| `sound_effect` | 音效 |
| `script_text` | 话术脚本 |
| `comment_export` | 评论/互动导出 |
| `replay_recording` | 直播录屏 |
| `highlight_clip` | 精彩片段 |
| `analysis_doc` | 复盘文档 |

### 7.3 槽位编号

麦兔模板中的可替换位置使用独立编号：

```text
MT-SLOT-{YYYYMMDD}-{SEQ}
```

示例：

```text
MT-SLOT-20260707-000001
```

槽位编号用于让 Agent 精确引用“要替换哪个位置”，而不是只靠自然语言描述“商品主图”“背景图”。

### 7.4 替换方案编号

麦兔素材替换方案使用独立编号：

```text
MT-PLAN-{YYYYMMDD}-{SEQ}
```

示例：

```text
MT-PLAN-20260707-000001
```

替换方案用于表达某个麦兔项目/场景下，一组槽位分别选择哪个素材，以及哪些槽位缺少候选素材。

### 7.5 Browser use 执行编号

Browser use 每次执行麦兔替换方案时使用独立执行编号：

```text
MT-EXEC-{YYYYMMDD}-{SEQ}
```

示例：

```text
MT-EXEC-20260707-000001
```

执行编号用于追踪一次 Browser use 操作麦兔软件的整体结果，并关联每个槽位的成功、失败、截图和错误信息。

### 7.6 Browser use 重试任务编号

当 Browser use 执行失败且可自动恢复时，AssetGraph 生成独立重试任务编号：

```text
MT-RETRY-{YYYYMMDD}-{SEQ}
```

示例：

```text
MT-RETRY-20260707-000001
```

重试任务用于记录失败类型、是否可重试、重试指令、重试次数、最近一次重试执行编号和处理状态。典型失败类型包括 `missing_layer`、`login_expired`、`asset_upload_failed`、`save_failed`、`selector_changed`、`missing_asset`、`manual_required`。

### 7.7 替换上下文

麦兔素材入库时建议记录：

- `maitu_project_code`
- `maitu_scene_name` / `maitu_scene_index`
- `maitu_layer_name` / `maitu_layer_index`
- `maitu_slot_name` / `maitu_slot_code`
- `layer_left` / `layer_top` / `layer_width` / `layer_height` / `layer_z_index`
- `replacement_policy`

`replacement_policy` 默认值为 `keep_layout`，含义是只替换素材资源，保持麦兔原有场景结构、图层位置和尺寸。

## 8. PostgreSQL 表结构建议

### 8.1 assets

素材主表。

```sql
CREATE TABLE assets (
    id UUID PRIMARY KEY,
    asset_code VARCHAR(32) NOT NULL UNIQUE,
    asset_type VARCHAR(16) NOT NULL,
    title VARCHAR(255),
    original_filename VARCHAR(512) NOT NULL,
    file_ext VARCHAR(32),
    mime_type VARCHAR(128),
    file_size BIGINT,
    checksum_sha256 CHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    project_id UUID,
    description TEXT,
    source_type VARCHAR(64),
    maitu_category VARCHAR(64),
    maitu_project_code VARCHAR(64),
    maitu_scene_name VARCHAR(128),
    maitu_scene_index INTEGER,
    maitu_layer_name VARCHAR(128),
    maitu_layer_index INTEGER,
    maitu_slot_name VARCHAR(128),
    maitu_slot_code VARCHAR(64),
    layer_left NUMERIC(12, 3),
    layer_top NUMERIC(12, 3),
    layer_width NUMERIC(12, 3),
    layer_height NUMERIC(12, 3),
    layer_z_index INTEGER,
    replacement_policy VARCHAR(32) NOT NULL DEFAULT 'keep_layout',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_assets_asset_type ON assets(asset_type);
CREATE INDEX idx_assets_status ON assets(status);
CREATE INDEX idx_assets_created_at ON assets(created_at);
CREATE INDEX idx_assets_project_id ON assets(project_id);
CREATE INDEX idx_assets_maitu_category ON assets(maitu_category);
CREATE INDEX idx_assets_maitu_scene_name ON assets(maitu_scene_name);
CREATE INDEX idx_assets_maitu_slot_name ON assets(maitu_slot_name);
```

### 6.2 asset_sequences

编号流水表。

```sql
CREATE TABLE asset_sequences (
    sequence_date DATE NOT NULL,
    asset_type VARCHAR(16) NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sequence_date, asset_type)
);
```

生成编号时按 `(sequence_date, asset_type)` 加行级锁，避免并发上传时重复编号。

### 6.3 asset_files

素材文件表，用于记录原始文件和派生文件。

```sql
CREATE TABLE asset_files (
    id UUID PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES assets(id),
    asset_code VARCHAR(32) NOT NULL,
    file_role VARCHAR(32) NOT NULL,
    bucket_name VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    mime_type VARCHAR(128),
    file_size BIGINT,
    checksum_sha256 CHAR(64),
    width INTEGER,
    height INTEGER,
    duration_seconds NUMERIC(12, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_asset_files_asset_id ON asset_files(asset_id);
CREATE INDEX idx_asset_files_asset_code ON asset_files(asset_code);
CREATE INDEX idx_asset_files_file_role ON asset_files(file_role);
```

`file_role` 示例：

- `original`：原始文件。
- `thumbnail`：缩略图。
- `preview`：预览文件。
- `frame`：视频抽帧。
- `transcript`：音频或视频转写文本。
- `subtitle`：字幕文件。

### 6.4 tags 与 asset_tags

```sql
CREATE TABLE tags (
    id UUID PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    tag_type VARCHAR(32) NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE asset_tags (
    asset_id UUID NOT NULL REFERENCES assets(id),
    tag_id UUID NOT NULL REFERENCES tags(id),
    source VARCHAR(32) NOT NULL DEFAULT 'manual',
    confidence NUMERIC(5, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_id, tag_id, source)
);
```

### 6.5 processing_jobs

```sql
CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES assets(id),
    asset_code VARCHAR(32) NOT NULL,
    job_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_processing_jobs_status ON processing_jobs(status);
CREATE INDEX idx_processing_jobs_asset_code ON processing_jobs(asset_code);
```

### 7.6 live_sessions

直播场次表。

```sql
CREATE TABLE live_sessions (
    id UUID PRIMARY KEY,
    live_code VARCHAR(40) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    platform VARCHAR(64),
    streamer_name VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    project_id UUID,
    scheduled_start_at TIMESTAMPTZ,
    actual_start_at TIMESTAMPTZ,
    actual_end_at TIMESTAMPTZ,
    description TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_live_sessions_live_code ON live_sessions(live_code);
CREATE INDEX idx_live_sessions_project_id ON live_sessions(project_id);
CREATE INDEX idx_live_sessions_status ON live_sessions(status);
```

### 7.7 live_sequences

直播编号流水表。

```sql
CREATE TABLE live_sequences (
    sequence_date DATE PRIMARY KEY,
    current_value INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 7.8 live_assets

直播与素材关联表。

```sql
CREATE TABLE live_assets (
    live_id UUID NOT NULL REFERENCES live_sessions(id),
    asset_id UUID NOT NULL REFERENCES assets(id),
    live_code VARCHAR(40) NOT NULL,
    asset_code VARCHAR(32) NOT NULL,
    relation_type VARCHAR(64) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    start_time_seconds NUMERIC(12, 3),
    end_time_seconds NUMERIC(12, 3),
    segment_label VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (live_id, asset_id, relation_type)
);

CREATE INDEX idx_live_assets_live_code ON live_assets(live_code);
CREATE INDEX idx_live_assets_asset_code ON live_assets(asset_code);
CREATE INDEX idx_live_assets_relation_type ON live_assets(relation_type);
```

通过 `live_code` 查询 `live_assets`，即可一次索引出组成该场直播的全部素材编号，再批量读取素材详情、文件、向量结果和图谱关系。

## 8. MinIO 路径规范

推荐 bucket：

```text
assetgraph
```

对象路径：

```text
lives/{YYYY}/{MM}/{DD}/{live_code}/manifest.json
lives/{YYYY}/{MM}/{DD}/{live_code}/recordings/{asset_code}/{filename}
lives/{YYYY}/{MM}/{DD}/{live_code}/clips/{asset_code}/{filename}
lives/{YYYY}/{MM}/{DD}/{live_code}/covers/{asset_code}/{filename}
lives/{YYYY}/{MM}/{DD}/{live_code}/transcripts/{asset_code}.txt
assets/{YYYY}/{MM}/{DD}/{asset_code}/original/{filename}
assets/{YYYY}/{MM}/{DD}/{asset_code}/thumbnail/{filename}
assets/{YYYY}/{MM}/{DD}/{asset_code}/preview/{filename}
assets/{YYYY}/{MM}/{DD}/{asset_code}/frames/{frame_index}.jpg
assets/{YYYY}/{MM}/{DD}/{asset_code}/transcripts/{asset_code}.txt
assets/{YYYY}/{MM}/{DD}/{asset_code}/subtitles/{asset_code}.srt
```

示例：

```text
lives/2026/07/06/AG-LIVE-20260706-000001/manifest.json
lives/2026/07/06/AG-LIVE-20260706-000001/recordings/AG-VID-20260706-000001/full.mp4
lives/2026/07/06/AG-LIVE-20260706-000001/clips/AG-VID-20260706-000002/highlight-01.mp4
assets/2026/07/06/AG-IMG-20260706-000001/original/campaign-poster.jpg
assets/2026/07/06/AG-VID-20260706-000001/frames/000001.jpg
assets/2026/07/06/AG-VID-20260706-000001/transcripts/AG-VID-20260706-000001.txt
```

## 8. Milvus Collection 建议

MVP 阶段建议先拆成三个 collection：

### 8.1 asset_text_embeddings

用于 OCR、ASR、标题、描述、标签文本检索。

字段：

- `id`
- `asset_code`
- `live_code`
- `chunk_id`
- `chunk_type`
- `text`
- `embedding`
- `metadata`

### 8.2 asset_image_embeddings

用于图片和视频关键帧相似检索。

字段：

- `id`
- `asset_code`
- `live_code`
- `file_id`
- `frame_index`
- `embedding`
- `metadata`

### 8.3 asset_multimodal_embeddings

用于后续统一多模态 embedding 检索，可在第二阶段启用。

字段：

- `id`
- `asset_code`
- `modality`
- `embedding`
- `metadata`

## 9. Neo4j 图谱 Schema 建议

### 9.1 节点类型

| 节点 | 说明 | 关键属性 |
| --- | --- | --- |
| `LiveSession` | 直播场次 | `live_code`, `title`, `platform`, `status` |
| `Asset` | 素材 | `asset_code`, `asset_type`, `title`, `status` |
| `Project` | 项目 | `project_id`, `name` |
| `Tag` | 标签 | `name`, `tag_type` |
| `Person` | 人物 | `name`, `source` |
| `Scene` | 场景 | `name` |
| `Object` | 物体 | `name` |
| `Location` | 地点 | `name` |
| `Brand` | 品牌 | `name` |
| `Event` | 事件 | `name`, `event_time` |

### 9.2 关系类型

| 关系 | 方向 | 说明 |
| --- | --- | --- |
| `CONTAINS_ASSET` | `LiveSession -> Asset` | 直播包含素材，关系属性记录素材角色、顺序和时间线 |
| `BELONGS_TO_LIVE` | `Asset -> LiveSession` | 素材归属或关联到某场直播 |
| `BELONGS_TO` | `Asset -> Project` | 素材属于项目 |
| `HAS_TAG` | `Asset -> Tag` | 素材拥有标签 |
| `CONTAINS_PERSON` | `Asset -> Person` | 素材中出现人物 |
| `CONTAINS_OBJECT` | `Asset -> Object` | 素材中出现物体 |
| `HAS_SCENE` | `Asset -> Scene` | 素材关联场景 |
| `SHOT_AT` | `Asset -> Location` | 素材拍摄地点 |
| `MENTIONS_BRAND` | `Asset -> Brand` | 素材涉及品牌 |
| `RELATED_TO_EVENT` | `Asset -> Event` | 素材关联事件 |
| `SIMILAR_TO` | `Asset -> Asset` | 素材相似关系，可由向量检索离线生成 |

### 9.3 约束建议

```cypher
CREATE CONSTRAINT live_code_unique IF NOT EXISTS
FOR (l:LiveSession) REQUIRE l.live_code IS UNIQUE;

CREATE CONSTRAINT asset_code_unique IF NOT EXISTS
FOR (a:Asset) REQUIRE a.asset_code IS UNIQUE;

CREATE CONSTRAINT tag_name_unique IF NOT EXISTS
FOR (t:Tag) REQUIRE t.name IS UNIQUE;
```

## 10. 检索策略

### 10.1 编号检索

用户输入完整或部分 `asset_code`，优先查 PostgreSQL，返回精确素材。用户输入 `live_code` 时，先查直播场次，再通过 `live_assets` 聚合返回该场直播的全部素材。

### 10.2 关键词检索

查询 PostgreSQL 元数据、OCR/ASR 文本、标签文本，可由 Weknora 统一编排。

### 10.3 向量检索

- 文搜图：用户输入文本，生成文本 embedding，在图片/多模态向量空间中召回。
- 图搜图：上传图片，生成图片 embedding，在 `asset_image_embeddings` 中召回。
- 视频相似搜索：使用封面、关键帧、镜头 embedding 聚合召回。

### 10.4 图谱检索

示例问题：

- “通过直播编号找出这场直播的完整录屏、切片、封面、字幕和复盘文档。”
- “找出某场直播里产品讲解片段用到的所有商品素材。”
- “找出与这个品牌相关的素材。”
- “找出同一场景下相似的宣传图。”
- “找出某事件相关的图片和视频。”

### 10.5 融合排序

Weknora 负责将以下结果融合：

- PostgreSQL 过滤条件。
- Milvus 相似度结果。
- Neo4j 图谱关系得分。
- 标签、时间、项目、状态等业务权重。

## 11. API 清单建议

### 11.1 素材入库

```http
POST /api/assets
```

职责：登记素材元数据、生成编号、保存素材名称、麦兔分类和替换上下文。文件写入 MinIO 的上传能力在后续阶段接入。

返回示例：

```json
{
  "id": "uuid",
  "asset_code": "AG-IMG-20260706-000001",
  "title": "胶原蛋白商品主图-白底款",
  "maitu_category": "product_image",
  "maitu_slot_name": "商品主图",
  "replacement_policy": "keep_layout",
  "status": "created"
}
```

### 11.2 素材详情

```http
GET /api/assets/{asset_code}
```

返回素材元数据、文件列表、标签、解析结果、图谱关系摘要。

### 11.3 素材列表与过滤

```http
GET /api/assets?asset_type=IMG&maitu_category=product_image&maitu_scene_name=京东空白直播间&maitu_slot_name=商品主图&q=胶原蛋白
```

支持按编号/名称关键词、文件类型、麦兔分类、麦兔项目、场景、槽位过滤，供 Agent 快速查找可替换素材。

### 11.4 相似素材

```http
GET /api/assets/{asset_code}/similar
```

基于 Milvus 向量召回相似素材，可写入 Neo4j `SIMILAR_TO` 关系。

### 11.5 图谱关系

```http
GET /api/assets/{asset_code}/graph
```

返回素材相关节点和关系，用于前端图谱展示。

### 11.6 解析任务状态

```http
GET /api/assets/{asset_code}/jobs
```

返回入库后处理任务的状态和错误信息。

### 11.7 创建直播场次

```http
POST /api/lives
```

职责：创建直播场次、生成 `live_code`、写入 `live_sessions`。

返回示例：

```json
{
  "live_id": "uuid",
  "live_code": "AG-LIVE-20260706-000001",
  "status": "planned"
}
```

### 11.8 直播素材列表

```http
GET /api/lives/{live_code}/assets
```

通过直播编号返回组成该场直播的所有素材，支持按 `relation_type`、时间线、素材类型过滤。

### 11.9 关联直播素材

```http
POST /api/lives/{live_code}/assets
```

职责：将已有素材或新上传素材关联到直播场次，写入 `live_assets`，保留素材在麦兔直播间中的场景/图层/槽位替换上下文，并同步 Neo4j `LiveSession -> Asset` 关系。

### 11.10 麦兔素材槽位

```http
POST /api/maitu/slots
GET  /api/maitu/slots
GET  /api/maitu/slots/{slot_code}
GET  /api/maitu/slots/{slot_code}/candidate-assets
PATCH /api/maitu/slots/{slot_code}
DELETE /api/maitu/slots/{slot_code}
```

职责：管理麦兔模板中的可替换素材槽位。Agent 可先查询槽位要求，再按 `required_category`、`accepted_asset_types`、场景、图层和尺寸去检索匹配素材。`candidate-assets` 接口会根据槽位自动返回候选素材、匹配分和匹配原因。

### 11.11 麦兔素材替换方案

```http
POST /api/maitu/replacement-plans
GET  /api/maitu/replacement-plans
GET  /api/maitu/replacement-plans/{plan_code}
GET  /api/maitu/replacement-plans/{plan_code}/browser-use-operations
POST /api/maitu/replacement-plans/{plan_code}/execution-results
GET  /api/maitu/replacement-plans/{plan_code}/execution-results
GET  /api/maitu/replacement-plans/{plan_code}/execution-results/{execution_code}
GET  /api/maitu/retry-queue
POST /api/maitu/retry-queue/claim-next
POST /api/maitu/retry-queue/reclaim-expired
POST /api/maitu/retry-worker/next
GET  /api/maitu/retry-tasks
GET  /api/maitu/retry-tasks/{retry_task_code}
GET  /api/maitu/retry-tasks/{retry_task_code}/browser-use-operations
POST /api/maitu/retry-tasks/{retry_task_code}/execution-results
POST /api/maitu/retry-tasks/{retry_task_code}/release
PATCH /api/maitu/retry-tasks/{retry_task_code}
```

职责：为麦兔项目/场景的一组槽位生成完整替换方案。方案 item 记录槽位编号、选中素材编号、素材标题、匹配分、匹配原因、替换策略和 `selected/missing` 状态。`browser-use-operations` 接口把方案转换为 Browser use 可理解的页面操作步骤，供 Browser use 实际操作麦兔软件。`execution-results` 接口接收 Browser use 执行结果回写，记录总体状态、单槽位操作状态、失败类型、是否可重试、重试指令、错误信息、截图素材编号和执行摘要。`retry-queue` 批量返回 pending、retryable、未超过最大尝试次数的重试任务及麦兔上下文。`retry-queue/claim-next` 原子领取下一条可执行任务并写入 `claimed_by/claimed_at/claim_expires_at`。`retry-queue/reclaim-expired` 将锁过期的 `in_progress` 任务释放回 `pending`。`retry-worker/next` 是 Browser use worker 的一站式取活入口：先回收过期任务，再领取下一条任务，并返回 Browser use 操作计划。`retry-tasks` 接口用于查询与更新可重试失败任务，`retry-tasks/{retry_task_code}/browser-use-operations` 将单个重试任务转换为最小化 Browser use 重试步骤，只重试失败槽位并保持麦兔原布局。`retry-tasks/{retry_task_code}/execution-results` 接收 Browser use 重试结果回写，更新重试任务状态、重试次数、最近执行编号、截图和结果摘要。`retry-tasks/{retry_task_code}/release` 释放已领取任务，清空 claim 字段并将任务放回指定状态。


## 12. 推荐工程目录

```text
D:\AssetGraph
  docs/
    mvp-architecture.md
    worker-protocols/
      maitu-browser-use-retry-worker.md
  backend/
    app/
      api/
      core/
      db/
      services/
      workers/
    migrations/
    tests/
  frontend/
  infra/
    docker-compose.yml
    minio/
    postgres/
    milvus/
    neo4j/
  scripts/
```

## 13. 下一步实施顺序

1. 初始化后端工程与配置管理。
2. 编写 `docker-compose.yml` 启动 PostgreSQL、MinIO、Milvus、Neo4j。
3. 实现 PostgreSQL migration：`assets`、`asset_sequences`、`asset_files`、`tags`、`asset_tags`、`processing_jobs`、`live_sessions`、`live_sequences`、`live_assets`。
4. 实现素材编号和直播编号生成服务。
5. 实现直播创建接口和直播素材关联接口。
6. 实现上传接口，将原始文件写入 MinIO。
7. 实现解析任务队列和 worker。
8. 接入图片 OCR/视觉标签和视频抽帧。
9. 写入 Milvus embedding，并保留 `live_code` 过滤字段。
10. 写入 Neo4j 图谱节点和直播-素材关系。
11. 接入 Weknora 做统一检索编排。

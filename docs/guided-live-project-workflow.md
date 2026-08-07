# 固定直播项目生成流程

新建内容项目只填写项目标题和麦兔直播间号。新项目使用 `guided-live.v1` 工作流，旧项目不迁移，继续由原工作区读取和编辑。

## 固定阶段

1. `主题与素材`：填写直播主题，并从素材库逐项选择本项目允许使用的素材。
2. `直播大纲`：DeepSeek Pro 生成结构化大纲；人工可排序、增删和修改，确认后进入脚本阶段。
3. `直播脚本`：按已确认大纲逐节生成完整口播和素材需求；人工修改并处理素材缺口后确认。
4. `麦兔分镜`：选择一个已发布的麦兔直播模板，按连续且素材签名相同的脚本块生成场景和镜头映射；人工确认后形成可继续搭建的直播间方案。
5. `成片`、`交付`、`动态`：复用现有项目产物、交付和审计视图。

## 数据与门禁

- 模型事实来源仅限直播主题，以及已选素材的标题、分类、描述和分析结果。不能确认的事实必须输出 `[待人工补充：...]`。
- 模型和匹配器不能选择素材池之外的素材。可用素材必须同时满足 `rights_status=approved` 和 `execution_capability=maitu_bound`。
- 脚本阶段可继续补充素材并生成绑定新素材池的脚本 revision，但不能移除已确认大纲使用的素材；补充操作只重新匹配需求，不改写口播正文。
- 必需素材缺失时阻断脚本确认和分镜生成。人工可逐项豁免；系统固定记录原因、操作人和时间，后续分镜标记为仅人工处理。
- 脚本确认后冻结当前脚本和素材池。重新打开大纲会使脚本、分镜失效；重新打开脚本会使分镜失效，历史版本保留。
- 分镜生成前必须选择一个 `published` 状态的麦兔直播模板。分镜确认只形成直播间方案，不自动保存麦兔草稿、排播或开播。

## 后台任务

大纲、脚本和分镜都通过 `content_generation_jobs` 持久化。脚本按大纲章节拆分任务项，可轮询进度并在失败后重试。Worker 使用带归属的限时租约；项目输入更新、任务被替换或租约丢失后，旧 Worker 不能把任务重新写成成功或排队。

Windows 一键启动默认包含该 Worker：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Start-AssetGraph.ps1
```

也可单独运行：

```powershell
backend\.venv\Scripts\python.exe scripts\run_guided_content_generation_worker.py
```

在线生成前需要配置 `DEEPSEEK_API_KEY`，并执行一次处理器授权登记：

```powershell
backend\.venv\Scripts\python.exe scripts\register_maitu_interaction_processor.py --region cn
```

## 主要接口

- `POST /api/content-projects/guided`
- `GET /api/content-projects/{project_code}/guided-workflow`
- `PATCH /api/content-projects/{project_code}/guided-workflow/setup`
- `POST /api/content-projects/{project_code}/guided-workflow/outline/generate`
- `POST /api/content-projects/{project_code}/guided-workflow/script/generate`
- `POST /api/content-projects/{project_code}/guided-workflow/storyboard/generate`
- `POST /api/content-projects/{project_code}/guided-workflow/jobs/{job_code}/retry`

所有编辑和确认接口都带预期 revision，冲突时要求前端刷新，不能覆盖其他操作人的修改。

## Guided workflow enhancements

- Setup has asynchronous theme optimization plus separate knowledge and material recommendations. A recommendation is advisory only; it never changes the project until the operator saves the selected entries.
- Knowledge selection is type-aware (`fact_card`, `fact_claim`, or `content_rule`). Saving setup pins the approved version, checksum, validity window, and source lineage into the project revision. Outline citations can only reference those pinned source IDs.
- A `pending` Maitu-bound asset may be used while planning an outline or draft script. Script confirmation, storyboard generation, and storyboard confirmation require every selected asset to be `rights_status=approved`.
- Digital human and voice are read from the target Maitu working room through the backend-only authority client. The UI receives safe configuration metadata only. Storyboard confirmation is blocked until exactly one complete non-live host configuration is available.
- Full script regeneration immediately marks the current draft as `superseded`, then queues a durable replacement job. The active script view remains empty while the job is running. Archived scripts can be restored only when their outline and material-pool revisions are still compatible; restore always creates a new draft revision.
- Outline sections support independent regeneration. The job replaces only the requested section in a new outline revision after success; the current draft stays editable only when no outline-generation job is active.

Additional endpoints:

- `POST /api/content-projects/{project_code}/guided-workflow/setup/theme-optimize`
- `POST /api/content-projects/{project_code}/guided-workflow/setup/recommendations`
- `GET /api/content-projects/{project_code}/guided-workflow/maitu-room-configuration`
- `POST /api/content-projects/{project_code}/guided-workflow/outline/sections/{section_key}/regenerate`
- `GET /api/content-projects/{project_code}/guided-workflow/revisions`
- `POST /api/content-projects/{project_code}/guided-workflow/script/revisions/{revision_number}/restore`

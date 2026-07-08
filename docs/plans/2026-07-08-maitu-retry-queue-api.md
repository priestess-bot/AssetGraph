# 麦兔重试队列 API

## 背景

AssetGraph 已经完成单个 retry task 的闭环：

```text
失败 -> 生成 MT-RETRY-* -> 生成 Browser use 重试步骤 -> 回写重试结果 -> 更新 retry task
```

下一步需要让 Browser use 或 Agent 可以批量发现“当前还有哪些任务值得重试”，而不是只能知道单个 retry task 编号后再处理。

因此本轮新增 retry queue 视图。

## API

```http
GET /api/maitu/retry-queue
```

查询参数：

```text
status                默认 pending；可传空值/其他状态
failure_type          按失败类型过滤
maitu_project_code    按麦兔项目过滤
scene_name            按麦兔场景过滤
max_attempts          默认 3；只返回 retry_attempt_count < max_attempts 的任务
limit                 默认 50
offset                默认 0
```

示例：

```http
GET /api/maitu/retry-queue?failure_type=missing_layer&maitu_project_code=MT-PROJ-20260708-000001&scene_name=京东空白直播间&max_attempts=3
```

## 返回字段

每个队列项基于 retry task，并补充麦兔上下文：

```text
retry_task_code
plan_code
execution_code
slot_code
asset_code
executor
failure_type
retryable
retry_instruction
status
error_message
screenshot_asset_code
retry_attempt_count
last_retry_execution_code
result_summary
maitu_project_code
scene_name
slot_name
layer_name
next_operation_type
browser_use_operations_url
```

## 筛选规则

默认只返回：

```text
retryable = true
status = pending
retry_attempt_count < max_attempts
```

并支持按失败类型、项目和场景过滤。

## 排序规则

第一版排序：

```text
retry_attempt_count ASC
created_at ASC
```

含义：优先处理尝试次数少、等待时间更久的任务。

## next_operation_type

队列直接返回下一步操作类型，方便 Browser use 决定处理策略：

```text
missing_layer        -> retry_replace_layer_asset
selector_changed     -> retry_replace_layer_asset
asset_upload_failed  -> retry_asset_upload_and_replace
save_failed          -> retry_save_project
login_expired        -> recover_login_then_retry
其他/未知            -> retry_browser_use_operation
```

## 验收标准

- `GET /api/maitu/retry-queue` 返回 pending + retryable + 未超过 max_attempts 的任务。
- 返回项包含项目、场景、槽位、图层上下文。
- 返回项包含 `next_operation_type`。
- 返回项包含 `browser_use_operations_url`。
- 可以按 `failure_type`、`maitu_project_code`、`scene_name`、`max_attempts` 过滤。
- 达到 `max_attempts` 的任务不再出现在队列中。
- API 合约测试通过。
- 全量测试、编译检查和 SQL migration 解析通过。

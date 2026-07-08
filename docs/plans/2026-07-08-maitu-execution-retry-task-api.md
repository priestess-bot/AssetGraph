# 麦兔 Browser use 执行失败分类与重试任务 API

## 背景

上一轮已经完成 Browser use 执行结果回写：AssetGraph 可以接收一次麦兔替换方案执行后的总体状态、单槽位状态、错误信息和截图素材编号。

但只记录“失败”还不够。下一步需要让系统知道：

- 失败属于哪一类。
- 是否可以自动重试。
- Browser use 下一次应该怎么重试。
- 哪些失败需要人工补素材或人工处理。

因此本轮新增失败分类字段和重试任务表，让 AssetGraph 从“执行结果归档”升级到“可恢复执行闭环”。

## 目标

1. 在执行结果和单槽位操作结果中增加：
   - `failure_type`
   - `retryable`
   - `retry_instruction`
2. 当 Browser use 回写 retryable 的失败结果时，自动创建 `MT-RETRY-*` 重试任务。
3. 提供重试任务列表、详情和状态更新 API。
4. 保持 AssetGraph 仍然是计划、记录和调度层，实际操作麦兔软件仍由 Browser use 完成。

## 编号规范

```text
MT-RETRY-{YYYYMMDD}-{SEQ}
```

示例：

```text
MT-RETRY-20260708-000001
```

## 失败类型建议

第一批可用字符串：

```text
missing_layer          找不到麦兔图层/槽位
login_expired          麦兔登录过期
asset_upload_failed    素材上传失败
save_failed            保存项目失败
selector_changed       页面结构或选择器变化
missing_asset          AssetGraph 缺少可替换素材
manual_required        需要人工处理
unknown                未分类错误
```

## API

### 1. 回写执行结果时携带失败分类

```http
POST /api/maitu/replacement-plans/{plan_code}/execution-results
```

请求示例：

```json
{
  "executor": "browser_use",
  "execution_status": "partial_failed",
  "failure_type": "missing_layer",
  "retryable": true,
  "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后只重试该槽位。",
  "operation_results": [
    {
      "slot_code": "MT-SLOT-20260708-000001",
      "operation_type": "replace_layer_asset",
      "asset_code": "AG-IMG-20260708-000001",
      "status": "failed",
      "failure_type": "missing_layer",
      "retryable": true,
      "retry_instruction": "重新扫描麦兔场景图层树，定位 layer_8 后替换商品主图。",
      "error_message": "Browser use 未找到 layer_8。",
      "details": {
        "layer_name": "layer_8",
        "selector": null
      }
    }
  ]
}
```

返回执行结果时保留失败分类和重试字段。

### 2. 查询重试任务

```http
GET /api/maitu/retry-tasks
```

支持过滤：

```http
?plan_code=MT-PLAN-20260708-000001&execution_code=MT-EXEC-20260708-000001&status=pending&failure_type=missing_layer
```

### 3. 查询单个重试任务

```http
GET /api/maitu/retry-tasks/{retry_task_code}
```

### 4. 更新重试任务状态

```http
PATCH /api/maitu/retry-tasks/{retry_task_code}
```

请求示例：

```json
{
  "status": "in_progress",
  "retry_attempt_count": 1,
  "last_retry_execution_code": "MT-EXEC-20260708-000001",
  "result_summary": "已交给 Browser use 重新定位 layer_8。"
}
```

## 数据库变更

在 `maitu_replacement_plan_executions` 中新增：

```text
failure_type
retryable
retry_instruction
```

在 `maitu_replacement_plan_operation_results` 中新增：

```text
failure_type
retryable
retry_instruction
```

新增表：

```text
maitu_execution_retry_tasks
```

核心字段：

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
```

## 状态建议

```text
pending       等待重试
in_progress   正在交给 Browser use 重试
succeeded     重试成功
failed        重试失败
cancelled     取消重试
manual_required 需要人工处理
```

## 验收标准

- `MT-RETRY-*` 编号可生成。
- 执行结果能返回 `failure_type`、`retryable`、`retry_instruction`。
- 单槽位操作结果能返回 `failure_type`、`retryable`、`retry_instruction`。
- retryable 的失败操作会自动创建重试任务。
- 可按 plan、execution、status、failure_type 查询重试任务。
- 可查询单个重试任务。
- 可更新重试任务状态和尝试次数。
- API 合约测试通过。
- 全量测试、编译检查和 PostgreSQL migration 语法解析通过。

# 麦兔重试任务 Browser use 操作计划 API

## 背景

上一轮已经为 Browser use 执行失败增加了失败分类、是否可重试、重试指令和 `MT-RETRY-*` 重试任务。但重试任务如果只停留在记录层，Browser use 仍然需要自己理解如何从失败记录转成下一次操作步骤。

本轮目标是让 AssetGraph 直接把单个重试任务转换成 Browser use 可执行的最小化操作计划。

## 目标

1. 增加 `GET /api/maitu/retry-tasks/{retry_task_code}/browser-use-operations`。
2. 返回重试任务对应的最小化 Browser use 操作步骤。
3. 明确只重试失败槽位，不重新执行整套替换方案。
4. 保留麦兔项目、场景、图层、槽位、素材、失败类型和替换策略。
5. 根据 `failure_type` 生成更具体的 `operation_type`。

## API

```http
GET /api/maitu/retry-tasks/{retry_task_code}/browser-use-operations
```

返回示例：

```json
{
  "retry_task_code": "MT-RETRY-20260708-000001",
  "plan_code": "MT-PLAN-20260708-000001",
  "execution_code": "MT-EXEC-20260708-000001",
  "executor": "browser_use",
  "target_app": "maitu",
  "maitu_project_code": "MT-PROJ-20260708-000001",
  "scene_name": "京东空白直播间",
  "operations": [
    {
      "operation_type": "retry_replace_layer_asset",
      "retry_task_code": "MT-RETRY-20260708-000001",
      "slot_code": "MT-SLOT-20260708-000001",
      "slot_name": "商品主图",
      "scene_name": "京东空白直播间",
      "layer_name": "layer_8",
      "asset_code": "AG-IMG-20260708-000001",
      "asset_title": "胶原蛋白商品主图-白底款",
      "replacement_policy": "keep_layout",
      "failure_type": "missing_layer",
      "status": "ready",
      "instruction": "执行重试任务 MT-RETRY-...：重新扫描麦兔场景图层树...只重试槽位 MT-SLOT-...；保持原图层位置和尺寸不变，替换后保存项目。"
    }
  ]
}
```

## failure_type 到 operation_type 的映射

```text
missing_layer        -> retry_replace_layer_asset
selector_changed     -> retry_replace_layer_asset
asset_upload_failed  -> retry_asset_upload_and_replace
save_failed          -> retry_save_project
login_expired        -> recover_login_then_retry
missing_asset        -> resolve_missing_slot_asset
manual_required      -> manual_retry_required
其他/未知            -> retry_browser_use_operation
```

## 状态规则

重试任务满足以下条件时，operation 状态为 `ready`：

```text
retryable = true
status in [pending, in_progress]
```

否则 operation 状态为 `blocked`，Browser use 不应自动执行。

## 验收标准

- 存在的 retry task 返回 Browser use 操作计划。
- 返回体包含 `retry_task_code`、`plan_code`、`execution_code`、`executor`、`target_app`、`scene_name`。
- operation 包含 slot、layer、asset、failure_type、replacement_policy、instruction。
- `missing_layer` 可映射为 `retry_replace_layer_asset`。
- instruction 明确“只重试槽位”，并要求“保持原图层位置和尺寸不变”。
- 不存在的 retry task 返回 404。
- API 合约测试通过。
- 全量测试、编译检查和 PostgreSQL migration 解析通过。

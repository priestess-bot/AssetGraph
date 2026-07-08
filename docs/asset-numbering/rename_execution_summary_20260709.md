# V3 Browser-use 友好素材重命名执行结果

执行时间：2026-07-09 00:43

## 执行策略

按 V3 Browser-use 友好编号体系执行真实重命名：

```text
普通麦兔素材：MT-{TYPE}-{SEQ}_{麦兔类型}_{用途}_{主体}.{ext}
数字分身素材：DH-{ENTITY}-{SEQ}-F{FILE_SEQ}_{子类型}_{主体}_{角色}.{ext}
```

本次策略：

```text
保留重复素材
只重命名
不删除
不去重
```

## 执行文件

重命名计划：

```text
D:/AssetGraph/docs/asset-numbering/asset_rename_plan_20260709_v3_browser_use.csv
```

执行 manifest：

```text
D:/AssetGraph/docs/asset-numbering/executions/rename_execution_manifest_20260709_004238.json
```

回滚清单：

```text
D:/AssetGraph/docs/asset-numbering/executions/rename_rollback_20260709_004238.csv
```

执行结果：

```text
D:/AssetGraph/docs/asset-numbering/executions/rename_execution_result_20260709_004300.json
```

复查结果：

```text
D:/AssetGraph/docs/asset-numbering/executions/rename_verify_summary_20260709_004300.json
```

## 执行统计

| 项目 | 数量 |
|---|---:|
| 计划重命名文件 | 131 |
| 成功重命名文件 | 131 |
| 执行错误 | 0 |
| 源旧路径残留 | 0 |
| 新路径缺失 | 0 |
| 素材目录当前媒体文件 | 131 |
| 未匹配新编号文件 | 0 |

## 当前编号覆盖

| 编号前缀 | 数量 | 含义 |
|---|---:|---|
| DH-AVT | 8 | 数字分身成品相关文件 |
| DH-MDL | 58 | 模特相关文件 |
| DH-VOI | 6 | 音色相关文件 |
| MT-* | 59 | 背景/装饰/视频/模版等普通麦兔素材 |

## 重复素材保留情况

复查后仍有 8 组重复素材，共 20 个文件。

这是预期结果，因为本次策略是：

```text
保留重复素材，不做物理去重。
```

重复素材后续应通过 AssetGraph 的 `PhysicalAsset + MaituMaterialAlias + AssetRoleBinding` 模型处理。

## 验证结论

V3 重命名已完成，当前 `D:/AssetGraph/素材` 下所有媒体素材都已经改为 Browser-use 友好的编号命名格式。

旧路径全部不存在，新路径全部存在，没有覆盖冲突，没有缺失文件。

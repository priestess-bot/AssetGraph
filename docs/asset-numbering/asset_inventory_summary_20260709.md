# AssetGraph 本地素材扫描结果

生成时间：2026-07-08T17:38:05.481260+00:00

## 扫描范围

```text
D:/AssetGraph/素材
```

## 总体统计

- 素材文件数：131
- 解析异常数：0
- 重复素材组：8
- 重复素材文件数：20

## 文件类型统计

- AUD: 4
- IMG: 71
- VID: 56

## 麦兔类型统计

- 数字分身: 72
- 模版: 1
- 背景: 4
- 装饰: 26
- 视频: 28

## 麦兔分类统计

- background_image: 5
- digital_human_video: 68
- floating_sticker: 26
- product_video: 28
- voice_audio: 4

## 后续用途

本清单用于把 `D:/AssetGraph/素材` 中的本地麦兔素材导入 AssetGraph：

```text
本地素材文件 -> asset_inventory.json/csv -> assets / asset_files -> 候选素材推荐 -> 麦兔替换方案
```

JSON 中每个素材都带有 `asset_create_payload`，可直接作为后续导入 `POST /api/assets` 或 CLI 导入的基础数据。

`asset_create_payload` 同时保留两套编号：

- `asset_code`：导入 AssetGraph 后生成的全局 AG-* 编号。
- `display_code` / `local_file_code` / `entity_code`：从文件名解析出的 MT-* / DH-* 麦兔或本地素材编号。

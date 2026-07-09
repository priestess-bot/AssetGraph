# 麦兔直播间模板库

这是 AssetGraph 的麦兔直播间模板库。模板库保存的是可复用的直播间结构、图层、脚本和及格线规则；不是单张模板预览图库。

## 当前默认基准模板

- 模板编码：`MT-TEMPLATE-38336-ZHANGYU-SUMMER`
- 模板名称：`张裕夏日主题`
- 来源直播间：`38336`
- 平台：`京东`
- 角色：第一个模板；以后京东葡萄酒直播间的最低及格线
- 结构：10 个商品、38 个场景、38 段脚本、31 个唯一视觉素材、307 次图层摆放

## 文件

- `index.json`：模板库索引，可按 `default_baseline_template_code` 找到默认基准。
- `38336-zhangyu-summer-baseline.md`：人类可审阅的结构说明。
- `38336-zhangyu-summer-baseline.json`：完整结构化模板，含每个商品、场景、图层、脚本、坐标、尺寸和素材 URL。
- `38336-zhangyu-summer-blueprint-import.json`：兼容现有后端 `/api/maitu/live-room-blueprints/import-reference` 的导入 payload。

## 硬规则

1. `MT-TPL-*` / 模板预览图只作风格和结构索引，不能当背景或装饰直接插入直播间。
2. 新直播间必须按模块搭建：背景/底图、品牌标题与 logo、前景/装饰、商品贴片/动图、数字人、商品特写视频、直播脚本。
3. 本模板的及格线是多商品、多场景、逐商品脚本；不能退化成单背景 + 单脚本。
4. 真实麦兔执行只能到草稿/自动保存边界，禁止点击正式开播。

## 后端导入命令（后端和数据库启动后）

```bash
cd D:/AssetGraph
./backend/.venv/Scripts/python - <<'PY'
from pathlib import Path
import json, urllib.request
base = 'http://127.0.0.1:8000'
payload = json.loads(Path('docs/maitu-live-room-templates/38336-zhangyu-summer-blueprint-import.json').read_text(encoding='utf-8'))
req = urllib.request.Request(
    base + '/api/maitu/live-room-blueprints/import-reference',
    data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
print(urllib.request.urlopen(req).read().decode('utf-8'))
PY
```

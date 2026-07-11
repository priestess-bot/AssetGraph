# AssetGraph 剧本生成与自动搭建质量契约

## 1. 定位

剧本生成是 AssetGraph 内容驱动自动化的 Stage 0，不再要求用户先提供一篇完整成稿。

完整链路：

```text
结构化商品事实 / 已核验活动信息 / 直播目标
  -> 纯口播剧本生成与质量门禁
  -> 场景计划
  -> 场景素材需求
  -> AssetGraph 真实素材检索与选择
  -> 素材缺口报告
  -> 场景布局
  -> BuildPlan
  -> Browser-use 麦兔草稿搭建
  -> Observe 回读验证
```

剧本段落是下游自动化的内容事实源。场景目标、商品关键词、背景主题、辅助画面、促单贴片和写入麦兔的脚本文本都必须追溯到剧本生成结果，而不是从参考模板反向拼文案。

## 2. 当前实现

### 2.1 生成剧本

```http
POST /api/maitu/livestream-script-drafts
```

输入包括：

- 直播标题、平台、目标时长和是否24小时循环；
- 主播人设提示；确定性基线目前用“直接/判断/利落”等指令切换开场表达，后续LLM提供器必须继续受同一质量门禁约束；
- 每个商品的定位；
- 已核验商品事实；
- 口感、使用场景、选购判断和异议处理；
- 已核验促销信息与未核验促销信息；
- 素材检索关键词。

输出包括：

- `spoken_script`：主播可直接口播的纯文本；
- `sections`：有内容归属、场景目标、关键词和估算时长的结构化段落；
- `quality_report`：范围、时间、重复、时长素材充分性等质量结果；
- `scene_plan_payload`：可直接进入下游场景/素材链路的输入；
- `manual_review_required`：是否需要人工复核。

### 2.2 一次性运行完整链路

```http
POST /api/maitu/script-driven-build-pipelines
```

阶段固定为：

```text
script_generation_and_quality_gate
script_scene_plan
script_asset_needs
script_asset_selections
script_asset_gap_report
script_layout_plan
script_layout_build_plan
```

响应同时返回每个阶段的可审计产物。`build_plan.operations` 中的 `write_script.script_text` 必须与生成稿的 `sections[].script` 一致。质量复核状态会下沉到每个 scene；即使调用方绕过聚合接口、逐个调用素材需求/选材/布局/BuildPlan接口，也不能把待复核剧本重新变成可执行计划。

## 3. 硬性质量边界

### 3.1 只使用已核验事实

- `verified_facts` 和 `verified_promotion_claims` 可以进入口播；
- `title` 只作计划元数据和检索上下文，不能直接进入主播口播，避免内部版本名、时段或范围描述泄漏；
- `unverified_promotion_claims` 不进入口播，记录在 `dropped_unverified_claims`；生成完成后还会反查整篇口播和检索关键词，即使未核验促销被塞入选购建议、定位、事实、异议处理或素材关键词，也会删除对应内容并触发人工复核；
- 只有能追溯到 `verified_promotion_claims` 的优惠、赠礼、满减、领券、折扣、限量等促销语义可以保留；
- 不补造价格、赠品、库存、排名、酒款工艺或商品范围。

### 3.2 不推断直播间商品总数

`catalog_total_verified=false` 时，不得出现“所有商品”“直播间就这几款”“把八款缩到两款”等范围断言。即使提交了多个商品，生成器也只说明当前正在讲解的商品，不把输入条数解释为直播间商品总数。

### 3.3 不凑目标时长

生成器不会为了达到 `target_duration_minutes` 重复卖点、改写同义句或机械增加FAQ。句号、问号、叹号、分号和逗号边界上的重复子句都会先去重，再重新计算中文字符数和预计时长；`padding_free` 由清洗后的实际重复检测结果计算，不再是固定值。已核验素材不足时：

```text
quality_report.material_sufficiency_status
  = insufficient_verified_material_for_target_duration
manual_review_required = true
```

下游仍会返回可审阅的场景、素材和BuildPlan产物，但：

```text
build_plan.can_execute = false
build_plan.blocked_reasons includes script_quality_review_required
all mutating operations use status = blocked_script_quality
```

### 3.4 24小时循环口播

`always_on_24h=true` 时：

- 不使用早上、晚上、今天、周末、下播、告别等时间绑定语句；
- 结尾只做短重入，不重新复述商品卖点；
- 主播口播和内部核验说明物理分离；
- 默认包含适量饮酒、未成年人禁酒和酒后禁驾提醒。

### 3.5 只搭草稿，不授权开播

无论剧本质量是否通过：

```text
ready_for_go_live = false
```

剧本管线只为麦兔草稿搭建提供计划，不构成“正式开播”授权。

## 4. 示例

```json
{
  "script_request": {
    "title": "张裕双品循环直播稿",
    "platform": "京东",
    "target_duration_minutes": 1,
    "always_on_24h": true,
    "catalog_total_verified": false,
    "products": [
      {
        "product_name": "品酒大师PRO",
        "positioning": "花果香和清爽酸度",
        "verified_facts": [
          "使用蛇龙珠酿造",
          "橡木桶贮藏九个月以上"
        ],
        "tasting_notes": ["紫罗兰", "成熟樱桃", "清凉草本气息"],
        "scenarios": ["搭配烤鸭", "搭配有油脂的肉菜"],
        "selection_guidance": "喜欢清爽风格的朋友可以重点看品酒大师PRO",
        "objection_response": "先按口味选择，不按等级盲目上探",
        "asset_keywords": ["品酒大师PRO", "蛇龙珠", "紫罗兰"],
        "verified_promotion_claims": [],
        "unverified_promotion_claims": ["前二十名赠送礼品"]
      }
    ]
  },
  "build_mode": "strict",
  "target_live_room_id": "draft-room-001"
}
```

## 5. 演进规则

当前 `jd_wine_livestream_script_rule_v1` 是可测试、可离线运行的确定性基线。后续可接入LLM写作/润色提供器，但提供器必须复用同一输入输出契约和质量门禁，且不能绕过以下约束：

- 事实白名单；
- 商品范围安全；
- 未核验促销隔离；
- 无凑时长；
- 纯口播与运营备注分离；
- 剧本段落与场景/素材/BuildPlan全链路可追溯；
- 未经明确授权不得正式开播。

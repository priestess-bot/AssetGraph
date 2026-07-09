# 麦兔参考直播间蓝图初稿：京东空白直播间-0707-1352

## ReferenceRoomProfile

- profile_code: `MT-REF-20260709-39826`
- source: `browser_use_observe`
- URL: `https://live2.maituai.com/LiveRoom?liveRoomId=39826`
- liveRoomId: `39826`
- room_name: `京东空白直播间-0707-1352`
- platform: `京东`
- active_scene: `场景01`
- logged_in: `True`

## LiveRoomBlueprint

- blueprint_code: `MT-BP-20260709-39826`
- room_type: `reference_rebuild`
- status: `draft`
- reference_profile_code: `MT-REF-20260709-39826`

## 场景蓝图

| 场景 | 类型 | 状态 | 参考页激活 | 已观测图层数 |
| --- | --- | --- | --- | --- |
| 场景01 | 讲品 | 已激活 | 是 | 7 |
| 场景02 | 讲品 | 已激活 | 否 | 0 |
| 场景03 | 讲品 | 已激活 | 否 | 0 |
| 场景04 | 讲品 | 已激活 | 否 | 0 |
| 场景05 | 讲品 | 已激活 | 否 | 0 |
| 场景06 | 讲品 | 已激活 | 否 | 0 |
| 场景07 | 讲品 | 已激活 | 否 | 0 |

## 当前激活场景图层蓝图

| 图层 | 角色 | 所需分类 | 接受类型 | 替换策略 |
| --- | --- | --- | --- | --- |
| 前景 | foreground_frame | floating_sticker | IMG | keep_layout |
| 品酒大师(PRO） | digital_human | digital_human_video | IMG, VID | keep_layout |
| png | decoration | floating_sticker | IMG | keep_layout |
| gif-01 | animated_sticker | floating_sticker | IMG | keep_layout |
| 标题+logo | logo_title | floating_sticker | IMG | keep_layout |
| 珠珠-亲和 | digital_human | digital_human_video | IMG, VID | keep_layout |
| 微信图片_20260618221607_11_15 | background | background_image | IMG | keep_layout |

## 脚本块

| 序号 | 场景 | 内容预览 |
| --- | --- | --- |
| 1 | 场景01 | 大家好，今天给大家介绍张裕解百纳品酒大师系列。从适合第一次喝红酒的PRO，到品质旗舰MASTER，再到高端礼赠SUPER，一分钟带大家了解三款酒的区别。如果你第 |

## 安全规则

- 默认不点击正式开播
- 真实执行前必须通过 Browser-use preflight 校验当前 URL、直播间、场景和图层
- 每次只执行一个小而可验证的 UI 操作，并回写截图或页面状态证据

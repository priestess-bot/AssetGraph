# 旧前端退役记录

> 范围：浏览器入口与前端资源。`/api/maitu/*` 和 `/api/live-research/*` 领域 API 不在退役范围内。
> 状态：2026-07-28 已完成一次性切换。

## 当前入口

唯一产品入口为 `/console/`。一级业务路由如下：

| 业务区 | Console 路由 |
| --- | --- |
| 业务概览 | `/console/` |
| 素材库 | `/console/assets` |
| 直播模板 | `/console/templates` |
| 知识库 | `/console/knowledge` |
| 内容项目 | `/console/projects` |
| 运营分析 | `/console/operations` |
| 效果学习 | `/console/learning` |

直播间、成片和交付默认从内容项目进入；保留 `/production/live-rooms`、`/production/videos`、`/production/releases` 作为统一 Console 的业务深链。

## 退役结果

- [x] Vite 只构建一个 Console 入口。
- [x] 后端只挂载统一 Console，不再挂载 `/maitu/` 和 `/live-research/` 静态资源。
- [x] 旧麦兔、直播研究、治理、排播、实体检查器和旧生产页面已从源码删除。
- [x] 麦兔和直播录屏领域 API、Worker、数据库对象与已有数据保持不变。
- [x] 旧页面专属样式和演示数据已删除。
- [x] 内部导航、任务、通知和全局搜索均指向统一业务路由。

## 运维说明

旧 `/maitu/` 和 `/live-research/` 浏览器地址不再保证可访问。部署前应更新书签、内部文档和反向代理规则；不得把旧路径代理到过期静态文件。需要回溯历史能力时查询 Git 历史，不恢复第二套正式前端。

回滚仅允许回滚统一 Console 的代码版本，不得通过重新挂载旧静态资源形成双入口。领域 API 和 canonical 数据不随前端回滚重写，也不自动重放任何写命令。

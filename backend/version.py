"""应用版本号的唯一来源。

任何需要展示或比对版本的模块都从这里取，不要再写字面量：
- 后端 `app.version`、`X-API-Version` 响应头、`/api/health`、`/api/meta`
- 备份 / 迁移 / 分享包的清单
- 导出到 MySQL / PostgreSQL 的 `_wb_migration_state`
- 前端静态资源的 `?v=` 查询参数（由 `/api/meta` 与 HTML 注入使用）

改版本只改这里一个地方。
"""
from __future__ import annotations

# 主版本：功能/架构变化时递增（语义化：主.次.补丁.构建）
VERSION = "0.9.5.7"

# 静态资源缓存键。默认跟主版本一致；只改前端资源、不动后端时可以让它单独前进。
ASSET_VERSION = VERSION

# 打包格式版本：备份 / 迁移 / 分享包的 zip 结构版本，与产品版本解耦。
FORMAT_VERSION = 1



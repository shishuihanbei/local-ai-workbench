# 本地 AI 工作台 · 架构与开发手册

> 用途：这份文档同时是**现状说明书**和**重新架构的设计基线**。任何人（包括另一个 AI 模型）读完它，应该能：
> 1. 知道每个功能在哪里、怎么跑起来的；
> 2. 按既有流程改代码、跑测试、发版本；
> 3. 按第 10–11 章做重构，而不破坏现网。
>
> 文档基准：`main` 分支最新提交（2026-11-26），测试 **242 passed**（另有 5 条浏览器交互冒烟，`WORKBENCH_E2E=1` 时单独跑，约 17 秒），API 版本 `0.8.5.0`。凡是数字（端点数、表数、行数）都是实测值，改动后请同步更新本文。

---

## 1. 项目定位与设计前提

工作台是一个**单机、内网、自带账号体系的 AI 门户**，不是通用云平台。所有设计取舍都来自这四条前提：

| 前提 | 含义 | 带来的约束 |
|---|---|---|
| 单进程部署 | 一个 uvicorn 进程 + 一个事件循环 | 天然适配 SQLite 单写者；不能直接加 `--workers` |
| 数据不出内网 | 会话、文档、密钥都在本机 `data/` | 不做多租户隔离，不做跨机共享存储 |
| 本地模型优先 | llama.cpp 由程序自己拉起和托管 | 单模型串行，切换要重启进程 |
| 管理员即部署者 | 装软件的人和管理员是同一个人 | 控制台承担"安装向导"职责，配置项必须可 GUI 修改 |

**因此**：数据库换 PG 的唯一动机是"要多实例"，不是"性能不够"；模型换云端或 vLLM 的唯一动机是"要并发"，不是"本地跑不动"。

---

## 2. 现状架构（AS-IS）

### 2.1 运行时拓扑

```
浏览器（用户端 /console 控制台 / 共享页）
        │  HTTPS 或 局域网 HTTP，Bearer Token / Cookie 会话
        ▼
┌─────────────────────────────────────────────┐
│ uvicorn 单进程（run.py → backend.main:app）  │
│  ├─ 中间件：CORS、安全响应头、异常兜底        │
│  ├─ 26 个 router 挂载（25 个文件），266 条路径 / 333 个操作 │
│  ├─ 46 个 service（业务逻辑，无状态为主）      │
│  ├─ logbus 后台协程：批量把调用记录写 requests │
│  └─ 共享 SQLite 连接（异步锁串行化）          │
└───────┬──────────────┬──────────────┬────────┘
        │              │              │
   data/workbench.db  llama-server  外部 OpenAI 兼容服务
   （WAL，48 张表）    （子进程，串行） （供应商 / 算力池节点 / 平台模型）
```

模型层有四种来源，路由优先级见 6.3：
`算力池 → 可达的平台模型（vLLM/Ollama/LM Studio）→ 供应商名单 → 本地 llama.cpp`。

### 2.2 分层与依赖规则（现状）

只有三层，且**没有仓储层**：

```
routers/   —— HTTP 契约：参数校验、鉴权、拼 SQL 或调 service、返回 JSON
services/  —— 业务逻辑：可被多个 router 复用，允许直接 import db 与 config
db.py      —— 数据访问：建表、迁移、fetch_all/fetch_one/execute/executemany/audit
```

依赖方向是单向的：`routers → services → db/config`。反向依赖（service 调 router）是不允许的，目前也没有出现。`pipeline.py` 是横切机制（钩子），`logbus.py` 是异步写队列，两者不依赖业务模块。

> 现状的最大问题：**部分 router 直接写 SQL**（如 `chat.py` 里大量 `INSERT INTO messages ...`），导致"业务规则"散落在 HTTP 层，换表结构或换数据库时要改路由文件。这是第 10 章要解决的第一个问题。

### 2.3 目录与模块地图

```
workbench/
├── run.py                 启动入口：读配置 → 设定 WORKBENCH_PORT → uvicorn.run
├── start.ps1 / start.sh   一键启动：建 venv、装依赖、后台拉起、打印访问地址
├── stop.ps1 / restart.ps1 停止 / 重启
├── backend/
│   ├── main.py            FastAPI 装配：lifespan、中间件、挂载、健康检查、静态页
│   ├── config.py          DEFAULTS（约 70 个键）+ load_config/save_config
│   ├── db.py              建表 SCHEMA / KB_SCHEMA、23 个版本化迁移、共享连接、审计
│   ├── security.py        口令、会话、Token、CSRF、权限装饰器、登录失败限流
│   ├── pipeline.py        生成前后钩子（before_render / before_call / after_call）
│   ├── logbus.py          调用记录（requests/spans）批量落库
│   ├── routers/           25 个模块，见附录 A
│   ├── services/          46 个模块，见附录 B
│   └── console/           管理控制台（index.html + core/models/session/tabs/boot + panels/*.js + console.css，静态挂载）
├── frontend/              用户端（index.html + 12 个域脚本 + app.css + app.ui.css + 共享页）
├── tests/                 31 个文件（含 conftest）：30 个测试模块，219 条用例 + 5 条浏览器冒烟（默认跳过）
├── docs/                  本文档与后续设计说明
├── data/                  运行期数据（见 2.5）
├── models/                本地 GGUF
├── platforms/             本地推理平台安装目录（llama.cpp 等）
└── .github/workflows/     ci.yml（3.10/3.12 矩阵跑 pytest + 前端脚本检查 + e2e 浏览器冒烟）、docker.yml（构建+冒烟+推 GHCR）
```

### 2.4 请求链路

**普通 JSON 请求**

```
HTTP → CORS/安全头中间件 → 路由函数
     → Depends(current_user) 解析 Bearer 或 Cookie 会话（security.session_user）
     → Depends(admin_user) 额外校验角色与 admin_role 权限集
     → 业务逻辑（service 或直接 SQL）
     → JSONResponse（错误统一抛 HTTPException(status, detail)）
```

**流式对话（`POST /api/chat/stream`，最关键的一条链路）**

```
1. 校验：消息非空 / 附件 ≤5 / 配额 quota.check / 模型权限 access.can_use
2. 内容安全：moderation.guard_input（命中则 400）
3. 路由决策：routing.resolve → {provider, base, key, model, strategy, pool_id...}
4. 落库：新建或校验会话 → 写入 user 消息 → 更新会话时间
5. 组装上下文：_build_context（历史消息、知识库、资料库、记忆、技能、附件、联网）
6. 钩子：pipeline.run("before_call")，允许改写 base/key/model（缓存、灰度）
7. 返回 StreamingResponse(event_stream)：
   ├─ 准入控制 admission.enter(用户)  ← 全局信号量 + 每分钟限流
   ├─ 本地则 model_usage.begin(模型, 用户)  ← 切换保护
   ├─ 逐行转发上游 SSE，翻译成 {type: meta|delta|reasoning|error|done}
   ├─ 输出过滤器 moderation.StreamFilter（跨块敏感词）
   └─ finally：落 assistant 消息、生成文档、写 requests/spans、释放准入与占用
```

关键约束：**流一旦开始就无法改 HTTP 状态码**，所以准入拒绝、上游报错都只能以 `data: {"type":"error"}` 事件下发给前端，HTTP 仍是 200。这是排查"聊天没反应"类问题的前提知识。

### 2.5 数据层

- 文件：`data/workbench.db`，WAL 模式，`foreign_keys=ON`。
- 48 张业务表（清单见附录 C），按域分为：身份权限、对话内容、模型路由、知识与资料、协作组织、运维审计。
- 迁移：`db.py` 的 `apply_migrations()` 按 `schema_migrations.version` 顺序执行，当前 23 个版本；新增字段/表一律通过新版本迁移，**不改历史迁移函数**。
- 访问方式：`fetch_all/fetch_one/execute/executemany` 走**进程内一条共享连接**，由 `asyncio.Lock` 串行化；`connect()` 仅用于建库、迁移、维护类长任务。
- 一致性维护：`database_admin.health()` 做 `integrity_check` + `foreign_key_check`，异常可用 `repair_foreign_keys()` 清理孤儿行（先自动快照）。

### 2.6 运行期数据目录

```
data/
├── workbench.db (+ -wal/-shm)   主库
├── config.json                  运行配置（控制台改的都在这里）
├── secret.key                   AES-GCM 主密钥（供应商 Key、连接密码加密用）
├── branding/                    Logo 与品牌图
├── uploads/                     聊天附件原文件
├── audio/                       TTS 生成的 mp3
├── exports/                     导出的 CSV / SQL
├── backups/                     整机备份、迁移包
├── database_backups/            数据库中心快照
├── migrations/                  整机迁移包
├── installers/                  离线安装包（llama.cpp zip / ollama-windows-amd64.zip）
├── shares/                      网站分享包
└── logs/                        app.log、llama.log
```

程序侧（`BASE_DIR` 下，可整体搬走）：

```
platforms/
├── llama.cpp/                   llama.cpp 程序（llama-server）
├── ollama/                      Ollama 便携版（ollama.exe + lib/），模型在 ollama/models
└── .downloads/                  平台安装包缓存（ollama-windows-amd64.zip 等）
```

- `platforms_dir` 可从控制台「部署 · 存储位置」改；`ollama_dir` 不落配置，始终 = `<platforms_dir>/ollama`，只有 `WORKBENCH_OLLAMA_DIR` 能覆盖。
- Ollama 启动时显式传 `OLLAMA_MODELS=<ollama_dir>/models`，所以 `ollama pull` 的模型不会跑去 `%USERPROFILE%\.ollama`。
- - 系统目录里已装 Ollama 的机器：`detect()` 返回 `managed=false`，卡片显示系统程序目录与它真实的模型目录，并提供「装到工作台目录」（`deploy?force=1` 走便携版）和「迁移旧模型」（`/api/system/local-platforms/ollama/adopt-models`）。

---

## 3. 功能清单（按业务域）

每个域给出：职责、关键实现文件、对外入口。端点全量清单见附录 A。

### 3.1 身份与权限

- 账号：初始化管理员（`/api/auth/setup`）、登录、注册（可关）、改密、会话列表与踢出。
- 登录方式可插拔：用户名口令、手机/邮箱验证码（`otp.py`、`auth_delivery.py`）、QQ/微信 OAuth（`auth_oauth.py`），由 `auth_providers.py` 注册表统一描述，控制台可配。
- 一个账号多身份：`auth_identities` 表，`provider + provider_uid` 唯一。
- 权限三层：`users.role`（admin/user）+ `admin_roles.permissions`（管理员细分权限）+ `users.allowed_models`（模型白名单）。
- 实现：`security.py`（`current_user` / `admin_user` / `permission_for_path` / `check_csrf`），路由 `auth.py`、`users.py`、`auth_admin.py`。

### 3.2 对话与生成

- 会话 CRUD、清空、置顶、重命名；消息带 reasoning、tokens、meta（附件/技能/联网/记忆/生成文件）。
- 流式生成、重新生成、停止、TTS 朗读。
- 上下文组成：最近消息 + 知识库片段 + 资料库文档 + 长期记忆 + 技能提示词 + 附件正文 + 联网摘要。
- 实现：`routers/chat.py`（770 行，最复杂的一个路由）、`services/attachments.py`、`kb.py`、`library.py`、`memory.py`、`skills.py`、`websearch.py`、`docgen.py`。

### 3.3 模型与路由

- 模型清单 52 条内置（九大分类），支持下载 GGUF、上传自有 GGUF、独立引擎仓库下载、删除、改别名。
- 下载来源按引擎分开：llama.cpp 走 GGUF 直链（`models_dir/<filename>`）；Ollama 走 registry tag（`ollama pull <tag>` → `platforms/ollama/models` 的 blobs/manifests）；vLLM/SGLang/ComfyUI 等独立引擎整仓库下到各自目录。同一个模型在多平台下各存一份、格式不互通（`backend/ollama_tags.py` 存“内置 key → Ollama tag”映射，模型列表每条带 `ollama_tag/ollama_ready/ollama_pulled`）。
- 本地 llama.cpp 生命周期：安装 → 加载 → 卸载 → 切换（切换有"别人正在生成"保护）。
- 平台卸载：`POST /api/system/local-platforms/{key}/uninstall` → `platform_deploy.uninstall()`，先停工作台拉起的进程（Ollama serve / llama-server）与端口，再删 `platforms/<key>` 程序、`lib` 与该平台的便携包缓存，**保留** `platforms/ollama/models` 与 `data/installers/`；系统安装的平台（`managed=false`）拒绝并提示手动卸载。
- Ollama 拉模型：`POST /api/system/local-platforms/ollama/pull` 走 Ollama 的 `/api/pull` 流式接口，进度写进 `platform_deploy.PULL`，`GET` 同路径轮询，完成后 `platform_models.invalidate()` 让下拉立刻刷新。
- 平台模型：已勾选且健康的外部 OpenAI 兼容服务，自动把 `/v1/models` 暴露到前端下拉。
- 供应商与路由：`providers`（云端 Key、价格）、`routes`（策略与 fallback），`routing.resolve` 做最终决策。
- 实现：`routers/models.py`、`services/llama.py`、`platforms.py`、`platform_models.py`、`routing.py`、`model_usage.py`、`access.py`。

### 3.4 知识库与资料库

- 共用 `kb_docs` 表，靠 `module` 字段区分 `kb`（知识库）和 `library`（资料库），靠 `scope` 区分 public/personal。
- 知识库：切块 + FTS5 全文检索（无 fts5 退化为 LIKE），`kb_top_k` 控制注入条数。
- 资料库：整篇文档按需选用，受 `library_max_docs` / `library_max_chars` 限制。
- 附件自动入库：聊天上传的可读文件进入用户个人资料库。
- 实现：`services/kb.py`、`library.py`、`attachments.py`，路由 `kb.py`、`library.py`。

### 3.5 内容安全

- 输入拦截 + 输出流式替换/拦截，敏感词可分组、可批量导入，命中写 `moderation_hits`。
- 开关与动作（block/replace/warn）在控制台配置。
- 实现：`services/moderation.py`，接入点在 `chat.py` 和 `/v1/chat/completions`。

### 3.6 协作与组织

- 智能体（agents，带专属提示词与模型）、小队（squads，成员 + 智能体 + 共享会话）、公告、服务台工单、会话分享（token 快照）。
- 用户组与管理员角色（部门树、leader、排序）。
- 实现：`services/collab.py`，路由 `collab.py`、`users.py`。

### 3.7 工作台与定时任务

- 工作台模板（快捷入口、插件、技能）、分享链接、当前激活模板。
- 定时任务：频率（once/daily/weekly/monthly）、到点执行、运行记录、可联网。
- 实现：`routers/workbench.py`、`services/scheduler.py`、`front_features.py`。

### 3.8 文档生成与保留

- 把模型输出的 Markdown 转成 Word/Excel/PPT/PDF/文本，存 `generated_files`，返回下载链接。
- 保留期按 `generated_file_retention_days`，到期物理删除，前端展示剩余时间。
- 实现：`services/docgen.py`（990 行）、`retention.py`。

### 3.9 运维与部署

- 硬件探测、llama.cpp / 平台一键部署、独立引擎 pip 安装与进度。平台程序与模型统一落在 `platforms/`：llama.cpp → `platforms/llama.cpp`；Ollama 便携版 → `platforms/ollama`（模型 `platforms/ollama/models`，下载缓存 `platforms/.downloads`）；已系统安装的 Ollama 可一键接管或迁移模型。部署卡上的「卸载」只删工作台自己装进去的程序与缓存，留着用户 pull 的模型和 `data/installers` 的安装包。
- 开机自启、桌面快捷方式、内网穿透（cloudflared）、网络诊断。
- 备份/恢复/整机迁移/网站分享包、日志查看、系统设置。
- 实现：`services/installer.py`、`platform_deploy.py`、`engine_install.py`、`autostart.py`、`shortcuts.py`、`tunnel.py`、`backup.py`、`netinfo.py`，路由 `system.py`（43 个端点，最大的运维入口）。

### 3.10 数据库中心

- 浏览表/字段/索引/外键，单行增删改、CSV 导出、只读 SQL 控制台。
- 外部 MySQL/PG/SQLite 连接管理（密码 AES-GCM 加密）、连接串解析。
- 一键迁移到外部库（建表、索引、外键、分批复制、逐表行数校验、进度与历史）。
- 健康检查（完整性、外键、空闲页、文件大小）、VACUUM、孤立外键修复、一致性快照。
- 实现：`services/database_admin.py`（1791 行，全项目最大的 service），路由 `database.py`。

### 3.11 可观测

- 每次生成落一条 `requests`（33 列：命中、耗时、ttft、token、成本、路由决策、提示词哈希），并附 `spans`（检索/模型两段）。
- 独立 `audit_logs` 记录管理员动作（谁、对什么、什么时候、IP、成功失败）。
- 实现：`logbus.py`、`db.audit`，控制台「概览」「调用记录」「审计日志」三页。

### 3.12 对外 API

- `/v1/models` 与 `/v1/chat/completions`（OpenAI 兼容），用用户自建 API Key（`apikeys.py`，只存哈希）。
- 同样走路由、内容安全、配额、准入、调用记录。

### 3.13 品牌与前端门面

- Logo、登录文案、页脚、备案号、水印，全部存配置；登录页与用户端实时读取。
- 实现：`services/branding.py`、`routers/branding.py`、`front_features.py`。

---

## 4. 前端与控制台

### 4.1 用户端 `frontend/`

| 文件 | 行数 | 职责 |
|---|---|---|
| index.html | 766 | 页面骨架、侧栏、聊天区、设置弹层 |
| core.js | 300 | 状态 `S`、`$ / $$ / esc / api / toast` 等基础工具、主题偏好 |
| auth.js | 412 | 登录 / 注册 / 初始化、启动引导 `boot` |
| models.js | 281 | 模型下拉、模型切换与加载保护 |
| skills.js | 260 | 技能、前台功能开关与图标 |
| attachments.js | 93 | 附件上传、OCR 状态与预览 |
| conversations.js | 211 | 会话列表、新建 / 重命名 / 删除 |
| messages.js | 274 | 消息渲染、Markdown、推理折叠、文件卡片 |
| generation.js | 248 | 流式生成、停止 / 重生成、排队与错误 |
| settings.js | 999 | 设置：账号、知识库、资料库、选择器、API、对话、数据、输入布局 |
| events.js | 370 | 全局事件分发 `bindEvents` |
| collab.js | 265 | 伙伴、小队、公告、工单、对话分享 |
| workbench.js | 1197 | 工作台模板、定时任务、抽屉；末尾 `bindEvents()` / `boot()` |
| app.css | 1406 | 基础样式与主题变量 |
| app.ui.css | 578 | 新版视觉层 |
| share.html / share.js | 38 / 19 | 会话分享只读页 |
| workbench-share.html / .js | 53 / 92 | 工作台模板分享页 |

代码组织按域分文件（0.8.3.0+）：原 `app.js` 的 IIFE 包裹已去掉，12 个脚本共享同一全局词法作用域，按 `core → auth → … → workbench` 顺序加载；新增功能放进对应域文件，不要另起体系。

### 4.2 管理控制台 `backend/console/`

| 文件 | 行数 | 职责 |
|---|---|---|
| index.html | 2780 | 31 个 tab 的页面骨架，底部按顺序加载 13 个脚本 |
| core.js | 247 | 全局状态 `S`、`api / esc / toast / confirm`、登录与外壳、品牌水印、导航与权限 |
| models.js | 724 | 硬件、平台安装、模型清单与引擎、开机自启、桌面快捷方式 |
| session.js | 370 | `loadAll` / `switchTab`、全局事件入口、登录提交 |
| tabs.js | 1208 | 管理页签框架（M0–M2）、页标题 `TITLES` 与使用说明 `PAGE_TUTORIALS` |
| panels/observe.js | 257 | 概览、调用记录、供应商、路由 |
| panels/people.js | 821 | 用户与模型权限、登录方式、API Key |
| panels/content.js | 1215 | 本地前端与穿透、知识库、网站分享 |
| panels/data.js | 1692 | 数据库中心、表管理、SQL 控制台、连接、备份与迁移 |
| panels/cluster.js | 301 | 多机算力池、自定义技能 |
| panels/prompts.js | 473 | 提示词中心 |
| panels/ops.js | 670 | 审计日志、协作套件、联网检索、附件解析 |
| panels/front.js | 541 | 提示词交互、前台功能与图标库、页面输入事件 |
| boot.js | 21 | 启动引导，**必须最后加载**（首个 await 之后会调用各面板渲染） |
| console.css | 1921 | 控制台样式 |

拆分规则（0.8.3.0+）：只按行区间切片，不改一行代码，因此行为与单文件时期完全等价；所有文件共享同一个全局词法作用域，函数声明可跨文件互相调用，但 `const/let` 的初始化顺序按加载顺序，新增文件不要插到 `core.js` 之前。

31 个 tab：概览、调用记录、用户、合作伙伴、小队、公告、工单、会话分享、模型、供应商、路由、技能、提示词、智能体、知识库、资料库、记忆、机构、前台功能、内容安全、登录方式、API、网络、联网检索、附件解析、部署、算力池、备份、审计、数据库、网站分享。

**事件模型**：`document.addEventListener("click")` 单入口分发，靠 `el.id` 或 `el.closest("[data-xxx]")` 判断；每个 tab 切换时整体重渲染对应 DOM。0.8.3.0+ 起单文件巨石已按页签拆成 13 个文件（见 T1）：改某个页只动 `panels/` 下对应那一个文件。

### 4.3 版本与缓存

版本只有一个来源：`backend/version.py` 的 `VERSION` 与 `ASSET_VERSION`。

- `/api/health`、`/api/meta`、`X-API-Version` 响应头、OpenAPI `info.version`、备份/迁移/分享包清单、导库元数据 `_wb_migration_state` 全部读这个常量。
- 资源版本不写死在 HTML：`backend/console/index.html` 与 `frontend/*.html` 里写 `?v=__ASSET_VERSION__` 占位，后端返回 HTML 时替换（`main.py: render_page()`）。`/console/`、`/console`、`/`、`/index.html`、`/chat/<id>`、`/share/<token>`、`/wb/<token>` 都走注入。
- 升级只改 `version.py` 一处：后端版本、页面资源缓存键、`/api/meta.asset_version` 同步变化。只改前端资源、不动后端时，把 `ASSET_VERSION` 写成比 `VERSION` 更细的值（如 `0.8.3.0.1`）。
- 静态资源本身仍由 `StaticFiles` mount 提供，注入只影响入口 HTML。

历史坑：之前 `main.py` 0.8.1、资源 0.8.2.x、备份清单 0.7.73 三套数字并存，用户报"改了没生效"多半是 HTML 与资源版本错位。

### 4.4 错误码与前端提示

所有错误响应都带 `code`，前端按码分支，不比对中文文案。

- 机制：`backend/errors.py` 提供 `APIError` 与 `DEFAULT_CODE_BY_STATUS`；`main.py` 注册 `StarletteHTTPException`、`RequestValidationError`、`Exception` 三个处理器，统一输出 `{detail, code, ...extra}`。
- 兼容：333 处已有的 `raise HTTPException(status, "中文")` 不用改，自动拿到状态码对应的默认码；前端读 `detail` 的旧写法继续有效。
- 结构化错误（如模型占用 409）保持 `detail` 为对象，顶层再补一份 `code`，前端既能读 `detail.code` 也能读顶层 `code`。
- 需要前端特殊处理的错误用 `raise APIError(429, "…", RATE_LIMITED, extra={"retry_after": 60})`，`extra` 平铺进响应体。
- 控制台 `api()` 与用户端 `errorText()` 都能解析字符串、校验数组、结构化对象；`Error` 上带 `status` 与 `code`。
- `/v1/*` 保持 OpenAI 错误外壳 `{"error": {"message", "type", "code"}}`，不套本项目的 `{detail, code}`。

---

## 5. 关键流程详解

以下六个流程覆盖了 80% 的故障面。改代码前先在这里找到对应的"正确行为"。

### 5.1 登录与会话

```
POST /api/auth/login
  → login_blocked(ip, username)：10 分钟窗口内失败 5 次即锁定 15 分钟（内存计数，重启清零）
  → verify_password（pbkdf2）
  → create_session：生成随机 token，库里只存 sha256，返回 Cookie(session) + csrf
  → 前端后续写操作带 X-CSRF-Token（check_csrf）
登录态另有一条并行通道：Authorization: Bearer <token>（create_access_token，默认 24h），
给 API/脚本用；user_from_any_token 让两条通道在同一个 Depends 里共存。
```

要点：会话 72 小时（`session_hours`）、令牌 24 小时（`token_hours`）；踢人 = `revoke_session` / `revoke_user_sessions`；Cookie 缺失但 Bearer 存在时不强制 CSRF。

"记住账号"只写 `localStorage`（用户端 `wb_last_username` / `wb_remember_username`，控制台 `wb_console_username` / `wb_console_remember`），不存密码；`showAuth()` / `showLogin()` 先 `reset()` 再回填，所以密码永远是空的。控制台只有在 `setupMode`（库里还没有管理员）才预填 `admin`，并在描述里写明"这是即将创建的第一个管理员"。

控制台与用户端同源（`/` 与 `/console/`），所以**复用同一个 cookie 会话**：`boot.js` 先 `GET /api/auth/me` 判身份，cookie 有效且角色是 admin 就直接进控制台，只在 401 或非管理员时才弹登录页（后者在提示里写明当前账号不是管理员）。只有 localStorage 令牌的旧浏览器仍走 Bearer 分支；`core.js` 的 `api()` 在无令牌时自动带 `X-CSRF-Token`（取 `wb_csrf`），因此登出、保存这类写操作在纯 cookie 会话下也合法。用户端"管理控制台"按钮与账号行并排放在侧栏底部，非管理员不显示。

### 5.2 聊天流式生成（`chat.py` 的骨架）

```
event_stream():
  try:
    token = admission.enter(user_id)          # 全局 4 路 + 每账号 30 条/分钟
    if local: model_usage.begin(model, user)  # 切换保护：有在跑就不许换模型
    async for chunk in upstream:  yield 翻译后的事件
    if 输出内容安全: yield replace/block
  except AdmissionRejected: yield {type:error, code:admission_limited}
  finally:
    落 assistant 消息 / 解析生成文件 / logbus.put(requests+spans)
    admission.leave() / model_usage.end()
```

- 事件协议：`meta`（模型、路由、ttft）→ `delta` / `reasoning` → `error` → `done`。
- 中断：前端断开时 `request.is_disconnected()` 会 break，finally 仍会落库半截内容（这是设计行为，不是 bug）。
- 上下文超预算时按 `_build_context` 的优先级裁剪：附件正文 > 资料库 > 知识库 > 记忆 > 历史。

### 5.3 模型路由与切换保护

```
routing.resolve(user, requested_model):
  1. 算力池（cluster）：pool.enabled → 按权重/轮询选 node → 失败重试 retries 次
  2. 平台模型：platform_models.reachable()（8 秒缓存）→ 取第一个健康节点
  3. 供应商：providers.enabled，按 routes 策略与 fallback
  4. 本地 llama.cpp：需 model_usage 无占用
返回 {provider, base, key, model, pool_id, node_id}
```

切换保护：`model_usage.begin()` 在有活跃生成时抛 `Busy`，控制台提示"正在被 N 个对话使用"；`/api/models/load` 强制参数可覆盖，但要在 UI 二次确认。

### 5.4 知识库检索

```
上传 → attachments.parse_upload（文本直读；PDF/Word/Excel/PPT 用 python-docx/pypdf/...）
     → kb.add_document：切块 ~500 字、写 kb_docs + FTS5 索引
提问 → kb.search(query, top_k)：FTS5 MATCH（不可用则 LIKE）→ 取前 N 块
     → 拼成"参考资料"段落注入 system message，并记 message.meta.kb
```

权限：`kb_use_public` / `kb_use_personal` / `library_use_*` 四个开关在 `users` 表，`kb.py` 每次检索前校验；个人文档永不跨账号可见。

### 5.5 文档生成与过期

```
生成结束 → docgen.build(markdown, format)：识别 ```代码块或显式指令
        → 写 generated_files（原文件 + 元信息），返回 /api/chat/files/{id}/download
        过期：retention 定时扫描 expires_at → 物理删除 + 前端灰显"已过期"
```

支持 docx / xlsx / pptx / pdf / txt / csv / md；docgen 内部按标题层级推断结构，不保证复杂表格还原。

### 5.6 备份、迁移、发布包

三条相似但独立的路径，别混用：

| 能力 | 入口 | 产物 | 恢复方式 |
|---|---|---|---|
| 整机备份 | `POST /api/system/backup` | `data/backups/*.zip`（库+配置+上传） | 控制台"备份"页还原 |
| 数据库快照 | `database_admin.create_database_backup` | `data/database_backups/*.db` | 数据库中心还原 |
| 一键迁移 | `database_admin.migrate` | 目标库（MySQL/PG/SQLite） | 改配置指向新库 |
| 网站分享包 | `services/shortcuts` + `data/shares` | 静态站 zip | 解压即用 |

`repair_foreign_keys()` 在删除孤儿行前**一定会先做快照**，这是硬约束，不要改。

---

## 6. 开发流程

### 6.1 环境准备（Windows 开发机）

```powershell
Set-Location D:\AI\workbench
# 依赖（首次）
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest   # 仓库里的 requirements-dev.txt 只有 pytest
# 跑测试（必须给 secret，且不要指到线上 data 目录）
$env:WORKBENCH_SECRET="pytest-secret-key-do-not-use-in-production"
.\.venv\Scripts\python.exe -m pytest -q          # 期望 195 passed（e2e 自动跳过）

# 浏览器交互冒烟：装内核后单独跑，约 17 秒
.\.venv\Scripts\python.exe -m playwright install chromium
$env:WORKBENCH_E2E="1"
.\.venv\Scripts\python.exe -m pytest -q tests/test_e2e_smoke.py   # 期望 5 passed
```

测试的 `conftest.py` 自己 `mkdtemp` 并固定 `WORKBENCH_DATA`，但**shell 里残留的 `WORKBENCH_DATA` 会污染它**——曾出现 `no such table: auth_identities` 的假失败，根因就是环境变量指到了别的临时目录。跑测试前 `Remove-Item Env:WORKBENCH_DATA`。

### 6.2 本地运行与验收

```powershell
Set-Location D:\AI\workbench
.\stop.ps1; Start-Sleep 2; .\start.ps1 -NoBrowser     # 后台起服务，日志 data\logs\app.log
Invoke-RestMethod http://127.0.0.1:9100/api/health    # {"status":"ok","version":"0.8.3.0"}
```

验收顺序固定：**接口 → 页面 → 截图**。
- 接口：`/api/docs`（Swagger）或直接 curl；
- 页面：`http://127.0.0.1:9100/`（用户端）、`/console/`（控制台）；
- 截图：UI 改动必须给"改前/改后"，因为视觉细节会被当作验收标准。

临时验证不想动线上数据时，用独立端口 + 独立数据目录：

```powershell
Start-Process .\.venv\Scripts\python.exe -ArgumentList "-m","uvicorn","backend.main:app","--host","127.0.0.1","--port","9403"
# 并且备份/指回原 WORKBENCH_DATA，验完 kill 掉进程
```

### 6.3 常见改动的工作流（Recipe）

**A. 新增一个后端接口**

1. 在对应 `routers/*.py` 加函数，`Depends(current_user)` 或 `admin_user`；
2. 复杂逻辑放 `services/`，路由里只做参数与返回；
3. 需要审计就 `await audit(..., action="xxx.yyy")`；
4. 在 `tests/` 补 1 条 happy path + 1 条权限拒绝；
5. 控制台或前端接入点在 4.2/4.1 对应分组里加。

**B. 新增一张表 / 一个字段**

1. 只加**新版本迁移**：`db.py` 的 `apply_migrations()` 里追加 `(N, "name", fn)`，函数内用 `ALTER TABLE` / `CREATE TABLE`；
2. 若表属于知识库域，同步 `KB_SCHEMA`；
3. 迁移必须幂等（先 `PRAGMA table_info` 判断，或 `IF NOT EXISTS`）；
4. 跑测试会自动建新库，另需在**现网库副本**上跑一次迁移验证。

**C. 新增一个控制台页面**

1. `console/index.html` 加 tab 与面板骨架；
2. `backend/console/panels/<域>.js` 里加渲染函数 + 事件分支（单入口 click 分发；不知道放哪个就查 4.2 的表）；
3. 权限：`permission_for_path` 里登记路径前缀，否则普通管理员看不到；
4. 页面必须有"详细说明"入口（项目既有约定）。

**D. 改模型路由或加平台**

1. 平台注册表在 `services/platforms.py`（llama.cpp / ollama / vllm / lmstudio / custom）；
2. 地址配置在 `config.platform_endpoints`，控制台「部署」页可改；
3. 新提供方要能被 `platform_models.reachable()` 探测，就必须实现 `/v1/models`；
4. 改完必须验证：模型下拉能列出、选中能生成、失败能回落。

**E. 改前端样式**

1. 只改 `frontend/app.ui.css` 或 `console.css`，优先走已有 CSS 变量；
2. 改完把 `backend/version.py` 的 `ASSET_VERSION` 上调（页面里的 `?v=__ASSET_VERSION__` 由后端注入，不用手改 HTML）；
3. 窄屏（≤600px）必须自测，历史问题多出在这里。

### 6.4 提交、CI 与发布

```powershell
# git / gh 需要显式指定，或把 git 的 cmd 目录加进 PATH
$env:PATH = "C:\Users\Administrator\AppData\Local\WorkbenchTools\git\cmd;$env:PATH"
$env:HTTP_PROXY="http://127.0.0.1:7890"; $env:HTTPS_PROXY="http://127.0.0.1:7890"
& "C:\Users\Administrator\AppData\Local\WorkbenchTools\git\cmd\git.exe" add -A
& "...\git.exe" commit -m "Short imperative summary"
& "...\git.exe" push origin main
& "C:\Users\Administrator\AppData\Local\WorkbenchTools\gh\bin\gh.exe" run list --limit 3
```

CI 两个工作流：

| 工作流 | 触发 | 内容 | 通过标准 |
|---|---|---|---|
| `ci.yml` | push main / PR | Python 3.10 与 3.12 矩阵 `pip install -r requirements*.txt` + `pytest -q` | 两个版本全绿 |
| `docker.yml` | push main / tag v* | buildx 构建镜像 → 起容器 → 轮询 `/api/health` 30 次 → 校验首页 → 推 GHCR | health 200、首页有内容 |

**发布 = 拉代码 + 重启 + 健康检查**，没有滚动发布：

```
stop.ps1 → git pull → start.ps1 -NoBrowser → /api/health → 打开控制台抽查一个页面
```

**回滚**：`git revert <sha>` 或 `git reset --hard <上一个 tag>` → 重启；数据层回滚用 `data/backups` 的 zip，**不要**用旧代码跑新库（迁移不可逆）。

**发布与镜像标签**

- 产品版本是四段（`0.8.3.0`），**不是合法 semver**（semver 只认 `X.Y.Z`）。镜像版本标签因此不能依赖 `type=semver`，要用 `type=ref,event=tag` 让 tag 名原样成为镜像标签（`v0.8.3.0`）；两条 `type=semver` 保留给未来可能出现的三段 tag。
- 发布顺序：`git tag -a vX.Y.Z.W` → `git push origin vX.Y.Z.W` → `gh release create vX.Y.Z.W --notes-file …`。打 tag 会同时触发 Docker 工作流的 smoke 和多架构推送。
- `latest` 只在 `main` 分支构建时打，release 不覆盖它。
- tag 打错要挪回：删本地与远端 tag → 在新提交上重建 → `gh release edit <tag> --draft=false`（删 tag 那一刻 release 会变成 draft）。

### 6.5 需求到上线的固定节奏

1. 需求卡：目标一句话 + 验收标准（可勾选）+ 不做什么；
2. 设计：改哪些表/端点/页面，是否影响权限与配额；
3. 实现：后端 → 测试 → 前端 → 联调；
4. 验收：接口 + 页面 + 截图 + 回归（`pytest -q` 195 全绿）；
5. 交付：提交 → CI 绿 → 重启 → 现网抽查 → README/本文档同步。

---

## 7. 工程约定与红线

**必须遵守**

- 迁移只增不改；任何破坏性 SQL 先备份。
- 新端点必须声明鉴权依赖；管理端点用 `admin_user` + 权限键。
- 用户可见的错误用中文、说明"发生了什么 + 能怎么做"，不要暴露堆栈。
- 前端资源版本号同步递增。
- 测试不得依赖真实网络、真实模型、真实外部数据库；外部调用要可 mock（现有测试用 monkeypatch + 临时 SQLite）。
- 长耗时任务（OCR、迁移、备份、下载）必须 `asyncio.to_thread` 或独立进程，绝不阻塞事件循环。

**禁止**

- 在 router 里写跨表事务型业务（现状有，属于待偿技术债，新代码不要再添）。
- 把明文密钥写进 `config.json`（供应商 Key/连接密码走 `secrets_store`，AES-GCM）。
- 直接改 `data/workbench.db`（用控制台或 SQL 控制台）。
- 用 `PRAGMA` 关掉外键来"修复"外键异常。

---

## 8. 已知技术债与风险（带证据）

| 编号 | 问题 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| T1 | 控制台单文件巨石 | 原 `console.js` 9031 行 / 403 个顶层函数，`index.html` 2780 行 | 改一个按钮要通读大文件；合并冲突高发 | **已解决（0.8.3.0+）**：按页签拆成 13 个文件（core / models / session / tabs / boot + `panels/*.js` 8 个），最大 `panels/data.js` 1692 行；只切行区间不改代码，31 个页签逐一打开无报错（见 4.2） |
| T2 | 用户端同样巨石 | 原 `app.js` 5190 行，`index.html` 766 行 | 同上 | **已解决（0.8.3.0+）**：拆成 12 个域文件，最大 `workbench.js` 1197 行；IIFE 包裹去掉后共享全局词法环境，`bindEvents()` / `boot()` 留在最后一个文件（见 4.1） |
| T3 | 单写者数据层 | 共享连接 + `asyncio.Lock`，SQLite WAL | 无法多实例；长事务会阻塞所有请求 | 抽 repository，迁移 PG 后去掉全局锁 |
| T4 | 业务规则下沉到路由 | `chat.py` 770 行内直接拼 SQL、判配额 | 换库/换表结构要改 HTTP 层 | 引入 `application/` 用例层 |
| T5 | 权限语义分散 | `role` + `admin_roles.permissions` + `allowed_models` + 4 个 kb/library 开关 | 新增权限容易漏配，行为难预测 | 收敛成单一 `Permission` 枚举 + 一张 `user_permissions` |
| T6 | 错误契约不统一 | 部分返回 `{code}` 事件，部分抛 `HTTPException(detail=str)` | 前端只能靠文案判断 | **已解决（0.8.3.0）**：`backend/errors.py` + 全局处理器补齐 `code`（见 4.4 / 附录 F）；剩余是把 333 处 `HTTPException` 逐步换成 `APIError` 以细化业务码 |
| T7 | 无 API 版本化 | 333 个操作平铺在 266 条路径 | 破坏性变更无法灰度、第三方接入会断 | 新能力走 `/api/v2`，旧端点加兼容层 |
| T8 | 本地模型串行 | `services/llama.py` 单进程托管 | 100 人并发时队列化严重 | 短期靠准入限流；中期接算力池/外部 vLLM |
| T9 | 前端零自动化测试 | `tests/` 全为后端用例 | 回归靠人工截图 | **已解决（0.8.3.0+）**：三层兜底——`tests/test_pages_smoke.py` 断言每个入口页引用的 js/css 可达；CI `frontend` job 做 `node --check` 与「每个脚本仍被某页引用」；`tests/test_e2e_smoke.py` 用 Playwright 真点 5 条路径（登录 / 发消息收流式回复 / 设置抽屉切分区 / 控制台登录并改品牌 / 分享页只读），任一条 console 报错即失败，CI `e2e` job 跑 |
| T10 | 版本号三处不一 | `main.py` 0.8.1、`/api/health` 0.8.1、资源 `0.8.2.2` | 无法判断线上跑的是哪版 | **已解决（0.8.3.0）**：`backend/version.py` 单源，资源版本由 `render_page()` 注入（见 4.3） |
| T11 | 重活混在线程池 | OCR/docgen/迁移用默认 executor（32 线程） | 并发上传时挤占事件循环调度 | 独立 `ThreadPoolExecutor(max_workers=4)` 或任务队列 |
| T12 | 三套备份逻辑 | `backup.py`、`database_admin`、`system` 分享 | 语义重叠，恢复路径易混 | 统一 `SnapshotService`，明确三种语义 |
| T13 | 可观测双轨 | `logbus`（requests/spans）与 `audit_logs` 各写一套 | trace_id 无法串起"谁点的、花了多少" | 审计里记录 `request_id`，概览页按 trace 聚合 |
| T14 | 测试共享全局状态 | `conftest` 单库 + 模块级缓存单例 | 偶发顺序依赖失败 | 每模块独立 tmp 库；单例提供 `reset_for_tests()`（`admission` 已有） |
| T15 | ~~容器开关未接线~~（原诊断有误） | `docker.yml` 传 `WORKBENCH_SERVE_FRONTEND=1`；实测 `config.load_config()` 对 DEFAULTS 全部键做 `WORKBENCH_<KEY>` 覆盖，bool 键按 `1/true/yes/on` 解析 | 容器首页其实正常：`WORKBENCH_SERVE_FRONTEND=1` 时 `GET /` 返回 200 且是注入后的 `index.html`（0.8.3.0 实测）；真正的缺口是 `docker.yml` 冒烟用 `curl -f` 且不跟随 307，断言偏弱 | 冒烟改为断言 `GET /` 为 200 且正文含 `<title>`，避免「重定向也算过」 |
| T16 | `/console` 不带尾斜杠时资源 404 | `backend/console/index.html` 原写 `<link href="console.css?v=…">` / `<script src="console.js?v=…">`（相对路径），而 0.8.3.0 起 `GET /console` 也直出 200 | 浏览器把相对路径解析成 `/console.css`、`/console.js` → 404，控制台**无样式且脚本不执行**，看起来像白屏；只有带尾斜杠访问才正常 | **已解决（0.8.3.0+）**：两处改为 `/console/console.css` / `/console/console.js`；`tests/test_pages_smoke.py` 逐个请求页面声明的资源，同类问题在 CI 直接失败 |

风险（非代码）：`GTX 650 1GB`、`gpu_usable=false`，本机只能跑小模型 CPU 推理；千兆内网做张量并行不现实；所以"多机"只应做成"多副本 + 调度"，不做"单模型跨机切分"。

---

## 9. 目标架构（TO-BE）

### 9.1 分层

```
app/
├── main.py                # 组装：中间件、路由注册、lifespan
├── api/                   # HTTP 层
│   ├── deps.py            # current_user / require_permission / trace
│   ├── v1/                # 现有端点原样迁入，路径不变
│   └── schemas/           # pydantic 出入参（现在几乎没有，这是缺口）
├── application/           # 用例层：一个函数 = 一次完整业务动作
│   ├── chat_run.py        # 组装上下文、调模型、落库、发事件
│   ├── model_switch.py
│   ├── kb_index.py
│   ├── snapshot.py        # 备份/迁移统一
│   └── user_admin.py
├── domain/                # 纯规则：配额、权限、路由策略、保留期计算
├── infra/
│   ├── db/                # repository 接口 + sqlite/pg 两个实现
│   ├── llm/               # adapter：llama.cpp / ollama / vllm / openai
│   ├── fs/                # 上传、生成文件、快照
│   └── crypto.py
└── jobs/                  # 后台：logbus、scheduler、retention、parse
```

三条横向原则：

1. **配置单源**：`Settings`（pydantic-settings）从环境变量 + `config.json` 读取，schema 即文档；不再有"默认值散落在 70 个键里没人知道"。
2. **错误单源**：`AppError(code, message, http_status)`，路由层统一转 JSON；流式场景复用同一 `code`。
3. **trace 贯穿**：入口生成 `trace_id`，写进日志、`requests`、`audit_logs`，任何一条用户投诉都能反查到一次完整调用。

### 9.2 多实例化的前置条件（只有真要扩容才做）

| 组件 | 现状 | 需要变成 |
|---|---|---|
| 数据库 | SQLite 文件 | PostgreSQL（唯一硬门槛） |
| 准入限流 | 进程内信号量 | PG advisory lock 或 Redis 计数 |
| 会话 | DB 表（已可共享） | 迁移后天然可用 |
| 文件 | 本地 `data/` | 共享卷或对象存储 |
| 静态资源 | 后端挂载 | 反向代理 / Nginx |
| 日志 | 文件 + 轮转 | stdout 结构化 + 采集 |

判断标准：**只有当"必须横向加机器"时再动**。100 人以内、单机 4 路并发 + 30 rpm 限流是够的，瓶颈在模型不在应用。

### 9.3 前端目标

- 用户端：Vite + ES Module，按域拆分（chat / settings / workbench / collab / share），共享 `api.js` 与 `sse.js`；
- 控制台：按 tab 拆文件，`registry.js` 声明 `{key, title, group, permission, render, mount}`，导航与权限自动生成；
- 保留现有视觉，只换工程结构，避免"重构即改版"的返工。

---

### 9.4 "多进程 / 多机部署"到底指什么

这三个词经常被混着用，但技术含义完全不同，选错方向会白花钱：

| 叫法 | 实际含义 | 瓶颈 | 工作台现状 | 结论 |
|---|---|---|---|---|
| 多进程 | 同一台机器起多个应用进程（`uvicorn --workers 4`） | SQLite 单写者，多进程写同一文件会 `database is locked` | 不支持，`run.py` 固定单 worker | 想做必须先把库换成 PG |
| 多机（多副本） | 两台以上机器各跑一套应用 + 各自/共用一份库 | 数据库与文件共享；模型各自加载 | 有算力池（调度多节点），但不是应用副本 | **100 人并发的正解**：多副本 + 算力池调度 |
| 多机（单模型） | 一个模型被切到多台机器上联合推理（张量并行 / 流水线并行 / RPC 后端） | **互联带宽**：NVLink、InfiniBand、25GbE 起步 | 完全不支持 | 千兆内网下通常比单机更慢，只适合"装得下更大的模型" |

判断口诀：

- 目标是**更多人同时用** → 加应用副本、加推理节点，别切模型；
- 目标是**跑更大的模型**（显存装不下）→ 才考虑跨机切分，且必须先解决网络；
- 目标是**更快的单次回答** → 换更强的单卡，比跨机划算。

如果确实要在这套代码上支持"单模型跨机"，改动点是明确的三处：
1. `services/llama.py` 的 `server.start()` 增加 `--rpc <ip:port>` 参数列表；
2. `config.platform_endpoints` 之外新增 `llama_rpc_nodes`，控制台「部署」页加远程后端管理；
3. `models` 表增加 `backend` 字段（local / rpc），路由决策里区分。

这三处不动，任何"多机跑一个模型"的说法都不成立。

## 10. 重构迁移路线（分阶段、可回滚）

原则：**每一阶段都要能独立上线、独立回滚，且不改变用户可见行为**（除非该阶段目标就是改行为）。

### 阶段 0：冻结基线（0.5 天）
- 打 tag 并发布 Release：**已完成**，`v0.8.3.0` 已推送、Release 已发布（含 Docker 多架构镜像 `:v0.8.3.0` / `:latest`），记录 195 测试基线、CI 与 Docker 两个工作流绿。
- 把本文档提交进仓库（`docs/`），README 增加入口链接：**已完成**（README「## 文档」）。
- 验收：任何人 clone 后能按 6.1 跑出 195 passed。

### 阶段 1：低风险治理（2–3 天）—— ✅ 已完成（0.8.3.0）
- T10 版本单源：新增 `backend/version.py`，`main.py` / `health` / `meta` / 备份清单 / 导库元数据全部改读常量。
- T6 错误码表：新增 `backend/errors.py` + 三个全局异常处理器；`/api/meta` 与错误体都带 `code`；控制台 `api()` 与用户端 `errorText()` 同步支持结构化错误。
- 资源版本注入：HTML 写 `?v=__ASSET_VERSION__`，`render_page()` 返回时替换；`/api/meta` 增加 `asset_version`。
- 顺手修：`/api/system/migration` 与 `/api/system/share` 的 `api_route` 导致 OpenAPI `operationId` 重复（客户端生成会互相覆盖），已拆成 `@router.get` + `@router.post`。
- 验收：`pytest -q` 195 passed；控制台与用户端实测资源为 `?v=0.8.3.0`、无 JS 报错；CI + Docker 绿。
- 仍未做：T14 测试隔离（`conftest` 单库仍是共享状态），留到阶段 2 一起处理。
- 回滚：`git revert` 单个 commit。

### 阶段 2：前端拆分（5–7 天，可与阶段 3 并行）
- T1 控制台按 tab 拆文件，先拆 4 个纯展示页（概览、审计、公告、工单），验证 registry 机制；
- T2 用户端拆分：**已完成**，12 个域文件、最大 1197 行；
- 验收：**已完成（0.8.3.0+）**：拆成 13 个文件、最大 1692 行；31 个页签逐一打开、说明与刷新按钮实测无 JS 报错；控制台路径已进 `tests/test_e2e_smoke.py`（登录 + 改品牌）。
- 回滚：保留旧文件一个版本周期，用特性开关切回。

### 阶段 3：后端分层（7–10 天）
- 建 `application/` 与 `infra/db/repository`，**先搬 `chat.py` 的读写**（风险最高、收益最大），再搬 `kb`、`workbench`；
- 路由瘦身到"解析 → 调用例 → 返回"，SQL 只出现在 repository；
- 验收：端点路径与响应结构零变化（用 `/api/docs` 快照 diff）；195 测试 + 新增 repository 单测全绿；`chat.py` < 300 行。
- 回滚：新旧实现并存，配置 `use_legacy_chat=1` 切回。

### 阶段 4：可扩展（按需）
- 数据库适配层接 PG（`infra/db/pg.py`），控制台"数据库中心"已有迁移工具可复用；
- 准入/限流外置；文件存储抽象；静态资源交反向代理；
- 验收：双实例指向同一 PG，同时发消息不报 `database is locked`；`requests` 表在两个实例都写成功。
- 回滚：配置指回 SQLite（保留最近一次快照）。

### 阶段 5：能力扩展（可选，与架构解耦）
- 模型层：接 vLLM/Ollama 做并发（已支持探测），或给 llama.cpp 加 RPC 远程后端（`--rpc ip:port`）；
- 前端：多模态消息、富文本编辑器；
- 运维：容器化单机部署（镜像已能构建）。

**不要做的事**：一次把所有 router 重写；在没有 PG 的情况下加 `--workers`；在没有自动化测试的情况下大改前端。

---

## 11. 换人 / 换 AI 接力的上手说明

### 11.1 读代码顺序（约 1 小时建立心智模型）

1. `README.md`（功能全貌 + 用户视角）
2. 本文档第 2、3 章（架构与域）
3. `backend/main.py`（装配顺序：从 `app = FastAPI(...)` 往下看 lifespan、include_router、mount）
4. `backend/db.py`（`SCHEMA` 开头 + `apply_migrations` 尾部，知道表怎么来的）
5. `backend/routers/chat.py`（最复杂链路；只看 `event_stream` 与 `_build_context`）
6. `backend/services/routing.py` + `llama.py`（模型怎么被选中和执行）
7. `frontend/core.js`（状态对象 `S` 与 API 封装）+ `backend/console/index.html` 的 tab 列表

### 11.2 高频任务速查

| 我想… | 去哪 |
|---|---|
| 加一个配置项 | `config.py` DEFAULTS + 控制台对应页 + `docs` 附录 D |
| 加一个模型分类 | `services/models` 数据（52 条内置清单） + `frontend/models.js` 分类渲染 |
| 让某模型对某用户可见 | `users.allowed_models`，控制台「用户」页 |
| 调并发上限 | `config.chat_max_active` / `chat_rpm`，或环境变量 |
| 查某次调用为什么慢 | `requests` 表的 `queue_ms / ttft_ms / total_ms` + `spans` |
| 查谁改了什么配置 | `audit_logs`，`action` 前缀即模块 |
| 数据库报外键异常 | 控制台「数据库」页 → 健康检查 → 一键清理（自动快照） |
| 换数据库 | 控制台「数据库」页 → 连接管理 → 一键迁移（先快照） |

### 11.3 坑清单（都是真实踩过的）

1. **静态资源版本号**不改 → 页面还是旧的，误判"没生效"。
2. **`WORKBENCH_DATA` 残留** → 测试假失败、临时实例写到线上库。
3. **流式接口的 HTTP 200** → 错误在 SSE 里，别只看状态码。
4. **SQLite 的 `database is locked`** → 说明有多进程/多实例，不是加锁参数问题。
5. **`asyncio` 里调同步重活** → 整个服务卡死，必须 `to_thread`。
6. **改迁移函数** → 老库不会重跑，只有新库生效，导致环境不一致。
7. **控制台单入口 click 分发** → 新按钮必须挂 `data-*` 或在分发里加 `id` 分支。
8. **`platform_models` 8 秒缓存** → 改完平台地址立刻看不到结果，等 8 秒或重启。
9. **模型切换**被保护拦住 → 不是 bug，先看 `model_usage` 是否有活跃生成。
10. **gh 找不到 git** → 必须把 git 的 `cmd` 目录加进 PATH。
11. **推送超时** → 需要 `HTTP_PROXY/HTTPS_PROXY=127.0.0.1:7890`。
12. **CI 与本地 Python 版本不同**（3.10/3.12 都跑）→ 本地 3.12 通过不代表 CI 通过。

### 11.4 交接时至少要交代的三件事

1. 现网入口与凭据在哪（`data/config.json`，管理员账号在 `users` 表）；
2. 回滚方式（代码 revert + `data/backups` 快照）；
3. 当前未完成的重构阶段（阶段 0–4 做到哪一步，开关名是什么）。

---

## 12. 附录

### 附录 A：路由清单（25 个文件 / 26 个 router 对象，266 条路径 / 333 个操作）

| 文件 | 行数 | 端点数 | 前缀 | 职责 |
|---|---|---|---|---|
| admin.py | 679 | 29 | /api/admin | 系统设置、硬件、安装、启停、日志 |
| apikeys.py | 100 | 4 | /api | 用户 API Key 增删查 |
| auth.py | 527 | 18 | /api/auth | 初始化、登录、注册、改密、会话 |
| auth_admin.py | 95 | 4 | /api/admin/auth-providers | 登录方式配置 |
| branding.py | 21 | 1 | /api/branding | 品牌公开信息 |
| chat.py | 770 | 12 | /api | 会话、消息、流式生成、文件下载 |
| cluster.py | 199 | 10 | /api/admin/cluster | 算力池节点/池/成员 |
| collab.py | 703 | 21 | /api/admin | 智能体、小队、公告、工单、分享 |
| database.py | 434 | 29 | /api/admin/database | 表浏览、SQL、连接、迁移、健康、修复 |
| engines.py | 46 | 3 | /api/engines | 独立引擎状态与安装 |
| files.py | 100 | 3 | /api/chat/files | 生成文件列表/下载/删除 |
| front.py | 108 | 1 | /api/front | 前台功能开关与图标 |
| kb.py | 351 | 9 | /api/kb | 知识库文档 CRUD 与检索 |
| library.py | 351 | 19 | /api/library（管理员 10）、/api/my/library（个人 9） | 资料库（与 kb 共用表） |
| memory.py | 82 | 5 | /api/admin/memory | 管理端记忆 |
| models.py | 412 | 11 | /api/models | 模型清单、下载、加载、删除 |
| my_memory.py | 91 | 6 | /api/my/memory | 用户自助记忆 |
| openai_api.py | 627 | 2 | 无 | `/v1/models`、`/v1/chat/completions` |
| ops.py | 77 | 5 | /api | 内网穿透隧道 |
| prompts.py | 328 | 8 | /api/admin/prompts | 提示词模板与版本 |
| system.py | 778 | 43 | /api/system | 概览、备份、迁移、网络、快捷方式、保留期 |
| upload_admin.py | 156 | 6 | /api/admin/uploads | 附件解析管理 |
| users.py | 538 | 16 | /api/users | 用户、组、角色、配额、权限 |
| workbench.py | 461 | 18 | /api/workbench | 模板、任务、分享、概览 |

### 附录 B：核心 service（46 个，按体积）

| 文件 | 行数 | 一句话职责 |
|---|---|---|
| database_admin.py | 1791 | 表浏览/迁移/健康/快照/外部库连接 |
| docgen.py | 990 | Markdown → docx/xlsx/pptx/pdf |
| websearch.py | 676 | 联网检索与网页正文抽取 |
| backup.py | 610 | 整机备份/恢复/导出 |
| shortcuts.py | 565 | 桌面快捷方式、网站分享包 |
| kb.py | 477 | 知识库切块、索引、检索 |
| prompts.py | 466 | 提示词注册表、版本、渲染 |
| attachments.py | 425 | 附件解析（文本/PDF/Office/OCR） |
| platform_deploy.py | 417 | 平台一键部署 |
| cluster.py | 395 | 算力池节点调度 |
| engines.py | 367 | 独立引擎探测 |
| installer.py | 361 | llama.cpp 安装与下载 |
| autostart.py | 357 | 开机自启（Windows/Linux） |
| scheduler.py | 352 | 定时任务轮询与执行 |
| auth_config.py | 335 | 登录方式配置读写 |
| auth_delivery.py | 272 | 验证码发送渠道 |
| llama.py | 275 | llama-server 进程生命周期 |
| platforms.py | 253 | 平台注册表 |
| memory.py | 249 | 长期记忆抽取与注入 |
| tunnel.py | 246 | cloudflared 隧道 |
| auth_providers.py | 225 | 身份提供方注册 |
| retention.py | 200 | 生成文件过期清理 |
| moderation.py | 198 | 敏感词与流式过滤 |
| collab.py | 185 | 智能体/小队/工单 |
| storage.py | 164 | 文件落盘与路径 |
| skills.py | 161 | 技能提示词 |
| routing.py | 154 | 模型路由决策 |
| branding.py | 151 | 品牌资源 |
| netinfo.py | 142 | 网卡与地址 |
| hardware.py | 140 | GPU/CPU/内存探测 |
| apikeys.py | 129 | Key 生成与校验 |
| auth_oauth.py | 99 | QQ/微信 OAuth |
| parse_jobs.py | 99 | 解析任务队列 |
| hf_models.py | 127 | HF 镜像下载 |
| engine_install.py | 116 | pip 安装引擎 |
| access.py | 119 | 模型访问控制 |
| otp.py | 111 | 一次性验证码 |
| library.py | 107 | 资料库 |
| admission.py | 105 | 并发准入（本轮新增） |
| model_usage.py | 84 | 模型占用与切换保护 |
| tts.py | 81 | edge-tts 语音 |
| auth_identity.py | 70 | 多身份绑定 |
| secrets_store.py | 70 | AES-GCM 密钥存储 |
| quota.py | 45 | 日/月 token 配额 |
| platform_models.py | 95 | 平台模型探测与缓存 |

### 附录 C：数据表分组（48 张业务表）

> `sqlite_master` 里实际是 54 项：除下列 48 张业务表，还有 6 张 FTS5 内部表（`kb_fts` 及其 `_config/_content/_data/_docsize/_idx`）。数表时先排除 FTS 影子表，否则会数成 54。下面是按实测名逐张归组的结果，各组数字相加正好 48 张。

- **身份权限（9）**：users、sessions、auth_identities、api_keys、admin_roles、user_groups、settings、front_features、front_icons（brand 配置在 `config.json`，不是表）
- **对话内容（8）**：conversations、messages、generated_files、uploads、conversation_shares、cache_entries、memories、kb_docs
- **模型路由（8）**：models、providers、routes、requests、spans、downloads、experiments、sensitive_words（用量统计在 `requests/spans`，没有独立的 model_usage 表）
- **协作组织（8）**：agents、squads、squad_agents、squad_members、squad_conversations、announcements、tickets、ticket_messages
- **工作台（5）**：workbench_templates、workbench_active、workbench_shares、scheduled_tasks、task_runs
- **提示词（3）**：prompt_templates、prompt_versions、prompt_releases
- **运维审计（6）**：audit_logs、moderation_hits、schema_migrations、cluster_nodes、cluster_pools、cluster_members
- **技能（1）**：custom_skills（kb_docs 归知识域，不重复计）

> 精确字段与行数见 `data/workbench.db` 的 `PRAGMA table_info`，或控制台「数据库」页的表浏览。`settings` 表只有 3 行——绝大多数配置在 `data/config.json`，这是"配置双轨"的来源（T3 相关）。

### 附录 D：配置分组（`config.py` DEFAULTS，约 70 键）

| 组 | 键 |
|---|---|
| 服务 | host、port（默认 9000；`start.ps1` 用 `--port 9100` 覆盖，`run.py` 写回 `WORKBENCH_PORT` 供穿透使用）、log_level、serve_frontend、cors_origins、frontend_url |
| 路径 | models_dir、platforms_dir、llama_dir、llama_bin、hf_endpoint、hf_token |
| 模型 | model、ctx、threads、gpu_layers、upstream_base、upstream_key、upstream_port、local_enabled、deploy_platforms、platform_endpoints、github_proxy |
| 会话 | session_hours、token_hours、allow_register |
| 生成 | system_prompt、chat_max_active、chat_rpm |
| 知识 | kb_enabled、kb_top_k、library_enabled、library_max_chars、library_max_docs |
| 记忆 | memory_enabled、memory_max_items、memory_context_chars |
| 安全 | moderation_enabled、moderation_input_action、moderation_output_action、moderation_replace、moderation_min_chars |
| 联网 | websearch_enabled、websearch_max_sources、websearch_max_pages |
| 品牌 | org_*、brand_*、watermark_* |
| 运维 | tunnel_target、tunnel_token、tunnel_domain、desktop_shortcuts、shortcut_mode、shortcut_lan_ip、shortcut_custom_url、generated_file_retention_days、tts_voice |

### 附录 E：环境变量

| 变量 | 作用 |
|---|---|
| WORKBENCH_DATA | 数据目录（测试/临时实例必须隔离） |
| WORKBENCH_SECRET | 会话与令牌签名密钥（测试必设） |
| WORKBENCH_MODELS / WORKBENCH_PLATFORMS / WORKBENCH_LLAMA | 模型与平台目录 |
| WORKBENCH_SERVE_FRONTEND | 单进程模式开关（docker-compose / docker.yml 传入）。`load_config()` 对 DEFAULTS 里**每个**键都做 `WORKBENCH_<KEY>` 覆盖，bool 键认 `1/true/yes/on` |
| WORKBENCH_CHAT_MAX_ACTIVE / WORKBENCH_CHAT_RPM | 覆盖并发准入参数 |
| WORKBENCH_HF_ENDPOINT / HF_TOKEN | 模型下载源与令牌 |

> 通用规则：`WORKBENCH_<KEY>` 可覆盖 `config.py` DEFAULTS 里任意一个键（键名大写），非空才生效；优先级高于 `data/config.json`。

### 附录 F：错误码表

响应体统一为 `{detail, code, ...extra}`；`detail` 是人类可读中文，`code` 是稳定契约。

状态码默认码（`DEFAULT_CODE_BY_STATUS`）：

| 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | `bad_request` | 参数不合法 |
| 401 | `unauthorized` | 未登录 / 令牌无效 |
| 403 | `forbidden` | 已登录但无权限 |
| 404 | `not_found` | 资源不存在 |
| 405 | `method_not_allowed` | 方法不对 |
| 409 | `conflict` | 状态冲突（如模型被占用） |
| 413 | `payload_too_large` | 上传过大 |
| 422 | `validation_error` | 请求体校验失败（`detail` 为数组） |
| 429 | `rate_limited` | 限流 / 配额（看 `retry_after`） |
| 500 | `internal_error` | 未处理异常 |
| 501 | `not_implemented` | 功能预留未启用 |
| 502 | `upstream_error` | 上游模型/引擎失败 |
| 503 | `service_unavailable` | 依赖不可用 |

业务码（`backend/errors.py` 顶部常量）：

| code | 状态码 | 触发点 | 前端建议处理 |
| --- | --- | --- | --- |
| `invalid_credentials` | 401 | 用户名或密码错误 | 提示重试，不清空账号 |
| `account_disabled` | 403 | 账号被管理员禁用 | 提示联系管理员 |
| `account_locked` | 429 | 连续失败被锁 | 按 `retry_after` 倒计时 |
| `register_closed` | 403 | 未开放自助注册 | 隐藏注册入口 |
| `rate_limited` | 429 | 登录/注册/发送过频 | 按 `retry_after` 倒计时 |
| `quota_exceeded` | 429 | 用量配额用完 | 展示套餐与重置时间 |
| `model_busy` | 409 | 本地模型正被其他会话占用 | 弹"等待/强制"选择 |
| `model_not_allowed` | 403 | 模型未对该用户开放 | 下拉里不显示该模型 |
| `invalid_api_key` | 401 | `/v1/*` Key 无效 | 提示检查 Key |
| `not_local` | 403 | 远程访问"打开文件夹" | 隐藏该按钮 |
| `confirm_required` | 409 | 破坏性操作需二次确认 | 弹确认条 |

新增错误时优先 `raise APIError(status, message, code, extra={...})`；不确定就用普通 `HTTPException`，默认码仍然可用。

### 附录 G：本文档维护规则

- 端点数、表数、测试数变化时，改第 2 章与附录对应数字；
- 新增技术债或偿还技术债时，改第 8 章表格（保留编号，标注"已偿还"）；
- 每完成一个重构阶段，在第 10 章该阶段打勾并记录实际耗时与偏差原因。

（文档结束）



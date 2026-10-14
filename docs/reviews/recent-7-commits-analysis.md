# HaloWebUI 最近七次提交核查（T1）

核查人：commit-analyst（Codex）。核查日期：2026-10-14，时区 Asia/Shanghai（UTC+08:00）。交接对象：team-lead、summary-editor。

本轮主线是：精答附件链路补齐 → 共用附件派发修复 → 费用口径展示修正 → 新增自动分流工作台 → 标题、历史和结果回填体验完善 → 导航测试跟进 → 模型标签精简。不是七项互不相关的新功能，也不是最近七天的统计。

## 1. 范围、基准与证据口径

- 只读分析源仓库：`/root/HaloWebUI`。
- 分析开始时的完整 HEAD：`f2b4f7fb107977448ebeaf2ad21380ac661d239a`。共享 worktree 在开始时也是这个 HEAD，分支为 `halo/halo-57ff30c03c5b4f04`。
- 按 `git log -7 HEAD` 选取最近 **七次提交**；随后所有差异比较固定到上述哈希，避免 HEAD 后续变化影响选取。
- 七笔的提交者时间范围：**2026-10-13T13:25:17+08:00 至 2026-10-14T15:54:56+08:00**，跨度约 26 小时 30 分钟。下表同时保存作者时间与提交者时间，二者在部分提交不同。
- 本地不是浅克隆，七笔及其父提交均可读取；未拉取远端。
- 七笔全部只有一个父提交，没有合并提交。逐笔比较基准为各自的唯一父提交；整体净变化基准为最早提交的父节点 `0df006327f4cd5b3d007ed1c74fd14e01fe59647`。
- 整体 `git diff --stat 0df006327f4cd5b3d007ed1c74fd14e01fe59647 f2b4f7fb107977448ebeaf2ad21380ac661d239a`：**85 个不同文件，增加 3391 行、删除 237 行**。包括测试、文档及格式变化，不能当成纯业务代码量；逐笔统计存在重复文件，不能直接相加作为独立功能数量。
- 主仓库当时已有两项未跟踪内容（`backend/open_webui/static/_probe_density.html`、`docs/image-templates/`），未纳入提交分析，也未修改。业务代码、分支及运行服务均未改动。
- 下文 `路径:行号` 默认指固定 HEAD 中的真实源码位置；路径相对 `/root/HaloWebUI`。逐笔完整文件清单见附录。历史行为以该提交与父提交的差异为准，后续已修正的问题不列为当前 HEAD 的未修复缺陷。

### 提交身份（与 `git log -7 HEAD` 相同，最新在前）

| 编号 | 完整哈希 | 作者时间（含时区） | 提交者时间（含时区） | 标题 | 唯一父提交（完整哈希） |
| --- | --- | --- | --- | --- | --- |
| C7 | `f2b4f7fb107977448ebeaf2ad21380ac661d239a` | `2026-10-14T15:54:56+08:00` | `2026-10-14T15:54:56+08:00` | fix: shorten routing model label in auto dispatch card | `9d95561dc3d25e6a52a35bd75f12533619df8350` |
| C6 | `9d95561dc3d25e6a52a35bd75f12533619df8350` | `2026-10-14T15:29:13+08:00` | `2026-10-14T15:29:13+08:00` | test: align team result navigation coverage with message reveal | `dab7f6aa22fe4c15be825459fb1d98a2b02ad655` |
| C5 | `dab7f6aa22fe4c15be825459fb1d98a2b02ad655` | `2026-10-14T15:12:18+08:00` | `2026-10-14T15:18:23+08:00` | fix: unify workbench titles and automatic routing experience | `589fb5328de28fc53b4e5ff6c94a4b5810b32354` |
| C4 | `589fb5328de28fc53b4e5ff6c94a4b5810b32354` | `2026-10-14T13:38:02+08:00` | `2026-10-14T13:38:36+08:00` | feat: add automatic routing workbench | `122424a49ac20e8b78c6516b9f32308cde82cda9` |
| C3 | `122424a49ac20e8b78c6516b9f32308cde82cda9` | `2026-10-13T16:54:23+08:00` | `2026-10-13T16:54:23+08:00` | fix(analytics): distinguish reported, estimated and partial runner costs | `d83549cef5f81ab8e8b22f89a78b677489220160` |
| C2 | `d83549cef5f81ab8e8b22f89a78b677489220160` | `2026-10-13T14:04:11+08:00` | `2026-10-13T14:04:49+08:00` | fix(dispatch): carry historical images and read raw document attachments | `39731631238b5b691519dec86449a53d0c0aca2d` |
| C1 | `39731631238b5b691519dec86449a53d0c0aca2d` | `2026-10-13T13:25:17+08:00` | `2026-10-13T13:25:17+08:00` | fix(answer): support document and image attachments end to end | `0df006327f4cd5b3d007ed1c74fd14e01fe59647` |

## 2. 逐笔核查（以下按时间从旧到新解释因果）

### C1 — `39731631238b5b691519dec86449a53d0c0aca2d`

标题：`fix(answer): support document and image attachments end to end`。相对父提交：10 文件，+525 / -75。

**目的与实际变化：**把精答从仅有问题文本扩展为可接收文档和图片。`backend/open_webui/routers/answers.py` 的创建表单增加 `files: list[str]`；创建和聊天派发入口读取附件，运行对象和用户消息保存文件引用；重复提交判断增加附件 ID 集合，避免同一句话但不同附件被合并。`backend/open_webui/utils/answer_desk.py:274` 将文档正文及可用图片附在调度器、回答模型的用户消息上，失败重试仍保留附件。图片按模型及基础模型的 vision 能力决定是否传递，缺图时明确提示模型不能编造内容；公开运行详情移除附件的 `text` 字段，图片数据临时物化，不将 base64 图像写入聊天。

**用户可感知变化：**`src/lib/components/answer/AnswerHome.svelte:54` 起新增最多 4 个附件的选择、粘贴、拖入、上传进度、错误与移除操作；上传未完成或存在失败附件时禁止提交。视频会尝试额外生成一张帧联系图，计入附件数量。模式草稿交接携带已上传附件。`AnswerRun.svelte:287` 显示文件下载链接和图片缩略图。聊天中的精答派发文案从“读不到附件”改为“文件会一起交给助手”。

**模块与接口：**修改精答路由、运行工具、聊天派发适配器、精答 API 类型、首页/详情组件及说明文档。`POST /api/v1/answers/` 的 `files` 有默认空列表，`AnswerRun.files` 为可选字段，旧的无附件请求仍适用；不增加数据库迁移。附件归属检查复用讨论模块的既有规则：普通用户必须拥有文件，管理员沿用原有例外，并非本次新增管理员越权路径。

**测试变化：**`test_answer_desk.py` 覆盖调度与回答均收到附件、失败后重试、相同/不同附件去重、不可用及他人附件拒绝、聊天派发、文本模型缺图说明；`AnswerHome.mount-test.ts` 增加上传进度、失败禁止提交、交接文件断言；`AnswerRun.mount-test.ts` 增加附件链接/缩略图断言。以上是提交中新增或修改的覆盖，本次未执行这些测试。

**与后续的关系：**本笔文档正文主要来自已有提取结果，聊天派发仍只收集当前 metadata 附件。C2 补齐历史图片及 `process=false` 原始文档，不能把 C1 标题里的“end to end”解释成当时已覆盖这两种情况。

### C2 — `d83549cef5f81ab8e8b22f89a78b677489220160`

标题：`fix(dispatch): carry historical images and read raw document attachments`。相对父提交：9 文件，+211 / -31。

**目的与实际变化：**修复切换处理方式时“之前发过的图片没有带过去”和 Hermes 原文件上传没有已提取正文的问题。新增 `backend/open_webui/utils/dispatch_files.py:19` 的共用收集函数：先保留当前 metadata 中选中的文件，再扫描本次请求历史内用户消息的 `image_url`，解析内部文件引用并去重。不扫描数据库中其他聊天分支，不从历史文件列表恢复已移除文档，不收集助手生成图片或普通外链图片。

`backend/open_webui/routers/discussions.py:271` 新增 `_read_raw_document`：已有正文优先；无正文且有存储路径时，通过 Storage 取得文件后，检查本地文件大小不超过 20 MiB，再以本地 Loader 提取，每份保留最多 12000 字符。读取异常返回空正文，后续附件提示明确不可读；不建立向量索引。精答、讨论的新建、派发和追问入口改用 `asyncio.to_thread` 承担这些同步读取。这个限制约束的是解析前的文件大小和传给模型的文本量，不能推断解析器的峰值内存也被限定为 20 MiB。

**用户可感知变化：**精答、讨论能继续看到当前请求历史中的用户图片；原始上传的可解析文档能参与回答；协作台共用同一 ID 收集规则，再经过既有归属检查转换为 Hermes 主机文件路径。

**模块与接口：**修改 `routers/answers.py`、`routers/discussions.py`、`utils/mode_dispatch.py`、`utils/agent_team_dispatch.py`，新增共用工具和单测，更新 `docs/hermes-dispatch-modes.md`。未新增 HTTP 字段、路由、环境变量或数据库迁移。图片仍必须是能解析为内部文件 ID 的引用；精答/讨论沿用各自已有附件数量边界，未扩展为无限历史附件。

**测试变化：**新增 `test_dispatch_files.py`，断言当前文档与历史图片去重、不恢复删除文档、不带助手/外链图、协作文件归属与主机路径、原文截断及不可读提示；精答/讨论路由测试增加缓存正文与原始文件两组参数，以及历史图片真正到达模型消息的断言。本次未执行这些测试。

**关系：**这是 C1 的直接补充，同时把附件收集提升为三个工作台共享的逻辑；C4 自动路由的聊天适配器继续复用它。

### C3 — `122424a49ac20e8b78c6516b9f32308cde82cda9`

标题：`fix(analytics): distinguish reported, estimated and partial runner costs`。相对父提交：6 文件，+158 / -39。

**目的与实际变化：**后台任务费用不再笼统显示成一个金额。`src/lib/apis/hermes/index.ts` 扩展可选 `cost_partial`、`cost_source`、`cost_notice`、`pricing_updated_at`，并增加两种缓存写 token 字段。`src/lib/utils/runner-stats.ts:76` 在原合计之外分别累计上报金额、估算金额、缺失数量、部分费用数量；空费用不参与金额合计，显式 0 仍是有记录费用。`runTokens` 纳入缓存写 token，`formatUsd:138` 统一保留两位小数。

**用户可感知变化：**`src/lib/components/admin/RunnerUsage.svelte` 将指标改为“已记录 API 折算费用”，展示上报/估算分项；估算带 `≈`，部分费用和缺失有明确标识，列表显示模型，提示中可显示价目表更新时间及缺失原因。页面明确缺失不代表免费、金额不等同订阅实际账单。

**接口与兼容性：**新增字段是可选扩展，未改变 Hermes stats 请求路径、未增加数据库迁移。旧服务缺少这些标识时，前端仍能汇总原 `cost_usd`，但无法凭空分辨未上报的部分费用或历史计价依据。

**证据边界：**这六个文件都是前端、前端测试及文档，**没有 Hermes 服务端计价实现**。`docs/runner-accounting.md:3` 说明费用来自 Hermes `/v1/runners/stats`，价目表和 `gateway/runner_costs.py` 位于本仓库外。文档描述的续跑增量、native rollout 定价、历史恢复及外部验证记录，不是本次 Git 差异能证明已部署/已通过的事实。本次没有运行文档中的价格同步命令，也没有访问账单。

**测试变化：**`runner-stats.test.ts` 更新分项、缺失/部分标识及两位小数断言；`RunnerUsage.mount-test.ts` 更新费用解释和行展示断言。未新增外部 Hermes 测试代码，本次未执行上述前端测试。

**关系：**与附件、自动路由没有直接修复依赖，是本组中的独立统计展示修正。

### C4 — `589fb5328de28fc53b4e5ff6c94a4b5810b32354`

标题：`feat: add automatic routing workbench`。相对父提交：41 文件，+1712 / -15。

**目的与实际变化：**新增 `/auto` 统一入口，把问题分配给既有精答、讨论、协作台，结果仍由原工作台执行。新增 `routers/auto.py`、`utils/auto_routing.py`、`utils/auto_dispatch.py`、`models/auto_routes.py`；`main.py` 注册 `/api/v1/auto`。精答、讨论、团队创建内部函数新增 `on_created` 回调，在创建目标后、启动前绑定目标 ID。

**选择与执行规则：**自动模式将问题、背景、附件名称/类型交给分类模型，并非先读取附件全文进行分类。分类调用超时 25 秒，读取模型和选择的外围步骤限时 60 秒，派发限时 180 秒。初版优先可用外部任务模型，否则精答调度模型；C5 后改为优先可访问的 `gpt-chat`。异常或无效选择尝试退到精答。讨论固定单轮 compare，标准最多 3 席、精简 2 席；协作要求执行意图、功能开启及 Hermes 连接，默认先出计划，`auto_start` 默认为 false。`research=false` 对精答/讨论关闭检索，对团队通过目标文本传递禁止联网要求，不是网络层隔离。目标加背景超过既有 8000 字限制时拒绝，避免截断约束。

**持久化与恢复：**新增迁移 `backend/open_webui/migrations/versions/a7d93e5f8102_add_auto_route.py`，父 revision 为 `b8e4c2a7d913`。`auto_route` 保存 user、client_key、fingerprint、状态、模式、target_id、输入/理由 JSON 和时间；唯一键 `(user_id, client_key)` 防止同键重复创建，配有用户时间及目标索引。相同键不同输入为 409。状态从 routing 到 dispatching 再到 dispatched，取消只接受 routing 的条件更新；超过十分钟的未完成回执在读取时标为 interrupted，不会自动重跑。目标创建和回执绑定跨调用，不构成跨表原子事务，不能称作严格 exactly-once；文档已说明两者之间崩溃需人工核对原任务。

**用户可感知变化：**自动入口进入侧栏、模式条、命令面板和 Hermes 派发菜单。`AutoHome.svelte` 支持问题、最多四附件、背景、联网及预算偏好、手动指定模式、持久化请求键和轮询恢复；上传按批次顺序执行，限制同时占用的资源。聊天显示 `AutoDispatchCard`，结果页显示 `AutoRouteNotice`。手写 `/命令` 保持优先，不走自动分流；临时对话拒绝自动派发。模式交接新增 `auto` 目标，保留草稿和附件。

**接口与配置：**新增 `POST /api/v1/auto/`、`GET /api/v1/auto/`、`GET /api/v1/auto/{id}`、`POST /api/v1/auto/{id}/cancel`、`GET /api/v1/auto/target/{mode}/{target_id}`，按登录用户查询归属。表单有 `question`、必填 `client_key`、`files`、`context`、`research`、`preference`、`mode`、`auto_start`。复用既有团队、联网和任务模型配置，没有另建一套全局配置。升级须具备新表；只回滚应用可以保留新表，执行迁移 downgrade 会删除分流回执，不删除已创建的目标任务。本次未执行任何迁移。

**测试变化：**新增 `test_auto_routing.py`，覆盖只读/后续执行边界、同键去重及异内容冲突、用户隔离、附件归属、取消、三种适配器参数、自动启动选项、中断标记、SQLite 迁移往返、分类失败与聊天适配；新增 `AutoHome.mount-test.ts`、`AutoWorkbenchLink.mount-test.ts`，覆盖交接、三种跳转、断网同键重试、取消与独立侧栏入口。更新 Hermes、模式条、命令面板测试。测试含 mock 的模型/任务边界，不能视为真实 provider 和部署链路已通过。本次只对其中纯函数边界做了最小核查（第 5 节）。

**关系与当前风险：**C5 修复非法结构响应的健壮性、完善体验；C6/C7 跟进它。当前仍有 R1 路由误判，另有多 worker 容量上限的条件性风险 R2（第 4 节）。

### C5 — `dab7f6aa22fe4c15be825459fb1d98a2b02ad655`

标题：`fix: unify workbench titles and automatic routing experience`。相对父提交：41 文件，+967 / -312。实际影响超过“改标题”，包含以下模块：

| 模块 | 差异证据与最终行为 | 用户/兼容性影响 |
| --- | --- | --- |
| 共享标题和分组 | `utils/mode_chats.py:378` 新增后台 metadata 调度；精答/讨论/协作派发入口调用；团队新建聊天标记为自动标题；`models/chats.py:97` 接受未显式手动命名的中文默认标题 | 标题和分组不阻塞派发，遵守既有生成开关，生成失败/超时摘要兜底；保留手动命名及分支保护 |
| 路由模型与容错 | `utils/auto_routing.py:46` 验证响应为 dict、mode 为合法字符串；`:61` 从可访问基础模型中找 `gpt-chat`；`routers/auto.py:99` 同步用于 planner 和 routing model | 修正初版非对象/非字符串响应可能引发 `.get` 或不可哈希错误的边界；会改变同时存在 gpt-chat 与外部任务模型时的优先级；不新增配置键 |
| 历史数据读取 | `models/auto_routes.py:63` 加 `(created_at,id)` 游标、字面问题搜索与模式筛选；`routers/auto.py` 用两类批量查询读取目标标题/状态；列表问题裁到 300 字 | 服务端保留旧 offset，新增 before/q/mode/next；前端 API 包装函数从 offset 参数改为 opts 对象，当前组件同步更新；每页 30 条，前端替换上一页，避免无限追加 |
| 自动标识和页面 | `utils/auto_dispatch.py` 与 `routers/auto.py` 写聊天 meta.auto_route；`utils/chat_kinds.py`、`src/lib/utils/chat-kind.ts` 加自动及实际模式标签；旧卡片打开时补 metadata | 侧栏显示“自动 · 精答/讨论/协作”；共享视觉组件进入自动首页；旧记录按打开时补齐，不扫描全库 |
| 回填与导航 | `utils/mode_dispatch.py:294` 保存 dispatch_report，团队 outputs 保存 message_id；两个详情 API 扩展 report；`ModeDispatchCard.svelte:203` 和 `TeamChatCard.svelte:143` 使用本地历史及服务端回执 | 已生成但尚未回填时继续轮询并提供重新同步；定位走 pendingMessageReveal，消息未载入时跳转结果页；新增字段可选，旧记录仍可走历史查找 |
| 通知 | 精答/讨论来源为聊天的子任务不再自行发完成通知；`src/routes/+layout.svelte` 跳过派发确认消息 | 防止“已派发”被误报成“任务已完成”，等待真正回填通知 |
| 生图标题 | `routers/image_studio.py:154` 新增批量标题接口；`models/image_studio.py:256` 仅更新同用户、同 prompt 且仍存在的记录；Images 组件及存储类型接入 title，搜索包含标题 | 成功生成并保存后，同组画廊/历史显示短标题，原提示词保留；调用共享标题服务且要求外部文本任务模型，无可用生成结果则用提示摘要；不会把生成期间已删记录重建 |

**新增接口和存储：**`POST /api/v1/image-studio/items/title` 接受 1–20 个 ID，标题生成限时 25 秒，返回 title 与实际更新 ids；数据写入既有 JSON。分流响应增加 `title`、`routing_model`，精答/讨论 `report` 和团队 `outputs.chat_posted.message_id` 扩展结果定位。不新增迁移；不要因此误写成“本轮七笔完全无迁移”，C4 已新增表。

**测试变化：**新增 `test_workbench_metadata.py`，覆盖共享标题、关闭生成的摘要回退、手动标题及生成过程中重命名保护、中文旧默认标题；扩展 `test_auto_routing.py` 的非法响应、可见 gpt-chat、游标稳定/字面搜索、列表裁剪、旧卡片修复；扩展生图标题所有权、删除不复活、保留收藏和原 prompt、复用标题服务测试；更新团队、讨论、chat kinds、团队聊天测试。前端补固定分页/搜索及持久化回执展示用例。未增加独立 `AutoDispatchCard.mount-test.ts`。本次未执行 pytest/Vitest。

**关系：**是 C4 的修复与完善，同时把既有多个工作台的标题、通知与回填契约统一；不是 C4 的回退。C6 专门跟进团队卡片导航测试，C7 修正本笔暴露的原始 routing_model 显示。

### C6 — `9d95561dc3d25e6a52a35bd75f12533619df8350`

标题：`test: align team result navigation coverage with message reveal`。相对父提交：1 文件，+51 / -8，仅 `src/lib/components/teams/TeamStage.mount-test.ts`。

**实际变化：**测试每次设置/清理 `chatId`、`pendingMessageReveal` 和导航 mock；去掉依赖临时 DOM 节点 `scrollIntoView` 的断言，改为检验共享导航请求 `{chatId, messageId}`。补齐结果消息 fixture；增加服务端回执指向最新消息且该消息已/未在本地 history 的两种情况，分别断言消息 reveal 与 `/teams/{id}/conclusion` 跳转。

**意义与兼容性：**这是对 C5 运行时代码的测试跟进，覆盖比直接查 DOM 更稳定的模块边界。没有新增生产功能、API、配置、数据库或用户可见文案，也不是在这一笔才实现消息定位。本次未执行该挂载测试。

### C7 — `f2b4f7fb107977448ebeaf2ad21380ac661d239a`

标题：`fix: shorten routing model label in auto dispatch card`。相对父提交：1 文件，+12 / -2，仅 `src/lib/components/auto/AutoDispatchCard.svelte`。

**实际变化与用户体验：**组件 `:20` 起按 routing_model 在模型 store 中查身份，优先用 `getModelBaseName` 去掉连接名后缀；无法查到时尝试解析连接作用域 selection ID 内的 modelId，再回退原始 ID。标签增加 `truncate` 与完整显示名 tooltip。改善长 `modelref::...` 标识挤占卡片的情况。

**兼容性与测试：**只改显示，不改实际选择的模型、数据库回执或接口字段；模型未载入/不能解析时仍有字符串回退。没有测试文件变化；已有 model-display/model-identity 工具被复用。本次仅检查了差异和两个工具的上下文，未运行组件/浏览器验证。

## 3. 七笔之间的修复、补充与回退关系

| 链路 | 关系 | 汇总时应避免的误读 |
| --- | --- | --- |
| C1 → C2 | 精答附件基础能力 → 历史用户图与未提取原文的补漏，扩展为共享收集 | 不要把二者说成重复实现，也不要声称 C1 已处理所有原始文件 |
| C3 | 独立的前端费用口径修正 | 外部 Hermes 定价实现、生产账单准确性不能由这笔证明 |
| C4 → C5 | 新增自动入口与持久化回执 → 健壮性、游标分页、标题、标记、通知及回填完善 | 不要把 C5 的非对象响应缺陷继续报为当前 HEAD 问题；也不要把新表重复计入 C5 |
| C5 → C6 | 运行时导航从 DOM 滚动转向消息 reveal，测试随后与之对齐 | C6 仅测试变更，不是新增导航功能 |
| C5 → C7 | 卡片展示 routing_model → 将原始模型标识变为可读短名称 | C7 不改变路由模型优先级 |

七笔中未见显式 revert，也没有通过差异发现整项功能被回退。C5 替换旧标题及通知处理方式、C6 替换旧测试断言属于修正，不应归为功能撤销。

## 4. 问题清单（按严重程度）

本轮未确认“严重”级问题。已核查文件归属、登录用户隔离、同键去重、取消条件更新、标题写回保护、附件边界及结果定位；这不是全仓安全审计或部署验收。

### 一般 · R1：局部“不要部署”约束误杀明确的实现请求（已确认）

- **引入提交：**`589fb5328de28fc53b4e5ff6c94a4b5810b32354`；在固定 HEAD `f2b4f7fb107977448ebeaf2ad21380ac661d239a` 仍存在。
- **位置：**`backend/open_webui/utils/auto_routing.py:11`、`:15`、`:53`；调用后果见 `backend/open_webui/routers/auto.py:139`。
- **问题：**“请修复这个函数并运行测试，不要部署”明确允许修改和测试，却因 READ_ONLY 匹配到“不要部署”，在任何后续意图判断前直接判为 analysis_only。
- **为什么出错：**即使分类器已返回 `mode=team, execution_requested=true` 且团队可用，normalize_selection 也强制改为 answer 并清除执行意图。手动指定 team 的选择分支也会因模式变化抛出 HTTPException(400)，后台运行将其记录为错误回执；不是 create 接口同步返回 400。
- **验证证据：**使用两份 Git blob 中的真实纯函数分别复现：同一句话不带“不要部署”输出 team，加上后输出 answer；C4 与 HEAD 结果相同。未调用任何模型、数据库或真实任务。
- **建议：**区分全局只分析/不执行与禁止特定动作。明确允许改码且禁止部署时，应保留 team，把部署禁令传给任务；为“允许改码/禁止部署”“只审查/不改码”“后续明确执行覆盖先前只分析”增加公共决策输出测试，避免通过简单删除保护规则造成反向误派。

### 建议 · R2：三请求容量上限在多 worker 下不是原子约束（需确认部署条件）

- **引入提交：**`589fb5328de28fc53b4e5ff6c94a4b5810b32354`；HEAD 中路径仍存在。
- **位置：**`backend/open_webui/routers/auto.py:238`；`backend/open_webui/models/auto_routes.py:36`、`:78`。
- **确认事实：**count_active 与 create 使用分开的数据库会话；唯一约束仅是 `(user_id, client_key)`，不同请求键之间没有数据库级容量仲裁。
- **条件性风险：**若部署多个 worker，同一用户不同 client_key 的请求可能都先读到活动数未满，再各自创建，突破“已有 3 个问题正在分流”的限制并增加模型调用。单个 asyncio worker 里这段同步代码没有 await，不能据此断言普通单 worker 一定触发；本次没有核查生产 worker 数，也没有做多进程压力测试。
- **建议：**若 3 是跨 worker 的硬上限，使用用户级事务锁/配额记录使检查和占位原子化，并测试不同键并发提交；若只是尽力限流，文档应注明作用边界。

其他交付边界不冒充缺陷：C4 新表迁移、目标插入与回执绑定间的崩溃窗口、团队联网约束只是文本、C3 依赖仓库外费用来源，均已有直接差异或代码依据，应在汇总的兼容性/限制部分保留。未验证其生产部署状态。

## 5. 本次验证与未覆盖范围

**实际执行：**

1. `git -C /root/HaloWebUI rev-parse HEAD`、`git log -7 HEAD --format=...`，固定哈希、两类时间、时区、标题和全部父提交；`rev-parse --is-shallow-repository` 返回 false。
2. 对七笔分别执行 `git show`，对整体与 C5 等使用 `git diff`，再读取相关上下文、测试文件和调用方；附录逐笔文件列表直接从固定 Git 对象生成。
3. 用 `python3 -B` 从 `git show <rev>:backend/open_webui/utils/auto_routing.py` 读取并执行标准库纯函数。C4/HEAD 的 R1 对照均复现；HEAD 的七类非法输入均抛 ValueError，加上只分析降级场景共 **8 个边界断言通过**。这是定向最小验证，不是项目测试套件通过。
4. 按 `jev-assist` 技能，经 runner receipt bridge 对实际差异片段做 rank，并核验 R1/R2/费用范围的引用支持；两次均 `jev_available=true`，无需降级。辅助分数不作为正确性证明，R1 以直接复现为依据。未做归档分类，也未写知识库。
5. 报告结构校验通过：7 笔完整哈希/父节点/时间/标题、109 条逐笔文件条目、85 个净变更路径、10 处完整路径加行号引用、净差异 +3391/-237 均与固定 Git 对象一致，无待填占位符。`git diff --no-index --check /dev/null docs/reviews/recent-7-commits-analysis.md` 首次发现文末多余空行，移除后复查通过。

R1 可复现命令（只读 Git blob，不导入应用、不写 pyc）：

```bash
python3 -B - <<'PY'
import subprocess
repo = '/root/HaloWebUI'
path = 'backend/open_webui/utils/auto_routing.py'
for rev in ['589fb5328de28fc53b4e5ff6c94a4b5810b32354',
            'f2b4f7fb107977448ebeaf2ad21380ac661d239a']:
    ns = {}
    source = subprocess.check_output(['git', '-C', repo, 'show', f'{rev}:{path}'], text=True)
    exec(compile(source, f'{rev}:{path}', 'exec'), ns)
    for question in ['请修复这个函数并运行测试', '请修复这个函数并运行测试，不要部署']:
        result = ns['normalize_selection'](
            {'mode': 'team', 'execution_requested': True}, question=question,
            teams_available=True, discussion_available=True)
        print(rev[:7], question, result['mode'], result['execution_requested'])
PY
```

输出两版均为：无部署禁令 `team True`；加部署禁令 `answer False`。

**明确未运行：**pytest、Vitest/组件挂载、类型检查、Lint、全量测试、构建、数据库迁移、真实 provider/Hermes/上传端到端、浏览器冒烟和部署。任务是提交分析，未改业务代码；约 6GB 环境下采用 Git 静态核查与不加载应用的最小验证，避免为了文档审查启动全应用或高内存构建。提交里的测试代码和文档中的历史“已验证”描述均未当成本轮执行结果。

## 6. 给后续成员的交接

- 产物：共享 worktree 的 `docs/reviews/recent-7-commits-analysis.md`，完整路径 `/root/work/agent-teams/halo-57ff30c03c5b4f04/docs/reviews/recent-7-commits-analysis.md`。
- 汇总建议按“附件可靠性、费用可解释性、自动分流及跨工作台体验”三条主线组织；七笔完整身份和逐笔变化已记录，可直接引用。
- 必须保留选取口径：固定 HEAD 的七次提交，跨 2026-10-13/14，不是七天；全部单父提交，无合并重复计算。
- 需要给用户指出的确认问题为 R1；R2 必须带“多 worker 条件、需确认”，不得写成已发生线上故障。初版非法 JSON 结构处理已被 C5 修正，不列为现存问题。
- 不将 C6 写成生产功能，不将 C7 写成模型调度策略变化；模型优先级变化在 C5。
- 新数据库迁移在 C4；C5 只复用既有 JSON 字段。费用服务端与价格快照不在这七笔实现范围内。
- 本任务只新增报告，未修业务代码、未提交 Git commit、未 push、未切分支、未合并、未迁移或部署。运行时问题修复另行安排；本报告没有授权或执行外部发布。

## 附录：逐笔实际变更文件

以下来自 `git diff-tree --no-commit-id --name-status -r <完整提交哈希>`；`A` 为新增，`M` 为修改。每个条目归属其提交，重复出现表示后续补充，不能重复算成独立新增模块。

### C1 — `39731631238b5b691519dec86449a53d0c0aca2d`（10 文件）

```text
M	backend/open_webui/routers/answers.py
M	backend/open_webui/test/unit/test_answer_desk.py
M	backend/open_webui/utils/answer_desk.py
M	backend/open_webui/utils/mode_dispatch.py
M	docs/hermes-dispatch-modes.md
M	src/lib/apis/answers/index.ts
M	src/lib/components/answer/AnswerHome.mount-test.ts
M	src/lib/components/answer/AnswerHome.svelte
M	src/lib/components/answer/AnswerRun.mount-test.ts
M	src/lib/components/answer/AnswerRun.svelte
```

### C2 — `d83549cef5f81ab8e8b22f89a78b677489220160`（9 文件）

```text
M	backend/open_webui/routers/answers.py
M	backend/open_webui/routers/discussions.py
M	backend/open_webui/test/unit/test_answer_desk.py
M	backend/open_webui/test/unit/test_discussions_router.py
A	backend/open_webui/test/unit/test_dispatch_files.py
M	backend/open_webui/utils/agent_team_dispatch.py
A	backend/open_webui/utils/dispatch_files.py
M	backend/open_webui/utils/mode_dispatch.py
M	docs/hermes-dispatch-modes.md
```

### C3 — `122424a49ac20e8b78c6516b9f32308cde82cda9`（6 文件）

```text
A	docs/runner-accounting.md
M	src/lib/apis/hermes/index.ts
M	src/lib/components/admin/RunnerUsage.mount-test.ts
M	src/lib/components/admin/RunnerUsage.svelte
M	src/lib/utils/runner-stats.test.ts
M	src/lib/utils/runner-stats.ts
```

### C4 — `589fb5328de28fc53b4e5ff6c94a4b5810b32354`（41 文件）

```text
M	backend/open_webui/main.py
A	backend/open_webui/migrations/versions/a7d93e5f8102_add_auto_route.py
A	backend/open_webui/models/auto_routes.py
M	backend/open_webui/routers/answers.py
A	backend/open_webui/routers/auto.py
M	backend/open_webui/routers/discussions.py
M	backend/open_webui/routers/teams.py
A	backend/open_webui/test/unit/test_auto_routing.py
M	backend/open_webui/test/unit/test_hermes_agent_payload.py
A	backend/open_webui/utils/auto_dispatch.py
A	backend/open_webui/utils/auto_routing.py
M	backend/open_webui/utils/hermes_agent.py
A	docs/auto-routing-workbench.md
A	src/lib/apis/auto/index.ts
M	src/lib/components/answer/AnswerRun.svelte
A	src/lib/components/auto/AutoDispatchCard.svelte
A	src/lib/components/auto/AutoHome.mount-test.ts
A	src/lib/components/auto/AutoHome.svelte
A	src/lib/components/auto/AutoRouteNotice.svelte
M	src/lib/components/chat/Chat.svelte
M	src/lib/components/chat/MessageInput/HermesRunOptions.mount-test.ts
M	src/lib/components/chat/MessageInput/HermesRunOptions.svelte
M	src/lib/components/chat/Messages/ResponseMessage.svelte
M	src/lib/components/discuss/DiscussRoom.svelte
M	src/lib/components/layout/CommandPalette.mount-test.ts
M	src/lib/components/layout/CommandPalette.svelte
M	src/lib/components/layout/Sidebar.svelte
A	src/lib/components/layout/Sidebar/AutoWorkbenchLink.mount-test.ts
A	src/lib/components/layout/Sidebar/AutoWorkbenchLink.svelte
M	src/lib/components/layout/Sidebar/SidebarModeIcon.svelte
M	src/lib/components/scifi/ModeDock.mount-test.ts
M	src/lib/components/scifi/ModeDock.svelte
M	src/lib/components/scifi/RelayFlash.svelte
M	src/lib/components/scifi/mode-relay.ts
M	src/lib/components/teams/TeamWorkbench.svelte
M	src/lib/stores/index.ts
M	src/lib/utils/destinations.ts
M	src/lib/utils/handoff.ts
M	src/lib/utils/hermes.test.ts
M	src/lib/utils/hermes.ts
A	src/routes/(app)/auto/+page.svelte
```

### C5 — `dab7f6aa22fe4c15be825459fb1d98a2b02ad655`（41 文件）

```text
M	backend/open_webui/models/auto_routes.py
M	backend/open_webui/models/chats.py
M	backend/open_webui/models/image_studio.py
M	backend/open_webui/routers/answers.py
M	backend/open_webui/routers/auto.py
M	backend/open_webui/routers/discussions.py
M	backend/open_webui/routers/image_studio.py
M	backend/open_webui/test/unit/test_agent_teams.py
M	backend/open_webui/test/unit/test_auto_routing.py
M	backend/open_webui/test/unit/test_chat_kinds.py
M	backend/open_webui/test/unit/test_discussions_router.py
M	backend/open_webui/test/unit/test_image_studio_items.py
M	backend/open_webui/test/unit/test_team_chats.py
A	backend/open_webui/test/unit/test_workbench_metadata.py
M	backend/open_webui/utils/agent_team_dispatch.py
M	backend/open_webui/utils/agent_team_outputs.py
M	backend/open_webui/utils/agent_teams.py
M	backend/open_webui/utils/auto_dispatch.py
M	backend/open_webui/utils/auto_routing.py
M	backend/open_webui/utils/chat_kinds.py
M	backend/open_webui/utils/mode_chats.py
M	backend/open_webui/utils/mode_dispatch.py
M	backend/open_webui/utils/team_chats.py
M	docs/auto-routing-workbench.md
M	src/lib/apis/answers/index.ts
M	src/lib/apis/auto/index.ts
M	src/lib/apis/discussions/index.ts
M	src/lib/apis/image-studio/index.ts
M	src/lib/apis/teams/index.ts
M	src/lib/components/admin/Settings/Interface.svelte
M	src/lib/components/auto/AutoDispatchCard.svelte
M	src/lib/components/auto/AutoHome.mount-test.ts
M	src/lib/components/auto/AutoHome.svelte
M	src/lib/components/chat/Messages/ModeDispatchCard.mount-test.ts
M	src/lib/components/chat/Messages/ModeDispatchCard.svelte
M	src/lib/components/scifi/ModeEmblem.svelte
M	src/lib/components/teams/TeamChatCard.svelte
M	src/lib/components/workspace/Images.svelte
M	src/lib/utils/chat-kind.ts
M	src/lib/utils/image-studio-storage.ts
M	src/routes/+layout.svelte
```

### C6 — `9d95561dc3d25e6a52a35bd75f12533619df8350`（1 文件）

```text
M	src/lib/components/teams/TeamStage.mount-test.ts
```

### C7 — `f2b4f7fb107977448ebeaf2ad21380ac661d239a`（1 文件）

```text
M	src/lib/components/auto/AutoDispatchCard.svelte
```

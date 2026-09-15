# Codex 完成结果未出现在 HaloWebUI 的排查

## 生产只读证据

对象为用户报告的 Codex 运行及其 HaloWebUI 会话。具体会话标识保留在私有排查记录中，不写入公开仓库。图片只有用户提供的文字描述，未查看原图。

- Codex 在 14:43:41 成功结束，`result.md` / `last-message.txt` 已有完整回答。未重跑任务。
- `notify.json` 为 `attempted: false`、`skipped: "origin session not found"`；`notify.log` 同时记录跳过通知。
- Hermes `state.db` 中目标会话存在，来源为 `api_server`。启动命令使用内联 `--task`，没有运行 ID / `--task-file`。运行 ID 出现在随后 `process poll` 的工具结果中，旧脚本只查 `assistant.tool_calls`，无法匹配。
- terminal 结果另有 `notify_on_complete: false` 和 `notify_unsupported`：该 API 会话不支持 Hermes 原生异步进程完成通知，所以没有 gateway 通知替它补上。
- HaloWebUI 的只读数据库中只有原始用户问题和“已交给 Codex，正在运行”的 assistant 消息，没有通知 user turn、续答占位或完成回答。原始 assistant 已是 `done: true`；“正在运行”是其正文/HTML 中的文字。
- 相关时段访问日志有持续成功的聊天 GET，但没有通知 POST。未抓取生产 Socket.IO 帧；本次根本没有生成对应续答消息可供推送。
- 容器 `WEBUI_BUILD_VERSION` 为 `a6b13a964bbfca1fc34684f2cbe191808d1dab74`；关键后端源码 SHA256 与该提交一致。用户入口与本机入口的 `/_app/version.json` 同为 `1789020322356`。因此不能将此故障解释为“尚未部署上次修复”。这仍不证明用户浏览器内存中所有资源的版本，截图未提供完整网络记录。

本次具体中断为 **通知未尝试发送 → 没有持久化通知消息 → 没有触发续答**，不是有一条最新消息被页面隐藏。上次“仅发起页面执行完成回调”限制在消息状态更新之后，本次也没有完成通知能到达该限制处。没有为掩盖通知故障而恢复所有设备重复写回。

## 修复

- `integrations/hermes-runner/reclaude-notify.py`：通过工具结果与调用 ID 追溯来源，正确支持内联任务；解析启动参数，避免把引用其他运行 ID 的排障提示词认作来源；歧义时拒绝猜测；增加无副作用 `--dry-run`。
- `CodeEditor.svelte` / `editor-highlighter.ts`：`codemirror-shiki` 0.3.0 对已加载的 highlighter 会在插件构造时同步 `dispatch`。组件正在 `reconfigure` 时再次 dispatch，能够独立复现用户描述的 CodeMirror 错误。改用 Promise 初始化路径，避免重入。
- 翻译扩展、`content_main.js`、frame-bridge、`postMessage` 与 preload 相关文字不能证明本次数据链路根因；未修改这些脚本或据截图推断它们导致通知丢失。

## 验证及边界

```bash
python3 -m pytest -q backend/open_webui/test/unit/test_runner_notify_origin.py

# 用现有 Chromium，避免下载浏览器；路径按本机安装调整。
export PLAYWRIGHT_CHROMIUM_EXECUTABLE=/root/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome
python3 scripts/verify-hermes-notify-chain.py --frontend-build /tmp/halo-notify-chain-20260910/build
python3 scripts/verify-editor-highlighter.py

node_modules/.bin/tsc --noEmit --strict --skipLibCheck --target ES2022 \
  --module ESNext --moduleResolution bundler src/lib/utils/editor-highlighter.ts
git diff --check
```

通知单元回归 10 项通过；现有聊天事件和同步回归 27 项通过。针对旧宿主机脚本运行内联任务、提示词误匹配、跨会话 poll 三项回归，均失败；新脚本通过。新脚本对真实目标运行的 `--dry-run` 返回正确目标会话，原通知记录仍保持未发送状态。

本地链路脚本使用从已部署容器**只读复制**的 a6b13a9 静态页面，运行两个真实 Chromium 上下文。真实通知 HTTP handler、`start_follow_up_turn`、聊天 model 和 Socket.IO emitter 与独立 SQLite 串联；上游 Hermes/LLM 使用固定测试回复，认证与无关 API 使用本地夹具。所有浏览器网络请求限于该本地服务。

该隔离链路通过：通知来源识别、HTTP 接收、续答占位持久化、完成结果持久化、Socket.IO 广播、两台查看设备可见、断线补齐、刷新恢复、其他会话不抢路由、查看设备不发送完成回写。三次测试通知后数据库正好 8 条消息，无浏览器 pageerror。它验证的是完整前端与这些真实后端模块的集成，**不等于真实上游模型或生产端到端验收**。

CodeMirror 的真实浏览器对照：旧初始化方式复现 `Calls to EditorView.update are not allowed while an update is in progress`，高亮 token 为 0；新适配器没有该错误，更新后的正文可见且有 8 个着色 token。只构建了小型浏览器测试入口，没有全量应用构建或容器构建。

环境与夹具调整：最初 Playwright 默认查找的旧 Chromium 版本不存在，改用本机已有可执行文件；隔离 handler 的首次动态加载有 Pydantic 类型解析错误，修正测试加载器后链路通过。这些是验证环境/夹具问题，不作为生产故障证据。

## 尚未执行的操作

没有替换宿主机线上通知脚本，没有修改生产配置/数据库，没有补发这次历史通知，没有调用真实模型，没有构建容器、部署或重启服务。通知根因需要用户按 [宿主机通知脚本安装说明](../integrations/hermes-runner/README.md) 更新脚本；仅拉镜像不能修复它。CodeMirror 修复随镜像更新生效。本次历史回答不会因为只读排查自动写入聊天，需要另行明确执行恢复操作。

---

## 2026-09-15 续：真正的根因与后续修复

2026-09-10 的结论（内联任务查不到来源）只说对了一半。后续复查把三件事钉死了：

**1. 根因是落库时序竞态，不只是启动命令的形状。**
对 2026-09-10 那两个投递失败的 Codex run，用同一份 legacy `find_origin()` 在 2026-09-15
重查，**两个都能查到来源会话**（当时都查不到）。数据一直都在，是通知在 run 结束后 1 秒
就执行、而发起那一回合的工具调用行还没进 `state.db`：`20260910-124730` 那条用于反查的
poll 行比通知**晚 5 分 23 秒**落库。旧行为实际上要求“有人在 run 结束前 poll 过、且那一
回合已持久化”，于是出现“必须先看进度，自动回写才生效”的反直觉因果。

**2. Hermes 0.21 把 `process` 改名 `process_manage`，且无向后别名。**
`state.db` 里 `process` 末次出现 2026-09-14 09:08、`process_manage` 首次 16:05。
硬编码 `tool_name in ('terminal','process')` 的通知脚本在改名后**必然**反查失败。
Codex 侧看起来“没这个问题”只是采样假象：最后一个 Codex run 早于改名窗口，它用的是同一份
有 bug 的脚本；24 个历史 Codex run 里仍有 2 个 `origin session not found`。

**3. 修复：不再事后反查，改为启动时记录。**
Hermes 把发起会话的 `HERMES_SESSION_*` 桥接进每个工具子进程，所以两个 runner 在
`cmd_run()` 里就把 `origin_session_id` / `origin_platform` / `origin_source` /
`origin_chat_id` 写进 `meta.json`，并传给通知脚本；通知优先用它
（`notify.json` 的 `origin_resolved_by = "runner"`），无论是否有人 poll。
`state.db` 反查降级为兜底，两个工具名都认。

### 同批处理的三个次级风险

- **仓库副本会把修复同步回旧版本。** 2026-09-11 到 2026-09-15，
  `integrations/hermes-runner/reclaude-notify.py` 一直停在修复前版本；照旧 README 的
  `install` 命令同步一次就会静默抹掉线上修复。现在副本与宿主机脚本逐字一致，并新增
  `install.sh`：比较 `SCRIPT_VERSION`，**旧副本装不上去**（无版本号视为最旧），除非 `--force`。
- **空的 `codex-runner.env` 会静默关掉 Codex 通知。** 配置加载以前是“第一个存在的文件
  全赢”，只要有人创建了该文件却没写全两个键，Codex 的通知就会以
  `skipped: notify not configured` 结束，而 reclaude 完全不受影响。现在配置**逐键分层**，
  一个键都没提供的文件会打印日志并继续往下读；`notify.json` 增加 `config_files` /
  `config_missing`（只记路径和键名，不记值）。
- **历史 run 只做记录，不补发。** `reclaude-notify-backfill.py` 用同一套只读查找重跑历史上
  `origin session not found` 的 run，把结论写进各 run 目录的 `origin-backfill.json`；
  追不回来的写成 `"resolved": false` 和原因。它不发送任何通知（脚本里没有 HTTP 客户端），
  也不改写 `notify.json`：补发会在真实会话里制造新一轮对话，属于独立的生产写操作。

### 验证

```bash
python3 -m pytest -q backend/open_webui/test/unit/test_runner_notify_origin.py
python3 /root/.hermes/scripts/tests/test_reclaude_notify.py     # 宿主机侧，纯标准库
```

宿主机测试套件包含**两个 runner 各自的真实端到端投递**（`reclaude-run.sh` /
`codex-run.sh` 的真实脚本 + 打桩的 CLI + 本机 127.0.0.1 上的一次性 HTTP 端点），
断言 `meta.json` 的 origin 四键、`notify.json` 的 `origin_resolved_by` / `chat_id` /
`http_status`、POST body 的 `source`，以及“空 `codex-runner.env` 在前仍能投递”。
没有向真实 HaloWebUI 发送通知，没有重跑任何历史任务，没有构建或部署容器。

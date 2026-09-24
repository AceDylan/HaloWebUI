# Hermes 后台运行完成通知

宿主机上的 `reclaude-run.sh` / `codex-run.sh`（Hermes 的 reclaude / Codex 独占运行器）
跑完之后，Hermes 的 api_server 平台**无法**把结果推回 HaloWebUI 会话
（`supports_async_delivery=False`），所以由 runner 自己 POST 到
`/api/v1/hermes/notifications`。本目录是那条链路里两个宿主机脚本的**可维护副本**：

| 文件 | 作用 |
|---|---|
| `reclaude-notify.py` | 完成通知本体；两个 runner 共用，Codex 侧额外传 `--agent codex` 等参数 |
| `reclaude-notify-backfill.py` | 只读排障：对历史上“找不到来源会话”的 run 记录还能追回什么 |
| `install.sh` | 带版本护栏的安装脚本（拒绝把旧副本装到新宿主机上） |

**这些脚本住在宿主机，拉取 HaloWebUI 镜像不会更新它们。** 安装由运维/用户执行。

## 来源会话是怎么确定的

按顺序两条路，第一条成功就不会走第二条：

1. **runner 在启动时记录的来源会话**（2026-09-15 起）。Hermes 把发起会话的
   `HERMES_SESSION_ID` / `HERMES_SESSION_PLATFORM` 桥接进每个工具子进程，runner 直接写进
   `meta.json` 的 `origin_session_id` / `origin_platform`，并用 `--origin-session` /
   `--origin-platform` 交给通知脚本。`sessions.source` 只用于二次校验（查不到行时退回
   runner 记录的 platform）。`notify.json` 里 `origin_resolved_by = "runner"`。
2. **旧的反查兜底**：从 `state.db` 的工具调用溯源（只读）：
   `poll 输出里的 run 开始横幅 → process session_id → 同一会话的 terminal 结果 →
   tool_call_id → 真正的 runner 启动命令`。`origin_resolved_by = "state.db"`。

第 2 条天生脆弱，只留给 2026-09-15 之前启动的 run：
- Hermes 0.21 把 `process` 改名 `process_manage`，硬编码旧名字的版本从此全数失败
  （现在两个名字都认）；
- 通知在 run 结束后 1 秒内执行，而发起那一回合的工具调用行可能**几分钟后才落库** ——
  于是形成“只有先 poll 过进度才投递得成功”的竞态，这正是第 1 条要消灭的东西；
- `terminal(background=true)` 只返回 `Background process started`，不含 run id，
  没人 poll 就根本没有可溯源的记录。

来源有歧义或缺少可验证记录时拒绝猜测。

## 投递方式（2026-09-24 起）

- **HaloWebUI（api_server）**：POST 里同时带 `mode=display` + `content`（runner 的报告：状态行 +
  result.md，超过约 6000 字截断、保留末行额度页脚）+ `notice`（聊天里那条通知的标题），以及旧的
  `prompt`。新版 HaloWebUI 直接把报告显示成一条回复，不起模型回合；旧版忽略新字段，照旧用 `prompt`
  起一轮 hermes 去读 result.md。
- **Telegram，且 run 是用 `--detach` 启动的**（runner 环境里有 `RUNNER_DETACHED_LOG`）：用 Hermes 的
  解释器跑 `/root/.hermes/scripts/runner-deliver.py`，经脱敏后直接发到来源聊天，并以 user 角色在该
  聊天当前的会话里记一条 `[后台任务完成通知] …` 消息。`notify.json` 里是 `delivery=telegram-direct`。
- **其他情况**（非 `--detach` 的 Telegram、QQ、CLI）：主动跳过，交给 gateway 的后台进程通知。
- `RUNNER_DIRECT_DELIVERY=0`：两条新路径都关掉，回到旧行为。

## 配置文件是**分层**的

`--config-file` 可重复，按顺序**逐键分层**，先出现的文件赢：

```
codex-run.sh → --config-file /root/.hermes/codex-runner.env \
               --config-file /root/.hermes/reclaude-runner.env
```

需要的键：

```
HALOWEBUI_NOTIFY_URL=http://127.0.0.1:3000/api/v1/hermes/notifications
HALOWEBUI_NOTIFY_TOKEN=<与容器里的 HERMES_AGENT_NOTIFY_TOKEN 相同>
```

以前是“第一个存在的文件全赢”，于是**一个空的（或只写了一半的）`codex-runner.env`
会遮住能用的 `reclaude-runner.env`，Codex 的通知被静默跳过，而 reclaude 毫发无伤** ——
几乎没人会把病因联想到那个文件。现在：某个文件只提供它**确实定义且非空**的键；
一个键都没提供的文件会打印一行日志并继续往下读；`notify.json` 的 `config_files`
记录每个候选文件的路径与它提供了哪些**键名**（只有路径和键名，绝不写值）。
`$RECLAUDE_NOTIFY_CONFIG` 会**整体替换**候选列表，所以测试用的临时配置永远不会
回退到生产凭据。

## 投递重试：忙碌的会话单独计预算

HaloWebUI 的 HTTP 409 只表示**那个会话正在回合中**，而回合总会结束；5xx 则可能是一台
一直坏着的服务器。等到别人的回合结束正是这条通知要做的事，而**通知一旦放弃就永远没了**
（`reclaude-notify-backfill.py` 只记录发生过什么，从不补发）——2026-09-15 的 codex run
`20260915-193235-32b394d1` 开跑 56 秒就结束，10 次重试全部撞在忙碌会话上，结果就此丢失。

所以两类失败各花各的预算，先用完的那个结束循环，总时长仍然有界：

| 失败类型 | 预算 | 合计等待 |
|---|---|---|
| HTTP 409（会话忙） | `BUSY_RETRY_ATTEMPTS = 40` | 40 × 30s = 20 分钟 |
| 429 / 5xx / 网络错误 | `RETRY_ATTEMPTS = 10` | 10 × 30s = 5 分钟 |

其它状态码（4xx）仍然一次都不重试，直接记 `failed`。

## 安装

```bash
./install.sh                 # 装到 /root/.hermes/scripts，自动备份被替换的文件
./install.sh --dry-run       # 只看会做什么
./install.sh --target-dir DIR
```

`install.sh` 比较 `reclaude-notify.py` 里的 `SCRIPT_VERSION`（递增的 `YYYY-MM-DD[.N]`），
**旧副本装不上去**（没有 `SCRIPT_VERSION` 的副本视为最旧），除非显式 `--force`。
这条护栏是有来历的：2026-09-11 到 2026-09-15 之间，本目录的副本一直停在修复前的版本，
照着旧 README 的 `install` 命令同步一次就会把线上修复整个抹掉，而且不报任何错。

安装不改 token、不改 runner 配置、不重启任何服务；下一个启动的 run 自动使用新脚本。

## 只读诊断

```bash
# 这次通知本该投递给谁（不发 HTTP、不读凭据、不写 notify.json）
python3 reclaude-notify.py --run-id RUN_ID --run-dir /root/.hermes/codex-runs/RUN_ID \
  --status success --agent codex --tool-marker codex-run.sh --dry-run

# 历史上“origin session not found”的 run，现在还能追回哪些（默认只报告不写盘）
python3 reclaude-notify-backfill.py
python3 reclaude-notify-backfill.py --apply    # 把结论写进各 run 目录的 origin-backfill.json
```

`--dry-run` 不发 HTTP 请求、不读取通知凭据、不修改 `notify.json` 或其他运行文件。
`--state-db PATH` 可指定隔离数据库，始终只读打开。

`reclaude-notify-backfill.py` 是**记录**不是**补发**：它不发送任何通知（脚本里根本没有
HTTP 客户端），不改写 `notify.json` / `meta.json` / `result.md`，只在 run 目录里新增一个
`origin-backfill.json`；追不回来的 run 会明确写成 `"resolved": false` 和原因，
不会假装成功。补发历史通知会在真实会话里制造新一轮对话，属于独立的生产写操作，
本目录的任何脚本都不做这件事。

## 排障入口

`<run_dir>/notify.json`：

| 字段 | 含义 |
|---|---|
| `origin_resolved_by` | `runner`（启动时记录）或 `state.db`（旧的反查兜底） |
| `skipped` | `origin is telegram; gateway delivers`（非 `--detach` 启动，正常）/ `origin session not found` / `notify not configured` |
| `launch` / `delivery` | `detached` 或 `background`；直接投递时为 `telegram-direct`，并带 `message_id` / `mirrored` / `mirror_target` |
| `config_missing` | 所有候选配置文件都没提供的键名 |
| `config_files` | 查过哪些配置文件、各自提供了哪些键名（无值） |
| `attempted` / `http_status` / `delivered_at` / `failed` | 实际投递结果 |
| `attempts` / `busy_attempts` | 放弃时才写：一共试了多少次、其中多少次是会话忙（409） |

`<run_dir>/notify.log` 是同一次执行的完整日志。

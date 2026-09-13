# 不活跃对话自动归档

每个账号自己在「设置 → 界面 → 对话功能 → 归档」（路由 `/settings/interface?tab=chat`）里打开「自动归档不活跃对话」并填写天数（默认 30 天），然后点右上角「保存」。没打开的账号完全不受影响；服务端没有全局开关会替所有人归档。

前端入口在 `src/lib/components/settings/InterfacePreferences.svelte`（`chat` 分区，随该分区的「保存 / 重置」一起提交 `settings.ui.chatAutoArchive`）。`src/lib/components/chat/Settings/Interface.svelte` 是没有被任何路由挂载的旧组件，不要往那里加设置项。

代码入口：`backend/open_webui/utils/chat_auto_archive.py`（策略、扫描、恢复）、`backend/open_webui/routers/chats.py` 的 `POST /api/v1/chats/archive/inactive` 与 `POST /api/v1/chats/archive/inactive/restore`、`backend/open_webui/main.py` 的 lifespan 里启动的 `periodic_chat_auto_archive`。

## 什么算"一个月以前"

| 项 | 规则 |
|---|---|
| 时间基准 | **最后活动时间**（`chat.updated_at`：最后一条消息、改名、移动分组、取消归档都会刷新），不是创建时间 |
| 天数 | 固定按 `days × 24h` 计算（默认 30 天），不是自然月 |
| 固定（pinned）的对话 | 永不归档 |
| 已归档的对话 | 不重复处理 |
| 手动取消归档 | 取消归档会刷新 `updated_at`，所以又能保留一个周期 |
| 用「恢复自动归档的对话」恢复 | 不改 `updated_at`（列表顺序不变），但在 `meta.auto_archive.restored_at` 记录时间，扫描把它当作一次活动 |

## 存储与可恢复性

扫描只把 `archived` 置为 `True` 并写入 `chat.meta.auto_archive = {"archived_at", "days", "reason": "inactive"}`，不改 `updated_at`，不删除任何数据。手动归档的对话没有这个标记。

恢复方式：
- 「已归档对话」弹窗里逐条取消归档或「全部取消归档」（原有功能）；
- 设置页的「恢复自动归档的对话」只恢复带 `auto_archive.archived_at` 标记的对话，手动归档的不动。

标签的处理与手动归档一致：归档后没有可见对话的标签从标签列表移除，恢复时重新写回。

## 扫描节奏

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `CHAT_AUTO_ARCHIVE_SWEEP_INTERVAL` | `21600`（6 小时） | 两次扫描间隔；设为 `0` 关闭后台扫描（设置页的「立即归档」仍可用） |
| `CHAT_AUTO_ARCHIVE_STARTUP_DELAY` | `300` | 启动后首轮扫描前的等待秒数 |

扫描在应用进程内用 `asyncio.to_thread` 跑同步 DB 查询，逐个用户读取 `user.settings.ui.chatAutoArchive`，只处理 `enabled === true` 且天数在 1–3650 内的账号。单 worker 部署下不需要额外的锁；多次执行是幂等的。

## 设置页的"立即归档"

同一分区里的「立即归档不活跃对话」按钮按输入框里的天数（不需要先保存）先用 `dry_run=true` 取数量，再弹确认框显示"将归档 N 个超过 X 天没有活动的对话"，确认后才真正归档，并刷新侧栏列表。没有符合条件的对话时只提示，不弹框。「恢复自动归档的对话」同样在这里。

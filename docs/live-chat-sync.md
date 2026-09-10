# 聊天实时展示修复（2026-09-10）

本次基于远端 `main` 的 `d6172f9`，在独立工作区处理，未纳入原工作区的 Hermes 插件未提交修改及未推送提交。

## 排查证据与修改

| 问题                           | 原因                                                                                                                                      | 修复位置与行为                                                                                                                                                                                                                      |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 后台通知导致回到首页或旧会话   | `Chat.svelte` 收到 `chat:reload` 后调用无参数 `loadChat()`；浅路由新会话的 `chatIdProp` 可能为空或仍是旧 ID，`loadChat` 会改写当前聊天 ID | `Chat.svelte`、`live-chat-sync.ts`：按实际显示的聊天 ID 静默获取并合并消息，不调用路由加载、不重置输入框与模型选择；导航或卸载后丢弃旧请求                                                                                          |
| 图片有时必须刷新才出现         | 未知消息 ID 的文件事件被丢弃；部分文件事件先广播后落库；初次加载后的完成状态调整未触发 Svelte 更新                                        | `socket/main.py`：先持久化再广播；`Chat.svelte`：补齐未知消息、显式更新历史引用；合并文件时沿用生成图片的去重规则                                                                                                                   |
| 消息延迟、断网后缺失           | 只在挂载时绑定一次 socket；没有重连、前台恢复补齐；增量事件丢失后缺少恢复完整正文的机制                                                   | `live-chat-sync.ts`：监听 socket 替换、connect、visibilitychange、focus、online、pageshow，前台每 15 秒兜底、合并刷新请求、10 秒取消超时请求；`hermes_agent.py`、`middleware.py`：发送累计正文，后续帧修复漏帧                      |
| 同账号多设备互相覆盖、重复处理 | 查看设备都会执行完成回调并保存整份历史；旧快照可能覆盖后台追加的消息                                                                      | `Chat.svelte`：只有发起请求的页面执行一次完成回写；`models/chats.py`、`routers/chats.py`、`chat_snapshot.py`：用 `base_chat` 合并客户端改动和最新存储数据，保留独立新增消息、分支、图片和停止状态；事件 ID 去重；保存后通知所有设备 |

## 定向验证

所有测试单进程或单 worker 执行。存储回归使用独立内存 SQLite；后端导入使用 `/tmp/halowebui-live-sync-tests-20260910`，没有访问线上数据库。

```bash
npx vitest run src/lib/components/chat/Chat.events.test.ts \
  src/lib/utils/live-chat-sync.test.ts src/lib/utils/chat-message-errors.test.ts \
  src/lib/utils/chat-model-recovery.test.ts --maxWorkers=1 --minWorkers=1 --pool=forks

PYTHONPATH=backend DATA_DIR=/tmp/halowebui-live-sync-tests-20260910 \
DATABASE_URL=sqlite:////tmp/halowebui-live-sync-tests-20260910/test.db \
python3 -m pytest -q backend/open_webui/test/unit/test_chat_snapshot.py \
  backend/open_webui/test/unit/test_chat_snapshot_storage.py \
  backend/open_webui/test/unit/test_chat_event_delivery.py

npx tsc --noEmit --strict --skipLibCheck --target ES2022 --module ESNext \
  --moduleResolution bundler src/lib/utils/live-chat-sync.ts
git diff --check
```

另使用 Svelte `preprocess` + `compile(generate: 'dom')` 检查两个修改过的 Svelte 组件，使用 `py_compile` 检查修改过的 Python 模块。

本次定向检查结果：前端 35 项通过，后端 19 项通过；同步模块严格 TypeScript 检查、两个 Svelte 组件编译、Python 语法检查和 `git diff --check` 均通过。

`Chat.events.test.ts` 执行真实组件中的 socket 监听器与完成处理函数，替换浏览器/API 边界，避免加载整个应用。对照 `d6172f9` 的组件源码，同一组 8 项测试有 7 项失败；修复后全部通过。

现有 `test_chat_title_update.py` 执行结果：15 项通过，1 项因当前环境缺少 `opentelemetry.exporter.otlp.proto.common._exporter_metrics` 在导入阶段失败。未修改这套环境依赖，也未重复运行失败项。

## 验证边界

没有运行完整构建或全量测试，以控制约 6 GB 环境的内存使用。未调用真实模型/图片生成服务，未做真实浏览器多设备、代理断连或线上验收。未构建镜像、部署、拉取容器或重启线上服务；推送 `main` 后由已有 GitHub Actions 构建，用户自行更新。

同一字段的并发修改保留服务器上较新的值；独立消息和字段可以合并。旧版客户端没有 `base_chat`，仍走兼容保存路径，因此更新后所有设备需要加载新版前端。本次提供聊天同步和冲突保护，不提供多人同时编辑同一段文字的协同编辑功能。

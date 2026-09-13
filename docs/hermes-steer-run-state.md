# Hermes 运行结束信号与 steer 失败处理

背景：hermes 回复结束（`run.completed`）后，HaloWebUI 还会做 AGY HTML 设计等后处理（默认 30s，上限 120s），这段时间消息仍是 `done: false`。此前前端只看 `done`，所以输入框仍显示"注入指引"，而后端注册表已经清空，steer 必然 404；前端又把 404 吞掉静默入队，队列消息在回复完成后自动作为新一轮发出，改写 `history.currentId`，导致第一轮的标题写入被守卫拒绝。

## 后端

`backend/open_webui/utils/hermes_agent.py` 的 `_finalize`：

1. 收到终态事件后照旧立刻 `_unregister_run`（hermes 已结束，不假装它还能接受指引）。
2. **紧接着**通过 `chat:completion` 发一条 `{"hermes_run": {"active": false, "run_id", "steers", "pending_steer"?}}`，并用 `upsert_response_message` 持久化到消息上，再进入 AGY 后处理。最终的 `done` 事件与落库消息也带同一份 `hermes_run`。
3. `run.completed` / 状态轮询里带 `pending_steer`（hermes 在最终回复之后才收到、从未读取的指引）时，`_mark_undelivered_steers` 给对应的 steer 块打 `undelivered` 标记，渲染为引用块下追加一行"⚠️ 未送达：任务在采纳这条指引前已结束"。

`backend/open_webui/models/chats.py` 的 `update_chat_title_by_id`：自动标题的分支守卫从"currentId 必须等于来源消息且来源消息没有子节点"放宽为 `is_message_on_current_branch`——来源消息是当前消息或它的祖先即可写入。快速追问、排队消息仍在同一分支上，标题照常落库；重新生成、编辑消息产生的兄弟分支仍被拒绝。手动标题保护（`title_generation.auto_generated === false`）不变。

## 前端

- `src/lib/utils/hermes.ts` 的 `isHermesRunSteerable(message, ids, fallbackModel)`：助手消息未完成、模型是 hermes、且 `message.hermesRun.active !== false` 才可 steer。`Chat.svelte` 的 `hermesRunActive` 直接用它。
- `chatCompletionEventHandler` 把 `hermes_run` 合并进 `message.hermesRun`；`done` 时若带 `pending_steer`，把文本放回输入框（输入框为空时）并提示。
- `submitPrompt`：只有输入框正显示"注入指引"时才调 `/api/v1/hermes/steer`；hermes 拒绝（404/409）时**不再静默入队**——提示"指引未送达，输入已保留"，把当前消息本地标记为 `hermesRun.active = false`，下一次发送按钮就变成"加入队列"。
- `src/lib/apis/hermes/index.ts` 的 `steerHermesRun` 失败时抛 `HermesSteerError`（带 `status`、`detail`、`runEnded`），不再返回 `null`。

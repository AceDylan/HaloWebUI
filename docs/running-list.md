# 侧栏「运行中」：全部模式

侧栏「运行中」分组和收起侧栏时的闪电弹窗共用 `Sidebar/ActiveHermesRunsList.svelte`。以前只列 Hermes 回合和后台 runner，现在每一种在干活的东西都有一行，带模式标记：

| 标记 | 什么时候出现 | 点开去哪 |
| --- | --- | --- |
| 对话 | 普通模型正在写回复（多模型讨论也算） | `/c/{id}` |
| 生图 | 对话里正在出图；生图工作台正在生成 | 对话 / `/workspace/images?tab=workbench` |
| 精答 | 精答在挑助手、查资料或作答 | `/answer/{id}` |
| 讨论 | 讨论台在讨论或写结论 | `/discuss/{id}` |
| 协作 | 负责人做计划、等你批准、成员执行中（未完成） | `/teams/{id}` |
| 自动分流 | 正在选处理方式或创建任务 | 来源对话，或 `/auto?request={id}` |

等你批准的计划、成员在等你回答时，这一行是琥珀色并写「等你批准 / 需要处理」，也计入闪电按钮上的数字。Hermes 行和后台 runner 行不变。

## 数据

- 同一个轮询：`GET /api/v1/hermes/runs` 多了 `work`（`utils/work_activity.py`），前端写入 `workActivity` store。每行 `{kind, id, chat_id, title, href, started_at, state, note?}`。
- 对话回复来自进程内任务表：`create_task(..., kind=)` 记下类型和开始时间；`kind` 为空（普通回复）或 `image` 才算，标题、标签等回复后的后台任务（`blocks_completion=False`）不算；Hermes（`hermes`）、精答（`answer`）、讨论台（`discuss`）和派发回执（`dispatch`）有各自的行。已经由 Hermes 行、精答/讨论/协作/自动分流行代表的对话不再重复列。
- 精答 / 讨论来自 `answer_desk.LIVE` / `discussion_room.LIVE`；协作台一次查询（`AgentTeams.list_working_for_user`，最多 10 个，计划中 / 待批准 / 执行中）；自动分流查 10 分钟内仍在 routing/dispatching 的回执；生图工作台读 `client_request_id` 去重表里还没结束的生成（`active_image_runs`，带提示词前 80 字）。
- 标题只读 `chat.title` 一列（不读整段对话）。任何一部分读失败都不影响其他行。
- 普通回复结束时（`chat:completion` 带 `done`）立即从列表移除；发出消息后 1.2 秒刷新一次，不用等 10 秒轮询。

## 限制

和 Hermes 行一样是进程内状态：多 worker 部署时只看得到本进程的对话回复、精答、讨论和生图（协作台、自动分流读数据库，不受影响）。当前部署是单 worker。

## 验证

- 后端 `test_work_activity.py`：各模式各一行、跨用户隔离、派发对话不重复、标题批量、某部分失败不影响其余、生图工作台运行登记、任务记录类型和时间。
- 前端 `hermes-activity.test.ts`（轮询写入、回复结束即移除）、`ActiveHermesRuns.mount-test.ts`（模式标记、等你批准为琥珀色）。

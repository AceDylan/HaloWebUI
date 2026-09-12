# 对话分组自动归类

新对话回复结束后，后台任务在生成标题的同一节奏上（用户第 1、3、6…轮）额外发起一次轻量的任务模型调用，让模型从当前用户**已存在的顶层分组**里选一个，或者回答 `null`。模型不能创建分组，也不能把对话移出分组。

代码入口：`backend/open_webui/utils/folder_assignment.py`（规则与编排）、`backend/open_webui/routers/tasks.py` 的 `POST /api/v1/tasks/folder/completions`（模型调用）、`backend/open_webui/utils/middleware.py` 的 `background_tasks_handler`（接线）。

## 开关与配置

| 项 | 默认 | 说明 |
|---|---|---|
| `ENABLE_FOLDER_AUTO_ASSIGNMENT` | `True` | 环境变量或管理端任务配置（`/api/v1/tasks/config/update`），持久化在 `task.folder_assignment.enable` |
| `FOLDER_AUTO_ASSIGNMENT_PROMPT_TEMPLATE` | 空（用内置模板） | 支持 `{{FOLDER_OPTIONS}}`、`{{CHAT_TITLE}}`、`{{CHAT_HISTORY}}` 三个占位符 |
| `FOLDER_AUTO_ASSIGNMENT_TIMEOUT` | `30` 秒 | 单次归类调用上限，超时只计次不移动 |
| `FOLDER_MAX_ITEM_COUNT` | 沿用 | 分组已满时不移动 |

模型解析与标题完全一致：`get_task_model_id` + 管理端的「外部任务模型」。图片对话与多模型讨论同样带 `require_external_task_model`，没有配置外部文本任务模型时直接跳过。

## 默认分组

某个用户第一次触发归类且名下**一个分组都没有**、并且从未初始化过时，一次性建 6 个顶层分组（用途写在 `folder.meta.description`，供模型判断）：服务器与 Hermes 运维、HaloWebUI 开发、编程与技术问答、图片生成、资讯与热点、生活与闲聊。

初始化标记写在 `user.info.folder_auto_assignment`，每个用户只初始化一次；删掉的分组不会重建；用户自己新建的顶层分组同样参与候选；子分组第一期不参与。

## 归类规则

`chat.meta.folder_assignment` 记录 `source`（`auto` / `manual`）、`evaluations`、`last_user_message_count`、`last_message_id`。

| 对话状态 | 自动归类 |
|---|---|
| `source == manual`（侧栏「移动到分组」「移出分组」写入） | 永不 |
| 无标记且 `folder_id` 为空 | 允许，视为第一次评估 |
| 无标记但已在分组里 | 按 manual 处理，不动 |
| `source == auto` | 在有名分组间纠正；模型答 `null` 不移出 |

- 每个对话最多评估 3 次，只在标题里程碑（第 1 轮或 3 的倍数轮）触发；成功、失败、超时、无候选都计一次。
- 同一条消息重复触发按 `last_message_id` 与轮数去重，不会重复计次。
- 旧对话不批量回填：无标记且未分组的旧对话在续聊到的**下一个**里程碑开始评估，然后照常在后续里程碑最多评估 3 次（例如第 14 轮续聊 → 第 15、18、21 轮）。
- 落库先于刷新：标题落库 → 分组落库 → 只发一次 `chat:title`，前端收到后重拉聊天列表和分组树。标题被手动保护时归类照常进行并仍会刷新。
- 模型调用期间用户手动移动了对话，落库时在行锁内重读标记，手动结果保留。
- 候选只来自当前用户；模型返回的名字必须与现有分组名精确匹配（唯一时允许忽略大小写），否则视为 `null`。落库前再次校验分组仍存在、仍是顶层、未超容量。

## 回滚

- 关闭功能：设置 `ENABLE_FOLDER_AUTO_ASSIGNMENT=false`（或通过任务配置接口置 false），无需迁移。
- 代码回滚：`git revert` 对应提交。已写入的 `chat.meta.folder_assignment`、`folder.meta.description`、`user.info.folder_auto_assignment` 都是附加字段，回滚后被忽略；已归入分组的对话保留在分组里，可用侧栏菜单移出。

## 测试

```bash
cd backend
python3 -m pytest open_webui/test/unit/test_folder_auto_assignment.py

# 管道测试会导入路由与中间件，需要可写的 DATA_DIR 和可导入的向量库设置
VECTOR_DB=milvus DATA_DIR=/tmp/halo-test-data DATABASE_URL=sqlite:////tmp/halo-test-data/webui.db \
python3 -m pytest open_webui/test/unit/test_folder_auto_assignment_pipeline.py
```

# 历史记录分页：精答 · 讨论 · 协作 · 图库 · 生图历史

这几份历史会一直变长。以前每次打开都整份读出来（协作只读最新 100 个，再早的看不到），侧栏的小圆点也要读整份列表，进行中的精答 / 讨论每 4 秒把整份列表再读一遍。现在都按页读，翻到哪里读到哪里。

## 怎么读

- **一页一页，最新在前**：精答、讨论、协作每页 30 条，图库每页 48 张，生图历史每页 30 条。列表底部快到时自动读下一页，也有「加载更多」按钮；读完显示「已经到底了 · 共 N 条」。
- **翻页位置**：用上一页最后一条的（时间, id）作游标（`before=<时间>:<id>`），按「时间倒序、id 倒序」取下一页。中间有条目更新跑到最前面，也不会漏读或重复。
- **搜索和筛选在服务器上做**：搜的是全部历史，不只是已经读出来的几页。
  - 精答：标题、问题、回答摘要、助手名；
  - 讨论：同上，外加「全部 / 进行中 / 已结束」；
  - 协作：标题和目标，外加「全部 / 进行中 / 待批准 / 已完成 / 已结束」。每个筛选旁的数字由服务器一次分组统计得出，也是全部历史的数；
  - 图库：提示词、模型、标签（不搜图片地址）；「收藏」只看收藏的图片。
- **进行中的刷新只读第一页**：精答 / 讨论有进行中的每 4 秒、协作每 15 秒，只重读第一页，并到已经读出来的列表上（往下翻过的几页保留）。
- **侧栏小圆点**：精答、讨论只读「进行中」的那几条（服务器直接从内存里取，不扫历史）；协作只读在干活、等批准，以及最近两小时有变化的团队。
- **以前的协作任务补对话**：不再依赖读到哪一页，每次读列表时按「还没有对话的团队」单独查一次（没有就是一次很小的带索引查询）。
- **模板**仍然整份读：数量少，输入框的生图快捷指令也要用。

## 接口

| 列表 | 接口 | 参数 | 返回 |
| --- | --- | --- | --- |
| 精答 | `GET /api/v1/answers/` | `limit` `before` `q` `status=live\|ended` `archived` | `{items, next, total, live}` |
| 讨论 | `GET /api/v1/discussions/` | 同上 | `{items, next, total, live}` |
| 协作 | `GET /api/v1/teams/` | `limit` `before` `q` `bucket=active\|review\|done\|ended`，或 `scope=current`，或 `chat_id` | `{teams, next, total, counts}` |
| 图库 / 生图历史 | `GET /api/v1/image-studio/items/page` | `kind=gallery\|history` `limit` `before` `q` `favorites` | `{items, next}` |

`next` 为空表示到底了；`total`、`counts` 只随第一页返回。

## 代码

- 后端：`models/chats.py` 的 `page_chats_with_meta_key` / `count_chats_with_meta_key`（精答、讨论的对话按页读，只读行不读对话内容；搜索同时匹配 JSON 里的 `\uXXXX` 转义写法），`models/agent_teams.py` 的 `page_for_user` / `counts_for_user` / `list_current_for_user` / `list_without_chat`，`models/image_studio.py` 的 `page_items`。
- 前端：`utils/paged.ts`（游标、追加下一页、把刷新的第一页并进已读列表）、`common/LoadMore.svelte`，以及 `AnswerHome`、`DiscussHome`、`TeamsHome`、`workspace/Images.svelte` 和三个侧栏徽标。

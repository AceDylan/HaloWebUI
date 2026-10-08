# 分组指令、搜索定位、上下文占用、收藏

四个对话体验功能，彼此独立，可以单独回滚。

## 分组指令

侧栏分组的「···」菜单 →「分组指令」，写一段说明（项目背景、技术栈、回答偏好，最多 2 万字），保存后这个分组里每段对话回答前都会先读它。有指令的分组在名字旁边显示一个文档图标，点它也能编辑。

| 项 | 规则 |
|---|---|
| 生效范围 | 对话所在分组及其所有上级分组的指令，外层在前；子分组只是补充，不会顶掉上级 |
| 位置 | 助手设定之后、个人系统提示词之前（`add_or_update_system_message` 前置，provider 路由再把助手设定前置） |
| 不生效 | 不在分组里的对话、临时对话、生图模型 |
| 自动归组的对话 | 归进分组之后的下一轮开始生效（自动归组发生在回复结束后） |

代码：`backend/open_webui/utils/folder_instructions.py`（只查 `chat.folder_id` 一列，不读整段对话），在 `utils/middleware.py` 的 `process_chat_payload` 开头调用；字段是已有的 `folder.system_prompt`，接口是已有的 `POST /api/v1/folders/{id}/update/system-prompt`。前端 `Sidebar/Folders/FolderInstructionsModal.svelte`。

## 搜索结果定位到消息

侧栏搜索和 Ctrl+K「对话历史」的结果下面多一行命中片段（关键词高亮），点开对话后滚动到那条消息并短暂高亮。

- 后端 `utils/chat_search.py`：搜索查询本来就按消息正文匹配，这里在已经取回的行里再找一次是哪条消息，不多查数据库。优先当前分支上最早的一条；只有别的分支命中时用那条，打开时切到经过它的最新分支。
- `GET /api/v1/chats/search` 每行多了 `message_id`、`snippet`（只命中标题或标签时为空）。
- 前端：点击前把 `{chatId, messageId}` 放进 `pendingMessageReveal`（`stores/index.ts`），`Chat.svelte` 在对话加载完、滚到底之后滚到那条消息；`Messages.svelte` 的 `revealMessageId` 会把渲染窗口扩到那条消息。收藏列表打开回复也走这条路。

## 上下文占用 + 总结后在新对话继续

发送按钮左边一个小圆环，显示这段对话占了模型上下文的多少（60% 变黄、90% 变红；手机上 60% 以下不显示）。点开看数字和「总结后在新对话继续」。到 80% 时输入框上方也会提示一次，可以关掉。

- 用量：最新一条带 `usage` 的回复的 输入 + 缓存读写 + 输出 −推理 tokens，加上它之后发出的消息的估算；整段都没有用量时按字数估算（中日韩字符约 1 token，其他约 4 字符 1 token）。
- 上限：模型设置里声明的（`info.meta.context_window` / `num_ctx` 等）优先，否则按模型系列估计（`src/lib/utils/context-usage.ts` 的表，偏保守），都没有按 128k。Hermes 和生图模型不显示。
- 总结：`POST /api/v1/tasks/handoff`（`routers/tasks.py` + `utils/chat_handoff.py`）。用当前对话的模型（Hermes/生图模型时退回任务模型）读当前分支，最新的消息优先，放不下的最早几条省略并告知；新对话沿用分组、助手、模型和对话参数，开头是「总结一下「X」这段对话…」和模型写的摘要，接着问就带着前面的上下文。
- 摘要是一次非流式请求，长对话可能要几十秒；反向代理的 `proxy_read_timeout` 太短时会超时。

## 收藏

回复下方「更多」→「收藏」。收藏过的回复在复制按钮旁边显示一个实心书签，点它取消。用户菜单 →「收藏」列出所有收藏（可搜索），点一条打开对话并定位到那条回复。

- 表 `message_bookmark`（迁移 `d5e8f1a2b3c4`）：每个（用户、对话、消息）一行，保存时截一段摘录（去掉思考过程和图片，280 字）。对话标题实时读取；对话删掉后，下次打开列表时顺手清掉它的收藏；删除用户时一起删。
- 接口 `routers/bookmarks.py`：`GET /api/v1/bookmarks/`、`GET /chat/{chat_id}`（这段对话收藏了哪些消息）、`POST /`、`DELETE /chat/{chat_id}/{message_id}`、`DELETE /{id}`。

## 验证

```bash
npx vitest run src/lib/utils/context-usage.test.ts src/lib/utils/search-snippet.test.ts
npx vitest run --config vitest.dom-mount.config.ts src/lib/components/layout/Sidebar/BookmarksModal.mount-test.ts
cd backend
python -m pytest -p no:cacheprovider -q open_webui/test/unit/test_folder_instructions.py \
  open_webui/test/unit/test_chat_search_snippet.py open_webui/test/unit/test_chat_handoff.py \
  open_webui/test/unit/test_message_bookmarks.py
```

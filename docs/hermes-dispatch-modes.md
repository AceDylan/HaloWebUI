# 派发给谁：精答 · 讨论 · 协作台

Hermes 对话里输入框旁的「Hermes」按钮打开「派发给谁」。上面两排是**谁来做**：直接（Hermes 自己）、reclaude、cchclaude、anyclaude、codex、agy；下面一排是**换一种方式问**：精答、讨论、协作台——这条消息不走 Hermes，交给对应的模式，结果发回这个对话。

都只对下一条消息生效，发出后回到「直接」；消息自己以 `/命令` 开头时以消息为准，交给 Hermes（对 runner 一直如此，现在对精答、讨论、协作台也一样）。选了这三种时，「Hermes 用的模型」那一行会写明这条消息不经过 Hermes 的模型。

## 精答

- 这条消息成为一个精答：调度器（最强的文本模型）从助手库挑最合适的助手（没有就写一个），需要时先联网查资料，再由这个助手回答。
- 对话里这条消息之前说过的话（最近 10 轮，每轮最多 2000 字，合计 8000 字）作为背景交给调度器和助手；问题本身不算背景。
- 精答在自己的对话里进行，来源对话记在 run 的 `origin` 上；精答页显示「回到那个对话」。
- 侧栏历史里只有**派发它的那个对话**（名字后面带「精答」标记），和协作台一样一件事一条：精答自己的对话带 `meta.dispatched_from`（来源对话 id），不进历史列表、文件夹和历史搜索，也不再自动归组，只在精答页列出；来源对话带 `meta.mode_dispatch: ["answer"]`，侧栏据此标「精答」（`chat_kinds` 的 `answer_dispatch`），点开是这个对话本身。
- 精答只读文字：附件不会带过去，卡片会说明（要连文件一起，用讨论或协作台）。

## 讨论

- 这条消息成为讨论台的一个讨论，**按你上次讨论的设置**（席位、形式、轮数、主持人、联网、自动匹配助手）；从没讨论过，或上次的模型已经不在，就挑三个不同家族的文本模型（比如 Claude、GPT、DeepSeek 各一个）圆桌讨论，有 Claude/GPT 就由它主持，每个席位自动匹配助手。
- 背景同精答；这条消息的附件（图片和文档）放上讨论桌。
- 只有从对话派发来的那一问会发回对话；之后在讨论台里追问的不会。
- 历史同精答：只列派发它的那个对话，标「讨论」（`discuss_dispatch`，一个对话既交过精答又交过讨论时标「讨论」）；讨论自己的对话只在讨论台列出。

## 回复卡片和发回来的结果

- 那条消息的回复立即写好（没有模型调用），带 `mode_dispatch: {kind, chat_id}`，页面显示成实时卡片（`ModeDispatchCard`），样式和协作台卡片一致：头部是助手头像 / 🎯 / 💬、问题、状态和一行概要（助手、来源数；讨论的形式、几个模型、几轮、谁主持）；下面一张阶段卡，进行中带流光边框：
  - 步骤条：精答「挑助手 → (查资料) → 作答 → 发回对话」，讨论「(匹配助手) → (查资料) → 讨论 n/m → 写结论 → 发回对话」；出错或停下时停在的那一步标出来；
  - 当前在做什么（GPT-5 在从助手库挑最合适的助手 / 合同审查 在回答 / GPT-5 在发言 / Claude 在写结论；出错时是出错原因）和「已用 / 用时」；
  - 精答作答时显示回答最新写出的三行（带光标）；讨论显示每个席位和主持人在做什么（第 2 轮已发言 / 发言中 / 等待发言 / 在写结论）；
  - 写好后卡片底部是「已发回这个对话 · 看结果 ↓」/「正在发回这个对话…」/「把结果放进这个对话」；
  - 右侧「去看看 / 打开精答 / 打开讨论台」，出错或停下时是「去重试」；删掉了只留一行说明。
- 答完 / 结论写好后，结果作为一条完整回复发回这个对话，上面一行通知（`[精答结果] 「问题」由「助手」回答…` / `[讨论结论] 「问题」：3 个模型圆桌讨论（…）…`），点开「详情」可以去精答页 / 讨论台。之后的 Hermes 回合能读到它，可以接着追问。
- 对话正在回答别的消息时，每 15 秒再试一次，最多约 10 分钟；卡片在结束后 45 秒内显示「正在发回这个对话…」，之后还没到就给「把结果放进这个对话」（`POST /api/v1/answers/{id}/report-back`、`/api/v1/discussions/{id}/report-back`，同一个结果只放一次）。
- 新对话以问题命名（没有模型回合给它起名），并按普通对话的规则归组。临时对话不能派发（结果没处发回）。

## 结果在对话页上，就不推送到 Telegram

- 精答、讨论、协作的结果发回对话时，只在你**一个网页都没开**时才推送到 Telegram（和其他回复的离开推送一样）。开着对话页（哪怕不在精答页 / 讨论台 / 协作台），就不推送。精答、讨论记下派发那一刻的网页连接，那个标签页还开着也算在看。
- 协作台的 Telegram 通知（成员提问、任务失败、完成）由 Hermes 发，以前只有协作台工作台页开着时才不发。现在对话里的团队卡片在屏幕上（页面没切到后台）时，每 12 秒告诉 Hermes「在看」（它的判断窗口是 25 秒），一直到团队完成后 15 分钟（完成通知要等结论和验收）。
- 生图：生图工作台和对话里的生图本来就不会单独推 Telegram；对话里的生图回复和其他回复一样，只在没开网页时走离开推送。

## 侧栏历史的标记

- 历史列表、文件夹（对话分组）里的对话、置顶对话、搜索结果都带同一个 `kind`，名字后面标「精答 / 讨论 / 协作 / 生图」。以前文件夹和置顶列表没有带，归进文件夹的协作对话就看不到「协作」。
- 交给精答、讨论、协作台后，回复写好时再发一次 `chat:title`，侧栏马上重读列表，新对话的名字和标记一起出来。
- 这个改动之前派发出去的精答 / 讨论（历史里多出来的那一条）：列表第一次读取时补上标记（每个用户每个进程一次，`mode_dispatch.backfill`），来源对话已经删掉的不动，仍留在历史里。

## 协作台（这次的调整）

- 和精答、讨论排在同一排，三格等宽，副标题改短。
- 消息以 `/命令` 开头时不再建团队，交给 Hermes（提示里一直这么写，以前没做到）。
- 回复头部只写「协作台」，不再带上给 Hermes 选的模型（团队用不到它），也不再有「模型只管 Hermes 这一轮」这行。
- 临时对话不能交给协作台（结果没处发回）。
- 卡片文字和协作台其他地方建的卡片用同一份（`team_chats.card_text`）。
- 对话里的团队卡片：阶段在动时每 5 秒读一次；一分钟没变化改为 10 秒，五分钟没变化改为 20 秒，一有变化回到 5 秒；切回页面立即读。

## 代码

- 历史：`models/chats.py` 的 `DISPATCHED_FROM_META_KEY` / `_not_dispatched`（列表、文件夹、搜索）、`utils/chat_kinds.py`（`answer_dispatch` / `discuss_dispatch`）、`routers/folders.py`（文件夹里的对话带 `kind`）、`ChatItem.svelte`。
- 后端：`utils/hermes_agent.py` 的 `_mode_dispatch`（`team` → `agent_team_dispatch.run_team_dispatch`，`answer` / `discuss` → `utils/mode_dispatch.run_mode_dispatch`）；`routers/answers.py` 的 `open_for_chat`、`routers/discussions.py` 的 `open_for_chat` / `dispatch_setup`；两边的 `_after_done` 在有 `origin` 时调用 `mode_dispatch.report_back_later`。对话前文的切分和协作台共用 `agent_team_dispatch.split_conversation`。
- 前端：`MessageInput/HermesRunOptions.svelte`（弹窗）、`utils/hermes.ts`（`isModeDispatch`、`describeModeNotice`、`/命令` 规则、回复头部）、`Messages/ModeDispatchCard.svelte`、`Messages/HermesRunNotice.svelte`、`Chat.svelte`（`mode_dispatch` 事件）。
- 测试：`test_answer_desk.py`、`test_discussions_router.py`、`test_chat_kinds.py`、`test_hermes_agent_payload.py`、`hermes.test.ts`、`HermesRunOptions.mount-test.ts`、`ModeDispatchCard.mount-test.ts`。

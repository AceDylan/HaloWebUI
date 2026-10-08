# 派发给谁：精答 · 讨论 · 协作台

Hermes 对话里输入框旁的「Hermes」按钮打开「派发给谁」。上面两排是**谁来做**：直接（Hermes 自己）、reclaude、cchclaude、anyclaude、codex、agy；下面一排是**换一种方式问**：精答、讨论、协作台——这条消息不走 Hermes，交给对应的模式，结果发回这个对话。

都只对下一条消息生效，发出后回到「直接」；消息自己以 `/命令` 开头时以消息为准，交给 Hermes（对 runner 一直如此，现在对精答、讨论、协作台也一样）。选了这三种时，「Hermes 用的模型」那一行会写明这条消息不经过 Hermes 的模型。

## 精答

- 这条消息成为一个精答：调度器（最强的文本模型）从助手库挑最合适的助手（没有就写一个），需要时先联网查资料，再由这个助手回答。
- 对话里这条消息之前说过的话（最近 10 轮，每轮最多 2000 字，合计 8000 字）作为背景交给调度器和助手；问题本身不算背景。
- 精答在自己的对话里进行（侧栏历史里带「精答」标记，和在 /answer 发起的一样），来源对话记在 run 的 `origin` 上；精答页显示「回到那个对话」。
- 精答只读文字：附件不会带过去，卡片会说明（要连文件一起，用讨论或协作台）。

## 讨论

- 这条消息成为讨论台的一个讨论，**按你上次讨论的设置**（席位、形式、轮数、主持人、联网、自动匹配助手）；从没讨论过，或上次的模型已经不在，就挑三个不同家族的文本模型（比如 Claude、GPT、DeepSeek 各一个）圆桌讨论，有 Claude/GPT 就由它主持，每个席位自动匹配助手。
- 背景同精答；这条消息的附件（图片和文档）放上讨论桌。
- 只有从对话派发来的那一问会发回对话；之后在讨论台里追问的不会。

## 回复卡片和发回来的结果

- 那条消息的回复立即写好（没有模型调用），带 `mode_dispatch: {kind, chat_id}`，页面显示成实时卡片（`ModeDispatchCard`）：
  - 精答：调度器在挑助手 → 某某在查资料 / 在回答（下面滚动显示回答的最后两行）→ 新建了「合同审查」· 已答完；
  - 讨论：席位头像（谁在发言）、形式、第几轮、谁在发言 → 主持人在写结论 → 已有结论；
  - 右侧「去看看 / 打开精答 / 打开讨论台」；删掉了只留一行说明。
- 答完 / 结论写好后，结果作为一条完整回复发回这个对话，上面一行通知（`[精答结果] 「问题」由「助手」回答…` / `[讨论结论] 「问题」：3 个模型圆桌讨论（…）…`），点开「详情」可以去精答页 / 讨论台。之后的 Hermes 回合能读到它，可以接着追问。
- 对话正在回答别的消息时，每 15 秒再试一次，最多约 10 分钟；卡片在结束后 45 秒内显示「正在发回这个对话…」，之后还没到就给「把结果放进这个对话」（`POST /api/v1/answers/{id}/report-back`、`/api/v1/discussions/{id}/report-back`，同一个结果只放一次）。
- 新对话以问题命名（没有模型回合给它起名），并按普通对话的规则归组。临时对话不能派发（结果没处发回）。

## 协作台（这次的调整）

- 和精答、讨论排在同一排，三格等宽，副标题改短。
- 消息以 `/命令` 开头时不再建团队，交给 Hermes（提示里一直这么写，以前没做到）。
- 回复头部只写「协作台」，不再带上给 Hermes 选的模型（团队用不到它），也不再有「模型只管 Hermes 这一轮」这行。
- 临时对话不能交给协作台（结果没处发回）。
- 卡片文字和协作台其他地方建的卡片用同一份（`team_chats.card_text`）。
- 对话里的团队卡片：阶段在动时每 5 秒读一次；一分钟没变化改为 10 秒，五分钟没变化改为 20 秒，一有变化回到 5 秒；切回页面立即读。

## 代码

- 后端：`utils/hermes_agent.py` 的 `_mode_dispatch`（`team` → `agent_team_dispatch.run_team_dispatch`，`answer` / `discuss` → `utils/mode_dispatch.run_mode_dispatch`）；`routers/answers.py` 的 `open_for_chat`、`routers/discussions.py` 的 `open_for_chat` / `dispatch_setup`；两边的 `_after_done` 在有 `origin` 时调用 `mode_dispatch.report_back_later`。对话前文的切分和协作台共用 `agent_team_dispatch.split_conversation`。
- 前端：`MessageInput/HermesRunOptions.svelte`（弹窗）、`utils/hermes.ts`（`isModeDispatch`、`describeModeNotice`、`/命令` 规则、回复头部）、`Messages/ModeDispatchCard.svelte`、`Messages/HermesRunNotice.svelte`、`Chat.svelte`（`mode_dispatch` 事件）。
- 测试：`test_answer_desk.py`、`test_discussions_router.py`、`test_hermes_agent_payload.py`、`hermes.test.ts`、`HermesRunOptions.mount-test.ts`、`ModeDispatchCard.mount-test.ts`。

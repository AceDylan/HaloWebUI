# HaloWebUI 最近七次提交总结

这七笔主要在完善“带资料提问 → 选择处理方式 → 找到结果”的使用链路：补齐精答及跨工作台的附件传递，新增自动分流入口，再统一标题、历史记录、通知与结果定位；另有一项独立改动，让后台任务费用的来源与完整程度更清楚。近期开发方向是连接并完善现有精答、讨论和协作能力。

范围固定为 `f2b4f7fb107977448ebeaf2ad21380ac661d239a` 向前的七次提交，提交者时间为 **2026-10-13 至 2026-10-14（UTC+08:00）**，不是最近七天。依据共享 worktree 中的 [T1 核查报告](recent-7-commits-analysis.md)，并对锁定提交的差异及相关源码作只读抽查。用户的“总价下”按“总结一下”理解，不估算开发成本或价格。

## 七笔提交简表

按时间从旧到新排列；标题保留原文，实际变化按代码归纳。

| 短哈希 | 标题 | 实际变化 |
| --- | --- | --- |
| `3973163` | fix(answer): support document and image attachments end to end | 精答接入文档和图片：表单、聊天派发、运行记录、模型消息及页面展示携带附件；去重考虑附件差异。历史图片和未提取正文的原文件尚由下一笔补齐。 |
| `d83549c` | fix(dispatch): carry historical images and read raw document attachments | 精答、讨论、协作共用附件 ID 收集，补带当前请求历史中的用户图片；精答/讨论遇到无缓存正文的原文档时尝试本地提取，并把同步读取移到线程。 |
| `122424a` | fix(analytics): distinguish reported, estimated and partial runner costs | 前端分别汇总上报与估算费用，标明缺失和部分费用，纳入缓存写 token，金额统一两位小数；不包含仓库外 Hermes 计价实现。 |
| `589fb53` | feat: add automatic routing workbench | 新增 `/auto` 入口及 API，将请求交给既有精答、讨论或协作台；新增 `auto_route` 表，保存分流回执，支持同键去重、恢复查询及选择阶段取消。协作默认先出计划。 |
| `dab7f6a` | fix: unify workbench titles and automatic routing experience | 统一后台标题/分组，补生图标题；完善自动历史分页、搜索和模式标识，保存结果回填消息 ID，调整定位、同步及通知；补非法响应校验，并优先选择可访问的 `gpt-chat` 做分流。 |
| `9d95561` | test: align team result navigation coverage with message reveal | 仅更新团队卡片挂载测试：断言通过共享消息定位机制打开结果，并覆盖消息未载入时跳转结果页；运行时导航已在上一笔实现。 |
| `f2b4f7f` | fix: shorten routing model label in auto dispatch card | 自动分流卡片显示可读模型短名，并增加截断和提示；只改显示，不改变模型选择策略。 |

## 主要成果与前后关系

- **附件链路补齐（`3973163` → `d83549c`）：**前一笔建立精答附件能力，后一笔补上历史用户图片与未提取原文档，并统一三个工作台的收集规则。这里的“历史”限于当前请求携带的消息；不会恢复已移除文档，也不收集助手图片或普通外链图片。证据：[dispatch_files.py](../../backend/open_webui/utils/dispatch_files.py)、[discussions.py](../../backend/open_webui/routers/discussions.py) 的 `_read_raw_document`。
- **自动入口与后续体验完善（`589fb53` → `dab7f6a` → 后两笔）：**分流记录与原工作台结果建立关联，历史可搜索，卡片能根据回执定位结果。`dab7f6a` 已补上非对象响应、非字符串模式的校验；这些初版问题不再列为固定 HEAD 的未修复缺陷。`9d95561` 跟进测试，`f2b4f7f` 改善标签展示，不能分别算成新增导航功能或新的路由策略。证据：[auto_routing.py](../../backend/open_webui/utils/auto_routing.py)、[TeamChatCard.svelte](../../src/lib/components/teams/TeamChatCard.svelte)。
- **费用解释更明确（`122424a`）：**缺失不再被解释成免费，估算与部分记录有提示。金额仍是 API 折算值，不能当作订阅实际账单；外部服务是否正确计价、是否部署，无法由这七笔证明。证据：[runner-stats.ts](../../src/lib/utils/runner-stats.ts)、[费用口径说明](../runner-accounting.md)。

## 影响范围与必要待验证事项

影响覆盖附件上传/派发、自动工作台前后端、聊天标题与通知、结果导航、生图记录标题，以及管理员费用页面。升级涉及 `589fb53` 新增的数据库迁移 `a7d93e5f8102`；`dab7f6a` 未再新增迁移，不能据此说整轮没有数据库变更。

1. **已复现的路由误判（后续已修复：只禁止某个动作不再判为只分析，见 [自动分流说明](../auto-routing-workbench.md)）。**`589fb53` 引入、固定 HEAD 仍保留的只读规则，会把“请修复这个函数并运行测试，不要部署”当作只分析。T1 的纯函数对照中，无部署禁令得到 `team / true`，加上后得到 `answer / false`；T2 回查确认“不要部署”先触发只读判断，随后清除执行意图。需要区分禁止部署与禁止全部执行，并补对应回归测试。这是最小复现确认的代码问题，未据此声称已发生线上故障。位置：`backend/open_webui/utils/auto_routing.py:11、:15、:53`；复现方法见 T1 第 5 节。
2. **多 worker 容量限制为条件性风险。**活动分流计数和创建使用分开的数据库会话，唯一键只约束同一用户的同一请求键；多个 worker 同时处理不同键时，可能突破每用户 3 个活动分流的限制。尚未确认部署 worker 数，也未做并发复现，不能写成已发生故障。位置：`backend/open_webui/routers/auto.py:238`、`backend/open_webui/models/auto_routes.py:36、:78`。
3. **迁移和中断恢复仍需部署环境验证。**应核对新表迁移及恢复行为；目标创建与回执绑定之间仍有崩溃窗口，同键去重不等于保证任务严格只执行一次。回执迁移回滚会删除分流记录，不删除已创建的目标任务。证据：[迁移文件](../../backend/open_webui/migrations/versions/a7d93e5f8102_add_auto_route.py)、`backend/open_webui/routers/auto.py:158、:178`。
4. **真实链路与外部依赖仍待验证。**附件解析、模型调用、结果回填/导航及卡片显示需定向端到端检查，费用完整性需结合 Hermes 返回数据核对。另外，关闭联网对协作台只是传递任务文本约束，不是网络层隔离（`backend/open_webui/routers/auto.py:170`）。

## 核对与验证边界

T2 执行了固定哈希的 `git log -7`、七笔 `git show` 抽查及源码对照；文档的提交身份、引用路径和空白检查通过。Jev 的排序及引用辅助核验均可用；低支持度结论已回查源码和 T1 复现记录，最终以原始证据为准。上述路由复现结果来自 T1，本次未重复执行已知失败场景。

**提交分析不等于测试通过。**本次仅新增此总结，未运行 pytest、Vitest、全量构建、数据库迁移或真实服务冒烟；提交中的测试变更不代表本轮已执行通过。文档核对采用低资源静态检查，未修改业务代码，也未推送、合并或部署。

给后续成员：可按三条主线汇总；优先交接已复现的路由误判，其余保留条件与验证边界。七笔完整身份、详细文件清单及复现命令均见 T1 报告。

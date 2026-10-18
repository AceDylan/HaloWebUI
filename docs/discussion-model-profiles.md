# 讨论台主持人的模型资料

主持人安排从当前用户可用模型动态取候选（最多 40 个），每个候选带短 ID、实际的
`vision` 标记及 `profile`。资料来自该连接的模型记录 `info.meta`，不会把同名别名的
版本套用到其他连接，也不根据名字猜测版本。没有资料时版本为 `unknown`。

在「工作区 → 模型」编辑的描述 `meta.description` 会进入候选资料，可补充用途与限制。
结构化资料通过模型 API/导入的 `meta.discussion_profile` 维护，示例：

```json
{
  "version": "上游实际返回的版本标识",
  "version_source": "chat/completions response.model；上游自报，非路由配置审计",
  "verified_at": "2026-10-18",
  "family": "glm",
  "strengths": ["已验证的能力及验证范围"],
  "suggested_roles": ["方案评审", "资料归纳"],
  "limitations": ["未验证的能力或已知限制"],
  "capability_source": "最小探测或官方说明的来源"
}
```

可选 `context_window` 必须为已确认的正整数；未知时省略。版本、能力、建议角色分别
标记来源，基础探测通过不能解释为复杂任务能力排名。不要填写密钥、地址凭据或内部日志。
此对象只接受有界的白名单字段，不改变模型访问控制、看图、联网、工具开关或实际调用 ID。
说明文本作为参考资料而非指令，主持人应结合问题选互补角色，并说明选择理由。

2026-10-18 对本机个人连接中三个别名的最小文本调用得到：

| 别名 | `response.model` |
| --- | --- |
| `grok-chat` | `grok-4.7` |
| `glm-chat` | `z-ai/glm-5.3` |
| `kimi-chat` | `kimi-k3` |

这些是当日上游自报标识，不是全局固定映射；仅写入相应连接的模型元数据。上游更换
路由后应重新核验并更新日期。未进行复杂能力基准、上下文长度、价格、速度或联网测试。

验证：定向运行 `test_discussion_profiles.py`、`test_discussion_room.py` 和
`test_discussions_router.py`；覆盖未知/畸形资料、长度限制、连接隔离、敏感字段排除，以及
三个新模型的资料进入主持人提示词后仍映射回原连接 ID。

回滚：恢复旧镜像/代码；模型元数据独立于代码，旧版忽略 `discussion_profile`。
恢复元数据时只还原本次新增的 `description` / `discussion_profile`，不要覆盖其他模型设置。

## 每日核验

Hermes 纯脚本任务 `6548cf3dda6f`（“HaloWebUI 模型资料每日核验与更新”），每天北京时间
06:30 执行，cron `30 6 * * *`，无限重复，`no_agent=true`、`deliver=local`。
HaloWebUI 的定时任务页面可查看、启停及读取运行结果；不会额外向聊天平台发送消息。

源码 `scripts/refresh-discussion-model-profiles.py` 安装到
`/root/.hermes/scripts/halowebui-model-profiles.py`；所属用户配置保存在
`/root/.hermes/state/halowebui-model-profiles/config.json`，只保存容器名与用户 ID。
脚本从宿主机将自身送入正在运行的容器，容器重建不会丢失任务实现。

核验范围为当前七个别名：GPT、DeepSeek、Claude、Gemini、Grok、GLM、Kimi 的 `*-chat`。
逐个使用各自的原生连接协议（含 GPT 的 Responses 模式），无 HaloWebUI 自动备用切换。
一次请求检查结构化版本字段、整数求和、中文摘要要点和基础 Python 表达式结果；每天最多
七次探测，每次等待上限 90 秒，仍有少量上游调用费用。调度本身不启动代理推理任务。

只通过模型 API 更新 `description` / `discussion_profile`。保留启用状态、调用别名、
密钥、备用模型及权限设置；用户自行修改的描述不会被自动覆盖。探测失败时保留上次
成功的版本、核验日期及能力证据，添加最新失败状态；返回具体版本但部分题未通过时，
只记录本次实际通过的项目，不将部分成功当成全部通过。版本变化后清除旧上下文容量声明。
能力资料始终限于基础探测，不代表完整基准测试、复杂任务排名或官方能力认证。

宿主机和容器内均加互斥锁，容器进程有 15 分钟总超时。每次写入前在数据卷
`/app/backend/data/.model-profile-refresh/` 保存字段级快照（保留最近 30 份），保存后执行
API 读回核对；单模型失败继续处理其余模型，最终非零退出让定时任务显示失败。
错误仅输出类型/HTTP 状态码，凭据不进入脚本、报告、快照或知识库。

离线验证（不调用模型、不操作真实数据库）：

```sh
python3 scripts/tests/test_refresh_discussion_model_profiles.py
```

覆盖四种原生请求/响应形态、拒绝把模型自述当版本证据、失败保留旧证据、版本变更、
部分失败继续执行、API 保存读回和字段回滚。维护脚本后重新测试，再安装运行副本。

暂停每日核验：`hermes cron pause 6548cf3dda6f`。单次回滚：先暂停任务，运行
`python3 /root/.hermes/scripts/halowebui-model-profiles.py --restore <快照文件名>`。
回滚仅还原本任务写入的两项字段；若资料已经被再次编辑，会拒绝覆盖，需要人工核对。

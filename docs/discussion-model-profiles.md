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

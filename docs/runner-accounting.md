# 后台任务费用口径

数据分析的后台任务页由 Hermes `/v1/runners/stats` 提供费用。HaloWebUI 只汇总，不重新定价。
所有金额均为美元 API 折算值，不能视为订阅账单或含中转折扣的实际扣费。

- 上报费用：读取执行器结果。旧 Claude 续跑的会话累计费用减去同会话父任务基线；新版已经记录本次增量，不再重复相减。无法核对基线时显示缺失。
- 模型估算：Hermes `gateway/runner_costs.py` 读取实际记录的模型与用量，再查询 `$HERMES_HOME/runner-prices.json`。不按执行器名称固定单价，也不使用今天的默认模型推测历史模型。
- Codex：从 native rollout 的逐请求用量、模型和时间确定任务归属；对缓存、优先级（记录存在时）和长上下文档位计价。续跑和失败任务不依赖最终 result 文件。
- AGY：保留启动/事件中的模型；历史累计用量减同会话父任务用量。只有总用量、而模型价格存在长上下文档位时，不猜测请求大小。
- Claude 中断：对已写入事件的消息用量按消息 ID 去重；已有 result 费用与其后的消息用量分别处理。已恢复金额标记为部分费用。
- 没有模型、价格、用量或可靠续跑基线时，保留缺失原因，不能当作免费。部分请求可计价时仅汇总已知部分并标明不完整。

价格快照通过只读同步更新，修改后下次查询生效，无需重新编译：

```sh
python3 /root/.hermes/scripts/runner-prices-sync.py --host hk-vps
```

该命令通过已有 `vpsctl` 连接读取 CCH `model_prices`，并只为没有直接价格、且最近账务记录仅对应一个模型的别名建立映射。快照不包含凭据；历史用量按当前快照折算，UI 提供更新时间。它不是历史账单价格版本库，也不保证恢复没有上报的请求。

验证使用定向 `runner-stats.test.ts`、`RunnerUsage.mount-test.ts` 及 Hermes `test_runner_costs_local.py`。发布通过 GitHub Actions 镜像构建；6GB 运行主机不进行本地全量构建。

回滚时同时恢复前端镜像及 Hermes `runner_dispatch.py`/`runner_costs.py`；历史任务文件未被改写。运行前备份位于 `/root/.hermes/backups/runner-costs-20261013/`。

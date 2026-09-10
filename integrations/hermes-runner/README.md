# Hermes 后台运行完成通知

`reclaude-notify.py` 是宿主机 Codex / reclaude runner 共用通知脚本的可维护副本，兼容现有 runner 参数与配置文件。它不运行 Codex、不重做任务，仅定位启动会话并向 HaloWebUI 的 `/api/v1/hermes/notifications` 发送完成通知。

## 为什么需要更新宿主机脚本

内联 `codex-run.sh run --task '…'` 在启动后才生成运行 ID。旧脚本要求启动命令同时包含脚本名和运行 ID，因而查不到来源；后续排障提示词若引用了这个 ID，又可能误匹配其他会话。

新脚本沿以下关联查找唯一来源：

`process poll 输出中的运行开始标记 → process session_id → 同一会话的 terminal 结果 → tool_call_id → 实际 runner 启动命令`

显式 `--run-id`、`--task-file`、`answer <parent-run>` 仍可使用，但按参数解析，不再匹配提示词里的引用。来源有歧义或缺少可验证记录时拒绝猜测；Telegram 等来源仍交由 gateway 处理。不能保证没有启动记录、也没有任何运行输出记录的任务能被追溯。

**该脚本位于宿主机，拉取 HaloWebUI 镜像不会更新它。** 安装由运维/用户执行；本次排查没有替换线上脚本、改动配置或补发历史通知。

在包含本文件的仓库 checkout 内，可保留旧脚本后安装：

```bash
cp -pn /root/.hermes/scripts/reclaude-notify.py /root/.hermes/scripts/reclaude-notify.py.before-origin-fix
install -m 755 integrations/hermes-runner/reclaude-notify.py /root/.hermes/scripts/reclaude-notify.py
```

不需要修改现有 token、runner 配置或 Codex 推理等级。新 runner 完成时会加载更新后的脚本。

## 只读诊断

```bash
python3 integrations/hermes-runner/reclaude-notify.py \
  --run-id RUN_ID \
  --run-dir /root/.hermes/codex-runs/RUN_ID \
  --status success --agent codex --tool-marker codex-run.sh --dry-run
```

`--dry-run` 不发 HTTP 请求、不读取通知凭据、不修改 `notify.json` 或其他运行文件。`--state-db PATH` 可指定隔离数据库，始终按只读方式打开。诊断不会补发该次通知；补发属于独立的生产写入操作，本次未执行。

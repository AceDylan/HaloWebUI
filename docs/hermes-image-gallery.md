# Hermes GPT Image 自动入库

Hermes 的 `image_gen_provider.success_response()` 发出 `image_generated` 完成事件，
`halowebui-teams/gallery.py` 接收 GPT Image 系列（包括 `chatgpt-image-latest`）的成功结果。
这个事件在 provider 层，因此普通对话、CLI、定时任务、原生子代理、协作成员、结论配图和直接调用
Hermes provider 的脚本都走同一入口。失败请求和其他生图模型不入库。
绕过 Hermes provider、自行请求外部 API 的任意脚本不在这个完成事件范围内。

## 数据流

1. 完成事件只做本地复制，把图片和元数据放入 `$HERMES_HOME/halo-image-outbox/`。
   不在生图返回前等待 HaloWebUI 网络请求。图片不再依赖 Hermes 临时缓存。
2. 已有协作插件网关 bridge 每轮处理最多 4 张，经 `POST /api/v1/teams/hermes/images` 导入。
   正常约在下一次 8 秒轮询入库；网络失败保留文件，后续轮询重试。
3. 服务端校验网关密钥、账户、模型、图片内容，写入已有文件存储和 `image_studio_item`。
   只写 gallery，不写生图工作台 history；存入提示词、模型、尺寸、时间及可确认的来源链接。
4. 图片路径的 SHA-256 作为生成事件 ID，同一生成重复通知/补传不会重复导入。
   已传条目保留 `.sent` 小收据并删除待传图片；服务端文件上的 `gallery_recorded` 收据
   保证图库删除/收藏后的重试不会重新插入或覆盖用户编辑。
5. 协作结论配图标记 `gallery_queued` 后跳过原来的单独复制入口；捕获未成功时仍用原入口。

图片限 32 MiB，接受 PNG/JPEG/WebP；较大的 PNG 复用既有 WebP 压缩策略。
导入鉴权复用该用户在 HaloWebUI 配置的 Hermes 连接密钥，不增加公开上传接口。

## 配置与归属

在已有 `$HERMES_HOME/halo-teams.json` 添加（不改现有 halowebui/telegram 配置）：

```json
{
  "image_gallery": {
    "enabled": true,
    "default_owner": "<HaloWebUI 用户 ID>"
  }
}
```

- 协作任务：使用任务所有者；结论配图通过 ContextVar 显式传递，避免并行任务串号。
- Telegram：使用已有 `telegram.owners` 绑定，未绑定者保留待传，绑定后重试。
- HaloWebUI 对话：服务端从 API session/chat ID 查真实聊天所有者，并确认其 Hermes 密钥相同。
- CLI、无来源定时任务和直接调用：使用显式 `default_owner`，不猜第一个管理员。
- 来源聊天/协作任务已删除时，图片仍保存在已授权账户，省略失效导航。

本机现有 Telegram 绑定只有一个 HaloWebUI 账户，部署时将它设为默认归属。
每个 Hermes profile 独立配置。网关需要启用 `halowebui-teams` 和其 bridge；
网关停机期间产生的图片先保留在队列，恢复后补传。不扫描或导入历史缓存。

## Hermes 完成事件补丁

通用完成事件补丁保存在 `integrations/hermes-patches/image-generated-hook.patch`，
只扩展 Hermes 的通用插件事件，不在 Hermes core 内写 HaloWebUI 特例。
安装目录的 `agent/image_gen_provider.py`、`hermes_cli/plugins.py` 需要此补丁：

```bash
git -C /usr/local/lib/hermes-agent apply --check /root/HaloWebUI/integrations/hermes-patches/image-generated-hook.patch
git -C /usr/local/lib/hermes-agent apply /root/HaloWebUI/integrations/hermes-patches/image-generated-hook.patch
```

已经应用时不要重复执行。Hermes 升级后需检查该事件仍存在，并运行下列最小验证；
仓库保留 `integrations/hermes-patches/test_image_generated_hook.py` 可复制到 Hermes 的 `tests/agent/`。

## 验证

- Hermes：`HERMES_TEST_WORKERS=1 HERMES_TEST_FILE_RETRIES=0 scripts/run_tests.sh tests/agent/test_image_generated_hook.py`。
- 插件：Hermes venv 中运行 `python -m pytest integrations/hermes-plugin/halowebui-teams/tests/test_gallery.py integrations/hermes-plugin/halowebui-teams/tests/test_images.py -q`。
- 后端：应用依赖环境运行 `python -m pytest backend/open_webui/test/unit/test_hermes_image_gallery.py -q`。
  该测试使用临时 SQLite 和文件目录，不写生产数据。
- 回归：`test_agent_teams.py -k 'hermes or gallery or illustration'`。

## 停用与回滚

先将 `image_gallery.enabled` 设为 false 停止捕获和补传；队列和已经入库的图片不删除。
恢复旧插件代码及后端文件，重启 HaloWebUI；还原 Hermes 完成事件补丁后走
`systemctl --user reload hermes-gateway` 的优雅重载。停止时不要清理待传队列。
本次后端通过只覆盖三个 Python 文件的 Docker 增量镜像部署，不需要前端构建或数据库迁移。
旧镜像保留为 `dylanha009/halowebui:before-hermes-gallery-20261010`。

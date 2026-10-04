# Hermes 会话文件上传

选择 Hermes 模型时，聊天附件按原文件上传（`POST /api/v1/files/?process=false`），不要求先通过 HaloWebUI 的文档提取器或向量索引。与 Hermes 网关一致，不按文件扩展名或 MIME 限制原文件存储：压缩包、音视频、Office/PDF、代码和未知二进制类型都可以作为附件交给 Hermes。文件选择、拖拽、Google Drive 和 OneDrive 使用同一策略。

Hermes 适配器按文件 ID 检查归属，再把共享数据目录中的原文件路径加入本轮输入。能上传表示 Hermes 可以访问原文件；具体解压、转录、解析能力取决于 Hermes 的工具和环境。图片继续使用已有的图片上传与预览流程，普通模型和知识库继续使用现有文档处理流程。登录、上传权限与页面配置的大小限制继续生效。

普通模型、多模型讨论台同样不因格式拒绝上传：文档解析读不了的文件（视频、音频、7z/rar、未知二进制）按原文件保存，返回非阻塞提示 `stored_as_raw_attachment`，文件 `meta.raw_attachment=true`；发消息时模型在 `current_chat_resources` 里看到它的名称、类型、大小（`access: metadata_only`），一个附件读不了不再影响同轮其它附件。zip、tar（含 .tar.gz/.tgz 等）会读出目录和其中的文本文件（单个 5 万字、合计 20 万字封顶，不落盘）。选中能看图的模型上传视频时，浏览器另抽 6 帧拼成一张带时间戳的「画面拼图」作为图片附上（Hermes 不需要，直接打开原视频）；浏览器解不了的编码就只附原视频。管理员配置了允许扩展名（`RAG_ALLOWED_FILE_EXTENSIONS`）时仍按名单拒绝；嵌入/解析服务故障等真实错误仍会让上传失败。

部署时需要让 Hermes 能访问 HaloWebUI 的数据卷；自动识别挂载失败时，可设置 `HERMES_AGENT_HOST_DATA_DIR` 为数据卷在 Hermes 主机上的路径。

验证：

```bash
npx vitest run src/lib/components/chat/MessageInput.rawFiles.test.ts src/lib/apis/files/upload-progress.test.ts src/lib/utils/file-upload-errors.test.ts --maxWorkers=1 --minWorkers=1
cd backend
python -m pytest -p no:cacheprovider -q open_webui/test/unit/test_file_upload_diagnostics.py open_webui/test/unit/test_archive_loader.py
```

后端测试使用隔离数据目录与 SQLite，不要指向生产数据库。GitHub Actions 已包含原文件上传回归测试，并在测试通过后构建发布镜像。本机只拉取发布镜像部署，无需编译。

回滚：恢复上一版镜像并用部署目录的 `docker compose up -d --no-build --pull never` 重建 HaloWebUI。无需迁移数据库或删除已上传附件。

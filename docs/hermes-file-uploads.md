# Hermes 会话文件上传

选择 Hermes 模型时，聊天附件按原文件上传（`POST /api/v1/files/?process=false`），不要求先通过 HaloWebUI 的文档提取器或向量索引。与 Hermes 网关一致，不按文件扩展名或 MIME 限制原文件存储：压缩包、音视频、Office/PDF、代码和未知二进制类型都可以作为附件交给 Hermes。文件选择、拖拽、Google Drive 和 OneDrive 使用同一策略。

Hermes 适配器按文件 ID 检查归属，再把共享数据目录中的原文件路径加入本轮输入。能上传表示 Hermes 可以访问原文件；具体解压、转录、解析能力取决于 Hermes 的工具和环境。图片继续使用已有的图片上传与预览流程，普通模型和知识库继续使用现有文档处理流程。登录、上传权限与页面配置的大小限制继续生效。

部署时需要让 Hermes 能访问 HaloWebUI 的数据卷；自动识别挂载失败时，可设置 `HERMES_AGENT_HOST_DATA_DIR` 为数据卷在 Hermes 主机上的路径。

验证：

```bash
npx vitest run src/lib/components/chat/MessageInput.rawFiles.test.ts src/lib/apis/files/upload-progress.test.ts --maxWorkers=1 --minWorkers=1
cd backend
python -m pytest -p no:cacheprovider -q open_webui/test/unit/test_file_upload_diagnostics.py
```

后端测试使用隔离数据目录与 SQLite，不要指向生产数据库。GitHub Actions 已包含原文件上传回归测试，并在测试通过后构建发布镜像。本机只拉取发布镜像部署，无需编译。

回滚：恢复上一版镜像并用部署目录的 `docker compose up -d --no-build --pull never` 重建 HaloWebUI。无需迁移数据库或删除已上传附件。

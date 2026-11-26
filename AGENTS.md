# HaloWebUI Agent 协作与发布约定

## 严禁在 6 GB 本机服务器执行构建

- **禁止在本机运行** `npm run build`、`npm run build:full`、`npm run build:debug`、`npx vite build`、`docker build`、`docker buildx build`、`docker compose build`、`docker compose up --build`、`make startAndBuild`、`make update`。
- 原因：本机仅 4 核 / 6 GB 内存，且 runner 进程受限在约 1.5 GB 内存 cgroup 内；前端 `vite build` 峰值约 4 GB，会卡死/OOM 并污染 `backend/open_webui/static/`。
- 仓库已在 `package.json`（`scripts/check-build-env.mjs`）和 `vite.config.ts` 中加入低内存硬拦截；**禁止私自加 `ALLOW_LOCAL_BUILD=1` 绕过**（该变量仅供 `Dockerfile` 与 GitHub Actions 使用）。

## 正确的验证与发布流程

1. **本地验证（轻量定向）**：
   - 前端单测：`npx vitest run <受影响的 .test.ts>`
   - 前端组件挂载测试：`npx vitest run --config vitest.dom-mount.config.ts <受影响的 .mount-test.ts>`
   - 类型检查：`npx svelte-check --tsconfig ./tsconfig.json --threshold error`（仅在需要时）
   - 后端单测：使用隔离临时目录 / 隔离容器跑受影响的 `pytest` 文件，禁止直连生产数据库。
   - 若确实需要发布前完整试编且家里电脑在线（`pc status` 为 `ready`），通过 `pc-repo` 分流到 PC，不在本机跑。
2. **构建镜像**：推送到 `origin/main`，由 GitHub Actions `Docker Image CI`（`.github/workflows/docker-image.yml`）自动执行测试并构建推送 `dylanha009/halowebui:custom`。
3. **部署上线**（仅在用户明确要求「按发布流程做」或明确授权部署时）：
   - `gh run watch -R AceDylan/HaloWebUI <RUN_ID> --exit-status --interval 15` 等待 CI 全绿；
   - `sh /root/work/halo-hermes-autopilot/deploy.sh <short_sha>` 拉取镜像并核验 `health=healthy` 与 `WEBUI_BUILD_VERSION`；
   - 核验 `/health` 与目标路由返回 HTTP 200 及容器内构建产物，清理本次临时产物并确保 `git status` 干净。

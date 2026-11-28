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

## 折叠屏 / 小平板（vivo X Fold6 内屏）适配

- 内屏接近正方形（物理 2312×2504），按 **小平板** 设计：不要当放大的手机，也不要直接套 PC 横屏布局。以 CSS px 布局，按**可用宽度**判断，不按横竖屏判断（Hub 内嵌、分屏和小窗时可用宽度可能只有手机那么宽）。
- 断点参考：`<600` 手机单栏；`600–899` 折叠屏 / 小平板（双列）；`900–1199` 平板 / 紧凑桌面；`≥1200` 完整桌面（侧栏 + 多列）。600–900 是最容易被忽略、最值得专门优化的区间；折叠屏上不要同时摆宽侧栏、多列表格和详情面板。
- 用 Grid / Flex / 百分比 / `minmax()`，避免固定宽高；移动端高度优先 `100dvh`；关键操作不能只靠 hover。
- **动效按指针判断，不只按宽度**：内屏 ≥768px 会进桌面布局，但它是触屏。无限循环的 SVG 描边 / 渐变 / `stroke-dashoffset` / `background-position` / `drop-shadow` 动画每帧都要重绘，在 Fold6 上会拖垮外层 Hub（侧栏闪烁，见协作台泳道 2026-11-28 修复）。这类动效在 `(prefers-reduced-motion: reduce), (max-width: 767px), (hover: none) and (pointer: coarse)` 下一律关闭。
- 测试视口：手机 390×844、Fold6 外屏 373×843、内屏 771×835、内屏横屏 835×771、平板 1024×768、PC 1440×900（Fold6 的 DPR 3 是假设，真机用 `innerWidth/innerHeight/devicePixelRatio` 校正）。Playwright 里折叠屏要开 `has_touch` / `is_mobile`。
- 详细规范：Obsidian `知识库/折叠屏与小平板 Web 适配规范（2026-11-28）.md`。

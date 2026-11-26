import { readFileSync } from 'node:fs';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

export const MIN_BUILD_MEMORY_BYTES = 10 * 1024 ** 3; // 10 GiB (excludes 6 GiB VPS & 1.5 GiB runner cgroups; allows 16 GiB PC/CI)
const MAX_SANE_CGROUP_LIMIT = 1024 ** 4; // 1 TiB; kernel uses huge sentinel values when unlimited

/**
 * Read the effective Linux cgroup memory cap in bytes, or null when unlimited / unavailable.
 * @returns {number | null}
 */
export const readCgroupMemoryLimitBytes = () => {
	const candidates = [
		'/sys/fs/cgroup/memory.max', // cgroup v2
		'/sys/fs/cgroup/memory/memory.limit_in_bytes' // cgroup v1
	];
	for (const file of candidates) {
		try {
			const raw = readFileSync(file, 'utf8').trim();
			if (!raw || raw === 'max') continue;
			const parsed = Number.parseInt(raw, 10);
			if (Number.isFinite(parsed) && parsed > 0 && parsed < MAX_SANE_CGROUP_LIMIT) {
				return parsed;
			}
		} catch {
			// Ignore missing cgroup files on non-Linux or older kernels.
		}
	}
	return null;
};

/**
 * @param {number} bytes
 * @returns {string}
 */
const formatGiB = (bytes) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;

/**
 * Evaluate whether running a local frontend production build is safe in this environment.
 * @param {{
 *   env?: Record<string, string | undefined>;
 *   totalMemBytes?: number;
 *   cgroupLimitBytes?: number | null;
 *   minMemoryBytes?: number;
 * }} [options]
 * @returns {{ allowed: boolean; reason: string }}
 */
export const evaluateBuildEnvironment = (options = {}) => {
	const env = options.env ?? process.env;
	const totalMemBytes = options.totalMemBytes ?? os.totalmem();
	const cgroupLimitBytes =
		options.cgroupLimitBytes !== undefined
			? options.cgroupLimitBytes
			: readCgroupMemoryLimitBytes();
	const minMemoryBytes = options.minMemoryBytes ?? MIN_BUILD_MEMORY_BYTES;

	if (env.ALLOW_LOCAL_BUILD === '1' || env.ALLOW_LOCAL_BUILD === 'true') {
		return { allowed: true, reason: 'ALLOW_LOCAL_BUILD is set' };
	}

	if (env.NO_LOCAL_BUILD === '1' || env.NO_LOCAL_BUILD === 'true') {
		return {
			allowed: false,
			reason:
				'Blocked by NO_LOCAL_BUILD=1: 本环境已禁止本机构建 HaloWebUI 前端。本地请只跑定向 vitest / svelte-check；镜像由 GitHub Actions (Docker Image CI) 自动构建（或 PC 在线时用 pc-repo）。'
		};
	}

	if (env.CI === 'true' || env.CI === '1' || env.GITHUB_ACTIONS === 'true') {
		return { allowed: true, reason: 'CI environment detected' };
	}

	const effectiveBytes =
		cgroupLimitBytes !== null ? Math.min(totalMemBytes, cgroupLimitBytes) : totalMemBytes;

	if (effectiveBytes < minMemoryBytes) {
		const limitDetail =
			cgroupLimitBytes !== null && cgroupLimitBytes < totalMemBytes
				? `cgroup 上限 ${formatGiB(cgroupLimitBytes)}，宿主机 ${formatGiB(totalMemBytes)}`
				: `宿主机内存 ${formatGiB(totalMemBytes)}`;
		return {
			allowed: false,
			reason: [
				`[check-build-env] 已拦截本机前端构建：当前可用内存低于 ${formatGiB(minMemoryBytes)}（${limitDetail}）。`,
				'HaloWebUI 的 vite build 峰值内存接近 4 GiB，在 6 GiB 服务器或 1.5 GiB runner cgroup 内会卡死/OOM 并污染 backend/open_webui/static/。',
				'请改为：',
				'  1. 本机只运行受影响的定向单测 / mount 测试（npx vitest run ...）或类型检查；',
				'  2. 推送到 GitHub，由 Docker Image CI 自动构建发布镜像（按发布流程做时等待 CI 全绿后执行 deploy.sh）；',
				'  3. 若需发布前试编且家里电脑在线（pc status -> ready），使用 pc-repo 分流到 PC；',
				'  4. 仅在用户明确授权本机构建时才使用 ALLOW_LOCAL_BUILD=1 跳过。'
			].join('\n')
		};
	}

	return { allowed: true, reason: `sufficient memory (${formatGiB(effectiveBytes)})` };
};

/**
 * Throw or exit immediately when local builds are not permitted.
 * @param {Parameters<typeof evaluateBuildEnvironment>[0] & { exitOnBlock?: boolean }} [options]
 */
export const assertBuildAllowed = (options = {}) => {
	const result = evaluateBuildEnvironment(options);
	if (!result.allowed) {
		console.error(result.reason);
		if (options.exitOnBlock !== false) {
			process.exit(2);
		}
		throw new Error(result.reason);
	}
	return result;
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	assertBuildAllowed();
}

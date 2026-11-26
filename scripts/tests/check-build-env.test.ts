import { describe, expect, it } from 'vitest';
import {
	MIN_BUILD_MEMORY_BYTES,
	evaluateBuildEnvironment
} from '../check-build-env.mjs';

const GiB = 1024 ** 3;

describe('check-build-env', () => {
	it('blocks on a 6 GiB host without CI or override', () => {
		const res = evaluateBuildEnvironment({
			env: {},
			totalMemBytes: 5.8 * GiB,
			cgroupLimitBytes: null
		});
		expect(res.allowed).toBe(false);
		expect(res.reason).toContain('已拦截本机前端构建');
		expect(res.reason).toContain('Docker Image CI');
	});

	it('blocks when inside a 1.5 GiB runner cgroup even if host RAM is larger', () => {
		const res = evaluateBuildEnvironment({
			env: {},
			totalMemBytes: 16 * GiB,
			cgroupLimitBytes: 1.5 * GiB
		});
		expect(res.allowed).toBe(false);
		expect(res.reason).toContain('cgroup 上限 1.5 GiB');
	});

	it('allows on a 16 GiB workstation / home PC without low cgroup cap', () => {
		const res = evaluateBuildEnvironment({
			env: {},
			totalMemBytes: 16 * GiB,
			cgroupLimitBytes: null
		});
		expect(res.allowed).toBe(true);
	});

	it('allows in CI / GitHub Actions regardless of reported memory', () => {
		expect(
			evaluateBuildEnvironment({
				env: { CI: 'true' },
				totalMemBytes: 4 * GiB,
				cgroupLimitBytes: 1.5 * GiB
			}).allowed
		).toBe(true);
		expect(
			evaluateBuildEnvironment({
				env: { GITHUB_ACTIONS: 'true' },
				totalMemBytes: 4 * GiB,
				cgroupLimitBytes: 1.5 * GiB
			}).allowed
		).toBe(true);
	});

	it('allows explicit ALLOW_LOCAL_BUILD=1 (used by Dockerfile)', () => {
		const res = evaluateBuildEnvironment({
			env: { ALLOW_LOCAL_BUILD: '1' },
			totalMemBytes: 4 * GiB,
			cgroupLimitBytes: 1.5 * GiB
		});
		expect(res.allowed).toBe(true);
	});

	it('blocks explicit NO_LOCAL_BUILD=1 even on large hosts', () => {
		const res = evaluateBuildEnvironment({
			env: { NO_LOCAL_BUILD: '1', CI: 'true' },
			totalMemBytes: 64 * GiB,
			cgroupLimitBytes: null
		});
		expect(res.allowed).toBe(false);
		expect(res.reason).toContain('NO_LOCAL_BUILD=1');
	});

	it('uses a 10 GiB threshold', () => {
		expect(MIN_BUILD_MEMORY_BYTES).toBe(10 * GiB);
	});
});

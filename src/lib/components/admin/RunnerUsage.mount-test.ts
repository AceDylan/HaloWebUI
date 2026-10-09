import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');
const api = vi.hoisted(() => ({ getRunnerStats: vi.fn() }));
vi.mock('$lib/apis/hermes', () => api);
const sleep = (ms = 20) => new Promise((r) => setTimeout(r, ms));
const run = (agent = 'officlaude') => ({
	run_id: 'r1',
	agent,
	status: 'error',
	failure_kind: 'official_limit',
	started_at: Date.now() / 1000,
	ended_at: null,
	duration_s: 600,
	cost_usd: 2,
	turns: 10,
	tool_calls: 5,
	model: 'claude',
	cwd: '/root/HaloWebUI',
	project: 'HaloWebUI',
	origin: 'telegram',
	parent_run: '',
	title: '继续修改'
});
let app: any;
let target: any;
const mount = async () => {
	const { default: Component } = await import('./RunnerUsage.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Component({ target, props: { days: 7 } });
	await sleep();
};
afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	api.getRunnerStats.mockReset();
});

describe('runner usage page', () => {
	it('shows per-run metrics, quota warnings and a daily table; changing days reloads', async () => {
		api.getRunnerStats.mockImplementation(async (_token: string, days: number) => ({
			days,
			runs: [run(), { ...run('agy'), run_id: 'r2', cost_usd: null, failure_kind: '' }],
			quota: {
				available: true,
				checked_at: Date.now() / 1000,
				windows: [{ key: 'five_hour', label: '5 小时', utilization: 94, resets_at: null }]
			}
		}));
		await mount();
		expect(target.textContent).toContain('订阅实际账单另计');
		expect(target.querySelector('[role="alert"]').textContent).toContain('额度即将用完');
		expect(target.querySelector('[data-halo-runner-rows]').textContent).toContain('$2.0');
		expect(target.textContent).toContain('1/2 次任务提供了费用');
		const button = Array.from(target.querySelectorAll('button')).find(
			(b: any) => b.textContent === '查看每日明细'
		) as any;
		button.click();
		await sleep();
		expect(target.textContent).toContain('隐藏每日明细');
		app.$set({ days: 30 });
		await sleep();
		expect(api.getRunnerStats.mock.calls.at(-1)[1]).toBe(30);
	});
	it('keeps the latest range when an older request finishes later and shows retryable errors', async () => {
		let finishOld: (value: any) => void = () => {};
		api.getRunnerStats.mockImplementationOnce(() => new Promise((r) => (finishOld = r)));
		await mount();
		api.getRunnerStats.mockResolvedValueOnce({ days: 30, runs: [run('codex')] });
		app.$set({ days: 30 });
		await sleep();
		finishOld({ days: 7, runs: [run('officlaude')] });
		await sleep();
		expect(target.querySelector('[data-halo-runner-rows]').textContent).toContain('codex');
		expect(target.querySelector('[data-halo-runner-rows]').textContent).not.toContain(
			'官方 Claude'
		);
		api.getRunnerStats.mockRejectedValueOnce('连接失败');
		app.$set({ days: 90 });
		await sleep();
		expect(target.querySelector('[role="alert"]').textContent).toContain('连接失败');
	});
});

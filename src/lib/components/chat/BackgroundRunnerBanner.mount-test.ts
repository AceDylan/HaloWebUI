// The banner over a chat whose reclaude / codex / agy runner is still working. Stopping the
// reply that launched it never reached the runner; the banner's own 停止 does, after a
// second press.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({ stopHermesBackgroundRunner: vi.fn() }));
const toast = vi.hoisted(() => ({
	success: vi.fn(),
	error: vi.fn(),
	info: vi.fn(),
	warning: vi.fn()
}));
vi.mock('$lib/apis/hermes', () => api);
vi.mock('svelte-sonner', () => ({ toast }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const RUN = {
	run_id: '20260927-005655-f2dd355f',
	chat_id: 'chat-1',
	agent: 'reclaude',
	status: 'running',
	started_at: Date.now() / 1000 - 600,
	step: 12,
	last_activity: 'terminal: npm test',
	updated_at: Date.now() / 1000
};

let app: any;
let target: any;

const mount = async () => {
	const stores = await import('$lib/stores');
	stores.chatId.set('chat-1');
	stores.hermesBackgroundRuns.set([{ ...RUN }]);
	const { default: Banner } = await import('./BackgroundRunnerBanner.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Banner({ target });
	await sleep(10);
	return stores;
};
const button = () => target.querySelector('[data-halo-background-runner-stop]') as any;

beforeEach(() => {
	(globalThis as any).localStorage.token = 'tok';
	api.stopHermesBackgroundRunner.mockReset();
	toast.success.mockReset();
	toast.error.mockReset();
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

describe('BackgroundRunnerBanner', () => {
	it('labels the official runner and stops its run with the same id', async () => {
		const stores = await mount();
		stores.hermesBackgroundRuns.set([{ ...RUN, agent: 'officlaude' }]);
		await sleep(10);
		expect(
			target
				.querySelector('[data-halo-background-runner]')
				.getAttribute('data-halo-background-runner')
		).toBe('officlaude');
		expect(target.textContent).toContain('官方 Claude');
		expect(button().getAttribute('aria-label')).toBe('停止 官方 Claude');
		api.stopHermesBackgroundRunner.mockResolvedValue({ stopped: true, report_shown: true });
		button().click();
		await sleep(10);
		button().click();
		await sleep(20);
		expect(api.stopHermesBackgroundRunner).toHaveBeenCalledWith('tok', RUN.run_id);
		expect(toast.success.mock.calls[0][0]).toContain('已停止 官方 Claude');
	});

	it('stops the runner on the second press and drops the banner', async () => {
		const stores = await mount();
		api.stopHermesBackgroundRunner.mockResolvedValue({ stopped: true, report_shown: true });

		button().click();
		await sleep(10);
		expect(api.stopHermesBackgroundRunner).not.toHaveBeenCalled();
		expect(button().textContent.trim()).toBe('确认停止');

		button().click();
		await sleep(20);
		expect(api.stopHermesBackgroundRunner).toHaveBeenCalledWith('tok', RUN.run_id);
		const { get } = await import('svelte/store');
		expect(get(stores.hermesBackgroundRuns)).toEqual([]);
		expect(toast.success).toHaveBeenCalledTimes(1);
		expect(toast.success.mock.calls[0][0]).toContain('直接回复就能让它按新说明接着做');
		expect(target.querySelector('[data-halo-background-runner]')).toBeFalsy();
	});

	it('does not promise a follow-up for a run stopped before it had a session', async () => {
		await mount();
		api.stopHermesBackgroundRunner.mockResolvedValue({
			stopped: true,
			report_shown: true,
			resumable: false
		});
		button().click();
		await sleep(10);
		button().click();
		await sleep(20);
		expect(toast.success.mock.calls[0][0]).toBe('已停止 reclaude');
	});

	it('keeps the banner and says why when the stop fails', async () => {
		const stores = await mount();
		api.stopHermesBackgroundRunner.mockRejectedValue('这个 Hermes 还不能停止后台任务');

		button().click();
		await sleep(10);
		button().click();
		await sleep(20);
		const { get } = await import('svelte/store');
		expect(get(stores.hermesBackgroundRuns).length).toBe(1);
		expect(toast.error.mock.calls[0][0]).toContain('这个 Hermes 还不能停止后台任务');
		expect(button().textContent.trim()).toBe('停止');
	});

	it('says when a runner has gone quiet', async () => {
		const stores = await mount();
		expect(target.querySelectorAll('[data-halo-background-runner-quiet]').length).toBe(0);
		stores.hermesBackgroundRuns.set([{ ...RUN, updated_at: Date.now() / 1000 - 12.5 * 60 }]);
		await sleep(10);
		expect(target.querySelector('[data-halo-background-runner-quiet]').textContent).toContain(
			'12 分钟没有新进度'
		);
	});
});

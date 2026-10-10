// The sidebar's 运行中 list: a background runner can be stopped from its row without
// opening the chat, with the same two-press confirm as the chat banner.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
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
	run_id: '20261009-195500-a1b2c3d4',
	chat_id: 'chat-9',
	title: '部署 HaloWebUI',
	agent: 'reclaude',
	status: 'running',
	started_at: Date.now() / 1000 - 300,
	step: 4,
	last_activity: '在做：跑测试',
	updated_at: Date.now() / 1000
};

let app: any;
let target: any;

const mount = async () => {
	const stores = await import('$lib/stores');
	stores.chatId.set('another-chat');
	stores.hermesActiveRuns.set([]);
	stores.hermesBackgroundRuns.set([{ ...RUN }]);
	const { default: Runs } = await import('./ActiveHermesRuns.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	const i18n = writable({ t: (s: string) => s });
	app = new Runs({ target, context: new Map<string, any>([['i18n', i18n]]) });
	await sleep(10);
	return stores;
};
const button = () => target.querySelector('[data-halo-hermes-background-stop]') as any;

// Folder pulls in a large module graph; transform it once, outside the tests' time limit.
beforeAll(async () => {
	await import('./ActiveHermesRuns.svelte');
}, 120_000);

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

describe('ActiveHermesRuns background row', () => {
	it('stops the runner on the second press without leaving the page', async () => {
		const stores = await mount();
		api.stopHermesBackgroundRunner.mockResolvedValue({ stopped: true, report_shown: true });
		expect(button().getAttribute('data-halo-hermes-background-stop')).toBe(RUN.run_id);
		// The button sits beside the link, not inside it.
		expect(button().closest('a')).toBeFalsy();

		button().click();
		await sleep(10);
		expect(api.stopHermesBackgroundRunner).not.toHaveBeenCalled();
		expect(button().textContent.trim()).toBe('确认停止');

		button().click();
		await sleep(20);
		expect(api.stopHermesBackgroundRunner).toHaveBeenCalledWith('tok', RUN.run_id);
		const { get } = await import('svelte/store');
		expect(get(stores.hermesBackgroundRuns)).toEqual([]);
		expect(toast.success.mock.calls[0][0]).toContain('已停止 reclaude');
		expect(target.querySelectorAll('[data-halo-hermes-background-row]').length).toBe(0);
	});

	it('keeps the row and says why when the stop fails', async () => {
		const stores = await mount();
		api.stopHermesBackgroundRunner.mockRejectedValue('这个后台任务已经结束');
		button().click();
		await sleep(10);
		button().click();
		await sleep(20);
		const { get } = await import('svelte/store');
		expect(get(stores.hermesBackgroundRuns).length).toBe(1);
		expect(toast.error.mock.calls[0][0]).toContain('这个后台任务已经结束');
		expect(button().textContent.trim()).toBe('停止');
	});
});

describe('ActiveHermesRuns collapsed rail', () => {
	it('opens a popup instead of the sidebar, and a row closes it', async () => {
		const stores = await import('$lib/stores');
		const { get } = await import('svelte/store');
		stores.showSidebar.set(false);
		stores.chatId.set('another-chat');
		stores.chats.set([{ id: 'chat-done', title: '整理周报' }] as any);
		stores.hermesActiveRuns.set([]);
		stores.hermesBackgroundRuns.set([{ ...RUN }]);
		stores.hermesUnreadChatIds.set(new Set(['chat-done']));
		const { default: Runs } = await import('./ActiveHermesRuns.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		const onOpen = vi.fn();
		const i18n = writable({ t: (s: string) => s });
		app = new Runs({
			target,
			props: { compact: true, onOpen },
			context: new Map<string, any>([['i18n', i18n]])
		});
		await sleep(10);
		const popup = () => document.body.querySelector('[data-halo-hermes-runs-popup]') as any;
		expect(popup()).toBeFalsy();

		(target.querySelector('[data-halo-hermes-runs-rail]') as any).click();
		await sleep(20);
		expect(onOpen).toHaveBeenCalledTimes(1);
		expect(get(stores.showSidebar)).toBe(false);
		expect(popup()).toBeTruthy();
		// The modal is portaled to <body>, outside the rail.
		expect(target.contains(popup())).toBe(false);
		const background = popup().querySelector('[data-halo-hermes-run-state="background"]');
		expect(background.getAttribute('href')).toBe('/c/chat-9');
		const unread = popup().querySelector('[data-halo-hermes-run-state="unread"]');
		expect(unread.getAttribute('href')).toBe('/c/chat-done');
		expect(unread.textContent).toContain('整理周报');

		background.addEventListener('click', (e: any) => e.preventDefault());
		background.click();
		await sleep(400);
		expect(popup()).toBeFalsy();
		expect(get(stores.showSidebar)).toBe(false);
	});
});

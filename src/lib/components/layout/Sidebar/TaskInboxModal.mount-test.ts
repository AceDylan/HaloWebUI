// TaskInboxModal: aggregates attention / running / ended tasks across web workbenches and
// Telegram/QQ, distinguishes continue vs restart recovery on failed tasks, stops background
// runners with two-press confirm, and imports unimported Telegram sessions on click.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const nav = vi.hoisted(() => ({ goto: vi.fn(async () => {}) }));
vi.mock('$app/navigation', () => nav);

const api = vi.hoisted(() => ({
	getTaskInbox: vi.fn(),
	importHermesSession: vi.fn(),
	stopHermesBackgroundRunner: vi.fn()
}));
vi.mock('$lib/apis/hermes', () => api);

const toast = vi.hoisted(() => ({
	success: vi.fn(),
	error: vi.fn(),
	info: vi.fn(),
	warning: vi.fn()
}));
vi.mock('svelte-sonner', () => ({ toast }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 8000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for TaskInboxModal');
		await sleep(20);
	}
};

let TaskInboxModal: any;
let app: any;
let target: any;

beforeAll(async () => {
	TaskInboxModal = (await import('./TaskInboxModal.svelte')).default;
}, 120_000);

beforeEach(() => {
	nav.goto.mockReset();
	api.getTaskInbox.mockReset();
	api.importHermesSession.mockReset();
	api.stopHermesBackgroundRunner.mockReset();
	toast.success.mockReset();
	toast.error.mockReset();
	(globalThis as any).localStorage.token = 'tok';
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	document.body.innerHTML = '';
});

const mount = async () => {
	target = document.createElement('div');
	document.body.appendChild(target);
	const i18n = writable({ t: (s: string) => s });
	app = new TaskInboxModal({
		target,
		props: { show: true },
		context: new Map<string, any>([['i18n', i18n]])
	});
	await until(() => !!document.body.querySelector('[data-halo-task-inbox-modal]'));
};

describe('TaskInboxModal', () => {
	it('auto-selects attention tab, shows explicit recovery cues, and imports Telegram sessions on click', async () => {
		const now = Math.floor(Date.now() / 1000);
		api.getTaskInbox.mockResolvedValue({
			days: 7,
			attention: [
				{
					id: 'team:t1',
					bucket: 'attention',
					kind: 'team',
					source: 'web',
					title: '重构任务中心',
					status: 'waiting',
					status_label: '等你批准',
					summary: '',
					href: '/teams/t1',
					timestamp: now - 60
				}
			],
			running: [
				{
					id: 'runner:r1',
					bucket: 'running',
					kind: 'runner',
					source: 'web',
					title: '部署脚本排查',
					status: 'running',
					status_label: 'offiagy运行中',
					summary: '第 12 步',
					href: '/c/c-run',
					chat_id: 'c-run',
					run_id: '20261121-190000-abcdef12',
					agent: 'offiagy',
					timestamp: now - 30
				}
			],
			ended: [
				{
					id: 'session:tg-1',
					bucket: 'ended',
					kind: 'session',
					source: 'telegram',
					title: '昨天在 Telegram 聊的方案',
					status: 'done',
					status_label: '点开导入',
					summary: '6 条消息',
					href: null,
					session_id: 'tg-1',
					imported: false,
					timestamp: now - 3600
				},
				{
					id: 'team:t-stopped',
					bucket: 'ended',
					kind: 'team',
					source: 'web',
					title: '被中断的调研',
					status: 'stopped',
					status_label: '已停止',
					summary: '可在协作台继续',
					href: '/teams/t-stopped',
					timestamp: now - 7200,
					recovery: 'continue'
				},
				{
					id: 'auto:a-failed',
					bucket: 'ended',
					kind: 'auto',
					source: 'web',
					title: '失败的分流',
					status: 'failed',
					status_label: '分流失败',
					summary: '超时',
					href: '/auto?request=a-failed',
					timestamp: now - 9000,
					recovery: 'restart'
				}
			],
			counts: { attention: 1, running: 1, ended: 3 }
		});
		api.importHermesSession.mockResolvedValue({ chat_id: 'tg-1', title: '昨天在 Telegram 聊的方案', created: true, imported_turns: 3 });

		await mount();
		const modal = () => document.body.querySelector('[data-halo-task-inbox-modal]') as any;
		await until(() => !!modal().querySelector('[data-halo-task-inbox-item="team:t1"]'));

		// Auto-picked attention tab
		expect(modal().querySelector('[data-halo-task-inbox-tab="attention"]').getAttribute('aria-pressed')).toBe('true');

		// Switch to ended tab
		modal().querySelector('[data-halo-task-inbox-tab="ended"]').click();
		await until(() => !!modal().querySelector('[data-halo-task-inbox-item="session:tg-1"]'));

		// Explicit recovery labels: continue vs restart (not generic "重试")
		expect(modal().querySelector('[data-halo-task-inbox-recovery="continue"]').textContent).toContain('可继续原任务');
		expect(modal().querySelector('[data-halo-task-inbox-recovery="restart"]').textContent).toContain('需重新发起');

		// Filter to Telegram only
		modal().querySelector('[data-halo-task-inbox-source="telegram"]').click();
		await sleep(20);
		expect(modal().querySelectorAll('[data-halo-task-inbox-item]').length).toBe(1);
		expect(modal().querySelector('[data-halo-task-inbox-source-badge="telegram"]').textContent.trim()).toBe('Telegram');

		// Click Telegram session -> imports then navigates
		modal().querySelector('[data-halo-task-inbox-item="session:tg-1"] button').click();
		await until(() => nav.goto.mock.calls.length > 0);
		expect(api.importHermesSession).toHaveBeenCalledWith('tok', 'tg-1');
		expect(nav.goto).toHaveBeenCalledWith('/c/tg-1');
	});
});

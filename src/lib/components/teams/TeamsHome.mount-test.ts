// 协作台 home taking work handed over from a chat (its + menu, a reply's ⋯ menu): the goal, the
// files, the conversation written under the goal as background, linked to the chat, a way back.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/teams');

const api = vi.hoisted(() => ({
	checkRunners: vi.fn(),
	createTeam: vi.fn(),
	deleteTeam: vi.fn(),
	getTeamsMeta: vi.fn(),
	listTeams: vi.fn()
}));
vi.mock('$lib/apis/teams', () => api);
vi.mock('$lib/apis/files', () => ({ uploadFile: vi.fn() }));
const nav = vi.hoisted(() => ({ goto: vi.fn(), replaceState: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 20000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

let Home: any;
let app: any;

beforeAll(async () => {
	Home = (await import('./TeamsHome.svelte')).default;
}, 60000);

beforeEach(() => {
	Object.values(api).forEach((fn: any) => fn.mockReset());
	api.listTeams.mockResolvedValue({ teams: [] });
	api.getTeamsMeta.mockResolvedValue(null);
	api.createTeam.mockResolvedValue({ id: 't-new' });
	localStorage.token = 't';
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const mount = async () => {
	const { writable } = await import('svelte/store');
	const target = document.createElement('div');
	document.body.appendChild(target);
	app = new Home({ target, context: new Map([['i18n', writable({ t: (s: string) => s })]]) });
	return target;
};

describe('TeamsHome handoff', () => {
	it('fills the goal, keeps the files, writes the conversation under the goal and links the chat', async () => {
		sessionStorage.setItem(
			'halo.handoff',
			JSON.stringify({
				to: 'teams',
				text: '把出游计划做成表格',
				models: [],
				files: [{ id: 'f-7', name: 'budget.xlsx', type: 'file' }],
				context: '用户：周末去杭州\n\n助手：好',
				from: { kind: 'chat', id: 'chat-3', title: '杭州周末' },
				at: Date.now()
			})
		);
		const target = await mount();
		await until(() => !!target.querySelector('[data-team-context]'));
		expect((target.querySelector('#team-goal') as any).value).toBe('把出游计划做成表格');
		expect(target.querySelector('[data-team-attachments]')!.textContent).toContain('budget.xlsx');
		expect(target.querySelector('[data-team-context]')!.textContent).toContain('带上对话「杭州周末」作背景');
		const back = target.querySelector('[data-handoff-back]') as any;
		expect(back.getAttribute('href')).toBe('/c/chat-3');

		target.querySelector('form')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		await until(() => api.createTeam.mock.calls.length > 0);
		const [, goal, chatId, , , , files] = api.createTeam.mock.calls[0];
		expect(goal).toBe('把出游计划做成表格\n\n背景（来自对话「杭州周末」）：\n用户：周末去杭州\n\n助手：好');
		expect(chatId).toBe('chat-3');
		expect(files).toEqual(['f-7']);
	});

	it('leaves the background out when asked', async () => {
		sessionStorage.setItem(
			'halo.handoff',
			JSON.stringify({ to: 'teams', text: '写周报', models: [], files: [], context: '用户：上周做了 A', from: null, at: Date.now() })
		);
		const target = await mount();
		await until(() => !!target.querySelector('[data-team-context]'));
		(target.querySelector('[data-team-context-remove]') as any).click();
		await sleep(20);
		target.querySelector('form')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		await until(() => api.createTeam.mock.calls.length > 0);
		expect(api.createTeam.mock.calls[0][1]).toBe('写周报');
		expect(api.createTeam.mock.calls[0][2]).toBeNull();
	});
});

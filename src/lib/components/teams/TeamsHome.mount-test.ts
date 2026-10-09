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
const upload = vi.hoisted(() => ({
	uploadFileReliably: vi.fn(),
	uploadErrorText: (e: any) => (typeof e === 'string' ? e : e?.message || '上传失败')
}));
vi.mock('$lib/utils/reliable-upload', () => upload);
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

describe('TeamsHome list', () => {
	it('reads one filter of the whole history from the server, with the counts it sends', async () => {
		const team = (id: string, status: string, phase: string | null = null) => ({
			id,
			title: `任务 ${id}`,
			goal: '目标',
			status,
			phase,
			chat_id: null,
			created_at: 1,
			updated_at: 1700000000,
			finished_at: null,
			deletable: true
		});
		api.listTeams.mockImplementation(async (_token: string, opts: any) =>
			opts?.bucket === 'done'
				? { teams: [team('d1', 'running', 'completed')], next: null, total: 1, counts: { all: 40, active: 3, review: 1, done: 30, ended: 6 } }
				: { teams: [team('a1', 'running', 'running')], next: '1700000000:a1', total: 40, counts: { all: 40, active: 3, review: 1, done: 30, ended: 6 } }
		);
		const target = await mount();
		await until(() => !!target.querySelector('[data-filter="done"]'));
		expect(api.listTeams.mock.calls[0][1]).toMatchObject({ limit: 30, bucket: null });
		expect(target.querySelector('[data-filter="done"]')!.textContent).toContain('30');
		expect(target.querySelector('[data-load-more]')).toBeTruthy();
		(target.querySelector('[data-filter="done"]') as any).click();
		await until(() => api.listTeams.mock.calls.some((call: any[]) => call[1]?.bucket === 'done'));
		await until(() => !target.querySelector('[data-load-more]'));
	});
});

describe('TeamsHome attachments', () => {
	it('shows how far a file has got, then marks it ready', async () => {
		let finish: (v: any) => void = () => {};
		upload.uploadFileReliably.mockImplementation((_t: string, _f: File, opts: any) => {
			opts.onProgress({ percent: 40 });
			return new Promise((resolve) => (finish = resolve));
		});
		const target = await mount();
		await until(() => !!target.querySelector('[data-team-file-input]'));
		const input = target.querySelector('[data-team-file-input]') as any;
		const file = { name: 'plan.pdf', size: 1000, type: 'application/pdf' };
		Object.defineProperty(input, 'files', { value: [file], configurable: true });
		input.dispatchEvent(new (window as any).Event('change'));
		await until(() => !!target.querySelector('[data-attachment-progress]'));
		expect(target.querySelector('[data-attachment-progress]')!.textContent).toBe('40%');
		expect(upload.uploadFileReliably.mock.calls[0][2].process).toBe(false);
		finish({ file: { id: 'f-1' }, reused: false });
		await until(() => !!target.querySelector('[data-attachment-state="ready"]'));
		expect(target.querySelectorAll('[data-attachment-progress]').length).toBe(0);
	});

	it('names the reason when an upload fails', async () => {
		upload.uploadFileReliably.mockRejectedValue('网络中断，上传未完成');
		const target = await mount();
		await until(() => !!target.querySelector('[data-team-file-input]'));
		const input = target.querySelector('[data-team-file-input]') as any;
		Object.defineProperty(input, 'files', {
			value: [{ name: 'a.txt', size: 10, type: 'text/plain' }],
			configurable: true
		});
		input.dispatchEvent(new (window as any).Event('change'));
		await until(() => !!target.querySelector('[data-attachment-state="failed"]'));
		expect(
			target.querySelector('[data-attachment-state="failed"] [title]')!.getAttribute('title')
		).toBe('网络中断，上传未完成');
	});
});

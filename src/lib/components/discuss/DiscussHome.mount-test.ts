// 讨论台 home: only text models can take a seat (not Hermes, not image models), sensible
// defaults, formats with their rounds and roles, starting a discussion, the list of discussions.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/discuss');

const api = vi.hoisted(() => ({
	listDiscussions: vi.fn(),
	createDiscussion: vi.fn(),
	deleteDiscussion: vi.fn(),
	DiscussApiError: class DiscussApiError extends Error {
		status: number;
		constructor(status: number, message: string) {
			super(message);
			this.status = status;
		}
	}
}));
vi.mock('$lib/apis/discussions', () => api);
const library = vi.hoisted(() => ({
	listLibrary: vi.fn(),
	searchTemplates: vi.fn()
}));
vi.mock('$lib/apis/assistant-library', () => library);
const files = vi.hoisted(() => ({ uploadFileReliably: vi.fn() }));
vi.mock('$lib/utils/reliable-upload', () => files);
const nav = vi.hoisted(() => ({ goto: vi.fn(), replaceState: vi.fn() }));
vi.mock('$app/navigation', () => nav);
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: toasts }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 30000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

let Home: any;
let app: any;
let stores: any;

beforeAll(async () => {
	stores = await import('$lib/stores');
	Home = (await import('./DiscussHome.svelte')).default;
}, 60000);

beforeEach(() => {
	[api.listDiscussions, api.createDiscussion, api.deleteDiscussion].forEach((fn: any) => fn.mockReset());
	library.listLibrary.mockReset().mockResolvedValue({
		assistants: [{ ref: 'model:a1', id: 'a1', name: '软件架构师', domain: '架构', description: '架构取舍', emoji: '🏗', hidden: true }],
		may_write: true,
		favorites: []
	});
	library.searchTemplates.mockReset().mockResolvedValue([]);
	Object.values(toasts).forEach((fn: any) => fn.mockReset());
	files.uploadFileReliably.mockReset();
	nav.goto.mockReset();
	localStorage.removeItem('halo.discuss.last');
	localStorage.token = 't';
	stores.models.set([
		{ id: 'a.gpt-chat', name: 'gpt-chat', selection_id: 'm-gpt' },
		{ id: 'c.gpt-image', name: 'gpt-image', selection_id: 'm-img' },
		{ id: 'h.hermes-agent', name: 'hermes-agent', selection_id: 'm-h', original_id: 'hermes-agent' },
		{ id: 'd.deepseek-chat', name: 'deepseek-chat', selection_id: 'm-ds' },
		{ id: 'g.gemini-chat', name: 'gemini-chat', selection_id: 'm-gem' },
		{ id: 'f.claude-chat', name: 'claude-chat', selection_id: 'm-claude' }
	]);
	stores.config.set({ hermes_agent_model_ids: ['hermes-agent'] } as any);
	api.listDiscussions.mockResolvedValue([
		{
			id: 'd1',
			title: '数据库选型',
			updated_at: Math.floor(Date.now() / 1000) - 60,
			created_at: 1,
			folder_id: null,
			archived: false,
			running: false,
			mode: 'debate',
			rounds: 3,
			seats: [
				{ model: 'm-gpt', name: 'gpt-chat', label: 'gpt-chat', role: '正方' },
				{ model: 'm-ds', name: 'deepseek-chat', label: 'deepseek-chat', role: '反方' }
			],
			moderator: { model: 'm-claude', name: 'claude-chat' },
			status: 'done',
			asks: 2,
			question: '用哪个？',
			preview: '用 Postgres'
		}
	]);
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

describe('DiscussHome', () => {
	it('seats text models only, starts a debate with sides, and opens its room', async () => {
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		const seatText = () => [...target.querySelectorAll('[data-discuss-seat]')].map((el: any) => el.textContent.replace(/\s+/g, ' ').replace(' · 自动匹配', '').trim());
		expect(seatText()).toEqual(['gpt-chat', 'deepseek-chat', 'gemini-chat']);

		(target.querySelector('[data-discuss-add-seat]') as any).click();
		await until(() => !!target.querySelector('[data-discuss-add-list]'));
		const offered = target.querySelector('[data-discuss-add-list]')!.textContent!;
		expect(offered).toContain('claude-chat');
		expect(offered).not.toContain('hermes-agent');
		expect(offered).not.toContain('gpt-image');

		(target.querySelector('[data-discuss-mode="debate"]') as any).click();
		await sleep(20);
		expect(seatText()).toEqual(['gpt-chat 正方', 'deepseek-chat 反方', 'gemini-chat 评审']);
		expect(target.querySelector('[data-discuss-rounds]')!.textContent).toContain('3');

		const start = target.querySelector('[data-discuss-start]') as any;
		expect(start.disabled).toBe(true);
		const box = target.querySelector('#discuss-question') as any;
		box.value = 'AI 会让初级程序员成长变慢吗？';
		box.dispatchEvent(new (globalThis as any).Event('input'));
		await sleep(20);
		expect(start.disabled).toBe(false);
		(target.querySelector('[data-discuss-research-toggle]') as any).click();
		await sleep(20);
		expect(target.querySelector('[data-discuss-research-toggle]')!.getAttribute('aria-pressed')).toBe('true');
		api.createDiscussion.mockResolvedValue({ id: 'new1', asks: [] });
		target.querySelector('[data-discuss-composer]')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		await until(() => nav.goto.mock.calls.length > 0);
		expect(api.createDiscussion.mock.calls[0][1]).toEqual({
			question: 'AI 会让初级程序员成长变慢吗？',
			mode: 'debate',
			seats: [
				{ model: 'm-gpt', role: '' },
				{ model: 'm-ds', role: '' },
				{ model: 'm-gem', role: '' }
			],
			rounds: 3,
			moderator: 'm-gpt', // a strong writer by default
			research: true,
			files: [],
			context: null,
			auto_match: true,
			client_key: expect.any(String)
		});
		expect(nav.goto).toHaveBeenCalledWith('/discuss/new1');
		expect(JSON.parse(localStorage.getItem('halo.discuss.last')!)).toMatchObject({ mode: 'debate', research: true });
	});

	it('uploads dropped files with a progress ring and sends their ids', async () => {
		let release: (v: any) => void = () => {};
		files.uploadFileReliably.mockImplementation((_t: string, file: File, opts: any) => {
			opts.onProgress?.({ loaded: 40, total: 100, percent: 40 });
			return new Promise(
				(resolve) => (release = () => resolve({ file: { id: `id-${file.name}` }, reused: false }))
			);
		});
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		const drop = new (globalThis as any).Event('drop', { cancelable: true });
		drop.dataTransfer = { files: [new File(['计划'], 'plan.txt', { type: 'text/plain' })] };
		target.querySelector('[data-discuss-composer]')!.dispatchEvent(drop);
		await until(() => !!target.querySelector('[data-attachment-state="uploading"]'));
		expect(target.querySelector('[data-discuss-attachments]')!.textContent).toContain('40%');
		expect(files.uploadFileReliably.mock.calls[0][2].process).toBeUndefined(); // documents are read for their text
		const box = target.querySelector('#discuss-question') as any;
		box.value = '评审这个计划';
		box.dispatchEvent(new (globalThis as any).Event('input'));
		await sleep(20);
		expect((target.querySelector('[data-discuss-start]') as any).disabled).toBe(true); // still uploading
		release(null);
		await until(() => !!target.querySelector('[data-attachment-state="ready"]'));
		expect((target.querySelector('[data-discuss-start]') as any).disabled).toBe(false);
		api.createDiscussion.mockResolvedValue({ id: 'n2', asks: [] });
		target.querySelector('[data-discuss-composer]')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		await until(() => api.createDiscussion.mock.calls.length > 0);
		expect(api.createDiscussion.mock.calls[0][1].files).toEqual(['id-plan.txt']);
	});

	it('review keeps two rounds; the list shows earlier discussions', async () => {
		const target = await mount();
		await until(() => !!target.querySelector('[data-discuss-row="d1"]'));
		const row = target.querySelector('[data-discuss-row="d1"]')!.textContent!.replace(/\s+/g, ' ');
		expect(row).toContain('数据库选型');
		expect(row).toContain('用 Postgres');
		expect(row).toContain('正反辩论');
		expect(row).toContain('2 问');
		expect(row).toContain('已有结论');
		(target.querySelector('[data-discuss-mode="review"]') as any).click();
		await sleep(20);
		const plus = [...target.querySelectorAll('[data-discuss-rounds] button')].pop() as any;
		expect(plus.disabled).toBe(true);
		expect(target.querySelector('[data-discuss-rounds]')!.textContent).toContain('2');
	});
	it('takes what a chat handed over: ticked models, the draft, files, the conversation, a way back', async () => {
		sessionStorage.setItem(
			'halo.handoff',
			JSON.stringify({
				to: 'discuss',
				text: '预算 3000 去哪？',
				models: ['m-ds', 'm-claude'],
				files: [{ id: 'f-1', name: 'plan.txt', type: 'file' }],
				context: '用户：想周末出去玩\n\n助手：可以去杭州',
				from: { kind: 'chat', id: 'chat-9', title: '周末出游' },
				at: Date.now()
			})
		);
		api.createDiscussion.mockResolvedValue({ id: 'new1' });
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		const seatText = () => [...target.querySelectorAll('[data-discuss-seat]')].map((el: any) => el.textContent.replace(/\s+/g, ' ').replace(' · 自动匹配', '').trim());
		expect(seatText()).toEqual(['deepseek-chat', 'claude-chat']);
		expect((target.querySelector('#discuss-question') as any).value).toBe('预算 3000 去哪？');
		expect(target.querySelector('[data-discuss-attachments]')!.textContent).toContain('plan.txt');
		expect(target.querySelector('[data-discuss-context]')!.textContent).toContain('带上对话「周末出游」作背景');
		const back = target.querySelector('[data-handoff-back]') as any;
		expect(back.getAttribute('href')).toBe('/c/chat-9');
		expect(back.textContent).toContain('返回对话「周末出游」');
		expect(sessionStorage.getItem('halo.handoff')).toBeNull();

		target.querySelector('[data-discuss-composer]')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		await until(() => api.createDiscussion.mock.calls.length > 0);
		const form = api.createDiscussion.mock.calls[0][1];
		expect(form.seats.map((s: any) => s.model)).toEqual(['m-ds', 'm-claude']);
		expect(form.files).toEqual(['f-1']);
		expect(form.context).toEqual({ text: '用户：想周末出去玩\n\n助手：可以去杭州', title: '周末出游', chat_id: 'chat-9' });
	});

	it('one ticked model gets a second seat; the background can be left out', async () => {
		sessionStorage.setItem(
			'halo.handoff',
			JSON.stringify({ to: 'discuss', text: '', models: ['m-claude'], files: [], context: '用户：你好', from: null, at: Date.now() })
		);
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		const seats = [...target.querySelectorAll('[data-discuss-seat]')].map((el: any) => el.textContent.replace(/\s*· 自动匹配/, '').trim());
		expect(seats).toEqual(['claude-chat', 'gpt-chat']);
		expect(target.querySelector('[data-handoff-back]')).toBeFalsy();
		(target.querySelector('[data-discuss-context-remove]') as any).click();
		await sleep(20);
		expect(target.querySelector('[data-discuss-context]')).toBeFalsy();
	});

	it('a dropped response is sent again with the same key and never makes a second discussion', async () => {
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		const box = target.querySelector('#discuss-question') as any;
		box.value = '武夷山竹筏漂流体验如何';
		box.dispatchEvent(new (globalThis as any).Event('input'));
		await sleep(20);
		api.createDiscussion
			.mockRejectedValueOnce(new TypeError('Failed to fetch'))
			.mockResolvedValueOnce({ id: 'first', asks: [], deduplicated: true });
		target.querySelector('[data-discuss-composer]')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		await until(() => nav.goto.mock.calls.length > 0, 10000);
		const keys = api.createDiscussion.mock.calls.map((c: any[]) => c[1].client_key);
		expect(keys).toHaveLength(2);
		expect(keys[0]).toBeTruthy();
		expect(keys[1]).toBe(keys[0]);
		expect(nav.goto).toHaveBeenCalledWith('/discuss/first');
		expect(toasts.info).toHaveBeenCalled();
		expect(toasts.error).not.toHaveBeenCalled();
	});

	it('an error from the server is shown, and asking again after changing the question uses a new key', async () => {
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		const box = target.querySelector('#discuss-question') as any;
		const ask = async (text: string) => {
			box.value = text;
			box.dispatchEvent(new (globalThis as any).Event('input'));
			await sleep(20);
			target.querySelector('[data-discuss-composer]')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		};
		api.createDiscussion.mockRejectedValueOnce(new api.DiscussApiError(429, '已有 2 个讨论在进行'));
		await ask('问题一');
		await until(() => toasts.error.mock.calls.length > 0);
		expect(toasts.error.mock.calls[0][0]).toContain('已有 2 个讨论');
		expect(api.createDiscussion).toHaveBeenCalledTimes(1); // not retried
		api.createDiscussion.mockResolvedValueOnce({ id: 'x', asks: [] });
		await ask('问题二');
		await until(() => nav.goto.mock.calls.length > 0);
		const [first, second] = api.createDiscussion.mock.calls.map((c: any[]) => c[1].client_key);
		expect(second).not.toBe(first);
	});
	it('a seat can be given a picked assistant and a duty; 自动匹配 can be turned off', async () => {
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		expect(target.querySelector('[data-discuss-automatch-toggle]')!.getAttribute('aria-pressed')).toBe('true');
		(target.querySelector('[data-discuss-seat="0"]') as any).click();
		await until(() => !!target.querySelector('[data-discuss-seat-editor]'));
		(target.querySelector('[data-discuss-assist="pick"]') as any).click();
		await until(() => !!target.querySelector('[data-discuss-assist-option="model:a1"]'));
		(target.querySelector('[data-discuss-assist-option="model:a1"]') as any).click();
		await sleep(20);
		const duty = target.querySelector('[data-discuss-seat-duty]') as any;
		duty.value = '分析架构收益';
		duty.dispatchEvent(new (globalThis as any).Event('input'));
		await sleep(20);
		expect(target.querySelector('[data-discuss-seat="0"]')!.textContent).toContain('软件架构师');
		(target.querySelector('[data-discuss-automatch-toggle]') as any).click();
		await sleep(20);
		const box = target.querySelector('#discuss-question') as any;
		box.value = '要不要迁移到微服务？';
		box.dispatchEvent(new (globalThis as any).Event('input'));
		await sleep(20);
		api.createDiscussion.mockResolvedValue({ id: 'n2', asks: [] });
		target.querySelector('[data-discuss-composer]')!.dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
		await until(() => nav.goto.mock.calls.length > 0);
		const form = api.createDiscussion.mock.calls[0][1];
		expect(form.auto_match).toBe(false);
		expect(form.seats[0]).toEqual({ model: 'm-gpt', role: '', assist: 'pick', assistant: 'model:a1', duty: '分析架构收益' });
		expect(form.seats[1]).toEqual({ model: 'm-ds', role: '' });
		expect(JSON.parse(localStorage.getItem('halo.discuss.last')!)).toMatchObject({ autoMatch: false });
	});
});

// 讨论台 home: only text models can take a seat (not Hermes, not image models), sensible
// defaults, formats with their rounds and roles, starting a discussion, the list of discussions.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/discuss');

const api = vi.hoisted(() => ({
	listDiscussions: vi.fn(),
	createDiscussion: vi.fn(),
	deleteDiscussion: vi.fn()
}));
vi.mock('$lib/apis/discussions', () => api);
const files = vi.hoisted(() => ({ uploadFile: vi.fn() }));
vi.mock('$lib/apis/files', () => files);
const nav = vi.hoisted(() => ({ goto: vi.fn(), replaceState: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }));

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
	Object.values(api).forEach((fn: any) => fn.mockReset());
	files.uploadFile.mockReset();
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
		const seatText = () => [...target.querySelectorAll('[data-discuss-seat]')].map((el: any) => el.textContent.replace(/\s+/g, ' ').trim());
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
			files: []
		});
		expect(nav.goto).toHaveBeenCalledWith('/discuss/new1');
		expect(JSON.parse(localStorage.getItem('halo.discuss.last')!)).toMatchObject({ mode: 'debate', research: true });
	});

	it('uploads dropped files with a progress ring and sends their ids', async () => {
		let release: (v: any) => void = () => {};
		files.uploadFile.mockImplementation((_t: string, file: File, opts: any) => {
			opts.onProgress?.({ loaded: 40, total: 100, percent: 40 });
			return new Promise((resolve) => (release = () => resolve({ id: `id-${file.name}` })));
		});
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-seat]').length > 0);
		const drop = new (globalThis as any).Event('drop', { cancelable: true });
		drop.dataTransfer = { files: [new File(['计划'], 'plan.txt', { type: 'text/plain' })] };
		target.querySelector('[data-discuss-composer]')!.dispatchEvent(drop);
		await until(() => !!target.querySelector('[data-attachment-state="uploading"]'));
		expect(target.querySelector('[data-discuss-attachments]')!.textContent).toContain('40%');
		expect(files.uploadFile.mock.calls[0][2].process).toBeUndefined(); // documents are read for their text
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
});

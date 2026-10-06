// 精答 home: the dispatcher picks among text models (not Hermes, not image models, not the
// assistants themselves), the library strip, starting a run (once per question), the list.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/answer');

const api = vi.hoisted(() => ({
	listAnswers: vi.fn(),
	listAnswerAssistants: vi.fn(),
	createAnswer: vi.fn(),
	deleteAnswer: vi.fn(),
	AnswerApiError: class AnswerApiError extends Error {
		status: number;
		constructor(status: number, message: string) {
			super(message);
			this.status = status;
		}
	}
}));
vi.mock('$lib/apis/answers', () => api);
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
	Home = (await import('./AnswerHome.svelte')).default;
}, 60000);

beforeEach(() => {
	[api.listAnswers, api.listAnswerAssistants, api.createAnswer, api.deleteAnswer].forEach((fn: any) => fn.mockReset());
	Object.values(toasts).forEach((fn: any) => fn.mockReset());
	nav.goto.mockReset();
	localStorage.removeItem('halo.answer.last');
	sessionStorage.removeItem('halo.handoff');
	localStorage.token = 't';
	stores.models.set([
		{ id: 'd.deepseek-chat', name: 'deepseek-chat', selection_id: 'm-ds' },
		{ id: 'c.gpt-image', name: 'gpt-image', selection_id: 'm-img' },
		{ id: 'h.hermes-agent', name: 'hermes-agent', selection_id: 'm-h', original_id: 'hermes-agent' },
		{ id: 'f.claude-chat', name: 'claude-chat', selection_id: 'm-claude' },
		{ id: 'answer-1', name: '合同审查', info: { base_model_id: 'm-ds', meta: {} } }
	]);
	stores.config.set({ hermes_agent_model_ids: ['hermes-agent'], features: { enable_web_search: true } } as any);
	api.listAnswerAssistants.mockResolvedValue({
		assistants: [{ id: 'answer-1', name: '合同审查', description: '逐条找合同风险', emoji: '⚖️', base: 'm-ds', baseName: 'deepseek-chat', editable: true, ref: 'model:answer-1', source: 'answer', hidden: true }],
		may_create: true
	});
	api.listAnswers.mockResolvedValue([
		{
			id: 'r1',
			title: '押金条款风险',
			updated_at: Math.floor(Date.now() / 1000) - 60,
			created_at: 1,
			folder_id: null,
			archived: false,
			running: false,
			status: 'done',
			question: '押金条款有什么风险？',
			preview: '退还期限要写清',
			assistant: { id: 'answer-1', name: '合同审查', emoji: '⚖️', action: 'create' },
			research: true
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
const submit = (target: any) =>
	target.querySelector('[data-answer-composer]').dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));

describe('AnswerHome', () => {
	it('offers text models as the dispatcher, shows the library and the runs', async () => {
		const target = await mount();
		await until(() => !!target.querySelector('[data-answer-row="r1"]'));
		const options = [...target.querySelectorAll('[data-answer-planner] option')].map((o: any) => o.textContent.trim());
		expect(options).toEqual(['deepseek-chat', 'claude-chat']);
		await until(() => !!target.querySelector('[data-answer-library-item="answer-1"]'));
		expect(target.querySelector('[data-answer-library-item="answer-1"]')!.textContent).toContain('合同审查');
		const row = target.querySelector('[data-answer-row="r1"]')!.textContent!.replace(/\s+/g, ' ');
		expect(row).toContain('押金条款风险');
		expect(row).toContain('新建 · 合同审查');
		expect(row).toContain('已答完');
		expect(target.querySelector('[data-answer-row="r1"] a')!.getAttribute('href')).toBe('/answer/r1');
	});

	it('starts a run with the strong dispatcher, sends it once per question, and opens it', async () => {
		api.createAnswer.mockResolvedValueOnce({ id: 'new1', run: null });
		const target = await mount();
		await until(() => !!target.querySelector('[data-answer-input]'));
		const input = target.querySelector('[data-answer-input]') as any;
		input.value = '劳动合同的竞业限制合理吗？';
		input.dispatchEvent(new (globalThis as any).Event('input'));
		submit(target);
		await until(() => nav.goto.mock.calls.length === 1);
		expect(nav.goto.mock.calls[0][0]).toBe('/answer/new1');
		const form = api.createAnswer.mock.calls[0][1];
		expect(form).toMatchObject({ question: '劳动合同的竞业限制合理吗？', planner: 'm-claude', research: true, context: null, assistant: null });
		expect(form.client_key).toBeTruthy();
		expect(JSON.parse(localStorage.getItem('halo.answer.last')!)).toEqual({ planner: 'm-claude', research: true });
	});

	it('a draft handed over from a chat brings its conversation, which can be dropped', async () => {
		sessionStorage.setItem(
			'halo.handoff',
			JSON.stringify({ to: 'answer', text: '押金多久退？', models: [], files: [], context: '用户：我在北京租房', from: { kind: 'chat', id: 'c-1', title: '租房' }, at: Date.now() })
		);
		api.createAnswer.mockResolvedValue({ id: 'new2', run: null });
		const target = await mount();
		await until(() => !!target.querySelector('[data-answer-context]'));
		expect((target.querySelector('[data-answer-input]') as any).value).toBe('押金多久退？');
		expect(target.querySelector('[data-answer-context]')!.textContent).toContain('对话「租房」');
		submit(target);
		await until(() => api.createAnswer.mock.calls.length === 1);
		expect(api.createAnswer.mock.calls[0][1].context).toEqual({ text: '用户：我在北京租房', title: '租房', chat_id: 'c-1' });
	});
	it('a tap on a library assistant makes it the one that answers', async () => {
		api.createAnswer.mockResolvedValueOnce({ id: 'new3', run: null });
		const target = await mount();
		await until(() => !!target.querySelector('[data-answer-library-item="answer-1"]'));
		(target.querySelector('[data-answer-library-item="answer-1"]') as any).click();
		await until(() => !!target.querySelector('[data-answer-chosen]'));
		expect(target.querySelector('[data-answer-chosen]')!.textContent).toContain('合同审查');
		const input = target.querySelector('[data-answer-input]') as any;
		input.value = '帮我看看这份合同';
		input.dispatchEvent(new (globalThis as any).Event('input'));
		submit(target);
		await until(() => api.createAnswer.mock.calls.length === 1);
		expect(api.createAnswer.mock.calls[0][1].assistant).toBe('model:answer-1');
	});
});

// 精答 run page: the relay of steps, the assistant introduced (new / upgraded, with its prompt
// and the undo), the answer streaming from the socket, retry, and the hand-offs afterwards.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/answer/chat1');

const api = vi.hoisted(() => ({
	getAnswer: vi.fn(),
	stopAnswer: vi.fn(),
	retryAnswer: vi.fn(),
	revertAnswerUpgrade: vi.fn(),
	deleteAnswer: vi.fn()
}));
vi.mock('$lib/apis/answers', () => api);
const service = vi.hoisted(() => ({ refreshModels: vi.fn(async () => []) }));
vi.mock('$lib/services/models', () => service);
const nav = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
vi.mock('$lib/components/common/CodeEditor.svelte', async () => ({
	default: (await import('$lib/test-support/CodeEditorStub.svelte')).default
}));
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: toasts }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 60000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

const routing = () => ({
	id: 'm1',
	userMessageId: 'u1',
	question: '租房合同里押金条款有什么风险？',
	lang: 'zh',
	status: 'routing',
	planner: { model: 'm-claude', name: 'claude-chat' },
	webAllowed: true,
	plan: { status: 'running', startedAt: Date.now() },
	assistant: null,
	research: null,
	answer: { status: 'waiting', content: '' },
	startedAt: Date.now()
});
const created = (over: any = {}) => ({
	...routing(),
	status: 'answering',
	plan: { status: 'done', action: 'create', reason: '合同问题需要律师视角', change: '能逐条审查合同风险', webSearch: false, note: '' },
	assistant: { id: 'answer-1', name: '合同审查', emoji: '⚖️', description: '逐条找合同风险', action: 'create', saved: true, baseName: 'deepseek-chat', system: '你是一名合同审查律师。' },
	answer: { status: 'streaming', content: '', startedAt: Date.now() },
	...over
});
const detail = (run: any, over: any = {}) => ({ id: 'chat1', title: '新精答', folder_id: null, updated_at: 1, created_at: 1, run, running: true, followups: 0, messageId: 'm1', ...over });

let Run: any;
let app: any;
let stores: any;
let handlers: Record<string, ((e: any) => void)[]>;

const fakeSocket = () => ({
	connected: true,
	on: (name: string, fn: any) => (handlers[name] = [...(handlers[name] ?? []), fn]),
	off: (name: string, fn: any) => (handlers[name] = (handlers[name] ?? []).filter((f) => f !== fn))
});
const emit = (data: any, chat = 'chat1') => (handlers['chat-events'] ?? []).forEach((fn) => fn({ chat_id: chat, message_id: 'm1', data: { type: 'answer', data } }));
const text = (target: any, sel: string) => (target.querySelector(sel)?.textContent ?? '').replace(/\s+/g, ' ');

beforeAll(async () => {
	stores = await import('$lib/stores');
	Run = (await import('./AnswerRun.svelte')).default;
	await import('$lib/components/chat/Messages/Markdown.svelte');
}, 120000);

beforeEach(() => {
	handlers = {};
	Object.values(api).forEach((fn: any) => fn.mockReset());
	Object.values(toasts).forEach((fn: any) => fn.mockReset());
	service.refreshModels.mockClear();
	nav.goto.mockReset();
	stores.models.set([{ id: 'f.claude-chat', name: 'claude-chat', selection_id: 'm-claude' }]);
	stores.config.set({ features: { enable_agent_teams: true } } as any);
	stores.socket.set(fakeSocket() as any);
	stores.chatId.set('');
	sessionStorage.removeItem('halo.handoff');
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
	app = new Run({ target, props: { chatId: 'chat1' }, context: new Map([['i18n', writable({ t: (s: string) => s })]]) });
	return target;
};

describe('AnswerRun', () => {
	it('shows the dispatcher at work, then the new assistant, then streams its answer', async () => {
		api.getAnswer.mockResolvedValue(detail(routing()));
		const target = await mount();
		await until(() => !!target.querySelector('[data-answer-question]'));
		expect(text(target, '[data-answer-question]')).toContain('押金条款');
		expect(target.querySelector('[data-answer-stage="route"]')!.getAttribute('data-state')).toBe('active');
		expect(text(target, '[data-answer-stage="route"]')).toContain('claude-chat 正在读你的助手库');
		expect(target.querySelector('[data-answer-assistant]')).toBeFalsy();
		expect(target.querySelector('[data-answer-stop]')).toBeTruthy();

		emit({ kind: 'state', chatId: 'chat1', runId: 'm1', v: 2, run: created() });
		await until(() => !!target.querySelector('[data-answer-assistant="create"]'));
		expect(text(target, '[data-answer-assistant]')).toContain('合同审查');
		expect(text(target, '[data-answer-assistant]')).toContain('新建');
		expect(text(target, '[data-answer-reason]')).toContain('新建了「合同审查」：合同问题需要律师视角');
		expect(text(target, '[data-answer-change]')).toContain('能逐条审查合同风险');
		expect(target.querySelector('[data-answer-stage="assistant"]')!.getAttribute('data-state')).toBe('done');
		// a new assistant is fetched into the model list once
		await until(() => service.refreshModels.mock.calls.length === 1);
		(target.querySelector('[data-answer-show-prompt]') as any).click();
		await until(() => !!target.querySelector('[data-answer-prompt]'));
		expect(text(target, '[data-answer-prompt]')).toContain('合同审查律师');
		expect(target.querySelector('[data-answer-edit]')!.getAttribute('href')).toBe('/workspace/models/edit?id=answer-1');

		emit({ kind: 'delta', chatId: 'chat1', runId: 'm1', v: 3, offset: 0, text: '押金**退还期限**' });
		emit({ kind: 'delta', chatId: 'chat1', runId: 'm1', v: 4, offset: 10, text: '要写清。' });
		await until(() => text(target, '[data-answer-body]').includes('要写清'));
		expect(target.querySelector('[data-answer-answer]')!.getAttribute('data-state')).toBe('streaming');
		// another chat's events change nothing
		emit({ kind: 'delta', chatId: 'other', runId: 'm1', v: 5, offset: 0, text: 'X' }, 'other');
		await sleep(50);
		expect(text(target, '[data-answer-body]')).toContain('退还期限');
		expect(stores.chatId && (await new Promise((r) => stores.chatId.subscribe(r)()))).toBe('chat1');
	}, 90000);

	it('after the answer: follow up in the chat, hand it to a discussion, undo an upgrade', async () => {
		const done = created({
			status: 'done',
			plan: { status: 'done', action: 'update', reason: '同一领域', change: '会审劳动合同', webSearch: false },
			assistant: { id: 'answer-1', name: '合同审查', emoji: '⚖️', action: 'update', saved: true, baseName: 'deepseek-chat', system: '升级后的设定' },
			answer: { status: 'done', content: '竞业限制要有补偿。', startedAt: 1000, endedAt: 9000, usage: { total_tokens: 1500 } }
		});
		api.getAnswer.mockResolvedValue(detail(done, { running: false, followups: 2 }));
		api.revertAnswerUpgrade.mockResolvedValue(detail({ ...done, assistant: { ...done.assistant, reverted: true } }, { running: false }));
		const target = await mount();
		await until(() => text(target, '[data-answer-body]').includes('补偿'));
		expect(text(target, '[data-answer-answer]')).toContain('用时 8s');
		const follow = target.querySelector('[data-answer-followup]')!;
		expect(follow.getAttribute('href')).toBe('/c/chat1');
		expect(follow.textContent).toContain('已追问 2 次');

		(target.querySelector('[data-answer-revert]') as any).click();
		await until(() => api.revertAnswerUpgrade.mock.calls.length === 1);
		await until(() => text(target, '[data-answer-assistant]').includes('已撤销升级'));
		expect(target.querySelector('[data-answer-revert]')).toBeFalsy();

		(target.querySelector('[data-answer-to-discuss]') as any).click();
		await until(() => nav.goto.mock.calls.length === 1);
		expect(nav.goto.mock.calls[0][0]).toBe('/discuss');
		const handed = JSON.parse(sessionStorage.getItem('halo.handoff')!);
		expect(handed.to).toBe('discuss');
		expect(handed.text).toBe('租房合同里押金条款有什么风险？');
		expect(handed.context).toContain('「合同审查」的回答：\n竞业限制要有补偿。');
		expect(handed.from).toEqual({ kind: 'answer', id: 'chat1', title: '新精答' });
	}, 90000);

	it('a failed answer offers to answer again with the same assistant', async () => {
		const failed = created({ status: 'error', error: '429 rate limited', answer: { status: 'error', content: '', startedAt: 1, error: '429 rate limited' } });
		api.getAnswer.mockResolvedValue(detail(failed, { running: false }));
		api.retryAnswer.mockResolvedValue(detail(created()));
		const target = await mount();
		await until(() => !!target.querySelector('[data-answer-failure="error"]'));
		expect(text(target, '[data-answer-failure]')).toContain('429 rate limited');
		const retry = target.querySelector('[data-answer-retry]') as any;
		expect(retry.textContent).toContain('让「合同审查」重新回答');
		retry.click();
		await until(() => api.retryAnswer.mock.calls.length === 1);
		await until(() => !!target.querySelector('[data-answer-stop]'));
		expect(target.querySelector('[data-answer-failure]')).toBeFalsy();
	}, 90000);
});

// 讨论台: the room renders a running discussion, follows the live socket events (parallel
// turns streaming, the moderator's conclusion split into panels), and drives interjections,
// stop, follow-ups and the hand-off to Hermes.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	getDiscussion: vi.fn(),
	askDiscussion: vi.fn(),
	interjectDiscussion: vi.fn(),
	stopDiscussion: vi.fn(),
	concludeDiscussion: vi.fn(),
	continueDiscussion: vi.fn(),
	deleteDiscussion: vi.fn()
}));
vi.mock('$lib/apis/discussions', () => api);
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

const seats = [
	{ id: 's1', model: 'm-a', name: 'gpt-chat', label: 'gpt-chat', role: '' },
	{ id: 's2', model: 'm-b', name: 'claude-chat', label: 'claude-chat', role: '怀疑派' }
];
const runningAsk = () => ({
	id: 'ask1',
	userMessageId: 'u1',
	question: '小团队的内部工具用 Postgres 还是 MongoDB？',
	lang: 'zh',
	mode: 'roundtable',
	rounds: 2,
	seats,
	moderator: { model: 'm-b', name: 'claude-chat' },
	status: 'running',
	round: 1,
	turns: [
		{ id: 'r1-s1', round: 1, seat: 's1', status: 'streaming', content: '' },
		{ id: 'r1-s2', round: 1, seat: 's2', status: 'streaming', content: '' }
	],
	interjections: [],
	conclusion: { status: 'waiting', content: '', model: 'm-b', name: 'claude-chat' },
	previousConclusions: [],
	startedAt: Date.now(),
	usage: {}
});
const discussion = (ask: any) => ({
	id: 'chat1',
	title: '新讨论',
	folder_id: null,
	updated_at: 1,
	created_at: 1,
	setup: { mode: 'roundtable', rounds: 2, seats, moderator: { model: 'm-b', name: 'claude-chat' } },
	asks: [ask],
	running: ask.status === 'running'
});

let Room: any;
let app: any;
let stores: any;
let handlers: Record<string, ((e: any) => void)[]>;

const fakeSocket = () => ({
	connected: true,
	on: (name: string, fn: any) => (handlers[name] = [...(handlers[name] ?? []), fn]),
	off: (name: string, fn: any) => (handlers[name] = (handlers[name] ?? []).filter((f) => f !== fn))
});
// the test DOM does not turn a submit button's click into a form submit
const submit = (target: any) =>
	target.querySelector('[data-discuss-dock] form').dispatchEvent(new (globalThis as any).Event('submit', { cancelable: true }));
const emit = (data: any) => (handlers['chat-events'] ?? []).forEach((fn) => fn({ chat_id: 'chat1', message_id: 'ask1', data: { type: 'discuss', data } }));

beforeAll(async () => {
	stores = await import('$lib/stores');
	Room = (await import('./DiscussRoom.svelte')).default;
	// the Markdown renderer loads lazily on first use; warm it so the tests time the room only
	await import('$lib/components/chat/Messages/Markdown.svelte');
}, 120000);

beforeEach(() => {
	handlers = {};
	Object.values(api).forEach((fn: any) => fn.mockReset());
	Object.values(toasts).forEach((fn: any) => fn.mockReset());
	nav.goto.mockReset();
	stores.models.set([
		{ id: 'a.gpt-chat', name: 'gpt-chat', selection_id: 'm-a' },
		{ id: 'b.claude-chat', name: 'claude-chat', selection_id: 'm-b' },
		{ id: 'h.hermes-agent', name: 'hermes-agent', selection_id: 'm-h', original_id: 'hermes-agent' }
	]);
	stores.config.set({ hermes_agent_model_ids: ['hermes-agent'] } as any);
	stores.socket.set(fakeSocket() as any);
	stores.chatId.set('');
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
	app = new Room({
		target,
		props: { chatId: 'chat1' },
		context: new Map([['i18n', writable({ t: (s: string) => s })]])
	});
	return target;
};

describe('DiscussRoom', () => {
	it('shows the question and the seats, then streams parallel turns from the socket', async () => {
		api.getDiscussion.mockResolvedValue(discussion(runningAsk()));
		const target = await mount();
		await until(() => !!target.querySelector('[data-discuss-question]'));
		expect(target.querySelector('[data-discuss-question]')!.textContent).toContain('Postgres 还是 MongoDB');
		expect(target.querySelectorAll('[data-discuss-turn]')).toHaveLength(2);
		expect(target.querySelector('[data-discuss-seat-chip="s2"]')!.textContent).toContain('怀疑派');
		expect(stores.chatId && (await new Promise((r) => stores.chatId.subscribe(r)()))).toBe('chat1');
		// the moderator waits for everyone
		expect(target.querySelector('[data-discuss-conclusion="waiting"]')!.textContent).toContain('claude-chat');
		expect(target.querySelector('[data-discuss-input]')!.getAttribute('placeholder')).toContain('插话');

		emit({ kind: 'delta', chatId: 'chat1', askId: 'ask1', v: 2, parts: [{ t: 'r1-s1', o: 0, x: '选 **Postgres**' }, { t: 'r1-s2', o: 0, x: '先问清数据形状' }] });
		await until(() => (target.querySelector('[data-discuss-turn="r1-s1"]')?.textContent ?? '').includes('Postgres'));
		expect(target.querySelector('[data-discuss-turn="r1-s2"]')!.textContent).toContain('先问清数据形状');
		// another chat's events are ignored
		(handlers['chat-events'] ?? []).forEach((fn) =>
			fn({ chat_id: 'other', data: { type: 'discuss', data: { kind: 'delta', askId: 'ask1', v: 3, parts: [{ t: 'r1-s1', o: 0, x: 'X' }] } } })
		);
		await sleep(50);
		expect(target.querySelector('[data-discuss-turn="r1-s1"]')!.textContent).toContain('Postgres');
	}, 90000);

	it('renders a finished conclusion as an answer plus agreement / disagreement panels', async () => {
		const ask = runningAsk();
		Object.assign(ask, {
			status: 'done',
			turns: ask.turns.map((t) => ({ ...t, status: 'done', content: `${t.seat} 说完了`, startedAt: 1000, endedAt: 13000, usage: { completion_tokens: 1200 } })),
			conclusion: {
				status: 'done',
				model: 'm-b',
				name: 'claude-chat',
				content: '## 结论\n用 **Postgres**。\n## 共识\n- 要备份\n## 分歧\n- 是否需要 JSONB\n## 各方立场\n- **gpt-chat** — 支持',
				startedAt: 1,
				endedAt: 9001
			}
		});
		api.getDiscussion.mockResolvedValue({ ...discussion(ask), title: '数据库选型' });
		const target = await mount();
		await until(() => (target.querySelector('[data-discuss-answer]')?.textContent ?? '').includes('Postgres'));
		expect(target.querySelector('[data-discuss-title]')!.textContent).toBe('数据库选型');
		const kinds = [...target.querySelectorAll('.dc-section')].map((el: any) => el.getAttribute('data-kind'));
		expect(kinds).toEqual(['agree', 'disagree', 'positions']);
		expect(target.querySelector('[data-discuss-turn="r1-s1"]')!.textContent).toContain('12s · 1.2k tokens');
		expect(target.querySelector('[data-discuss-input]')!.getAttribute('placeholder')).toContain('追问');
		expect(target.querySelector('[data-discuss-continue]')).toBeTruthy();
		expect(target.querySelector('[data-discuss-conclude]')).toBeFalsy();

		// hand-off to Hermes: an editable message, sent only on confirm
		(target.querySelector('[data-discuss-hermes]') as any).click();
		await until(() => !!document.querySelector('[data-discuss-send-hermes]'));
		expect(nav.goto).not.toHaveBeenCalled();
		(document.querySelector('[data-discuss-send-hermes]') as any).click();
		await until(() => nav.goto.mock.calls.length > 0);
		const url = nav.goto.mock.calls[0][0] as string;
		expect(url.startsWith('/?models=m-h&q=')).toBe(true);
		expect(decodeURIComponent(url.split('&q=')[1])).toContain('用 **Postgres**');
	}, 90000);

	it('interjects while running, stops, and asks a follow-up when settled', async () => {
		api.getDiscussion.mockResolvedValue(discussion(runningAsk()));
		api.interjectDiscussion.mockResolvedValue({ ok: true });
		const stopped = runningAsk();
		Object.assign(stopped, {
			status: 'stopped',
			turns: [
				{ id: 'r1-s1', round: 1, seat: 's1', status: 'done', content: '观点' },
				{ id: 'r1-s2', round: 1, seat: 's2', status: 'stopped', content: '半' }
			]
		});
		api.stopDiscussion.mockResolvedValue({ ...discussion(stopped), stopped: true });
		const target = await mount();
		await until(() => !!target.querySelector('[data-discuss-input]'));
		const input = target.querySelector('[data-discuss-input]') as any;
		input.value = '预算只有 100 元';
		input.dispatchEvent(new (globalThis as any).Event('input'));
		await sleep(10);
		submit(target);
		await until(() => api.interjectDiscussion.mock.calls.length === 1);
		expect(api.interjectDiscussion.mock.calls[0].slice(1)).toEqual(['chat1', '预算只有 100 元']);

		await until(() => toasts.success.mock.calls.some((c: any[]) => String(c[0]).startsWith('已插话')));
		await sleep(20);
		(target.querySelector('[data-discuss-stop]') as any).click();
		await until(() => !!target.querySelector('[data-discuss-conclude]'));
		expect(target.querySelector('[data-discuss-status]')!.getAttribute('data-discuss-status')).toBe('stopped');
		expect(target.querySelector('[data-discuss-stop]')).toBeFalsy();

		const follow = runningAsk();
		Object.assign(follow, { id: 'ask2', question: '那备份呢？' });
		api.askDiscussion.mockResolvedValue({ ...discussion(stopped), asks: [stopped, follow], running: true });
		const box = target.querySelector('[data-discuss-input]') as any;
		box.value = '那备份呢？';
		box.dispatchEvent(new (globalThis as any).Event('input'));
		await sleep(10);
		submit(target);
		await until(() => target.querySelectorAll('[data-discuss-ask]').length === 2);
		expect(api.askDiscussion.mock.calls[0].slice(1, 3)).toEqual(['chat1', '那备份呢？']);
		expect(target.textContent).toContain('追问 1');
	}, 90000);
});

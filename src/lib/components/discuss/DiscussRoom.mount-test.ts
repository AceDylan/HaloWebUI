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
	retryDiscussionTurn: vi.fn(),
	resumeDiscussion: vi.fn(),
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

	it('主持人安排: shows the moderator setting the table, then its format, rounds, seats and why', async () => {
		const planning = { ...runningAsk(), mode: 'roundtable', seats: [], turns: [], round: 0, planning: { status: 'running' } };
		api.getDiscussion.mockResolvedValue({ ...discussion(planning), setup: { ...discussion(planning).setup, seats: [], smart: true } });
		const target = await mount();
		await until(() => !!target.querySelector('[data-discuss-planning]'));
		expect(target.querySelector('[data-discuss-planning]')!.textContent).toContain('正在读题');
		expect(target.querySelectorAll('[data-discuss-seat-chip]')).toHaveLength(0);
		expect(target.querySelectorAll('.dc-round-head')).toHaveLength(0); // no rounds before there is a table

		const planned = {
			...runningAsk(),
			mode: 'debate',
			rounds: 3,
			turns: [],
			round: 0,
			seats: [
				{ ...seats[0], role: '正方', duty: '论证收益' },
				{ ...seats[1], role: '反方', duty: '论证代价' }
			],
			planning: { status: 'done', reason: '二选一的决策，正反交锋三轮' },
			matching: { status: 'running' }
		};
		emit({ kind: 'state', chatId: 'chat1', askId: 'ask1', v: 2, ask: planned });
		await until(() => !!target.querySelector('[data-discuss-plan]'));
		expect(target.querySelector('[data-discuss-planning]')).toBeFalsy();
		const plan = target.querySelector('[data-discuss-plan]')!.textContent!.replace(/\s+/g, ' ');
		expect(plan).toContain('正反辩论 · 2 位 · 3 轮');
		expect(plan).toContain('二选一的决策，正反交锋三轮');
		expect(target.querySelector('[data-discuss-seat-chip="s1"]')!.textContent).toContain('正方');
		expect(target.querySelector('[data-discuss-seat-assistant="s2"]')!.textContent).toContain('本次职责：论证代价');
		expect(target.querySelector('[data-discuss-matching]')).toBeTruthy();
		expect(target.querySelector('[data-discuss-seat-assistant="s1"]')!.textContent).not.toContain('通用角色'); // not yet matched
	}, 90000);

	it('shows the web notes, links [n] to them and retries a failed seat', async () => {
		const ask = runningAsk();
		const sources = [
			{ n: 1, title: 'PostgreSQL 文档', url: 'https://www.postgresql.org/docs/', excerpt: '关系型数据库……' },
			{ n: 2, title: 'MongoDB 手册', url: 'https://mongodb.com/docs', excerpt: '文档数据库……' }
		];
		Object.assign(ask, {
			status: 'done',
			research: {
				status: 'done',
				queries: ['postgres mongodb'],
				sources,
				lookups: [{ round: 1, queries: ['mongodb 文档'], status: 'done', added: 1 }]
			},
			turns: [
				{ id: 'r1-s1', round: 1, seat: 's1', status: 'done', content: '选 Postgres [1]', lookup: { query: 'mongodb 文档', status: 'done', added: 1 } },
				{ id: 'r1-s2', round: 1, seat: 's2', status: 'error', content: '', error: '429 rate limited' }
			],
			conclusion: { status: 'done', model: 'm-b', name: 'claude-chat', content: '## 结论\n用 Postgres [1]，不用 Mongo [2]。\n## 共识\n- 要备份' }
		});
		api.getDiscussion.mockResolvedValue(discussion(ask));
		api.retryDiscussionTurn.mockResolvedValue(discussion({ ...ask, status: 'running' }));
		const target = await mount();
		await until(() => (target.querySelector('[data-discuss-answer]')?.textContent ?? '').includes('Postgres'));
		expect(target.querySelector('[data-discuss-research="done"]')!.textContent).toContain('资料 · 2 个来源');
		expect(target.querySelector('[data-discuss-research="done"]')!.textContent).toContain('postgresql.org');
		// a seat's 补查 between rounds: on the notes and on its turn
		expect(target.querySelector('[data-discuss-lookup="done"]')!.textContent).toContain('第 1 轮后补查');
		expect(target.querySelector('[data-discuss-lookup="done"]')!.textContent).toContain('新增 1 个来源');
		expect(target.querySelector('[data-discuss-turn-lookup="done"]')!.textContent).toContain('申请补查：mongodb 文档');
		const links = [...target.querySelectorAll('[data-discuss-answer] a')].map((a: any) => [a.textContent.trim(), a.getAttribute('href')]);
		expect(links).toContainEqual(['[1]', 'https://www.postgresql.org/docs/']);
		expect(links).toContainEqual(['[2]', 'https://mongodb.com/docs']);
		await until(() => !!target.querySelector('[data-discuss-turn="r1-s1"] a'));
		expect(target.querySelector('[data-discuss-turn="r1-s1"] a')!.getAttribute('href')).toBe('https://www.postgresql.org/docs/');
		expect(target.querySelector('[data-discuss-conclusion-sources]')!.textContent).toContain('mongodb.com');
		const retry = target.querySelector('[data-discuss-retry="r1-s2"]') as any;
		expect(retry).toBeTruthy();
		expect(target.querySelector('[data-discuss-turn="r1-s2"]')!.textContent).toContain('429 rate limited');
		retry.click();
		await until(() => api.retryDiscussionTurn.mock.calls.length === 1);
		expect(api.retryDiscussionTurn.mock.calls[0].slice(1)).toEqual(['chat1', 'r1-s2']);
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
	it('carries the conclusion on: into a new chat (not sent) or to a team with it as background', async () => {
		const ask = runningAsk();
		Object.assign(ask, {
			status: 'done',
			research: { status: 'done', queries: ['q'], sources: [{ n: 1, title: 'PG 文档', url: 'https://www.postgresql.org/docs/', excerpt: '…' }] },
			turns: [
				{ id: 'r1-s1', round: 1, seat: 's1', status: 'done', content: '选 Postgres' },
				{ id: 'r1-s2', round: 1, seat: 's2', status: 'done', content: '同意' }
			],
			conclusion: { status: 'done', model: 'm-b', name: 'claude-chat', content: '## 结论\n用 Postgres [1]。' }
		});
		api.getDiscussion.mockResolvedValue({ ...discussion(ask), title: '数据库选型' });
		stores.config.set({ hermes_agent_model_ids: ['hermes-agent'], features: { enable_agent_teams: true } } as any);
		const target = await mount();
		await until(() => !!target.querySelector('[data-discuss-next]'));
		expect(target.querySelector('[data-discuss-next]')!.textContent).toContain('继续对话');
		expect(target.querySelector('[data-discuss-hermes]')).toBeTruthy();

		(target.querySelector('[data-discuss-to-chat]') as any).click();
		expect(nav.goto).toHaveBeenLastCalledWith('/');
		const toChat = JSON.parse(sessionStorage.getItem('halo.handoff')!);
		expect(toChat.to).toBe('chat');
		expect(toChat.text).toContain('问题：小团队的内部工具用 Postgres 还是 MongoDB？');
		expect(toChat.text).toContain('用 Postgres [1]。');
		expect(toChat.from).toEqual({ kind: 'discuss', id: 'chat1', title: '数据库选型' });

		(target.querySelector('[data-discuss-to-team]') as any).click();
		expect(nav.goto).toHaveBeenLastCalledWith('/teams');
		const toTeam = JSON.parse(sessionStorage.getItem('halo.handoff')!);
		expect(toTeam).toMatchObject({ to: 'teams', text: '按讨论结论去做：小团队的内部工具用 Postgres 还是 MongoDB？' });
		expect(toTeam.context).toContain('讨论结论：\n## 结论\n用 Postgres [1]。');
		expect(toTeam.context).toContain('[1] PG 文档 https://www.postgresql.org/docs/');
		sessionStorage.removeItem('halo.handoff');
	}, 90000);

	it('shows a rate-limited call waiting to be made again, a stand-in moderator, and resumes a failed question', async () => {
		const ask = runningAsk();
		Object.assign(ask, {
			turns: [
				{ id: 'r1-s1', round: 1, seat: 's1', status: 'streaming', content: '' },
				{ id: 'r1-s2', round: 1, seat: 's2', status: 'streaming', content: '' }
			]
		});
		api.getDiscussion.mockResolvedValue(discussion(ask));
		const target = await mount();
		await until(() => target.querySelectorAll('[data-discuss-turn]').length === 2);
		emit({
			kind: 'turn',
			chatId: 'chat1',
			askId: 'ask1',
			v: 2,
			turn: { id: 'r1-s1', status: 'waiting', retry: { n: 1, of: 3, reason: '限流', until: Date.now() + 20000 } }
		});
		await until(() => !!target.querySelector('[data-discuss-retry-wait="r1-s1"]'));
		expect(target.querySelector('[data-discuss-turn="r1-s1"]')!.textContent).toMatch(/限流，\d+ 秒后重试（1\/3）/);
		app.$destroy();
		document.body.innerHTML = '';

		// the moderator stayed rate-limited: a seat wrote the conclusion
		const done = runningAsk();
		Object.assign(done, {
			status: 'done',
			turns: done.turns.map((t) => ({ ...t, status: 'done', content: `${t.seat} 说完了` })),
			conclusion: {
				status: 'done',
				model: 'm-a',
				name: 'gpt-chat',
				content: '## 结论\n照常去。',
				standIn: { for: 'claude-chat', reason: '限流' }
			}
		});
		api.getDiscussion.mockResolvedValue(discussion(done));
		const second = await mount();
		await until(() => !!second.querySelector('[data-discuss-stand-in]'));
		expect(second.querySelector('[data-discuss-stand-in]')!.textContent).toContain('主持人 claude-chat 暂时写不了（限流），由 gpt-chat 代写');
		expect(second.querySelector('[data-discuss-resume]')).toBeFalsy();
		app.$destroy();
		document.body.innerHTML = '';

		// every try failed: the step can be restarted from where it broke
		const failed = runningAsk();
		Object.assign(failed, {
			status: 'error',
			error: 'exceeded token rate limit',
			turns: failed.turns.map((t) => ({ ...t, status: 'done', content: `${t.seat} 说完了` })),
			conclusion: { status: 'error', model: 'm-b', name: 'claude-chat', content: '', error: 'exceeded token rate limit' }
		});
		api.getDiscussion.mockResolvedValue(discussion(failed));
		api.resumeDiscussion.mockResolvedValue(discussion({ ...failed, status: 'concluding' }));
		const third = await mount();
		await until(() => !!third.querySelector('[data-discuss-resume]'));
		expect(third.querySelector('[data-discuss-resume]')!.textContent).toContain('从出错处继续');
		expect(third.querySelector('[data-discuss-failure="error"]')!.textContent).toContain('exceeded token rate limit');
		expect(third.querySelector('[data-discuss-rewrite]')).toBeTruthy();
		expect(third.querySelector('[data-discuss-conclusion="error"] .dc-skeleton')).toBeFalsy();
		(third.querySelector('[data-discuss-resume-inline]') as any).click();
		await until(() => api.resumeDiscussion.mock.calls.length === 1);
		expect(api.resumeDiscussion.mock.calls[0].slice(1)).toEqual(['chat1']);
	}, 90000);
});

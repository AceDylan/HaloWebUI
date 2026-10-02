// 协作台: the communication feed and the replay bar, mounted in a DOM. The feed shows a note's
// delivery as it stood at the replay cursor; the replay bar only moves a cursor (seek events),
// it never calls an API.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	getTeamTask: vi.fn(),
	sendTeamMessage: vi.fn(),
	retryTeamTask: vi.fn(),
	controlTeam: vi.fn(),
	teamFilePath: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`,
	teamFileUrl: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`
}));
vi.mock('$lib/apis/teams', () => api);
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const ev = (seq: number, partial: Record<string, unknown>) => ({
	id: String(seq),
	seq,
	ts: 1790900000 + seq,
	task_id: 't_1',
	key: 'T1',
	member: 'backend-dev',
	kind: 'x',
	run_id: null,
	type: 'status',
	...partial
});

const EVENTS = [
	ev(1, { type: 'attempt', text: '开始第 1 次执行', status: 'running', sub_status: 'running' }),
	ev(2, { type: 'tool', text: 'npm test', data: { name: 'terminal' } }),
	ev(3, {
		type: 'message',
		who: 'user',
		author: 'Ace',
		text: '接口用 REST',
		data: { comment_id: 1, delivered_seq: 5, delivered_via: 'steer' }
	}),
	ev(4, { type: 'tool', text: 'cat api.md', data: { name: 'read_file' } }),
	ev(5, { type: 'delivery', text: '补充说明已送达运行中的成员' }),
	ev(6, {
		type: 'handoff',
		text: '接口写好了，见 api.md',
		data: { to: [{ task_id: 't_3', key: 'T3', member: 'reviewer' }] }
	})
];

let app: any;
let target: any;

const mount = async (Component: any, props: Record<string, unknown>) => {
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Component({ target, props });
	await sleep(5);
	return app;
};

beforeEach(() => {
	(globalThis as any).localStorage.token = 'tok';
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
});

const items = () => Array.from(target.querySelectorAll('li[data-event-type]')) as any[];

describe('CommFeed', () => {
	it('lists newest first and shows the delivery a note had at the replay cursor', async () => {
		const { default: CommFeed } = await import('./CommFeed.svelte');
		await mount(CommFeed, { events: EVENTS.slice(0, 4), cursorSeq: 4 });
		expect(items().map((li) => li.getAttribute('data-event-type'))).toEqual([
			'tool',
			'message',
			'tool',
			'attempt'
		]);
		const note = items()[1];
		expect(note.textContent).toContain('Ace → backend-dev');
		expect(note.textContent).toContain('排队中，尚未送达');

		app.$set({ events: EVENTS, cursorSeq: null });
		await sleep(5);
		expect(items()[0].getAttribute('data-event-type')).toBe('handoff');
		expect(items()[0].textContent).toContain('reviewer(#T3)');
		const delivered = items().find((li) => li.getAttribute('data-event-type') === 'message');
		expect(delivered.textContent).toContain('已送达（运行中注入）');
	});

	it('filters to tool logs', async () => {
		const { default: CommFeed } = await import('./CommFeed.svelte');
		await mount(CommFeed, { events: EVENTS, cursorSeq: null });
		const tools = Array.from(target.querySelectorAll('button[role="radio"]')).find((b: any) =>
			b.textContent.includes('工具日志')
		) as any;
		tools.click();
		await sleep(5);
		expect(items().map((li) => li.getAttribute('data-event-type'))).toEqual(['tool', 'tool']);
		expect(items()[0].textContent).toContain('cat api.md');
	});
});

describe('ReplayBar', () => {
	it('starts a replay from the first event, plays forward, and goes back to live — only seek events', async () => {
		const { default: ReplayBar } = await import('./ReplayBar.svelte');
		const quick = EVENTS.map((e) => ({ ...e, ts: 1790900000 }));
		await mount(ReplayBar, { events: quick, index: null });
		const seeks: (number | null)[] = [];
		app.$on('seek', (e: CustomEvent) => {
			seeks.push(e.detail);
			app.$set({ index: e.detail });
		});
		expect(target.textContent).toContain('实时');
		const replayButton = Array.from(target.querySelectorAll('button')).find((b: any) =>
			b.textContent.includes('回放')
		) as any;
		replayButton.click();
		await sleep(5);
		expect(seeks[0]).toBe(0);
		expect(target.textContent).toContain('回放中');
		const fast = Array.from(target.querySelectorAll('button[role="radio"]')).find(
			(b: any) => b.textContent.trim() === '4×'
		) as any;
		fast.click();
		await sleep(400);
		expect(seeks[seeks.length - 1]).toBeGreaterThan(1);
		expect(seeks).toEqual([...seeks].sort((a, b) => (a as number) - (b as number)));
		const pause = Array.from(target.querySelectorAll('button')).find((b: any) =>
			b.textContent.includes('暂停回放')
		) as any;
		if (pause) pause.click();
		const live = Array.from(target.querySelectorAll('button')).find((b: any) =>
			b.textContent.includes('回到实时')
		) as any;
		live.click();
		await sleep(5);
		expect(seeks[seeks.length - 1]).toBeNull();
		for (const fn of Object.values(api))
			if (vi.isMockFunction(fn)) expect(fn).not.toHaveBeenCalled();
	});
});

describe('Inspector (member)', () => {
	it('sends a note to the task the selected member is on, and is read-only in a replay', async () => {
		api.sendTeamMessage.mockResolvedValue({
			comment_id: 7,
			delivery: 'queued',
			expect: '成员正在执行：会在它当前这批工具调用结束后读到'
		});
		const { default: Inspector } = await import('./Inspector.svelte');
		const tasks = [
			{
				id: 't_1',
				key: 'T1',
				seq: 1,
				title: '写接口',
				member: 'backend-dev',
				executor: 'hermes',
				status: 'done',
				sub_status: 'done',
				parents: [],
				children: [],
				attempts: 1
			},
			{
				id: 't_2',
				key: 'T2',
				seq: 2,
				title: '写测试',
				member: 'backend-dev',
				executor: 'hermes',
				status: 'running',
				sub_status: 'running',
				parents: [],
				children: [],
				attempts: 1
			}
		];
		const states = new Map(
			tasks.map((t) => [t.id, { status: t.status, sub_status: t.sub_status }])
		);
		const members = [
			{ name: 'backend-dev', role: '后端开发', executor: 'hermes', status: 'running' }
		];
		await mount(Inspector, {
			teamId: 'team-1',
			memberName: 'backend-dev',
			tasks,
			states,
			members,
			events: []
		});
		expect(target.querySelectorAll('[data-member-note]').length).toBe(1);
		expect(target.textContent).toContain('正在做的 #T2');
		const textarea = target.querySelector('[data-member-note] textarea') as any;
		textarea.value = '加上错误处理';
		textarea.dispatchEvent(new (globalThis as any).Event('input', { bubbles: true }));
		await sleep(5);
		(target.querySelector('[data-member-note]') as any).dispatchEvent(
			new (globalThis as any).Event('submit', { bubbles: true, cancelable: true })
		);
		await sleep(20);
		expect(api.sendTeamMessage).toHaveBeenCalledWith('tok', 'team-1', 't_2', '加上错误处理');
		app.$set({ replay: true });
		await sleep(5);
		expect(target.querySelectorAll('[data-member-note]').length).toBe(0);
	});
});

describe('PlanReview', () => {
	it('lets each member be run by Hermes or any runner', async () => {
		const { default: PlanReview } = await import('./PlanReview.svelte');
		const team = {
			id: 'team-1',
			status: 'plan_ready',
			plan: {
				title: '小工具',
				members: [{ name: 'backend-dev', role: '后端开发', executor: 'hermes' }],
				tasks: [{ key: 'T1', title: '写接口', member: 'backend-dev', depends_on: [] }],
				layers: [['T1']],
				widest_layer: 1
			}
		};
		await mount(PlanReview, { team });
		const picked: any[] = [];
		app.$on('executor', (e: any) => picked.push(e.detail));
		const select = target.querySelector('select') as any;
		expect(Array.from(select.querySelectorAll('option')).map((o: any) => o.value)).toEqual([
			'hermes',
			'reclaude',
			'cchclaude',
			'anyclaude',
			'codex',
			'agy'
		]);
		select.value = 'codex';
		select.dispatchEvent(new (globalThis as any).Event('change', { bubbles: true }));
		await sleep(5);
		expect(picked).toEqual([{ name: 'backend-dev', executor: 'codex', source: 'user' }]);
	});
});

describe('Inspector (runner member)', () => {
	it('tells the user a runner member gets the note after its current run', async () => {
		const { default: Inspector } = await import('./Inspector.svelte');
		const tasks = [
			{
				id: 't_1',
				key: 'T1',
				seq: 1,
				title: '写接口',
				member: 'coder',
				executor: 'codex',
				status: 'running',
				sub_status: 'running',
				parents: [],
				children: [],
				attempts: 1
			}
		];
		const states = new Map(
			tasks.map((t) => [t.id, { status: t.status, sub_status: t.sub_status }])
		);
		const members = [{ name: 'coder', role: '开发', executor: 'codex', status: 'running' }];
		await mount(Inspector, {
			teamId: 'team-1',
			memberName: 'coder',
			tasks,
			states,
			members,
			events: []
		});
		const textarea = target.querySelector('[data-member-note] textarea') as any;
		expect(textarea.getAttribute('placeholder')).toContain('codex 运行中收不到消息');
		expect(target.querySelector('[data-member-profile]').textContent).toContain('codex');
	});
});

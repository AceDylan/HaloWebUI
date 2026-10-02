// 协作台: the communication feed and the replay bar, mounted in a DOM. The feed shows a note's
// delivery as it stood at the replay cursor; the replay bar only moves a cursor (seek events),
// it never calls an API.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	getTeamTask: vi.fn(),
	sendTeamMessage: vi.fn(),
	retryTeamTask: vi.fn(),
	controlTeam: vi.fn()
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
	ev(3, { type: 'message', who: 'user', author: 'Ace', text: '接口用 REST', data: { comment_id: 1, delivered_seq: 5, delivered_via: 'steer' } }),
	ev(4, { type: 'tool', text: 'cat api.md', data: { name: 'read_file' } }),
	ev(5, { type: 'delivery', text: '补充说明已送达运行中的成员' }),
	ev(6, { type: 'handoff', text: '接口写好了，见 api.md', data: { to: [{ task_id: 't_3', key: 'T3', member: 'reviewer' }] } })
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

afterEach(() => {
	app?.$destroy();
	target?.remove();
});

const items = () => Array.from(target.querySelectorAll('li[data-event-type]')) as any[];

describe('CommFeed', () => {
	it('lists newest first and shows the delivery a note had at the replay cursor', async () => {
		const { default: CommFeed } = await import('./CommFeed.svelte');
		await mount(CommFeed, { events: EVENTS.slice(0, 4), cursorSeq: 4 });
		expect(items().map((li) => li.getAttribute('data-event-type'))).toEqual(['tool', 'message', 'tool', 'attempt']);
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
		const tools = Array.from(target.querySelectorAll('button[role="radio"]')).find((b: any) => b.textContent.includes('工具日志')) as any;
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
		const replayButton = Array.from(target.querySelectorAll('button')).find((b: any) => b.textContent.includes('回放')) as any;
		replayButton.click();
		await sleep(5);
		expect(seeks[0]).toBe(0);
		expect(target.textContent).toContain('回放中');
		const fast = Array.from(target.querySelectorAll('button[role="radio"]')).find((b: any) => b.textContent.trim() === '4×') as any;
		fast.click();
		await sleep(400);
		expect(seeks[seeks.length - 1]).toBeGreaterThan(1);
		expect(seeks).toEqual([...seeks].sort((a, b) => (a as number) - (b as number)));
		const pause = Array.from(target.querySelectorAll('button')).find((b: any) => b.textContent.includes('暂停回放')) as any;
		if (pause) pause.click();
		const live = Array.from(target.querySelectorAll('button')).find((b: any) => b.textContent.includes('回到实时')) as any;
		live.click();
		await sleep(5);
		expect(seeks[seeks.length - 1]).toBeNull();
		for (const fn of Object.values(api)) expect(fn).not.toHaveBeenCalled();
	});
});

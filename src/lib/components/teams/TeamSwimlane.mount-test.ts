import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readable } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	getTeam: vi.fn(),
	getTeamEvents: vi.fn(),
	getTeamTask: vi.fn(),
	getTeamsMeta: vi.fn(),
	checkRunners: vi.fn(),
	approveTeam: vi.fn(),
	cancelTeam: vi.fn(),
	controlTeam: vi.fn(),
	editTeamPlan: vi.fn(),
	fillTeamGaps: vi.fn(),
	replanTeam: vi.fn(),
	adjustTeam: vi.fn(),
	decideTeamChange: vi.fn(),
	retryTeamTask: vi.fn(),
	sendTeamMessage: vi.fn(),
	taskDiagnosis: vi.fn(),
	markTeamAssistantReverted: vi.fn(),
	teamFilePath: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`,
	teamFileUrl: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`
}));
vi.mock('$lib/apis/teams', () => api);
vi.mock('$lib/apis/assistant-library', () => ({ undoAssistantRun: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const ev = (seq: number, partial: Record<string, unknown> = {}) => ({
	id: String(seq),
	seq,
	ts: 1790900000 + seq * 4,
	task_id: 't_1',
	key: 'T1',
	member: 'dev-a',
	kind: 'code',
	run_id: 1,
	type: 'status',
	...partial
});

const SAMPLE_TASKS = [
	{
		id: 't_1',
		key: 'T1',
		seq: 1,
		title: '设计接口',
		member: 'dev-a',
		executor: 'officlaude',
		status: 'done',
		sub_status: 'done',
		parents: [],
		children: ['t_2'],
		created_at: 1790900000,
		started_at: 1790900001,
		completed_at: 1790900025,
		attempts: 1,
		current_run: null,
		result: 'done',
		block_reason: '',
		consecutive_failures: 0
	},
	{
		id: 't_2',
		key: 'T2',
		seq: 2,
		title: '实现测试',
		member: 'dev-b',
		executor: 'codex',
		status: 'running',
		sub_status: 'waiting_user',
		parents: ['t_1'],
		children: [],
		created_at: 1790900000,
		started_at: 1790900026,
		completed_at: null,
		attempts: 1,
		current_run: null,
		result: '',
		block_reason: '',
		consecutive_failures: 0
	}
];

const SAMPLE_EVENTS = [
	ev(1, { type: 'attempt', text: '开始第 1 次执行', status: 'running', sub_status: 'running' }),
	ev(2, { type: 'tool', text: 'cat api.md', data: { name: 'read_file' } }),
	ev(3, { type: 'tool', text: 'edit src/routes.ts', data: { name: 'edit_file' } }),
	ev(4, {
		type: 'handoff',
		text: '完成 api.md，请接手',
		data: { to: [{ task_id: 't_2', key: 'T2', member: 'dev-b' }] }
	}),
	ev(5, {
		type: 'runner',
		task_id: 't_2',
		key: 'T2',
		member: 'dev-b',
		data: { runner: 'codex', phase: 'question' },
		text: '需要兼容旧版字段吗？'
	}),
	ev(6, {
		type: 'status',
		task_id: 't_2',
		key: 'T2',
		member: 'dev-b',
		status: 'failed',
		sub_status: 'failed',
		text: '测试失败'
	})
];

let app: any;
let target: any;

const mount = async (Component: any, props: Record<string, unknown>) => {
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Component({
		target,
		props,
		context: new Map([['i18n', readable({ t: (s: string) => s })]])
	});
	await sleep(10);
	return app;
};

beforeEach(() => {
	(globalThis as any).localStorage.token = 'tok';
	for (const fn of Object.values(api)) {
		if (typeof (fn as any).mockReset === 'function') (fn as any).mockReset();
	}
	api.getTeamTask.mockResolvedValue({
		task_id: 't_1',
		key: 'T1',
		member: 'dev-a',
		executor: 'officlaude',
		title: '设计接口',
		body: '',
		status: 'done',
		result: 'ok',
		attempts: [],
		comments: [],
		log: null
	});
});

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
});

describe('NarrativeFeed', () => {
	it('collapses tool steps, toggles expansion, and supports inline reply & retry', async () => {
		api.sendTeamMessage.mockResolvedValue({ comment_id: 9, delivery: 'queued' });
		api.retryTeamTask.mockResolvedValue({ ok: true });
		const { buildStages, groupNarrative } = await import('./narrative');
		const { default: NarrativeFeed } = await import('./NarrativeFeed.svelte');
		const items = groupNarrative(SAMPLE_EVENTS as any, SAMPLE_TASKS as any);
		await mount(NarrativeFeed, {
			teamId: 'team-1',
			items,
			stages: buildStages(SAMPLE_TASKS, new Map()),
			members: [
				{ name: 'dev-a', role: '后端' },
				{ name: 'dev-b', role: '测试' }
			]
		});

		const rows = Array.from(target.querySelectorAll('li[data-narrative-kind]')) as any[];
		expect(rows.map((r) => r.getAttribute('data-narrative-kind'))).toEqual([
			'status',
			'tool_group',
			'handoff',
			'approval',
			'fail'
		]);
		expect(
			Array.from(target.querySelectorAll('[data-narrative-stage]'), (el: any) =>
				el.getAttribute('data-narrative-stage')
			)
		).toEqual(['layer-0', 'layer-1']);
		expect(rows[2].textContent).toContain('dev-b #T2');
		expect(rows[3].classList.contains('is-actionable')).toBe(true);

		// Tool group collapsed by default, expands on click
		const tgId = rows[1].getAttribute('data-narrative-id');
		expect(target.querySelector(`[data-tool-group-steps="${tgId}"]`)).toBeFalsy();
		(target.querySelector(`[data-tool-group-toggle="${tgId}"]`) as any).click();
		await sleep(5);
		const expandedSteps = target.querySelector(`[data-tool-group-steps="${tgId}"]`);
		expect(expandedSteps).toBeTruthy();
		expect(expandedSteps.textContent).toContain('cat api.md');
		expect(expandedSteps.textContent).toContain('edit src/routes.ts');
		expect(expandedSteps.textContent).toContain('02');

		// Inline approval reply
		const replyForm = target.querySelector('[data-inline-reply]') as any;
		const input = replyForm.querySelector('input') as any;
		input.value = '需要兼容';
		input.dispatchEvent(new (globalThis as any).Event('input', { bubbles: true }));
		await sleep(5);
		replyForm.dispatchEvent(new (globalThis as any).Event('submit', { bubbles: true, cancelable: true }));
		await sleep(15);
		expect(api.sendTeamMessage).toHaveBeenCalledWith('tok', 'team-1', 't_2', '需要兼容');

		// Inline retry on fail card
		const retryBtn = target.querySelector('[data-inline-retry] button') as any;
		retryBtn.click();
		await sleep(15);
		expect(api.retryTeamTask).toHaveBeenCalledWith('tok', 'team-1', 't_2');

		// Once live states mark t_2 as done, stale approval/fail controls disappear
		app.$set({ states: new Map([['t_2', { status: 'done', sub_status: 'done' }]]) });
		await sleep(10);
		expect(target.querySelector('[data-inline-reply]')).toBeFalsy();
		expect(target.querySelector('[data-inline-retry]')).toBeFalsy();
		expect(rows[3].classList.contains('is-actionable')).toBe(false);
	});
});

describe('SwimlaneTree', () => {
	it('renders lanes/nodes, grows live with replay items, and dispatches focus & member toggle', async () => {
		const { buildStages, groupNarrative } = await import('./narrative');
		const { default: SwimlaneTree } = await import('./SwimlaneTree.svelte');
		const initialItems = groupNarrative(SAMPLE_EVENTS.slice(0, 2) as any, SAMPLE_TASKS as any);
		await mount(SwimlaneTree, {
			items: initialItems,
			stages: buildStages(SAMPLE_TASKS, new Map()),
			activeLanes: new Set(['dev-a']),
			members: [
				{ name: 'dev-a', role: '后端' },
				{ name: 'dev-b', role: '测试' }
			],
			leadName: '统筹'
		});
		const focused: any[] = [];
		const toggled: any[] = [];
		app.$on('focus', (e: CustomEvent) => focused.push(e.detail));
		app.$on('toggleMember', (e: CustomEvent) => toggled.push(e.detail));

		expect(target.querySelectorAll('[data-swimlane-lane]').length).toBe(3);
		expect(target.querySelectorAll('[data-swimlane-node]').length).toBe(2);
		expect(
			target.querySelector('[data-swimlane-lane="dev-a"][data-lane-active="true"]')
		).toBeTruthy();
		expect(target.querySelector('[data-swimlane-hud]').textContent).toContain('api.md');

		// Simulate replay cursor moving forward -> swimlane grows live
		const fullItems = groupNarrative(SAMPLE_EVENTS as any, SAMPLE_TASKS as any);
		app.$set({ items: fullItems });
		await sleep(10);
		const nodes = target.querySelectorAll('[data-swimlane-node]');
		expect(nodes.length).toBe(fullItems.length);
		expect(target.querySelectorAll('[data-swimlane-stage-band]').length).toBe(2);
		expect(target.querySelector('[data-swimlane-hud]').textContent).toContain('dev-b');
		expect(target.querySelector('[data-swimlane-hud]').textContent).toContain('#T2');

		// Clicking a node dispatches focus with source='swimlane' and pin=true
		(nodes[2] as any).dispatchEvent(new (globalThis as any).Event('click', { bubbles: true }));
		await sleep(5);
		expect(focused[focused.length - 1]).toEqual({
			id: fullItems[2].id,
			source: 'swimlane',
			pin: true
		});
		app.$set({ focusId: fullItems[2].id });
		await sleep(5);
		expect(target.querySelector('[data-swimlane-hud]').textContent).toContain('交接 → dev-b(#T2)');
		expect(nodes[0].getAttribute('opacity')).toBe('0.26');
		expect(nodes[3].getAttribute('opacity')).toBe('1');
		expect(target.querySelectorAll('.workbench-motion-particle').length).toBe(1);
		app.$set({ motion: false });
		await sleep(5);
		expect(target.querySelectorAll('.workbench-motion-particle').length).toBe(0);

		// Clicking a lane header toggles member filter
		(target.querySelector('[data-swimlane-lane="dev-a"]') as any).click();
		await sleep(5);
		expect(toggled[toggled.length - 1]).toBe('dev-a');
	});

	it('windows nodes on a long scrolling canvas and shows a focused node outside the window in the HUD', async () => {
		const { groupNarrative } = await import('./narrative');
		const { default: SwimlaneTree } = await import('./SwimlaneTree.svelte');
		const items = groupNarrative(
			Array.from({ length: 125 }, (_, i) => ev(i + 1, { text: `执行记录 ${i + 1}` })) as any,
			SAMPLE_TASKS
		);
		await mount(SwimlaneTree, { items, autoFollow: false, focusId: items.at(-1)?.id });
		const scroller = target.querySelector('[data-swimlane-scroll]');
		Object.defineProperties(scroller, {
			clientHeight: { value: 420 },
			scrollHeight: { value: 6600 },
			scrollTop: { value: 0, writable: true }
		});
		scroller.dispatchEvent(new Event('scroll'));
		await sleep(5);
		expect(target.querySelectorAll('[data-swimlane-node]').length).toBeLessThan(40);
		expect(target.querySelector('[data-swimlane-node="ev-125"]')).toBeFalsy();
		expect(target.querySelector('[data-swimlane-hud]').textContent).toContain('执行记录 125');
		scroller.scrollTop = 6100;
		scroller.dispatchEvent(new Event('scroll'));
		await sleep(5);
		expect(target.querySelector('[data-swimlane-node="ev-125"]')).toBeTruthy();
	});
});

describe('TeamWorkbench integration (dual-pane + non-destructive drawer)', () => {
	it('defaults to stream+swimlane mode and keeps stream visible when inspector drawer opens', async () => {
		api.getTeam.mockResolvedValue({
			team: {
				id: 'team-1',
				chat_id: null,
				title: '协作台升级',
				goal: '升级协作台',
				status: 'running',
				phase: 'running',
				plan: {
					title: '协作台升级',
					members: [
						{ name: 'dev-a', role: '后端', executor: 'officlaude' },
						{ name: 'dev-b', role: '测试', executor: 'codex' }
					],
					tasks: []
				},
				error: null,
				board: 'b1',
				created_at: 1790900000,
				updated_at: 1790900000,
				approved_at: 1790900001,
				finished_at: null,
				member_count: 2,
				task_count: 2,
				executors: ['officlaude', 'codex']
			},
			live: {
				team: {
					team_id: 'team-1',
					board: 'b1',
					title: '协作台升级',
					goal: '升级协作台',
					summary: '',
					chat_id: '',
					workspace: '/tmp/ws',
					state: 'running',
					archived: false,
					phase: 'running',
					created_at: 1790900000,
					approved_at: 1790900001,
					completed_at: null,
					stopped_at: null,
					max_parallel: 2,
					lead: { name: 'team-lead', role: '负责人', status: 'coordinating' }
				},
				members: [
					{ name: 'dev-a', role: '后端', executor: 'officlaude', status: 'done', task_ids: ['t_1'], current_task: null },
					{ name: 'dev-b', role: '测试', executor: 'codex', status: 'waiting_user', task_ids: ['t_2'], current_task: 't_2' }
				],
				tasks: SAMPLE_TASKS,
				counts: { done: 1, running: 1, total: 2 },
				latest_seq: 6,
				generated_at: 1790900030
			},
			live_error: null,
			stage: null
		});
		api.getTeamEvents.mockResolvedValue({
			events: SAMPLE_EVENTS,
			next_after: 6,
			has_more: false,
			latest_seq: 6,
			reconcile: []
		});

		const { default: TeamWorkbench } = await import('./TeamWorkbench.svelte');
		await mount(TeamWorkbench, { teamId: 'team-1' });
		await sleep(40);

		expect(target.querySelector('[data-workbench-filter]')).toBeTruthy();
		expect(target.querySelector('[data-workbench-stream]')).toBeTruthy();
		expect(target.querySelector('[data-narrative-feed]')).toBeTruthy();
		expect(target.querySelector('[data-swimlane-tree]')).toBeTruthy();
		const wideToggle = target.querySelector('[data-wide-toggle]');
		const stream = target.querySelector('[data-workbench-stream]');
		expect(wideToggle.getAttribute('aria-pressed')).toBe('false');
		wideToggle.click();
		await sleep(10);
		expect(stream.getAttribute('data-wide')).toBe('true');
		expect(wideToggle.getAttribute('aria-pressed')).toBe('true');
		wideToggle.click();
		await sleep(10);
		expect(stream.hasAttribute('data-wide')).toBe(false);

		// Domino has no layout. Give the two scrollboxes and focus targets physical coordinates.
		const rect = (left: number, top: number, width: number, height: number) => ({
			left,
			top,
			width,
			height,
			right: left + width,
			bottom: top + height,
			x: left,
			y: top
		});
		const graphScroll = target.querySelector('[data-swimlane-scroll]');
		const feedList = target.querySelector('[data-narrative-feed] ol');
		const row = target.querySelector('[data-narrative-id="ev-4"]');
		const node = target.querySelector('[data-swimlane-node="ev-4"]');
		const anchor = node.querySelector('[data-swimlane-anchor]');
		stream.getBoundingClientRect = () => rect(0, 40, 1000, 600);
		feedList.getBoundingClientRect = () => rect(0, 85, 490, 500);
		graphScroll.getBoundingClientRect = () => rect(510, 85, 490, 500);
		row.getBoundingClientRect = () => rect(28, 140, 450, 60);
		anchor.getBoundingClientRect = () => rect(629, 192, 18, 18);
		Object.defineProperty(graphScroll, 'clientWidth', { value: 490 });
		Object.defineProperty(graphScroll, 'clientHeight', { value: 500 });
		row.dispatchEvent(new Event('mouseenter'));
		await sleep(10);
		const overlay = target.querySelector('[data-focus-connector]');
		expect(overlay).toBeTruthy();
		expect(overlay.querySelectorAll('path').length).toBe(2);
		anchor.getBoundingClientRect = () => rect(490, 192, 18, 18);
		graphScroll.dispatchEvent(new Event('scroll'));
		await sleep(10);
		expect(target.querySelector('[data-focus-connector]')).toBeFalsy();
		row.dispatchEvent(new Event('mouseleave'));
		await sleep(5);

		(target.querySelector('[data-filter-stage="layer-1"]') as any).click();
		await sleep(10);
		expect(target.querySelector('[data-narrative-stage="layer-0"]')).toBeFalsy();
		(target.querySelector('[data-clear-filters]') as any).click();
		await sleep(10);
		expect(target.querySelector('[data-narrative-stage="layer-0"]')).toBeTruthy();

		// Open member inspector via compact filter bar -> slide-over drawer opens while stream stays visible
		(target.querySelector('[data-inspect-member="dev-a"]') as any).click();
		await sleep(20);
		expect(target.querySelector('[data-inspector-drawer]')).toBeTruthy();
		expect(target.querySelector('[data-narrative-feed]')).toBeTruthy();
		expect(target.querySelector('[data-swimlane-tree]')).toBeTruthy();

		// Switch desktop view to 依赖图 -> TeamBoard mounts
		(target.querySelector('[data-view-tab="board"]') as any).click();
		await sleep(20);
		expect(target.querySelector('[data-team-board]')).toBeTruthy();
	});
});

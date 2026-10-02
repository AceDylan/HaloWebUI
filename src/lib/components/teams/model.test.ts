import { describe, expect, it } from 'vitest';

import type { TeamEvent } from '$lib/apis/teams';
import {
	activityText,
	avatarKind,
	boardDirection,
	countStates,
	deliveryAt,
	EXECUTOR_LABEL,
	EXECUTOR_OPTIONS,
	foldStates,
	isRunnerExecutor,
	latestActivity,
	layoutTasks,
	memberStatus,
	mergeEvents,
	openParents,
	phaseAt,
	plainPreview,
	replayDelay,
	replayMarks,
	taskDepths
} from './model';

const ev = (seq: number, partial: Partial<TeamEvent>): TeamEvent => ({
	id: String(seq),
	seq,
	ts: 1000 + seq,
	task_id: null,
	key: null,
	member: null,
	kind: 'x',
	run_id: null,
	type: 'status',
	...partial
});

// #1 #2 #3 done; #4 #6 run in parallel after #3; #5 waits for #4 and #6.
const tasks = [
	{ id: 't1', key: 'T1', seq: 1, parents: [] },
	{ id: 't2', key: 'T2', seq: 2, parents: ['t1'] },
	{ id: 't3', key: 'T3', seq: 3, parents: ['t2'] },
	{ id: 't4', key: 'T4', seq: 4, parents: ['t3'] },
	{ id: 't6', key: 'T6', seq: 6, parents: ['t3'] },
	{ id: 't5', key: 'T5', seq: 5, parents: ['t4', 't6'] }
];

describe('layout', () => {
	it('puts each dependency depth in its own lane, parallel tasks side by side', () => {
		const layout = layoutTasks(tasks);
		const depth = (id: string) => layout.positions.get(id)!.depth;
		expect([depth('t1'), depth('t2'), depth('t3'), depth('t4'), depth('t6'), depth('t5')]).toEqual([
			0, 1, 2, 3, 3, 4
		]);
		expect(layout.columns).toBe(5);
		expect(layout.positions.get('t4')!.x).toBe(layout.positions.get('t6')!.x);
		expect(layout.positions.get('t4')!.y).toBeLessThan(layout.positions.get('t6')!.y);
		expect(layout.positions.get('t5')!.x).toBeGreaterThan(layout.positions.get('t4')!.x);
	});

	it('survives cycles and unknown parents', () => {
		const depths = taskDepths([
			{ id: 'a', parents: ['b'] },
			{ id: 'b', parents: ['a'] },
			{ id: 'c', parents: ['ghost'] }
		]);
		expect(depths.get('c')).toBe(0);
		expect([...depths.values()].every((d) => Number.isFinite(d))).toBe(true);
	});
});

describe('board direction', () => {
	const chain = [1, 2, 3, 4].map((n) => ({
		id: `c${n}`,
		key: `T${n}`,
		seq: n,
		parents: n > 1 ? [`c${n - 1}`] : []
	}));
	it('lays a long chain top to bottom on a narrow board, keeps wide boards left to right', () => {
		expect(boardDirection(chain, 760, 640)).toBe('TB');
		expect(boardDirection(chain, 1400, 640)).toBe('LR');
		expect(boardDirection(tasks, 760, 640)).toBe('TB'); // five steps deep
		const fan = [
			...[1, 2, 3, 4].map((n) => ({ id: `f${n}`, key: `F${n}`, seq: n, parents: [] })),
			{ id: 'f5', key: 'F5', seq: 5, parents: ['f1', 'f2', 'f3', 'f4'] }
		];
		expect(boardDirection(fan, 760, 640)).toBe('LR'); // wide and shallow
		const tb = layoutTasks(chain, 'TB');
		const ys = chain.map((t) => tb.positions.get(t.id)!.y);
		expect(ys).toEqual([...ys].sort((a, b) => a - b));
		expect(new Set(chain.map((t) => tb.positions.get(t.id)!.x)).size).toBe(1);
		expect(tb.height).toBeGreaterThan(tb.width);
	});
});

describe('fold', () => {
	const events: TeamEvent[] = [
		ev(1, { type: 'team', data: { action: 'approved' } }),
		ev(2, { task_id: 't4', status: 'ready', sub_status: 'queued' }),
		ev(3, { task_id: 't6', status: 'ready', sub_status: 'queued' }),
		ev(4, { task_id: 't5', status: 'todo', sub_status: 'waiting_deps' }),
		ev(5, { task_id: 't4', type: 'attempt', status: 'running', sub_status: 'running' }),
		ev(6, { task_id: 't6', type: 'attempt', status: 'running', sub_status: 'running' }),
		ev(7, { task_id: 't4', type: 'tool', text: 'ls' }),
		ev(8, { task_id: 't4', type: 'attempt', status: 'done', sub_status: 'done' }),
		ev(9, { task_id: 't6', type: 'runner', status: 'running', sub_status: 'quota_wait' })
	];
	const list = [{ id: 't4' }, { id: 't5' }, { id: 't6' }];

	it('gives the state at any point; events without a status change nothing', () => {
		expect(foldStates(list, events, 0).get('t4')).toEqual({
			status: 'pending',
			sub_status: 'pending'
		});
		const mid = foldStates(list, events, 6);
		expect(mid.get('t4')).toEqual({ status: 'running', sub_status: 'running' });
		expect(mid.get('t5')!.sub_status).toBe('waiting_deps');
		const end = foldStates(list, events);
		expect(end.get('t4')!.status).toBe('done');
		expect(end.get('t6')).toEqual({ status: 'running', sub_status: 'quota_wait' });
		expect(countStates(end)).toEqual({ done: 1, running: 0, waiting: 2, attention: 0, total: 3 });
	});

	it('names the open parents a waiting task depends on', () => {
		const end = foldStates(list, events);
		expect(openParents({ parents: ['t4', 't6'] }, end)).toEqual(['t6']);
	});

	it('derives member and team phase from the same states', () => {
		expect(
			memberStatus([
				{ status: 'done', sub_status: 'done' },
				{ status: 'running', sub_status: 'running' }
			])
		).toBe('running');
		expect(memberStatus([{ status: 'done', sub_status: 'done' }])).toBe('done');
		expect(memberStatus([{ status: 'todo', sub_status: 'waiting_deps' }])).toBe('waiting_deps');
		expect(
			memberStatus([
				{ status: 'blocked', sub_status: 'failed' },
				{ status: 'todo', sub_status: 'waiting_deps' }
			])
		).toBe('failed');
		const end = foldStates(list, events);
		expect(phaseAt(end, events, events.length - 1)).toBe('running');
		const paused = [...events, ev(10, { type: 'team', data: { action: 'paused' } })];
		expect(phaseAt(end, paused, paused.length - 1)).toBe('paused');
		const stopped = [...paused, ev(11, { type: 'team', data: { action: 'stopped' } })];
		expect(phaseAt(end, stopped, stopped.length - 1)).toBe('stopped');
	});
});

describe('events', () => {
	it('merges pages without duplicates and keeps order when pages overlap or arrive late', () => {
		const a = [ev(1, {}), ev(2, {}), ev(3, {})];
		const b = [ev(3, {}), ev(4, {}), { ...ev(4, {}), id: '4:handoff', type: 'handoff' as const }];
		const merged = mergeEvents(a, b);
		expect(merged.map((e) => e.id)).toEqual(['1', '2', '3', '4', '4:handoff']);
		expect(mergeEvents(merged, [ev(2, {})])).toBe(merged);
		const late = mergeEvents([ev(1, {}), ev(5, {})], [ev(3, {})]);
		expect(late.map((e) => e.seq)).toEqual([1, 3, 5]);
	});

	it('reports a note as queued until the delivery event, also in replay', () => {
		const note = ev(5, {
			type: 'message',
			who: 'user',
			data: { delivered_seq: 9, delivered_via: 'steer' }
		});
		expect(deliveryAt(note, 7)!.state).toBe('queued');
		expect(deliveryAt(note, 9)!.label).toBe('已送达（运行中注入）');
		expect(deliveryAt(note, null)!.state).toBe('delivered');
		const lost = ev(6, { type: 'message', who: 'user', data: { delivery: 'undelivered' } });
		expect(deliveryAt(lost, null)!.state).toBe('undelivered');
		expect(deliveryAt(ev(7, { type: 'message', who: 'member' }), null)).toBeNull();
	});

	it('scales real gaps by speed and compresses long idle gaps', () => {
		const list = [ev(1, { ts: 100 }), ev(2, { ts: 101 }), ev(3, { ts: 4000 })];
		expect(replayDelay(list, 0, 1)).toEqual({ ms: 1000, compressed: false });
		expect(replayDelay(list, 0, 4).ms).toBe(250);
		expect(replayDelay(list, 1, 1)).toEqual({ ms: 2500, compressed: true });
		expect(replayDelay(list, 2, 1).ms).toBe(120);
	});
});

describe('replay marks', () => {
	it('marks failures, handoffs, team milestones and messages, thinning messages first', () => {
		const list = [
			ev(1, { type: 'team', text: '计划已批准' }),
			ev(2, { type: 'tool' }),
			ev(3, { type: 'message', who: 'member', text: 'hi' }),
			ev(4, { type: 'message', who: 'user', text: '加上测试' }),
			ev(5, { type: 'attempt', sub_status: 'failed' }),
			ev(6, { type: 'runner', data: { phase: 'failed' } }),
			ev(7, { type: 'handoff', sub_status: 'done' })
		];
		expect(replayMarks(list)).toEqual([
			{ index: 0, kind: 'team' },
			{ index: 2, kind: 'message' },
			{ index: 3, kind: 'user' },
			{ index: 4, kind: 'fail' },
			{ index: 5, kind: 'fail' },
			{ index: 6, kind: 'handoff' }
		]);
		expect(replayMarks(list, 5).map((m) => m.kind)).not.toContain('message');
		expect(replayMarks(list, 2)).toHaveLength(2);
	});
});

describe('activity', () => {
	it('says in one line what each member did last, ignoring your own notes', () => {
		const list = [
			ev(1, { member: 'a', type: 'attempt', text: '开始第 1 次执行' }),
			ev(2, { member: 'b', type: 'tool', text: 'npm  test\n--watch', data: { name: 'terminal' } }),
			ev(3, {
				member: 'a',
				type: 'runner',
				text: '',
				data: { runner: 'codex', phase: 'launched' }
			}),
			ev(4, { member: 'a', type: 'message', who: 'user', text: '加上错误处理' }),
			ev(5, { member: 'c', type: 'delivery', text: 'x' })
		];
		const map = latestActivity(list, ['a', 'b', 'c']);
		expect(map.get('a')).toEqual({ text: 'codex 已启动', ts: 1003, type: 'runner' });
		expect(map.get('b')!.text).toBe('terminal · npm test --watch');
		expect(map.has('c')).toBe(false);
		expect(activityText(ev(6, { type: 'handoff', text: '见 api.md' }))).toBe(
			'完成并交接 · 见 api.md'
		);
		expect(activityText(ev(7, { type: 'status', sub_status: 'running' }))).toBe('执行中');
	});
});

describe('plain preview', () => {
	it('drops markdown syntax members write, keeps the words and lines', () => {
		expect(plainPreview('## T3 评审结论：**不通过**，见 `review.md`')).toBe(
			'T3 评审结论：不通过，见 review.md'
		);
		expect(plainPreview('> 引用\n- [文档](./a.md) 与 *重点*\n\n\n\n结束')).toBe(
			'引用\n- 文档 与 重点\n\n结束'
		);
		expect(plainPreview('a * b * c')).toBe('a * b * c');
	});
});

describe('avatars', () => {
	it('maps roles to occupational avatars, lead first', () => {
		expect(avatarKind({ name: 'backend-dev', role: '后端开发' })).toBe('backend');
		expect(avatarKind({ name: 'qa-engineer', role: '测试工程师' })).toBe('qa');
		expect(avatarKind({ name: 'reviewer', role: '技术评审' })).toBe('reviewer');
		expect(avatarKind({ name: 'x', role: '杂项' })).toBe('generic');
		expect(avatarKind({ name: 'reviewer' }, true)).toBe('lead');
	});
});

describe('executors', () => {
	it('offers Hermes and every runner, and only runners count as runners', () => {
		expect(EXECUTOR_OPTIONS.map((o) => o.value)).toEqual([
			'hermes',
			'reclaude',
			'cchclaude',
			'anyclaude',
			'codex',
			'agy'
		]);
		expect(EXECUTOR_LABEL.hermes).toBe('Hermes 代理');
		expect(EXECUTOR_LABEL.codex).toBe('codex');
		expect(['reclaude', 'cchclaude', 'anyclaude', 'codex', 'agy'].every(isRunnerExecutor)).toBe(
			true
		);
		expect(isRunnerExecutor('hermes')).toBe(false);
		expect(isRunnerExecutor('gpt')).toBe(false);
		expect(isRunnerExecutor(undefined)).toBe(false);
	});
});

describe('stage estimates', () => {
	it('formats how long is left the way people say it', async () => {
		const { formatEta } = await import('./model');
		expect(formatEta(20)).toBe('不到 1 分钟');
		expect(formatEta(170, 175)).toBe('约 3 分钟');
		expect(formatEta(170, 400)).toBe('约 3–7 分钟');
		expect(formatEta(30, 200)).toBe('约 1–3 分钟');
		expect(formatEta(6000, 9000)).toBe('约 1.5–2.5 小时');
	});

	it('counts down from when the estimate was made and admits running late', async () => {
		const { etaLeft, etaSentence } = await import('./model');
		const eta = { seconds: 300, high: 420 };
		expect(etaLeft(eta, 1000, 1100)).toEqual({ low: 200, high: 320, overtime: false });
		expect(etaSentence(eta, 1000, 1100)).toBe('预计还要约 3–5 分钟');
		expect(etaLeft(eta, 1000, 1350)).toEqual({ low: 0, high: 70, overtime: true });
		expect(etaSentence(eta, 1000, 1350)).toBe('比平时久一些，可能还要 1 分钟');
		expect(etaSentence(eta, 1000, 2000)).toBe('比平时久一些，应该快好了');
		expect(etaSentence(null, 1000, 2000)).toBe('');
	});
});

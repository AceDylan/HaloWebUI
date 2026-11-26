import { describe, expect, it } from 'vitest';

import type { LiveTask, TeamDeployState, TeamEvent } from '$lib/apis/teams';
import {
	LEAD_LANE_ID,
	buildStages,
	extractArtifacts,
	groupNarrative,
	lanePalette,
	layoutSwimlanes
} from './narrative';

const ev = (seq: number, partial: Partial<TeamEvent> = {}): TeamEvent => ({
	id: String(seq),
	seq,
	ts: 1790900000 + seq * 5,
	task_id: 't_1',
	key: 'T1',
	member: 'dev-a',
	kind: 'code',
	run_id: 1,
	type: 'status',
	...partial
});

const TASKS: Pick<LiveTask, 'id' | 'key' | 'seq' | 'title' | 'parents' | 'member'>[] = [
	{ id: 't_1', key: 'T1', seq: 1, title: '接口设计', parents: [], member: 'dev-a' },
	{ id: 't_2', key: 'T2', seq: 2, title: '后端实现', parents: ['t_1'], member: 'dev-b' },
	{ id: 't_3', key: 'T3', seq: 3, title: '前端页面', parents: ['t_1'], member: 'dev-c' },
	{ id: 't_4', key: 'T4', seq: 4, title: '集成验证', parents: ['t_2', 't_3'], member: 'qa' }
];

describe('narrative pure engine', () => {
	it('builds dependency stages with parallel counts, status priority, and deploy stage', () => {
		const states = new Map([
			['t_1', { status: 'done', sub_status: 'done' }],
			['t_2', { status: 'running', sub_status: 'running' }],
			['t_3', { status: 'blocked', sub_status: 'failed' }],
			['t_4', { status: 'pending', sub_status: 'waiting_deps' }]
		]);
		const deploy: TeamDeployState = {
			status: 'running',
			steps: [
				{ key: 'review', label: 'Codex 审查', status: 'done' },
				{ key: 'merge', label: '合并到 main', status: 'running' }
			]
		};
		const stages = buildStages(TASKS, states, deploy);
		expect(stages.map((s) => [s.id, s.status, s.done, s.total])).toEqual([
			['layer-0', 'done', 1, 1],
			['layer-1', 'attention', 0, 2],
			['layer-2', 'pending', 0, 1],
			['deploy', 'running', 1, 2]
		]);
		expect(stages[1].shortLabel).toContain('2并行');
	});

	it('extracts workspace-like filenames while ignoring URLs', () => {
		const files = extractArtifacts(
			'Updated src/api.ts and keyframes/01.png (see https://example.com/foo.js and notes.md)'
		);
		expect(files).toEqual(['src/api.ts', 'keyframes/01.png', 'notes.md']);
	});

	it('collapses consecutive tool/subagent calls per (member, task) with step count & duration', () => {
		const events: TeamEvent[] = [
			ev(1, { type: 'attempt', text: '开始第 1 次执行', status: 'running', sub_status: 'running' }),
			ev(2, { type: 'tool', ts: 100, text: 'cat src/api.ts', data: { name: 'read_file' } }),
			ev(3, { type: 'tool', ts: 112, text: 'grep router src/api.ts', data: { name: 'grep' } }),
			ev(4, { type: 'subagent', ts: 126, data: { phase: 'start', subagent: 'explore' } }),
			ev(5, {
				type: 'tool',
				ts: 130,
				task_id: 't_2',
				key: 'T2',
				member: 'dev-b',
				text: 'npm test',
				data: { name: 'terminal' }
			})
		];
		const items = groupNarrative(events, TASKS);
		expect(items.map((i) => i.kind)).toEqual(['status', 'tool_group', 'tool_group']);
		expect(items[1].stepCount).toBe(3);
		expect(items[1].durationSec).toBe(26);
		expect(items[1].files).toContain('src/api.ts');
		expect(items[2].member).toBe('dev-b');
		expect(items[2].stepCount).toBe(1);
	});

	it('detects approval, failure, retry, runner fallback, handoff, and hides redundant delivery', () => {
		const events: TeamEvent[] = [
			ev(1, {
				type: 'message',
				who: 'user',
				author: 'Ace',
				text: '优先做暗色模式',
				data: { delivered_seq: 2, delivered_via: 'steer' }
			}),
			ev(2, { type: 'delivery', text: '已送达' }),
			ev(3, { type: 'runner', data: { runner: 'officlaude', phase: 'question' }, text: '选方案 A 还是 B？' }),
			ev(4, { type: 'status', status: 'failed', sub_status: 'failed', text: '测试 3 失败' }),
			ev(5, { type: 'runner', data: { runner: 'cchclaude', phase: 'fallback' }, text: '额度不足改派' }),
			ev(6, { type: 'attempt', text: '开始第 2 次执行', status: 'running', sub_status: 'running' }),
			ev(7, {
				type: 'handoff',
				text: '产出 api.md',
				data: { to: [{ task_id: 't_2', key: 'T2', member: 'dev-b' }] }
			})
		];
		const items = groupNarrative(events, TASKS, { cursorSeq: null });
		expect(items.map((i) => i.kind)).toEqual([
			'message',
			'approval',
			'fail',
			'retry',
			'retry',
			'handoff'
		]);
		expect(items[0].lane).toBe(LEAD_LANE_ID);
		expect(items[0].targetLane).toBe('dev-a');
		expect(items[0].delivery?.state).toBe('delivered');
		expect(items[1].actionable).toBe('reply');
		expect(items[2].actionable).toBe('retry');
		expect(items[5].handoffTo[0].member).toBe('dev-b');
	});

	it('truncates cleanly for replay cursors and appends deploy milestones only in live mode', () => {
		const events: TeamEvent[] = [
			ev(1, { type: 'attempt', text: '开始第 1 次执行' }),
			ev(2, { type: 'tool', text: 'ls', data: { name: 'terminal' } }),
			ev(3, { type: 'handoff', text: '完成', data: { to: [{ member: 'dev-b', key: 'T2' }] } })
		];
		const deploy: TeamDeployState = {
			status: 'succeeded',
			sha: 'c41d7aa99',
			steps: [
				{ key: 'merge', label: '合并到 main', status: 'done', at: 1790900100 },
				{ key: 'push', label: '推送', status: 'pending' }
			]
		};
		const replayItems = groupNarrative(events.slice(0, 2), TASKS, {
			cursorSeq: 2,
			deploy,
			includeDeploy: false
		});
		expect(replayItems.length).toBe(2);
		expect(replayItems.some((i) => i.kind === 'deploy')).toBe(false);

		const liveItems = groupNarrative(events, TASKS, {
			cursorSeq: null,
			deploy,
			includeDeploy: true
		});
		expect(liveItems[liveItems.length - 1].kind).toBe('deploy');
		expect(liveItems[liveItems.length - 1].badge).toBe('合并');
	});

	it('lays out swimlanes with lead on lane 0, unplanned members, handoff/retry/merge edges, and span clamping', () => {
		const events: TeamEvent[] = [
			ev(1, { type: 'team', member: null, task_id: null, key: null, text: '团队已启动' }),
			ev(2, { type: 'status', status: 'failed', sub_status: 'failed', text: '单测挂了' }),
			ev(3, { type: 'attempt', text: '开始第 2 次执行' }),
			ev(4, {
				type: 'handoff',
				text: '交给 unplanned-bot',
				data: { to: [{ task_id: 't_x', key: 'TX', member: 'unplanned-bot' }] }
			}),
			// 12 intermediate items to exercise MAX_EDGE_SPAN_ROWS clamping
			...Array.from({ length: 12 }, (_, idx) =>
				ev(5 + idx, {
					type: 'message',
					who: 'member',
					member: 'dev-b',
					task_id: 't_2',
					key: 'T2',
					text: `进度 ${idx}`
				})
			),
			ev(20, { type: 'attempt', member: 'unplanned-bot', task_id: 't_x', key: 'TX', text: '开始接手' })
		];
		const deploy: TeamDeployState = {
			status: 'succeeded',
			steps: [{ key: 'merge', label: '合并到 main', status: 'done', at: 1790900200 }]
		};
		const items = groupNarrative(events, TASKS, { deploy, includeDeploy: true });
		const layout = layoutSwimlanes(items, [{ name: 'dev-a', role: '后端' }, { name: 'dev-b', role: '前端' }], {
			leadName: '统筹'
		});

		expect(layout.lanes[0].id).toBe(LEAD_LANE_ID);
		expect(layout.lanes.map((l) => l.id)).toEqual([LEAD_LANE_ID, 'dev-a', 'dev-b', 'unplanned-bot']);
		expect(layout.nodes.length).toBe(items.length);
		// Evenly spaced Y coordinates
		expect(layout.nodes[1].y - layout.nodes[0].y).toBe(layout.rowHeight);

		const retryEdge = layout.edges.find((e) => e.kind === 'retry');
		expect(retryEdge).toBeTruthy();

		const handoffEdge = layout.edges.find((e) => e.kind === 'handoff');
		expect(handoffEdge).toBeTruthy();
		expect(handoffEdge?.compact).toBe(true);

		const mergeEdges = layout.edges.filter((e) => e.kind === 'merge');
		expect(mergeEdges.length).toBeGreaterThanOrEqual(2);
		expect(lanePalette('extra-member', 9).stroke).toMatch(/^hsl\(/);
	});
});

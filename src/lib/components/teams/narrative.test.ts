import { describe, expect, it } from 'vitest';

import type { LiveTask, TeamDeployState, TeamEvent } from '$lib/apis/teams';
import {
	LEAD_LANE_ID,
	buildStages,
	connectedSwimlaneIds,
	extractArtifacts,
	groupNarrative,
	lanePalette,
	layoutSwimlanes,
	sectionStageIds,
	swimlaneEdgeCurveEndY,
	swimlaneEdgePath
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
		expect(items[1].toolIcon).toBe('search');
		expect(items[2].member).toBe('dev-b');
		expect(items[2].stepCount).toBe(1);
		expect(items[2].toolIcon).toBe('terminal');
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

	it('routes long edges along lane rails instead of leaving them floating mid-canvas', () => {
		// Member lanes go quiet long before the lead merges and deploys (the 2026-11-28 screenshot).
		const events: TeamEvent[] = [
			ev(1, { member: 'dev-a', task_id: 't_1', key: 'T1', text: '开始设计' }),
			ev(2, {
				type: 'handoff',
				member: 'dev-a',
				text: '交给 dev-b',
				data: { to: [{ task_id: 't_2', key: 'T2', member: 'dev-b' }] }
			}),
			...Array.from({ length: 14 }, (_, idx) =>
				ev(3 + idx, {
					type: 'message',
					who: 'lead',
					member: null,
					task_id: null,
					key: null,
					text: `负责人进度 ${idx}`
				})
			),
			ev(30, { member: 'dev-b', task_id: 't_2', key: 'T2', text: '开始实现' })
		];
		const deploy: TeamDeployState = {
			status: 'succeeded',
			steps: [{ key: 'merge', label: '合并到 main', status: 'done', at: 1790900400 }]
		};
		const items = groupNarrative(events, TASKS, { deploy, includeDeploy: true });
		const layout = layoutSwimlanes(items, [{ name: 'dev-a' }, { name: 'dev-b' }], {
			leadName: '统筹'
		});
		const byId = new Map(layout.nodes.map((node) => [node.id, node]));

		const merges = layout.edges.filter((e) => e.kind === 'merge');
		const fromA = merges.find((e) => byId.get(e.fromNodeId)?.laneId === 'dev-a');
		expect(fromA).toBeTruthy();
		const last = byId.get(fromA!.fromNodeId)!;
		const merge = byId.get(fromA!.toNodeId!)!;
		// Starts on the member's last node, not 1.5 rows above the merge in an empty lane.
		expect([fromA!.fromX, fromA!.fromY]).toEqual([last.x, last.y]);
		expect(fromA!.compact).toBe(true);
		expect(fromA!.elbow).toEqual({ at: 'from', y: merge.y - layout.rowHeight * 1.5 });
		expect(swimlaneEdgePath(fromA!)).toMatch(
			new RegExp(`^M ${last.x} ${last.y} V ${fromA!.elbow!.y} C `)
		);
		expect(fromA!.fromColor).toBe(layout.lanes[last.laneIndex].palette.stroke);
		expect(fromA!.color).not.toBe(fromA!.fromColor);

		// A long handoff lands on the receiving node via the target lane rail.
		const handoff = layout.edges.find((e) => e.kind === 'handoff')!;
		const target = byId.get(handoff.toNodeId!)!;
		expect(handoff.compact).toBe(true);
		expect(handoff.toY).toBe(target.y);
		expect(handoff.elbow?.at).toBe('to');
		expect(swimlaneEdgePath(handoff)).toMatch(new RegExp(`V ${target.y}$`));
		expect(swimlaneEdgeCurveEndY(handoff)).toBe(handoff.elbow!.y);

		// Every merge but a short hop fans in along its lane; short non-merge edges keep a single curve.
		for (const edge of merges) {
			const span = byId.get(edge.toNodeId!)!.row - byId.get(edge.fromNodeId)!.row;
			expect(edge.elbow?.at).toBe(span > 2 ? 'from' : undefined);
		}
		for (const edge of layout.edges.filter((e) => !e.compact && e.kind !== 'merge')) {
			expect(edge.elbow).toBeUndefined();
			expect(swimlaneEdgePath(edge)).not.toContain(' V ');
		}
	});

	it('groups consecutive stage rows, preserves their spacing, and adapts lane widths', () => {
		const deploy: TeamDeployState = {
			status: 'running',
			steps: [{ key: 'review', label: '审查', status: 'running' }]
		};
		const items = groupNarrative(
			[
				ev(1, { text: '开始设计' }),
				ev(2, {
					type: 'tool',
					ts: 100,
					text: 'read src/really-long-router-file.ts',
					data: { name: 'read_file' }
				}),
				ev(3, { type: 'tool', ts: 113, text: 'read docs/设计.md', data: { name: 'read_file' } }),
				ev(4, { task_id: 't_2', key: 'T2', member: 'dev-b', text: '开始实现' }),
				ev(5, { text: '设计回访' })
			],
			TASKS,
			{ deploy, includeDeploy: true }
		);
		const members = TASKS.slice(0, 3).map((task) => ({ name: task.member }));
		const stages = buildStages(TASKS, new Map(), deploy);
		const layout = layoutSwimlanes(items, members, { stages, leadName: '统筹' });
		expect(layout.laneWidth).toBe(112);
		expect(layout.rowHeight).toBe(52);
		expect(layout.topPad).toBe(30);
		expect(layout.nodes.map((node) => node.y)).toEqual([30, 82, 134, 186, 238]);
		expect(
			layout.stageBands.map(({ stageId, startRow, endRow, topY, bottomY }) => [
				stageId,
				startRow,
				endRow,
				topY,
				bottomY
			])
		).toEqual([
			['layer-0', 0, 1, 4, 108],
			['layer-1', 2, 2, 108, 160],
			['layer-0', 3, 3, 160, 212],
			['deploy', 4, 4, 212, 264]
		]);
		expect(layout.stageBands[1]).toMatchObject({
			label: stages[1].shortLabel,
			color: stages[1].color
		});
		expect(new Set(layout.stageBands.map((band) => band.id)).size).toBe(4);
		expect(layout.nodes[1]).toMatchObject({
			fullTitle: items[1].title,
			memberName: 'dev-a',
			files: ['src/really-long-router-file.ts'],
			badge: '检索与阅读',
			durationSec: 13,
			stepCount: 2
		});
		expect(layout.nodes[1].label).toBe('really-lo…');
		expect(layout.nodes.at(-1)).toMatchObject({ memberName: '统筹', isHead: true });
		const moreMembers = [...members, { name: 'qa' }];
		const dense = layoutSwimlanes(items, moreMembers);
		expect(dense.laneWidth).toBe(96);
		expect(dense.stageBands.map((band) => band.label)).toEqual([
			'第1步',
			'第2步',
			'第1步',
			'审查与部署'
		]);
		const custom = layoutSwimlanes(items, moreMembers, { laneWidth: 80, rowHeight: 48 });
		expect(custom.laneWidth).toBe(80);
		expect(custom.lanes[1].x - custom.lanes[0].x).toBe(80);
		expect(custom.nodes[1].y - custom.nodes[0].y).toBe(48);
		expect(custom.width - custom.lanes.at(-1)!.x).toBe(custom.lanes[0].x);
	});

	it('keeps task-less lead items inside the stage that is already open', () => {
		const items = groupNarrative(
			[
				ev(1, { type: 'message', task_id: null, key: null, member: null, who: 'lead', text: '开工' }),
				ev(2, { text: '开始设计' }),
				ev(3, { task_id: 't_2', key: 'T2', member: 'dev-b', text: '开始实现' }),
				ev(4, { type: 'message', task_id: null, key: null, member: null, who: 'lead', text: '跟进' }),
				ev(5, { task_id: 't_2', key: 'T2', member: 'dev-b', text: '实现完成' })
			],
			TASKS
		);
		expect(items.map((item) => item.stageId)).toEqual([
			'layer-0',
			'layer-0',
			'layer-1',
			'layer-0',
			'layer-1'
		]);
		expect(sectionStageIds(items)).toEqual(['layer-0', 'layer-0', 'layer-1', 'layer-1', 'layer-1']);
		const layout = layoutSwimlanes(items, [{ name: 'dev-a' }, { name: 'dev-b' }], {
			stages: buildStages(TASKS, new Map())
		});
		expect(layout.stageBands.map(({ stageId, startRow, endRow }) => [stageId, startRow, endRow])).toEqual([
			['layer-0', 0, 1],
			['layer-1', 2, 4]
		]);
		// The stage filter still uses the item's own stage.
		expect(layout.nodes[3].stageId).toBe('layer-0');
	});

	it('returns only incident edges and direct neighbors, including a handoff without a target node', () => {
		const items = groupNarrative(
			[
				ev(1, { type: 'message', who: 'lead', text: '开始检查' }),
				ev(2, {
					type: 'handoff',
					data: {
						to: [
							{ member: 'dev-b', key: 'T2' },
							{ member: 'dev-c', key: 'T3' }
						]
					}
				}),
				ev(3, {
					task_id: 't_2',
					key: 'T2',
					member: 'dev-b',
					status: 'failed',
					sub_status: 'failed'
				}),
				ev(4, {
					type: 'attempt',
					task_id: 't_2',
					key: 'T2',
					member: 'dev-b',
					text: '开始第 2 次执行'
				}),
				ev(5, { type: 'message', who: 'lead', text: '等下一次更新' })
			],
			TASKS
		);
		const layout = layoutSwimlanes(items, []);
		const { nodeIds, edgeIds } = connectedSwimlaneIds(layout, items[1].id);
		expect(nodeIds).toEqual(new Set([items[0].id, items[1].id, items[2].id]));
		expect(layout.edges.filter((edge) => edgeIds.has(edge.id)).map((edge) => edge.kind)).toEqual([
			'steer',
			'handoff',
			'handoff'
		]);
		expect(connectedSwimlaneIds(layout, 'missing')).toEqual({
			nodeIds: new Set(),
			edgeIds: new Set()
		});
		expect(connectedSwimlaneIds(layout, null)).toEqual({ nodeIds: new Set(), edgeIds: new Set() });
		const pendingSteer = layout.edges.at(-1)!;
		expect(pendingSteer).toMatchObject({ fromNodeId: items.at(-1)?.id, toNodeId: null });
		expect(pendingSteer.toY).toBeLessThan(layout.height);
	});
});

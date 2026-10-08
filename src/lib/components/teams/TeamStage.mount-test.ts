// 协作台 stage rail, mounted in a DOM: every stage says where the team is (计划 → 批准 → 执行 →
// 整理结果 → 验收), what is happening right now, how long it has taken and about how long is left.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	getTeam: vi.fn(),
	followUpTeamConclusion: vi.fn(),
	getTeamEvents: vi.fn(async () => ({ events: [], next_after: 7, has_more: false, latest_seq: 7, reconcile: [] }))
}));
vi.mock('$lib/apis/teams', () => api);
const nav = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => nav);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const nowTs = () => Math.floor(Date.now() / 1000);

let app: any;
let target: any;

const mount = async (props: Record<string, unknown>) => {
	const { default: StageRail } = await import('./StageRail.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new StageRail({ target, props });
	await sleep(5);
	return app;
};

const steps = (active: number) =>
	['plan', 'approve', 'run', 'conclude', 'check'].map((key, i) => ({
		key,
		state: i < active ? 'done' : i === active ? 'active' : 'pending'
	}));

const text = (sel: string) => (target.querySelector(sel)?.textContent ?? '').replace(/\s+/g, ' ').trim();

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
});

describe('StageRail', () => {
	it('planning: the lead’s current step, time spent and about how long is left', async () => {
		const at = nowTs();
		await mount({
			stage: {
				key: 'planning',
				label: '负责人制定计划',
				now: '负责人（gpt-chat）在理解目标、挑选成员、拆分带依赖的任务',
				started_at: at - 12,
				at,
				eta: { seconds: 33, high: 60, basis: '按本机最近 10 次做计划的用时估算' },
				steps: steps(0)
			}
		});
		const rail = target.querySelector('[data-stage]');
		expect(rail.getAttribute('data-stage')).toBe('planning');
		expect(rail.classList.contains('tm-live')).toBe(true);
		expect(target.querySelector('[data-step="plan"]').getAttribute('aria-current')).toBe('step');
		expect(target.querySelector('[data-step="run"]').getAttribute('data-state')).toBe('pending');
		expect(text('[data-stage-now]')).toContain('gpt-chat');
		expect(text('[data-stage-clock]')).toMatch(/^已用 1\ds · 预计还要约 1 分钟$/);
		expect(text('[data-stage-basis]')).toContain('本机最近 10 次');
	});

	it('running: each member at work, its time against what such tasks usually take', async () => {
		const at = nowTs();
		await mount({
			stage: {
				key: 'running',
				label: '成员执行中',
				now: '#T1 researcher：搜索 · 看板工具（另有 1 个成员在并行）',
				started_at: at - 200,
				at,
				eta: { seconds: 420, high: 600, basis: '按本机最近 8 次 hermes 调研任务的用时估算' },
				steps: steps(2),
				done: 1,
				total: 4,
				running: [
					{ key: 'T1', member: 'researcher', text: '搜索 · 看板工具', since: at - 150, typical: 500, typical_high: 600 },
					{ key: 'T2', member: 'writer', text: '写文件 · advice.md', since: at - 30, typical: 120 }
				]
			}
		});
		expect(text('[data-step="run"]')).toContain('执行1/4');
		expect(text('[data-stage-eta]')).toBe('预计还要约 7–10 分钟');
		const lines = target.querySelectorAll('[data-stage-lines] li');
		expect(lines.length).toBe(2);
		expect(lines[0].textContent).toContain('搜索 · 看板工具');
		expect(lines[0].textContent).toContain('通常 8–10 分钟');
		expect(text('[data-stage-basis]')).toContain('含整理结果和验收');
	});

	it('approval: no clock, but how long the plan takes once approved', async () => {
		await mount({
			stage: {
				key: 'approval',
				label: '等你批准',
				now: '计划好了：看一下成员和任务，批准后才开始执行',
				at: nowTs(),
				after_approval: { seconds: 540, high: 760, basis: '按本机最近 8 次 hermes 调研任务的用时估算' },
				steps: steps(1)
			}
		});
		const rail = target.querySelector('[data-stage]');
		expect(rail.classList.contains('tm-live')).toBe(false);
		expect(rail.getAttribute('data-tone')).toBe('waiting');
		expect(text('[data-stage-clock]')).toBe('批准后预计 约 9–13 分钟 出结果');
		expect(text('[data-stage-clock]')).not.toContain('已用');
	});

	it('a member needs you: says who and why, promises no time', async () => {
		await mount({
			stage: {
				key: 'attention',
				label: '需要你处理',
				now: '#T2 writer 停下来问你：要不要附上来源',
				at: nowTs(),
				steps: steps(2),
				done: 1,
				total: 3
			}
		});
		expect(target.querySelector('[data-stage]').getAttribute('data-tone')).toBe('attention');
		expect(text('[data-stage-now]')).toContain('停下来问你');
		expect(target.querySelector('[data-stage-clock]')).toBeFalsy();
	});

	it('writing the result past its usual time says so instead of counting below zero', async () => {
		const at = nowTs() - 400;
		await mount({
			stage: {
				key: 'concluding',
				label: '整理完整结果',
				now: '负责人（gpt-chat）在把 3 个任务的成果整合成完整结果',
				started_at: at,
				at,
				eta: { seconds: 40, high: 60 },
				steps: steps(3)
			}
		});
		expect(text('[data-stage-eta]')).toBe('比平时久一些，应该快好了');
	});
});

describe('TeamChatCard (派发方式「协作台」 in a chat)', () => {
	it('shows the team’s stage live, then where its result is', async () => {
		const at = nowTs();
		const responses = [
			{
				team: { id: 'team-c', title: '戒烟计划', status: 'planning', member_count: 0, task_count: 0 },
				live: null,
				stage: {
					key: 'planning',
					label: '负责人制定计划',
					now: '负责人（gpt-chat）在理解目标、挑选成员、拆分带依赖的任务',
					started_at: at - 5,
					at,
					eta: { seconds: 40, high: 70 },
					steps: steps(0)
				}
			},
			{
				team: { id: 'team-c', title: '戒烟计划', status: 'running', phase: 'completed', member_count: 2, task_count: 3 },
				live: {},
				stage: { key: 'done', label: '已完成', now: '完整结果已经整理好', at, steps: steps(5) }
			}
		];
		api.getTeam.mockImplementation(async () => responses.shift() ?? responses[0]);
		const { default: TeamChatCard } = await import('./TeamChatCard.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		(globalThis as any).localStorage.token = 'tok';
		app = new TeamChatCard({ target, props: { teamId: 'team-c' } });
		const until = async (check: () => boolean) => {
			const end = Date.now() + 15000;
			while (!check()) {
				if (Date.now() > end) throw new Error('timed out');
				await sleep(20);
			}
		};
		await until(() => !!target.querySelector('[data-stage="planning"]'));
		expect(target.querySelector('[data-team-chat-card]').textContent).toContain('戒烟计划');
		expect(target.querySelector('[data-team-chat-open]').getAttribute('href')).toBe('/teams/team-c');
		expect(text('[data-stage-now]')).toContain('gpt-chat');
		expect(api.getTeam.mock.calls[0].slice(1)).toEqual(['team-c']);
	});

	const card = async (props: { teamId: string; history?: { messages: Record<string, any> } }) => {
		const { default: TeamChatCard } = await import('./TeamChatCard.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		(globalThis as any).localStorage.token = 'tok';
		app = new TeamChatCard({ target, props });
		const end = Date.now() + 15000;
		while (target.querySelector('[data-team-chat-state="loading"]')) {
			if (Date.now() > end) throw new Error('timed out');
			await sleep(20);
		}
	};
	const doneTeam = {
		team: {
			id: 'team-d',
			title: '看板调研',
			status: 'running',
			phase: 'completed',
			member_count: 2,
			task_count: 3,
			roster: [
				{ name: 'researcher', role: '调研' },
				{ name: 'writer', role: '写作' }
			],
			inputs: ['需求.pdf']
		},
		live: {},
		stage: { key: 'done', label: '已完成', at: nowTs(), steps: steps(5) }
	};

	it('done, with the result in this chat: one click down to it, the rest on the 协作台', async () => {
		api.getTeam.mockResolvedValue(doneTeam);
		const history = {
			messages: {
				n1: {
					id: 'n1',
					role: 'user',
					timestamp: 1,
					childrenIds: ['r1'],
					hermes_notice: { source: 'team', run_id: 'team:team-d:100' }
				},
				n2: {
					id: 'n2',
					role: 'user',
					timestamp: 2,
					childrenIds: ['r2'],
					hermes_notice: { source: 'team', run_id: 'team:team-d:200' }
				},
				other: {
					id: 'other',
					role: 'user',
					timestamp: 3,
					childrenIds: ['r3'],
					hermes_notice: { source: 'team', run_id: 'team:another:300' }
				}
			}
		};
		await card({ teamId: 'team-d', history });
		const el = target.querySelector('[data-team-chat-card]');
		expect(el.getAttribute('data-team-chat-state')).toBe('done');
		expect(el.textContent).toContain('负责人 + 2 位成员');
		expect(el.textContent).toContain('附带 1 个文件');
		expect(target.querySelector('[data-team-chat-bring]')).toBeFalsy();
		const scrolled: string[] = [];
		const reply = document.createElement('div');
		reply.id = 'message-r2'; // the newest version of the result
		(reply as any).scrollIntoView = () => scrolled.push(reply.id);
		document.body.appendChild(reply);
		target.querySelector('[data-team-chat-jump]').click();
		expect(scrolled).toEqual(['message-r2']);
		reply.remove();
		const links = [...target.querySelectorAll('[data-team-result-link]')].map((a: any) => [
			a.getAttribute('data-team-result-link'),
			a.getAttribute('href'),
			a.getAttribute('target')
		]);
		expect(links).toEqual([
			['page', '/teams/team-d/conclusion', null],
			['files', '/teams/team-d/conclusion#files', null],
			['process', '/teams/team-d/conclusion#process', null]
		]);
	});

	it('done, with the result not in this chat yet: brings it here', async () => {
		api.getTeam.mockResolvedValue(doneTeam);
		api.followUpTeamConclusion.mockResolvedValue({ chat_id: 'chat-elsewhere', created: false, posted: true });
		await card({ teamId: 'team-d', history: { messages: {} } });
		target.querySelector('[data-team-chat-bring]').click();
		const end = Date.now() + 5000;
		while (!nav.goto.mock.calls.length && Date.now() < end) await sleep(10);
		expect(api.followUpTeamConclusion.mock.calls[0].slice(1)).toEqual(['team-d']);
		// posted into the team's own chat, which is not the one on screen: go there
		expect(nav.goto).toHaveBeenCalledWith('/c/chat-elsewhere');
	});

	it('on screen, the card tells Hermes the team is being watched (no Telegram notice for it)', async () => {
		api.getTeamEvents.mockClear();
		api.getTeam.mockResolvedValue({
			team: { id: 'team-w', title: '周报', status: 'running', phase: 'running', member_count: 1, task_count: 2 },
			live: {},
			stage: { key: 'running', label: '执行中', at: nowTs(), steps: steps(2) }
		});
		await card({ teamId: 'team-w' });
		const end = Date.now() + 5000;
		while (!api.getTeamEvents.mock.calls.length && Date.now() < end) await sleep(10);
		// visible=true: Hermes' "the page is in front of the user"; one event at most, from the start
		expect(api.getTeamEvents.mock.calls[0].slice(1)).toEqual(['team-w', 0, 1, true]);
		app.$destroy();
		app = null;
		target.remove();

		// finished an hour ago: nothing left to announce, nothing to say
		api.getTeamEvents.mockClear();
		api.getTeam.mockResolvedValue({
			...doneTeam,
			team: { ...doneTeam.team, id: 'team-old', finished_at: nowTs() - 3600 }
		});
		await card({ teamId: 'team-old', history: { messages: {} } });
		await sleep(80);
		expect(api.getTeamEvents).not.toHaveBeenCalled();
	});

	it('a team deleted on the 协作台 leaves a quiet line, and the card stops asking', async () => {
		api.getTeam.mockReset();
		api.getTeam.mockRejectedValue(Object.assign(new Error('协作任务不存在'), { status: 404 }));
		await card({ teamId: 'team-x' });
		expect(target.querySelector('[data-team-chat-card]').getAttribute('data-team-chat-state')).toBe('gone');
		expect(text('[data-team-chat-gone]')).toContain('已经在协作台删除');
		expect(target.querySelector('[data-team-chat-open]')).toBeFalsy();
		expect(api.getTeam).toHaveBeenCalledTimes(1);
	});
});

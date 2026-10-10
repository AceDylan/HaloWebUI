// 再来一次 / 定时: the team page's dialog makes a new team or sets a schedule, and the 定时任务
// page lists the schedules with 立即运行 / 暂停 / 修改 / 取消.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/teams/t1');

const teams = vi.hoisted(() => ({
	repeatTeam: vi.fn(),
	getTeamSchedule: vi.fn(),
	setTeamSchedule: vi.fn(),
	deleteTeamSchedule: vi.fn(),
	listTeamSchedules: vi.fn()
}));
vi.mock('$lib/apis/teams', () => teams);
const hermes = vi.hoisted(() => ({
	listHermesJobs: vi.fn(),
	createHermesJob: vi.fn(),
	updateHermesJob: vi.fn(),
	deleteHermesJob: vi.fn(),
	hermesJobAction: vi.fn(),
	getHermesJobOutputs: vi.fn()
}));
vi.mock('$lib/apis/hermes', () => hermes);
const nav = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => nav);
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 15000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error(`timed out; text: ${document.body.textContent?.slice(0, 300)}`);
		await sleep(20);
	}
};
const q = (selector: string) => document.querySelector(selector) as any;

const TEAM = {
	id: 't1',
	title: '每周新闻汇总',
	goal: '汇总本周 AI 新闻',
	status: 'running',
	phase: 'completed',
	member_count: 2,
	task_count: 3,
	plan: { members: [{}, {}], tasks: [{}, {}, {}] }
};
const SCHEDULE = {
	team_id: 't1',
	freq: 'weekly',
	time: '09:00',
	weekday: 0,
	day: null,
	tz: 'Asia/Shanghai',
	enabled: true,
	next_run_at: 4_000_000_000,
	last_run_at: 3_900_000_000,
	last_team_id: 't9',
	last_error: null,
	label: '每周一 09:00'
};

let TeamRepeat: any;
let Schedules: any;
let app: any;
let target: any;

beforeAll(async () => {
	TeamRepeat = (await import('./TeamRepeat.svelte')).default;
	Schedules = (await import('../workspace/Schedules.svelte')).default;
}, 120_000);

beforeEach(() => {
	[...Object.values(teams), ...Object.values(hermes), nav.goto, toast.success, toast.error].forEach((fn: any) =>
		fn.mockReset()
	);
	(globalThis as any).localStorage.token = 'tok';
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

const mount = async (Component: any, props = {}) => {
	const { writable } = await import('svelte/store');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Component({ target, props, context: new Map([['i18n', writable({ t: (s: string) => s })]]) });
};

describe('TeamRepeat', () => {
	it('repeats the team at once and opens the new one', async () => {
		teams.getTeamSchedule.mockResolvedValue({ schedule: null, repeatable: true });
		teams.repeatTeam.mockResolvedValue({ ...TEAM, id: 't2', status: 'running' });
		await mount(TeamRepeat, { team: TEAM });
		await until(() => teams.getTeamSchedule.mock.calls.length === 1);
		expect(q('[data-team-repeat]').textContent).toContain('再来一次');
		q('[data-team-repeat]').click();
		await until(() => !!q('[data-team-repeat-dialog]'));
		expect(q('[data-team-repeat-dialog]').textContent).toContain('2 人、3 个任务');
		q('[data-team-repeat-start]').click();
		await until(() => nav.goto.mock.calls.length === 1);
		expect(teams.repeatTeam).toHaveBeenCalledWith('tok', 't1', true);
		expect(nav.goto).toHaveBeenCalledWith('/teams/t2');
	});

	it('sets a weekly schedule and the button then reads it', async () => {
		teams.getTeamSchedule.mockResolvedValue({ schedule: null, repeatable: true });
		teams.setTeamSchedule.mockResolvedValue({ schedule: { ...SCHEDULE, weekday: 2, time: '07:30', label: '每周三 07:30' } });
		await mount(TeamRepeat, { team: TEAM });
		await until(() => teams.getTeamSchedule.mock.calls.length === 1);
		q('[data-team-repeat]').click();
		await until(() => !!q('[data-team-schedule-freq]'));
		q('[data-team-schedule-freq] [data-value="weekly"]').click();
		await sleep(10);
		q('[data-team-schedule-weekday] [data-value="2"]').click();
		const input = q('[data-team-schedule-time]');
		input.value = '07:30';
		input.dispatchEvent(new (window as any).Event('input'));
		await sleep(10);
		q('[data-team-schedule-save]').click();
		await until(() => teams.setTeamSchedule.mock.calls.length === 1);
		expect(teams.setTeamSchedule.mock.calls[0].slice(1)).toEqual([
			't1',
			{ freq: 'weekly', time: '07:30', enabled: true, weekday: 2, day: null }
		]);
		await until(() => q('[data-team-repeat]').textContent.includes('每周三 07:30'));
		expect(q('[data-team-schedule-state]').textContent).toContain('已开启');
	});
});

describe('定时任务 page: 协作台定时', () => {
	it('lists team schedules and runs, pauses or cancels them', async () => {
		const { config } = await import('$lib/stores');
		config.set({ features: { enable_agent_teams: true } } as any);
		hermes.listHermesJobs.mockResolvedValue([]);
		teams.listTeamSchedules.mockResolvedValue({
			schedules: [
				{
					...SCHEDULE,
					team: { id: 't1', title: '每周新闻汇总', goal: '汇总' },
					last_team: { id: 't9', title: '每周新闻汇总', status: 'running', phase: 'completed', chat_id: 'c9' }
				}
			]
		});
		teams.repeatTeam.mockResolvedValue({ ...TEAM, id: 't3' });
		teams.setTeamSchedule.mockResolvedValue({ schedule: { ...SCHEDULE, enabled: false } });
		await mount(Schedules);
		await until(() => !!q('[data-team-schedule="t1"]'));
		const card = q('[data-team-schedule="t1"]');
		expect(card.textContent).toContain('每周一 09:00');
		expect(card.textContent).toContain('已完成');
		expect(card.querySelector('[data-team-schedule-edit]').getAttribute('href')).toBe('/teams/t1?schedule=1');
		// no hermes job is queued: the team's schedule leads the page
		expect(q('[data-schedule-next-up]').textContent).toContain('协作台 · 每周新闻汇总');
		card.querySelector('[data-team-schedule-run]').click();
		await until(() => teams.repeatTeam.mock.calls.length === 1);
		expect(teams.repeatTeam).toHaveBeenCalledWith('tok', 't1', true);
		card.querySelector('[data-team-schedule-toggle]').click();
		await until(() => teams.setTeamSchedule.mock.calls.length === 1);
		expect(teams.setTeamSchedule.mock.calls[0][2]).toMatchObject({ freq: 'weekly', weekday: 0, enabled: false });
		config.set(undefined as any);
	});
});

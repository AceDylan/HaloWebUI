// 协作台 × 助手库: the plan review says per member what approval will do with its assistant
// (选用 / 升级 / 新建 / 仅本次) and shows the proposed prompt; a started team shows what was
// applied and can undo its upgrade; 「用于协作」 (/teams?assistant=<ref>) puts a removable chip
// on the composer and sends the ref with the new team.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/teams?assistant=model:asst-viz');

const api = vi.hoisted(() => ({
	checkRunners: vi.fn(),
	createTeam: vi.fn(),
	deleteTeam: vi.fn(),
	getTeamsMeta: vi.fn(),
	listTeams: vi.fn(),
	getTeamTask: vi.fn(),
	sendTeamMessage: vi.fn(),
	retryTeamTask: vi.fn(),
	taskDiagnosis: vi.fn(),
	markTeamAssistantReverted: vi.fn(),
	teamFilePath: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`
}));
vi.mock('$lib/apis/teams', () => api);
const library = vi.hoisted(() => ({ undoAssistantRun: vi.fn(), listLibrary: vi.fn() }));
vi.mock('$lib/apis/assistant-library', async (original) => ({
	...((await original()) as object),
	...library
}));
vi.mock('$lib/apis/files', () => ({ uploadFile: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn(), replaceState: vi.fn() }));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 20000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

let app: any;
let target: any;

const mount = async (Component: any, props: Record<string, unknown> = {}) => {
	const { writable } = await import('svelte/store');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Component({
		target,
		props,
		context: new Map([['i18n', writable({ t: (s: string) => s })]])
	});
	await sleep(5);
	return app;
};

beforeEach(() => {
	Object.values(api).forEach((fn: any) => fn?.mockReset?.());
	Object.values(library).forEach((fn: any) => fn.mockReset());
	(globalThis as any).localStorage.token = 'tok';
});

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
	document.body.innerHTML = '';
});

const PROMPT = '你是图表分析师。先澄清目标，再选图表，最后自查数字。新增：注明数据口径。';

const plan = {
	title: '季度报告',
	members: [
		{
			name: 'analyst',
			role: '数据分析',
			executor: 'hermes',
			assistant: {
				ref: 'model:asst-viz',
				id: 'asst-viz',
				name: '图表分析师',
				emoji: '📊',
				action: 'update',
				proposal: 'model:asst-viz',
				reason: '做图表的老手'
			}
		},
		{
			name: 'writer',
			role: '撰写',
			executor: 'hermes',
			assistant: { ref: '', id: '', name: '报告撰稿人', action: 'create', proposal: 'new:A1' }
		},
		{
			name: 'seo',
			role: '搜索优化',
			executor: 'hermes',
			assistant: { ref: 'model:asst-seo', id: 'asst-seo', name: 'SEO 顾问', action: 'use' },
			assistant_preferred: true
		},
		{
			name: 'reviewer',
			role: '评审',
			executor: 'hermes',
			assistant: { id: '18', name: '测试工程师', emoji: '🧪' }
		}
	],
	tasks: [
		{ key: 'T1', title: '分析', member: 'analyst', depends_on: [] },
		{ key: 'T2', title: '撰写', member: 'writer', depends_on: ['T1'] },
		{ key: 'T3', title: 'SEO', member: 'seo', depends_on: [] },
		{ key: 'T4', title: '评审', member: 'reviewer', depends_on: ['T2'] }
	],
	layers: [['T1', 'T3'], ['T2'], ['T4']],
	widest_layer: 2,
	assistant_proposals: [
		{
			key: 'model:asst-viz',
			action: 'update',
			ref: 'model:asst-viz',
			name: '图表分析师',
			system_prompt: PROMPT,
			change: '会注明数据口径'
		},
		{ key: 'new:A1', action: 'create', name: '报告撰稿人', system_prompt: '你是报告撰稿人。' }
	],
	assistant_library: { may_write: true }
};

describe('PlanReview × 助手库', () => {
	it('labels each member’s assistant and shows the proposed prompt', async () => {
		const { default: PlanReview } = await import('./PlanReview.svelte');
		await mount(PlanReview, { team: { id: 'team-1', status: 'plan_ready', plan } });
		const member = (name: string) => target.querySelector(`[data-plan-member="${name}"]`) as any;
		const label = (name: string) =>
			member(name).querySelector('[data-assistant-action]')?.textContent?.trim();
		expect(label('analyst')).toBe('升级');
		expect(label('writer')).toBe('新建');
		expect(label('seo')).toBe('选用');
		expect(label('reviewer')).toBe('选用模板'); // a plan from before the library
		expect(member('reviewer').querySelector('[data-assistant="18"]').textContent).toContain('测试工程师');
		expect(member('analyst').querySelector('[data-assistant-why]').textContent).toContain('做图表的老手');
		expect(target.querySelector('[data-assistant-writes]').textContent).toContain('升级 1 个、新建 1 个');

		expect(member('analyst').querySelector('[data-assistant-prompt]')).toBeFalsy();
		member('analyst').querySelector('[data-assistant-prompt-toggle]').click();
		await sleep(5);
		const shown = member('analyst').querySelector('[data-assistant-prompt]');
		expect(shown.textContent).toContain('这次升级：会注明数据口径');
		expect(shown.textContent).toContain('注明数据口径。');
		expect(member('seo').querySelector('[data-assistant-prompt-toggle]')).toBeFalsy();
	});

	it('after a failed start shows what was already applied', async () => {
		const { default: PlanReview } = await import('./PlanReview.svelte');
		const applied = {
			run_ref: 'team:team-1',
			at: 1,
			members: {
				analyst: { action: 'temporary', saved: false, note: '这个助手刚被改过，本次临时补充设定' }
			}
		};
		await mount(PlanReview, {
			team: { id: 'team-1', status: 'start_failed', plan: { ...plan, assistants_applied: applied } }
		});
		const analyst = target.querySelector('[data-plan-member="analyst"]') as any;
		expect(analyst.querySelector('[data-assistant-action]').textContent.trim()).toBe('仅本次');
		expect(analyst.textContent).toContain('刚被改过');
		expect(target.querySelector('[data-assistant-writes]')).toBeFalsy();
	});
});

describe('Inspector × 助手库', () => {
	it('shows the applied upgrade and undoes it', async () => {
		const { default: Inspector } = await import('./Inspector.svelte');
		const applied = {
			run_ref: 'team:team-1',
			at: 1,
			members: {
				analyst: {
					action: 'update',
					saved: true,
					id: 'asst-viz',
					name: '图表分析师',
					version: 4,
					system: PROMPT,
					change: '会注明数据口径',
					reason: '做图表的老手'
				}
			}
		};
		const members = [
			{
				name: 'analyst',
				role: '数据分析',
				executor: 'hermes',
				assistant: { id: 'asst-viz', name: '图表分析师', emoji: '📊', action: 'update', version: 4 }
			}
		];
		library.undoAssistantRun.mockResolvedValue({ id: 'asst-viz', version: 5 });
		const reverted = { id: 'team-1', plan: { ...plan, assistants_applied: applied } };
		api.markTeamAssistantReverted.mockResolvedValue(reverted);
		await mount(Inspector, {
			teamId: 'team-1',
			memberName: 'analyst',
			tasks: [],
			states: new Map(),
			members,
			events: [],
			assistantsApplied: applied
		});
		const row = target.querySelector('[data-member-assistant]') as any;
		expect(row.textContent).toContain('第 4 版');
		expect(row.querySelector('[data-assistant-action]').textContent.trim()).toBe('升级');
		expect(row.textContent).toContain('这次升级：会注明数据口径');
		const seen: any[] = [];
		app.$on('team', (e: any) => seen.push(e.detail));
		row.querySelector('[data-assistant-undo]').click();
		await until(() => seen.length > 0);
		expect(library.undoAssistantRun).toHaveBeenCalledWith('tok', 'asst-viz', 'team:team-1', PROMPT);
		expect(api.markTeamAssistantReverted).toHaveBeenCalledWith('tok', 'team-1', 'asst-viz');
		expect(seen[0]).toBe(reverted);
		app.$set({
			assistantsApplied: { ...applied, members: { analyst: { ...applied.members.analyst, reverted: true } } }
		});
		await sleep(5);
		expect(row.querySelector('[data-assistant-undo]')).toBeFalsy();
		expect(row.textContent).toContain('已撤销升级');
	});

	it('says when the planned assistant was gone at approval', async () => {
		const { default: Inspector } = await import('./Inspector.svelte');
		await mount(Inspector, {
			teamId: 'team-1',
			memberName: 'charter',
			tasks: [],
			states: new Map(),
			members: [{ name: 'charter', role: '作图', executor: 'hermes', assistant: null }],
			events: [],
			assistantsApplied: {
				run_ref: 'team:team-1',
				at: 1,
				members: {
					charter: { action: 'generic', saved: false, note: '「图表分析师」已不在助手库（删除或归档），按角色「作图」执行' }
				}
			}
		});
		const row = target.querySelector('[data-member-assistant]') as any;
		expect(row.querySelector('[data-assistant-action]').textContent.trim()).toBe('通用角色');
		expect(row.textContent).toContain('已不在助手库');
	});
});

describe('TeamsHome 「用于协作」', () => {
	it('shows the picked assistant as a removable chip and sends it with the team', async () => {
		api.listTeams.mockResolvedValue({ teams: [] });
		api.getTeamsMeta.mockResolvedValue(null);
		api.createTeam.mockResolvedValue({ id: 't-new' });
		library.listLibrary.mockResolvedValue({
			assistants: [{ ref: 'model:asst-viz', id: 'asst-viz', name: '图表分析师', emoji: '📊' }],
			may_write: true,
			favorites: []
		});
		const { default: Home } = await import('./TeamsHome.svelte');
		await mount(Home);
		await until(() => !!target.querySelector('[data-team-assistant]')?.textContent?.includes('图表分析师'));
		const chip = target.querySelector('[data-team-assistant]') as any;
		expect(chip.getAttribute('data-team-assistant')).toBe('model:asst-viz');
		expect(chip.textContent).toContain('指定成员助手：图表分析师');

		const goal = target.querySelector('#team-goal') as any;
		goal.value = '做一份季度图表报告';
		goal.dispatchEvent(new (globalThis as any).Event('input', { bubbles: true }));
		await sleep(5);
		target.querySelector('[data-team-composer]').dispatchEvent(
			new (globalThis as any).Event('submit', { bubbles: true, cancelable: true })
		);
		await until(() => api.createTeam.mock.calls.length > 0);
		expect(api.createTeam.mock.calls[0][7]).toEqual(['model:asst-viz']);

		chip.querySelector('[data-team-assistant-remove]').click();
		await sleep(5);
		expect(target.querySelector('[data-team-assistant]')).toBeFalsy();
	});
});

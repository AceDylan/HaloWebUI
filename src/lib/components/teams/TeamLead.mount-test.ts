// 协作台, the lead after approval: 对负责人说 and the plan change it proposes (applied only by the
// user's click), the lead's diagnosis of a failed task, and the lead's notes in the feed.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	adjustTeam: vi.fn(),
	decideTeamChange: vi.fn(),
	taskDiagnosis: vi.fn(),
	getTeamTask: vi.fn(),
	sendTeamMessage: vi.fn(),
	retryTeamTask: vi.fn(),
	teamFilePath: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`,
	teamFileUrl: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`
}));
vi.mock('$lib/apis/teams', () => api);
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

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
	for (const fn of Object.values(api))
		if (typeof (fn as any).mockReset === 'function') (fn as any).mockReset();
	api.getTeamTask.mockResolvedValue({ attempts: [], comments: [], log: null });
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
});

const PROPOSAL = {
	reply: '加一个测试成员写接口测试，页面那步改成先出线框。',
	add_members: [
		{ name: 'qa-engineer', role: '测试', kind: 'code', executor: 'cchclaude', runner: 'codex' }
	],
	add_tasks: [
		{
			key: 'T4',
			title: '接口测试',
			description: '给 api.md 写 tests.md',
			member: 'qa-engineer',
			depends_on: ['T1']
		}
	],
	edit_tasks: [
		{
			key: 'T2',
			task_id: 't_2',
			title: '写页面',
			description: '先出线框 wireframe.md',
			retry: true
		}
	],
	cancel_tasks: [{ key: 'T3', task_id: 't_3', title: '评审', state: 'waiting_deps' }],
	notes: ['T5 依赖 T3：取消后它们不再等它，直接开始']
};

describe('LeadDesk', () => {
	it('sends what you say to the lead and waits while it thinks', async () => {
		const { default: LeadDesk } = await import('./LeadDesk.svelte');
		api.adjustTeam.mockResolvedValue({ id: 'abcd1234', status: 'thinking' });
		const changed = vi.fn();
		await mount(LeadDesk, { teamId: 'team-1', change: null, phase: 'running' });
		app.$on('changed', changed);
		expect(target.querySelector('[data-lead-proposal]')).toBeFalsy();
		const textarea = target.querySelector('[data-lead-compose] textarea') as any;
		expect(textarea.getAttribute('placeholder')).toContain('对负责人说');
		textarea.value = '再加上接口测试';
		textarea.dispatchEvent(new Event('input'));
		await sleep(5);
		const enter = new Event('keydown') as any;
		enter.key = 'Enter';
		textarea.dispatchEvent(enter);
		await sleep(10);
		expect(api.adjustTeam).toHaveBeenCalledWith('tok', 'team-1', '再加上接口测试');
		expect(changed).toHaveBeenCalled();
		app.$set({
			change: { id: 'abcd1234', status: 'thinking', text: '再加上接口测试', requested_at: 1 }
		});
		await sleep(5);
		const card = target.querySelector('[data-lead-proposal]');
		expect(card.getAttribute('data-change-status')).toBe('thinking');
		expect(card.textContent).toContain('你说：再加上接口测试');
		expect(target.querySelector('[data-lead-compose] textarea').disabled).toBe(true);
		expect(target.querySelector('[data-change-apply]')).toBeFalsy();
	});

	it('shows the proposed change and applies it only on your click', async () => {
		const { default: LeadDesk } = await import('./LeadDesk.svelte');
		api.decideTeamChange.mockResolvedValue({ applied: true, reopened: true, added: ['T4'] });
		await mount(LeadDesk, {
			teamId: 'team-1',
			phase: 'completed',
			change: {
				id: 'abcd1234',
				status: 'ready',
				text: '加上接口测试',
				via: 'telegram',
				requested_at: 1,
				proposal: PROPOSAL,
				model: 'gpt-chat'
			}
		});
		const card = target.querySelector('[data-lead-proposal]');
		expect(card.textContent).toContain('提出了计划变更');
		expect(card.textContent).toContain('来自 Telegram');
		expect(target.querySelector('[data-lead-reply]').textContent).toContain('加一个测试成员');
		const items = Array.from(target.querySelectorAll('[data-change-item]')) as any[];
		expect(items.map((li) => li.getAttribute('data-change-item'))).toEqual([
			'member',
			'task',
			'edit',
			'cancel'
		]);
		expect(items[0].textContent).toContain('qa-engineer');
		expect(items[1].textContent).toContain('#T4');
		expect(items[1].textContent).toContain('等 #T1');
		expect(items[2].textContent).toContain('改写重试');
		expect(card.textContent).toContain('应用后重新开工');
		expect(card.textContent).toContain('注意：T5 依赖 T3');
		expect(api.decideTeamChange).not.toHaveBeenCalled();
		const apply = target.querySelector('[data-change-apply]');
		expect(apply.textContent).toContain('应用变更（4 项）');
		apply.click();
		await sleep(10);
		expect(api.decideTeamChange).toHaveBeenCalledWith('tok', 'team-1', 'abcd1234', 'apply');
	});

	it('a plain answer has no change to apply, only 知道了', async () => {
		const { default: LeadDesk } = await import('./LeadDesk.svelte');
		api.decideTeamChange.mockResolvedValue({ discarded: true });
		await mount(LeadDesk, {
			teamId: 'team-1',
			phase: 'running',
			change: {
				id: 'abcd1234',
				status: 'answered',
				text: '进展怎么样？',
				requested_at: 1,
				proposal: {
					...PROPOSAL,
					reply: '接口快好了。',
					add_members: [],
					add_tasks: [],
					edit_tasks: [],
					cancel_tasks: [],
					notes: []
				}
			}
		});
		expect(target.querySelector('[data-change-apply]')).toBeFalsy();
		expect(target.querySelector('[data-change-item]')).toBeFalsy();
		target.querySelector('[data-change-dismiss]').click();
		await sleep(10);
		expect(api.decideTeamChange).toHaveBeenCalledWith('tok', 'team-1', 'abcd1234', 'discard');
	});
});

const failedTask = (diagnosis: Record<string, unknown>) => ({
	id: 't_1',
	key: 'T1',
	seq: 1,
	title: '写接口',
	member: 'backend-dev',
	executor: 'cchclaude',
	status: 'blocked',
	sub_status: 'failed',
	parents: [],
	children: [],
	attempts: 1,
	block_reason: 'cchclaude 运行失败：quota exceeded',
	diagnosis
});

const inspect = async (task: any) => {
	const { default: Inspector } = await import('./Inspector.svelte');
	await mount(Inspector, {
		teamId: 'team-1',
		taskId: 't_1',
		tasks: [task],
		states: new Map([[task.id, { status: task.status, sub_status: task.sub_status }]]),
		members: [{ name: 'backend-dev', role: '后端', executor: 'cchclaude', status: 'failed' }],
		events: []
	});
};

describe('Inspector (diagnosis)', () => {
	it('shows the lead’s reading of a failure and applies its suggestion in one click', async () => {
		api.taskDiagnosis.mockResolvedValue({ applied: 'switch_runner' });
		await inspect(
			failedTask({
				status: 'ready',
				cause: 'cchclaude 中转额度用完了',
				action: 'switch_runner',
				action_label: '换执行器重试',
				runner: 'codex',
				model: 'gpt-chat'
			})
		);
		const card = target.querySelector('[data-task-diagnosis]');
		expect(card.getAttribute('data-task-diagnosis')).toBe('ready');
		expect(card.textContent).toContain('cchclaude 中转额度用完了');
		expect(card.textContent).toContain('建议：换执行器重试');
		expect(card.textContent).toContain('codex');
		target.querySelector('[data-diagnosis-apply]').click();
		await sleep(10);
		expect(api.taskDiagnosis).toHaveBeenCalledWith('tok', 'team-1', 't_1', 'apply');
	});

	it('a question for you is not applied by a click', async () => {
		await inspect(
			failedTask({
				status: 'ready',
				cause: '需要 GitHub 账号',
				action: 'ask_user',
				action_label: '需要你决定',
				note: '用哪个 GitHub 账号？'
			})
		);
		const card = target.querySelector('[data-task-diagnosis]');
		expect(card.textContent).toContain('要问你：用哪个 GitHub 账号？');
		expect(target.querySelector('[data-diagnosis-apply]')).toBeFalsy();
		expect(target.querySelector('[data-diagnosis-again]')).toBeTruthy();
	});
});

describe('CommFeed (lead)', () => {
	it('shows the lead’s note to a member as the lead’s', async () => {
		const { default: CommFeed } = await import('./CommFeed.svelte');
		await mount(CommFeed, {
			events: [
				{
					id: '1',
					seq: 1,
					ts: 1790900001,
					task_id: 't_1',
					key: 'T1',
					member: 'backend-dev',
					kind: 'commented',
					run_id: null,
					type: 'message',
					who: 'lead',
					author: 'team-lead',
					text: '用 Markdown 表格输出接口列表',
					data: { comment_id: 9, delivered_seq: 2, delivered_via: 'attempt_context' }
				}
			],
			members: [{ name: 'backend-dev', role: '后端' }]
		});
		const item = target.querySelector('[data-event-type="message"]');
		expect(item.textContent).toContain('负责人 → backend-dev');
		expect(item.querySelector('.bubble-lead')).toBeTruthy();
		expect(item.textContent).toContain('已随新的执行尝试送达');
	});
});

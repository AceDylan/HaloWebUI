// 协作台 变更: a project team's branch, commits per task, files with +/−, a file's diff on demand,
// and merge / push only as the user's own clicks (and only once the team is over).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	getTeamChanges: vi.fn(),
	getTeamChangeDiff: vi.fn(),
	mergeTeamChanges: vi.fn(),
	pushTeamChanges: vi.fn(),
	discardTeamChanges: vi.fn()
}));
vi.mock('$lib/apis/teams', () => api);
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const CHANGES = {
	project: {
		path: '/root/myapp',
		name: 'myapp',
		base_branch: 'main',
		base_sha: 'abcdef1234567890',
		branch: 'halo/halo-1234',
		pushed: null
	},
	available: true,
	commits: [
		{
			sha: 'b'.repeat(40),
			subject: '[T2 · frontend-dev] 写页面',
			author: 'Halo Team',
			at: 1790900100,
			task_key: 'T2',
			member: 'frontend-dev'
		},
		{
			sha: 'a'.repeat(40),
			subject: '[T1 · backend-dev] 写接口',
			author: 'Halo Team',
			at: 1790900000,
			task_key: 'T1',
			member: 'backend-dev'
		}
	],
	files: [
		{ path: 'app.py', added: 3, removed: 1, binary: false },
		{ path: 'api.md', added: 10, removed: 0, binary: false }
	],
	pending: [],
	added: 13,
	removed: 1,
	base_moved: 0,
	merged: false
};

let app: any;
let target: any;

const mount = async (props: Record<string, unknown>) => {
	const { writable } = await import('svelte/store');
	const { default: ChangesView } = await import('./ChangesView.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new ChangesView({
		target,
		props,
		context: new Map([['i18n', writable({ t: (s: string) => s })]])
	});
	await sleep(10);
	return app;
};

beforeEach(() => {
	(globalThis as any).localStorage.token = 'tok';
	for (const fn of Object.values(api)) fn.mockReset();
	api.getTeamChanges.mockResolvedValue(CHANGES);
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
});

describe('ChangesView', () => {
	it('shows the branch, commits per task and files, and opens a diff on click', async () => {
		api.getTeamChangeDiff.mockResolvedValue({
			path: 'app.py',
			diff: "@@ -1 +1 @@\n-print('v1')\n+print('v2')"
		});
		await mount({ teamId: 'team-1', phase: 'completed' });
		expect(api.getTeamChanges).toHaveBeenCalledWith('tok', 'team-1');
		expect(target.textContent).toContain('halo/halo-1234');
		expect(target.querySelector('[data-changes-stats]').textContent).toContain('+13');
		const commits = Array.from(target.querySelectorAll('[data-changes-commits] li')) as any[];
		expect(commits.map((li) => li.textContent.replace(/\s+/g, ' ').trim().slice(0, 9))).toEqual([
			'T2 写页面 fr',
			'T1 写接口 ba'
		]);
		target.querySelector('[data-changes-file="app.py"]').click();
		await sleep(10);
		expect(api.getTeamChangeDiff).toHaveBeenCalledWith('tok', 'team-1', 'app.py');
		const lines = Array.from(target.querySelectorAll('[data-changes-diff] div')) as any[];
		expect(lines.map((d) => d.textContent)).toEqual([
			'@@ -1 +1 @@',
			"-print('v1')",
			"+print('v2')"
		]);
		expect(lines[2].className).toContain('emerald');
	});

	it('offers merge / push only once the team is over, and merges only after confirming', async () => {
		await mount({ teamId: 'team-1', phase: 'running' });
		expect(target.querySelector('[data-changes-merge]')).toBeFalsy();
		expect(target.textContent).toContain('成员还在干活');
		app.$set({ phase: 'completed' });
		await sleep(10);
		const merge = target.querySelector('[data-changes-merge]');
		expect(merge.textContent).toContain('合并到 main');
		merge.click();
		await sleep(5);
		expect(api.mergeTeamChanges).not.toHaveBeenCalled(); // a confirmation first
		api.mergeTeamChanges.mockResolvedValue({
			merged: true,
			how: 'fast-forward',
			sha: 'c',
			base_branch: 'main'
		});
		api.getTeamChanges.mockResolvedValue({ ...CHANGES, merged: true });
		const confirm = Array.from(document.querySelectorAll('button')).find(
			(b: any) => b.textContent.trim() === '合并'
		) as any;
		confirm.click();
		await sleep(20);
		expect(api.mergeTeamChanges).toHaveBeenCalledWith('tok', 'team-1');
		expect(target.querySelector('[data-changes-merged]')).toBeTruthy();
		expect(target.querySelector('[data-changes-push-base]').textContent).toContain('推送 main');
		expect(api.pushTeamChanges).not.toHaveBeenCalled();
	});

	it('explains a branch that was cleaned up because the team changed nothing', async () => {
		api.getTeamChanges.mockResolvedValue({
			project: { ...CHANGES.project, discarded_at: 1790900500, auto_cleaned: true },
			available: false,
			commits: [],
			files: [],
			pending: [],
			merged: false
		});
		await mount({ teamId: 'team-3', phase: 'completed' });
		expect(target.querySelector('[data-changes-discarded]').textContent).toContain('没有改动，分支已自动清理');
		expect(target.textContent).toContain('重新开一个分支');
		expect(target.querySelector('[data-changes-merge]')).toBeFalsy();
		expect(target.querySelector('[data-changes-discard]')).toBeFalsy();
	});

	it('says so when the team did not work on a project', async () => {
		api.getTeamChanges.mockResolvedValue({ project: null });
		await mount({ teamId: 'team-2', phase: 'completed' });
		expect(target.textContent).toContain('不是在项目里做的');
	});
});

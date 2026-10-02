// 协作台: the conclusion (report states, mixed agent output rendered with images from the
// workspace), runner badges / availability, and a plan member whose runner fell back.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({
	getTeamConclusion: vi.fn(),
	writeTeamConclusion: vi.fn(),
	followUpTeamConclusion: vi.fn(),
	saveTeamConclusionToKnowledge: vi.fn(),
	getTeamsMeta: vi.fn(),
	illustrateTeamConclusion: vi.fn(),
	teamFilePath: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`,
	teamFileUrl: (teamId: string, path: string) => `/api/v1/teams/${teamId}/files/${path}`
}));
vi.mock('$lib/apis/teams', () => api);
const nav = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
// CodeMirror cannot run in the test DOM; code blocks render through a plain stand-in.
vi.mock('$lib/components/common/CodeEditor.svelte', async () => ({
	default: (await import('$lib/test-support/CodeEditorStub.svelte')).default
}));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 60000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

const REPORT = [
	'# 看板工具调研结论',
	'',
	'> 推荐 Focalboard：功能够用、可自托管。',
	'',
	'## 结论摘要',
	'',
	'- 三个工具都能自托管',
	'- Focalboard 最轻',
	'',
	'## 关键成果',
	'',
	'| 工具 | 许可 | 结论 |',
	'| --- | --- | --- |',
	'| Focalboard | MIT | 推荐 |',
	'| Wekan | MIT | 备选 |',
	'',
	'```bash',
	'docker run -p 8000:8000 mattermost/focalboard',
	'```',
	'',
	'![首页截图](shots/home.png)',
	'',
	'## 产出物',
	'',
	'- [对比表](compare.md)'
].join('\n');

const CONCLUSION = {
	status: 'ready',
	entry: {
		status: 'ready',
		source: 'lead',
		model: 'gpt-chat',
		model_label: 'Hermes 默认模型',
		generated_at: 1790900000,
		tasks_done: 2,
		tasks_total: 2
	},
	markdown: REPORT,
	workspace: '/root/work/agent-teams/halo-x',
	files: [
		{ path: 'shots/home.png', size: 20480, mtime: 1790900000, kind: 'image' },
		{ path: 'compare.md', size: 2048, mtime: 1790900000, kind: 'text' }
	],
	tasks: [
		{
			id: 't_1',
			key: 'T1',
			title: '调研',
			member: 'researcher',
			executor: 'hermes',
			status: 'done',
			result: '{"tools": ["Focalboard", "Wekan"]}',
			error: '',
			attempts: 1
		},
		{
			id: 't_2',
			key: 'T2',
			title: '写报告',
			member: 'writer',
			executor: 'anyclaude',
			status: 'done',
			result: '报告见 compare.md',
			error: '',
			attempts: 2
		}
	]
};

let ConclusionView: any;
let app: any;
let target: any;

const mount = async (Component: any, props: Record<string, unknown>) => {
	const { writable } = await import('svelte/store');
	target = document.createElement('div');
	document.body.appendChild(target);
	// ConfirmDialog reads the app's i18n store from context.
	app = new Component({
		target,
		props,
		context: new Map([['i18n', writable({ t: (s: string) => s })]])
	});
	await sleep(5);
	return app;
};

beforeAll(async () => {
	ConclusionView = (await import('./ConclusionView.svelte')).default;
	await import('$lib/components/chat/Messages/Markdown.svelte'); // warm the renderer once
});

beforeEach(() => {
	(globalThis as any).localStorage.token = 'tok';
	api.getTeamConclusion.mockReset();
	api.writeTeamConclusion.mockReset();
});

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
});

describe('ConclusionView', () => {
	it('renders a mixed report with workspace images, a table, code, files and task results', async () => {
		api.getTeamConclusion.mockResolvedValue(CONCLUSION);
		await mount(ConclusionView, {
			teamId: 'team-1',
			title: '看板调研',
			phase: 'completed',
			variant: 'page'
		});
		await until(() => !!target.querySelector('[data-team-report] h1'));
		const report = target.querySelector('[data-team-report]');
		expect(report.querySelector('h1').textContent).toContain('看板工具调研结论');
		expect(report.querySelector('table')).toBeTruthy();
		expect(report.textContent).toContain('docker run -p 8000:8000');
		const img = report.querySelector('img');
		expect(img.getAttribute('src')).toBe('/api/v1/teams/team-1/files/shots/home.png');
		const link = Array.from(report.querySelectorAll('a')).find((a: any) =>
			a.textContent.includes('对比表')
		) as any;
		expect(link.getAttribute('href')).toBe('/api/v1/teams/team-1/files/compare.md');
		expect(target.querySelector('[data-conclusion-meta]').textContent).toContain('gpt-chat');
		const files = target.querySelector('[data-conclusion-files]');
		expect(files.querySelectorAll('img').length).toBe(1);
		expect(files.textContent).toContain('compare.md');
		// The process record (every task's raw result) is folded away under the result, and each
		// result opens on demand; a whole-JSON result is shown as a JSON code block.
		const process = target.querySelector('[data-conclusion-tasks] details.process');
		expect(process.open).toBeFalsy();
		expect(target.querySelector('[data-conclusion-process]').textContent).toContain('过程记录');
		const details = target.querySelectorAll('[data-conclusion-tasks] li > details');
		expect(details.length).toBe(2);
		expect(details[1].textContent).toContain('anyclaude');
		details[0].open = true;
		details[0].dispatchEvent(new (globalThis as any).Event('toggle'));
		await until(() => (details[0].textContent ?? '').includes('"Focalboard"'));
		expect(details[0].textContent).toContain('"tools"');
	});

	it('接下来: ask about it in a chat, or keep it in the knowledge base (per version)', async () => {
		api.getTeamConclusion.mockResolvedValue(CONCLUSION);
		api.followUpTeamConclusion.mockResolvedValue({
			chat_id: 'chat-9',
			created: true,
			posted: true
		});
		api.saveTeamConclusionToKnowledge.mockResolvedValue({
			knowledge_id: 'kb-1',
			knowledge_name: '协作结论',
			file_id: 'f-1',
			replaced: false,
			duplicate: false,
			generated_at: 1790900000
		});
		nav.goto.mockReset();
		await mount(ConclusionView, {
			teamId: 'team-1',
			title: '看板调研',
			phase: 'completed',
			variant: 'page',
			chatId: null,
			outputs: { knowledge: { id: 'kb-1', generated_at: 1780000000 }, chat_posted: null }
		});
		await until(() => !!target.querySelector('[data-conclusion-next]'));
		const next = target.querySelector('[data-conclusion-next]');
		const ask = next.querySelector('[data-conclusion-ask]');
		expect(ask.textContent).toContain('在对话里追问');
		expect(ask.textContent).toContain('开一个新对话');
		// an older version is in the base: offer to replace it
		const save = next.querySelector('[data-conclusion-save]');
		expect(save.textContent).toContain('更新知识库里的结论');
		save.click();
		await until(() => !!target.querySelector('[data-conclusion-saved]'));
		expect(api.saveTeamConclusionToKnowledge).toHaveBeenCalledWith('tok', 'team-1');
		expect(target.querySelector('[data-conclusion-saved]').getAttribute('href')).toBe(
			'/workspace/knowledge/kb-1'
		);
		ask.click();
		await until(() => nav.goto.mock.calls.length > 0);
		expect(api.followUpTeamConclusion).toHaveBeenCalledWith('tok', 'team-1');
		expect(nav.goto).toHaveBeenCalledWith('/c/chat-9');
	});

	it('a team started from a chat goes back there; nothing to do while it is rewritten', async () => {
		api.getTeamConclusion.mockResolvedValue(CONCLUSION);
		await mount(ConclusionView, {
			teamId: 'team-1',
			title: '看板调研',
			phase: 'completed',
			variant: 'panel',
			chatId: 'chat-1',
			outputs: { knowledge: null, chat_posted: { generated_at: 1790900000 } }
		});
		await until(() => !!target.querySelector('[data-conclusion-next]'));
		const ask = target.querySelector('[data-conclusion-ask]');
		expect(ask.textContent).toContain('回到对话接着问');
		expect(ask.textContent).toContain('结论已经发回发起它的对话');
		expect(target.querySelector('[data-conclusion-save]').textContent).toContain('存入知识库');
		app.$destroy();
		target.remove();
		api.getTeamConclusion.mockResolvedValue({
			...CONCLUSION,
			status: 'generating',
			entry: { ...CONCLUSION.entry, status: 'generating' }
		});
		await mount(ConclusionView, { teamId: 'team-1', phase: 'completed', chatId: 'chat-1' });
		await until(() => !!target.querySelector('[data-team-report]'));
		expect(target.querySelector('[data-conclusion-next]')).toBeFalsy();
	});

	it('before the team finishes it says when the conclusion will come', async () => {
		api.getTeamConclusion.mockResolvedValue({
			status: 'none',
			entry: {},
			markdown: '',
			tasks: [],
			files: []
		});
		await mount(ConclusionView, {
			teamId: 'team-1',
			phase: 'running',
			progress: { done: 1, total: 3 }
		});
		await until(() => !!target.querySelector('[data-conclusion-empty]'));
		expect(target.textContent).toContain('结论还没开始写');
		expect(target.textContent).toContain('已完成 1/3 个任务');
		expect(target.querySelectorAll('[data-conclusion-empty] button').length).toBe(0);
	});

	it('a stopped team with results can ask the lead to write one', async () => {
		api.getTeamConclusion.mockResolvedValue({
			status: 'none',
			entry: {},
			markdown: '',
			files: [],
			tasks: [
				{
					id: 't_1',
					key: 'T1',
					title: 'x',
					member: 'm',
					executor: 'codex',
					status: 'done',
					result: 'ok',
					error: '',
					attempts: 1
				}
			]
		});
		api.writeTeamConclusion.mockResolvedValue({ status: 'generating' });
		await mount(ConclusionView, { teamId: 'team-1', phase: 'stopped' });
		await until(() => !!target.querySelector('[data-conclusion-empty] button'));
		expect(target.textContent).toContain('协作任务已停止');
		(target.querySelector('[data-conclusion-empty] button') as any).click();
		await sleep(20);
		expect(api.writeTeamConclusion).toHaveBeenCalledWith('tok', 'team-1');
	});

	it('the complete result marks the files placed in it; an old summary offers to become one', async () => {
		api.getTeamConclusion.mockResolvedValue({
			...CONCLUSION,
			entry: { ...CONCLUSION.entry, format: 2, included: ['compare.md'] }
		});
		await mount(ConclusionView, { teamId: 'team-1', phase: 'completed', variant: 'page' });
		await until(() => !!target.querySelector('[data-team-report] h1'));
		const included = target.querySelectorAll('[data-file-included]');
		expect(included.length).toBe(1);
		expect(included[0].closest('a').textContent).toContain('compare.md');
		expect(target.querySelectorAll('[data-conclusion-old-format]').length).toBe(0);
		app.$destroy();
		target.remove();
		// A conclusion written before (a report about the work): one click rewrites it as the result.
		api.getTeamConclusion.mockResolvedValue(CONCLUSION);
		api.writeTeamConclusion.mockResolvedValue({ status: 'generating' });
		await mount(ConclusionView, { teamId: 'team-1', phase: 'completed', variant: 'page' });
		await until(() => !!target.querySelector('[data-conclusion-old-format]'));
		target.querySelector('[data-conclusion-old-format] button').click();
		await until(() => api.writeTeamConclusion.mock.calls.length === 1);
		expect(api.writeTeamConclusion.mock.calls[0][1]).toBe('team-1');
	});

	it('为结果配图: pick one of your image templates, then watch it being drawn', async () => {
		api.getTeamConclusion.mockResolvedValue({
			...CONCLUSION,
			entry: { ...CONCLUSION.entry, format: 2 }
		});
		api.getTeamsMeta.mockResolvedValue({
			image_templates: [
				{ id: 'halo_daily_v2_knowledge_card', name: '知识卡片 · 小红书封面', aspect: '2:3' },
				{ id: 'halo_hand_v1_auto_style', name: '手绘万能图 · 自动选画风与画幅', aspect: '3:2' }
			]
		});
		api.illustrateTeamConclusion.mockResolvedValue({
			status: 'generating',
			template: '手绘万能图 · 自动选画风与画幅',
			step: 'condense',
			started_at: Math.floor(Date.now() / 1000)
		});
		await mount(ConclusionView, { teamId: 'team-1', phase: 'completed', variant: 'page' });
		await until(() => !!target.querySelector('[data-conclusion-illustrate]'));
		const card = () => target.querySelector('[data-conclusion-illustrate]');
		expect(card().getAttribute('data-conclusion-illustrate')).toBe('none');
		expect(card().textContent).toContain('为结果配图');
		card().querySelector('button').click();
		await until(() => !!target.querySelector('[data-illustrate-start]'));
		const select = target.querySelector('[data-illustrate-picker] select');
		expect(select.querySelectorAll('option').length).toBe(3); // Hermes' default + two of yours
		await sleep(20);
		target.querySelector('[data-illustrate-start]').click(); // the all-round template is preselected
		await until(() => api.illustrateTeamConclusion.mock.calls.length === 1);
		expect(api.illustrateTeamConclusion.mock.calls[0].slice(1)).toEqual([
			'team-1',
			'halo_hand_v1_auto_style'
		]);
		await until(() => card().getAttribute('data-conclusion-illustrate') === 'generating');
		expect(card().textContent).toContain('负责人在提炼图上的要点');
		expect(card().classList.contains('tm-live')).toBe(true);
	});

	it('shows generation in progress and an assembled fallback honestly', async () => {
		api.getTeamConclusion.mockResolvedValue({
			...CONCLUSION,
			status: 'generating',
			entry: { status: 'generating', model: 'gpt-chat' }
		});
		await mount(ConclusionView, { teamId: 'team-1', phase: 'completed' });
		await until(() => target.textContent.includes('整合成完整结果'));
		expect(target.textContent).toContain('负责人（gpt-chat）正在把 2 个任务的成果');
		app.$destroy();
		target.remove();
		api.getTeamConclusion.mockResolvedValue({
			...CONCLUSION,
			entry: {
				...CONCLUSION.entry,
				source: 'assembled',
				fallback_reason: '负责人模型都调用失败：gpt-chat 502'
			}
		});
		await mount(ConclusionView, { teamId: 'team-1', phase: 'completed' });
		await until(() => target.textContent.includes('没有给出结论'));
		expect(target.textContent).toContain('gpt-chat 502');
	});
});

describe('RunnerBadge and RunnerStatus', () => {
	it('badge shows a fallback as chosen → actual', async () => {
		const { default: RunnerBadge } = await import('./RunnerBadge.svelte');
		await mount(RunnerBadge, { chosen: 'cchclaude', actual: 'anyclaude', reason: '中转 502' });
		const badge = target.querySelector('[data-runner]');
		expect(badge.textContent.replace(/\s+/g, ' ')).toContain('cchclaude');
		expect(badge.getAttribute('data-runner')).toBe('anyclaude');
		expect(badge.getAttribute('title')).toContain('中转 502');
	});

	it('status panel lists the chain and explains a runner that is down', async () => {
		const { default: RunnerStatus } = await import('./RunnerStatus.svelte');
		const runner = (name: string, available: boolean, reason = '可用', layers: any[] = []) => ({
			name,
			label: name,
			engine: 'Claude Code',
			note: '',
			native: name === 'hermes',
			quota_wait: false,
			available,
			state: available ? 'ok' : 'unreachable',
			reason,
			checked_at: 1790900000,
			layers
		});
		const registry = {
			order: ['cchclaude', 'codex', 'hermes'],
			kinds: [],
			cache_seconds: 120,
			runners: [
				runner('cchclaude', false, 'cchclaude 连不上：HTTP 502', [
					{ layer: 'installed', ok: true, detail: '' },
					{ layer: 'reachable', ok: false, detail: 'HTTP 502' }
				]),
				runner('codex', true),
				runner('hermes', true)
			]
		};
		await mount(RunnerStatus, { registry });
		const chips = Array.from(target.querySelectorAll('[data-runner-chip]')) as any[];
		expect(chips.map((c) => c.getAttribute('data-runner-chip'))).toEqual([
			'cchclaude',
			'codex',
			'Hermes'.toLowerCase()
		]);
		expect(chips[0].getAttribute('data-available')).toBe('false');
		expect(target.textContent.replace(/\s+/g, ' ')).toContain('1 个暂不可用');
		chips[0].click();
		await sleep(10);
		expect(target.textContent).toContain('cchclaude 连不上：HTTP 502');
		expect(target.textContent).toContain('网络可达');
		const checks: any[] = [];
		app.$on('check', () => checks.push(1));
		(
			Array.from(target.querySelectorAll('button')).find((b: any) =>
				b.textContent.includes('重新检测')
			) as any
		).click();
		expect(checks.length).toBe(1);
	});
});

describe('PlanReview (runners)', () => {
	it('shows the template, the kind, and a fallback with its reason; "恢复自动" goes back to auto', async () => {
		const { default: PlanReview } = await import('./PlanReview.svelte');
		const team = {
			id: 'team-1',
			status: 'plan_ready',
			plan: {
				title: '小工具',
				lead_model: { model: 'gpt-chat', label: 'Hermes 默认模型' },
				members: [
					{
						name: 'backend-dev',
						role: '后端开发',
						kind: 'code',
						executor: 'cchclaude',
						executor_source: 'auto',
						recommended: 'cchclaude',
						runner: 'anyclaude',
						runner_note: 'cchclaude 连不上：HTTP 502',
						assistant: { id: '17', name: '开发工程师', emoji: '💻' }
					},
					{
						name: 'ui-dev',
						role: '前端',
						kind: 'ui',
						executor: 'codex',
						executor_source: 'user',
						recommended: 'agy',
						runner: 'codex',
						runner_note: '',
						assistant: null
					}
				],
				tasks: [
					{ key: 'T1', title: '接口', member: 'backend-dev', depends_on: [], description: '' },
					{ key: 'T2', title: '页面', member: 'ui-dev', depends_on: [], description: '' }
				],
				layers: [['T1', 'T2']],
				widest_layer: 2
			}
		};
		await mount(PlanReview, { team });
		expect(target.querySelector('[data-lead-model]').textContent).toContain('gpt-chat');
		const backend = target.querySelector('[data-plan-member="backend-dev"]');
		expect(backend.querySelector('[data-assistant="17"]').textContent).toContain('开发工程师');
		expect(backend.querySelector('[data-runner-fallback]').textContent).toContain('anyclaude');
		expect(backend.textContent).toContain('cchclaude 连不上');
		const ui = target.querySelector('[data-plan-member="ui-dev"]');
		expect(ui.textContent).toContain('自定义角色');
		expect(ui.textContent).toContain('你手动指定');
		const picked: any[] = [];
		app.$on('executor', (e: any) => picked.push(e.detail));
		(
			Array.from(ui.querySelectorAll('button')).find((b: any) =>
				b.textContent.includes('恢复自动')
			) as any
		).click();
		expect(picked).toEqual([{ name: 'ui-dev', executor: 'codex', source: 'auto' }]);
		expect(target.textContent).toContain('1 位成员已改用备选');
	});
});

// Mounts the 「Hermes 模型」 settings page: pick a main model, see the lanes and the
// unsaved summary follow, save the whole routing with the revision it was read at,
// and roll back from the history after a confirm.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';
import { toast } from 'svelte-sonner';
import type { HermesWorkConfigResponse, WorkWorkflowConfig } from '$lib/apis/hermes';

installDominoDom('http://localhost/');

const routing = () => ({
	main: 'deepseek-chat',
	fallback: ['gpt-chat', 'gemini-chat'],
	delegation: { model: 'deepseek-chat', fallback: ['gemini-chat'] },
	auxiliary: {
		compression: { model: 'gemini-chat', fallback: ['deepseek-chat'] },
		approval: { model: '?openrouter/x', fallback: [] },
		vision: { model: '', fallback: [] }
	},
	media: { model: 'gemini-chat', timeout: 300 }
});
const models = ['gpt-chat', 'deepseek-chat', 'gemini-chat', 'claude-chat'].map((id) => ({
	id,
	model: id,
	provider: `custom:${id}`,
	base_url: 'http://gw/v1',
	api_mode: id === 'gpt-chat' ? 'codex_responses' : 'chat_completions',
	vision: id === 'gpt-chat'
}));
const snapshot = (over: any = {}) => ({
	models,
	routing: routing(),
	revision: 'rev-1',
	reasoning_effort: 'medium',
	history: [
		{
			id: '20261123-140000-000001',
			at: 1763877600,
			source: 'halowebui',
			changes: [{ path: 'main', before: 'gpt-chat', after: 'deepseek-chat' }]
		}
	],
	...over
});

const agyPrefs = (over: any = {}) => ({
	card: { model: 'gemini-4-argon-high', default: 'gemini-4-argon-high', signed_in: true },
	teams: {
		ui_runner: 'offiagy',
		ui_runner_default: 'offiagy',
		ui_chain: ['offiagy', 'agy', 'hermes'],
		ui_choices: [
			{ name: 'offiagy', label: 'offiagy', note: '', chain: ['offiagy', 'agy', 'hermes'] },
			{ name: 'agy', label: 'agy', note: '', chain: ['agy', 'hermes'] },
			{ name: 'hermes', label: 'Hermes', note: '', chain: ['hermes'] }
		],
		offiagy_model: '',
		offiagy_models: [
			{ id: 'gemini-4-argon-high', name: 'Gemini 4 Argon (High)' },
			{ id: 'gemini-4-neon-high', name: 'Gemini 4 Neon (High)' }
		]
	},
	...over
});

const workProfileDefaults = (over: Partial<WorkWorkflowConfig> = {}) => ({
	plan_review: true,
	dual_plan: false,
	plan_approval: false,
	ui_review: false,
	split_dev: true,
	codex_review: false,
	steps: {
		plan: { runner: 'offiagy', fallback: ['agy'] },
		plan_review: { runner: 'officlaude', fallback: ['cchclaude', 'anyclaude', 'reclaude'] },
		dev: { runner: 'codex', fallback: [] },
		frontend: { runner: 'offiagy', fallback: ['agy'] },
		review: { runner: 'officlaude', fallback: ['cchclaude', 'anyclaude', 'reclaude'] }
	},
	...over
});

const workDefaults = (): WorkWorkflowConfig => ({
	...workProfileDefaults(),
	presets: {
		deep: workProfileDefaults({
			plan_review: true,
			dual_plan: true,
			plan_approval: true,
			ui_review: true,
			split_dev: true,
			codex_review: true
		}),
		fast: workProfileDefaults({
			plan_review: false,
			dual_plan: false,
			plan_approval: false,
			ui_review: false,
			split_dev: false,
			codex_review: false
		})
	}
});

const workResponse = (config = workDefaults()): HermesWorkConfigResponse => ({
	config,
	defaults: workDefaults(),
	runners: [
		{ name: 'offiagy', label: 'offiagy', engine: 'AGY', family: 'agy', note: '' },
		{ name: 'agy', label: 'agy', engine: 'AGY', family: 'agy', note: '' },
		{ name: 'officlaude', label: 'officlaude', engine: 'Claude', family: 'claude', note: '' },
		{ name: 'cchclaude', label: 'cchclaude', engine: 'Claude', family: 'claude', note: '' },
		{ name: 'anyclaude', label: 'anyclaude', engine: 'Claude', family: 'claude', note: '' },
		{ name: 'reclaude', label: 'reclaude', engine: 'Claude', family: 'claude', note: '' },
		{ name: 'codex', label: 'codex', engine: 'Codex', family: 'codex', note: '' },
		{ name: 'hermes', label: 'hermes', engine: 'Hermes', family: 'hermes', note: '' }
	],
	steps_meta: [
		{ key: 'plan', label: '规划 / 方案顾问', hint: '' },
		{ key: 'plan_review', label: '规划审阅 / 主控', hint: '', optional: true },
		{ key: 'dev', label: '后端 / 全栈开发', hint: '' },
		{ key: 'frontend', label: '前端开发', hint: '', optional: true },
		{ key: 'review', label: '审阅修复', hint: '' }
	],
	presets_meta: [
		{ key: 'default', preset: '', command: '/work', label: '默认工作流', hint: '默认档' },
		{ key: 'deep', preset: 'deep', command: '/work 深度', label: '深度多模型', hint: '深度档' },
		{ key: 'fast', preset: 'fast', command: '/work 快速', label: '快速精简', hint: '快速档' }
	]
});

const api = vi.hoisted(() => ({
	getHermesAgyPrefs: vi.fn(),
	saveHermesAgyPrefs: vi.fn(),
	getHermesRouting: vi.fn(),
	saveHermesRouting: vi.fn(),
	getHermesWorkConfig: vi.fn(),
	saveHermesWorkConfig: vi.fn(),
	rollbackHermesRouting: vi.fn(),
	probeHermesRoutingModel: vi.fn()
}));
vi.mock('$lib/apis/hermes', () => api);
vi.mock('$lib/apis/haloclaw', () => ({
	getHaloClawConfig: vi.fn(async () => ({ default_reasoning_effort: 'high' }))
}));
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(fn: () => T, what: string): Promise<NonNullable<T>> => {
	const started = Date.now();
	for (;;) {
		const v = fn();
		if (v) return v as NonNullable<T>;
		if (Date.now() - started > 8000) throw new Error(`timed out waiting for ${what}`);
		await sleep(15);
	}
};

let app: any;
let target: any;

const mount = async () => {
	(globalThis as any).localStorage.token = 'tok';
	const { default: Page } = await import('./HermesRouting.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Page({ target });
	await waitFor(() => target.querySelector('[data-lane="chat"]'), 'the lanes');
	return target;
};
const text = (el: any) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
const pill = (root: any, section: string, id: string) =>
	root.querySelector(`[data-section="${section}"] [role="radio"][data-model="${id}"]`);

const choose = (select: HTMLSelectElement, value: string) => {
	// Domino does not reflect selected options through HTMLSelectElement.value.
	select.value = value;
	select.dispatchEvent(new Event('change'));
};

const toggleWorkReview = (root: HTMLElement, checked: boolean) => {
	const input = root.querySelector<HTMLInputElement>('[data-work-toggle="plan_review"]')!;
	input.checked = checked;
	input.dispatchEvent(new Event('change'));
};

beforeEach(() => {
	api.getHermesRouting.mockResolvedValue(snapshot());
	api.getHermesAgyPrefs.mockResolvedValue(agyPrefs());
	api.getHermesWorkConfig.mockResolvedValue(workResponse());
	api.saveHermesWorkConfig.mockImplementation(async (_token, config) => workResponse(config));
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	vi.clearAllMocks();
});

describe('Hermes 模型 settings', () => {
	it('edits and saves all three /work presets independently, previews all three lanes, and restores or discards defaults', async () => {
		const root = await mount();
		const lane = () => text(root.querySelector('[data-lane="work"]'));
		const deepLane = () => text(root.querySelector('[data-lane="work-deep"]'));
		const fastLane = () => text(root.querySelector('[data-lane="work-fast"]'));
		const card = root.querySelector('[data-section="work"]');
		const dev = () => card.querySelector('[data-work-step="dev"]');
		const frontend = () => card.querySelector('[data-work-step="frontend"]');
		const resetAll = () =>
			Array.from<HTMLButtonElement>(card.querySelectorAll('button')).find((b) => text(b) === '恢复默认')!;
		const fallback = () =>
			Array.from<HTMLElement>(dev().querySelectorAll('[data-work-fallback]')).map((chip) =>
				chip.getAttribute('data-work-fallback')
			);

		// All 3 workflows are visible both in the top lanes and in the card overview.
		expect(card.querySelectorAll('[data-work-preset]')).toHaveLength(3);
		expect(card.querySelectorAll('[data-work-step]')).toHaveLength(5);
		expect(lane()).toContain('规划 · offiagy 规划审阅 · officlaude 后端开发 · codex 前端开发 · offiagy 审阅修复 · officlaude');
		expect(deepLane()).toContain('双方案合成·拍板');
		expect(deepLane()).toContain('Codex 2 轮审查');
		expect(fastLane()).toContain('规划 · offiagy 全栈开发 · codex 审阅修复 · officlaude');
		expect(resetAll().disabled).toBe(true);

		// Edit default preset: turn off plan_review, edit dev fallback + primary, switch frontend to officlaude (triggers self-review hint).
		toggleWorkReview(root, false);
		choose(dev().querySelector('[aria-label="添加后端开发兜底"]'), 'officlaude');
		await waitFor(() => fallback().length === 1 && !lane().includes('规划审阅'), 'workflow preview');
		choose(dev().querySelector('[aria-label="添加后端开发兜底"]'), 'agy');
		await waitFor(() => fallback().length === 2, 'second fallback');
		dev().querySelector('[aria-label="把 agy 往前挪"]').click();
		await waitFor(() => fallback()[0] === 'agy', 'move earlier');
		dev().querySelector('[aria-label="把 agy 往后挪"]').click();
		await waitFor(() => fallback()[0] === 'officlaude', 'move later');
		choose(dev().querySelector('[aria-label="后端开发首选执行器"]'), 'officlaude');
		await waitFor(() => fallback().length === 1, 'new primary removed from fallback');
		dev().querySelector('[aria-label="移除 agy"]').click();
		await waitFor(() => fallback().length === 0, 'empty fallback');
		choose(frontend().querySelector('[aria-label="前端开发首选执行器"]'), 'officlaude');
		await waitFor(() => Boolean(card.querySelector('[data-work-self-review-warn]')), 'self-review warning');
		expect(lane()).toContain('后端开发 · officlaude 前端开发 · officlaude');
		expect(text(root.querySelector('.hr-bar'))).toContain('默认 /work · 后端 / 全栈开发首选：codex → officlaude');

		// Switch to deep preset and edit its planner & codex_review independently.
		card.querySelector('[data-work-preset="deep"]').click();
		await waitFor(() => card.querySelector('[data-work-editor="deep"]'), 'deep editor');
		choose(card.querySelector('[data-work-step="plan"] [aria-label="规划 / 方案顾问首选执行器"]'), 'codex');
		const codexRev = card.querySelector('[data-work-toggle="codex_review"]') as HTMLInputElement;
		codexRev.checked = false;
		codexRev.dispatchEvent(new Event('change'));
		await waitFor(() => deepLane().includes('officlaude + codex') && !deepLane().includes('Codex 2 轮审查'), 'deep updated');

		// Switch to fast preset and change its dev runner without affecting default or deep.
		card.querySelector('[data-work-preset="fast"]').click();
		await waitFor(() => card.querySelector('[data-work-editor="fast"]'), 'fast editor');
		expect(text(frontend())).toContain('未启用');
		choose(card.querySelector('[data-work-step="dev"] [aria-label="全栈开发首选执行器"]'), 'offiagy');
		await waitFor(() => fastLane().includes('全栈开发 · offiagy'), 'fast updated');

		root.querySelector('.hr-save').click();
		await waitFor(() => root.querySelector('.hr-save').disabled, 'saved workflow');
		const expected = workDefaults();
		expected.plan_review = false;
		expected.steps.dev = { runner: 'officlaude', fallback: [] };
		expected.steps.frontend = { runner: 'officlaude', fallback: ['agy'] };
		expected.presets.deep.codex_review = false;
		expected.presets.deep.steps.plan = { runner: 'codex', fallback: ['agy'] };
		expected.presets.fast.steps.dev = { runner: 'offiagy', fallback: [] };
		expect(api.saveHermesWorkConfig).toHaveBeenCalledWith('tok', expected);
		expect(api.saveHermesRouting).not.toHaveBeenCalled();

		// Reset only fast preset via "恢复本档默认"
		card.querySelector('[data-work-reset-preset="fast"]').click();
		await waitFor(() => fastLane().includes('全栈开发 · codex'), 'reset fast preset');
		expect(deepLane()).toContain('officlaude + codex');

		// Reset all presets, discard, then reset all and save.
		resetAll().click();
		await waitFor(() => lane().includes('后端开发 · codex') && lane().includes('规划审阅'), 'reset draft');
		expect(api.saveHermesWorkConfig).toHaveBeenCalledTimes(1);
		const discard = Array.from<HTMLButtonElement>(root.querySelectorAll('.hr-bar button')).find((b) => text(b) === '放弃')!;
		discard.click();
		await waitFor(() => fastLane().includes('全栈开发 · offiagy'), 'discard reset');
		resetAll().click();
		await waitFor(() => !root.querySelector('.hr-save').disabled, 'save defaults enabled');
		root.querySelector('.hr-save').click();
		await waitFor(() => api.saveHermesWorkConfig.mock.calls.length === 2, 'save defaults');
		await waitFor(
			() => root.querySelector('.hr-save').disabled && text(root.querySelector('.hr-save')) === '保存并生效',
			'saved defaults'
		);
		expect(api.saveHermesWorkConfig).toHaveBeenLastCalledWith('tok', workDefaults());
	});

	it('keeps routing and AGY editable when /work is unavailable and retries separately', async () => {
		api.getHermesWorkConfig.mockRejectedValueOnce(new Error('请更新 Hermes'));
		const root = await mount();
		const card = root.querySelector('[data-section="work"]');
		await waitFor(() => text(card).includes('读取失败：请更新 Hermes'), 'work read error');
		expect(root.querySelector('[data-lane="work"]')).toBeFalsy();
		pill(root, 'main', 'gpt-chat').click();
		root.querySelector('[data-agy="ui"] [data-runner="agy"]').click();
		await waitFor(() => text(root.querySelector('.hr-bar')).includes('界面任务起点'), 'AGY changes');
		expect(text(root.querySelector('.hr-bar'))).toContain('gpt-chat');
		card.querySelector('button').click();
		await waitFor(() => root.querySelector('[data-lane="work"]'), 'retried work settings');
		expect(text(root.querySelector('.hr-bar'))).toContain('界面任务起点');
	});

	it('keeps the failed /work draft after the routing has saved', async () => {
		api.saveHermesWorkConfig.mockRejectedValueOnce(new Error('连接失败'));
		api.saveHermesRouting.mockResolvedValue(snapshot({
			routing: { ...routing(), main: 'gpt-chat', fallback: ['gemini-chat'] },
			changes: [{ path: 'main' }]
		}));
		const root = await mount();
		pill(root, 'main', 'gpt-chat').click();
		toggleWorkReview(root, false);
		await waitFor(() => text(root.querySelector('.hr-bar')).includes('规划后审阅'), 'work draft');
		root.querySelector('.hr-save').click();
		await waitFor(() => vi.mocked(toast.error).mock.calls.length, 'partial save notice');
		expect(toast.error).toHaveBeenCalledWith('Hermes 路由已保存，/work 工作流保存失败：连接失败');
		expect(text(root.querySelector('.hr-bar'))).toContain('1 处改动');
		expect(text(root.querySelector('[data-lane="work"]'))).not.toContain('规划审阅');
	});

	it('shows every lane at a glance', async () => {
		const root = await mount();
		expect(text(root.querySelector('[data-lane="chat"]'))).toContain(
			'对话 deepseek-chat gpt-chat gemini-chat'
		);
		expect(text(root.querySelector('[data-lane="media"]'))).toContain('gemini-chat 超时 300 秒');
		// an entry set from the command line shows as such and stays selected
		expect(text(root.querySelector('[data-task="approval"]'))).toContain('其他：openrouter/x');
		expect(pill(root, 'main', 'deepseek-chat').getAttribute('aria-checked')).toBe('true');
		expect(text(root.querySelector('[data-section="main"]'))).toContain('不能直接看图');
		await waitFor(
			() => text(root.querySelector('[data-section="main"]')).includes('：高'),
			'effort'
		);
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe(
			'对话 deepseek-chat gpt-chat gemini-chat 思考 高'
		);
		expect(root.querySelector('.hr-save').disabled).toBe(true);
	});

	it('saves the edited routing with the revision it was read at', async () => {
		const root = await mount();
		pill(root, 'main', 'gpt-chat').click();
		await sleep(20);
		// the new primary leaves its own fallback chain; the lane follows the draft
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe('对话 gpt-chat gemini-chat 思考 高');
		expect(text(root.querySelector('[data-section="main"]'))).not.toContain('不能直接看图');
		expect(text(root.querySelector('.hr-bar'))).toContain('2 处改动');

		// following the main model drops a task's own chain
		root.querySelector('[data-task="compression"] [role="radio"]').click();
		await sleep(20);
		expect(
			root.querySelector('[data-task="compression"] [aria-label="上下文压缩兜底"]')
		).toBeFalsy();

		const saved = snapshot({
			routing: { ...routing(), main: 'gpt-chat', fallback: ['gemini-chat'] },
			revision: 'rev-2',
			changes: [{ path: 'main', before: 'deepseek-chat', after: 'gpt-chat' }]
		});
		api.saveHermesRouting.mockResolvedValue(saved);
		root.querySelector('.hr-save').click();
		await waitFor(() => api.saveHermesRouting.mock.calls.length, 'save');
		const [, sent, revision] = api.saveHermesRouting.mock.calls[0];
		expect(revision).toBe('rev-1');
		expect(sent.main).toBe('gpt-chat');
		expect(sent.fallback).toEqual(['gemini-chat']);
		expect(sent.auxiliary.compression).toEqual({ model: '', fallback: [] });
		expect(sent.auxiliary.approval.model).toBe('?openrouter/x');
		await waitFor(
			() => text(root.querySelector('.hr-bar')).includes('没有未保存的改动'),
			'clean bar'
		);
	});

	it('edits a fallback chain and can discard', async () => {
		const root = await mount();
		const chain = root.querySelector('[data-section="main"] [aria-label="兜底链"]');
		chain.querySelector('[aria-label="移除 gpt-chat"]').click();
		await sleep(20);
		root.querySelector('[data-section="main"] [data-add="claude-chat"]').click();
		await sleep(20);
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe(
			'对话 deepseek-chat gemini-chat claude-chat 思考 高'
		);
		root.querySelector('[data-section="main"] [aria-label="把 claude-chat 往前挪"]').click();
		await sleep(20);
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe(
			'对话 deepseek-chat claude-chat gemini-chat 思考 高'
		);
		const discard = Array.from(root.querySelectorAll('.hr-bar button')).find(
			(b: any) => text(b) === '放弃'
		) as any;
		discard.click();
		await sleep(20);
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe(
			'对话 deepseek-chat gpt-chat gemini-chat 思考 高'
		);
	});

	it('rolls back only after a confirm', async () => {
		const root = await mount();
		const row = root.querySelector('[data-history="20261123-140000-000001"]');
		expect(text(row)).toContain('主模型：gpt-chat → deepseek-chat');
		row.querySelector('button').click();
		await sleep(20);
		expect(api.rollbackHermesRouting).not.toHaveBeenCalled();
		api.rollbackHermesRouting.mockResolvedValue(snapshot({ revision: 'rev-3', changes: [] }));
		root.querySelector('[data-history="20261123-140000-000001"] button').click();
		await waitFor(() => api.rollbackHermesRouting.mock.calls.length, 'rollback');
		expect(api.rollbackHermesRouting.mock.calls[0].slice(1)).toEqual([
			'20261123-140000-000001',
			'rev-1'
		]);
	});

	it('probes a model and shows the result', async () => {
		api.probeHermesRoutingModel.mockImplementation(async (_t: string, model: string) =>
			model === 'claude-chat'
				? { model, ok: false, latency_ms: 900, reply: '', error: 'HTTP 503' }
				: { model, ok: true, latency_ms: 1234, reply: 'OK', error: '' }
		);
		const root = await mount();
		const all = Array.from(root.querySelectorAll('button')).find(
			(b: any) => text(b) === '全部测试'
		) as any;
		all.click();
		await waitFor(
			() =>
				api.probeHermesRoutingModel.mock.calls.length === 4 &&
				root.querySelector('.hr-probe-error'),
			'probe'
		);
		await sleep(20);
		expect(text(root.querySelector('.hr-model[data-model="gpt-chat"] .hr-probe'))).toBe('1.2s');
		expect(text(root.querySelector('.hr-probe-error'))).toBe('claude-chat：HTTP 503');
	});

	it('edits the AGY preferences with the same save bar', async () => {
		const root = await mount();
		await waitFor(() => root.querySelector('[data-lane="ui"]'), 'agy lanes');
		expect(text(root.querySelector('[data-lane="card"]'))).toBe(
			'回答卡片 gemini-4-argon-high agy（网关 gemini-chat）'
		);
		expect(text(root.querySelector('[data-lane="ui"]'))).toBe(
			'界面任务 offiagy（Google 账号） agy（网关 gemini-chat） Hermes'
		);

		root.querySelector('[data-agy="ui"] [data-runner="agy"]').click();
		const select = root.querySelector('[aria-label="回答卡片的 offiagy 模型"]');
		for (const option of Array.from(select.querySelectorAll('option')) as any[]) {
			option.selected = option.value === '';
			if (option.selected) option.setAttribute('selected', '');
			else option.removeAttribute('selected');
		}
		select.dispatchEvent(new Event('change'));
		await sleep(20);
		expect(text(root.querySelector('[data-lane="ui"]'))).toBe(
			'界面任务 agy（网关 gemini-chat） Hermes'
		);
		expect(text(root.querySelector('[data-lane="card"]'))).toBe('回答卡片 agy（网关 gemini-chat）');
		expect(text(root.querySelector('.hr-bar'))).toContain('2 处改动');
		expect(text(root.querySelector('.hr-bar'))).toContain(
			'界面任务起点：offiagy（Google 账号） → agy（网关 gemini-chat）'
		);

		api.saveHermesAgyPrefs.mockResolvedValue(
			agyPrefs({
				card: { model: '', default: 'gemini-4-argon-high', signed_in: true },
				teams: { ...agyPrefs().teams, ui_runner: 'agy', ui_chain: ['agy', 'hermes'] }
			})
		);
		root.querySelector('.hr-save').click();
		await waitFor(() => api.saveHermesAgyPrefs.mock.calls.length, 'agy save');
		expect(api.saveHermesAgyPrefs.mock.calls[0][1]).toEqual({ card_model: '', ui_runner: 'agy' });
		expect(api.saveHermesRouting).not.toHaveBeenCalled();
		await waitFor(
			() => text(root.querySelector('.hr-bar')).includes('没有未保存的改动'),
			'clean bar'
		);
	});

	it('still edits the routing when the AGY part cannot be read', async () => {
		api.getHermesAgyPrefs.mockRejectedValue(new Error('连不上 Hermes'));
		const root = await mount();
		await waitFor(
			() => text(root.querySelector('[data-section="agy"]')).includes('读取失败'),
			'agy error'
		);
		expect(root.querySelector('[data-lane="ui"]')).toBeFalsy();
		pill(root, 'main', 'gpt-chat').click();
		await sleep(20);
		expect(text(root.querySelector('.hr-bar'))).toContain('2 处改动');
	});

	it('strips the new main model from delegation fallback when delegation follows main', async () => {
		api.getHermesRouting.mockResolvedValue(
			snapshot({
				routing: {
					...routing(),
					delegation: { model: '', fallback: ['gpt-chat', 'gemini-chat'] }
				}
			})
		);
		const root = await mount();
		pill(root, 'main', 'gpt-chat').click();
		await sleep(20);
		expect(text(root.querySelector('[data-lane="delegation"]'))).toBe('子代理 跟随主模型 gemini-chat');
	});

	it('refreshes offiagy models on demand while keeping unsaved AGY edits', async () => {
		const root = await mount();
		await waitFor(() => root.querySelector('[data-lane="ui"]'), 'agy lanes');
		// Make an unsaved edit first
		root.querySelector('[data-agy="ui"] [data-runner="agy"]').click();
		await sleep(20);
		api.getHermesAgyPrefs.mockResolvedValueOnce(
			agyPrefs({
				teams: {
					...agyPrefs().teams,
					offiagy_models: [
						{ id: 'gemini-4-argon-high', name: 'Gemini 4 Argon (High)' },
						{ id: 'gemini-4-neon-high', name: 'Gemini 4 Neon (High)' },
						{ id: 'gemini-5-new', name: 'Gemini 5 New' }
					],
					offiagy_models_at: 1763877600
				}
			})
		);
		const refreshBtn = Array.from(
			root.querySelectorAll('[data-section="agy"] button')
		).find((b: any) => text(b) === '刷新模型') as any;
		refreshBtn.click();
		await waitFor(
			() => api.getHermesAgyPrefs.mock.calls.some((c: any[]) => c[1]?.refresh === true),
			'refresh call'
		);
		await sleep(20);
		// New model appears in dropdown and unsaved ui_runner edit is preserved
		expect(text(root.querySelector('[aria-label="offiagy 模型"]'))).toContain('Gemini 5 New');
		expect(text(root.querySelector('[data-lane="ui"]'))).toBe(
			'界面任务 agy（网关 gemini-chat） Hermes'
		);
	});

	it('switches default model to a logged-in Codex OAuth model and edits reasoning effort', async () => {
		const oauthModels = [
			...models,
			{
				id: 'openai-codex:gpt-6.2-sol',
				model: 'gpt-6.2-sol',
				provider: 'openai-codex',
				provider_label: 'ChatGPT / Codex',
				auth_kind: 'oauth',
				base_url: 'https://chatgpt.com/backend-api/codex',
				api_mode: 'codex_responses',
				vision: true,
				media_capable: false
			}
		];
		api.getHermesRouting.mockResolvedValue(
			snapshot({
				models: oauthModels,
				auth_providers: [
					{ slug: 'openai-codex', label: 'ChatGPT / Codex', logged_in: true, model_count: 1 }
				],
				halo_reasoning_effort: 'high',
				routing: {
					...routing(),
					reasoning_effort: 'high',
					reasoning_overrides: { 'claude-chat': 'xhigh' }
				}
			})
		);

		const root = await mount();
		// Logged-in Codex section appears in 可用模型
		expect(text(root.querySelector('[data-oauth-models]'))).toContain('ChatGPT / Codex');
		expect(text(root.querySelector('[data-oauth-models]'))).toContain('已登录');
		// Media section excludes non-media-capable OAuth models
		expect(root.querySelector('[data-section="media"] [data-oauth-picker]')).toBeFalsy();

		// Switch default model via the inline logged-in Codex selector
		const oauthSelect = root.querySelector('[data-section="main"] [data-oauth-picker]') as any;
		for (const option of Array.from(oauthSelect.querySelectorAll('option')) as any[]) {
			option.selected = option.value === 'openai-codex:gpt-6.2-sol';
			if (option.selected) option.setAttribute('selected', '');
			else option.removeAttribute('selected');
		}
		oauthSelect.value = 'openai-codex:gpt-6.2-sol';
		oauthSelect.dispatchEvent(new Event('change'));
		await sleep(20);
		expect(text(root.querySelector('[data-lane="chat"]'))).toContain('Codex · gpt-6.2-sol');

		// Change thinking effort directly on the page
		const xhighBtn = root.querySelector('[data-effort-picker] [data-effort="xhigh"]') as any;
		xhighBtn.click();
		await sleep(20);
		expect(xhighBtn.getAttribute('aria-checked')).toBe('true');
		expect(text(root.querySelector('[data-lane="chat"]'))).toContain('思考 超高');
		expect(text(root.querySelector('.hr-bar'))).toContain('思考强度：高 → 超高');

		api.saveHermesRouting.mockResolvedValue(
			snapshot({
				models: oauthModels,
				halo_reasoning_effort: 'xhigh',
				routing: {
					...routing(),
					main: 'openai-codex:gpt-6.2-sol',
					reasoning_effort: 'xhigh',
					reasoning_overrides: { 'claude-chat': 'xhigh' }
				},
				revision: 'rev-2',
				changes: [
					{ path: 'main', before: 'deepseek-chat', after: 'openai-codex:gpt-6.2-sol' },
					{ path: 'reasoning_effort', before: 'high', after: 'xhigh' }
				]
			})
		);
		root.querySelector('.hr-save').click();
		await waitFor(() => api.saveHermesRouting.mock.calls.length, 'save codex + effort');
		const [, sent] = api.saveHermesRouting.mock.calls[0];
		expect(sent.main).toBe('openai-codex:gpt-6.2-sol');
		expect(sent.reasoning_effort).toBe('xhigh');
	});
});

// Mounts the 「Hermes 模型」 settings page: pick a main model, see the lanes and the
// unsaved summary follow, save the whole routing with the revision it was read at,
// and roll back from the history after a confirm.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

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

const api = vi.hoisted(() => ({
	getHermesAgyPrefs: vi.fn(),
	saveHermesAgyPrefs: vi.fn(),
	getHermesRouting: vi.fn(),
	saveHermesRouting: vi.fn(),
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

beforeEach(() => {
	api.getHermesRouting.mockResolvedValue(snapshot());
	api.getHermesAgyPrefs.mockResolvedValue(agyPrefs());
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	vi.clearAllMocks();
});

describe('Hermes 模型 settings', () => {
	it('shows every lane at a glance', async () => {
		const root = await mount();
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe(
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
		expect(root.querySelector('.hr-save').disabled).toBe(true);
	});

	it('saves the edited routing with the revision it was read at', async () => {
		const root = await mount();
		pill(root, 'main', 'gpt-chat').click();
		await sleep(20);
		// the new primary leaves its own fallback chain; the lane follows the draft
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe('对话 gpt-chat gemini-chat');
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
			'对话 deepseek-chat gemini-chat claude-chat'
		);
		root.querySelector('[data-section="main"] [aria-label="把 claude-chat 往前挪"]').click();
		await sleep(20);
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe(
			'对话 deepseek-chat claude-chat gemini-chat'
		);
		const discard = Array.from(root.querySelectorAll('.hr-bar button')).find(
			(b: any) => text(b) === '放弃'
		) as any;
		discard.click();
		await sleep(20);
		expect(text(root.querySelector('[data-lane="chat"]'))).toBe(
			'对话 deepseek-chat gpt-chat gemini-chat'
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
});

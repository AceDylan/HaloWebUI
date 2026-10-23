// Mounts the 辅助决策模型 card in a domino DOM: it shows the server-side setting (and when that
// model is gone), lists candidates with their connection so same-named models stay apart, and
// 「恢复默认」 clears the setting on the server.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/settings/interface?tab=chat');

vi.mock('$app/environment', () => ({
	browser: true,
	dev: false,
	building: false,
	version: 'test'
}));
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const candidates = [
	{ id: 'a.gpt-chat', name: 'gpt-chat', connection: 'A', kind: 'text' },
	{ id: 'b.gpt-chat', name: 'gpt-chat', connection: 'B', kind: 'text' },
	{ id: 'c.jev-latest', name: 'jev-latest', connection: 'C', kind: 'system_one' }
];
const api = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn() }));
vi.mock('$lib/apis/decision-model', () => ({
	getDecisionModel: api.get,
	setDecisionModel: api.set
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(
	probe: () => T | null | undefined | false,
	label: string,
	timeout = 5000
) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > timeout) throw new Error(`timed out waiting for ${label}`);
		await sleep(15);
	}
};

let target: any;
let app: any;

const mount = async () => {
	(globalThis as any).localStorage = { token: 'tok' };
	const { default: Card } = await import('./DecisionModelSetting.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Card({ target });
	await waitFor(() => api.get.mock.calls.length > 0, 'load');
	await sleep(30);
};

afterEach(() => {
	app?.$destroy();
	target?.remove();
	api.get.mockReset();
	api.set.mockReset();
});

describe('辅助决策模型 setting', () => {
	it('defaults to the existing logic and has nothing to reset', async () => {
		api.get.mockResolvedValue({ model: null, name: null, kind: null, available: null, candidates });
		await mount();
		expect(target.textContent).toContain('辅助决策模型');
		expect(target.textContent).toContain('沿用现有逻辑（默认）');
		expect(target.querySelector('[data-decision-model-reset]')).toBeFalsy();
		expect(target.querySelector('[data-decision-model-unavailable]')).toBeFalsy();
	});

	it('shows a stored model that is gone and resets it on the server', async () => {
		api.get.mockResolvedValue({
			model: 'b.gpt-chat',
			name: null,
			kind: null,
			available: false,
			candidates: []
		});
		api.set.mockResolvedValue({ model: null, name: null, kind: null, available: null, candidates });
		await mount();
		expect(target.querySelector('[data-decision-model-unavailable]')).toBeTruthy();
		target.querySelector('[data-decision-model-reset]').click();
		await waitFor(() => api.set.mock.calls.length > 0, 'save');
		expect(api.set).toHaveBeenCalledWith('tok', null);
		await waitFor(() => !target.querySelector('[data-decision-model-reset]'), 'reset button gone');
		expect(target.querySelector('[data-decision-model-unavailable]')).toBeFalsy();
	});

	it('keeps the setting when the server refuses', async () => {
		api.get.mockResolvedValue({
			model: 'c.jev-latest',
			name: 'jev-latest',
			kind: 'system_one',
			available: true,
			candidates
		});
		api.set.mockRejectedValue(new Error('no'));
		await mount();
		expect(target.textContent).toContain('jev-latest · C（判断模型）');
		target.querySelector('[data-decision-model-reset]').click();
		await waitFor(() => api.set.mock.calls.length > 0, 'save');
		await sleep(30);
		expect(target.querySelector('[data-decision-model-reset]')).toBeTruthy();
	});
});

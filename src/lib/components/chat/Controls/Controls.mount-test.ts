// 对话高级设置 on a hermes-agent chat. Hermes only receives the system prompt
// (as the run's instructions); its reasoning-sync plugin sets the thinking
// level and sampling params are never sent, so those dials are replaced by a
// note saying where each thing is actually decided.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('$lib/apis', () => ({ getBackendConfig: vi.fn() }));
vi.mock('$lib/apis/configs', () => ({
	getNativeToolsConfig: vi.fn(),
	setNativeToolsConfig: vi.fn()
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let app: any;
let target: any;

const mount = async (models: any[]) => {
	const { writable } = await import('svelte/store');
	const stores = await import('$lib/stores');
	stores.user.set({ id: 'u1', role: 'admin' } as any);
	stores.settings.set({} as any);
	stores.config.set({ hermes_agent_model_ids: ['hermes-agent'] } as any);
	const i18n = writable({ t: (key: string, options?: any) => options?.defaultValue ?? key });
	const { default: Controls } = await import('./Controls.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Controls({
		target,
		props: { models, modelId: models[0]?.id ?? null, params: {} },
		context: new Map<string, any>([['i18n', i18n]])
	});
	await sleep(10);
};

const text = () => String(target.textContent || '');

// Compiling Controls and AdvancedParams takes longer than one test's budget.
beforeAll(async () => {
	await import('./Controls.svelte');
}, 120_000);

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

describe('Controls', () => {
	it('shows a note instead of the thinking and sampling dials for hermes', async () => {
		await mount([{ id: 'hermes-agent', name: 'Hermes', owned_by: 'openai' }]);

		expect(target.querySelectorAll('[data-halo-hermes-controls-note]').length).toBe(1);
		expect(text()).toContain('消息网关');
		expect(text()).not.toContain('Advanced Params');
		expect(text()).not.toContain('Budget Mode');
		// The system prompt still reaches hermes, so it stays editable.
		expect(text()).toContain('Current Chat System Prompt');
	});

	it('keeps every dial for an ordinary model', async () => {
		await mount([{ id: 'gpt-4o', name: 'GPT-4o', owned_by: 'openai' }]);

		expect(target.querySelectorAll('[data-halo-hermes-controls-note]').length).toBe(0);
		expect(text()).toContain('Advanced Params');
		expect(text()).toContain('Budget Mode');
	});

	it('keeps the dials when hermes is compared with another model', async () => {
		await mount([
			{ id: 'hermes-agent', name: 'Hermes', owned_by: 'openai' },
			{ id: 'gpt-4o', name: 'GPT-4o', owned_by: 'openai' }
		]);

		expect(target.querySelectorAll('[data-halo-hermes-controls-note]').length).toBe(0);
		expect(text()).toContain('Advanced Params');
	});
});

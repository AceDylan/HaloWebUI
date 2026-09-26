// Mounts the composer's Hermes options against the model list the backend
// condenses from hermes' config. Regression guard for the picker offering the
// default model twice, and for a 思考强度 row of its own: the thinking level is
// the chat's (对话控制), handed to hermes by the backend.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('$lib/apis/hermes', () => ({ getHermesModelOptions: vi.fn() }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(probe: () => T | null | undefined | false, label: string) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > 8000) throw new Error(`timed out waiting for ${label}`);
		await sleep(15);
	}
};

let app: any;
let target: any;
let api: any;

const mount = async (options: Record<string, string> = {}) => {
	const { writable } = await import('svelte/store');
	const i18n = writable({ t: (key: string) => key });
	const { default: HermesRunOptions } = await import('./HermesRunOptions.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new HermesRunOptions({
		target,
		props: { options: { dispatch: '', model: '', provider: '', ...options } },
		context: new Map<string, any>([['i18n', i18n]])
	});
	(target.querySelector('button') as any).click();
	return waitFor(
		() =>
			document.body.querySelectorAll('[data-halo-hermes-model] option').length > 1 &&
			(document.body.querySelector('[data-halo-hermes-options-panel]') as any),
		'the hermes model list'
	);
};

const optionTexts = () =>
	Array.from(document.body.querySelectorAll('[data-halo-hermes-model] option')).map((el: any) =>
		el.textContent.trim()
	);

beforeEach(() => {
	(globalThis as any).localStorage.token = 'tok';
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	document.body.querySelector('[data-halo-hermes-options-panel]')?.remove();
	app = null;
	vi.clearAllMocks();
});

describe('HermesRunOptions', () => {
	beforeEach(async () => {
		api = await import('$lib/apis/hermes');
		api.getHermesModelOptions.mockResolvedValue({
			model: 'gpt-chat',
			provider: 'custom:relay',
			providers: [
				{ slug: 'custom:relay', name: 'relay', current: true, models: ['gpt-chat'] },
				{ slug: 'custom:claude-chat', name: 'claude-chat', current: false, models: ['claude-chat'] },
				{
					slug: 'custom:deepseek-chat',
					name: 'deepseek-chat',
					current: false,
					models: ['deepseek-chat']
				}
			]
		});
	});

	it('offers the default once and then the other configured models, flat', async () => {
		const panel: any = await mount();
		expect(optionTexts()).toEqual(['默认（gpt-chat）', 'claude-chat', 'deepseek-chat']);
		expect(panel.querySelectorAll('optgroup')).toHaveLength(0);
	});

	it('has no thinking level of its own', async () => {
		const panel: any = await mount();
		expect(Boolean(panel.querySelector('[data-halo-hermes-effort]'))).toBe(false);
		expect(panel.textContent).not.toContain('极高');
		expect(panel.textContent).toContain('思考强度沿用对话设置');
	});

	it('keeps showing a model picked earlier that the list no longer offers', async () => {
		await mount({ model: '[free]claude-opus-5', provider: 'custom:relay' });
		expect(optionTexts()).toEqual([
			'默认（gpt-chat）',
			'[free]claude-opus-5',
			'claude-chat',
			'deepseek-chat'
		]);
	});
});

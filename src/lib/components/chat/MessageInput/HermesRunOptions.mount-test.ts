// Mounts the composer's Hermes options against the model list the backend
// condenses from hermes' config. Regression guard for the picker offering the
// default model twice, and for a 思考强度 row of its own: the thinking level is
// HaloWebUI's (admin default via hermes' reasoning-sync plugin, plus the chat's).
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

const mount = async (
	options: Record<string, string> = {},
	continuation: any = null,
	buttonRect: { top: number; left: number; bottom: number } | null = null
) => {
	const { writable } = await import('svelte/store');
	const i18n = writable({ t: (key: string) => key });
	const { default: HermesRunOptions } = await import('./HermesRunOptions.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new HermesRunOptions({
		target,
		props: { options: { dispatch: '', model: '', provider: '', ...options }, continuation },
		context: new Map<string, any>([['i18n', i18n]])
	});
	const button = target.querySelector('button') as any;
	if (buttonRect) {
		button.getBoundingClientRect = () => ({
			...buttonRect,
			right: buttonRect.left + 90,
			width: 90,
			height: buttonRect.bottom - buttonRect.top
		});
	}
	button.click();
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
				{
					slug: 'custom:claude-chat',
					name: 'claude-chat',
					current: false,
					models: ['claude-chat']
				},
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
		expect(panel.textContent).toContain('思考强度跟随 HaloWebUI 设置');
	});

	it('says which thinking level every hermes request gets, and where an admin changes it', async () => {
		const { user } = await import('$lib/stores');
		api.getHermesModelOptions.mockResolvedValue({
			model: 'gpt-chat',
			provider: 'custom:relay',
			providers: [
				{ slug: 'custom:relay', name: 'relay', current: true, models: ['gpt-chat'] },
				{
					slug: 'custom:deepseek-chat',
					name: 'deepseek',
					current: false,
					models: ['deepseek-chat']
				}
			],
			reasoning_effort: 'high'
		});
		user.set({ role: 'admin' } as any);
		let panel: any = await mount();
		let note = panel.querySelector('[data-halo-hermes-effort-note]');
		expect(note.textContent).toContain('思考强度高');
		expect(note.textContent).toContain('调低回复更快 · 去修改');
		expect(note.querySelector('a')?.getAttribute('href')).toBe('/settings/haloclaw');
		app.$destroy();
		target.remove();

		user.set({ role: 'user' } as any);
		panel = await mount();
		note = panel.querySelector('[data-halo-hermes-effort-note]');
		expect(note.textContent).toContain('思考强度高');
		expect(note.querySelectorAll('a').length).toBe(0);
		user.set(undefined as any);
	});

	it('says a dispatch covers the next message only, readable without hovering', async () => {
		const panel: any = await mount({ dispatch: 'codex' });
		const hint = panel.querySelector('[data-halo-hermes-dispatch-hint]');
		expect(hint.textContent).toContain('交给 Codex 在后台独占执行');
		expect(hint.textContent).toContain('只对下一条消息生效');
		expect(panel.textContent).toContain(
			'派发给 reclaude/cchclaude/anyclaude/officlaude/codex/agy 时它们用自己的模型'
		);
	});

	it('offers cchclaude next to reclaude, three choices to a row', async () => {
		const panel: any = await mount({ dispatch: 'cchclaude' });
		const choices = Array.from(panel.querySelectorAll('[data-halo-hermes-dispatch]')).map(
			(el: any) => el.getAttribute('data-halo-hermes-dispatch')
		);
		expect(choices).toEqual([
			'direct',
			'reclaude',
			'cchclaude',
			'anyclaude',
			'officlaude',
			'codex',
			'agy',
			'answer',
			'discuss',
			'team'
		]);
		const cch = panel.querySelector('[data-halo-hermes-dispatch="cchclaude"]') as any;
		expect(cch.getAttribute('aria-checked')).toBe('true');
		expect(panel.querySelector('[data-halo-hermes-dispatch-hint]').textContent).toContain(
			'交给 Claude Code（自己的 cch 中转）在后台独占执行'
		);
		expect(panel.querySelector('[role="radiogroup"]').className).toContain('grid-cols-3');
		expect(
			(target.querySelector('[data-halo-hermes-options-summary]') as any)?.textContent
		).toContain('cchclaude');
	});

	it('offers 精答, 讨论 and 协作台 on a row of their own: asked another way, the result comes back', async () => {
		const panel: any = await mount({ dispatch: 'team' });
		const choice = (name: string) =>
			panel.querySelector(`[data-halo-hermes-dispatch="${name}"]`) as any;
		const hint = () => panel.querySelector('[data-halo-hermes-dispatch-hint]').textContent;
		const summary = () =>
			(target.querySelector('[data-halo-hermes-options-summary]') as any)?.textContent ?? '';
		expect(panel.querySelector('[data-halo-hermes-modes-label]').textContent).toContain(
			'换一种方式问'
		);
		expect(choice('team').getAttribute('aria-checked')).toBe('true');
		expect(choice('team').className).not.toContain('col-span-3');
		expect(choice('team').textContent).toContain('协作台');
		expect(hint()).toContain('完整结果发回这里');
		// the model picked for Hermes does not take part in this message
		expect(panel.querySelector('[data-halo-hermes-model-note]').textContent).toContain(
			'这条消息交给协作台，不经过 Hermes'
		);

		choice('answer').click();
		await waitFor(() => choice('answer').getAttribute('aria-checked') === 'true', '精答 picked');
		expect(choice('team').getAttribute('aria-checked')).toBe('false');
		expect(choice('answer').textContent).toContain('精答');
		expect(hint()).toContain('调度器从助手库挑最合适的助手');
		expect(hint()).toContain('答完发回这里');
		expect(hint()).toContain('消息自己以 /命令 开头时以消息为准');
		expect(summary()).toContain('精答');

		choice('discuss').click();
		await waitFor(() => choice('discuss').getAttribute('aria-checked') === 'true', '讨论 picked');
		expect(hint()).toContain('几个模型按你上次的设置讨论');
		expect(summary()).toContain('讨论');

		choice('direct').click();
		await waitFor(() => choice('direct').getAttribute('aria-checked') === 'true', 'back to 直接');
		expect(panel.querySelector('[data-halo-hermes-model-note]').textContent).toContain(
			'派发给 reclaude/cchclaude/anyclaude/officlaude/codex/agy 时它们用自己的模型'
		);
	});

	it('selects official Claude with its own runner id', async () => {
		const panel: any = await mount();
		const official = panel.querySelector('[data-halo-hermes-dispatch="officlaude"]') as any;
		expect(official.textContent).toContain('官方 Claude');
		official.click();
		await sleep(5);
		expect(official.getAttribute('aria-checked')).toBe('true');
		expect(target.querySelector('[data-halo-hermes-options-summary]').textContent).toContain(
			'官方 Claude'
		);
		expect(panel.querySelector('[data-halo-hermes-dispatch-hint]').textContent).toContain(
			'claude.ai'
		);
	});

	it('offers anyclaude and says it is the slow free one', async () => {
		const panel: any = await mount({ dispatch: 'anyclaude' });
		const any = panel.querySelector('[data-halo-hermes-dispatch="anyclaude"]') as any;
		expect(any.getAttribute('aria-checked')).toBe('true');
		expect(panel.querySelector('[data-halo-hermes-dispatch-hint]').textContent).toContain(
			'交给 Claude Code（anyrouter 免费服务，较慢，失败会自动重试）在后台独占执行'
		);
		expect(
			(target.querySelector('[data-halo-hermes-options-summary]') as any)?.textContent
		).toContain('anyclaude');
	});

	it('continues the official account using its Chinese display name', async () => {
		const panel: any = await mount(
			{},
			{ runner: 'officlaude', runId: '20261008-010000-abcdef12', status: 'error' }
		);
		expect(panel.querySelector('[data-halo-hermes-dispatch="continue"]').textContent).toContain(
			'官方 Claude'
		);
		expect(panel.querySelector('[data-halo-hermes-dispatch-hint]').textContent).toContain(
			'交回 官方 Claude'
		);
	});

	it('after a runner report, offers going back to that run first, and "直接" for hermes', async () => {
		const run = { runner: 'reclaude', runId: '20260927-005655-f2dd355f', status: 'success' };
		const panel: any = await mount({}, run);
		const choice = (name: string) =>
			panel.querySelector(`[data-halo-hermes-dispatch="${name}"]`) as any;
		const summary = () =>
			(target.querySelector('[data-halo-hermes-options-summary]') as any)?.textContent ?? '';
		const hint = () => panel.querySelector('[data-halo-hermes-dispatch-hint]').textContent;
		expect(choice('continue').getAttribute('aria-checked')).toBe('true');
		expect(choice('direct').getAttribute('aria-checked')).toBe('false');
		expect(summary()).toContain('接着 reclaude');
		expect(hint()).toContain('交回 reclaude 运行 20260927-005655-f2dd355f 的原会话继续');
		choice('direct').click();
		await waitFor(() => choice('direct').getAttribute('aria-checked') === 'true', 'direct picked');
		expect(choice('continue').getAttribute('aria-checked')).toBe('false');
		expect(summary()).toContain('直接');
		expect(hint()).toContain('Hermes 自己回答');
		choice('continue').click();
		await waitFor(
			() => choice('continue').getAttribute('aria-checked') === 'true',
			'back to the run'
		);
	});

	it('without a report to go back to, "直接" is the default and nothing is added', async () => {
		const panel: any = await mount();
		expect(Boolean(panel.querySelector('[data-halo-hermes-dispatch="continue"]'))).toBe(false);
		expect(
			(panel.querySelector('[data-halo-hermes-dispatch="direct"]') as any).getAttribute(
				'aria-checked'
			)
		).toBe('true');
		expect(Boolean(target.querySelector('[data-halo-hermes-options-summary]'))).toBe(false);
	});

	describe('placement', () => {
		const win = window as any;
		const saved = { innerWidth: win.innerWidth, innerHeight: win.innerHeight };
		// The panel's full height (domino has no layout).
		const proto = Object.getPrototypeOf(document.createElement('div'));
		beforeEach(() => {
			Object.defineProperty(proto, 'scrollHeight', {
				configurable: true,
				get() {
					return this.hasAttribute('data-halo-hermes-options-panel') ? 520 : 0;
				}
			});
		});
		afterEach(() => {
			delete proto.scrollHeight;
			delete win.visualViewport;
			Object.assign(win, saved);
		});
		const styleOf = (panel: any) => panel.getAttribute('style') as string;

		it('on a phone with the keyboard up, opens above the button no taller than the room there', async () => {
			Object.assign(win, { innerWidth: 390, innerHeight: 800 });
			win.visualViewport = {
				offsetTop: 0,
				offsetLeft: 0,
				width: 390,
				height: 360,
				addEventListener: () => {},
				removeEventListener: () => {}
			};
			const style = styleOf(await mount({}, null, { top: 300, left: 60, bottom: 332 }));
			expect(style).toContain('top: 292px; transform: translateY(-100%);');
			expect(style).toContain('max-height: 284px;');
			expect(style).toContain('width: 374px;');
			expect(style).toContain('left: 8px;');
		});

		it('opens below a composer in the middle of a phone screen (a new chat)', async () => {
			Object.assign(win, { innerWidth: 390, innerHeight: 800 });
			const style = styleOf(await mount({}, null, { top: 260, left: 60, bottom: 292 }));
			expect(style).toContain('top: 300px;');
			expect(style).not.toContain('translateY');
			expect(style).toContain('max-height: 492px;');
		});

		it('on a wide screen with room above, opens above at its own width', async () => {
			Object.assign(win, { innerWidth: 1280, innerHeight: 800 });
			const style = styleOf(await mount({}, null, { top: 700, left: 400, bottom: 732 }));
			expect(style).toContain('top: 692px; transform: translateY(-100%);');
			expect(style).toContain('max-height: 684px;');
			expect(style).toContain('width: 288px;');
			expect(style).toContain('left: 400px;');
		});
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

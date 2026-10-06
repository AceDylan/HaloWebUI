// Workspace 「我的助手」: 「全部在模型菜单中显示」 finds hidden assistants (it read
// model.info.meta.hidden, which list rows do not have, so it never showed anything), hidden ones
// carry a badge, the source filter and archived rows, and favourites sort first.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/workspace/models');

const api = vi.hoisted(() => ({
	getModels: vi.fn(),
	updateModelById: vi.fn(),
	createNewModel: vi.fn(),
	deleteModelById: vi.fn(),
	toggleModelById: vi.fn()
}));
vi.mock('$lib/apis/models', () => api);
vi.mock('$lib/services/models', () => ({ refreshModels: vi.fn(async () => undefined) }));
vi.mock('$lib/apis/groups', () => ({ getGroups: vi.fn(async () => []) }));
const library = vi.hoisted(() => ({ archiveAssistant: vi.fn() }));
vi.mock('$lib/apis/assistant-library', async (original) => ({
	...((await original()) as object),
	archiveAssistant: library.archiveAssistant
}));
const settingsSave = vi.hoisted(() => ({ saveUserSettingsPatch: vi.fn(async () => ({})) }));
vi.mock('$lib/utils/user-settings', () => settingsSave);
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/components/common/HaloSelect.svelte', async () => ({
	default: (await import('./test-stubs/SelectStub.svelte')).default
}));
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: toasts }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 10000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(20);
	}
};

const row = (id: string, meta: Record<string, any> = {}, extra: Record<string, any> = {}) => ({
	id,
	name: id.toUpperCase(),
	base_model_id: 'gpt',
	user_id: 'u1',
	params: { system: `you are ${id}` },
	meta: { description: `${id} desc`, ...meta },
	access_control: null,
	is_active: true,
	...extra
});

let Models: any;
let app: any;
let stores: any;

beforeAll(async () => {
	stores = await import('$lib/stores');
	Models = (await import('./Models.svelte')).default;
}, 60000);

beforeEach(() => {
	Object.values(api).forEach((fn: any) => fn.mockReset());
	Object.values(toasts).forEach((fn: any) => fn.mockReset());
	library.archiveAssistant.mockReset();
	settingsSave.saveUserSettingsPatch.mockClear();
	localStorage.token = 't';
	stores.user.set({ id: 'u1', role: 'admin', email: 'a@b.c', name: 'A', permissions: {} } as any);
	stores.settings.set({} as any);
	api.updateModelById.mockImplementation(async (_t: string, id: string, info: any) => ({ id, ...info }));
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const mount = async () => {
	const { writable } = await import('svelte/store');
	const target = document.createElement('div');
	document.body.appendChild(target);
	app = new Models({
		target,
		context: new Map([
			[
				'i18n',
				writable({
					// interpolates like i18next does for a missing key
					t: (s: string, o: Record<string, any> = {}) => s.replace(/{{(\w+)}}/g, (_, k) => `${o[k] ?? ''}`),
					language: 'zh-CN',
					resolvedLanguage: 'zh-CN'
				})
			]
		])
	});
	await until(() => !!target.querySelector('#model-list') || !!target.querySelector('.workspace-empty-state'));
	return target;
};

const listedIds = (target: HTMLElement) =>
	Array.from(target.querySelectorAll('[id^="model-item-"]')).map((el: any) => el.id.replace('model-item-', ''));

const click = (el: any) => el.click();

// The stub is a native <select>; Svelte reads the picked option back on change.
const choose = (select: any, value: string) => {
	for (const option of Array.from(select.querySelectorAll('option')) as any[]) {
		option.selected = option.value === value;
	}
	select.dispatchEvent(new (globalThis as any).Event('change'));
};

describe('Show all in the model menus', () => {
	it('shows the hidden assistants (meta at the top level of a list row) and badges them', async () => {
		api.getModels.mockResolvedValue([row('a', { hidden: true }), row('b'), row('c', { hidden: true })]);
		const target = await mount();

		expect(target.querySelectorAll('[data-hidden-badge]').length).toBe(2);

		click(target.querySelector('[data-show-all]'));
		await until(() => api.updateModelById.mock.calls.length === 2);
		await sleep(30);

		const updated = api.updateModelById.mock.calls.map((call: any[]) => [call[1], call[2].meta.hidden]);
		expect(updated).toEqual([
			['a', false],
			['c', false]
		]);
		expect(toasts.success).toHaveBeenCalledWith('已在模型菜单中显示 2 个助手');
	});

	it('hides the shown ones and leaves the hidden ones alone', async () => {
		api.getModels.mockResolvedValue([row('a', { hidden: true }), row('b')]);
		const target = await mount();

		click(target.querySelector('[data-hide-all]'));
		await until(() => api.updateModelById.mock.calls.length === 1);
		expect(api.updateModelById.mock.calls[0][1]).toBe('b');
		expect(api.updateModelById.mock.calls[0][2].meta.hidden).toBe(true);
	});
});

describe('source filter, archived rows and favourites', () => {
	const rows = () => [
		row('manual1'),
		row('answer1', { assistant: { source: 'answer', version: 3 } }),
		row('legacy1', { answer_desk: { revisions: [{}, {}] } }),
		row('team1', { assistant: { source: 'team' } }),
		row('tpl1', { assistant: { source: 'builtin:15' } }),
		row('old1', { assistant: { source: 'answer', archived: true } }, { is_active: false })
	];

	it('filters by source, counting an old 精答 record as 精答, and keeps archived rows out', async () => {
		api.getModels.mockResolvedValue(rows());
		const target = await mount();

		expect(listedIds(target)).toEqual(['manual1', 'answer1', 'legacy1', 'team1', 'tpl1']);
		const version = target.querySelector('#model-item-answer1 [data-assistant-badges]')?.textContent ?? '';
		expect(version).toContain('精答');
		expect(version).toContain('v3');
		expect(target.querySelector('#model-item-legacy1 [data-assistant-badges]')?.textContent).toContain('v3');

		const sourceSelect: any = Array.from(target.querySelectorAll('select[data-select-stub]')).find((el: any) =>
			el.getAttribute('data-select-stub').includes('builtin')
		);
		choose(sourceSelect, 'answer');
		await until(() => listedIds(target).length === 2);
		expect(listedIds(target)).toEqual(['answer1', 'legacy1']);

		click(target.querySelector('[data-show-archived]'));
		await until(() => listedIds(target).length === 3);
		expect(listedIds(target)).toEqual(['answer1', 'legacy1', 'old1']);
		expect(target.querySelector('#model-item-old1 [data-archived-badge]')).toBeTruthy();

		choose(sourceSelect, 'builtin');
		await until(() => listedIds(target).length === 1);
		expect(listedIds(target)).toEqual(['tpl1']);
	});

	it('sorts favourites first and stars into the server favourites', async () => {
		stores.settings.set({ assistantFavorites: ['model:team1', 'builtin:1'] } as any);
		api.getModels.mockResolvedValue(rows());
		const target = await mount();

		expect(listedIds(target)[0]).toBe('team1');

		click(target.querySelector('[data-favorite="tpl1"]'));
		await until(() => settingsSave.saveUserSettingsPatch.mock.calls.length === 1);
		expect(settingsSave.saveUserSettingsPatch.mock.calls[0][1]).toEqual({
			assistantFavorites: ['model:team1', 'builtin:1', 'model:tpl1']
		});
		await until(() => listedIds(target)[1] === 'tpl1');
	});
});

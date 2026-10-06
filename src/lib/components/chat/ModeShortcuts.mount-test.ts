// The chat's modes as one family: the home composer's shortcuts take the draft along, the
// sidebar shows 讨论 / 协作 / 生图 as one row (and the studio only with image permission), and
// the chat list marks discussions, team chats and image chats.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const nav = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return { page: writable({ url: new URL('http://localhost/teams') }), navigating: writable(null), updated: { subscribe: writable(false).subscribe } };
});
vi.mock('$lib/apis/discussions', () => ({ listDiscussions: vi.fn(async () => []) }));
vi.mock('$lib/apis/teams', () => ({ listTeams: vi.fn(async () => ({ teams: [] })) }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let stores: any;
const apps: any[] = [];

beforeAll(async () => {
	stores = await import('$lib/stores');
}, 60000);

beforeEach(() => {
	nav.goto.mockReset();
	sessionStorage.removeItem('halo.handoff');
	stores.config.set({ features: { enable_agent_teams: true, enable_image_generation: true } } as any);
	stores.user.set({ id: 'u1', role: 'admin' } as any);
});

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
});

const mount = async (Component: any, props: Record<string, unknown> = {}) => {
	const { writable } = await import('svelte/store');
	const target = document.createElement('div');
	document.body.appendChild(target);
	apps.push(new Component({ target, props, context: new Map([['i18n', writable({ t: (s: string) => s })]]) }));
	await sleep(20);
	return target;
};

describe('ModeShortcuts', () => {
	it('hands the draft and its files to the mode picked', async () => {
		const { default: ModeShortcuts } = await import('./ModeShortcuts.svelte');
		const target = await mount(ModeShortcuts, {
			prompt: '画一只柴犬',
			files: [{ id: 'f1', name: 'dog.png', type: 'image', status: 'uploaded' }]
		});
		expect(target.textContent).toContain('把这句话交给');
		expect(target.querySelectorAll('[data-halo-mode-shortcut]').length).toBe(4);
		(target.querySelector('[data-halo-mode-shortcut="studio"]') as any).click();
		expect(nav.goto).toHaveBeenCalledWith('/workspace/images?tab=workbench');
		const entry = JSON.parse(sessionStorage.getItem('halo.handoff')!);
		expect(entry).toMatchObject({ to: 'studio', text: '画一只柴犬', files: [{ id: 'f1', name: 'dog.png', type: 'image' }], from: null });
		(target.querySelector('[data-halo-mode-shortcut="answer"]') as any).click();
		expect(nav.goto).toHaveBeenLastCalledWith('/answer');
		expect(JSON.parse(sessionStorage.getItem('halo.handoff')!)).toMatchObject({ to: 'answer', text: '画一只柴犬' });
	});

	it('offers only what the account may use', async () => {
		stores.config.set({ features: { enable_agent_teams: false, enable_image_generation: true } } as any);
		stores.user.set({ id: 'u2', role: 'user', permissions: { features: { image_generation: false } } } as any);
		const { default: ModeShortcuts } = await import('./ModeShortcuts.svelte');
		const target = await mount(ModeShortcuts, { prompt: '' });
		expect([...target.querySelectorAll('[data-halo-mode-shortcut]')].map((el: any) => el.getAttribute('data-halo-mode-shortcut'))).toEqual(['answer', 'discuss']);
		expect(target.textContent).toContain('也可以');
	});
});

describe('SidebarModes', () => {
	it('is one row of 精答 / 讨论 / 协作 / 生图 with the current page marked', async () => {
		const { default: SidebarModes } = await import('$lib/components/layout/Sidebar/SidebarModes.svelte');
		const target = await mount(SidebarModes);
		const tiles = [...target.querySelectorAll('[data-sidebar-mode]')];
		expect(tiles.map((el: any) => el.textContent.trim())).toEqual(['精答', '讨论', '协作', '生图']);
		expect(tiles.map((el: any) => el.getAttribute('href'))).toEqual(['/answer', '/discuss', '/teams', '/workspace/images?tab=workbench']);
		expect(target.querySelector('[data-sidebar-mode="teams"]')!.getAttribute('aria-current')).toBe('page');
		expect(target.querySelector('[data-sidebar-discuss]')).toBeTruthy();
		expect(target.querySelector('[data-sidebar-answer]')).toBeTruthy();
	});
});

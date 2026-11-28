// The chat's modes as one family: the home composer's shortcuts take the draft along, the
// sidebar shows 讨论 / 协作 / 生图 as one row (and the studio only with image permission) with
// 助手 / 提示词 under it, and the chat list marks discussions, team chats and image chats.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const nav = vi.hoisted(() => ({ goto: vi.fn(), afterNavigate: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return { page: writable({ url: new URL('http://localhost/teams') }), navigating: writable(null), updated: { subscribe: writable(false).subscribe } };
});
vi.mock('$lib/apis/discussions', () => ({ listDiscussions: vi.fn(async () => []) }));
vi.mock('$lib/apis/teams', () => ({ listTeams: vi.fn(async () => ({ teams: [] })) }));
vi.mock('$lib/apis/answers', () => ({ listAnswers: vi.fn(async () => []) }));

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
	it('hands the draft and its files to the mode picked, including 自动分流 and live counts', async () => {
		const { setModeLive } = await import('$lib/components/scifi/mode-relay');
		setModeLive('teams', 2);
		const { default: ModeShortcuts } = await import('./ModeShortcuts.svelte');
		const target = await mount(ModeShortcuts, {
			prompt: '画一只柴犬',
			files: [{ id: 'f1', name: 'dog.png', type: 'image', status: 'uploaded' }]
		});
		expect(target.textContent).toContain('把这句话交给');
		expect(target.querySelector('[data-halo-shortcuts-cargo]')?.textContent).toContain('1 个附件');
		expect(target.querySelector('[data-halo-mode-shortcut-live="teams"]')?.textContent).toBe('2');
		expect(target.querySelectorAll('[data-halo-mode-shortcut]').length).toBe(6);
		(target.querySelector('[data-halo-mode-shortcut="auto"]') as any).click();
		expect(nav.goto).toHaveBeenCalledWith('/auto');
		expect(JSON.parse(sessionStorage.getItem('halo.handoff')!)).toMatchObject({
			to: 'auto',
			text: '画一只柴犬',
			files: [{ id: 'f1', name: 'dog.png', type: 'image' }]
		});
		(target.querySelector('[data-halo-mode-shortcut="studio"]') as any).click();
		expect(nav.goto).toHaveBeenCalledWith('/workspace/images?tab=workbench');
		const entry = JSON.parse(sessionStorage.getItem('halo.handoff')!);
		expect(entry).toMatchObject({ to: 'studio', text: '画一只柴犬', files: [{ id: 'f1', name: 'dog.png', type: 'image' }], from: null });
		(target.querySelector('[data-halo-mode-shortcut="answer"]') as any).click();
		expect(nav.goto).toHaveBeenLastCalledWith('/answer');
		expect(JSON.parse(sessionStorage.getItem('halo.handoff')!)).toMatchObject({ to: 'answer', text: '画一只柴犬' });
		setModeLive('teams', 0);
	});

	it('offers only what the account may use, and recognizes attachment-only drafts', async () => {
		stores.config.set({ features: { enable_agent_teams: false, enable_image_generation: true } } as any);
		stores.user.set({ id: 'u2', role: 'user', permissions: { features: { image_generation: false } } } as any);
		const { default: ModeShortcuts } = await import('./ModeShortcuts.svelte');
		const target = await mount(ModeShortcuts, { prompt: '' });
		expect([...target.querySelectorAll('[data-halo-mode-shortcut]')].map((el: any) => el.getAttribute('data-halo-mode-shortcut'))).toEqual(['auto', 'answer', 'discuss', 'video']);
		expect(target.textContent).toContain('工作台');
		const withFile = await mount(ModeShortcuts, {
			prompt: '',
			files: [{ id: 'f2', name: 'doc.pdf', type: 'file', status: 'uploaded' }]
		});
		expect(withFile.querySelector('[data-halo-mode-shortcuts]')?.hasAttribute('data-carrying')).toBe(true);
		expect(withFile.querySelector('[data-halo-shortcuts-cargo]')?.textContent).toContain('1 个附件');
	});
});

describe('SidebarModes', () => {
	it('is one row of 精答 / 讨论 / 协作 / 生图 / 视频 with the current page marked', async () => {
		const { default: SidebarModes } = await import('$lib/components/layout/Sidebar/SidebarModes.svelte');
		const target = await mount(SidebarModes);
		const tiles = [...target.querySelectorAll('[data-sidebar-mode]')];
		expect(tiles.map((el: any) => el.textContent.trim())).toEqual(['精答', '讨论', '协作', '生图', '视频']);
		expect(tiles.map((el: any) => el.getAttribute('href'))).toEqual(['/answer', '/discuss', '/teams', '/workspace/images?tab=workbench', '/workspace/videos']);
		expect(target.querySelector('[data-sidebar-mode="teams"]')!.getAttribute('aria-current')).toBe('page');
		expect(target.querySelector('[data-sidebar-discuss]')).toBeTruthy();
		expect(target.querySelector('[data-sidebar-answer]')).toBeTruthy();
	});
});

describe('SidebarLibrary', () => {
	const links = async () => {
		const { default: SidebarLibrary } = await import('$lib/components/layout/Sidebar/SidebarLibrary.svelte');
		const target = await mount(SidebarLibrary);
		return [...target.querySelectorAll('[data-sidebar-library]')].map((el: any) => [el.textContent.trim(), el.getAttribute('href')]);
	};

	it('puts 助手 and 提示词 where the workspace was, and 定时 for admins', async () => {
		expect(await links()).toEqual([
			['助手', '/workspace/models'],
			['提示词', '/workspace/prompts'],
			['定时', '/workspace/schedules']
		]);
	});

	it('follows the permissions: templates for users without the assistants page, nothing without any', async () => {
		stores.user.set({ id: 'u2', role: 'user', permissions: { workspace: { prompts: true } } } as any);
		expect(await links()).toEqual([
			['助手', '/workspace/assistants'],
			['提示词', '/workspace/prompts']
		]);
		stores.user.set({ id: 'u3', role: 'user', permissions: { workspace: {} } } as any);
		expect(await links()).toEqual([]);
	});

	it('collapses multiple libraries into one portaled popover trigger in compact rail mode', async () => {
		const { default: SidebarLibrary } = await import('$lib/components/layout/Sidebar/SidebarLibrary.svelte');
		const onOpen = vi.fn();
		const target = await mount(SidebarLibrary, { compact: true, onOpen });

		const trigger = target.querySelector('[data-sidebar-library-trigger]') as HTMLButtonElement | null;
		expect(trigger).toBeTruthy();
		expect(trigger!.getAttribute('aria-haspopup')).toBe('menu');
		expect(trigger!.getAttribute('aria-expanded')).toBe('false');
		expect(target.querySelectorAll('[data-sidebar-library]').length).toBe(0);
		expect(document.body.querySelector('[data-sidebar-library-popover]')).toBeFalsy();

		// Open popover — portaled to document.body, outside target
		trigger!.click();
		await sleep(20);

		expect(onOpen).toHaveBeenCalledTimes(1);
		expect(trigger!.getAttribute('aria-expanded')).toBe('true');
		const popover = document.body.querySelector('[data-sidebar-library-popover]') as HTMLElement | null;
		expect(popover).toBeTruthy();
		expect(target.contains(popover!)).toBe(false);

		const items = [...popover!.querySelectorAll('[data-sidebar-library]')].map((el: any) => [
			el.querySelector('[data-sidebar-library-label]')?.textContent?.trim(),
			el.getAttribute('href')
		]);
		expect(items).toEqual([
			['助手', '/workspace/models'],
			['提示词', '/workspace/prompts'],
			['定时', '/workspace/schedules']
		]);

		// Escape closes the popover
		const esc = new (window as any).Event('keydown', { bubbles: true }) as any;
		esc.key = 'Escape';
		window.dispatchEvent(esc);
		await sleep(20);
		expect(document.body.querySelector('[data-sidebar-library-popover]')).toBeFalsy();
		expect(trigger!.getAttribute('aria-expanded')).toBe('false');

		// Arrow keys move within the menu without closing it; Tab closes it (the
		// menu sits at the end of <body>, so Tab must not walk out of the page).
		trigger!.click();
		await sleep(20);
		const down = new (window as any).Event('keydown', { bubbles: true }) as any;
		down.key = 'ArrowDown';
		window.dispatchEvent(down);
		await sleep(20);
		expect(document.body.querySelector('[data-sidebar-library-popover]')).toBeTruthy();
		const tab = new (window as any).Event('keydown', { bubbles: true, cancelable: true }) as any;
		tab.key = 'Tab';
		window.dispatchEvent(tab);
		await sleep(20);
		expect(document.body.querySelector('[data-sidebar-library-popover]')).toBeFalsy();
		expect(trigger!.getAttribute('aria-expanded')).toBe('false');
	});

	it('renders a direct icon link for 1 library permission and nothing for 0 in compact mode', async () => {
		const { default: SidebarLibrary } = await import('$lib/components/layout/Sidebar/SidebarLibrary.svelte');

		// 1 permission (knowledge grants only 助手 -> /workspace/assistants)
		stores.user.set({ id: 'u4', role: 'user', permissions: { workspace: { knowledge: true } } } as any);
		const oneTarget = await mount(SidebarLibrary, { compact: true });
		expect(oneTarget.querySelector('[data-sidebar-library-trigger]')).toBeFalsy();
		const single = oneTarget.querySelector('[data-sidebar-library="assistants"]') as HTMLAnchorElement | null;
		expect(single).toBeTruthy();
		expect(single!.getAttribute('href')).toBe('/workspace/assistants');

		// 0 permissions
		stores.user.set({ id: 'u5', role: 'user', permissions: { workspace: {} } } as any);
		const emptyTarget = await mount(SidebarLibrary, { compact: true });
		expect(emptyTarget.querySelector('[data-sidebar-library-trigger]')).toBeFalsy();
		expect(emptyTarget.querySelector('[data-sidebar-library]')).toBeFalsy();
	});
});

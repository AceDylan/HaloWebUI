// Mounts the real avatar menu the way the page's top-right avatar does — no
// sidebar-only props. Regression guard for "Hermes 会话" being reachable from
// only one of the two avatar menus on screen.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));
vi.mock('$lib/apis/auths', () => ({ userSignOut: vi.fn(async () => {}) }));
// bits-ui's floating and focus machinery needs a real layout engine; the menu's
// own items are what is under test.
vi.mock('bits-ui', async () => {
	const { default: PassThrough } = await import('$lib/test-support/PassThrough.svelte');
	return { DropdownMenu: { Root: PassThrough, Trigger: PassThrough, Content: PassThrough } };
});
// The icon barrel is thousands of modules, slower to load than the test may take.
vi.mock('lucide-svelte', async () => {
	const { default: PassThrough } = await import('$lib/test-support/PassThrough.svelte');
	return { Bookmark: PassThrough };
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 150));

describe('UserMenu', () => {
	let target: HTMLElement;
	let component: { $destroy: () => void } | null = null;

	beforeEach(() => {
		target = document.createElement('div');
		document.body.appendChild(target);
	});

	afterEach(() => {
		component?.$destroy();
		component = null;
		target.remove();
	});

	it('opens the Hermes sessions dialog from any avatar menu', async () => {
		const stores = await import('$lib/stores');
		stores.showHermesSessions.set(false);
		stores.mobile.set(true);
		stores.showSidebar.set(true);

		const { default: UserMenu } = await import('./UserMenu.svelte');
		component = new UserMenu({
			target,
			props: { show: true, role: 'admin' },
			context: new Map([['i18n', writable({ t: (key: string) => key })]])
		});
		await settle();

		const item = document.querySelector(
			'[data-halo-user-menu-item="hermes-sessions"]'
		) as HTMLElement | null;
		expect(item).not.toBeNull();

		item!.dispatchEvent(new Event('click', { bubbles: true }));
		await settle();

		expect(get(stores.showHermesSessions)).toBe(true);
		expect(get(stores.showSidebar)).toBe(false);
	});
});

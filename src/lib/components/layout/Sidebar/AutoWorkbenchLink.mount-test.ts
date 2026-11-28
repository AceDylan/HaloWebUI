import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';
installDominoDom('http://localhost/auto');
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return { page: writable({ url: new URL('http://localhost/auto') }) };
});
let Link: any, app: any, target: HTMLElement;
beforeAll(async () => {
	Link = (await import('./AutoWorkbenchLink.svelte')).default;
});
afterEach(() => {
	app?.$destroy();
	target?.remove();
});
it('renders the workbench as a separate full row, with an accessible compact entry', () => {
	target = document.createElement('div');
	document.body.appendChild(target);
	const navigate = vi.fn();
	app = new Link({ target, props: { buttonClass: 'w-full flex', onNavigate: navigate } });
	const row = target.querySelector('[data-sidebar-auto-row]')!;
	expect(row).toBeTruthy();
	expect(row.querySelector('a')!.getAttribute('href')).toBe('/auto');
	expect(row.textContent).toContain('自动分流工作台');
	row.querySelector('a')!.click();
	expect(navigate).toHaveBeenCalledOnce();
	app.$destroy();
	target.innerHTML = '';
	app = new Link({ target, props: { compact: true } });
	expect(target.querySelector('[aria-label="自动分流工作台"]')).toBeTruthy();
});

it('renders a compact inline pill when inline is enabled', () => {
	target = document.createElement('div');
	document.body.appendChild(target);
	const navigate = vi.fn();
	app = new Link({ target, props: { inline: true, onNavigate: navigate } });
	expect(target.querySelector('[data-sidebar-auto-row]')).toBeFalsy();
	const pill = target.querySelector('[data-sidebar-auto-inline]') as HTMLAnchorElement | null;
	expect(pill).toBeTruthy();
	expect(pill!.getAttribute('href')).toBe('/auto');
	expect(pill!.getAttribute('aria-label')).toBe('自动分流工作台');
	expect(pill!.hasAttribute('data-sidebar-auto')).toBe(true);
	expect(pill!.textContent).toContain('自动分流');
	pill!.click();
	expect(navigate).toHaveBeenCalledOnce();
});

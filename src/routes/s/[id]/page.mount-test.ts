// Shared-chat link opened signed out: the conversation renders from the public
// endpoint, with no sign-in redirect, no session-only calls and no clone button.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/s/share-1');

vi.mock('$app/environment', () => ({
	browser: true,
	dev: false,
	building: false,
	version: 'test'
}));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const page = writable({ url: new URL('http://localhost/s/share-1'), params: { id: 'share-1' } });
	return { page, navigating: writable(null), updated: { subscribe: writable(false).subscribe } };
});
const nav = vi.hoisted(() => ({ goto: vi.fn(async () => {}) }));
vi.mock('$app/navigation', () => ({
	goto: nav.goto,
	invalidate: async () => {},
	invalidateAll: async () => {},
	afterNavigate: () => {},
	beforeNavigate: () => {},
	onNavigate: () => {}
}));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));
const api = vi.hoisted(() => ({
	getPublicSharedChat: vi.fn(),
	getChatByShareId: vi.fn(),
	cloneSharedChatById: vi.fn(),
	getUserSettings: vi.fn(),
	getUserById: vi.fn()
}));
vi.mock('$lib/apis/chats', async (importOriginal) => ({
	...(await importOriginal<any>()),
	getPublicSharedChat: api.getPublicSharedChat,
	getChatByShareId: api.getChatByShareId,
	cloneSharedChatById: api.cloneSharedChatById
}));
vi.mock('$lib/apis/users', async (importOriginal) => ({
	...(await importOriginal<any>()),
	getUserSettings: api.getUserSettings,
	getUserById: api.getUserById
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 10000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

let Page: any;
let stores: any;
const apps: any[] = [];

beforeAll(async () => {
	stores = await import('$lib/stores');
	Page = (await import('./+page.svelte')).default;
}, 60000);

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
	Object.values(api).forEach((fn) => fn.mockReset());
	nav.goto.mockClear();
});

const mount = () => {
	const target = document.createElement('div');
	document.body.appendChild(target);
	apps.push(
		new Page({
			target,
			context: new Map([['i18n', writable({ t: (s: string) => s, language: 'en-US' })]])
		})
	);
	return target;
};

const shared = {
	id: 'share-1',
	title: 'Trip plan',
	user: { name: 'Dylan' },
	chat: {
		title: 'Trip plan',
		models: ['gpt-x'],
		timestamp: 1,
		history: {
			currentId: 'a',
			messages: {
				u: {
					id: 'u',
					role: 'user',
					content: 'Plan a trip',
					parentId: null,
					childrenIds: ['a'],
					timestamp: 1
				},
				a: {
					id: 'a',
					role: 'assistant',
					content: 'Day one: the lake.',
					parentId: 'u',
					childrenIds: [],
					model: 'gpt-x',
					done: true,
					timestamp: 2
				}
			}
		}
	}
};

describe('shared chat page, signed out', () => {
	it('shows the conversation from the public endpoint without a session', async () => {
		stores.user.set(undefined);
		api.getPublicSharedChat.mockResolvedValue(shared);
		const target = mount();
		await until(() => (target.textContent ?? '').includes('Day one: the lake.'));

		expect(api.getPublicSharedChat).toHaveBeenCalledWith('share-1');
		expect(target.textContent).toContain('Trip plan');
		expect(target.textContent).toContain('Plan a trip');
		expect(target.textContent).not.toContain('Clone Chat');
		expect(api.getChatByShareId).not.toHaveBeenCalled();
		expect(api.getUserSettings).not.toHaveBeenCalled();
		expect(nav.goto).not.toHaveBeenCalled();
	});

	it('says a dead link is gone instead of sending the visitor to sign in', async () => {
		stores.user.set(undefined);
		api.getPublicSharedChat.mockRejectedValue({ detail: 'Not found' });
		const target = mount();
		await until(() => !!target.querySelector('[data-shared-chat-not-found]'));
		expect(target.textContent).toContain('This shared link is invalid or has been removed.');
		expect(nav.goto).not.toHaveBeenCalled();
	});

	it('keeps the signed-in view and its clone button', async () => {
		stores.user.set({ id: 'me', name: 'Me', role: 'user' });
		api.getUserSettings.mockResolvedValue(null);
		api.getChatByShareId.mockResolvedValue({ ...shared, user_id: 'owner' });
		api.getUserById.mockResolvedValue({ name: 'Dylan' });
		const target = mount();
		await until(() => (target.textContent ?? '').includes('Day one: the lake.'));
		expect(target.textContent).toContain('Clone Chat');
		expect(api.getPublicSharedChat).not.toHaveBeenCalled();
	});
});

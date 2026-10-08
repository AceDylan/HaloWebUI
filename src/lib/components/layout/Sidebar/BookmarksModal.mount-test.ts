// Mounts the real 收藏 dialog against a fake server: kept replies are listed newest
// first, a search narrows them, opening one goes to its chat at that reply, and
// 取消收藏 removes it from the list and from the marks on the open chat.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));
vi.mock('$lib/apis/bookmarks', () => ({
	getBookmarks: vi.fn(),
	removeBookmark: vi.fn()
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(probe: () => T | null | undefined | false, label: string, timeout = 8000) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > timeout) {
			throw new Error(
				`timed out waiting for ${label}; text: ${String(document.body.textContent ?? '')
					.replace(/\s+/g, ' ')
					.slice(0, 400)}`
			);
		}
		await sleep(15);
	}
};

const KEPT = [
	{
		id: 'b2',
		chat_id: 'chat-2',
		message_id: 'm2',
		role: 'assistant',
		excerpt: 'Run docker compose up -d after editing the file.',
		created_at: 1_760_000_100,
		chat_title: 'Deploy notes',
		chat_archived: true
	},
	{
		id: 'b1',
		chat_id: 'chat-1',
		message_id: 'm1',
		role: 'assistant',
		excerpt: 'Redis listens on 6379 by default.',
		created_at: 1_760_000_000,
		chat_title: 'Server ports',
		chat_archived: false
	}
];

const items = () => Array.from(document.body.querySelectorAll('[data-halo-bookmark]')) as any[];

let app: any;
let target: any;
let api: any;
let stores: any;

const openDialog = async () => {
	const { writable } = await import('svelte/store');
	const i18n = writable({
		language: 'en-US',
		resolvedLanguage: 'en-US',
		t: (key: string) => key,
		exists: () => false,
		on: () => {},
		off: () => {},
		changeLanguage: async () => {}
	});
	const { default: BookmarksModal } = await import('./BookmarksModal.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new BookmarksModal({
		target,
		props: { show: true },
		context: new Map<string, any>([['i18n', i18n]])
	});
	await waitFor(() => items().length > 0, 'the kept replies');
};

beforeEach(async () => {
	(globalThis as any).localStorage.token = 'tok';
	api = await import('$lib/apis/bookmarks');
	stores = await import('$lib/stores');
	api.getBookmarks.mockResolvedValue(structuredClone(KEPT));
	api.removeBookmark.mockResolvedValue(true);
	stores.pendingMessageReveal.set(null);
	stores.chatBookmarkIds.set({ chatId: 'chat-1', ids: new Set(['m1']) });
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	vi.clearAllMocks();
});

describe('收藏', () => {
	it('lists kept replies with their chat, newest first', async () => {
		await openDialog();

		expect(items().map((el) => el.getAttribute('data-halo-bookmark'))).toEqual(['b2', 'b1']);
		expect(items()[0].textContent).toContain('docker compose');
		expect(items()[0].textContent).toContain('Deploy notes');
		expect(items()[0].textContent).toContain('Archived');
	});

	it('narrows the list as the person types', async () => {
		await openDialog();

		const input = document.body.querySelector('input') as any;
		input.value = '6379';
		input.dispatchEvent(new (window as any).Event('input'));

		await waitFor(() => items().length === 1, 'one match');
		expect(items()[0].getAttribute('data-halo-bookmark')).toBe('b1');
		expect(items()[0].querySelector('mark')?.textContent).toBe('6379');
	});

	it('opens the chat at the kept reply', async () => {
		const { goto } = await import('$app/navigation');
		const { get } = await import('svelte/store');
		await openDialog();

		items()[1].querySelector('button').click();

		await waitFor(() => (goto as any).mock.calls.length > 0, 'navigation');
		expect((goto as any).mock.calls[0][0]).toBe('/c/chat-1');
		expect(get(stores.pendingMessageReveal)).toEqual({ chatId: 'chat-1', messageId: 'm1' });
	});

	it('取消收藏 removes it from the list and from the open chat', async () => {
		const { get } = await import('svelte/store');
		await openDialog();

		const remove = items()[1].querySelectorAll('button')[1];
		remove.click();

		await waitFor(() => items().length === 1, 'the row to go');
		expect(api.removeBookmark).toHaveBeenCalledWith('tok', 'b1');
		expect(get(stores.chatBookmarkIds).ids.has('m1')).toBe(false);
	});
});

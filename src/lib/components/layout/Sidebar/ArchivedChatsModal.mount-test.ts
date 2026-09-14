// Mounts the real Archived Chats modal against a fake server holding more chats
// than fit on a page. Regression guard for the modal fetching (and rendering)
// every archived conversation the moment it opened.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

// DOMPurify cannot parse HTML through domino's document implementation (it returns '');
// sanitisation is not under test here, so pass the tooltip markup through.
vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));
vi.mock('file-saver', () => ({ default: { saveAs: vi.fn() } }));
vi.mock('$lib/apis/chats', () => ({
	archiveChatById: vi.fn(),
	deleteChatById: vi.fn(),
	getAllArchivedChats: vi.fn(),
	getArchivedChatCount: vi.fn(),
	getArchivedChatList: vi.fn()
}));

const TOTAL = 57;
const PER_PAGE = 20; // what the modal asks for

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(
	probe: () => T | null | undefined | false,
	label: string,
	timeout = 8000
) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > timeout) {
			throw new Error(
				`timed out waiting for ${label}; modal text: ${String(document.body.textContent ?? '')
					.replace(/\s+/g, ' ')
					.slice(0, 400)}`
			);
		}
		await sleep(15);
	}
};

// The fake archive: titles are stable so a page can be named exactly.
let archived: { id: string; title: string; updated_at: number; created_at: number }[] = [];

const resetArchive = (count = TOTAL) => {
	archived = Array.from({ length: count }, (_, index) => ({
		id: `chat-${index}`,
		title: `Archived ${index}`,
		updated_at: 1_000 + (count - index),
		created_at: 1_000 + (count - index)
	}));
};

const rows = () => Array.from(document.body.querySelectorAll('tbody tr'));
const rowTitles = () => rows().map((row: any) => row.querySelector('td a').textContent.trim());
const byText = (selector: string, text: string) =>
	Array.from(document.body.querySelectorAll(selector)).find(
		(el: any) => el.textContent.trim() === text
	) as any;

let app: any;
let target: any;
let api: any;

const openModal = async () => {
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
	const { default: ArchivedChatsModal } = await import('./ArchivedChatsModal.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new ArchivedChatsModal({
		target,
		props: { show: true },
		context: new Map<string, any>([['i18n', i18n]])
	});
	await waitFor(() => rows().length > 0, 'first page of archived chats');
};

beforeEach(async () => {
	(globalThis as any).localStorage.token = 'tok';
	resetArchive();
	api = await import('$lib/apis/chats');
	api.getArchivedChatList.mockImplementation(
		async (_token: string, options: { page?: number; limit?: number; query?: string } = {}) => {
			const query = (options.query ?? '').trim().toLowerCase();
			const matching = query
				? archived.filter((chat) => chat.title.toLowerCase().includes(query))
				: archived;
			const limit = options.limit ?? 50;
			const skip = ((options.page ?? 1) - 1) * limit;
			return matching.slice(skip, skip + limit);
		}
	);
	api.getArchivedChatCount.mockImplementation(async (_token: string, query = '') => {
		const needle = query.trim().toLowerCase();
		return needle
			? archived.filter((chat) => chat.title.toLowerCase().includes(needle)).length
			: archived.length;
	});
	api.archiveChatById.mockImplementation(async (_token: string, id: string) => {
		archived = archived.filter((chat) => chat.id !== id);
		return { id };
	});
	api.deleteChatById.mockImplementation(async (_token: string, id: string) => {
		archived = archived.filter((chat) => chat.id !== id);
		return true;
	});
	api.getAllArchivedChats.mockResolvedValue([]);
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	vi.clearAllMocks();
});

describe('ArchivedChatsModal: the archive is read one page at a time', () => {
	it('opens on the first page only, and never asks for the whole archive', async () => {
		await openModal();

		expect(api.getArchivedChatList).toHaveBeenCalledTimes(1);
		expect(api.getArchivedChatList.mock.calls[0][1]).toMatchObject({ page: 1, limit: PER_PAGE });
		expect(api.getAllArchivedChats).not.toHaveBeenCalled();

		expect(rows()).toHaveLength(PER_PAGE);
		expect(rowTitles()[0]).toBe('Archived 0');
		expect(document.body.textContent).toContain(`${TOTAL}`); // the header shows the real total
	});

	it('fetches the next page from the server when the pager moves', async () => {
		await openModal();

		const secondPage = await waitFor(() => byText('button', '2'), 'page 2 button');
		secondPage.click();

		await waitFor(() => rowTitles()[0] === 'Archived 20', 'second page rows');
		const lastCall = api.getArchivedChatList.mock.calls.at(-1)[1];
		expect(lastCall).toMatchObject({ page: 2, limit: PER_PAGE });
		expect(rows()).toHaveLength(PER_PAGE);

		const lastPageButton = await waitFor(() => byText('button', '3'), 'page 3 button');
		lastPageButton.click();
		await waitFor(() => rows().length === TOTAL - 2 * PER_PAGE, 'short last page');
		expect(rowTitles().at(-1)).toBe(`Archived ${TOTAL - 1}`);
	});

	it('hands the search to the server instead of filtering the page in the browser', async () => {
		await openModal();

		const input = document.body.querySelector('input') as any;
		input.value = 'Archived 4';
		input.dispatchEvent(new (globalThis as any).Event('input', { bubbles: true }));

		await waitFor(
			() => api.getArchivedChatList.mock.calls.at(-1)[1]?.query === 'Archived 4',
			'search sent to the server'
		);
		await waitFor(() => rowTitles().length === 11, 'search results (4, 40..49)');
		expect(api.getArchivedChatList.mock.calls.at(-1)[1]).toMatchObject({ page: 1 });
		expect(rowTitles()).toContain('Archived 4');
		expect(rowTitles()).toContain('Archived 49');
	});

	it('reports an empty search without claiming the archive is empty', async () => {
		await openModal();

		const input = document.body.querySelector('input') as any;
		input.value = 'nothing matches this';
		input.dispatchEvent(new (globalThis as any).Event('input', { bubbles: true }));

		await waitFor(() => document.body.textContent.includes('No results found'), 'empty search');
		expect(document.body.textContent).not.toContain('You have no archived conversations.');
		// Unarchive/export stay reachable: they act on the archive, not the search.
		expect(byText('button', 'Export All Archived Chats')).toBeTruthy();
	});

	it('steps back a page when the last row of the last page is deleted', async () => {
		resetArchive(PER_PAGE + 1);
		await openModal();

		(await waitFor(() => byText('button', '2'), 'page 2 button')).click();
		await waitFor(() => rows().length === 1, 'single row on the last page');

		const deleteButton = rows()[0].querySelectorAll('button')[1] as any;
		deleteButton.click();

		await waitFor(() => rows().length === PER_PAGE, 'fallback to the page that still has rows');
		expect(api.deleteChatById).toHaveBeenCalledTimes(1);
		expect(api.getArchivedChatList.mock.calls.at(-1)[1]).toMatchObject({ page: 1 });
	});

	it('unarchives every page, not just the one on screen', async () => {
		resetArchive(45);
		await openModal();

		(
			await waitFor(() => byText('button', 'Unarchive All Archived Chats'), 'unarchive all')
		).click();
		const confirm = await waitFor(() => byText('button', 'Unarchive All'), 'confirm button');
		confirm.click();

		await waitFor(() => archived.length === 0, 'every archived chat unarchived', 20000);
		expect(api.archiveChatById).toHaveBeenCalledTimes(45);
		await waitFor(
			() => document.body.textContent.includes('You have no archived conversations.'),
			'empty state after unarchiving everything'
		);
	}, 30000);

	it('shows the error and retries the same page when the list cannot be read', async () => {
		api.getArchivedChatList.mockRejectedValueOnce(new Error('server is down'));
		api.getArchivedChatCount.mockRejectedValueOnce(new Error('server is down'));

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
		const { default: ArchivedChatsModal } = await import('./ArchivedChatsModal.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new ArchivedChatsModal({
			target,
			props: { show: true },
			context: new Map<string, any>([['i18n', i18n]])
		});

		const retry = await waitFor(() => byText('button', 'Retry'), 'retry button');
		expect(document.body.textContent).toContain('server is down');

		retry.click();
		await waitFor(() => rows().length === PER_PAGE, 'the page after a retry');
	});
});

// Mounts the real Hermes Sessions modal against a fake hermes holding more
// sessions per surface than fit on a page. Regression guard for all three tabs
// (Telegram / QQ / CLI) showing a flat first fifty with no way to reach the
// rest.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));
vi.mock('$lib/apis/hermes', () => ({
	getHermesSessions: vi.fn(),
	importHermesSession: vi.fn()
}));

const PAGE_SIZE = 20; // what the modal asks for
const COUNTS: Record<string, number> = { telegram: 47, qqbot: 3, cli: 25 };

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

const makeSessions = (source: string, count: number) =>
	Array.from({ length: count }, (_, index) => ({
		id: `${source}-${index}`,
		source,
		title: `${source} ${index}`,
		preview: '',
		message_count: 4,
		started_at: 1_000 + count - index,
		last_active: 2_000 + count - index,
		model: 'hermes',
		imported: false
	}));

let store: Record<string, ReturnType<typeof makeSessions>> = {};

const rows = () => Array.from(document.body.querySelectorAll('button[type="button"]'));
const rowTitles = () => rows().map((row: any) => row.querySelector('div > div').textContent.trim());
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
	const { default: HermesSessionsModal } = await import('./HermesSessionsModal.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new HermesSessionsModal({
		target,
		props: { show: true },
		context: new Map<string, any>([['i18n', i18n]])
	});
	await waitFor(() => rows().length > 0, 'first page of hermes sessions');
};

const switchTo = async (label: string) => {
	const tab = await waitFor(() => byText('button', label), `${label} tab`);
	tab.click();
};

beforeEach(async () => {
	(globalThis as any).localStorage.token = 'tok';
	store = {
		telegram: makeSessions('telegram', COUNTS.telegram),
		qqbot: makeSessions('qqbot', COUNTS.qqbot),
		cli: makeSessions('cli', COUNTS.cli)
	};
	api = await import('$lib/apis/hermes');
	api.getHermesSessions.mockImplementation(
		async (_token: string, source: string, opts: { limit?: number; offset?: number } = {}) => {
			const limit = opts.limit ?? 20;
			const offset = opts.offset ?? 0;
			const all = store[source] ?? [];
			const slice = all.slice(offset, offset + limit);
			return { sessions: slice, next_offset: offset + limit, has_more: slice.length >= limit };
		}
	);
	api.importHermesSession.mockImplementation(async (_token: string, id: string) => ({
		chat_id: id,
		title: id,
		created: true,
		imported_turns: 2
	}));
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	vi.clearAllMocks();
});

describe('HermesSessionsModal: each surface is read one page at a time', () => {
	it('opens on the first page only, and never asks for the whole surface', async () => {
		await openModal();

		expect(api.getHermesSessions).toHaveBeenCalledTimes(1);
		const [, source, opts] = api.getHermesSessions.mock.calls[0];
		expect(source).toBe('telegram');
		expect(opts).toMatchObject({ limit: PAGE_SIZE, offset: 0 });
		expect(rows()).toHaveLength(PAGE_SIZE);
		expect(rowTitles()[0]).toBe('telegram 0');
	});

	it('walks Telegram to the end with the cursor, without repeats or gaps', async () => {
		await openModal();

		for (const expected of [40, COUNTS.telegram]) {
			const more = await waitFor(() => byText('button', 'Load more'), 'Load more');
			more.click();
			await waitFor(() => rows().length === expected, `${expected} rows loaded`);
		}

		const titles = rowTitles();
		expect(titles).toEqual(store.telegram.map((s) => s.title));
		expect(new Set(titles).size).toBe(COUNTS.telegram);
		expect(api.getHermesSessions.mock.calls.map((call: any[]) => call[2].offset)).toEqual([
			0, 20, 40
		]);
		// The surface ran out: no pager left to press.
		expect(byText('button', 'Load more')).toBeUndefined();
	});

	it('gives each of the three tabs its own first page and forgets the last one', async () => {
		await openModal();

		await switchTo('QQ');
		await waitFor(() => rowTitles()[0] === 'qqbot 0', 'QQ rows');
		expect(rows()).toHaveLength(COUNTS.qqbot); // short surface, no pager
		expect(byText('button', 'Load more')).toBeUndefined();
		expect(api.getHermesSessions.mock.calls.at(-1)).toMatchObject([
			'tok',
			'qqbot',
			{ limit: PAGE_SIZE, offset: 0 }
		]);

		await switchTo('CLI');
		await waitFor(() => rowTitles()[0] === 'cli 0', 'CLI rows');
		expect(rows()).toHaveLength(PAGE_SIZE);
		const more = await waitFor(() => byText('button', 'Load more'), 'CLI Load more');
		more.click();
		await waitFor(() => rows().length === COUNTS.cli, 'rest of CLI');
		expect(rowTitles().every((title) => title.startsWith('cli '))).toBe(true);

		// Back to Telegram: its own first page again, not CLI's rows and not
		// CLI's cursor.
		await switchTo('Telegram');
		await waitFor(() => rowTitles()[0] === 'telegram 0', 'telegram rows again');
		expect(rows()).toHaveLength(PAGE_SIZE);
		expect(api.getHermesSessions.mock.calls.at(-1)[2]).toMatchObject({ offset: 0 });
	});

	it('drops a page that lost its race with a tab switch', async () => {
		let releaseTelegram: (() => void) | null = null;
		api.getHermesSessions.mockImplementation(
			async (_token: string, source: string, opts: { limit?: number; offset?: number } = {}) => {
				const slice = (store[source] ?? []).slice(
					opts.offset ?? 0,
					(opts.offset ?? 0) + (opts.limit ?? 20)
				);
				const page = {
					sessions: slice,
					next_offset: (opts.offset ?? 0) + (opts.limit ?? 20),
					has_more: slice.length >= (opts.limit ?? 20)
				};
				if (source === 'telegram') {
					await new Promise<void>((resolve) => {
						releaseTelegram = resolve;
					});
				}
				return page;
			}
		);

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
		const { default: HermesSessionsModal } = await import('./HermesSessionsModal.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new HermesSessionsModal({
			target,
			props: { show: true },
			context: new Map<string, any>([['i18n', i18n]])
		});

		await waitFor(() => releaseTelegram, 'the telegram request to be in flight');
		await switchTo('QQ');
		await waitFor(() => rowTitles()[0] === 'qqbot 0', 'QQ rows');

		releaseTelegram!(); // the stale telegram page lands now
		await sleep(80);

		expect(rowTitles()).toEqual(store.qqbot.map((s) => s.title));
	});

	it('shows the failure and retries instead of claiming the surface is empty', async () => {
		api.getHermesSessions.mockRejectedValueOnce('hermes connection is not configured');

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
		const { default: HermesSessionsModal } = await import('./HermesSessionsModal.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new HermesSessionsModal({
			target,
			props: { show: true },
			context: new Map<string, any>([['i18n', i18n]])
		});

		await waitFor(
			() => document.body.textContent?.includes('hermes connection is not configured'),
			'the error the server gave'
		);
		expect(document.body.textContent).not.toContain('No hermes sessions');

		const retry = await waitFor(() => byText('button', 'Retry'), 'Retry');
		retry.click();
		await waitFor(() => rows().length === PAGE_SIZE, 'the retried first page');
		expect(rowTitles()[0]).toBe('telegram 0');
	});

	it('keeps the loaded rows when only the next page fails', async () => {
		await openModal();
		api.getHermesSessions.mockRejectedValueOnce('hermes returned 502');

		const more = await waitFor(() => byText('button', 'Load more'), 'Load more');
		more.click();
		await waitFor(() => byText('button', 'Load more'), 'the pager to come back');

		expect(rows()).toHaveLength(PAGE_SIZE);
		expect(document.body.textContent).not.toContain('No hermes sessions');
		const { toast } = await import('svelte-sonner');
		expect(toast.error).toHaveBeenCalled();
	});

	it('offers the pager, not "nothing here", when a page is empty but more remain', async () => {
		// hermes hands over stretches of the empty shells the server drops, so the
		// first page can legitimately be empty while the walk continues — the
		// conversations start at offset 100 here.
		store.telegram = makeSessions('telegram', 140);
		api.getHermesSessions.mockImplementationOnce(async () => ({
			sessions: [],
			next_offset: 100,
			has_more: true
		}));

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
		const { default: HermesSessionsModal } = await import('./HermesSessionsModal.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new HermesSessionsModal({
			target,
			props: { show: true },
			context: new Map<string, any>([['i18n', i18n]])
		});

		const more = await waitFor(() => byText('button', 'Load more'), 'Load more on an empty page');
		expect(document.body.textContent).not.toContain('No hermes sessions');

		more.click();
		await waitFor(() => rows().length > 0, 'the rows past the empty stretch');
		expect(api.getHermesSessions.mock.calls.at(-1)[2]).toMatchObject({ offset: 100 });
	});

	it('says the surface is empty once the walk is actually over', async () => {
		store.telegram = [];

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
		const { default: HermesSessionsModal } = await import('./HermesSessionsModal.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new HermesSessionsModal({
			target,
			props: { show: true },
			context: new Map<string, any>([['i18n', i18n]])
		});

		await waitFor(
			() => document.body.textContent?.includes('No hermes sessions'),
			'the empty-surface message'
		);
		expect(byText('button', 'Load more')).toBeUndefined();
	});

	it('re-reads the current surface from page one when Refresh is pressed', async () => {
		await openModal();
		const more = await waitFor(() => byText('button', 'Load more'), 'Load more');
		more.click();
		await waitFor(() => rows().length === 40, '40 rows loaded');

		store.telegram = makeSessions('telegram', 5);
		byText('button', 'Refresh').click();

		await waitFor(() => rows().length === 5, 'the refreshed surface');
		expect(api.getHermesSessions.mock.calls.at(-1)[2]).toMatchObject({ offset: 0 });
		expect(byText('button', 'Load more')).toBeUndefined();
	});
});

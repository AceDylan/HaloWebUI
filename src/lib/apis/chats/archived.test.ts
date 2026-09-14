// The archived list is paged by the server: these guard the query string the
// modal sends, so a page request can never turn back into "give me everything".
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/constants', () => ({ WEBUI_API_BASE_URL: '/api/v1' }));

import { getArchivedChatCount, getArchivedChatList } from './index';

const jsonResponse = (body: unknown, status = 200) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});

const stubFetch = (body: unknown, status = 200) => {
	const fetchMock = vi.fn(async () => jsonResponse(body, status));
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
};

const urlOf = (fetchMock: ReturnType<typeof stubFetch>, call = 0) =>
	new URL((fetchMock.mock.calls[call] as unknown as [string])[0], 'http://localhost');

describe('getArchivedChatList', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('asks for a single page and passes the token', async () => {
		const fetchMock = stubFetch([{ id: 'c1', title: 'One', updated_at: 1, created_at: 1 }]);

		const chats = await getArchivedChatList('tok', { page: 3, limit: 20 });

		const url = urlOf(fetchMock);
		expect(url.pathname).toBe('/api/v1/chats/archived');
		expect(url.searchParams.get('page')).toBe('3');
		expect(url.searchParams.get('limit')).toBe('20');
		expect(url.searchParams.has('query')).toBe(false);
		const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect((init.headers as Record<string, string>).authorization).toBe('Bearer tok');
		expect(chats[0].id).toBe('c1');
		expect(chats[0].time_range).toBeTruthy(); // still grouped like the other chat lists
	});

	it('sends the search to the server, trimmed, and drops an empty one', async () => {
		const fetchMock = stubFetch([]);

		await getArchivedChatList('tok', { page: 1, limit: 20, query: '  holiday  ' });
		expect(urlOf(fetchMock).searchParams.get('query')).toBe('holiday');

		await getArchivedChatList('tok', { page: 1, limit: 20, query: '   ' });
		expect(urlOf(fetchMock, 1).searchParams.has('query')).toBe(false);
	});

	it('leaves the paging to the server when the caller asks for no page', async () => {
		const fetchMock = stubFetch([]);

		await getArchivedChatList('tok');

		expect(urlOf(fetchMock).search).toBe('');
	});

	it('tolerates an empty body and raises the server error', async () => {
		stubFetch(null);
		expect(await getArchivedChatList('tok', { page: 1 })).toEqual([]);

		vi.unstubAllGlobals();
		stubFetch({ detail: 'nope' }, 500);
		await expect(getArchivedChatList('tok', { page: 1 })).rejects.toBeTruthy();
	});
});

describe('getArchivedChatCount', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('reads the total under the same filter', async () => {
		const fetchMock = stubFetch({ count: 137 });

		expect(await getArchivedChatCount('tok', ' invoice ')).toBe(137);

		const url = urlOf(fetchMock);
		expect(url.pathname).toBe('/api/v1/chats/archived/count');
		expect(url.searchParams.get('query')).toBe('invoice');
	});

	it('counts nothing when the server answers without a number', async () => {
		stubFetch({});
		expect(await getArchivedChatCount('tok')).toBe(0);
	});
});

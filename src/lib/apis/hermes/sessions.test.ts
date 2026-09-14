// The hermes session list is paged by cursor: these guard the query string the
// modal sends, so a page request can never turn back into "give me the first
// fifty and hide the rest".
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/constants', () => ({ WEBUI_API_BASE_URL: '/api/v1' }));

import { getHermesSessions } from './index';

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

const session = (id: string) => ({
	id,
	source: 'telegram',
	title: id,
	preview: '',
	message_count: 3,
	started_at: 1,
	last_active: 2,
	model: 'hermes',
	imported: false
});

describe('getHermesSessions', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('asks for one page at the requested cursor and passes the token', async () => {
		const fetchMock = stubFetch({
			sessions: [session('s1')],
			offset: 40,
			next_offset: 60,
			has_more: true
		});

		const page = await getHermesSessions('tok', 'cli', { limit: 20, offset: 40 });

		const url = urlOf(fetchMock);
		expect(url.pathname).toBe('/api/v1/hermes/sessions');
		expect(url.searchParams.get('source')).toBe('cli');
		expect(url.searchParams.get('limit')).toBe('20');
		expect(url.searchParams.get('offset')).toBe('40');
		const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect((init.headers as Record<string, string>).authorization).toBe('Bearer tok');
		expect(page).toEqual({ sessions: [session('s1')], next_offset: 60, has_more: true });
	});

	it('defaults to the first page of telegram', async () => {
		const fetchMock = stubFetch({ sessions: [], next_offset: 20, has_more: false });

		await getHermesSessions('tok');

		const url = urlOf(fetchMock);
		expect(url.searchParams.get('source')).toBe('telegram');
		expect(url.searchParams.get('offset')).toBe('0');
		expect(url.searchParams.get('limit')).toBe('20');
	});

	it('treats a backend that answers {sessions} alone as a single final page', async () => {
		stubFetch({ sessions: [session('s1'), session('s2')] });

		const page = await getHermesSessions('tok', 'qqbot', { limit: 20, offset: 20 });

		expect(page.has_more).toBe(false);
		expect(page.next_offset).toBe(22); // where those rows ended, not past them
	});

	it('reads an empty page without inventing rows', async () => {
		stubFetch({ sessions: [], next_offset: 100, has_more: false });

		expect(await getHermesSessions('tok', 'cli', { offset: 80 })).toEqual({
			sessions: [],
			next_offset: 100,
			has_more: false
		});
	});

	it('throws the server detail so the modal can show why the page failed', async () => {
		stubFetch({ detail: 'hermes connection is not configured' }, 503);

		await expect(getHermesSessions('tok', 'telegram', { offset: 0 })).rejects.toBe(
			'hermes connection is not configured'
		);
	});
});

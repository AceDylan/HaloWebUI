import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchRidingRestart } from './restart-retry';

const response = (status: number) => new Response('{}', { status });
const noSleep = async () => {};

afterEach(() => vi.unstubAllGlobals());

describe('fetchRidingRestart', () => {
	it('waits out a 502 restart window and returns the answer', async () => {
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce(response(502))
			.mockRejectedValueOnce(new TypeError('Failed to fetch'))
			.mockResolvedValueOnce(response(200));
		vi.stubGlobal('fetch', fetchMock);
		const res = await fetchRidingRestart('/x', {}, { sleep: noSleep, online: () => true });
		expect(res.status).toBe(200);
		expect(fetchMock).toHaveBeenCalledTimes(3);
	});

	it('returns ordinary errors at once', async () => {
		const fetchMock = vi.fn().mockResolvedValue(response(404));
		vi.stubGlobal('fetch', fetchMock);
		expect((await fetchRidingRestart('/x', {}, { sleep: noSleep })).status).toBe(404);
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('gives the last 502 back once the delays are used up', async () => {
		const fetchMock = vi.fn().mockResolvedValue(response(502));
		vi.stubGlobal('fetch', fetchMock);
		const res = await fetchRidingRestart('/x', {}, { delays: [1, 1], sleep: noSleep });
		expect(res.status).toBe(502);
		expect(fetchMock).toHaveBeenCalledTimes(3);
	});

	it('does not wait while the device is offline', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		await expect(
			fetchRidingRestart('/x', {}, { sleep: noSleep, online: () => false })
		).rejects.toBeInstanceOf(TypeError);
	});

	it('stops waiting when the request is aborted', async () => {
		const controller = new AbortController();
		const fetchMock = vi.fn().mockResolvedValue(response(502));
		vi.stubGlobal('fetch', fetchMock);
		const pending = fetchRidingRestart('/x', { signal: controller.signal });
		await Promise.resolve();
		controller.abort();
		await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});
});

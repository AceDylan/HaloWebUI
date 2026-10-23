// 开始制作 from a phone: the response can be lost while the server goes on. The request is
// asked once more with the same key, which the server answers with the task already started.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/constants', () => ({ WEBUI_API_BASE_URL: '/api/v1' }));

import { startVideoTask } from './index';

const form = { brief: '请制作一个视频', idea: '番茄', files: [], maker: '', client_key: 'click-1' };
const task = { id: 'c1', chatId: 'c1', state: 'running' };

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('startVideoTask', () => {
	it('asks again with the same key when the response is lost', async () => {
		vi.useFakeTimers();
		const fetchMock = vi
			.fn()
			.mockRejectedValueOnce(new TypeError('Failed to fetch'))
			.mockResolvedValueOnce(
				new Response(JSON.stringify(task), { headers: { 'Content-Type': 'application/json' } })
			);
		vi.stubGlobal('fetch', fetchMock);
		const started = startVideoTask('t', form);
		await vi.advanceTimersByTimeAsync(1500);
		await expect(started).resolves.toEqual(task);
		expect(fetchMock).toHaveBeenCalledTimes(2);
		const bodies = fetchMock.mock.calls.map((call) => JSON.parse(call[1].body));
		expect(bodies.map((b) => b.client_key)).toEqual(['click-1', 'click-1']);
	});

	it('does not ask again when the server answered with an error', async () => {
		const fetchMock = vi.fn(
			async () =>
				new Response(JSON.stringify({ detail: '没有可用的 Hermes 模型' }), {
					status: 503,
					headers: { 'Content-Type': 'application/json' }
				})
		);
		vi.stubGlobal('fetch', fetchMock);
		await expect(startVideoTask('t', form)).rejects.toBeTruthy();
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});
});

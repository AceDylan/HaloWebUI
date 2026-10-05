import { describe, expect, it, vi } from 'vitest';

import {
	CONNECTION_LOST,
	IMAGE_STUDIO_PENDING_RUN_KEY,
	PENDING_RUN_MAX_AGE_MS,
	clearPendingImageRun,
	isImageRunInFlight,
	newImageRunId,
	readPendingImageRun,
	savePendingImageRun,
	sendSurvivingDisconnects,
	trackImageRun
} from './image-studio-run';

const memoryStorage = () => {
	const data = new Map<string, string>();
	return {
		getItem: (key: string) => data.get(key) ?? null,
		setItem: (key: string, value: string) => void data.set(key, value),
		removeItem: (key: string) => void data.delete(key),
		data
	};
};

const run = (id: string, startedAt = 1_000) => ({
	id,
	startedAt,
	payload: { prompt: 'a cat', client_request_id: id },
	record: { prompt: 'a cat', model: 'gpt-image', size: '1024x1536', parameters: {} }
});

describe('pending image studio run', () => {
	it('is kept until that run ends, and survives a reload', () => {
		const storage = memoryStorage();
		savePendingImageRun(storage, run('r1'));
		expect(readPendingImageRun(storage, 2_000)).toEqual(run('r1'));

		// A newer run started meanwhile is not cleared by the old one finishing.
		savePendingImageRun(storage, run('r2'));
		clearPendingImageRun(storage, 'r1');
		expect(readPendingImageRun(storage, 2_000)?.id).toBe('r2');
		clearPendingImageRun(storage, 'r2');
		expect(readPendingImageRun(storage, 2_000)).toBeNull();
	});

	it('is dropped once the server no longer keeps its result, or when unreadable', () => {
		const storage = memoryStorage();
		savePendingImageRun(storage, run('r1', 0));
		expect(readPendingImageRun(storage, PENDING_RUN_MAX_AGE_MS + 1)).toBeNull();
		expect(storage.data.has(IMAGE_STUDIO_PENDING_RUN_KEY)).toBe(false);

		storage.setItem(IMAGE_STUDIO_PENDING_RUN_KEY, '{not json');
		expect(readPendingImageRun(storage, 0)).toBeNull();
		storage.setItem(IMAGE_STUDIO_PENDING_RUN_KEY, JSON.stringify({ id: 'x' }));
		expect(readPendingImageRun(storage, 0)).toBeNull();
	});

	it('gets distinct ids', () => {
		expect(newImageRunId()).not.toBe(newImageRunId());
		expect(newImageRunId()).toMatch(/^[A-Za-z0-9_-]+$/);
	});
});

describe('sendSurvivingDisconnects', () => {
	it('asks again while the connection is lost, then returns the answer', async () => {
		const send = vi
			.fn()
			.mockRejectedValueOnce(CONNECTION_LOST)
			.mockRejectedValueOnce(CONNECTION_LOST)
			.mockResolvedValueOnce([{ url: '/img' }]);
		const waits: number[] = [];
		const result = await sendSurvivingDisconnects(send, {
			waitBeforeRetry: async (attempt) => void waits.push(attempt)
		});
		expect(result).toEqual([{ url: '/img' }]);
		expect(send).toHaveBeenCalledTimes(3);
		expect(waits).toEqual([1, 2]);
	});

	it('does not repeat a real error from the server', async () => {
		const send = vi.fn().mockRejectedValue('Upstream refused the prompt');
		await expect(sendSurvivingDisconnects(send, { waitBeforeRetry: async () => {} })).rejects.toBe(
			'Upstream refused the prompt'
		);
		expect(send).toHaveBeenCalledTimes(1);
	});

	it('gives up after the last attempt', async () => {
		const send = vi.fn().mockRejectedValue(CONNECTION_LOST);
		await expect(
			sendSurvivingDisconnects(send, { attempts: 3, waitBeforeRetry: async () => {} })
		).rejects.toBe(CONNECTION_LOST);
		expect(send).toHaveBeenCalledTimes(3);
	});
});

describe('trackImageRun', () => {
	it('marks the run as in flight until it ends, failed or not', async () => {
		let finish: () => void = () => {};
		const running = trackImageRun('r1', () => new Promise<void>((resolve) => (finish = resolve)));
		expect(isImageRunInFlight('r1')).toBe(true);
		expect(isImageRunInFlight('r2')).toBe(false);
		finish();
		await running;
		expect(isImageRunInFlight('r1')).toBe(false);

		await expect(trackImageRun('r3', () => Promise.reject('boom'))).rejects.toBe('boom');
		expect(isImageRunInFlight('r3')).toBe(false);
	});
});

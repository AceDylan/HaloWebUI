import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
	sendUpload: vi.fn(),
	getReusableFile: vi.fn()
}));
vi.mock('$lib/apis/files', () => api);

import {
	ANSWER_TIMEOUT_MS,
	MAX_ATTEMPTS,
	STALL_MS,
	UPLOAD_INTERRUPTED,
	isUploadCancelled,
	uploadFileReliably
} from './reliable-upload';

const file = () => new File(['same bytes'], 'a.png', { type: 'image/png' });
const DIGEST = '58100dc8fc06562ce3e578231dc948e083520ee49c4b4ee5a5a28bb4b4003feb'; // sha256 of 'same bytes'

// The tests run in node: a document that is only an event target with a visibility.
const fakeDocument = Object.assign(new EventTarget(), { visibilityState: 'visible' });
const setVisibility = (state: 'visible' | 'hidden') => {
	fakeDocument.visibilityState = state;
	fakeDocument.dispatchEvent(new Event('visibilitychange'));
};

// A request that reports progress and settles when told to.
const pendingRequest = () => {
	let resolve!: (value: unknown) => void;
	let reject!: (error: unknown) => void;
	let options: any;
	api.sendUpload.mockImplementationOnce((_token, _file, opts) => {
		options = opts;
		return new Promise((res, rej) => {
			resolve = res;
			reject = rej;
			opts.signal?.addEventListener('abort', () => rej(new TypeError('Upload aborted')));
		});
	});
	return {
		progress: (percent: number) => options.onProgress({ loaded: percent, total: 100, percent }),
		resolve: (value: unknown) => resolve(value),
		reject: (error: unknown) => reject(error),
		get options() {
			return options;
		}
	};
};

// Resolves once the upload has made `count` requests (after hashing the file, which takes
// real time: up to a few seconds on a busy CI machine). performance.now is not faked.
const sent = async (count = 1) => {
	const start = performance.now();
	while (api.sendUpload.mock.calls.length < count && performance.now() - start < 4_000) {
		await new Promise((resolve) => setImmediate(resolve));
	}
	expect(api.sendUpload).toHaveBeenCalledTimes(count);
};

beforeEach(() => {
	// setImmediate stays real: hashing the file is real async work (sent() waits on it).
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
	api.sendUpload.mockReset();
	api.getReusableFile.mockReset().mockResolvedValue(null);
	fakeDocument.visibilityState = 'visible';
	vi.stubGlobal('document', fakeDocument);
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('uploadFileReliably', () => {
	it('uses an earlier upload of the same bytes without sending anything', async () => {
		api.getReusableFile.mockResolvedValueOnce({ id: 'earlier' });
		const result = await uploadFileReliably('t', file(), { process: false });

		expect(result).toEqual({ file: { id: 'earlier' }, reused: true });
		expect(api.sendUpload).not.toHaveBeenCalled();
		const [, query] = api.getReusableFile.mock.calls[0];
		expect(query).toEqual({ sha256: DIGEST, size: 10, name: 'a.png', process: false, processingMode: undefined });
	});

	it('sends the file as reusable when there is no earlier upload', async () => {
		api.sendUpload.mockResolvedValueOnce({ id: 'new' });
		const result = await uploadFileReliably('t', file(), { process: true, processingMode: 'full_context' });

		expect(result).toEqual({ file: { id: 'new' }, reused: false });
		expect(api.sendUpload.mock.calls[0][2]).toMatchObject({
			process: true,
			processingMode: 'full_context',
			reuse: true
		});
	});

	it('waits for the page to come back after losing the connection, then sends again', async () => {
		const first = pendingRequest();
		const onRetry = vi.fn();
		const upload = uploadFileReliably('t', file(), { onRetry });
		await sent();

		setVisibility('hidden');
		first.reject(new TypeError('Failed to fetch'));
		const second = pendingRequest();
		await vi.advanceTimersByTimeAsync(60_000);
		expect(api.sendUpload).toHaveBeenCalledTimes(1); // nothing while in the background

		setVisibility('visible');
		await vi.advanceTimersByTimeAsync(2_000);
		expect(onRetry).toHaveBeenCalledWith(1);
		expect(api.sendUpload).toHaveBeenCalledTimes(2);
		second.resolve({ id: 'second' });

		await expect(upload).resolves.toEqual({ file: { id: 'second' }, reused: false });
	});

	it('does not send again when the lost request was in fact stored', async () => {
		const first = pendingRequest();
		const upload = uploadFileReliably('t', file());
		await sent();
		api.getReusableFile.mockResolvedValueOnce({ id: 'stored' });
		first.reject(new TypeError('Failed to fetch'));
		await vi.advanceTimersByTimeAsync(2_000);

		await expect(upload).resolves.toEqual({ file: { id: 'stored' }, reused: false });
		expect(api.sendUpload).toHaveBeenCalledTimes(1);
	});

	it('gives up on a request that stopped moving while the page is in front', async () => {
		const first = pendingRequest();
		const upload = uploadFileReliably('t', file());
		await sent();
		first.progress(40);
		const second = pendingRequest();

		await vi.advanceTimersByTimeAsync(STALL_MS + 2_000);
		expect(first.options.signal.aborted).toBe(true);
		await vi.advanceTimersByTimeAsync(2_000);
		expect(api.sendUpload).toHaveBeenCalledTimes(2);
		second.resolve({ id: 'second' });
		await expect(upload).resolves.toMatchObject({ file: { id: 'second' } });
	});

	it('does not count time in the background as a stall, only a short grace after it', async () => {
		const first = pendingRequest();
		const upload = uploadFileReliably('t', file());
		await sent();
		first.progress(10);

		setVisibility('hidden');
		await vi.advanceTimersByTimeAsync(5 * 60_000);
		expect(first.options.signal.aborted).toBe(false);

		setVisibility('visible');
		first.progress(11); // the connection survived
		await vi.advanceTimersByTimeAsync(STALL_MS - 4_000);
		expect(first.options.signal.aborted).toBe(false);
		first.resolve({ id: 'first' });
		await expect(upload).resolves.toMatchObject({ file: { id: 'first' } });
	});

	it('takes the stored file when the answer to a fully sent upload never comes', async () => {
		const first = pendingRequest();
		const upload = uploadFileReliably('t', file());
		await sent();
		first.progress(100);
		api.getReusableFile.mockResolvedValue({ id: 'stored' });

		setVisibility('hidden');
		setVisibility('visible');
		await expect(upload).resolves.toEqual({ file: { id: 'stored' }, reused: false });
		expect(first.options.signal.aborted).toBe(true);
	});

	it('sends a stored-only file again when its answer never comes and the server does not have it', async () => {
		const first = pendingRequest();
		const upload = uploadFileReliably('t', file(), { process: false });
		await sent();
		first.progress(100);
		const second = pendingRequest();

		await vi.advanceTimersByTimeAsync(ANSWER_TIMEOUT_MS.stored - 4_000);
		expect(first.options.signal.aborted).toBe(false);
		await vi.advanceTimersByTimeAsync(8_000);
		expect(first.options.signal.aborted).toBe(true);
		await vi.advanceTimersByTimeAsync(2_000);
		expect(api.sendUpload).toHaveBeenCalledTimes(2);
		second.resolve({ id: 'second' });
		await expect(upload).resolves.toMatchObject({ file: { id: 'second' } });
	});

	it('gives a document the server is reading much longer before sending it again', async () => {
		const first = pendingRequest();
		const upload = uploadFileReliably('t', file(), { process: true });
		await sent();
		first.progress(100);
		await vi.advanceTimersByTimeAsync(ANSWER_TIMEOUT_MS.processed - 4_000);
		expect(first.options.signal.aborted).toBe(false);
		first.resolve({ id: 'read' });
		await expect(upload).resolves.toMatchObject({ file: { id: 'read' } });
	});

	it('fails at once on an error the server answered with', async () => {
		api.sendUpload.mockRejectedValueOnce({ status: 400, detail: 'File type exe is not allowed' });
		await expect(uploadFileReliably('t', file())).rejects.toMatchObject({ status: 400 });
		expect(api.sendUpload).toHaveBeenCalledTimes(1);
	});

	it(`reports the upload as interrupted after ${MAX_ATTEMPTS} lost connections`, async () => {
		api.sendUpload.mockRejectedValue(new TypeError('Failed to fetch'));
		const upload = uploadFileReliably('t', file());
		const outcome = expect(upload).rejects.toBe(UPLOAD_INTERRUPTED);
		await sent();
		await vi.advanceTimersByTimeAsync(60_000);
		await outcome;
		expect(api.sendUpload).toHaveBeenCalledTimes(MAX_ATTEMPTS);
	});

	it('stops when cancelled, also while waiting for the page', async () => {
		const first = pendingRequest();
		const controller = new AbortController();
		const upload = uploadFileReliably('t', file(), { signal: controller.signal });
		const outcome = upload.catch((error) => error);
		await sent();
		setVisibility('hidden');
		first.reject(new TypeError('Failed to fetch'));
		await vi.advanceTimersByTimeAsync(5_000);

		controller.abort();
		expect(isUploadCancelled(await outcome)).toBe(true);
		expect(api.sendUpload).toHaveBeenCalledTimes(1);
	});
});

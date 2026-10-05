// Uploads that survive a phone putting the page in the background, and files that were
// uploaded before not being sent again.
//
// A mobile browser that hides the page (another app, the screen locked) cuts or freezes
// its connections: the request fails, or hangs at some percent and never moves again. So
// a failure without an answer from the server, or no progress for STALL_MS while the page
// is in front, is not the end: once the page is visible and online again the file is
// sent again (up to MAX_ATTEMPTS times). So is a fully sent file whose answer does not come
// (ANSWER_TIMEOUT_MS), once the lookup below says the server does not have it.
//
// The file's SHA-256 is computed first. If this user has already uploaded the same bytes
// the same way, that file is used and nothing is sent. The same lookup answers "did the
// server finish the request we lost?" before sending again, and while the server is still
// working on a file whose answer may never arrive.

import { getReusableFile, sendUpload, type UploadProgress } from '$lib/apis/files';

/** Larger files are uploaded without the lookup (hashing reads the whole file into memory). */
export const MAX_HASH_BYTES = 256 * 1024 * 1024;
export const MAX_ATTEMPTS = 5;
/** No progress for this long while the page is visible: the connection is dead. */
export const STALL_MS = 30_000;
/** After the page comes back, how long a frozen request gets to show progress. */
export const RESUME_GRACE_MS = 8_000;
/** How often to ask whether a fully sent file has been stored, while waiting for the answer. */
export const FINISHED_CHECK_MS = 15_000;
/** A fully sent file with no answer after this long in front is sent again. Documents are
 * read (and embedded) by the server before it answers; other files are only stored. */
export const ANSWER_TIMEOUT_MS = { processed: 5 * 60_000, stored: 60_000 };
const TICK_MS = 2_000;

const RETRYABLE_STATUSES = new Set([408, 502, 503, 504]);

export type ReliableUploadOptions = {
	process?: boolean;
	processingMode?: string;
	onProgress?: (progress: UploadProgress) => void;
	/** The file is being sent again (progress starts over). */
	onRetry?: (attempt: number) => void;
	/** Stops the upload and any waiting; the promise rejects with an UploadCancelled. */
	signal?: AbortSignal;
};

export type ReliableUploadResult = {
	file: any;
	/** An earlier upload of the same file: nothing was sent, and it is not this upload's to delete. */
	reused: boolean;
};

export class UploadCancelled extends Error {
	constructor() {
		super('Upload cancelled');
		this.name = 'UploadCancelled';
	}
}

class UploadStalled extends Error {}

/** What the upload fails with when every attempt lost the connection (a file-upload diagnostic). */
export const UPLOAD_INTERRUPTED = {
	code: 'upload_interrupted',
	title: 'Upload interrupted',
	message: 'The connection dropped before the file was sent.',
	blocking: true
};

export const isUploadCancelled = (error: unknown) => error instanceof UploadCancelled;

/** No answer from the server (network gone, request frozen) or a gateway giving up. */
export const isRetryableUploadError = (error: unknown) => {
	if (error instanceof TypeError || error instanceof UploadStalled) return true;
	const status = (error as { status?: unknown } | null)?.status;
	return typeof status === 'number' && RETRYABLE_STATUSES.has(status);
};

const pageInFront = () =>
	(typeof document === 'undefined' || document.visibilityState !== 'hidden') &&
	(typeof navigator === 'undefined' || navigator.onLine !== false);

const toHex = (buffer: ArrayBuffer) =>
	Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, '0')).join('');

export const hashFile = async (file: Blob): Promise<string | null> => {
	const subtle = globalThis.crypto?.subtle;
	if (!subtle || file.size > MAX_HASH_BYTES) return null;
	try {
		return toHex(await subtle.digest('SHA-256', await file.arrayBuffer()));
	} catch {
		return null;
	}
};

const listen = (target: EventTarget | undefined, type: string, handler: () => void) => {
	target?.addEventListener(type, handler);
	return () => target?.removeEventListener(type, handler);
};

const pageTargets = () => ({
	doc: typeof document === 'undefined' ? undefined : document,
	win: typeof window === 'undefined' ? undefined : window
});

// Resolves once the page is visible and online, after at least `delayMs`.
const waitForPage = (delayMs: number, signal?: AbortSignal) =>
	new Promise<void>((resolve, reject) => {
		const { doc, win } = pageTargets();
		let delayed = false;
		const check = () => {
			if (delayed && pageInFront()) done(resolve);
		};
		const stops = [
			listen(doc, 'visibilitychange', check),
			listen(win, 'online', check),
			listen(signal, 'abort', () => done(() => reject(new UploadCancelled())))
		];
		// Some browsers miss the events when a frozen page wakes up.
		const poll = setInterval(check, 2_000);
		const timer = setTimeout(() => {
			delayed = true;
			check();
		}, delayMs);
		function done(settle: () => void) {
			clearInterval(poll);
			clearTimeout(timer);
			stops.forEach((stop) => stop());
			settle();
		}
		if (signal?.aborted) done(() => reject(new UploadCancelled()));
	});

// One request, given up when it stops moving while the page is in front. Once every byte
// is out, the server's answer is waited for, but if `lookup` finds the stored file first
// (the answer was lost with the connection), that is the result; with no answer after
// ANSWER_TIMEOUT_MS in front, the request is given up as well.
const sendOnce = (
	token: string,
	file: File,
	options: ReliableUploadOptions,
	lookup: (() => Promise<any | null>) | null
) =>
	new Promise<any>((resolve, reject) => {
		const controller = new AbortController();
		const { doc } = pageTargets();
		let lastActivity = Date.now();
		let sent = false;
		// Time spent waiting for the answer with the page in front.
		let answerWait = 0;
		const answerTimeout = ANSWER_TIMEOUT_MS[options.process === false ? 'stored' : 'processed'];
		let settled = false;
		let checking = false;

		const settle = (fn: () => void) => {
			if (settled) return;
			settled = true;
			clearInterval(watchdog);
			stops.forEach((stop) => stop());
			fn();
		};

		// Time in the background does not count: when the page comes back, the request
		// has RESUME_GRACE_MS to move before it is given up.
		const clampToGrace = () => {
			lastActivity = Math.max(lastActivity, Date.now() - (STALL_MS - RESUME_GRACE_MS));
		};

		const checkFinished = async () => {
			if (!lookup || checking || settled) return;
			checking = true;
			const stored = await lookup();
			checking = false;
			if (stored)
				settle(() => {
					controller.abort();
					resolve(stored);
				});
		};

		const tick = () => {
			if (!pageInFront()) return clampToGrace();
			if (sent) answerWait += TICK_MS;
			if (sent ? answerWait > answerTimeout : Date.now() - lastActivity > STALL_MS) {
				settle(() => {
					controller.abort();
					reject(new UploadStalled('Upload stalled'));
				});
			} else if (sent && Date.now() - lastActivity > FINISHED_CHECK_MS) {
				lastActivity = Date.now();
				void checkFinished();
			}
		};

		const stops = [
			listen(doc, 'visibilitychange', () => {
				if (!pageInFront()) return;
				clampToGrace();
				if (sent) void checkFinished();
			}),
			listen(options.signal, 'abort', () =>
				settle(() => {
					controller.abort();
					reject(new UploadCancelled());
				})
			)
		];
		const watchdog = setInterval(tick, TICK_MS);

		if (options.signal?.aborted) {
			settle(() => reject(new UploadCancelled()));
			return;
		}

		sendUpload(token, file, {
			process: options.process,
			processingMode: options.processingMode,
			reuse: true,
			signal: controller.signal,
			onProgress: (progress) => {
				lastActivity = Date.now();
				if (progress.percent >= 100) sent = true;
				options.onProgress?.(progress);
			}
		}).then(
			(result) => settle(() => resolve(result)),
			(error) => settle(() => reject(error))
		);
	});

export const uploadFileReliably = async (
	token: string,
	file: File,
	options: ReliableUploadOptions = {}
): Promise<ReliableUploadResult> => {
	const { signal } = options;
	const process = options.process ?? true;
	const sha256 = await hashFile(file);
	if (signal?.aborted) throw new UploadCancelled();

	const lookup = sha256
		? () =>
				getReusableFile(token, {
					sha256,
					size: file.size,
					name: file.name,
					process,
					processingMode: options.processingMode
				})
		: null;

	const earlier = lookup ? await lookup() : null;
	if (signal?.aborted) throw new UploadCancelled();
	if (earlier) return { file: earlier, reused: true };

	// From here on, a file found by the lookup is the one this upload stored.
	for (let attempt = 1; ; attempt++) {
		try {
			return { file: await sendOnce(token, file, { ...options, process }, lookup), reused: false };
		} catch (error) {
			if (signal?.aborted || isUploadCancelled(error)) throw new UploadCancelled();
			if (!isRetryableUploadError(error)) throw error;
			if (attempt >= MAX_ATTEMPTS) throw UPLOAD_INTERRUPTED;
		}

		await waitForPage(Math.min(1_000 * 2 ** (attempt - 1), 10_000), signal);
		const stored = lookup ? await lookup() : null;
		if (signal?.aborted) throw new UploadCancelled();
		if (stored) return { file: stored, reused: false };
		options.onRetry?.(attempt);
	}
};

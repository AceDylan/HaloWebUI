/**
 * A deploy recreates the container; for 10-60 s nginx answers 502 and opening a
 * chat in that window used to fail and send the page back to a new chat. Reads
 * that the page cannot do without wait the restart out instead.
 */
export const RESTART_STATUSES = new Set([502, 503, 504]);
// ≈ 61 s in all: longer than every deploy window seen so far.
export const RESTART_RETRY_DELAYS_MS = [1000, 2000, 3000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000];

type Options = {
	delays?: number[];
	sleep?: (ms: number, signal?: AbortSignal | null) => Promise<void>;
	online?: () => boolean;
};

const abortError = () => new DOMException('The operation was aborted.', 'AbortError');

const defaultSleep = (ms: number, signal?: AbortSignal | null) =>
	new Promise<void>((resolve, reject) => {
		if (signal?.aborted) return reject(abortError());
		const timer = setTimeout(() => {
			signal?.removeEventListener('abort', onAbort);
			resolve();
		}, ms);
		const onAbort = () => {
			clearTimeout(timer);
			reject(abortError());
		};
		signal?.addEventListener('abort', onAbort, { once: true });
	});

// An offline phone fails at once as before; only a server that is away is waited for.
const defaultOnline = () => typeof navigator === 'undefined' || navigator.onLine !== false;

/** `fetch` for a GET that rides out a server restart (502/503/504 or a refused connection). */
export const fetchRidingRestart = async (
	input: RequestInfo | URL,
	init: RequestInit = {},
	{ delays = RESTART_RETRY_DELAYS_MS, sleep = defaultSleep, online = defaultOnline }: Options = {}
): Promise<Response> => {
	for (let attempt = 0; ; attempt++) {
		const last = attempt >= delays.length;
		try {
			const res = await fetch(input, init);
			if (last || !RESTART_STATUSES.has(res.status)) return res;
		} catch (error) {
			const aborted = init.signal?.aborted || (error as Error)?.name === 'AbortError';
			if (last || aborted || !(error instanceof TypeError) || !online()) throw error;
		}
		await sleep(delays[attempt], init.signal);
	}
};

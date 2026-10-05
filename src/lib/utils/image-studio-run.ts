// A workbench generation that outlives a dropped connection.
//
// A phone that locks its screen or switches apps while an image is being made
// (60–150 s through cch) loses the connection. The page then showed "Server
// connection failed" although the server went on and made the image, and the
// browser sometimes re-sent the POST by itself, so one picture cost two
// upstream generations. Each run now carries an id (`client_request_id`): the
// server runs an id once and hands a repeat the same result
// (routers/images.py `_run_image_generation_once`). The workbench keeps the
// unfinished run here, asks again with the same id when the connection is
// lost, and picks the run up again if the page itself was reloaded.

export const IMAGE_STUDIO_PENDING_RUN_KEY = 'workspace:image-studio:pending-run:v1';

// Keep in sync with _IMAGE_RUN_KEEP_SECONDS in backend/open_webui/routers/images.py.
export const PENDING_RUN_MAX_AGE_MS = 30 * 60 * 1000;

// What imageGenerations throws when no HTTP response arrived at all.
export const CONNECTION_LOST = 'Server connection failed';

export type PendingImageRun<P, R> = {
	id: string;
	startedAt: number;
	// The request body, sent again unchanged.
	payload: P;
	// What the gallery and history entries are written from.
	record: R;
};

type KeyValueStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export const newImageRunId = (): string =>
	globalThis.crypto?.randomUUID?.() ??
	`${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;

export const savePendingImageRun = <P, R>(storage: KeyValueStorage, run: PendingImageRun<P, R>) => {
	try {
		storage.setItem(IMAGE_STUDIO_PENDING_RUN_KEY, JSON.stringify(run));
	} catch {
		// Full or blocked storage: the run still works, it just cannot be resumed after a reload.
	}
};

export const readPendingImageRun = <P, R>(
	storage: KeyValueStorage,
	now: number = Date.now()
): PendingImageRun<P, R> | null => {
	try {
		const run = JSON.parse(storage.getItem(IMAGE_STUDIO_PENDING_RUN_KEY) || 'null');
		if (
			run &&
			typeof run.id === 'string' &&
			run.id &&
			typeof run.startedAt === 'number' &&
			run.payload &&
			run.record &&
			now - run.startedAt < PENDING_RUN_MAX_AGE_MS
		) {
			return run;
		}
		if (run) storage.removeItem(IMAGE_STUDIO_PENDING_RUN_KEY);
	} catch {
		// Unreadable: nothing to resume.
	}
	return null;
};

// Only the run that finished is removed: a newer one started meanwhile stays.
export const clearPendingImageRun = (storage: KeyValueStorage, id: string) => {
	try {
		const raw = storage.getItem(IMAGE_STUDIO_PENDING_RUN_KEY);
		if (raw && JSON.parse(raw)?.id === id) storage.removeItem(IMAGE_STUDIO_PENDING_RUN_KEY);
	} catch {
		// Nothing to clear.
	}
};

// Runs this page is still waiting for. The workbench opened again mid-run
// (left for a chat and come back) must not send and record that run a second
// time: the first workbench still records it when it ends.
const runsInFlight = new Set<string>();

export const isImageRunInFlight = (id: string) => runsInFlight.has(id);

export const trackImageRun = async <T>(id: string, work: () => Promise<T>): Promise<T> => {
	runsInFlight.add(id);
	try {
		return await work();
	} finally {
		runsInFlight.delete(id);
	}
};

// Resolves once the page is in the foreground again: a locked phone cannot reconnect.
const pageVisible = () =>
	new Promise<void>((resolve) => {
		if (typeof document === 'undefined' || !document.hidden) return resolve();
		const onChange = () => {
			if (document.hidden) return;
			document.removeEventListener('visibilitychange', onChange);
			resolve();
		};
		document.addEventListener('visibilitychange', onChange);
	});

const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// Sends the request again while the connection keeps getting lost (the server
// joins the repeats to the one run), up to `attempts` times in all. Any real
// answer — an image or an error from the server — ends it.
export const sendSurvivingDisconnects = async <T>(
	send: () => Promise<T>,
	{
		attempts = 5,
		waitBeforeRetry = async (attempt: number) => {
			await pageVisible();
			await pause(1500 * attempt);
		}
	}: { attempts?: number; waitBeforeRetry?: (attempt: number) => Promise<void> } = {}
): Promise<T> => {
	for (let attempt = 1; ; attempt += 1) {
		try {
			return await send();
		} catch (error) {
			if (error !== CONNECTION_LOST || attempt >= attempts) throw error;
			await waitBeforeRetry(attempt);
		}
	}
};

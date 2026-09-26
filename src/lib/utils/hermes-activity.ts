import { get } from 'svelte/store';

import {
	getHermesActivity,
	HermesSessionExpiredError,
	markHermesChatRead,
	type HermesActiveRun
} from '$lib/apis/hermes';
import { chatId, hermesActiveRuns, hermesBackgroundRuns, hermesUnreadChatIds } from '$lib/stores';

/**
 * The one poll of the signed-in user's hermes activity (runs executing, the
 * background runners they launched, chats finished but not opened), feeding
 * the stores the sidebar, the chat banner, the composer and the tab title
 * read. It lives with the page, not the sidebar: the sidebar list unmounts
 * while searching or in an assistant scene, and the poll used to stop with it.
 *
 * A hidden tab polls slower instead of not at all - the tab's "⏳ 待审批" and
 * "✓" marks exist for exactly the time nobody is looking - and socket events
 * update the stores at once (applyHermesChatEvent) so they do not wait for
 * the next poll.
 */
export const HERMES_ACTIVITY_POLL_MS = 10_000;
export const HERMES_ACTIVITY_HIDDEN_POLL_MS = 30_000;
const SOON_MS = 800;

type PollerOptions = {
	/** Called once when the token stops being accepted. */
	onSessionExpired?: () => void;
};

let timer: ReturnType<typeof setTimeout> | null = null;
let soonTimer: ReturnType<typeof setTimeout> | null = null;
let running = false;
let inFlight: Promise<void> | null = null;
let refreshAgain = false;
// Set once the token stops being accepted: polling stops (a tab left open
// overnight otherwise sends a failing request every few seconds) and the
// indicators are cleared instead of showing a stale "running". Showing the tab
// again retries once, which picks up a sign-in made in another tab.
let sessionExpired = false;
let options: PollerOptions = {};

const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';

const schedule = () => {
	if (timer) clearTimeout(timer);
	timer = null;
	if (!running || sessionExpired) return;
	timer = setTimeout(
		() => void refreshHermesActivity(),
		hidden() ? HERMES_ACTIVITY_HIDDEN_POLL_MS : HERMES_ACTIVITY_POLL_MS
	);
};

const clearStores = () => {
	hermesActiveRuns.set([]);
	hermesBackgroundRuns.set([]);
	hermesUnreadChatIds.set(new Set());
};

const fetchOnce = async () => {
	let activity;
	try {
		activity = await getHermesActivity(localStorage.token);
	} catch (error) {
		if (error instanceof HermesSessionExpiredError && !sessionExpired) {
			sessionExpired = true;
			clearStores();
			options.onSessionExpired?.();
		}
		return;
	}
	sessionExpired = false;
	if (!running) return;
	hermesActiveRuns.set(activity.runs);
	hermesBackgroundRuns.set(activity.background);
	const unread = new Set(activity.unread);
	// The chat on screen is read by definition; clear it server-side too. Not
	// from a hidden tab: nobody is looking, and marking it read there took the
	// "finished" dot off the phone and the other tabs too. Showing the tab
	// again refreshes, and that refresh marks it read.
	const current = get(chatId);
	if (current && unread.has(current) && !hidden()) {
		unread.delete(current);
		markHermesChatRead(localStorage.token, current).catch(() => {});
	}
	hermesUnreadChatIds.set(unread);
};

/** Fetch now (one request at a time; a call during one runs once more after it). */
export const refreshHermesActivity = async (): Promise<void> => {
	if (!running) return;
	if (inFlight) {
		refreshAgain = true;
		return inFlight;
	}
	inFlight = (async () => {
		try {
			do {
				refreshAgain = false;
				await fetchOnce();
			} while (refreshAgain && running && !sessionExpired);
		} finally {
			inFlight = null;
			schedule();
		}
	})();
	return inFlight;
};

/** A refresh shortly, folding a burst of events into one request. */
export const refreshHermesActivitySoon = (delayMs = SOON_MS) => {
	if (!running || sessionExpired) return;
	if (soonTimer) clearTimeout(soonTimer);
	soonTimer = setTimeout(() => {
		soonTimer = null;
		void refreshHermesActivity();
	}, delayMs);
};

const onVisibilityChange = () => {
	if (hidden()) {
		schedule();
		return;
	}
	void refreshHermesActivity();
};

/** Start polling (idempotent); returns the stop function. */
export const startHermesActivityPolling = (pollerOptions: PollerOptions = {}) => {
	options = pollerOptions;
	if (!running) {
		running = true;
		sessionExpired = false;
		if (typeof document !== 'undefined') {
			document.addEventListener('visibilitychange', onVisibilityChange);
		}
		void refreshHermesActivity();
	}
	return stopHermesActivityPolling;
};

export const stopHermesActivityPolling = () => {
	running = false;
	if (timer) clearTimeout(timer);
	if (soonTimer) clearTimeout(soonTimer);
	timer = null;
	soonTimer = null;
	if (typeof document !== 'undefined') {
		document.removeEventListener('visibilitychange', onVisibilityChange);
	}
};

type ChatEvent = {
	chat_id?: string;
	message_id?: string;
	data?: { type?: string; data?: Record<string, any> | null } | null;
};

/**
 * Apply what a chat socket event says about hermes activity right away:
 * a run's end (`chat:completion` with `hermes_run.active === false`), an
 * approval request and its answer. The poll that follows confirms it.
 */
export const applyHermesChatEvent = (event: ChatEvent | null | undefined) => {
	const type = event?.data?.type ?? null;
	const data = event?.data?.data ?? null;
	const eventChatId = event?.chat_id ?? '';
	if (!type || !eventChatId) return;

	if (type === 'chat:completion') {
		const run = data?.hermes_run;
		if (!run || typeof run !== 'object' || run.active !== false) return;
		let removed = false;
		hermesActiveRuns.update((runs) => {
			const next = runs.filter(
				(item) =>
					!(item.chat_id === eventChatId && (!run.run_id || item.run_id === run.run_id))
			);
			removed = next.length !== runs.length;
			return removed ? next : runs;
		});
		if (removed && (eventChatId !== get(chatId) || hidden())) {
			hermesUnreadChatIds.update((ids) =>
				ids.has(eventChatId) ? ids : new Set([...ids, eventChatId])
			);
		}
		refreshHermesActivitySoon();
		return;
	}

	if (type === 'hermes:approval') {
		const approval = {
			request_id: data?.request_id,
			command: data?.command,
			description: data?.description,
			since: data?.requested_at
		};
		hermesActiveRuns.update((runs) => {
			const index = runs.findIndex((item) => item.chat_id === eventChatId);
			if (index >= 0) {
				if (runs[index].awaiting_approval && runs[index].approval?.request_id === approval.request_id) {
					return runs;
				}
				const next = [...runs];
				next[index] = { ...runs[index], awaiting_approval: true, approval };
				return next;
			}
			// The run started after the last poll: known from this event alone.
			const entry: HermesActiveRun = {
				chat_id: eventChatId,
				message_id: event?.message_id ?? '',
				run_id: String(data?.run_id ?? ''),
				started_at: Number(data?.requested_at) || Date.now() / 1000,
				steers: 0,
				title: null,
				awaiting_approval: true,
				approval
			};
			return [...runs, entry];
		});
		refreshHermesActivitySoon();
		return;
	}

	if (type === 'hermes:approval:resolved') {
		hermesActiveRuns.update((runs) => {
			let changed = false;
			const next = runs.map((item) => {
				if (
					item.awaiting_approval &&
					(item.approval?.request_id === data?.request_id || item.chat_id === eventChatId)
				) {
					changed = true;
					return { ...item, awaiting_approval: false, approval: null };
				}
				return item;
			});
			return changed ? next : runs;
		});
		refreshHermesActivitySoon();
		return;
	}

	if (type === 'chat:reload' && data?.reason === 'hermes_notification') {
		// A background runner delivered its report: it is no longer running.
		refreshHermesActivitySoon();
	}
};

/** Test hook: forget all module state. */
export const __resetHermesActivityForTests = () => {
	stopHermesActivityPolling();
	inFlight = null;
	refreshAgain = false;
	sessionExpired = false;
	options = {};
};

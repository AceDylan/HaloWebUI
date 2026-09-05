import { WEBUI_API_BASE_URL } from '$lib/constants';

export type HermesActiveRun = {
	chat_id: string;
	message_id: string;
	run_id: string;
	started_at: number;
	steers: number;
	title: string | null;
};

const jsonHeaders = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

/**
 * Inject guidance into the hermes run currently streaming in `chatId`.
 * Resolves null when nothing steerable is running there (no hermes run, run
 * already finishing, other model), so the caller can fall back to queueing.
 */
export const steerHermesRun = async (
	token: string,
	chatId: string,
	text: string
): Promise<{ accepted: boolean; run_id: string } | null> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/steer`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify({ chat_id: chatId, text })
	});
	if (!res.ok) {
		return null;
	}
	return await res.json();
};

/** The signed-in user's hermes runs that are executing right now. */
export const getActiveHermesRuns = async (token: string): Promise<HermesActiveRun[]> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/runs`, {
		method: 'GET',
		headers: jsonHeaders(token)
	});
	if (!res.ok) {
		return [];
	}
	const data = await res.json();
	return Array.isArray(data?.runs) ? data.runs : [];
};

export type HermesSession = {
	id: string;
	source: string;
	title: string;
	preview: string;
	message_count: number;
	started_at: number | string | null;
	last_active: number | string | null;
	model: string | null;
	imported: boolean;
};

const detailOf = async (res: Response) => {
	const body = await res.json().catch(() => ({}));
	return body?.detail ?? `${res.status} ${res.statusText}`;
};

/** hermes sessions from another surface (telegram | qqbot | cli), newest first. */
export const getHermesSessions = async (
	token: string,
	source = 'telegram',
	limit = 50
): Promise<HermesSession[]> => {
	const params = new URLSearchParams({ source, limit: `${limit}` });
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/sessions?${params}`, {
		method: 'GET',
		headers: jsonHeaders(token)
	});
	if (!res.ok) {
		throw await detailOf(res);
	}
	const data = await res.json();
	return Array.isArray(data?.sessions) ? data.sessions : [];
};

/**
 * Import a hermes session as a chat (id = session id, so the chat continues
 * that session). Idempotent: an already-imported session returns its chat.
 */
export const importHermesSession = async (
	token: string,
	sessionId: string
): Promise<{ chat_id: string; title: string; created: boolean; imported_turns: number }> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/hermes/sessions/${encodeURIComponent(sessionId)}/import`,
		{
			method: 'POST',
			headers: jsonHeaders(token),
			body: JSON.stringify({})
		}
	);
	if (!res.ok) {
		throw await detailOf(res);
	}
	return await res.json();
};

/**
 * Push one test message through the notification webhook: the URL given here
 * (the unsaved form value) first, the saved one otherwise.
 */
export const testNotificationWebhook = async (
	token: string,
	url: string
): Promise<{ status: boolean }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/webhook-test`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify({ url })
	});
	if (!res.ok) {
		throw await detailOf(res);
	}
	return await res.json();
};

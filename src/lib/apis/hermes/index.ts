import { WEBUI_API_BASE_URL } from '$lib/constants';

export type HermesActiveRunApproval = {
	request_id?: string;
	command?: string;
	description?: string;
	since?: number;
};

export type HermesActiveRun = {
	chat_id: string;
	message_id: string;
	run_id: string;
	started_at: number;
	steers: number;
	title: string | null;
	/** The run is paused on a command approval nobody has answered yet. */
	awaiting_approval?: boolean;
	approval?: HermesActiveRunApproval | null;
};

const jsonHeaders = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

export class HermesSteerError extends Error {
	status: number;
	detail: string;

	constructor(status: number, detail: string) {
		super(detail);
		this.name = 'HermesSteerError';
		this.status = status;
		this.detail = detail;
	}

	/** 404: no run is registered for the chat (it finished, or the server restarted). */
	get runEnded(): boolean {
		return this.status === 404 || this.status === 409;
	}
}

/**
 * Inject guidance into the hermes run currently streaming in `chatId`.
 * Throws a HermesSteerError when hermes did not take the text: 404 when no
 * run is active for the chat, 409 when the run stopped accepting input, so
 * the caller can tell the person instead of silently doing something else.
 */
export const steerHermesRun = async (
	token: string,
	chatId: string,
	text: string
): Promise<{ accepted: boolean; run_id: string }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/steer`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify({ chat_id: chatId, text })
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		const detail =
			typeof body?.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`;
		throw new HermesSteerError(res.status, detail);
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

export type HermesActivity = { runs: HermesActiveRun[]; unread: string[] };

/**
 * Runs executing now plus the chats whose run finished and has not been opened
 * since — one poll feeds both sidebar indicators.
 */
export const getHermesActivity = async (token: string): Promise<HermesActivity> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/runs`, { headers: jsonHeaders(token) });
	if (!res.ok) {
		throw await detailOf(res);
	}
	const data = await res.json();
	return {
		runs: Array.isArray(data?.runs) ? data.runs : [],
		unread: Array.isArray(data?.unread) ? data.unread : []
	};
};

/** Opening a chat clears the unread mark its finished hermes run left. */
export const markHermesChatRead = async (token: string, chatId: string): Promise<void> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/hermes/chats/${encodeURIComponent(chatId)}/read`,
		{ method: 'POST', headers: jsonHeaders(token) }
	);
	if (!res.ok) {
		throw await detailOf(res);
	}
};

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

export type HermesSessionPage = {
	sessions: HermesSession[];
	/** The hermes offset this page stopped at; pass it back to read the next one. */
	next_offset: number;
	has_more: boolean;
};

/**
 * One page of hermes sessions from another surface (telegram | qqbot | cli),
 * newest first.
 *
 * Cursor paging, not page numbers: hermes reports no total for a source, so
 * there is nothing to build a numbered pager from. Start at offset 0 and walk
 * forward with the `next_offset` each answer carries, while `has_more` holds.
 */
export const getHermesSessions = async (
	token: string,
	source = 'telegram',
	{ limit = 20, offset = 0 }: { limit?: number; offset?: number } = {}
): Promise<HermesSessionPage> => {
	const params = new URLSearchParams({
		source,
		limit: `${limit}`,
		offset: `${offset}`
	});
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/sessions?${params}`, {
		method: 'GET',
		headers: jsonHeaders(token)
	});
	if (!res.ok) {
		throw await detailOf(res);
	}
	const data = await res.json();
	const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
	return {
		sessions,
		// An older backend answers `{sessions}` alone: treat that as the one
		// page it is instead of paging past the end of it.
		next_offset:
			typeof data?.next_offset === 'number' ? data.next_offset : offset + sessions.length,
		has_more: data?.has_more === true
	};
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

/** A background runner (reclaude / codex / agy) as its last progress report described it. */
export type HermesBackgroundRun = {
	run_id: string;
	chat_id: string;
	agent: string;
	status: string;
	started_at: number | null;
	step: number | null;
	last_activity: string;
	updated_at: number;
	title?: string | null;
};

export type HermesActivity = {
	runs: HermesActiveRun[];
	unread: string[];
	background: HermesBackgroundRun[];
};

/** The sign-in behind the token is gone (a framed Hub session lasts 12h). */
export class HermesSessionExpiredError extends Error {
	constructor() {
		super('session expired');
		this.name = 'HermesSessionExpiredError';
	}
}

/**
 * Runs executing now plus the chats whose run finished and has not been opened
 * since — one poll feeds both sidebar indicators.
 */
export const getHermesActivity = async (token: string): Promise<HermesActivity> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/runs`, { headers: jsonHeaders(token) });
	if (res.status === 401) {
		throw new HermesSessionExpiredError();
	}
	if (!res.ok) {
		throw await detailOf(res);
	}
	const data = await res.json();
	return {
		runs: Array.isArray(data?.runs) ? data.runs : [],
		unread: Array.isArray(data?.unread) ? data.unread : [],
		background: Array.isArray(data?.background) ? data.background : []
	};
};

/** Opening a chat clears the unread mark its finished hermes run left. */
export const markHermesChatRead = async (token: string, chatId: string): Promise<void> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/chats/${encodeURIComponent(chatId)}/read`, {
		method: 'POST',
		headers: jsonHeaders(token)
	});
	if (!res.ok) {
		throw await detailOf(res);
	}
};

export type HermesRunnerStopResult = {
	stopped: boolean;
	run_id: string;
	agent: string;
	chat_id: string;
	/** False when a hermes turn was running in the chat, so no "已停止" line was added. */
	report_shown: boolean;
	resumable?: boolean;
};

/** Stop a background runner (reclaude / codex / agy) one of the user's chats launched. */
export const stopHermesBackgroundRunner = async (
	token: string,
	runId: string
): Promise<HermesRunnerStopResult> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/hermes/runners/${encodeURIComponent(runId)}/stop`,
		{ method: 'POST', headers: jsonHeaders(token) }
	);
	if (!res.ok) {
		throw await detailOf(res);
	}
	return res.json();
};

export type HermesModelProvider = {
	slug: string;
	name: string;
	current: boolean;
	models: string[];
};

export type HermesModelOptions = {
	/** hermes' configured default model and provider. */
	model: string;
	provider: string;
	providers: HermesModelProvider[];
	/** The Message Gateway thinking level hermes applies to every model request. */
	reasoning_effort?: string;
};

/** The models hermes can run a chat with, grouped by provider. */
export const getHermesModelOptions = async (token: string): Promise<HermesModelOptions> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/model-options`, {
		method: 'GET',
		headers: jsonHeaders(token)
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(body?.detail ?? `HTTP ${res.status}`);
	}
	return res.json();
};

// ---- 定时任务 (hermes cron jobs; admin only) ----

export type HermesJobSchedule = {
	kind: 'cron' | 'interval' | 'once' | string;
	expr?: string;
	minutes?: number;
	run_at?: string;
	display?: string;
};

export type HermesJob = {
	id: string;
	name: string;
	prompt: string;
	/** A script job runs this file under ~/.hermes/scripts without a model turn (no_agent). */
	script: string | null;
	no_agent: boolean;
	skills: string[] | null;
	schedule: HermesJobSchedule;
	schedule_display: string | null;
	repeat: { times: number | null; completed: number } | null;
	enabled: boolean;
	/** scheduled | paused | running | completed */
	state: string;
	paused_reason: string | null;
	created_at: string | null;
	next_run_at: string | null;
	last_run_at: string | null;
	/** ok | error | null (never ran) */
	last_status: string | null;
	last_error: string | null;
	last_delivery_error: string | null;
	/** local | telegram:<chat> | origin … */
	deliver: string;
	failure_streak: number | null;
	latest_execution: {
		status: string | null;
		started_at: string | null;
		finished_at: string | null;
		error: string | null;
		delivery_outcome: string | null;
	} | null;
};

export type HermesJobOutput = { name: string; size: number; content: string; truncated: boolean };

export type HermesJobFields = {
	name: string;
	schedule: string;
	prompt?: string;
	deliver?: string;
	repeat?: number;
};

const jobsCall = async <T>(
	token: string,
	method: string,
	path = '',
	body?: unknown
): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/jobs${path}`, {
		method,
		headers: jsonHeaders(token),
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	if (!res.ok) {
		throw await detailOf(res);
	}
	return res.json();
};

export const listHermesJobs = async (token: string) =>
	(await jobsCall<{ jobs: HermesJob[] }>(token, 'GET')).jobs;

export const createHermesJob = async (token: string, fields: HermesJobFields) =>
	(await jobsCall<{ job: HermesJob }>(token, 'POST', '', fields)).job;

export const updateHermesJob = async (
	token: string,
	id: string,
	fields: Partial<HermesJobFields>
) => (await jobsCall<{ job: HermesJob }>(token, 'PATCH', `/${encodeURIComponent(id)}`, fields)).job;

export const deleteHermesJob = async (token: string, id: string) =>
	jobsCall<{ status: boolean }>(token, 'DELETE', `/${encodeURIComponent(id)}`);

export const hermesJobAction = async (
	token: string,
	id: string,
	action: 'pause' | 'resume' | 'run'
) =>
	(await jobsCall<{ job: HermesJob }>(token, 'POST', `/${encodeURIComponent(id)}/${action}`)).job;

export const getHermesJobOutputs = async (token: string, id: string, limit = 3) =>
	(
		await jobsCall<{ outputs: HermesJobOutput[] }>(
			token,
			'GET',
			`/${encodeURIComponent(id)}/outputs?limit=${limit}`
		)
	).outputs;

// ---- 后台任务 usage (admin only) ----

export type RunnerRun = {
	run_id: string;
	agent: string;
	status: string;
	failure_kind: string;
	started_at: number;
	ended_at: number | null;
	duration_s: number | null;
	/** what the runner reported, at API prices (a subscription or relay is not billed this way) */
	cost_usd: number | null;
	turns: number | null;
	tool_calls: number | null;
	model: string;
	cwd: string;
	project: string;
	origin: string;
	parent_run: string;
	title: string;
};

export type RunnerQuota = {
	available: boolean;
	checked_at: number;
	notice?: string;
	windows: { key: string; label: string; utilization: number; resets_at: string | null }[];
};

export const getRunnerStats = async (token: string, days = 30) =>
	(await fetch(`${WEBUI_API_BASE_URL}/hermes/runner-stats?days=${days}`, {
		headers: jsonHeaders(token)
	}).then(async (res) => {
		if (!res.ok) throw await detailOf(res);
		return res.json();
	})) as { days: number; runs: RunnerRun[]; quota?: RunnerQuota };

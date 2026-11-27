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
 * Search recent hermes sessions across Telegram / QQ / CLI (unimported by default, for ⌘K).
 */
export const searchHermesSessions = async (
	token: string,
	query: string,
	{
		limit = 8,
		includeImported = false,
		source
	}: { limit?: number; includeImported?: boolean; source?: string } = {}
): Promise<HermesSession[]> => {
	const q = query.trim();
	if (!q) return [];
	const params = new URLSearchParams({
		q,
		limit: `${limit}`,
		include_imported: includeImported ? 'true' : 'false'
	});
	if (source) params.set('source', source);
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/sessions/search?${params}`, {
		method: 'GET',
		headers: jsonHeaders(token)
	});
	if (!res.ok) {
		throw await detailOf(res);
	}
	const data = await res.json();
	return Array.isArray(data?.sessions) ? data.sessions : [];
};

export type TaskInboxItem = {
	id: string;
	bucket: 'attention' | 'running' | 'ended';
	kind: 'hermes' | 'runner' | 'team' | 'answer' | 'discuss' | 'video' | 'auto' | 'chat' | 'image' | 'session';
	source: 'web' | 'telegram' | 'qqbot' | 'cli';
	title: string;
	status: string;
	status_label: string;
	summary?: string;
	href?: string | null;
	chat_id?: string | null;
	session_id?: string | null;
	imported?: boolean;
	run_id?: string | null;
	agent?: string | null;
	timestamp: number;
	unread?: boolean;
	/** Explicit recovery semantics on failed/stopped tasks: continue original vs start fresh. */
	recovery?: 'continue' | 'restart' | null;
};

export type TaskInboxResponse = {
	days: number;
	attention: TaskInboxItem[];
	running: TaskInboxItem[];
	ended: TaskInboxItem[];
	counts: { attention: number; running: number; ended: number };
};

/**
 * Unified Task Inbox: waiting-for-user, running, and recently ended tasks across web workbenches,
 * background runners, and Telegram/QQ Hermes sessions.
 */
export const getTaskInbox = async (token: string, days = 7): Promise<TaskInboxResponse> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/inbox?days=${days}`, {
		method: 'GET',
		headers: jsonHeaders(token)
	});
	if (res.status === 401) {
		throw new HermesSessionExpiredError();
	}
	if (!res.ok) {
		throw await detailOf(res);
	}
	const data = await res.json();
	const attention = Array.isArray(data?.attention) ? data.attention : [];
	const running = Array.isArray(data?.running) ? data.running : [];
	const ended = Array.isArray(data?.ended) ? data.ended : [];
	return {
		days: typeof data?.days === 'number' ? data.days : days,
		attention,
		running,
		ended,
		counts: {
			attention: data?.counts?.attention ?? attention.length,
			running: data?.counts?.running ?? running.length,
			ended: data?.counts?.ended ?? ended.length
		}
	};
};

export type TaskInboxRemoveResult = {
	status: boolean;
	id: string;
	stopped: boolean;
	dismissed: boolean;
	cross_channel?: boolean;
};

/**
 * Stop (when owned and live) and remove a task from the user's Task Inbox so unwanted
 * running or pending tasks can be cleaned up directly from the page.
 */
export const removeTaskInboxItem = async (
	token: string,
	item: Pick<TaskInboxItem, 'id' | 'kind' | 'chat_id' | 'run_id'>
): Promise<TaskInboxRemoveResult> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/inbox/remove`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify({
			id: item.id,
			kind: item.kind,
			chat_id: item.chat_id ?? null,
			run_id: item.run_id ?? null
		})
	});
	if (res.status === 401) {
		throw new HermesSessionExpiredError();
	}
	if (!res.ok) {
		throw await detailOf(res);
	}
	return await res.json();
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

/** Other work, including Hermes before registration and video tasks between reports. */
export type WorkActivityItem = {
	kind: 'chat' | 'image' | 'video' | 'answer' | 'discuss' | 'team' | 'auto';
	id: string;
	chat_id: string | null;
	title: string | null;
	href: string;
	started_at: number;
	state: 'running' | 'waiting';
	note?: string | null;
};

export type HermesActivity = {
	runs: HermesActiveRun[];
	unread: string[];
	background: HermesBackgroundRun[];
	work: WorkActivityItem[];
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
		background: Array.isArray(data?.background) ? data.background : [],
		work: Array.isArray(data?.work) ? data.work : []
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
	/** what the runner reported, at API prices (a subscription or relay is not billed this way);
	 * codex / agy report none, so Hermes estimates theirs from tokens (cost_estimated) */
	cost_usd: number | null;
	cost_estimated?: boolean;
	cost_partial?: boolean;
	cost_source?: string;
	cost_notice?: string;
	pricing_updated_at?: string;
	/** this run's own tokens (a resumed run without its predecessor's) */
	tokens?: {
		input: number;
		cached: number;
		output: number;
		cache_write?: number;
		cache_write_1h?: number;
	} | null;
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
	/** Which official account: officlaude (官方 Claude), offiagy, or openai-codex (Hermes Codex); absent from older Hermes. */
	runner?: string;
	label?: string;
	plan?: string;
	banked_resets?: number;
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
	})) as { days: number; runs: RunnerRun[]; quota?: RunnerQuota; quotas?: RunnerQuota[] };

// ---- Hermes 模型路由 (main model, fallback chain, sub-agents, auxiliary, media; admin only) ----

export type HermesRoutingModel = {
	id: string;
	model: string;
	provider: string;
	provider_label?: string;
	auth_kind?: 'custom' | 'oauth' | string;
	base_url: string;
	api_mode: string;
	vision: boolean;
	context_length?: number | null;
	media_capable?: boolean;
};

export type HermesAuthProvider = {
	slug: string;
	label: string;
	logged_in: boolean;
	model_count: number;
};

export type HermesRoutingSlot = { model: string; fallback: string[] };

export type HermesRouting = {
	main: string;
	fallback: string[];
	delegation: HermesRoutingSlot;
	auxiliary: Record<string, HermesRoutingSlot>;
	media: { model: string; timeout: number };
	reasoning_effort?: string;
	reasoning_overrides?: Record<string, string>;
};

export type HermesRoutingChange = { path: string; before: unknown; after: unknown };

export type HermesRoutingHistoryEntry = {
	id: string;
	at: number;
	source: string;
	changes: HermesRoutingChange[];
};

export type HermesRoutingSnapshot = {
	models: HermesRoutingModel[];
	auth_providers?: HermesAuthProvider[];
	routing: HermesRouting;
	revision: string;
	reasoning_effort: string;
	halo_reasoning_effort?: string;
	history: HermesRoutingHistoryEntry[];
	changes?: HermesRoutingChange[];
};

export type HermesRoutingProbe = {
	model: string;
	ok: boolean;
	latency_ms: number;
	reply: string;
	error: string;
};

const routingCall = async <T>(
	token: string,
	method: string,
	path = '',
	body?: unknown
): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/routing${path}`, {
		method,
		headers: jsonHeaders(token),
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	if (!res.ok) {
		const error: any = await detailOf(res);
		throw Object.assign(new Error(String(error)), { status: res.status });
	}
	return res.json();
};

export const getHermesRouting = (token: string, opts?: { refresh?: boolean }) =>
	routingCall<HermesRoutingSnapshot>(token, 'GET', opts?.refresh ? '?refresh=1' : '');

export const saveHermesRouting = (token: string, routing: HermesRouting, revision: string) =>
	routingCall<HermesRoutingSnapshot>(token, 'PUT', '', { routing, revision });

export const rollbackHermesRouting = (token: string, id: string, revision: string) =>
	routingCall<HermesRoutingSnapshot>(token, 'POST', '/rollback', { id, revision });

export const probeHermesRoutingModel = (token: string, model: string) =>
	routingCall<HermesRoutingProbe>(token, 'POST', '/probe', { model });

// 「AGY 优先」 on the same page: the HTML card's first try on the Google account sign-in
// (offiagy), where team UI tasks start, and offiagy's model.
export type HermesAgyRunnerChoice = { name: string; label: string; note: string; chain: string[] };

export type HermesAgyPrefs = {
	card: { model: string; default: string; signed_in: boolean };
	teams: {
		ui_runner?: string;
		ui_runner_default?: string;
		ui_chain?: string[];
		ui_choices?: HermesAgyRunnerChoice[];
		offiagy_model?: string;
		offiagy_models?: { id: string; name: string }[];
		offiagy_models_at?: number;
		offiagy_models_error?: string;
		error?: string;
	};
};

export type HermesAgyPrefsUpdate = {
	card_model?: string;
	ui_runner?: string;
	offiagy_model?: string;
};

const agyPrefsCall = async (
	token: string,
	method: string,
	body?: HermesAgyPrefsUpdate,
	query = ''
) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/agy-prefs${query}`, {
		method,
		headers: jsonHeaders(token),
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	if (!res.ok) {
		throw new Error(String(await detailOf(res)));
	}
	return (await res.json()) as HermesAgyPrefs;
};

export const getHermesAgyPrefs = (token: string, opts?: { refresh?: boolean }) =>
	agyPrefsCall(token, 'GET', undefined, opts?.refresh ? '?refresh=1' : '');

export const saveHermesAgyPrefs = (token: string, update: HermesAgyPrefsUpdate) =>
	agyPrefsCall(token, 'PUT', update);

export type WorkStepKey = 'plan' | 'plan_review' | 'dev' | 'review';
export type WorkStepConfig = { runner: string; fallback: string[] };
export type WorkWorkflowConfig = {
	plan_review: boolean;
	dual_plan: boolean;
	plan_approval: boolean;
	ui_review: boolean;
	split_dev: boolean;
	steps: Record<WorkStepKey, WorkStepConfig>;
};
export type WorkRunnerOption = {
	name: string;
	label: string;
	engine: string;
	family: string;
	note: string;
	native?: boolean;
};
export type WorkStepMeta = { key: WorkStepKey; label: string; hint: string; optional?: boolean };
export type HermesWorkConfigResponse = {
	config: WorkWorkflowConfig;
	defaults: WorkWorkflowConfig;
	runners: WorkRunnerOption[];
	steps_meta: WorkStepMeta[];
};

const workConfigCall = async (
	token: string,
	method: 'GET' | 'PUT',
	config?: WorkWorkflowConfig
): Promise<HermesWorkConfigResponse> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hermes/work-config`, {
		method,
		headers: jsonHeaders(token),
		...(config === undefined ? {} : { body: JSON.stringify(config) })
	});
	if (!res.ok) {
		throw Object.assign(new Error(String(await detailOf(res))), { status: res.status });
	}
	return res.json();
};

export const getHermesWorkConfig = (token: string) => workConfigCall(token, 'GET');

export const saveHermesWorkConfig = (token: string, config: WorkWorkflowConfig) =>
	workConfigCall(token, 'PUT', config);

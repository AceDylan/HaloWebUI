import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

/** 协作台 (agent teams) API — see backend/open_webui/routers/teams.py. */

/** A Hermes agent, or one of the runners Hermes drives (each brings its own model and account). */
export type TeamExecutor = 'hermes' | 'reclaude' | 'cchclaude' | 'anyclaude' | 'codex' | 'agy';

/** What a member's work is, which decides the runner it starts on (see the plugin's runners.py). */
export type TaskKind = 'code' | 'ui' | 'complex' | 'research' | 'writing';

/** A HaloWebUI assistant template the lead staffed a member with (src/lib/data/agents-zh.json). */
export type AssistantRef = {
	id: string;
	name: string;
	emoji?: string;
	kind?: TaskKind;
	description?: string;
};

export type TeamPlanMember = {
	name: string;
	role: string;
	/** Where the member's runner chain starts: the user's / the goal's choice, else the kind's default. */
	executor: TeamExecutor;
	focus?: string;
	kind?: TaskKind;
	assistant?: AssistantRef | null;
	/** auto = picked by task kind; goal = named in the goal; user = changed by the user. */
	executor_source?: 'auto' | 'goal' | 'user';
	/** The kind's default runner. */
	recommended?: TeamExecutor;
	/** The runner that will actually run it now (null: nothing on the chain is available). */
	runner?: TeamExecutor | null;
	/** Why runner differs from executor. */
	runner_note?: string;
};

export type LeadModel = {
	model: string;
	source?: string;
	label?: string;
	fallback_from?: string[];
	fallback_reason?: string;
	fallbacks?: string[];
	/** The model this team asked for (when not Hermes' default). */
	requested?: string;
	/** Models Hermes has configured that the lead can use (the default first). */
	choices?: string[];
};

export type TeamPlanTask = {
	key: string;
	title: string;
	description: string;
	member: string;
	depends_on: string[];
};

export type TeamPlan = {
	title: string;
	summary?: string;
	lead?: { name: string; role: string; model?: string };
	lead_model?: LeadModel;
	members: TeamPlanMember[];
	tasks: TeamPlanTask[];
	layers?: string[][];
	max_parallel?: number;
	widest_layer?: number;
	executors?: TeamExecutor[];
};

export type TeamStatus =
	| 'planning'
	| 'plan_ready'
	| 'plan_failed'
	| 'starting'
	| 'start_failed'
	| 'running'
	| 'cancelled';

export type Team = {
	id: string;
	chat_id: string | null;
	title: string;
	goal: string;
	status: TeamStatus;
	phase: string | null;
	plan?: TeamPlan | null;
	error: string | null;
	board: string | null;
	created_at: number;
	updated_at: number;
	approved_at: number | null;
	finished_at: number | null;
	member_count: number;
	task_count: number;
	executors: TeamExecutor[];
	/** The model this team asked the lead to use (null = Hermes' default). */
	lead_model?: string | null;
};

export type SubStatus =
	| 'queued'
	| 'waiting_deps'
	| 'running'
	| 'quota_wait'
	| 'waiting_user'
	| 'failed'
	| 'blocked'
	| 'stopped'
	| 'done'
	| 'review'
	| 'triage'
	| 'scheduled'
	| 'archived';

export type LiveTask = {
	id: string;
	key: string;
	seq: number;
	title: string;
	member: string;
	executor: TeamExecutor;
	status: string;
	sub_status: SubStatus;
	parents: string[];
	children: string[];
	created_at: number;
	started_at: number | null;
	completed_at: number | null;
	attempts: number;
	current_run: Record<string, any> | null;
	result: string;
	block_reason: string;
	consecutive_failures: number;
	/** Where the task's runner chain starts (the member's choice) and how it got to executor. */
	chosen?: TeamExecutor;
	chosen_by?: 'auto' | 'goal' | 'user';
	trail?: RunnerStep[];
};

/** One move of a task to another runner. */
export type RunnerStep = {
	from: TeamExecutor;
	to: TeamExecutor | null;
	reason: string;
	at: number;
	phase: 'plan' | 'launch' | 'runtime' | 'retry';
	fail_kind?: string;
};

export type ConclusionEntry = {
	status?: 'generating' | 'ready' | 'failed';
	source?: 'lead' | 'assembled';
	model?: string;
	model_label?: string;
	fallback_reason?: string;
	generated_at?: number;
	started_at?: number;
	seconds?: number;
	chars?: number;
	tasks_done?: number;
	tasks_total?: number;
	by?: string;
	error?: string;
};

export type WorkspaceFile = {
	path: string;
	size: number;
	mtime: number;
	kind: 'image' | 'text' | 'binary';
};

export type TeamConclusion = {
	status: 'none' | 'generating' | 'ready' | 'failed';
	entry: ConclusionEntry;
	markdown: string;
	tasks: {
		id: string;
		key: string;
		title: string;
		member: string;
		executor: string;
		status: string;
		result: string;
		error: string;
		attempts: number;
	}[];
	files: WorkspaceFile[];
	workspace?: string;
};

export type RunnerLayer = { layer: string; ok: boolean; detail: string };

export type RunnerInfo = {
	name: TeamExecutor;
	label: string;
	engine: string;
	note: string;
	native: boolean;
	quota_wait: boolean;
	available: boolean;
	state: string;
	reason: string;
	resume_at?: string | null;
	checked_at: number;
	layers: RunnerLayer[];
};

export type TeamsMeta = {
	lead_model: LeadModel;
	registry: {
		runners: RunnerInfo[];
		kinds: { value: TaskKind; label: string; hint: string; default: TeamExecutor }[];
		order: TeamExecutor[];
		cache_seconds: number;
	};
	assistants: AssistantRef[];
};

export type LiveMember = TeamPlanMember & {
	status: string;
	task_ids: string[];
	current_task: string | null;
};

export type LiveSnapshot = {
	team: {
		team_id: string;
		board: string;
		title: string;
		goal: string;
		summary: string;
		chat_id: string;
		workspace: string;
		state: string;
		archived: boolean;
		phase: string;
		created_at: number;
		approved_at: number;
		completed_at: number | null;
		stopped_at: number | null;
		max_parallel: number;
		lead: { name: string; role: string; status: string; model?: string };
		lead_model?: LeadModel;
		conclusion?: ConclusionEntry;
	};
	members: LiveMember[];
	tasks: LiveTask[];
	counts: Record<string, number>;
	latest_seq: number;
	generated_at: number;
};

export type TeamEvent = {
	id: string;
	seq: number;
	ts: number;
	task_id: string | null;
	key: string | null;
	member: string | null;
	kind: string;
	run_id: number | null;
	type:
		| 'status'
		| 'attempt'
		| 'message'
		| 'handoff'
		| 'tool'
		| 'subagent'
		| 'delivery'
		| 'runner'
		| 'team';
	text?: string;
	status?: string | null;
	sub_status?: string | null;
	who?: 'user' | 'member' | 'system';
	author?: string;
	data?: Record<string, any>;
};

export type TeamEventsPage = {
	events: TeamEvent[];
	next_after: number;
	has_more: boolean;
	latest_seq: number;
	total_raw_events?: number;
	truncated?: boolean;
	reconcile: { task_id: string; key: string; history: string | null; live: string }[];
};

export type TaskAttempt = {
	n: number;
	id: number;
	status: string;
	outcome: string | null;
	started_at: number;
	ended_at: number | null;
	summary: string;
	error: string;
	runner?: string;
	runner_run_id?: string;
	runner_phase?: string;
	resume_at?: string;
	question?: string;
	parent_runner_run_id?: string;
};

export type TaskDetail = {
	task_id: string;
	key: string;
	member: string;
	executor: TeamExecutor;
	title: string;
	body: string;
	status: string;
	result: string;
	runner?: { chosen: TeamExecutor; chosen_by: string; actual: TeamExecutor; trail: RunnerStep[] };
	attempts: TaskAttempt[];
	comments: { id: number; who: string; author: string; text: string; created_at: number }[];
	log?: { text: string; source: string; truncated?: boolean; note?: string };
};

export class TeamsApiError extends Error {
	status: number;
	constructor(status: number, detail: string) {
		super(detail);
		this.name = 'TeamsApiError';
		this.status = status;
	}
}

const headers = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

const request = async <T>(
	token: string,
	method: string,
	path: string,
	body?: unknown
): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/teams${path}`, {
		method,
		headers: headers(token),
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		let detail = data?.detail;
		if (Array.isArray(detail)) {
			detail = detail
				.map((d) => d?.msg ?? '')
				.filter(Boolean)
				.join('；');
		}
		throw new TeamsApiError(res.status, detail || `${res.status} ${res.statusText}`);
	}
	return res.json();
};

const id = (value: string) => encodeURIComponent(value);

export const listTeams = (token: string, chatId?: string | null) =>
	request<{ teams: Team[] }>(token, 'GET', chatId ? `/?chat_id=${id(chatId)}` : '/');

export const createTeam = (
	token: string,
	goal: string,
	chatId?: string | null,
	leadModel?: string | null
) =>
	request<Team>(token, 'POST', '/', {
		goal,
		chat_id: chatId || null,
		lead_model: leadModel || null
	});

export const getTeam = (token: string, teamId: string) =>
	request<{ team: Team; live: LiveSnapshot | null; live_error: string | null }>(
		token,
		'GET',
		`/${id(teamId)}`
	);

export const replanTeam = (token: string, teamId: string, feedback: string) =>
	request<Team>(token, 'POST', `/${id(teamId)}/replan`, { feedback });

export const editTeamPlan = (
	token: string,
	teamId: string,
	members: { name: string; executor: TeamExecutor; source?: 'user' | 'auto' }[]
) => request<Team>(token, 'PUT', `/${id(teamId)}/plan`, { members });

export const getTeamsMeta = (token: string) => request<TeamsMeta>(token, 'GET', '/meta');

export const checkRunners = (token: string, names: string[] = []) =>
	request<TeamsMeta['registry']>(token, 'POST', '/runners/check', { names });

export const getTeamConclusion = (token: string, teamId: string) =>
	request<TeamConclusion>(token, 'GET', `/${id(teamId)}/conclusion`);

export const writeTeamConclusion = (token: string, teamId: string) =>
	request<ConclusionEntry>(token, 'POST', `/${id(teamId)}/conclusion`);

/** A workspace file's path on this site (the session cookie authenticates it). Markdown images
 *  take this form: the chat's Image component adds WEBUI_BASE_URL itself. */
export const teamFilePath = (teamId: string, path: string) =>
	`/api/v1/teams/${id(teamId)}/files/${path.split('/').map(encodeURIComponent).join('/')}`;

/** A workspace file as a full URL for <img src> / <a href>. */
export const teamFileUrl = (teamId: string, path: string) =>
	`${WEBUI_BASE_URL}${teamFilePath(teamId, path)}`;

export const approveTeam = (token: string, teamId: string) =>
	request<Team>(token, 'POST', `/${id(teamId)}/approve`);

export const cancelTeam = (token: string, teamId: string) =>
	request<Team>(token, 'POST', `/${id(teamId)}/cancel`);

export const getTeamEvents = (token: string, teamId: string, after: number, limit = 1000) =>
	request<TeamEventsPage>(token, 'GET', `/${id(teamId)}/events?after=${after}&limit=${limit}`);

export const getTeamTask = (token: string, teamId: string, taskId: string, log = false) =>
	request<TaskDetail>(token, 'GET', `/${id(teamId)}/tasks/${id(taskId)}${log ? '?log=true' : ''}`);

export const sendTeamMessage = (token: string, teamId: string, taskId: string, body: string) =>
	request<{ comment_id: number; delivery: string; expect: string }>(
		token,
		'POST',
		`/${id(teamId)}/tasks/${id(taskId)}/messages`,
		{ body }
	);

export const retryTeamTask = (token: string, teamId: string, taskId: string) =>
	request<{ retried: boolean }>(token, 'POST', `/${id(teamId)}/tasks/${id(taskId)}/retry`);

export const controlTeam = (token: string, teamId: string, action: 'pause' | 'resume' | 'stop') =>
	request<{ state: string; changed: boolean }>(token, 'POST', `/${id(teamId)}/control`, { action });

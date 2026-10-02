import { WEBUI_API_BASE_URL } from '$lib/constants';

/** 协作台 (agent teams) API — see backend/open_webui/routers/teams.py. */

/** A Hermes agent, or one of the runners Hermes drives (each brings its own model and account). */
export type TeamExecutor = 'hermes' | 'reclaude' | 'cchclaude' | 'anyclaude' | 'codex' | 'agy';

export type TeamPlanMember = {
	name: string;
	role: string;
	executor: TeamExecutor;
	focus?: string;
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
	lead?: { name: string; role: string };
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
		lead: { name: string; role: string; status: string };
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
	type: 'status' | 'attempt' | 'message' | 'handoff' | 'tool' | 'subagent' | 'delivery' | 'runner' | 'team';
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

const request = async <T>(token: string, method: string, path: string, body?: unknown): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/teams${path}`, {
		method,
		headers: headers(token),
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		let detail = data?.detail;
		if (Array.isArray(detail)) {
			detail = detail.map((d) => d?.msg ?? '').filter(Boolean).join('；');
		}
		throw new TeamsApiError(res.status, detail || `${res.status} ${res.statusText}`);
	}
	return res.json();
};

const id = (value: string) => encodeURIComponent(value);

export const listTeams = (token: string, chatId?: string | null) =>
	request<{ teams: Team[] }>(token, 'GET', chatId ? `/?chat_id=${id(chatId)}` : '/');

export const createTeam = (token: string, goal: string, chatId?: string | null) =>
	request<Team>(token, 'POST', '/', { goal, chat_id: chatId || null });

export const getTeam = (token: string, teamId: string) =>
	request<{ team: Team; live: LiveSnapshot | null; live_error: string | null }>(token, 'GET', `/${id(teamId)}`);

export const replanTeam = (token: string, teamId: string, feedback: string) =>
	request<Team>(token, 'POST', `/${id(teamId)}/replan`, { feedback });

export const editTeamPlan = (token: string, teamId: string, members: { name: string; executor: TeamExecutor }[]) =>
	request<Team>(token, 'PUT', `/${id(teamId)}/plan`, { members });

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

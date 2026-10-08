import { parseModelSelectionId } from '$lib/utils/model-identity';
import { formatRunDuration } from '$lib/utils/tool-call-preview';

export const DEFAULT_HERMES_AGENT_MODEL_IDS = ['hermes-agent'];

/**
 * The upstream model id behind whatever the UI holds for a message or a
 * selection: a `modelref::…::<id>` selection id, a legacy `<conn>.<id>`
 * prefixed id, or the bare id itself.
 */
export const getUpstreamModelId = (value: unknown): string => {
	const raw = typeof value === 'string' ? value.trim() : '';
	if (!raw) return '';
	const parsed = parseModelSelectionId(raw);
	if (parsed?.modelId) return parsed.modelId;
	return raw;
};

/**
 * True when `value` (message.model, a selection id or a bare id) targets a
 * model served by hermes's /v1/runs, i.e. one whose reply can be steered.
 * `hermesModelIds` comes from `/api/config` (`hermes_agent_model_ids`).
 */
export const isHermesAgentModelId = (
	value: unknown,
	hermesModelIds: readonly string[] | null | undefined = DEFAULT_HERMES_AGENT_MODEL_IDS
): boolean => {
	const ids =
		Array.isArray(hermesModelIds) && hermesModelIds.length > 0
			? hermesModelIds
			: DEFAULT_HERMES_AGENT_MODEL_IDS;
	const upstream = getUpstreamModelId(value);
	if (!upstream) return false;
	if (ids.includes(upstream)) return true;
	// Legacy "<connection-prefix>.<id>" ids.
	const dot = upstream.indexOf('.');
	return dot > 0 && ids.includes(upstream.slice(dot + 1));
};

type ModelIdentity = {
	id?: unknown;
	selection_id?: unknown;
	original_id?: unknown;
	model_id?: unknown;
	model_ref?: Record<string, unknown> | null;
};

/**
 * True when a resolved model entry is served by hermes. `original_id` /
 * `model_id` / `model_ref.model_id` carry the upstream id even when `id` is
 * connection-prefixed (same order as the backend's `_model_upstream_id`).
 */
export const isHermesAgentModel = (
	model: ModelIdentity | null | undefined,
	hermesModelIds: readonly string[] | null | undefined = DEFAULT_HERMES_AGENT_MODEL_IDS
): boolean => {
	if (!model) return false;
	const upstream = [
		model.original_id,
		model.model_id,
		model.model_ref?.model_id,
		model.id,
		model.selection_id
	].find((value) => typeof value === 'string' && value.trim() !== '');
	return isHermesAgentModelId(upstream, hermesModelIds);
};

/**
 * State the backend attaches to an assistant message once its hermes run
 * ends (`chat:completion` → `hermes_run`). `active: false` arrives before
 * the post-processing that keeps the message streaming, so the composer
 * stops offering to steer a run that can no longer take input.
 */
export type HermesRunState = {
	active: boolean;
	run_id?: string | null;
	steers?: number;
	/** Guidance hermes accepted after its final reply and never read. */
	pending_steer?: string;
	/** Set locally when a steer was refused: the run is treated as ended. */
	reason?: string;
};

type SteerableMessage = {
	role?: string;
	done?: boolean;
	model?: string | null;
	hermesRun?: HermesRunState | null;
};

/**
 * True when `message` is the reply of a hermes run that still takes
 * guidance: an assistant message that is not done, served by a hermes model,
 * and not yet flagged by the backend (or a refused steer) as ended.
 * `fallbackModel` covers a reply whose `model` is not set yet.
 */
export const isHermesRunSteerable = (
	message: SteerableMessage | null | undefined,
	hermesModelIds: readonly string[] | null | undefined = DEFAULT_HERMES_AGENT_MODEL_IDS,
	fallbackModel: unknown = null
): boolean => {
	if (!message || message.role !== 'assistant' || message.done) {
		return false;
	}
	if (message.hermesRun && message.hermesRun.active === false) {
		return false;
	}
	return isHermesAgentModelId(message.model ?? fallbackModel, hermesModelIds);
};

/** Payload of the `hermes:approval` socket call (see backend hermes_agent.py). */
export type HermesApprovalRequest = {
	request_id: string;
	run_id?: string;
	chat_id?: string;
	title?: string;
	description?: string;
	command?: string;
	choices?: string[];
	timeout?: number;
	requested_at?: number;
};

/**
 * Per-chat choices for how a hermes run starts (the composer's "Hermes 选项"):
 * `dispatch` puts /reclaude, /cchclaude, /anyclaude, /codex or /agy in front of the message; `model`
 * (+ `provider`) overrides hermes' configured default for this chat. Empty
 * strings mean "hermes decides". The thinking level is HaloWebUI's (see
 * _inherited_reasoning_effort in the backend), not a hermes option.
 *
 * In the panel, `dispatch: ''` follows the chat: right after a runner's report
 * the message goes back to that run ("接着上次", see findHermesContinuation),
 * otherwise to hermes; `'hermes'` is hermes even then. A sent message records
 * what that resolved to: a runner plus `continue_run` for a follow-up.
 */
export type HermesRunOptions = {
	dispatch: '' | 'hermes' | 'reclaude' | 'cchclaude' | 'anyclaude' | 'codex' | 'agy' | 'team';
	model: string;
	provider: string;
	/** The run a sent follow-up went back to (its session resumed, not a new task). */
	continue_run?: string;
};

export const EMPTY_HERMES_RUN_OPTIONS: HermesRunOptions = {
	dispatch: '',
	model: '',
	provider: ''
};

// cchclaude: the reclaude runner driving Claude Code through the user's own cch hub;
// anyclaude: the same on anyrouter (free and slow).
const HERMES_RUNNERS = new Set(['reclaude', 'cchclaude', 'anyclaude', 'codex', 'agy']);
// 'team': the message becomes a 协作台 team (agent_team_dispatch in the backend), no Hermes run.
const HERMES_DISPATCHES = new Set([...HERMES_RUNNERS, 'hermes', 'team']);
// A run id as the runners name them: "20260927-005655-f2dd355f", an answer round "…-a1".
const RUNNER_RUN_ID_RE = /^\d{8}-\d{6}-[0-9a-f]{6,32}(?:-a\d+)*$/;
// "/reclaude …", "/model": a typed command wins over the panel ("/root/x" is a path).
const SLASH_COMMAND_RE = /^\s*\/[A-Za-z][\w-]*(?:\s|$)/;

export const normalizeHermesRunOptions = (value: unknown): HermesRunOptions => {
	const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
	const text = (key: string) => (typeof record[key] === 'string' ? (record[key] as string).trim() : '');
	const dispatch = text('dispatch');
	const model = text('model').slice(0, 200);
	const continueRun = text('continue_run');
	return {
		dispatch: (HERMES_DISPATCHES.has(dispatch) ? dispatch : '') as HermesRunOptions['dispatch'],
		model,
		provider: model ? text('provider').slice(0, 200) : '',
		...(HERMES_RUNNERS.has(dispatch) && RUNNER_RUN_ID_RE.test(continueRun)
			? { continue_run: continueRun }
			: {})
	};
};

/** Only the choices that differ from the default, for the request body; null when none do. */
export const hermesRunOptionsForRequest = (
	options: HermesRunOptions | null | undefined
): Partial<HermesRunOptions> | null => {
	const normalized = normalizeHermesRunOptions(options);
	const picked = Object.fromEntries(
		Object.entries(normalized).filter(([, value]) => value !== '')
	) as Partial<HermesRunOptions>;
	return Object.keys(picked).length > 0 ? picked : null;
};

/**
 * "接着上次": the run whose report ends the chat's current branch. The next
 * message goes back to that run's own session, which remembers what it read
 * and did; hermes' model only knows the report as text and used to answer on
 * its own. Null while a run is still going or once anything was said after
 * its report, and for a run that never started.
 */
export type HermesContinuation = {
	runner: 'reclaude' | 'cchclaude' | 'anyclaude' | 'codex' | 'agy';
	runId: string;
	status: string;
};

type ChatHistoryLike =
	| {
			currentId?: string | null;
			messages?: Record<string, any>;
	  }
	| null
	| undefined;

export const findHermesContinuation = (history: ChatHistoryLike): HermesContinuation | null => {
	const last = history?.currentId ? history.messages?.[history.currentId] : null;
	if (!last || last.role !== 'assistant' || last.done !== true || !last.parentId) return null;
	const notice = parseHermesRunNotice(history?.messages?.[last.parentId]);
	if (!notice || notice.status === 'quota_blocked') return null;
	// Stopped before it had a session (agy before its first result): nothing to go back to.
	if (notice.status === 'stopped' && !notice.sessionId && notice.runId) return null;
	const runner = notice.agent.toLowerCase().replace(/-runner$/, '');
	if (!HERMES_RUNNERS.has(runner) || !RUNNER_RUN_ID_RE.test(notice.runId)) return null;
	return {
		runner: runner as HermesContinuation['runner'],
		runId: notice.runId,
		status: notice.status
	};
};

/**
 * The choices a message was sent with, kept on the user message: 派发方式 is
 * for that one message (the panel falls back to "直接" once it is sent), the
 * model stays for the chat. Regenerating a reply reuses what its message was
 * sent with, not whatever the panel shows now. Left on "直接" right after a
 * runner's report, the message goes back to that run (`continuation`), unless
 * it starts with a command of its own.
 */
export const hermesOptionsForMessage = (
	options: HermesRunOptions | null | undefined,
	continuation: HermesContinuation | null = null,
	prompt: unknown = ''
): HermesRunOptions => {
	const { continue_run: _stale, ...picked } = normalizeHermesRunOptions(options);
	if (picked.dispatch === 'hermes') return { ...picked, dispatch: '' };
	if (!picked.dispatch && continuation && !SLASH_COMMAND_RE.test(String(prompt ?? ''))) {
		return { ...picked, dispatch: continuation.runner, continue_run: continuation.runId };
	}
	return picked;
};

/** What the chat remembers between messages: the model, never a dispatch. */
export const hermesOptionsToKeep = (value: unknown): HermesRunOptions => {
	const { continue_run: _sent, ...kept } = normalizeHermesRunOptions(value);
	return { ...kept, dispatch: '' };
};

/**
 * The panel's 派发方式 for a message taken back into the input (edited from
 * the queue, or not sent at all): what was picked, not what it resolved to.
 */
export const hermesDispatchToRestore = (sent: unknown): HermesRunOptions['dispatch'] => {
	const options = normalizeHermesRunOptions(sent);
	return options.continue_run ? '' : options.dispatch;
};

/**
 * The options a reply is (re)generated with: those recorded on its user
 * message; for a message sent before they were recorded, the panel's model
 * without a dispatch (a typed "/reclaude …" is in the text itself).
 */
export const hermesOptionsForReply = (
	recorded: unknown,
	panel: HermesRunOptions | null | undefined
): HermesRunOptions =>
	recorded && typeof recorded === 'object'
		? normalizeHermesRunOptions(recorded)
		: hermesOptionsToKeep(panel);

/** The run details the backend records on a hermes reply (`hermes_run`). */
export type HermesRunDetails = {
	active?: boolean;
	dispatch?: string;
	requested_model?: string;
	model?: string;
	provider?: string;
	fallback_from?: string;
	runner_run_id?: string;
	fast_dispatch?: boolean;
	/** "/reclaude 进度" answered from the run directories: nothing launched. */
	progress_check?: boolean;
	/** "服务器健康吗" answered by hermes' fleet report: no model, no run. */
	health_check?: boolean;
	/** The run a follow-up went back to ("接着上次"). */
	continued_from?: string;
};

const DISPATCH_LABELS: Record<string, string> = {
	reclaude: 'reclaude',
	cchclaude: 'cchclaude',
	anyclaude: 'anyclaude',
	codex: 'codex',
	agy: 'agy',
	team: '协作台'
};

/**
 * "codex · claude-chat", "gemini-chat → deepseek-chat": who answered a hermes
 * reply, for its header. `run` is what the backend recorded (hermes' actual
 * model when it reports one), `sent` what the user message was sent with.
 * Null when there is nothing to say.
 */
export const describeHermesReply = (
	run: HermesRunDetails | null | undefined,
	sent: Partial<HermesRunOptions> | null | undefined
): { label: string; title: string; fallback: boolean } | null => {
	const dispatch = String(run?.dispatch || sent?.dispatch || '').trim();
	const requested = String(run?.requested_model || sent?.model || '').trim();
	const used = String(run?.model || '').trim();
	const fallbackFrom = String(run?.fallback_from || '').trim();
	const continuedFrom = String(run?.continued_from || '').trim();
	const askedToContinue = String(sent?.continue_run || '').trim();
	// Asked to go back to the run, but hermes' model took the message (the run
	// was still going, or could not be resumed): the model answered.
	const handedToModel =
		Boolean(askedToContinue) && !continuedFrom && run?.active === false && !run.fast_dispatch;
	const parts: string[] = [];
	const lines: string[] = [];
	if (run?.health_check) {
		// Whatever 派发方式 it was sent with: the report ran, nothing was launched.
		parts.push('服务器体检');
		lines.push('直接读取各台服务器、代理线路和网站的状态（没有经过模型，没有启动任务）');
	} else if (dispatch && run?.progress_check) {
		parts.push(`${DISPATCH_LABELS[dispatch] ?? dispatch} · 进度`);
		lines.push('直接读取后台任务的运行状态（没有经过模型，没有启动新任务）');
	} else if (dispatch && continuedFrom) {
		parts.push(`${DISPATCH_LABELS[dispatch] ?? dispatch} · 接着上次`);
		lines.push(`交回 ${dispatch} 运行 ${continuedFrom} 的原会话继续（没有经过模型）`);
		if (run?.runner_run_id) lines.push(`run ${run.runner_run_id}`);
	} else if (handedToModel) {
		// Visible, not only in the tooltip (phones have none): the person meant
		// the runner to get this and should know it did not.
		parts.push(`未交回 ${DISPATCH_LABELS[dispatch] ?? dispatch}`);
		lines.push(`没能直接交回 ${dispatch} 运行 ${askedToContinue}，由 Hermes 处理`);
	} else if (dispatch === 'team') {
		parts.push('协作台');
		lines.push('交给协作台的团队：负责人做计划、成员分工执行，结果会发回这个对话（没有经过模型）');
	} else if (dispatch) {
		parts.push(DISPATCH_LABELS[dispatch] ?? dispatch);
		lines.push(
			run?.fast_dispatch
				? `交给 ${dispatch} 执行（直接启动，没有经过模型）`
				: `交给 ${dispatch} 执行`
		);
		if (run?.runner_run_id) lines.push(`run ${run.runner_run_id}`);
	}
	if (run?.fast_dispatch) {
		// No hermes model took part: the runner's own model does the work.
	} else if (fallbackFrom && used) {
		parts.push(`${fallbackFrom} → ${used}`);
		lines.push(`${fallbackFrom} 不可用，已改用 ${used}`);
	} else if (used || requested) {
		parts.push(used || requested);
		lines.push(
			used
				? `Hermes 使用的模型：${used}${run?.provider ? `（${run.provider}）` : ''}`
				: `选择的模型：${requested}`
		);
	}
	if (parts.length === 0) return null;
	if (dispatch && !run?.fast_dispatch && !handedToModel) {
		lines.push('模型只管 Hermes 这一轮，不影响 runner 自己用什么模型');
	}
	return {
		label: parts.join(' · '),
		title: lines.join('\n'),
		fallback: Boolean(fallbackFrom) || handedToModel
	};
};

/**
 * A background runner's completion notice ("[后台任务完成通知] reclaude 运行
 * <id> 已结束，状态：success，Claude 会话：<id>。"), which hermes needs in the
 * transcript but the person did not write. Null for anything else.
 */
export type HermesRunNotice = {
	agent: string;
	runId: string;
	status: string;
	sessionLabel: string;
	sessionId: string;
};

const RUN_NOTICE_RE =
	/^\s*\[后台任务完成通知\]\s*(\S+)\s+运行\s+(\S+)\s+已结束，状态：([^，。\s]+)(?:，([^：\n]+)：([^。\n]+))?/;

export const parseHermesRunNotice = (message: {
	role?: string;
	content?: unknown;
	hermes_notice?: unknown;
} | null | undefined): HermesRunNotice | null => {
	if (!message || message.role !== 'user') return null;
	const content = typeof message.content === 'string' ? message.content : '';
	const match = content.match(RUN_NOTICE_RE);
	if (match) {
		return {
			agent: match[1],
			runId: match[2],
			status: match[3],
			sessionLabel: (match[4] ?? '').trim(),
			sessionId: (match[5] ?? '').trim()
		};
	}
	if (message.hermes_notice && typeof message.hermes_notice === 'object') {
		const notice = message.hermes_notice as Record<string, unknown>;
		return {
			agent: String(notice.source ?? 'runner'),
			runId: String(notice.run_id ?? ''),
			status: '',
			sessionLabel: '',
			sessionId: ''
		};
	}
	return null;
};

/**
 * A 协作台 team's conclusion posted into its chat ("[协作任务结论] 「标题」已完成，…"; run id
 * "team:<team id>:<version>"): the line reads as the team's, and links back to its page.
 */
export const describeTeamNotice = (
	notice: HermesRunNotice,
	content: unknown
): { headline: string; teamId: string } | null => {
	if (notice.agent !== 'team') return null;
	const text = typeof content === 'string' ? content : '';
	const match = text.match(/「(.+?)」(已完成|已停止)/);
	const teamId = notice.runId.match(/^team:([^:]+):/)?.[1] ?? '';
	return {
		headline: match ? `🤝 协作任务「${match[1]}」${match[2]} · 负责人的结论` : '🤝 协作任务的结论',
		teamId
	};
};

/**
 * A team's result as the chat shows it: its last line — the way to the result page, its files and
 * its record ("在协作台看：[结果页](/teams/<id>/conclusion) · …", or the older single link) — is
 * shown as buttons that open each part in place (TeamResultBar), so it is taken off the text, and
 * so is the rule above it when nothing else (the lead's acceptance) sits under the rule. null when
 * the content does not end with that line.
 */
export const splitTeamReport = (content: unknown, teamId: string): { body: string } | null => {
	const text = typeof content === 'string' ? content.replace(/\s+$/, '') : '';
	if (!teamId || !text) return null;
	const lines = text.split('\n');
	const last = lines[lines.length - 1] ?? '';
	if (!/\]\(\/teams\/[^)\s]+\/conclusion[^)\s]*\)/.test(last) || !last.includes(`/teams/${teamId}/conclusion`)) {
		return null;
	}
	const rest = lines.slice(0, -1);
	while (rest.length && !rest[rest.length - 1].trim()) rest.pop();
	if (rest.length && /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(rest[rest.length - 1])) rest.pop();
	return { body: rest.join('\n').replace(/\s+$/, '') };
};

const NOTICE_STATUS: Record<string, { icon: string; label: string }> = {
	success: { icon: '✅', label: '已完成' },
	question: { icon: '❓', label: '等你决定' },
	max_turns: { icon: '⏸', label: '达到轮数上限' },
	quota_blocked: { icon: '⛔', label: '没有启动' },
	timeout: { icon: '⏱', label: '超时' },
	stopped: { icon: '⏹️', label: '已停止' }
};

// The runner's own first report line: "⏳ reclaude 运行 <id> · 额度用完，暂停中，约 04:31 自动接着跑（不用管）".
const REPORT_HEADLINE_RE = /^\s*(\S+)\s+(\S+)\s+运行\s+(\S+)\s+·\s+(.+?)\s*$/;

/** The run id in a runner report's first line ("✅ reclaude 运行 <id> · 已完成"), or null. */
export const getRunReportRunId = (content: unknown): string | null =>
	(typeof content === 'string' ? content : '').split('\n', 1)[0].match(REPORT_HEADLINE_RE)?.[3] ??
	null;

/**
 * "✅ reclaude 已完成" for the notice line. With the report under it, the
 * runner's own headline wins: it knows more than the status word (a run parked
 * until the quota resets ends as "error" but resumes by itself).
 */
export const describeHermesRunNotice = (notice: HermesRunNotice, report?: unknown): string => {
	const headline = (typeof report === 'string' ? report : '').split('\n', 1)[0].match(REPORT_HEADLINE_RE);
	if (headline && headline[3] === notice.runId) {
		// "（不用管）" and the like are asides for the full report, not the pill.
		const label = headline[4].replace(/（[^（）]*）$/, '').trim();
		if (label) return `${headline[1]} ${headline[2]} ${label}`;
	}
	const status = NOTICE_STATUS[notice.status] ?? {
		icon: notice.status ? '❌' : '📋',
		label: notice.status ? `没有正常完成（${notice.status}）` : '已结束'
	};
	return `${status.icon} ${notice.agent} ${status.label}`;
};

/**
 * The run's duration in seconds from the report under the notice, whose
 * second line reads "Claude 会话 … · 12 轮 · 27m47s"; null when absent.
 */
export const reportDurationSeconds = (report: unknown): number | null => {
	const details = (typeof report === 'string' ? report : '').split('\n', 3)[1] ?? '';
	const match = details.match(/(?:^|·\s*)((?:\d+h)?(?:\d+m)?(?:\d+s)?)\s*$/);
	if (!match || !match[1]) return null;
	const part = (unit: string) => Number(match[1].match(new RegExp(`(\\d+)${unit}`))?.[1] ?? 0);
	const seconds = part('h') * 3600 + part('m') * 60 + part('s');
	return seconds > 0 ? seconds : null;
};

/**
 * The report's figures line for the notice's 详情: "claude-opus-5-5[1m] · Claude 会话 c6fe25fb ·
 * $4.18 · 52 轮 · 20m47s" reads "claude-opus-5-5 · $4.18 · 52 轮 · 用时 20 分 47 秒" — the
 * session is listed in full right below, the context tag and the compact time are not for reading.
 */
export const describeReportFigures = (details: string): string =>
	String(details ?? '')
		.split(' · ')
		.map((part) => part.trim())
		.filter((part) => part && !/(会话|conversation|thread|session)\s+\S+$/i.test(part))
		.map((part) => {
			const time = part.match(/^(共 )?((?:\d+h)?(?:\d+m)?(?:\d+s)?)$/);
			if (time && time[2]) {
				const seconds = reportDurationSeconds(`x\nx · ${time[2]}`);
				const human = seconds ? formatRunDuration(seconds) : '';
				return human ? `${time[1] ?? ''}用时 ${human}` : part;
			}
			return part.replace(/\[[^\]]*\]$/, '');
		})
		.join(' · ');

/**
 * A runner report under its notice line, split for the chat: the runner's own two header
 * lines ("✅ agy 运行 <id> · 已完成" / "AGY conversation e87… · 1 轮") repeat what the
 * notice line right above already says, so the page shows the body only and the notice's
 * 详情 shows the second line (model, cost, turns, time). null when the content does not
 * start with this run's headline (an old report, a team's conclusion, a reply in its place).
 */
export const splitRunReport = (
	content: unknown,
	runId: string
): { headline: string; details: string; body: string } | null => {
	const text = typeof content === 'string' ? content : '';
	if (!runId || !text) return null;
	const lines = text.split('\n');
	const headline = lines[0]?.match(REPORT_HEADLINE_RE);
	if (!headline || headline[3] !== runId) return null;
	// The second line is the details line when it is not blank and not the body's start.
	const second = (lines[1] ?? '').trim();
	const details = second && !/^(#|[-*>]|```|<)/.test(second) ? second : '';
	const body = lines
		.slice(details ? 2 : 1)
		.join('\n')
		.replace(/^\s*\n/, '')
		.trimStart();
	return { headline: lines[0].trim(), details, body };
};

import { parseModelSelectionId } from '$lib/utils/model-identity';

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
 * `dispatch` puts /reclaude, /codex or /agy in front of the message; `model`
 * (+ `provider`) overrides hermes' configured default for this chat. Empty
 * strings mean "hermes decides". The thinking level is HaloWebUI's (see
 * _inherited_reasoning_effort in the backend), not a hermes option.
 */
export type HermesRunOptions = {
	dispatch: '' | 'reclaude' | 'codex' | 'agy';
	model: string;
	provider: string;
};

export const EMPTY_HERMES_RUN_OPTIONS: HermesRunOptions = {
	dispatch: '',
	model: '',
	provider: ''
};

const HERMES_DISPATCHES = new Set(['reclaude', 'codex', 'agy']);

export const normalizeHermesRunOptions = (value: unknown): HermesRunOptions => {
	const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
	const text = (key: string) => (typeof record[key] === 'string' ? (record[key] as string).trim() : '');
	const dispatch = text('dispatch');
	const model = text('model').slice(0, 200);
	return {
		dispatch: (HERMES_DISPATCHES.has(dispatch) ? dispatch : '') as HermesRunOptions['dispatch'],
		model,
		provider: model ? text('provider').slice(0, 200) : ''
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
 * The choices a message was sent with, kept on the user message: 派发方式 is
 * for that one message (the panel falls back to "直接" once it is sent), the
 * model stays for the chat. Regenerating a reply reuses what its message was
 * sent with, not whatever the panel shows now.
 */
export const hermesOptionsForMessage = (options: HermesRunOptions | null | undefined) =>
	normalizeHermesRunOptions(options);

/** What the chat remembers between messages: the model, never a dispatch. */
export const hermesOptionsToKeep = (value: unknown): HermesRunOptions => ({
	...normalizeHermesRunOptions(value),
	dispatch: ''
});

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
	dispatch?: string;
	requested_model?: string;
	model?: string;
	provider?: string;
	fallback_from?: string;
	runner_run_id?: string;
	fast_dispatch?: boolean;
};

const DISPATCH_LABELS: Record<string, string> = {
	reclaude: 'reclaude',
	codex: 'codex',
	agy: 'agy'
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
	const parts: string[] = [];
	const lines: string[] = [];
	if (dispatch) {
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
	if (dispatch && !run?.fast_dispatch) {
		lines.push('模型只管 Hermes 这一轮，不影响 runner 自己用什么模型');
	}
	return { label: parts.join(' · '), title: lines.join('\n'), fallback: Boolean(fallbackFrom) };
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

const NOTICE_STATUS: Record<string, { icon: string; label: string }> = {
	success: { icon: '✅', label: '已完成' },
	question: { icon: '❓', label: '等你决定' },
	max_turns: { icon: '⏸', label: '达到轮数上限' },
	quota_blocked: { icon: '⛔', label: '没有启动' },
	timeout: { icon: '⏱', label: '超时' }
};

/** "✅ reclaude 已完成" for the notice line. */
export const describeHermesRunNotice = (notice: HermesRunNotice): string => {
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

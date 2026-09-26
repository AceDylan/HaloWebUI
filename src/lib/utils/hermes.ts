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
 * strings mean "hermes decides". The thinking level is the chat's own
 * (对话控制), which the backend hands to hermes.
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

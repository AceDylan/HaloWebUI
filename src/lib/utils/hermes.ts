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

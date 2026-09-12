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

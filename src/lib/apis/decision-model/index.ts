import { WEBUI_API_BASE_URL } from '$lib/constants';

/** A model the user may pick as 辅助决策模型 (a selection id: it keeps its connection). */
export type DecisionModelCandidate = {
	id: string;
	name: string;
	connection: string;
	kind: 'text' | 'system_one';
};

export type DecisionModelState = {
	/** null: 沿用现有逻辑 */
	model: string | null;
	name: string | null;
	kind: 'text' | 'system_one' | null;
	/** false: set, but the model is gone or no longer allowed (decisions fall back) */
	available: boolean | null;
	candidates: DecisionModelCandidate[];
};

/** What a module's run records about its decision (plan.decider, planning.decider, …). */
export type DecisionTrace = {
	module: 'auto' | 'answer' | 'discuss' | 'team';
	model: string;
	name: string;
	kind: string;
	used: boolean;
	fallback: boolean;
	reason?: string;
	result?: unknown;
	at: number;
};

async function call(token: string, body?: object): Promise<DecisionModelState> {
	const res = await fetch(`${WEBUI_API_BASE_URL}/decision-model/`, {
		method: body === undefined ? 'GET' : 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	const data = await res.json().catch(() => ({}));
	if (!res.ok)
		throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请稍后再试');
	return data;
}

export const getDecisionModel = (token: string) => call(token);
export const setDecisionModel = (token: string, model: string | null) => call(token, { model });

import { WEBUI_BASE_URL } from '$lib/constants';
import { parseJsonResponse } from '../response';

const HERMES_AGENT_API_BASE_URL = `${WEBUI_BASE_URL}/hermes-agent`;

export type HermesAgentConfig = {
	ENABLE_HERMES_AGENT?: boolean;
	HERMES_AGENT_BASE_URLS: string[];
	HERMES_AGENT_API_KEYS: string[];
	HERMES_AGENT_CONFIGS: Record<string, any>;
};

const authHeaders = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	...(token && { authorization: `Bearer ${token}` })
});

const parseOrThrow = async <T>(res: Response): Promise<T> => parseJsonResponse<T>(res);

export const getHermesAgentConfig = async (token: string = ''): Promise<HermesAgentConfig> => {
	let error: unknown = null;
	const res = await fetch(`${HERMES_AGENT_API_BASE_URL}/config`, {
		method: 'GET',
		headers: authHeaders(token)
	})
		.then((res) => parseOrThrow<HermesAgentConfig>(res))
		.catch((err) => {
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	if (!res) throw new Error('Failed to load Hermes Agent config.');
	return res;
};

export const updateHermesAgentConfig = async (
	token: string = '',
	config: HermesAgentConfig
): Promise<HermesAgentConfig> => {
	let error: unknown = null;
	const res = await fetch(`${HERMES_AGENT_API_BASE_URL}/config/update`, {
		method: 'POST',
		headers: authHeaders(token),
		body: JSON.stringify(config)
	})
		.then((res) => parseOrThrow<HermesAgentConfig>(res))
		.catch((err) => {
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	if (!res) throw new Error('Failed to update Hermes Agent config.');
	return res;
};

export const getHermesAgentModels = async (token: string = '') => {
	let error: unknown = null;
	const res = await fetch(`${HERMES_AGENT_API_BASE_URL}/models`, {
		method: 'GET',
		headers: authHeaders(token)
	})
		.then(parseJsonResponse)
		.catch((err) => {
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

import { WEBUI_API_BASE_URL } from '$lib/constants';

/** 讨论台 (multi-model discussion room) API — see backend/open_webui/routers/discussions.py. */

export type DiscussMode = 'roundtable' | 'debate' | 'review' | 'brainstorm';

export type DiscussSeat = {
	id: string;
	/** The selection id the seat's model is called by. */
	model: string;
	name: string;
	/** The model name, or "name·role" / "name #2" when two seats share a model. */
	label: string;
	role: string;
};

export type DiscussModerator = { model: string; name: string };

export type DiscussSetup = {
	mode: DiscussMode;
	rounds: number;
	seats: DiscussSeat[];
	moderator: DiscussModerator;
};

export type TurnStatus = 'waiting' | 'streaming' | 'done' | 'error' | 'stopped';

export type DiscussUsage = { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };

export type DiscussTurn = {
	/** r{round}-{seat id} */
	id: string;
	round: number;
	seat: string;
	status: TurnStatus;
	content: string;
	thinking?: boolean;
	error?: string | null;
	usage?: DiscussUsage;
	startedAt?: number | null;
	endedAt?: number | null;
};

export type DiscussConclusion = {
	status: TurnStatus;
	content: string;
	model: string;
	name: string;
	thinking?: boolean;
	error?: string | null;
	usage?: DiscussUsage;
	startedAt?: number | null;
	endedAt?: number | null;
};

export type AskStatus = 'running' | 'concluding' | 'done' | 'stopped' | 'error' | 'interrupted';

/** One question asked in a discussion and everything said about it. */
export type DiscussAsk = {
	id: string;
	userMessageId: string;
	question: string;
	lang: 'zh' | 'en';
	mode: DiscussMode;
	rounds: number;
	seats: DiscussSeat[];
	moderator: DiscussModerator;
	status: AskStatus;
	round: number;
	turns: DiscussTurn[];
	interjections: { text: string; afterRound: number; at: number }[];
	conclusion: DiscussConclusion;
	previousConclusions: { content: string; endedAt?: number | null }[];
	startedAt: number;
	endedAt?: number | null;
	usage: DiscussUsage;
	error?: string | null;
};

export type Discussion = {
	id: string;
	title: string;
	folder_id: string | null;
	updated_at: number;
	created_at: number;
	setup: DiscussSetup;
	asks: DiscussAsk[];
	running: boolean;
};

/** A row of the list (the chat's meta.discussion_room summary). */
export type DiscussionSummary = {
	id: string;
	title: string;
	updated_at: number;
	created_at: number;
	folder_id: string | null;
	archived: boolean;
	running: boolean;
	mode: DiscussMode;
	rounds: number;
	seats: { model: string; name: string; label: string; role: string }[];
	moderator: DiscussModerator;
	status: AskStatus;
	asks: number;
	question: string;
	preview: string;
	round?: number;
};

export class DiscussApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

const request = async <T>(token: string, method: string, path: string, body?: unknown): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/discussions${path}`, {
		method,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
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
		throw new DiscussApiError(res.status, detail || `${res.status} ${res.statusText}`);
	}
	return res.json();
};

const id = (value: string) => encodeURIComponent(value);

export const listDiscussions = (token: string, archived = false) =>
	request<DiscussionSummary[]>(token, 'GET', archived ? '/?archived=true' : '/');

export const createDiscussion = (
	token: string,
	form: {
		question: string;
		mode: DiscussMode;
		seats: { model: string; role?: string }[];
		rounds: number;
		moderator: string;
	}
) => request<Discussion>(token, 'POST', '/', form);

export const getDiscussion = (token: string, chatId: string) =>
	request<Discussion>(token, 'GET', `/${id(chatId)}`);

export const askDiscussion = (token: string, chatId: string, question: string, rounds?: number) =>
	request<Discussion>(token, 'POST', `/${id(chatId)}/ask`, { question, rounds: rounds ?? null });

export const interjectDiscussion = (token: string, chatId: string, text: string) =>
	request<{ ok: boolean }>(token, 'POST', `/${id(chatId)}/interject`, { text });

export const stopDiscussion = (token: string, chatId: string) =>
	request<Discussion & { stopped: boolean }>(token, 'POST', `/${id(chatId)}/stop`);

export const concludeDiscussion = (token: string, chatId: string) =>
	request<Discussion>(token, 'POST', `/${id(chatId)}/conclude`);

export const continueDiscussion = (token: string, chatId: string) =>
	request<Discussion>(token, 'POST', `/${id(chatId)}/continue`);

export const deleteDiscussion = (token: string, chatId: string) =>
	request<{ ok: boolean }>(token, 'DELETE', `/${id(chatId)}`);

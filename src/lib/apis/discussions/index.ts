import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { AssistantChoice } from '$lib/apis/assistant-library';
import { pageQuery, type PageQuery } from '$lib/apis/paging';

/** 讨论台 (multi-model discussion room) API — see backend/open_webui/routers/discussions.py. */

export type DiscussMode = 'roundtable' | 'compare' | 'debate' | 'review' | 'brainstorm';

export type DiscussSeat = {
	id: string;
	/** The selection id the seat's model is called by. */
	model: string;
	name: string;
	/** The model name, or "name·role" / "name #2" when two seats share a model. */
	label: string;
	role: string;
	/** Where the seat's assistant comes from: matched to each question, picked by the user, none
	 * (the role only), or the seat's model is itself an assistant. */
	assist?: SeatAssist;
	/** The picked assistant (`model:<id>` / `builtin:<id>`). */
	assistant?: string;
	/** What the seat covers in this discussion. */
	duty?: string;
	/** In an ask: the assistant the seat used for that question (a snapshot). */
	assistant_choice?: AssistantChoice | null;
};

export type SeatAssist = 'auto' | 'pick' | 'generic' | 'self';

/** `persona`: the moderator was picked as an assistant; it writes through its base model, neutral. */
export type DiscussModerator = { model: string; name: string; persona?: string };

export type DiscussSetup = {
	mode: DiscussMode;
	rounds: number;
	seats: DiscussSeat[];
	moderator: DiscussModerator;
	/** Look things up on the web before round 1 (one shared set of notes). */
	research?: boolean;
	/** 自动匹配助手 */
	autoMatch?: boolean;
};

/** Matching the seats' assistants when a question starts. */
export type DiscussMatching = {
	status: 'waiting' | 'running' | 'done' | 'error' | 'stopped';
	error?: string | null;
	startedAt?: number | null;
	endedAt?: number | null;
};

/** A file attached to a question (images go to the models that read images, documents to all). */
export type DiscussFile = { id: string; name: string; type: 'image' | 'file'; content_type?: string; size?: number };

export type DiscussContext = { text: string; title: string; chatId: string | null };

/** The chat a 精答 run / a discussion was sent from (派发方式「精答」/「讨论」) and its card reply. */
export type DispatchOrigin = { chatId: string; messageId: string };

/** The result put into the chat it was sent from (`posted` false: it was there already). */
export type ReportBack = { chat_id: string; posted: boolean; duplicate: boolean };

export type ResearchSource = { n: number; title: string; url: string; excerpt: string };

/** One round's 补查: the searches the seats asked for, run before the next round. */
export type ResearchLookup = {
	round: number;
	queries: string[];
	status: 'running' | 'done' | 'empty' | 'error' | 'stopped';
	/** sources it added to the notes */
	added: number;
	error?: string | null;
};

export type DiscussResearch = {
	/** skipped: the query writer found nothing a search could help with */
	status: 'waiting' | 'running' | 'done' | 'empty' | 'error' | 'stopped' | 'skipped';
	queries: string[];
	sources: ResearchSource[];
	lookups?: ResearchLookup[];
	error?: string | null;
	startedAt?: number | null;
	endedAt?: number | null;
};

export type TurnStatus = 'waiting' | 'streaming' | 'done' | 'error' | 'stopped';

/** A call the upstream refused for a passing reason, about to be made again. */
export type DiscussRetry = { n: number; of: number; reason: string; until: number; error?: string };

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
	/** The model rejected the attached images; it spoke from the text only. */
	imagesDropped?: boolean;
	retry?: DiscussRetry | null;
	/** the one more search (补查) this seat asked for before the next round */
	lookup?: { query: string; status?: ResearchLookup['status'] | 'skipped'; added?: number } | null;
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
	/** The moderator rejected the attached images; it concluded from the text only. */
	imagesDropped?: boolean;
	retry?: DiscussRetry | null;
	/** The moderator could not write it; a seat (model / name above) wrote it instead. */
	standIn?: { for: string; reason: string; error?: string } | null;
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
	matching?: DiscussMatching | null;
	status: AskStatus;
	round: number;
	turns: DiscussTurn[];
	interjections: { text: string; afterRound: number; at: number }[];
	conclusion: DiscussConclusion;
	previousConclusions: { content: string; endedAt?: number | null }[];
	research?: DiscussResearch | null;
	files?: DiscussFile[];
	/** The conversation the discussion was started from, given to every seat as background. */
	context?: DiscussContext | null;
	/** Sent from a chat (派发方式「讨论」): the conclusion goes back to that chat. */
	origin?: DispatchOrigin | null;
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
	/** Creating it again returned the discussion already started for this question. */
	deduplicated?: boolean;
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
	seats: { model: string; name: string; label: string; role: string; assistant?: string }[];
	moderator: DiscussModerator;
	research?: boolean;
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

/** One page of the discussions, newest first (the same paging as the 精答 list). */
export type DiscussionPage = {
	items: DiscussionSummary[];
	next: string | null;
	total: number | null;
	live: number;
};

export const listDiscussions = (token: string, opts: PageQuery = {}) =>
	request<DiscussionPage>(token, 'GET', pageQuery(opts));

export const createDiscussion = (
	token: string,
	form: {
		question: string;
		mode: DiscussMode;
		seats: { model: string; role?: string; assist?: SeatAssist; assistant?: string; duty?: string }[];
		rounds: number;
		moderator: string;
		research?: boolean;
		files?: string[];
		context?: { text: string; title?: string; chat_id?: string | null } | null;
		/** One per question: a retry with the same key gets the same discussion back. */
		client_key?: string;
		/** 自动匹配助手: seats without their own choice get an assistant matched to each question. */
		auto_match?: boolean;
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

/** Pick the last question up where it failed, stopped or was cut off. */
export const resumeDiscussion = (token: string, chatId: string) =>
	request<Discussion>(token, 'POST', `/${id(chatId)}/resume`);

export const continueDiscussion = (token: string, chatId: string) =>
	request<Discussion>(token, 'POST', `/${id(chatId)}/continue`);

/** Run a seat's failed or stopped turn again (then a fresh conclusion). */
export const retryDiscussionTurn = (token: string, chatId: string, turn: string) =>
	request<Discussion>(token, 'POST', `/${id(chatId)}/retry`, { turn });

/** Undo the upgrade the last question made to a seat's assistant. */
export const undoSeatAssistant = (token: string, chatId: string, seat: string) =>
	request<Discussion>(token, 'POST', `/${id(chatId)}/undo-assistant`, { seat });

/** 「把结论放进这个对话」: the conclusion of a discussion sent from a chat, into that chat now. */
export const reportBackDiscussion = (token: string, chatId: string) =>
	request<ReportBack>(token, 'POST', `/${id(chatId)}/report-back`);

export const deleteDiscussion = (token: string, chatId: string) =>
	request<{ ok: boolean }>(token, 'DELETE', `/${id(chatId)}`);

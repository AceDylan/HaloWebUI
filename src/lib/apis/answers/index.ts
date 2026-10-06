import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { DiscussContext, DiscussResearch, DiscussRetry, DiscussUsage } from '$lib/apis/discussions';

/** 精答工作台 (answer desk) API — see backend/open_webui/routers/answers.py. */

export type AnswerStatus = 'routing' | 'researching' | 'answering' | 'done' | 'stopped' | 'error' | 'interrupted';

/** How the dispatcher got an assistant: kept one, upgraded one, made one; `temporary` = made one
 * for this question only (the user may not keep assistants), `direct` = the dispatcher failed and
 * answered itself. */
export type AssistantAction = 'use' | 'update' | 'create' | 'temporary' | 'direct';

export type AnswerAssistant = {
	id: string;
	name: string;
	emoji?: string;
	description?: string;
	action: AssistantAction;
	saved: boolean;
	base?: string;
	baseName?: string;
	/** The system prompt written into it (created / upgraded / one-off). */
	system?: string;
	/** The upgrade was undone. */
	reverted?: boolean;
};

export type AnswerPlan = {
	status: 'running' | 'done' | 'error' | 'stopped';
	action?: AssistantAction;
	reason?: string;
	change?: string;
	note?: string;
	webSearch?: boolean;
	error?: string | null;
	startedAt?: number | null;
	endedAt?: number | null;
};

export type AnswerPart = {
	status: 'waiting' | 'streaming' | 'done' | 'error' | 'stopped';
	content: string;
	thinking?: boolean;
	usage?: DiscussUsage;
	error?: string | null;
	retry?: DiscussRetry | null;
	startedAt?: number | null;
	endedAt?: number | null;
};

export type AnswerRun = {
	id: string;
	userMessageId: string;
	question: string;
	lang: 'zh' | 'en';
	status: AnswerStatus;
	planner: { model: string; name: string };
	webAllowed: boolean;
	/** The conversation it was asked from, given to the dispatcher and the assistant as background. */
	context?: DiscussContext | null;
	plan: AnswerPlan;
	assistant: AnswerAssistant | null;
	research: DiscussResearch | null;
	answer: AnswerPart;
	startedAt: number;
	endedAt?: number | null;
	error?: string | null;
};

export type AnswerDetail = {
	id: string;
	title: string;
	folder_id: string | null;
	updated_at: number;
	created_at: number;
	run: AnswerRun | null;
	running: boolean;
	/** Questions asked in the chat after the answer. */
	followups: number;
	messageId: string;
	/** Creating it again returned the run already started for this question. */
	deduplicated?: boolean;
};

/** A row of the list (the chat's meta.answer_desk summary). */
export type AnswerSummary = {
	id: string;
	title: string;
	updated_at: number;
	created_at: number;
	folder_id: string | null;
	archived: boolean;
	running: boolean;
	status: AnswerStatus;
	question: string;
	preview: string;
	assistant: { id: string; name: string; emoji?: string; action: AssistantAction } | null;
	research?: boolean;
};

export type LibraryAssistant = {
	id: string;
	name: string;
	description: string;
	emoji: string;
	base: string;
	baseName: string;
	editable: boolean;
	/** Made (or last upgraded) by 精答. */
	byDesk: boolean;
};

export class AnswerApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

const request = async <T>(token: string, method: string, path: string, body?: unknown): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/answers${path}`, {
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
		throw new AnswerApiError(res.status, detail || `${res.status} ${res.statusText}`);
	}
	return res.json();
};

const id = (value: string) => encodeURIComponent(value);

export const listAnswers = (token: string, archived = false) =>
	request<AnswerSummary[]>(token, 'GET', archived ? '/?archived=true' : '/');

export const listAnswerAssistants = (token: string) =>
	request<{ assistants: LibraryAssistant[]; may_create: boolean }>(token, 'GET', '/assistants');

export const createAnswer = (
	token: string,
	form: {
		question: string;
		planner?: string | null;
		research?: boolean;
		context?: { text: string; title: string; chat_id: string | null } | null;
		client_key?: string;
	}
) => request<AnswerDetail>(token, 'POST', '/', form);

export const getAnswer = (token: string, chatId: string) => request<AnswerDetail>(token, 'GET', `/${id(chatId)}`);

export const stopAnswer = (token: string, chatId: string) => request<AnswerDetail>(token, 'POST', `/${id(chatId)}/stop`);

export const retryAnswer = (token: string, chatId: string) => request<AnswerDetail>(token, 'POST', `/${id(chatId)}/retry`);

export const revertAnswerUpgrade = (token: string, chatId: string) =>
	request<AnswerDetail>(token, 'POST', `/${id(chatId)}/revert`);

export const deleteAnswer = (token: string, chatId: string) => request<{ ok: boolean }>(token, 'DELETE', `/${id(chatId)}`);

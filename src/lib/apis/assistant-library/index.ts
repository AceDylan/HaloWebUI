import { WEBUI_API_BASE_URL } from '$lib/constants';

/** 助手库 API — see backend/open_webui/routers/assistant_library.py. */

/** Who made an assistant: by hand, one of the workbenches, or saved from a built-in template
 * (`builtin:<id>`). */
export type AssistantSource = 'manual' | 'answer' | 'team' | 'discuss' | `builtin:${string}`;

/** How a workbench got a unit's assistant: kept one, upgraded one, made one; `template` = a
 * built-in template as it is; `temporary` = written for this run only (no right to save, or over
 * the per-run limit); `generic` = no specialist, the plain role. */
export type AssistantChoiceAction = 'use' | 'template' | 'update' | 'create' | 'temporary' | 'generic';

export type LibraryEntry = {
	/** `model:<id>` */
	ref: string;
	id: string;
	name: string;
	description: string;
	domain: string;
	emoji: string;
	/** Its system prompt. */
	prompt: string;
	/** Its recommended base model. */
	base: string;
	baseName: string;
	owned: boolean;
	editable: boolean;
	/** Kept out of the model menus (the workbenches still pick it). */
	hidden: boolean;
	source: AssistantSource;
	version: number;
};

/** The assistant a workbench used for one unit (a question, a member, a seat), as the run keeps it. */
export type AssistantChoice = {
	action: AssistantChoiceAction;
	saved: boolean;
	ref?: string;
	id?: string;
	name?: string;
	emoji?: string;
	description?: string;
	version?: number | null;
	base?: string;
	source?: string;
	reason?: string;
	change?: string;
	note?: string;
	hasSystem?: boolean;
	/** The full system prompt (only where the page asked for it). */
	system?: string;
	reverted?: boolean;
};

export type AssistantRevision = {
	version: number;
	at: number;
	source: string;
	runRef?: string | null;
	change?: string;
	name?: string;
	system: string;
	description?: string;
};

export type AssistantVersions = {
	id: string;
	name: string;
	editable: boolean;
	source: AssistantSource;
	domain: string;
	createdFor?: { runRef?: string; by?: string; question?: string; at?: number } | null;
	current: { version: number; name: string; system: string; description: string; at: number };
	/** Newest first. */
	revisions: AssistantRevision[];
};

export type StalePin = { id: string; name: string; pinned: number | null; current: number };

export class LibraryApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

const request = async <T>(token: string, method: string, path: string, body?: unknown): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/assistant-library${path}`, {
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
		throw new LibraryApiError(res.status, detail || `${res.status} ${res.statusText}`);
	}
	return res.json();
};

const q = (value: string) => encodeURIComponent(value);

export const listLibrary = (token: string) =>
	request<{ assistants: LibraryEntry[]; may_write: boolean; favorites: string[] }>(token, 'GET', '/');

export type TemplateEntry = { ref: string; id: string; name: string; emoji: string; description: string; groups: string[] };

/** Built-in templates matching `q`, or the ones named in `refs`. */
export const searchTemplates = (token: string, opts: { q?: string; refs?: string[]; limit?: number }) =>
	request<TemplateEntry[]>(
		token,
		'GET',
		`/templates?q=${q(opts.q ?? '')}&refs=${q((opts.refs ?? []).join(','))}&limit=${opts.limit ?? 20}`
	);

export const getAssistantVersions = (token: string, id: string) =>
	request<AssistantVersions>(token, 'GET', `/versions?id=${q(id)}`);

export const restoreAssistantVersion = (token: string, id: string, version: number) =>
	request<AssistantVersions>(token, 'POST', `/restore?id=${q(id)}`, { version });

export const archiveAssistant = (token: string, id: string, archived: boolean) =>
	request<{ id: string; archived: boolean; is_active: boolean }>(token, 'POST', `/archive?id=${q(id)}`, { archived });

/** Undo the upgrade one run made (`answer:<chat>`, `discuss:<chat>:<ask>`, `team:<id>`). */
export const undoAssistantRun = (token: string, id: string, runRef: string, afterSystem?: string) =>
	request<{ id: string; version: number }>(token, 'POST', '/undo', {
		id,
		run_ref: runRef,
		...(afterSystem === undefined ? {} : { after_system: afterSystem })
	});

export const getStalePins = (token: string, chatId: string) =>
	request<StalePin[]>(token, 'GET', `/pins/${q(chatId)}`);

export const refreshPin = (token: string, chatId: string, id: string) =>
	request<{ ok: boolean }>(token, 'POST', `/pins/${q(chatId)}/refresh`, { id });

/** Label of an assistant's source, for filters and cards. */
export const sourceLabel = (source: string | null | undefined): string => {
	const value = String(source ?? 'manual');
	if (value.startsWith('builtin:')) return '内置派生';
	return { manual: '手动', answer: '精答', team: '协作台', discuss: '讨论台' }[value] ?? '手动';
};

/** Label of what a workbench did with a unit's assistant. */
export const choiceLabel = (action: AssistantChoiceAction | string | null | undefined): string =>
	({
		use: '选用',
		template: '选用模板',
		update: '升级',
		create: '新建',
		temporary: '仅本次',
		generic: '通用角色',
		direct: '直接回答'
	})[String(action ?? '')] ?? '';

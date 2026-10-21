import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseJsonResponse } from '../response';

const STUDIO_PREP_API_BASE_URL = `${WEBUI_API_BASE_URL}/studio-prep`;

export type StudioPrepKind = 'video' | 'image';
export type StudioPrepStepKey = 'plan' | 'search' | 'answer' | 'discuss' | 'enhance';

/** One step of 提示词增强 (backend utils/studio_prep.py). */
export type StudioPrepStep = {
	key: StudioPrepStepKey;
	label: string;
	status: 'running' | 'done' | 'skipped' | 'error';
	detail?: string;
};

/** The 精答 / 讨论 it asked first: a chat of its own, open on its page. */
export type StudioPrepRun = { kind: 'answer' | 'discuss'; chatId: string; href: string; label: string };

export type StudioPrepSource = { n: number; title: string; url: string };

export type StudioPrepResult = {
	/** The enhanced request. */
	idea: string;
	/** The key facts it rests on (from the web or the 精答 / 讨论), '' without material. */
	notes: string;
	sources: StudioPrepSource[];
	run?: StudioPrepRun;
};

export type StudioPrepJob = {
	id: string;
	kind: StudioPrepKind;
	status: 'running' | 'done' | 'error' | 'cancelled';
	/** The request as the user wrote it. */
	idea: string;
	steps: StudioPrepStep[];
	run: StudioPrepRun | null;
	result: StudioPrepResult | null;
	error: string;
	/** The model that analyses and rewrites (gpt-chat when the user has it). */
	model: string;
	createdAt: number;
};

export type StudioPrepForm = {
	kind: StudioPrepKind;
	idea: string;
	/** The decided settings in words (做法, 画幅, 时长 …). */
	settings?: string;
	/** May it look things up on the web (it decides whether the request needs it). */
	research?: boolean;
	/** Video: may it ask 精答 / 讨论 first (it decides whether the request needs it). */
	deeper?: boolean;
};

const headers = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

export const startStudioPrep = async (token: string, form: StudioPrepForm): Promise<StudioPrepJob> =>
	fetch(`${STUDIO_PREP_API_BASE_URL}/`, {
		method: 'POST',
		headers: headers(token),
		body: JSON.stringify(form)
	}).then(parseJsonResponse<StudioPrepJob>);

export const getStudioPrep = async (token: string, id: string): Promise<StudioPrepJob> =>
	fetch(`${STUDIO_PREP_API_BASE_URL}/${encodeURIComponent(id)}`, {
		method: 'GET',
		headers: headers(token)
	}).then(parseJsonResponse<StudioPrepJob>);

export const cancelStudioPrep = async (token: string, id: string): Promise<StudioPrepJob> =>
	fetch(`${STUDIO_PREP_API_BASE_URL}/${encodeURIComponent(id)}/cancel`, {
		method: 'POST',
		headers: headers(token)
	}).then(parseJsonResponse<StudioPrepJob>);

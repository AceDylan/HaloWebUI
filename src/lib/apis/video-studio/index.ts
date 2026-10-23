import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseJsonResponse } from '../response';

const VIDEO_STUDIO_API_BASE_URL = `${WEBUI_API_BASE_URL}/video-studio`;

/** A video Hermes or a runner handed over (backend utils/video_library.py). */
export type LibraryVideo = {
	id: string;
	fileId: string;
	url: string;
	name: string;
	title: string;
	size: number;
	contentType: string;
	/** Hermes' own reply, or a runner's report. */
	origin: 'hermes' | 'runner';
	createdAt: number;
	/** The chat it came in, while that chat is still there. */
	chatId?: string;
	chatTitle?: string;
	/** The background run that made it (a runner's report): its id, runner, where it was
	 * started (telegram, api_server) and its task. */
	runId?: string;
	runner?: string;
	platform?: string;
	runTitle?: string;
};

const headers = (token: string) => ({ Accept: 'application/json', authorization: `Bearer ${token}` });

/** One page of the library, newest first (`next`: pass it as `before`, null at the end). */
export const getVideoPage = async (
	token: string,
	opts: { limit?: number; before?: string | null; q?: string } = {}
): Promise<{ items: LibraryVideo[]; next: string | null }> => {
	const params = new URLSearchParams();
	if (opts.limit) params.set('limit', String(opts.limit));
	if (opts.before) params.set('before', opts.before);
	if (opts.q?.trim()) params.set('q', opts.q.trim());
	const res = await fetch(`${VIDEO_STUDIO_API_BASE_URL}/items?${params}`, {
		method: 'GET',
		headers: headers(token)
	}).then(parseJsonResponse<{ items: { id: string; data: LibraryVideo; created_at: number }[]; next: string | null }>);
	const items = (Array.isArray(res?.items) ? res.items : [])
		.filter((item) => item?.data?.url)
		.map((item) => ({ ...item.data, id: item.id, createdAt: item.data.createdAt || item.created_at * 1000 }));
	return { items, next: res?.next ?? null };
};

/** Takes a video out of the library (the chat that shows it keeps it). */
export const deleteLibraryVideo = async (token: string, id: string): Promise<boolean> =>
	fetch(`${VIDEO_STUDIO_API_BASE_URL}/items/${encodeURIComponent(id)}`, {
		method: 'DELETE',
		headers: headers(token)
	}).then(parseJsonResponse<boolean>);

/** An MP3 the user uploaded before: background music the workbench can pick again. */
export type MusicFile = { id: string; name: string; size: number; createdAt: number };

/** The user's own MP3 uploads, newest first. */
export const getMusicFiles = async (token: string, limit = 12): Promise<MusicFile[]> => {
	const res = await fetch(`${VIDEO_STUDIO_API_BASE_URL}/music?limit=${limit}`, {
		method: 'GET',
		headers: headers(token)
	}).then(parseJsonResponse<MusicFile[]>);
	return Array.isArray(res) ? res.filter((m) => m?.id) : [];
};

/** A video the workbench started (backend utils/video_tasks.py): its chat, as it stands now. */
export type VideoTask = {
	id: string;
	chatId: string;
	messageId: string;
	title: string;
	/** Hermes, or the runner the brief named (codex, reclaude …). */
	maker: string;
	/** running: Hermes is at work · background: a runner makes it, its report comes back to
	 * the chat · done: the video is in the library · replied: answered without a video (it may
	 * be asking something) · failed · stopped */
	state: 'running' | 'background' | 'done' | 'replied' | 'failed' | 'stopped';
	/** What is happening now (or how it ended), one line. */
	now: string;
	/** The 提示词增强 the brief waited for: still going, done, or none. */
	prep: 'running' | 'done' | null;
	/** Tool calls Hermes made so far. */
	steps: number;
	startedAt: number;
	endedAt: number | null;
	videos: Pick<LibraryVideo, 'id' | 'fileId' | 'url' | 'name' | 'title' | 'size' | 'contentType' | 'createdAt'>[];
	runner: { runId: string; agent: string; step?: number | null; startedAt?: number | null; activity?: string } | null;
	error: string;
	/** Where a stopped or failed task ended: the enhancement, Hermes' turn, or the runner. */
	endedIn: 'prep' | 'make' | 'runner' | null;
};

const jsonHeaders = (token: string) => ({ ...headers(token), 'Content-Type': 'application/json' });

/** 开始制作: a new Hermes chat with the brief and its files, started on the server. */
export const startVideoTask = async (
	token: string,
	form: { brief: string; idea: string; files: { id: string; name: string; type: string }[]; maker: string }
): Promise<VideoTask> =>
	fetch(`${VIDEO_STUDIO_API_BASE_URL}/tasks`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify(form)
	}).then(parseJsonResponse<VideoTask>);

/** The newest tasks, newest first. */
export const getVideoTasks = async (token: string, limit = 8): Promise<VideoTask[]> => {
	const res = await fetch(`${VIDEO_STUDIO_API_BASE_URL}/tasks?limit=${limit}`, {
		method: 'GET',
		headers: headers(token)
	}).then(parseJsonResponse<VideoTask[]>);
	return Array.isArray(res) ? res.filter((t) => t?.chatId) : [];
};

/** One task (its chat's card). 404 once the chat is deleted. */
export const getVideoTask = async (token: string, chatId: string): Promise<VideoTask> =>
	fetch(`${VIDEO_STUDIO_API_BASE_URL}/tasks/${encodeURIComponent(chatId)}`, {
		method: 'GET',
		headers: headers(token)
	}).then(parseJsonResponse<VideoTask>);

/** Stops the Hermes turn at work on it, or the runner it handed the work to. */
export const stopVideoTask = async (token: string, chatId: string): Promise<VideoTask> =>
	fetch(`${VIDEO_STUDIO_API_BASE_URL}/tasks/${encodeURIComponent(chatId)}/stop`, {
		method: 'POST',
		headers: headers(token)
	}).then(parseJsonResponse<VideoTask>);

/** Still moving: worth reading again. */
export const videoTaskLive = (task: VideoTask | null | undefined) =>
	task?.state === 'running' || task?.state === 'background';

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

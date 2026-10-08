import { WEBUI_API_BASE_URL } from '$lib/constants';
import { parseJsonResponse } from '../response';

// 收藏 (backend/open_webui/routers/bookmarks.py)
export type MessageBookmark = {
	id: string;
	chat_id: string;
	message_id: string;
	role: string | null;
	excerpt: string | null;
	created_at: number;
	chat_title: string;
	chat_archived: boolean;
};

const request = async <T>(token: string, path: string, init: RequestInit = {}): Promise<T> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/bookmarks${path}`, {
		...init,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(parseJsonResponse)
		.catch((err) => {
			error = err?.detail ?? err;
			return null;
		});
	if (error) throw error;
	return res as T;
};

export const getBookmarks = (token: string) => request<MessageBookmark[]>(token, '/');

export const getChatBookmarkIds = (token: string, chatId: string) =>
	request<string[]>(token, `/chat/${encodeURIComponent(chatId)}`);

export const addBookmark = (token: string, chatId: string, messageId: string) =>
	request<MessageBookmark>(token, '/', {
		method: 'POST',
		body: JSON.stringify({ chat_id: chatId, message_id: messageId })
	});

export const removeBookmarkByMessage = (token: string, chatId: string, messageId: string) =>
	request<boolean>(
		token,
		`/chat/${encodeURIComponent(chatId)}/${encodeURIComponent(messageId)}`,
		{ method: 'DELETE' }
	);

export const removeBookmark = (token: string, id: string) =>
	request<boolean>(token, `/${encodeURIComponent(id)}`, { method: 'DELETE' });

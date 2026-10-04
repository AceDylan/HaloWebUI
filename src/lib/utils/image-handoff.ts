// Carrying an image between a chat and the image studio. A chat's image opens
// in the studio through the address (/workspace/images?reference=…); a studio
// image goes to a new chat through sessionStorage, read once by the chat page.
// Only this server's own files travel: a link to anything else is ignored, so a
// crafted address cannot make the image model fetch an outside URL.

const FILE_CONTENT_PATH = /^(?:\/[^?#]*)?\/api\/v1\/files\/([A-Za-z0-9_-]{1,128})\/content$/;

/** The file id behind a file's content address (relative, or absolute on `origin`); '' otherwise. */
export const imageFileIdFromUrl = (url: unknown, origin = ''): string => {
	const text = typeof url === 'string' ? url.trim() : '';
	if (!text) return '';
	let path = text;
	if (/^[a-z][a-z0-9+.-]*:/i.test(text)) {
		try {
			const parsed = new URL(text);
			if (!origin || parsed.origin !== origin) return '';
			path = parsed.pathname;
		} catch {
			return '';
		}
	} else if (!text.startsWith('/') || text.startsWith('//')) {
		return '';
	}
	return path.match(FILE_CONTENT_PATH)?.[1] ?? '';
};

const PROMPT_MAX_CHARS = 1500;

/** The studio address that opens `url` as a reference image, with the prompt that made it. */
export const studioUrlForImage = (url: string, prompt = ''): string => {
	const params = new URLSearchParams({ tab: 'workbench', reference: url });
	const text = prompt.trim().slice(0, PROMPT_MAX_CHARS);
	if (text) params.set('prompt', text);
	return `/workspace/images?${params.toString()}`;
};

/** What the studio was asked to open: a file id (or '') and a prompt (or ''). */
export const readStudioRequest = (search: string, origin = '') => {
	const params = new URLSearchParams(search);
	return {
		fileId: imageFileIdFromUrl(params.get('reference'), origin),
		prompt: (params.get('prompt') ?? '').trim().slice(0, PROMPT_MAX_CHARS)
	};
};

export const CHAT_IMAGE_HANDOFF_KEY = 'halo.chatImageHandoff';
// Left over from a tab closed before the chat opened: not picked up later.
const HANDOFF_TTL_MS = 5 * 60 * 1000;

// `model` is the image model the studio was using, so the chat can pick the same one.
export type ChatImageHandoff = { fileId: string; name: string; model: string; at: number };

export const serializeChatImageHandoff = (
	url: string,
	name = '',
	model = '',
	now = Date.now()
): string | null => {
	const fileId = imageFileIdFromUrl(url, typeof location === 'undefined' ? '' : location.origin);
	if (!fileId) return null;
	return JSON.stringify({
		fileId,
		name: name.trim().slice(0, 120),
		model: model.trim().slice(0, 200),
		at: now
	});
};

export const parseChatImageHandoff = (
	raw: string | null | undefined,
	now = Date.now()
): ChatImageHandoff | null => {
	if (!raw) return null;
	try {
		const value = JSON.parse(raw);
		const fileId = typeof value?.fileId === 'string' ? value.fileId : '';
		const at = Number(value?.at);
		if (!/^[A-Za-z0-9_-]{1,128}$/.test(fileId)) return null;
		if (!Number.isFinite(at) || now - at > HANDOFF_TTL_MS || at - now > 60_000) return null;
		return {
			fileId,
			name: typeof value.name === 'string' ? value.name : '',
			model: typeof value.model === 'string' ? value.model : '',
			at
		};
	} catch {
		return null;
	}
};

/**
 * The composer attachment for a handed-off image (already on the server, nothing
 * to upload). No `itemId`: that marks a file the composer uploaded itself, which
 * removing it from the message box deletes from the server. This image belongs
 * to the gallery or a chat, so removing it must only take it out of the box.
 */
export const chatImageFileFromHandoff = (
	handoff: Pick<ChatImageHandoff, 'fileId' | 'name'>,
	apiBaseUrl: string
) => ({
	type: 'image',
	id: handoff.fileId,
	url: `${apiBaseUrl}/files/${handoff.fileId}/content`,
	name: handoff.name || 'image.png',
	status: 'uploaded'
});

/** Reads the handed-off image once (it is removed either way). */
export const takeChatImageHandoff = (
	storage: Pick<Storage, 'getItem' | 'removeItem'> | null | undefined,
	now = Date.now()
): ChatImageHandoff | null => {
	if (!storage) return null;
	try {
		const raw = storage.getItem(CHAT_IMAGE_HANDOFF_KEY);
		if (raw === null) return null;
		storage.removeItem(CHAT_IMAGE_HANDOFF_KEY);
		return parseChatImageHandoff(raw, now);
	} catch {
		return null;
	}
};

// "Edit this one" on an image in the open chat: the chat page puts it in the
// message box with image generation on.
export const CHAT_EDIT_IMAGE_EVENT = 'halo:edit-image';
export type ChatEditImageDetail = { fileId: string; name: string };

export const requestChatImageEdit = (url: string, name = ''): boolean => {
	if (typeof window === 'undefined') return false;
	const fileId = imageFileIdFromUrl(url, window.location.origin);
	if (!fileId) return false;
	const detail: ChatEditImageDetail = { fileId, name: name.trim().slice(0, 120) };
	window.dispatchEvent(new CustomEvent(CHAT_EDIT_IMAGE_EVENT, { detail }));
	return true;
};

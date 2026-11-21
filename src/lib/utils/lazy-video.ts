import { WEBUI_API_BASE_URL } from '$lib/constants';

/**
 * Videos that show without being fetched. A `<video preload="metadata">` still buffers megabytes
 * in Chrome to paint its first frame; a chat or a library page with several of them filled a slow
 * link (the proxy across the sea) so every other click waited behind the video bytes. Players
 * here fetch nothing until played and show a small first-frame JPEG the server cuts once
 * (GET /video-studio/thumb/{fileId}, backend utils/video_cover.thumbnail).
 */
export const videoThumbUrl = (fileId: string): string =>
	`${WEBUI_API_BASE_URL}/video-studio/thumb/${encodeURIComponent(fileId)}`;

const FILE_CONTENT = /\/api\/v1\/files\/([A-Za-z0-9-]+)\/content(?:[?#][^"']*)?$/;

/** The file id of a stored file's content URL, '' for any other URL. */
export const storedFileId = (src: string): string => FILE_CONTENT.exec(String(src || ''))?.[1] ?? '';

/** Every `<video>` of *html* (already sanitized) set to fetch nothing until played, with the
 * first-frame poster when it plays one of the stored files and has none of its own. */
export const lazyVideoHtml = (html: string): string =>
	String(html || '').replace(/<video\b([^>]*)>/gi, (_tag, attrs: string) => {
		let out = /\spreload\s*=/i.test(attrs)
			? attrs.replace(/\spreload\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/i, ' preload="none"')
			: `${attrs} preload="none"`;
		if (!/\sposter\s*=/i.test(out)) {
			const src = /\ssrc\s*=\s*"([^"]*)"|\ssrc\s*=\s*'([^']*)'/i.exec(out);
			const fileId = storedFileId(src?.[1] ?? src?.[2] ?? '');
			if (fileId) out = `${out} poster="${videoThumbUrl(fileId)}"`;
		}
		return `<video${out}>`;
	});

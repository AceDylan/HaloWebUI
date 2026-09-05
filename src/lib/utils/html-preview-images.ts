import { collectSameOriginPreviewImageSources, inlineHtmlPreviewImages } from './html-preview';

// The preview iframe is an opaque-origin sandbox with `img-src data: blob:`,
// so a same-origin upload such as /api/v1/files/<id>/content can never load
// inside it. The parent page is authenticated and same-origin: it fetches the
// bytes once and hands the document a data: URL instead. Kept out of
// html-preview.ts so the pure helpers there stay testable without fetch.

export const HTML_PREVIEW_INLINE_IMAGE_MAX_BYTES = 8 * 1024 * 1024;
const MAX_CACHE_ENTRIES = 64;

const dataUrlCache = new Map<string, Promise<string | null>>();

const readBlobAsDataUrl = (blob: Blob) =>
	new Promise<string>((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result ?? ''));
		reader.onerror = () => reject(reader.error ?? new Error('Failed to read image'));
		reader.readAsDataURL(blob);
	});

const fetchSameOriginImageDataUrl = async (path: string): Promise<string | null> => {
	try {
		const headers: Record<string, string> = {};
		const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null;
		if (token) {
			headers.Authorization = `Bearer ${token}`;
		}
		const response = await fetch(path, { headers, credentials: 'same-origin' });
		if (!response.ok) {
			return null;
		}
		const blob = await response.blob();
		if (
			!blob.type.startsWith('image/') ||
			blob.size === 0 ||
			blob.size > HTML_PREVIEW_INLINE_IMAGE_MAX_BYTES
		) {
			return null;
		}
		const dataUrl = await readBlobAsDataUrl(blob);
		return dataUrl.startsWith('data:image/') ? dataUrl : null;
	} catch {
		return null;
	}
};

export const resolveSameOriginPreviewImage = (path: string): Promise<string | null> => {
	let pending = dataUrlCache.get(path);
	if (!pending) {
		pending = fetchSameOriginImageDataUrl(path).then((result) => {
			if (result === null) {
				// Leave failures uncached so a transient error retries next render.
				dataUrlCache.delete(path);
			}
			return result;
		});
		if (dataUrlCache.size >= MAX_CACHE_ENTRIES) {
			const oldest = dataUrlCache.keys().next().value;
			if (oldest !== undefined) {
				dataUrlCache.delete(oldest);
			}
		}
		dataUrlCache.set(path, pending);
	}
	return pending;
};

const currentOrigin = () => (typeof location !== 'undefined' ? location.origin : '');

export const hasSameOriginPreviewImages = (html: string | null | undefined): boolean =>
	Boolean(html) && collectSameOriginPreviewImageSources(String(html), currentOrigin()).length > 0;

export const inlineSameOriginPreviewImages = (html: string): Promise<string> =>
	inlineHtmlPreviewImages(html, resolveSameOriginPreviewImage, currentOrigin());

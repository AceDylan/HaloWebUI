// File names for downloaded images. Generated images live at /api/v1/files/<id>/content, so the
// last path segment ("content") is no name at all; data: URLs have none either.

const EXTENSIONS: Record<string, string> = {
	'image/png': 'png',
	'image/jpeg': 'jpg',
	'image/webp': 'webp',
	'image/gif': 'gif',
	'image/svg+xml': 'svg',
	'image/avif': 'avif'
};

const lastSegment = (url: string): string => {
	if (!url || url.startsWith('data:') || url.startsWith('blob:')) return '';
	const path = url.split(/[?#]/)[0];
	try {
		return decodeURIComponent(path.slice(path.lastIndexOf('/') + 1));
	} catch {
		return path.slice(path.lastIndexOf('/') + 1);
	}
};

/**
 * A file name for an image download: the URL's own name when it has an extension, otherwise the
 * caption (or `fallback`) with the extension of the downloaded type.
 */
export const imageDownloadName = (
	url: string,
	caption = '',
	mimeType = '',
	fallback = 'image'
): string => {
	const own = lastSegment(url);
	if (/^[^.].*\.[a-z0-9]{2,5}$/i.test(own)) return own;
	const base =
		`${caption ?? ''}`
			.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ')
			.replace(/\s+/g, ' ')
			.trim()
			.slice(0, 60)
			.trim() || fallback;
	const type = `${mimeType ?? ''}`.split(';')[0].trim().toLowerCase();
	const ext = EXTENSIONS[type] ?? (type.startsWith('image/') ? type.slice(6).split('+')[0] : 'png');
	return `${base}.${ext}`;
};

/** Fetches the image and saves it under {@link imageDownloadName}. */
export const downloadImageFile = async (url: string, caption = '', fallback = 'image') => {
	const response = await fetch(url);
	const blob = await response.blob();
	const objectUrl = URL.createObjectURL(blob);
	const link = document.createElement('a');
	link.href = objectUrl;
	link.download = imageDownloadName(url, caption, blob.type, fallback);
	document.body.appendChild(link);
	link.click();
	link.remove();
	setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
};

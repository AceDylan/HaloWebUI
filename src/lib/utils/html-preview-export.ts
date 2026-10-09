import {
	hardenHtmlArtifactExportDocument,
	HTML_ARTIFACT_EXPORT_MAX_SNAPSHOT_CHARS,
	HTML_EXPORT_SANDBOX,
	HTML_PREVIEW_REFERRER_POLICY,
	isActiveHtmlArtifactSnapshotMessage
} from './html-preview';

// Turning a sandboxed HTML preview into a PNG. The preview frame runs the
// author's scripts in an opaque origin, so the host cannot read it directly:
// the frame's snapshot bridge (PREVIEW_SNAPSHOT_BRIDGE) serialises its live DOM
// on request, the host strips everything that could execute or fetch, and
// html2canvas draws the result inside a script-less same-origin frame.

export type HtmlPreviewExportOptions = {
	/**
	 * Keep the dark-theme adaptation the reader is looking at. Off by default:
	 * an export is the document in the author's own palette.
	 */
	keepTheme?: boolean;
	timeoutMs?: number;
};

type HtmlPreviewSnapshot = { html: string; width: unknown; height: unknown };

const EXPORT_TIMEOUT_MS = 30_000;
const MAX_PNG_BYTES = 80_000_000;

const clampNumber = (value: number, min: number, max: number) =>
	Math.max(min, Math.min(max, value));

const sanitizeCssUrls = (value: string) =>
	value
		.replace(/@import\s+[^;]+;?/gi, '')
		.replace(/(?:-webkit-)?image-set\(([^)]*)\)/gi, (match, body) =>
			/data:/i.test(body) ? match : 'none'
		)
		.replace(/url\(\s*(['"]?)(.*?)\1\s*\)/gi, (match, _quote, url) => {
			const normalized = String(url ?? '').trim();
			return normalized.startsWith('data:') || normalized.startsWith('#') ? match : 'url("")';
		});

export const sanitizeHtmlArtifactSnapshot = (snapshot: string, keepTheme = false) => {
	const parsed = new DOMParser().parseFromString(snapshot, 'text/html');
	parsed
		.querySelectorAll('script,noscript,base,link,iframe,object,embed,meta[http-equiv]')
		.forEach((node) => node.remove());

	const urlAttributes = new Set(['action', 'formaction', 'poster', 'srcdoc', 'srcset', 'data']);
	parsed.querySelectorAll('*').forEach((element) => {
		for (const attribute of Array.from(element.attributes)) {
			const name = attribute.name.toLowerCase();
			const value = attribute.value.trim();
			if (name.startsWith('on') || urlAttributes.has(name)) {
				element.removeAttribute(attribute.name);
				continue;
			}
			if (name === 'src') {
				if (!value.toLowerCase().startsWith('data:image/')) {
					element.removeAttribute(attribute.name);
				}
				continue;
			}
			if (name === 'href' || name === 'xlink:href') {
				if (!value.startsWith('#') && !value.toLowerCase().startsWith('data:image/')) {
					element.removeAttribute(attribute.name);
				}
				continue;
			}
			if (name === 'style') {
				const sanitized = sanitizeCssUrls(attribute.value);
				if (sanitized.trim()) element.setAttribute(attribute.name, sanitized);
				else element.removeAttribute(attribute.name);
			}
		}
	});
	parsed.querySelectorAll('style').forEach((style) => {
		style.textContent = sanitizeCssUrls(style.textContent ?? '');
	});

	return hardenHtmlArtifactExportDocument(`<!DOCTYPE html>${parsed.documentElement.outerHTML}`, {
		keepTheme
	});
};

const isTransparent = (color: string) =>
	!color || color === 'transparent' || /^rgba\(.*,\s*0\)$/.test(color.replace(/\s+/g, ' '));

// The page colour behind the document: the root's, else the body's, else white.
const documentBackground = (frameDocument: Document) => {
	const view = frameDocument.defaultView;
	for (const element of [frameDocument.documentElement, frameDocument.body]) {
		const color = element && view ? view.getComputedStyle(element).backgroundColor : '';
		if (!isTransparent(color)) return color;
	}
	return '#ffffff';
};

export const renderHtmlSnapshotPng = async (
	snapshot: string,
	rawWidth: unknown,
	rawHeight: unknown,
	keepTheme = false
): Promise<Blob> => {
	const width = clampNumber(Math.ceil(Number(rawWidth) || 320), 320, 2048);
	const maxBasePixels = 16_000_000;
	const maxHeight = Math.min(16_384, Math.floor(maxBasePixels / width));
	const height = clampNumber(Math.ceil(Number(rawHeight) || 1), 1, maxHeight);
	const maxRenderedPixels = 16_000_000;
	const scale = clampNumber(Math.sqrt(maxRenderedPixels / Math.max(width * height, 1)), 1, 2);
	const exportDocument = sanitizeHtmlArtifactSnapshot(snapshot, keepTheme);
	const exportFrame = document.createElement('iframe');
	exportFrame.setAttribute('sandbox', HTML_EXPORT_SANDBOX);
	exportFrame.referrerPolicy = HTML_PREVIEW_REFERRER_POLICY;
	exportFrame.setAttribute('aria-hidden', 'true');
	exportFrame.style.cssText = `position:fixed;left:-100000px;top:0;width:${width}px;height:${height}px;opacity:0;pointer-events:none;border:0;z-index:-1;`;

	try {
		const loaded = new Promise<void>((resolve, reject) => {
			exportFrame.addEventListener('load', () => resolve(), { once: true });
			exportFrame.addEventListener(
				'error',
				() => reject(new Error('Export document failed to load')),
				{ once: true }
			);
		});
		exportFrame.srcdoc = exportDocument;
		document.body.appendChild(exportFrame);
		await loaded;

		const frameDocument = exportFrame.contentDocument;
		if (!frameDocument?.documentElement) {
			throw new Error('Export document is unavailable');
		}
		await frameDocument.fonts?.ready.catch(() => undefined);
		const { default: html2canvas } = await import('html2canvas-pro');
		const canvas = await html2canvas(frameDocument.documentElement, {
			allowTaint: false,
			backgroundColor: documentBackground(frameDocument),
			height,
			logging: false,
			removeContainer: true,
			scale,
			scrollX: 0,
			scrollY: 0,
			useCORS: false,
			width,
			windowHeight: height,
			windowWidth: width,
			x: 0,
			y: 0
		});
		const blob = await new Promise<Blob>((resolve, reject) => {
			canvas.toBlob((value) => {
				if (value) resolve(value);
				else reject(new Error('PNG encoding failed'));
			}, 'image/png');
		});
		if (blob.size > MAX_PNG_BYTES) {
			throw new Error('Exported PNG exceeds the 80 MB safety limit');
		}
		return blob;
	} finally {
		exportFrame.remove();
	}
};

const createExportRequestId = () =>
	`halo-html-export-${Array.from(crypto.getRandomValues(new Uint32Array(4)), (value) =>
		value.toString(16).padStart(8, '0')
	).join('')}`;

export class HtmlPreviewExportTimeoutError extends Error {
	constructor() {
		super('PNG export timed out');
		this.name = 'HtmlPreviewExportTimeoutError';
	}
}

/** A short reason for a failed export, or '' when there is none worth showing. */
export const htmlPreviewExportErrorMessage = (error: unknown): string =>
	String(error instanceof Error ? error.message : (error ?? ''))
		.trim()
		.slice(0, 300);

/** Asks a preview frame for a serialised copy of its current DOM. */
export const requestHtmlPreviewSnapshot = (
	frame: HTMLIFrameElement,
	{ keepTheme = false, timeoutMs = EXPORT_TIMEOUT_MS }: HtmlPreviewExportOptions = {}
): Promise<HtmlPreviewSnapshot> =>
	new Promise((resolve, reject) => {
		const target = frame.contentWindow;
		if (!target) {
			reject(new Error('No HTML preview is available to export.'));
			return;
		}
		const requestId = createExportRequestId();
		const finish = () => {
			clearTimeout(timer);
			window.removeEventListener('message', onMessage);
		};
		const onMessage = (event: MessageEvent) => {
			if (event.source !== target) return;
			const data = event.data;
			if (!isActiveHtmlArtifactSnapshotMessage(data, requestId, true)) return;
			finish();
			if (data.ok !== true) {
				reject(
					new Error(typeof data.error === 'string' ? data.error : 'Failed to capture preview')
				);
				return;
			}
			if (
				typeof data.html !== 'string' ||
				!data.html.trim() ||
				data.html.length > HTML_ARTIFACT_EXPORT_MAX_SNAPSHOT_CHARS
			) {
				reject(new Error('HTML preview snapshot is invalid or too large'));
				return;
			}
			resolve({ html: data.html, width: data.width, height: data.height });
		};
		const timer = setTimeout(() => {
			finish();
			reject(new HtmlPreviewExportTimeoutError());
		}, timeoutMs);
		window.addEventListener('message', onMessage);
		target.postMessage({ type: 'halo-html-preview-export-snapshot', requestId, keepTheme }, '*');
	});

/** The preview frame's current document as a PNG. */
export const captureHtmlPreviewPng = async (
	frame: HTMLIFrameElement,
	options: HtmlPreviewExportOptions = {}
): Promise<Blob> => {
	const snapshot = await requestHtmlPreviewSnapshot(frame, options);
	return renderHtmlSnapshotPng(
		snapshot.html,
		snapshot.width,
		snapshot.height,
		options.keepTheme ?? false
	);
};

/**
 * Copies a PNG that is still being rendered. The ClipboardItem is created
 * right away, inside the click, with the blob as a promise: Safari only allows
 * clipboard writes that start within the user gesture, and the render takes
 * longer than that gesture lasts.
 */
export const copyPngToClipboard = async (png: Promise<Blob>): Promise<void> => {
	if (typeof ClipboardItem === 'undefined' || !navigator.clipboard?.write) {
		throw new Error('Copying images is not supported in this browser');
	}
	await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]);
};

export const downloadBlob = (blob: Blob, filename: string) => {
	const url = URL.createObjectURL(blob);
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	document.body.appendChild(link);
	link.click();
	link.remove();
	setTimeout(() => URL.revokeObjectURL(url), 0);
};

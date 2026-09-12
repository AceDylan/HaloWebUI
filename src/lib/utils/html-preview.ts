import { marked } from 'marked';

export const HTML_PREVIEW_SANDBOX = 'allow-scripts';
export const HTML_EXPORT_SANDBOX = 'allow-same-origin';
export const HTML_PREVIEW_REFERRER_POLICY = 'no-referrer';
export const HTML_ARTIFACT_EXPORT_MAX_SNAPSHOT_CHARS = 2_000_000;
export const INLINE_HTML_PREVIEW_MIN_HEIGHT = 200;
export const INLINE_HTML_PREVIEW_MAX_HEIGHT = 1200;

/**
 * Which palette the preview document is rendered for. `dark` adds a bounded
 * adaptation layer (see PREVIEW_DARK_THEME_BRIDGE); `light` is the document
 * exactly as the author wrote it.
 */
export type HtmlPreviewColorScheme = 'light' | 'dark';

export const isActiveHtmlArtifactSnapshotMessage = (
	data: unknown,
	requestId: string | null,
	exporting: boolean
): data is { type: string; requestId: string; ok?: unknown; [key: string]: unknown } =>
	exporting === true &&
	typeof requestId === 'string' &&
	requestId.length > 0 &&
	typeof data === 'object' &&
	data !== null &&
	(data as { type?: unknown }).type === 'halo-html-preview-export-snapshot-result' &&
	typeof (data as { requestId?: unknown }).requestId === 'string' &&
	(data as { requestId: string }).requestId === requestId;

export const isInlineHtmlPreviewResizeMessage = (
	data: unknown
): data is { type: 'halo-html-preview-resize'; height: number } =>
	typeof data === 'object' &&
	data !== null &&
	(data as { type?: unknown }).type === 'halo-html-preview-resize' &&
	typeof (data as { height?: unknown }).height === 'number' &&
	Number.isFinite((data as { height: number }).height) &&
	(data as { height: number }).height > 0;

export const getInlineHtmlPreviewHeight = (data: unknown): number | null => {
	if (!isInlineHtmlPreviewResizeMessage(data)) {
		return null;
	}

	return Math.round(
		Math.max(INLINE_HTML_PREVIEW_MIN_HEIGHT, Math.min(INLINE_HTML_PREVIEW_MAX_HEIGHT, data.height))
	);
};

export const HTML_PREVIEW_CSP = [
	"default-src 'none'",
	"base-uri 'none'",
	"object-src 'none'",
	"frame-src 'none'",
	"connect-src 'none'",
	"form-action 'none'",
	"script-src 'unsafe-inline' blob:",
	"style-src 'unsafe-inline'",
	'img-src data: blob:',
	'font-src data:',
	'media-src data: blob:',
	'worker-src blob:'
].join('; ');

export const HTML_EXPORT_CSP = [
	"default-src 'none'",
	"base-uri 'none'",
	"object-src 'none'",
	"frame-src 'none'",
	"connect-src 'none'",
	"form-action 'none'",
	"script-src 'none'",
	"style-src 'unsafe-inline'",
	'img-src data:',
	'font-src data:',
	"media-src 'none'",
	"worker-src 'none'"
].join('; ');

const PREVIEW_POLICY_MARKER = 'data-halo-html-preview-policy="true"';
const EXPORT_POLICY_MARKER = 'data-halo-html-export-policy="true"';
const PREVIEW_NAVIGATION_GUARD = `<script data-halo-html-preview-guard="true">(() => {
	document.addEventListener('click', (event) => {
		const target = event.target instanceof Element ? event.target.closest('a[href]') : null;
		const href = target?.getAttribute('href')?.trim() ?? '';
		if (target && href && !href.startsWith('#')) event.preventDefault();
	}, true);
	document.addEventListener('submit', (event) => event.preventDefault(), true);
})();</script>`;
const PREVIEW_RESIZE_BRIDGE = `<script data-halo-html-preview-resize="true">(() => {
	let frame = 0;
	const reportSize = () => {
		frame = 0;
		const root = document.documentElement;
		const body = document.body || root;
		const height = Math.ceil(Math.max(
			root.scrollHeight,
			body.scrollHeight,
			1
		));
		parent.postMessage({ type: 'halo-html-preview-resize', height }, '*');
	};
	const scheduleSize = () => {
		if (frame) cancelAnimationFrame(frame);
		frame = requestAnimationFrame(reportSize);
	};
	const resizeObserver = new ResizeObserver(scheduleSize);
	resizeObserver.observe(document.documentElement);
	if (document.body) resizeObserver.observe(document.body);
	new MutationObserver(scheduleSize).observe(document.documentElement, {
		childList: true,
		subtree: true,
		attributes: true,
		characterData: true
	});
	window.addEventListener('load', scheduleSize, { once: true });
	scheduleSize();
})();</script>`;
const PREVIEW_SNAPSHOT_BRIDGE = `<script data-halo-html-preview-snapshot="true">(() => {
	const getSize = () => {
		const root = document.documentElement;
		const body = document.body || root;
		return {
			width: Math.ceil(Math.max(root.scrollWidth, body.scrollWidth, root.offsetWidth, body.offsetWidth, root.clientWidth, 320)),
			height: Math.ceil(Math.max(root.scrollHeight, body.scrollHeight, root.offsetHeight, body.offsetHeight, root.clientHeight, 1))
		};
	};
	window.addEventListener('message', (event) => {
		if (event.source !== parent) return;
		const message = event.data || {};
		if (message.type !== 'halo-html-preview-export-snapshot') return;
		event.stopImmediatePropagation();
		try {
			const clone = document.documentElement.cloneNode(true);
			clone.querySelectorAll('script,noscript').forEach((node) => node.remove());
			// Exports keep the author's palette: undo the dark-mode adaptation layer.
			clone.querySelectorAll('style[data-halo-artifact-dark-styles]').forEach((node) => node.remove());
			clone.querySelectorAll('[data-halo-dark-adapted]').forEach((node) => {
				const original = node.getAttribute('data-halo-orig-style');
				if (original) node.setAttribute('style', original);
				else node.removeAttribute('style');
				node.removeAttribute('data-halo-dark-adapted');
				node.removeAttribute('data-halo-orig-style');
			});
			clone.removeAttribute('data-halo-theme');
			const html = '<!DOCTYPE html>' + clone.outerHTML;
			if (html.length > ${HTML_ARTIFACT_EXPORT_MAX_SNAPSHOT_CHARS}) {
				throw new Error('HTML preview is too large to export safely');
			}
			parent.postMessage({
				type: 'halo-html-preview-export-snapshot-result',
				requestId: message.requestId,
				ok: true,
				html,
				...getSize()
			}, '*');
		} catch (error) {
			parent.postMessage({
				type: 'halo-html-preview-export-snapshot-result',
				requestId: message.requestId,
				ok: false,
				error: String(error?.message || error)
			}, '*');
		}
	});
})();</script>`;
// Dark-mode adaptation for answer previews. Almost every generated document
// hardcodes a light palette and none declare `prefers-color-scheme`, so in the
// dark theme the frame would sit as a white slab in the page. The rules are
// deliberately narrow: only *neutral* light backgrounds and *neutral* dark text
// are remapped, saturated colours are left alone (dark ones are brightened for
// contrast only), and images, SVG, canvas, video and gradients are never
// touched. Documents that declare their own dark palette (a
// `prefers-color-scheme` media rule, `<meta name="color-scheme">` with dark, or
// a `data-halo-color-scheme` root attribute) are left exactly as written; they
// only receive `data-halo-theme="dark"` on <html> so templates can hook it.
// Everything the script changes is recorded so exports can undo it.
const PREVIEW_DARK_THEME_BRIDGE = `<script data-halo-html-preview-theme="true">(() => {
	const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'SVG', 'CANVAS', 'IMG', 'VIDEO', 'AUDIO', 'PICTURE', 'IFRAME', 'OBJECT', 'EMBED', 'MATH', 'TEMPLATE', 'NOSCRIPT', 'SOURCE', 'TRACK']);
	const SIDES = ['top', 'right', 'bottom', 'left'];
	const MAX_ELEMENTS = 8000;
	const states = new WeakMap();
	const parse = (value) => {
		const text = String(value || '');
		if (!text.startsWith('rgb')) return null;
		const open = text.indexOf('(');
		const close = text.lastIndexOf(')');
		if (open < 0 || close < 0) return null;
		const parts = text.slice(open + 1, close).split(/[\\s,\\/]+/).filter(Boolean).map(Number);
		if (parts.length < 3 || parts.some((part) => Number.isNaN(part))) return null;
		return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
	};
	const channel = (value) => {
		const v = value / 255;
		return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
	};
	const luminance = (c) => 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
	const chroma = (c) => Math.max(c.r, c.g, c.b) - Math.min(c.r, c.g, c.b);
	const isLightNeutral = (c) => c.a >= 0.5 && chroma(c) <= 24 && luminance(c) >= 0.55;
	const isDark = (c) => c.a >= 0.5 && luminance(c) < 0.25;
	const rgb = (r, g, b, a) => (a >= 1 ? 'rgb(' + r + ', ' + g + ', ' + b + ')' : 'rgba(' + r + ', ' + g + ', ' + b + ', ' + a + ')');
	const clamp01 = (value) => Math.min(1, Math.max(0, value));
	const darkSurface = (c) => {
		const t = clamp01((luminance(c) - 0.55) / 0.45);
		const base = Math.round(24 + t * 14);
		return rgb(base, base + 1, base + 8, c.a);
	};
	const lightText = (c) => {
		const t = clamp01(luminance(c) / 0.4);
		const base = Math.round(230 - t * 76);
		return rgb(base, base + 2, base + 8, c.a);
	};
	const brighten = (c) => {
		const r = c.r / 255, g = c.g / 255, b = c.b / 255;
		const max = Math.max(r, g, b), min = Math.min(r, g, b);
		const l = (max + min) / 2;
		const d = max - min;
		let h = 0, s = 0;
		if (d > 0) {
			s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
			if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
			else if (max === g) h = (b - r) / d + 2;
			else h = (r - g) / d + 4;
			h *= 60;
		}
		return 'hsla(' + Math.round(h) + ', ' + Math.round(s * 100) + '%, ' + Math.round(Math.max(l, 0.7) * 100) + '%, ' + c.a + ')';
	};
	const authorHandlesDark = () => {
		const meta = document.querySelector('meta[name="color-scheme"]');
		if (meta && /dark/i.test(meta.getAttribute('content') || '')) return true;
		if (document.documentElement.hasAttribute('data-halo-color-scheme')) return true;
		for (const sheet of Array.from(document.styleSheets)) {
			let rules = null;
			try { rules = sheet.cssRules; } catch (error) { rules = null; }
			if (!rules) continue;
			for (const rule of Array.from(rules)) {
				if (rule.media && /prefers-color-scheme/i.test(rule.media.mediaText)) return true;
			}
		}
		return false;
	};
	const setStyle = (el, prop, value) => {
		if (el.dataset.haloDarkAdapted !== 'true') {
			el.dataset.haloDarkAdapted = 'true';
			el.dataset.haloOrigStyle = el.getAttribute('style') || '';
		}
		el.style.setProperty(prop, value, 'important');
	};
	const snapshot = (el) => {
		const cs = getComputedStyle(el);
		const borders = [];
		for (const side of SIDES) {
			const width = parseFloat(cs.getPropertyValue('border-' + side + '-width')) || 0;
			if (width > 0) borders.push({ side, color: parse(cs.getPropertyValue('border-' + side + '-color')) });
		}
		return {
			el,
			bg: parse(cs.backgroundColor),
			bgImage: cs.backgroundImage !== 'none',
			color: parse(cs.color),
			borders
		};
	};
	const parentState = (el) => {
		let node = el.parentElement;
		while (node) {
			const state = states.get(node);
			if (state !== undefined) return state;
			node = node.parentElement;
		}
		return true;
	};
	const adapt = (roots) => {
		const entries = [];
		const collect = (el) => {
			// SVG/MathML subtrees (lower-case tagName, foreign namespace) are never touched.
			if (entries.length >= MAX_ELEMENTS || el.namespaceURI !== 'http://www.w3.org/1999/xhtml' || SKIP_TAGS.has(el.tagName.toUpperCase())) return;
			entries.push(snapshot(el));
			for (const child of Array.from(el.children)) collect(child);
		};
		roots.forEach(collect);
		for (const entry of entries) {
			const el = entry.el;
			const inherited = parentState(el);
			let dark = inherited;
			if (entry.bgImage) {
				dark = false;
			} else if (entry.bg && entry.bg.a >= 0.5) {
				if (isLightNeutral(entry.bg)) {
					setStyle(el, 'background-color', darkSurface(entry.bg));
					dark = true;
				} else {
					dark = isDark(entry.bg);
				}
			}
			states.set(el, dark);
			const color = entry.color;
			if (color) {
				if (dark) {
					if (chroma(color) <= 40 && luminance(color) <= 0.4) setStyle(el, 'color', lightText(color));
					else if (luminance(color) < 0.3) setStyle(el, 'color', brighten(color));
				} else if (inherited && luminance(color) <= 0.5) {
					setStyle(el, 'color', rgb(color.r, color.g, color.b, color.a));
				}
			}
			if (dark) {
				for (const border of entry.borders) {
					if (border.color && isLightNeutral(border.color)) setStyle(el, 'border-' + border.side + '-color', 'rgba(255, 255, 255, 0.12)');
				}
			}
		}
	};
	let pending = new Set();
	let frame = 0;
	const flush = () => {
		frame = 0;
		const roots = Array.from(pending);
		pending = new Set();
		adapt(roots.filter((el) => el.isConnected && !states.has(el) && !(el.closest && el.closest('svg'))));
	};
	const observer = new MutationObserver((records) => {
		for (const record of records) {
			for (const node of Array.from(record.addedNodes)) if (node.nodeType === 1) pending.add(node);
		}
		if (pending.size && !frame) frame = requestAnimationFrame(flush);
	});
	const start = () => {
		document.documentElement.setAttribute('data-halo-theme', 'dark');
		if (authorHandlesDark()) return;
		// Measure the author's light rendering (the dark base off for the duration of this
		// task, so nothing is painted in between), then decide and apply with it back on.
		const darkBase = document.querySelector('style[data-halo-artifact-dark-styles]');
		if (darkBase) darkBase.disabled = true;
		try {
			adapt([document.documentElement]);
		} finally {
			if (darkBase) darkBase.disabled = false;
		}
		observer.observe(document.documentElement, { childList: true, subtree: true });
	};
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
	else start();
})();</script>`;
const COMMON_POLICY_META = [
	'<meta name="referrer" content="no-referrer">',
	'<meta name="viewport" content="width=device-width, initial-scale=1.0">',
	'<meta charset="UTF-8">'
];
const buildPreviewPolicyMeta = (
	labels: HtmlPreviewLabels = DEFAULT_HTML_PREVIEW_LABELS,
	colorScheme: HtmlPreviewColorScheme = 'light'
) =>
	[
		`<meta ${PREVIEW_POLICY_MARKER} http-equiv="Content-Security-Policy" content="${HTML_PREVIEW_CSP}">`,
		...COMMON_POLICY_META,
		PREVIEW_NAVIGATION_GUARD,
		PREVIEW_RESIZE_BRIDGE,
		PREVIEW_SNAPSHOT_BRIDGE,
		buildPreviewInteractionsBridge(labels),
		...(colorScheme === 'dark' ? [PREVIEW_DARK_THEME_BRIDGE] : [])
	].join('');
const EXPORT_POLICY_META = [
	`<meta ${EXPORT_POLICY_MARKER} http-equiv="Content-Security-Policy" content="${HTML_EXPORT_CSP}">`,
	...COMMON_POLICY_META
].join('');

const stripLeadingDoctype = (value: string) => value.replace(/^\s*<!doctype\s+html[^>]*>/i, '');

const ensureDoctype = (value: string) =>
	/^\s*<!doctype\s+html\b/i.test(value) ? value : `<!DOCTYPE html>${value}`;

const insertAfterOpeningTag = (document: string, tagName: string, content: string) =>
	document.replace(
		new RegExp(`<${tagName}\\b[^>]*>`, 'i'),
		(openingTag) => `${openingTag}${content}`
	);

const insertBeforeClosingTag = (document: string, tagName: string, content: string) => {
	const closingTag = new RegExp(`</${tagName}>`, 'i');
	if (closingTag.test(document)) {
		return document.replace(closingTag, `${content}</${tagName}>`);
	}
	if (new RegExp(`<${tagName}\\b[^>]*>`, 'i').test(document)) {
		return insertAfterOpeningTag(document, tagName, content);
	}
	return `${document}${content}`;
};

const stripInjectedPreviewPolicies = (html: unknown) =>
	String(html ?? '')
		.replace(/<meta\b(?=[^>]*\bdata-halo-html-preview-policy=["']true["'])[^>]*>/gi, '')
		.replace(/<meta\b(?=[^>]*\bdata-halo-html-export-policy=["']true["'])[^>]*>/gi, '')
		.replace(
			/<script\b(?=[^>]*\bdata-halo-html-preview-guard=["']true["'])[^>]*>[\s\S]*?<\/script>/gi,
			''
		)
		.replace(
			/<script\b(?=[^>]*\bdata-halo-html-preview-(?:snapshot|export|resize|interactions|theme)=["']true["'])[^>]*>[\s\S]*?<\/script>/gi,
			''
		);

const stripDarkArtifactStyles = (html: string) =>
	html.replace(
		/<style\b(?=[^>]*\bdata-halo-artifact-dark-styles=["']true["'])[^>]*>[\s\S]*?<\/style>/gi,
		''
	);

const hardenHtmlDocument = (html: unknown, policyMeta: string): string => {
	const source = stripInjectedPreviewPolicies(html);

	if (/<html\b[^>]*>/i.test(source)) {
		let document = ensureDoctype(source);
		if (/<head\b[^>]*>/i.test(document)) {
			return insertAfterOpeningTag(document, 'head', policyMeta);
		}
		return insertAfterOpeningTag(document, 'html', `<head>${policyMeta}</head>`);
	}

	if (/<(?:head|body)\b[^>]*>/i.test(source)) {
		return hardenHtmlDocument(
			`<!DOCTYPE html><html lang="en">${stripLeadingDoctype(source)}</html>`,
			policyMeta
		);
	}

	return `<!DOCTYPE html><html lang="en"><head>${policyMeta}</head><body>${stripLeadingDoctype(source)}</body></html>`;
};

export const hardenHtmlPreviewDocument = (
	html: unknown,
	labels: HtmlPreviewLabels = DEFAULT_HTML_PREVIEW_LABELS,
	colorScheme: HtmlPreviewColorScheme = 'light'
): string => hardenHtmlDocument(html, buildPreviewPolicyMeta(labels, colorScheme));

export const hardenHtmlArtifactExportDocument = (html: unknown): string => {
	const source = stripDarkArtifactStyles(stripInjectedPreviewPolicies(html))
		.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
		.replace(/<noscript\b[^>]*>[\s\S]*?<\/noscript>/gi, '')
		.replace(/<base\b[^>]*>/gi, '')
		.replace(/<meta\b(?=[^>]*\bhttp-equiv=["']?refresh\b)[^>]*>/gi, '');
	return hardenHtmlDocument(source, EXPORT_POLICY_META);
};

const normalizeCodeLanguage = (value: unknown) =>
	String(value ?? '')
		.trim()
		.toLowerCase()
		.split(/\s+/, 1)[0];

const HTML_ARTIFACT_CODE_LANGUAGES = new Set(['html']);

export const shouldMaskStreamingPreviewSource = (
	language: unknown,
	streaming: boolean,
	detectArtifacts: boolean,
	hideHtmlArtifactCodeBlocks: boolean
): boolean =>
	streaming &&
	detectArtifacts &&
	hideHtmlArtifactCodeBlocks &&
	HTML_ARTIFACT_CODE_LANGUAGES.has(normalizeCodeLanguage(language));

export const isHtmlArtifactSourceToken = (token: unknown): boolean => {
	if (!token || typeof token !== 'object') {
		return false;
	}

	const candidate = token as { type?: unknown; lang?: unknown; raw?: unknown; text?: unknown };
	if (candidate.type === 'code') {
		return HTML_ARTIFACT_CODE_LANGUAGES.has(normalizeCodeLanguage(candidate.lang));
	}

	if (candidate.type !== 'html') {
		return false;
	}

	const raw = String(candidate.raw ?? candidate.text ?? '').trim();
	return /^(?:<!doctype\s+html\b|<html\b)/i.test(raw);
};

const stripThinkingBlocks = (value: string) =>
	value.replace(/<(think|thinking|reasoning)\b[^>]*>[\s\S]*?<\/\1>/gi, '');

type ArtifactParts = {
	html: string[];
	css: string[];
	javascript: string[];
	/** Source token raw(s) behind each html entry, so callers can locate it in the Markdown. */
	htmlRaws: string[][];
};

const collectArtifactParts = (content: string): ArtifactParts => {
	const parts: ArtifactParts = { html: [], css: [], javascript: [], htmlRaws: [] };
	const tokens = marked.lexer(stripThinkingBlocks(content));
	let pendingRawDoctypeIndex = -1;

	marked.walkTokens(tokens, (token: any) => {
		if (token?.type === 'code') {
			pendingRawDoctypeIndex = -1;
			const language = normalizeCodeLanguage(token.lang);
			const code = String(token.text ?? '');
			if (language === 'html') {
				parts.html.push(code);
				parts.htmlRaws.push([String(token.raw ?? '')]);
			} else if (language === 'css') {
				parts.css.push(code);
			} else if (language === 'javascript' || language === 'js') {
				parts.javascript.push(code);
			}
			return;
		}

		if (token?.type !== 'html') {
			if (token?.type !== 'space') pendingRawDoctypeIndex = -1;
			return;
		}

		const raw = String(token.raw ?? token.text ?? '').trim();
		if (/^<!doctype\s+html\b[^>]*>$/i.test(raw)) {
			parts.html.push(raw);
			parts.htmlRaws.push([raw]);
			pendingRawDoctypeIndex = parts.html.length - 1;
		} else if (/^<html\b/i.test(raw)) {
			if (pendingRawDoctypeIndex === parts.html.length - 1) {
				parts.html[pendingRawDoctypeIndex] = `${parts.html[pendingRawDoctypeIndex]}${raw}`;
				parts.htmlRaws[pendingRawDoctypeIndex] = [...parts.htmlRaws[pendingRawDoctypeIndex], raw];
			} else {
				parts.html.push(raw);
				parts.htmlRaws.push([raw]);
			}
			pendingRawDoctypeIndex = -1;
		} else if (/^<style\b/i.test(raw)) {
			pendingRawDoctypeIndex = -1;
			parts.css.push(raw);
		} else if (/^<script\b/i.test(raw)) {
			pendingRawDoctypeIndex = -1;
			parts.javascript.push(raw);
		} else {
			pendingRawDoctypeIndex = -1;
		}
	});

	return parts;
};

// The light base stays in every document (exports rely on it); the dark base is
// appended after the author's styles so plain `body { background: #fff }` rules
// are overruled without touching anything else. Inline body styles and nested
// light panels are handled by PREVIEW_DARK_THEME_BRIDGE at runtime. The values
// mirror darkSurface(white) / lightText(black) in that script.
const ARTIFACT_LIGHT_STYLE =
	'<style data-halo-artifact-styles="true">body { background-color: white; }</style>';
const ARTIFACT_DARK_STYLE =
	'<style data-halo-artifact-dark-styles="true">:root { color-scheme: dark; } html { background-color: #1c1d24; } body { background-color: #26272e; color: #e6e8ee; }</style>';
const buildArtifactStyles = (colorScheme: HtmlPreviewColorScheme) =>
	colorScheme === 'dark' ? `${ARTIFACT_LIGHT_STYLE}${ARTIFACT_DARK_STYLE}` : ARTIFACT_LIGHT_STYLE;

export const buildHtmlArtifactPreview = (
	content: unknown,
	options: { labels?: HtmlPreviewLabels; colorScheme?: HtmlPreviewColorScheme } = {}
): string | null => {
	if (typeof content !== 'string' || !content.trim()) {
		return null;
	}

	const parts = collectArtifactParts(content);
	// A response is previewable only when it contains exactly one HTML source.
	// Separate CSS/JS fences and multiple HTML sources are ambiguous executable
	// artifacts and must remain inert Markdown instead of being merged here.
	if (parts.html.length !== 1 || parts.css.length !== 0 || parts.javascript.length !== 0) {
		return null;
	}

	const colorScheme = options.colorScheme ?? 'light';
	const style = buildArtifactStyles(colorScheme);
	const mergedHtml = renderMarkdownImagesInsideHtml(parts.html[0]);

	if (/(?:<!doctype\s+html\b|<html\b)/i.test(mergedHtml)) {
		let document = mergedHtml;
		if (/<head\b[^>]*>/i.test(document)) {
			document = insertBeforeClosingTag(document, 'head', style);
		} else if (/<html\b[^>]*>/i.test(document)) {
			document = insertAfterOpeningTag(document, 'html', `<head>${style}</head>`);
		}
		return hardenHtmlPreviewDocument(document, options.labels, colorScheme);
	}

	return hardenHtmlPreviewDocument(
		`<!DOCTYPE html><html lang="en"><head>${style}</head><body>${mergedHtml}</body></html>`,
		options.labels,
		colorScheme
	);
};

export const buildInlineHtmlArtifactPreview = (
	content: unknown,
	options: {
		enabled: boolean;
		streaming: boolean;
		labels?: HtmlPreviewLabels;
		colorScheme?: HtmlPreviewColorScheme;
	}
): string | null => {
	if (!options.enabled || options.streaming) {
		return null;
	}

	return buildHtmlArtifactPreview(content, {
		labels: options.labels,
		colorScheme: options.colorScheme
	});
};

export const shouldRenderInlineHtmlArtifactOriginalText = (
	preview: string | null,
	showOriginalText: boolean
): boolean => !preview || showOriginalText;

export const getCodePreviewEventKey = (
	language: unknown,
	code: unknown,
	streaming: boolean
): string | null => {
	if (streaming) {
		return null;
	}

	const normalizedLanguage = normalizeCodeLanguage(language);
	const normalizedCode = typeof code === 'string' ? code : '';
	if (!normalizedLanguage || !normalizedCode) {
		return null;
	}

	return `${normalizedLanguage}\u0000${normalizedCode}`;
};

// ---------------------------------------------------------------------------
// Preview interactions: copy buttons on <pre>, click-to-zoom on <img>, and
// same-origin image inlining. The iframe stays an opaque-origin sandbox; every
// action that needs the page's privileges (clipboard, lightbox, authenticated
// fetch) is delegated to the parent through postMessage.
// ---------------------------------------------------------------------------

export type HtmlPreviewLabels = { copy: string; copied: string; zoom: string };

export const DEFAULT_HTML_PREVIEW_LABELS: HtmlPreviewLabels = {
	copy: 'Copy',
	copied: 'Copied',
	zoom: 'Click to enlarge'
};

export const HTML_PREVIEW_COPY_MESSAGE_TYPE = 'halo-html-preview-copy';
export const HTML_PREVIEW_IMAGE_MESSAGE_TYPE = 'halo-html-preview-image';
export const HTML_PREVIEW_COPY_MAX_CHARS = 200_000;
export const HTML_PREVIEW_IMAGE_ALT_MAX_CHARS = 500;

export const isInlineHtmlPreviewCopyMessage = (
	data: unknown
): data is { type: typeof HTML_PREVIEW_COPY_MESSAGE_TYPE; text: string } =>
	typeof data === 'object' &&
	data !== null &&
	(data as { type?: unknown }).type === HTML_PREVIEW_COPY_MESSAGE_TYPE &&
	typeof (data as { text?: unknown }).text === 'string' &&
	(data as { text: string }).text.length > 0 &&
	(data as { text: string }).text.length <= HTML_PREVIEW_COPY_MAX_CHARS;

export const isInlineHtmlPreviewImageMessage = (
	data: unknown
): data is { type: typeof HTML_PREVIEW_IMAGE_MESSAGE_TYPE; src: string; alt?: string } =>
	typeof data === 'object' &&
	data !== null &&
	(data as { type?: unknown }).type === HTML_PREVIEW_IMAGE_MESSAGE_TYPE &&
	typeof (data as { src?: unknown }).src === 'string' &&
	/^data:image\//i.test((data as { src: string }).src) &&
	(typeof (data as { alt?: unknown }).alt === 'undefined' ||
		typeof (data as { alt?: unknown }).alt === 'string');

const SAME_ORIGIN_PREVIEW_IMAGE_PATH_RE =
	/^\/(?:api\/v1\/files\/[A-Za-z0-9_-]+\/content(?:\/[^?#"'\s]*)?|cache\/[^?#"'\s]+)(?:\?[^#"'\s]*)?$/;
const IMG_SRC_ATTRIBUTE_RE = /(<img\b[^>]*?\ssrc\s*=\s*)(?:"([^"]*)"|'([^']*)')/gi;

/** The same-origin path for an <img src> the parent may fetch on the preview's behalf, else null. */
export const normalizeSameOriginPreviewImageSource = (
	src: unknown,
	origin: string = ''
): string | null => {
	const value = String(src ?? '')
		.trim()
		.replace(/&amp;/g, '&');
	if (!value) {
		return null;
	}
	let path = value;
	if (/^[a-z][a-z0-9+.-]*:/i.test(value) && !/^https?:\/\//i.test(value)) {
		return null;
	}
	if (/^https?:\/\//i.test(value)) {
		const base = String(origin ?? '')
			.trim()
			.replace(/\/+$/, '');
		if (!base || !value.toLowerCase().startsWith(`${base.toLowerCase()}/`)) {
			return null;
		}
		path = value.slice(base.length);
	}
	if (value.startsWith('//')) {
		return null;
	}
	return SAME_ORIGIN_PREVIEW_IMAGE_PATH_RE.test(path) ? path : null;
};

export const collectSameOriginPreviewImageSources = (html: unknown, origin: string = ''): string[] => {
	const sources: string[] = [];
	for (const match of String(html ?? '').matchAll(IMG_SRC_ATTRIBUTE_RE)) {
		const path = normalizeSameOriginPreviewImageSource(match[2] ?? match[3] ?? '', origin);
		if (path && !sources.includes(path)) {
			sources.push(path);
		}
	}
	return sources;
};

/** Rewrites same-origin <img src> values to the data: URLs `resolve` returns; others are left alone. */
export const inlineHtmlPreviewImages = async (
	html: string,
	resolve: (path: string) => Promise<string | null>,
	origin: string = ''
): Promise<string> => {
	const sources = collectSameOriginPreviewImageSources(html, origin);
	if (sources.length === 0) {
		return html;
	}
	const resolved = new Map<string, string>();
	await Promise.all(
		sources.map(async (path) => {
			const dataUrl = await resolve(path).catch(() => null);
			if (typeof dataUrl === 'string' && /^data:image\//i.test(dataUrl)) {
				resolved.set(path, dataUrl);
			}
		})
	);
	if (resolved.size === 0) {
		return html;
	}
	return html.replace(
		IMG_SRC_ATTRIBUTE_RE,
		(whole: string, prefix: string, doubleQuoted?: string, singleQuoted?: string) => {
			const path = normalizeSameOriginPreviewImageSource(doubleQuoted ?? singleQuoted ?? '', origin);
			const dataUrl = path ? resolved.get(path) : undefined;
			return dataUrl ? `${prefix}"${dataUrl}"` : whole;
		}
	);
};

const escapeForInlineScript = (value: string) => value.replace(/</g, '\\u003c');

export const buildPreviewInteractionsBridge = (labels: HtmlPreviewLabels): string => {
	const serializedLabels = escapeForInlineScript(
		JSON.stringify({
			copy: String(labels?.copy || DEFAULT_HTML_PREVIEW_LABELS.copy),
			copied: String(labels?.copied || DEFAULT_HTML_PREVIEW_LABELS.copied),
			zoom: String(labels?.zoom || DEFAULT_HTML_PREVIEW_LABELS.zoom)
		})
	);
	return `<script data-halo-html-preview-interactions="true">(() => {
	const labels = ${serializedLabels};
	const STYLE_ID = 'halo-html-preview-interactions-style';
	const css = '.halo-pre-wrap{position:relative}'
		+ '.halo-copy-btn{position:absolute;top:6px;right:6px;z-index:5;font:12px/1 system-ui,-apple-system,sans-serif;padding:5px 9px;border-radius:6px;border:1px solid rgba(0,0,0,.14);background:rgba(255,255,255,.94);color:#333;cursor:pointer;opacity:0;transition:opacity .15s}'
		+ '.halo-pre-wrap:hover .halo-copy-btn,.halo-copy-btn:focus,.halo-copy-btn[data-copied="true"]{opacity:1}'
		+ 'img[data-halo-zoomable="true"]{cursor:zoom-in}';
	const ensureStyle = () => {
		if (document.getElementById(STYLE_ID)) return;
		const style = document.createElement('style');
		style.id = STYLE_ID;
		style.textContent = css;
		(document.head || document.documentElement).appendChild(style);
	};
	const post = (message) => parent.postMessage(message, '*');
	const codeText = (pre) => {
		const code = pre.querySelector('code');
		if (code) return code.textContent || '';
		const clone = pre.cloneNode(true);
		clone.querySelectorAll('.halo-copy-btn').forEach((node) => node.remove());
		return clone.textContent || '';
	};
	const decorate = () => {
		ensureStyle();
		document.querySelectorAll('pre').forEach((pre) => {
			if (pre.dataset.haloCopyReady === 'true') return;
			if (!codeText(pre).trim()) return;
			pre.dataset.haloCopyReady = 'true';
			pre.classList.add('halo-pre-wrap');
			const button = document.createElement('button');
			button.type = 'button';
			button.className = 'halo-copy-btn';
			button.textContent = labels.copy;
			button.setAttribute('aria-label', labels.copy);
			button.addEventListener('click', (event) => {
				event.preventDefault();
				event.stopPropagation();
				const text = codeText(pre);
				if (!text) return;
				post({ type: '${HTML_PREVIEW_COPY_MESSAGE_TYPE}', text });
				button.textContent = labels.copied;
				button.dataset.copied = 'true';
				setTimeout(() => {
					button.textContent = labels.copy;
					delete button.dataset.copied;
				}, 1600);
			});
			pre.appendChild(button);
		});
		document.querySelectorAll('img').forEach((img) => {
			if (img.dataset.haloZoomable === 'true') return;
			img.dataset.haloZoomable = 'true';
			if (!img.getAttribute('title')) img.setAttribute('title', labels.zoom);
		});
	};
	document.addEventListener('click', (event) => {
		const image = event.target instanceof Element ? event.target.closest('img') : null;
		if (!image) return;
		const src = image.currentSrc || image.src || '';
		if (!/^data:image\\//i.test(src)) return;
		event.preventDefault();
		post({ type: '${HTML_PREVIEW_IMAGE_MESSAGE_TYPE}', src, alt: image.getAttribute('alt') || '' });
	}, true);
	let frame = 0;
	const schedule = () => {
		if (frame) return;
		frame = requestAnimationFrame(() => { frame = 0; decorate(); });
	};
	const start = () => {
		decorate();
		new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
	};
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
	else start();
})();</script>`;
};

type HtmlArtifactSourceLocation = {
	source: string;
	firstRaw: string;
	lastRaw: string;
};

const resolveHtmlArtifactSource = (content: unknown): HtmlArtifactSourceLocation | null => {
	if (typeof content !== 'string' || !content.trim()) {
		return null;
	}
	const parts = collectArtifactParts(content);
	if (parts.html.length !== 1 || parts.css.length !== 0 || parts.javascript.length !== 0) {
		return null;
	}
	const raws = parts.htmlRaws[0] ?? [];
	if (raws.length === 0) {
		return null;
	}
	return { source: parts.html[0], firstRaw: raws[0], lastRaw: raws[raws.length - 1] };
};

/** The HTML source that the inline preview renders, for a "copy source" action. */
export const getHtmlArtifactSource = (content: unknown): string | null =>
	resolveHtmlArtifactSource(content)?.source ?? null;

/**
 * The Markdown around the previewed HTML source, so text, images and other
 * code blocks in the same answer keep rendering while the fence itself is
 * replaced by the preview frame.
 */
export const splitHtmlArtifactContent = (
	content: unknown
): { before: string; after: string; source: string } | null => {
	const located = resolveHtmlArtifactSource(content);
	if (!located) {
		return null;
	}
	const text = content as string;
	const start = text.indexOf(located.firstRaw);
	if (start < 0) {
		return null;
	}
	const lastIndex = text.indexOf(located.lastRaw, start);
	if (lastIndex < 0) {
		return null;
	}
	const end = lastIndex + located.lastRaw.length;
	return {
		before: text.slice(0, start).replace(/\s+$/, ''),
		after: text.slice(end).replace(/^\s+/, ''),
		source: located.source
	};
};

export type HtmlArtifactCompanionImage = { src: string; alt: string };

const MARKDOWN_IMAGE_RE = /!\[([^\]]*)\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+["'][^"']*["'])?\s*\)/g;
const HTML_IMAGE_TAG_RE = /<img\b[^>]*?\ssrc\s*=\s*(?:"([^"]*)"|'([^']*)')[^>]*>/gi;
const HTML_IMAGE_ALT_RE = /\salt\s*=\s*(?:"([^"]*)"|'([^']*)')/i;

const collectImagesFromMarkdown = (text: string): HtmlArtifactCompanionImage[] => {
	const images: HtmlArtifactCompanionImage[] = [];
	for (const match of text.matchAll(MARKDOWN_IMAGE_RE)) {
		const src = match[2].replace(/^<|>$/g, '').trim();
		if (src) {
			images.push({ src, alt: match[1].trim() });
		}
	}
	for (const match of text.matchAll(HTML_IMAGE_TAG_RE)) {
		const src = (match[1] ?? match[2] ?? '').trim();
		if (!src) {
			continue;
		}
		const alt = HTML_IMAGE_ALT_RE.exec(match[0]);
		images.push({ src, alt: (alt?.[1] ?? alt?.[2] ?? '').trim() });
	}
	return images;
};

/**
 * Images that sit in the Markdown around the previewed HTML but not inside it,
 * e.g. a generated picture the model shows before its HTML write-up. Preview
 * mode hides that Markdown, so only these are rendered next to the frame; the
 * text and code blocks stay behind "Show original text".
 */
export const collectHtmlArtifactCompanionImages = (
	content: unknown
): { before: HtmlArtifactCompanionImage[]; after: HtmlArtifactCompanionImage[] } | null => {
	const split = splitHtmlArtifactContent(content);
	if (!split) {
		return null;
	}
	// Only an actual <img> in the (rendered) HTML counts as "already shown";
	// the URL appearing as plain text in the HTML does not display anything.
	const seen = new Set<string>(collectHtmlImageSources(renderMarkdownImagesInsideHtml(split.source)));
	const keep = (image: HtmlArtifactCompanionImage) => {
		if (!/^(?:https?:\/\/|\/|data:image\/)/i.test(image.src)) {
			return false;
		}
		if (seen.has(image.src)) {
			return false;
		}
		seen.add(image.src);
		return true;
	};
	return {
		before: collectImagesFromMarkdown(split.before).filter(keep),
		after: collectImagesFromMarkdown(split.after).filter(keep)
	};
};

export const companionImagesToMarkdown = (images: HtmlArtifactCompanionImage[]): string =>
	images.map((image) => `![${image.alt.replace(/[\[\]]/g, ' ')}](${image.src})`).join('\n\n');

const MARKDOWN_IMAGE_IN_HTML_TEXT_RE =
	/!\[([^\]\n]*)\]\(\s*(\/api\/v1\/files\/[^)\s]+|\/cache\/[^)\s]+|https?:\/\/[^)\s]+|data:image\/[^)\s]+)\s*\)/g;
// One capture group so String.split keeps tags, comments and whole
// script/style elements at odd indexes; only the text between them is touched.
const HTML_MARKUP_SEGMENT_RE =
	/(<!--[\s\S]*?-->|<script\b[\s\S]*?<\/script\s*>|<style\b[\s\S]*?<\/style\s*>|<[^>]+>)/i;

const escapeHtmlAttribute = (value: string) =>
	value
		.replace(/&(?!(?:amp|lt|gt|quot|#39|#x27|#\d+|#x[0-9a-f]+);)/gi, '&amp;')
		.replace(/"/g, '&quot;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');

const collectHtmlImageSources = (html: string): string[] => {
	const sources: string[] = [];
	for (const match of String(html ?? '').matchAll(IMG_SRC_ATTRIBUTE_RE)) {
		const src = (match[2] ?? match[3] ?? '').trim().replace(/&amp;/g, '&');
		if (src && !sources.includes(src)) {
			sources.push(src);
		}
	}
	return sources;
};

/**
 * A model (or the safe fallback) sometimes leaves Markdown image syntax as
 * plain text inside the HTML; rendered literally it shows the URL instead of
 * the picture. Text nodes get a real <img>; attributes, comments, script and
 * style bodies are left untouched.
 */
export const renderMarkdownImagesInsideHtml = (html: string): string => {
	if (typeof html !== 'string' || !html.includes('![')) {
		return html;
	}
	return html
		.split(HTML_MARKUP_SEGMENT_RE)
		.map((segment, index) =>
			index % 2 === 1
				? segment
				: segment.replace(
						MARKDOWN_IMAGE_IN_HTML_TEXT_RE,
						(_whole: string, alt: string, src: string) =>
							`<img src="${escapeHtmlAttribute(src)}" alt="${escapeHtmlAttribute(alt.trim())}" style="max-width:100%;height:auto;display:block;border-radius:10px;margin:10px 0;">`
					)
		)
		.join('');
};

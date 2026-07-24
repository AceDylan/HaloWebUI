import { marked } from 'marked';

export const HTML_PREVIEW_SANDBOX = 'allow-scripts';
export const HTML_PREVIEW_REFERRER_POLICY = 'no-referrer';

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

const PREVIEW_POLICY_MARKER = 'data-halo-html-preview-policy="true"';
const PREVIEW_NAVIGATION_GUARD = `<script data-halo-html-preview-guard="true">(() => {
	document.addEventListener('click', (event) => {
		const target = event.target instanceof Element ? event.target.closest('a[href]') : null;
		const href = target?.getAttribute('href')?.trim() ?? '';
		if (target && href && !href.startsWith('#')) event.preventDefault();
	}, true);
	document.addEventListener('submit', (event) => event.preventDefault(), true);
})();</script>`;
const PREVIEW_POLICY_META = [
	`<meta ${PREVIEW_POLICY_MARKER} http-equiv="Content-Security-Policy" content="${HTML_PREVIEW_CSP}">`,
	'<meta name="referrer" content="no-referrer">',
	'<meta name="viewport" content="width=device-width, initial-scale=1.0">',
	'<meta charset="UTF-8">',
	PREVIEW_NAVIGATION_GUARD
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

export const hardenHtmlPreviewDocument = (html: unknown): string => {
	const source = String(html ?? '')
		.replace(/<meta\b(?=[^>]*\bdata-halo-html-preview-policy=["']true["'])[^>]*>/gi, '')
		.replace(
			/<script\b(?=[^>]*\bdata-halo-html-preview-guard=["']true["'])[^>]*>[\s\S]*?<\/script>/gi,
			''
		);

	if (/<html\b[^>]*>/i.test(source)) {
		let document = ensureDoctype(source);
		if (/<head\b[^>]*>/i.test(document)) {
			return insertAfterOpeningTag(document, 'head', PREVIEW_POLICY_META);
		}
		return insertAfterOpeningTag(document, 'html', `<head>${PREVIEW_POLICY_META}</head>`);
	}

	if (/<(?:head|body)\b[^>]*>/i.test(source)) {
		return hardenHtmlPreviewDocument(
			`<!DOCTYPE html><html lang="en">${stripLeadingDoctype(source)}</html>`
		);
	}

	return `<!DOCTYPE html><html lang="en"><head>${PREVIEW_POLICY_META}</head><body>${stripLeadingDoctype(source)}</body></html>`;
};

const normalizeCodeLanguage = (value: unknown) =>
	String(value ?? '')
		.trim()
		.toLowerCase()
		.split(/\s+/, 1)[0];

const stripThinkingBlocks = (value: string) =>
	value.replace(/<(think|thinking|reasoning)\b[^>]*>[\s\S]*?<\/\1>/gi, '');

const extractTagBody = (value: string, tagName: 'style' | 'script') => {
	const match = new RegExp(`<${tagName}\\b[^>]*>([\\s\\S]*?)</${tagName}>`, 'i').exec(value);
	return match?.[1] ?? '';
};

const extractDocumentBody = (value: string) => {
	const match = /<body\b[^>]*>([\s\S]*?)<\/body>/i.exec(value);
	return match?.[1] ?? stripLeadingDoctype(value);
};

type ArtifactParts = {
	html: string[];
	css: string[];
	javascript: string[];
};

const collectArtifactParts = (content: string): ArtifactParts => {
	const parts: ArtifactParts = { html: [], css: [], javascript: [] };
	const tokens = marked.lexer(stripThinkingBlocks(content));

	marked.walkTokens(tokens, (token: any) => {
		if (token?.type === 'code') {
			const language = normalizeCodeLanguage(token.lang);
			const code = String(token.text ?? '');
			if (language === 'html') {
				parts.html.push(code);
			} else if (language === 'css') {
				parts.css.push(code);
			} else if (language === 'javascript' || language === 'js') {
				parts.javascript.push(code);
			}
			return;
		}

		if (token?.type !== 'html') {
			return;
		}

		const raw = String(token.raw ?? token.text ?? '').trim();
		if (/^(?:<!doctype\s+html\b|<html\b)/i.test(raw)) {
			parts.html.push(raw);
		} else if (/^<style\b/i.test(raw)) {
			parts.css.push(extractTagBody(raw, 'style'));
		} else if (/^<script\b/i.test(raw)) {
			parts.javascript.push(extractTagBody(raw, 'script'));
		}
	});

	return parts;
};

const mergeHtmlParts = (htmlParts: string[]) => {
	let documentIndex = htmlParts.findIndex((part) => /<html\b/i.test(part));
	if (documentIndex < 0) {
		documentIndex = htmlParts.findIndex((part) => /<!doctype\s+html\b/i.test(part));
	}
	if (documentIndex < 0) {
		return htmlParts.join('\n');
	}

	let document = htmlParts[documentIndex];
	for (let index = 0; index < htmlParts.length; index += 1) {
		if (index === documentIndex) continue;
		document = insertBeforeClosingTag(
			document,
			'body',
			`\n${extractDocumentBody(htmlParts[index])}`
		);
	}
	return document;
};

export const buildHtmlArtifactPreview = (content: unknown): string | null => {
	if (typeof content !== 'string' || !content.trim()) {
		return null;
	}

	const parts = collectArtifactParts(content);
	if (parts.html.length === 0 && parts.css.length === 0 && parts.javascript.length === 0) {
		return null;
	}

	const style = `<style data-halo-artifact-styles="true">body { background-color: white; }\n${parts.css.join('\n')}</style>`;
	const script = parts.javascript.length
		? `<script data-halo-artifact-scripts="true">\n${parts.javascript.join('\n')}\n</script>`
		: '';
	const mergedHtml = mergeHtmlParts(parts.html);

	if (/(?:<!doctype\s+html\b|<html\b)/i.test(mergedHtml)) {
		let document = mergedHtml;
		if (/<head\b[^>]*>/i.test(document)) {
			document = insertBeforeClosingTag(document, 'head', style);
		} else if (/<html\b[^>]*>/i.test(document)) {
			document = insertAfterOpeningTag(document, 'html', `<head>${style}</head>`);
		}
		if (script) {
			document = insertBeforeClosingTag(document, 'body', script);
		}
		return hardenHtmlPreviewDocument(document);
	}

	return hardenHtmlPreviewDocument(
		`<!DOCTYPE html><html lang="en"><head>${style}</head><body>${mergedHtml}${script}</body></html>`
	);
};

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

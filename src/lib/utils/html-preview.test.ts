import { describe, expect, it } from 'vitest';

import {
	HTML_EXPORT_CSP,
	HTML_EXPORT_SANDBOX,
	HTML_PREVIEW_SANDBOX,
	buildHtmlArtifactPreview,
	buildInlineHtmlArtifactPreview,
	getCodePreviewEventKey,
	getInlineHtmlPreviewHeight,
	hardenHtmlArtifactExportDocument,
	hardenHtmlPreviewDocument,
	isActiveHtmlArtifactSnapshotMessage,
	isHtmlArtifactSourceToken,
	isInlineHtmlPreviewResizeMessage
} from './html-preview';

const countMatches = (value: string, pattern: RegExp) => value.match(pattern)?.length ?? 0;

describe('html-preview', () => {
	it('accepts snapshot responses only for a non-empty active export request', () => {
		const response = {
			type: 'halo-html-preview-export-snapshot-result',
			requestId: 'request-1',
			ok: true
		};

		expect(isActiveHtmlArtifactSnapshotMessage(response, 'request-1', true)).toBe(true);
		expect(isActiveHtmlArtifactSnapshotMessage({ ...response, requestId: '' }, '', false)).toBe(
			false
		);
		expect(isActiveHtmlArtifactSnapshotMessage(response, null, false)).toBe(false);
		expect(isActiveHtmlArtifactSnapshotMessage(response, 'request-2', true)).toBe(false);
	});

	it('builds a script-free same-origin export document with an offline CSP', () => {
		const exported = hardenHtmlArtifactExportDocument(`
<!doctype html><html><head>
<base href="https://example.com/"><meta http-equiv="refresh" content="0;url=https://example.com">
</head><body><script>alert(1)</script><main>Export me</main></body></html>`);

		expect(HTML_EXPORT_SANDBOX).toBe('allow-same-origin');
		expect(HTML_EXPORT_SANDBOX).not.toContain('allow-scripts');
		expect(HTML_EXPORT_CSP).toContain("script-src 'none'");
		expect(exported).toContain('data-halo-html-export-policy="true"');
		expect(exported).toContain('<main>Export me</main>');
		expect(exported).not.toContain('<script');
		expect(exported).not.toContain('<base');
		expect(exported).not.toContain('http-equiv="refresh"');
		expect(exported).not.toContain('data-halo-html-preview-snapshot');
	});

	it('wraps fragments in an isolated document with a strict CSP', () => {
		const preview = hardenHtmlPreviewDocument(
			'<h1>Hello</h1><script>window.ready = true;</script>'
		);

		expect(preview).toContain('<!DOCTYPE html>');
		expect(preview).toContain('http-equiv="Content-Security-Policy"');
		expect(preview).toContain("default-src 'none'");
		expect(preview).toContain("connect-src 'none'");
		expect(preview).toContain("form-action 'none'");
		expect(preview).toContain('data-halo-html-preview-guard="true"');
		expect(preview).toContain('data-halo-html-preview-snapshot="true"');
		expect(preview).toContain('data-halo-html-preview-resize="true"');
		expect(preview).toContain('halo-html-preview-export-snapshot');
		expect(preview).toContain('halo-html-preview-resize');
		expect(preview).toContain('ResizeObserver');
		expect(preview).toContain('event.source !== parent');
		expect(preview).toContain('event.stopImmediatePropagation()');
		expect(preview).toContain('name="referrer" content="no-referrer"');
		expect(preview).toContain('<body><h1>Hello</h1><script>window.ready = true;</script></body>');
	});

	it('injects preview policies into complete documents without nesting html elements', () => {
		const preview = hardenHtmlPreviewDocument(
			'<!doctype html><html lang="zh"><head><title>Demo</title></head><body>OK</body></html>'
		);

		expect(countMatches(preview, /<html\b/gi)).toBe(1);
		expect(countMatches(preview, /<head\b/gi)).toBe(1);
		expect(countMatches(preview, /<body\b/gi)).toBe(1);
		expect(preview).toContain('<title>Demo</title>');
		expect(preview).toContain('http-equiv="Content-Security-Policy"');
	});

	it('builds one artifact document from fenced html, css, and javascript blocks', () => {
		const preview = buildHtmlArtifactPreview(`
<reasoning>\n\`\`\`html\n<p>hidden</p>\n\`\`\`\n</reasoning>

\`\`\`html title="demo"
<!doctype html><html><head><title>Artifact</title></head><body><main>Visible</main></body></html>
\`\`\`

\`\`\`css
main { color: rebeccapurple; }
\`\`\`

\`\`\`javascript
window.artifactReady = true;
\`\`\`
`);

		expect(preview).not.toBeNull();
		expect(countMatches(preview ?? '', /<html\b/gi)).toBe(1);
		expect(preview).toContain('<main>Visible</main>');
		expect(preview).not.toContain('<p>hidden</p>');
		expect(preview).toContain('main { color: rebeccapurple; }');
		expect(preview).toContain('window.artifactReady = true;');
		expect(preview).toContain('http-equiv="Content-Security-Policy"');
	});

	it('does not trust a user-supplied preview policy marker', () => {
		const preview = hardenHtmlPreviewDocument(
			'<meta data-halo-html-preview-policy="true"><main>spoofed marker</main>'
		);

		expect(preview).toContain("default-src 'none'");
		expect(preview).toContain('data-halo-html-preview-guard="true"');
		expect(countMatches(preview, /data-halo-html-preview-policy="true"/g)).toBe(1);
		expect(countMatches(preview, /data-halo-html-preview-snapshot="true"/g)).toBe(1);
	});

	it('extracts inline HTML documents without relying on fenced-code regexes', () => {
		const preview = buildHtmlArtifactPreview(
			'Intro\n\n<!DOCTYPE html><html lang="zh"><head><title>Inline</title></head><body><p>Body</p></body></html>'
		);

		expect(preview).not.toBeNull();
		expect(preview).toContain('<title>Inline</title>');
		expect(preview).toContain('<p>Body</p>');
		expect(countMatches(preview ?? '', /<html\b/gi)).toBe(1);
	});

	it('keeps injected styles in head and scripts in body for incomplete documents', () => {
		const preview = buildHtmlArtifactPreview(`\`\`\`html
<html><head><title>Incomplete</title><body><main>Body</main>
\`\`\`

\`\`\`css
main { color: teal; }
\`\`\`

\`\`\`js
window.done = true;
\`\`\``);

		expect(preview).not.toBeNull();
		expect((preview ?? '').indexOf('data-halo-artifact-styles')).toBeLessThan(
			(preview ?? '').indexOf('<body>')
		);
		expect((preview ?? '').indexOf('data-halo-artifact-scripts')).toBeGreaterThan(
			(preview ?? '').indexOf('<body>')
		);
	});

	it('places CSS-only artifacts in the document head', () => {
		const preview = buildHtmlArtifactPreview('```css\nbody { color: navy; }\n```');

		expect(preview).not.toBeNull();
		expect((preview ?? '').indexOf('data-halo-artifact-styles')).toBeLessThan(
			(preview ?? '').indexOf('<body>')
		);
	});

	it('preserves standalone raw style and script blocks with attributes', () => {
		const preview = buildHtmlArtifactPreview(
			'<style media="screen">main { color: olive; }</style>\n<script type="module">window.rawReady = true;</script>'
		);

		expect(preview).not.toBeNull();
		expect(preview).toContain('main { color: olive; }');
		expect(preview).toContain('window.rawReady = true;');
	});

	it('does not emit code preview events while streaming', () => {
		expect(getCodePreviewEventKey('html', '<main>partial', true)).toBeNull();
		expect(getCodePreviewEventKey(' HTML ', '<main>done</main>', false)).toBe(
			'html\u0000<main>done</main>'
		);
		expect(getCodePreviewEventKey('html title="demo"', '<main>done</main>', false)).toBe(
			'html\u0000<main>done</main>'
		);
		expect(getCodePreviewEventKey('', 'content', false)).toBeNull();
	});

	it('renders completed HTML artifacts inline only when artifact detection is enabled', () => {
		const content = '```html\n<main>Inline preview</main>\n```';

		expect(buildInlineHtmlArtifactPreview(content, { enabled: true, streaming: false })).toContain(
			'<main>Inline preview</main>'
		);
		expect(
			buildInlineHtmlArtifactPreview(content, { enabled: false, streaming: false })
		).toBeNull();
		expect(buildInlineHtmlArtifactPreview(content, { enabled: true, streaming: true })).toBeNull();
		expect(
			buildInlineHtmlArtifactPreview('plain text', { enabled: true, streaming: false })
		).toBeNull();
	});

	it('accepts bounded resize messages for inline preview height', () => {
		expect(
			isInlineHtmlPreviewResizeMessage({ type: 'halo-html-preview-resize', height: 420 })
		).toBe(true);
		expect(getInlineHtmlPreviewHeight({ type: 'halo-html-preview-resize', height: 420 })).toBe(420);
		expect(getInlineHtmlPreviewHeight({ type: 'halo-html-preview-resize', height: 40 })).toBe(200);
		expect(getInlineHtmlPreviewHeight({ type: 'halo-html-preview-resize', height: 5000 })).toBe(
			1200
		);
		expect(
			getInlineHtmlPreviewHeight({ type: 'halo-html-preview-resize', height: Number.NaN })
		).toBeNull();
		expect(getInlineHtmlPreviewHeight({ type: 'other', height: 420 })).toBeNull();
	});

	it('identifies only preview-consumed HTML artifact source tokens', () => {
		expect(isHtmlArtifactSourceToken({ type: 'code', lang: 'html', text: '<main />' })).toBe(true);
		expect(isHtmlArtifactSourceToken({ type: 'code', lang: 'CSS', text: 'body {}' })).toBe(true);
		expect(
			isHtmlArtifactSourceToken({ type: 'code', lang: 'javascript title="demo"', text: '1' })
		).toBe(true);
		expect(
			isHtmlArtifactSourceToken({
				type: 'html',
				raw: '<!doctype html><html><body>demo</body></html>'
			})
		).toBe(true);
		expect(
			isHtmlArtifactSourceToken({ type: 'html', raw: '<style>body { color: red; }</style>' })
		).toBe(true);
		expect(isHtmlArtifactSourceToken({ type: 'code', lang: 'python', text: 'print(1)' })).toBe(
			false
		);
		expect(
			isHtmlArtifactSourceToken({ type: 'html', raw: '<div>ordinary inline html</div>' })
		).toBe(false);
	});

	it('never grants forms or same-origin access to untrusted preview documents', () => {
		expect(HTML_PREVIEW_SANDBOX).toBe('allow-scripts');
		expect(HTML_PREVIEW_SANDBOX).not.toContain('allow-forms');
		expect(HTML_PREVIEW_SANDBOX).not.toContain('allow-same-origin');
	});
});

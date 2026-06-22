import renderMathInElement from 'katex/contrib/auto-render';
import 'katex/contrib/mhchem';
import 'katex/dist/katex.min.css';

// Keep the delimiter set in sync with src/lib/utils/marked/katex-extension.ts so that
// LaTeX rendered inside raw HTML tokens matches the markdown rendering path.
const DELIMITERS = [
	{ left: '$$', right: '$$', display: true },
	{ left: '\\[', right: '\\]', display: true },
	{ left: '\\begin{equation}', right: '\\end{equation}', display: true },
	{ left: '\\(', right: '\\)', display: false },
	{ left: '\\ce{', right: '}', display: false },
	{ left: '\\pu{', right: '}', display: false },
	{ left: '$', right: '$', display: false }
];

const IGNORED_TAGS = ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'];

export function renderKatexInHtml(node: HTMLElement): void {
	if (!node) return;
	try {
		renderMathInElement(node, {
			delimiters: DELIMITERS,
			throwOnError: false,
			ignoredTags: IGNORED_TAGS
		});
	} catch {
		// Leave the original text in place if auto-render fails for any reason.
	}
}

/**
 * Svelte action that renders LaTeX delimiters inside an element whose content is
 * injected via `{@html ...}`. Pass the html string as the action parameter so the
 * action re-runs whenever the streamed/updated content changes.
 */
export function katexAutoRender(node: HTMLElement, _html?: unknown) {
	renderKatexInHtml(node);
	return {
		update() {
			// `{@html ...}` replaces innerHTML before the action update fires, so the raw
			// delimiters are present again here and need to be re-rendered.
			renderKatexInHtml(node);
		}
	};
}

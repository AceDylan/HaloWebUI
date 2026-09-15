import renderMathInElement from 'katex/contrib/auto-render';
import 'katex/contrib/mhchem';
import 'katex/dist/katex.min.css';

import { KATEX_STRICT } from '$lib/utils/katex-options';

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

// Cheap pre-check mirroring DELIMITERS: walking (and rewriting) the subtree is the expensive
// part, and most HTML chunks in an answer carry no math at all.
const DELIMITER_PROBE = /\$|\\\(|\\\[|\\ce\{|\\pu\{|\\begin\{equation\}/;

const IGNORED_TAGS = ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'];

export function renderKatexInHtml(node: HTMLElement): void {
	if (!node) return;
	if (!DELIMITER_PROBE.test(node.textContent ?? '')) return;
	try {
		renderMathInElement(node, {
			delimiters: DELIMITERS,
			throwOnError: false,
			strict: KATEX_STRICT,
			ignoredTags: IGNORED_TAGS
		});
	} catch {
		// Leave the original text in place if auto-render fails for any reason.
	}
}

/**
 * Svelte action that injects `html` into `node` and renders the LaTeX delimiters inside it.
 *
 * The action owns the subtree on purpose: it must NOT be combined with `{@html ...}` on the
 * same element. KaTeX's auto-render swaps out the text nodes it rewrites, so the nodes Svelte
 * was tracking for `{@html ...}` end up detached; Svelte can then no longer remove them and
 * every content update leaves another rendered copy behind. On a streamed answer that grows
 * the DOM without bound (one extra copy per chunk, each re-scanned by KaTeX on the next pass)
 * until the tab freezes.
 */
export function katexAutoRender(node: HTMLElement, html?: unknown) {
	let rendered: string | null = null;

	const apply = (value: unknown) => {
		const next = typeof value === 'string' ? value : '';
		// Svelte re-runs action updates whenever the surrounding block is dirty, even when
		// `html` itself is unchanged. Re-injecting identical markup would rebuild the subtree
		// (and re-request any <img> in it) on every streamed chunk, so skip that work.
		if (next === rendered) return;
		rendered = next;
		node.innerHTML = next;
		renderKatexInHtml(node);
	};

	apply(html);

	return {
		update: apply
	};
}

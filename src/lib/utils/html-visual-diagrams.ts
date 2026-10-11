// Diagrams in AI-designed answer cards. The designer cannot place boxes and
// arrows by hand (it would have to compute SVG coordinates), so it writes the
// relations as text inside the card:
//
//   <pre class="hv-dia" data-kind="flow LR">用户 -> 网关: HTTPS
//   网关 -> {已登录?}</pre>
//
// and this module turns each block into SVG before the card is shown, with the
// layout computed by the vendored answer-me-with-html components (dagre for
// flows). The syntax is documented to the designer in backend
// html_visual_prompt.py (HTML_VISUAL_AGY_HTML_REQUEST_PROMPT); the colours live
// in the kit stylesheet (html-visual-kit.ts). A block that does not parse stays
// as its readable source text.

import flow from '$lib/vendor/answer-me-with-html/components/flow.js';
import sequence from '$lib/vendor/answer-me-with-html/components/sequence.js';
import tree from '$lib/vendor/answer-me-with-html/components/tree.js';

type DiagramComponent = {
	render: (text: string, context: Record<string, unknown>) => string;
};

const COMPONENTS: Record<string, DiagramComponent> = { flow, sequence, tree };

const UI_LABELS = {
	flow: '流程图',
	sequence: '时序图',
	er: '关系图',
	colon: '：',
	sep: '、',
	delta: {
		added: '新增',
		removed: '删除',
		changed: '修改',
		view: '视图',
		before: '改前',
		changes: '改动',
		after: '改后'
	}
};

const DIAGRAM_BLOCK_RE =
	/<pre\b(?=[^>]*\bclass\s*=\s*["'](?:[^"']*\s)?hv-dia(?:\s[^"']*)?["'])([^>]*)>([\s\S]*?)<\/pre\s*>/gi;
const KIND_ATTR_RE = /\bdata-kind\s*=\s*(?:"([^"]*)"|'([^']*)')/i;
const ENTITY_RE = /&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi;
const NAMED_ENTITIES: Record<string, string> = {
	amp: '&',
	lt: '<',
	gt: '>',
	quot: '"',
	apos: "'",
	nbsp: ' '
};
// Flows that run sideways are drawn a second time top to bottom for phones.
const SIDEWAYS_FLOW_RE = /\b(?:LR|RL)\b/i;
// A wide drawing shrinks to fit the card down to this scale; past it the card
// scrolls sideways instead, so labels stay readable.
const MIN_DRAWING_SCALE = 0.75;
const SVG_OPEN_RE = /<svg viewBox="0 0 (\d+) \d+" width="\d+"/g;
// Slips the designer makes that upstream rejects, repaired for a second try:
// misplaced change markers (`~ A -> B`, `A -> + B`) are dropped, and group
// members written like nodes (`group 后端: *服务, [(库)]`) lose the highlight
// and the brackets, since a group lists node text.
const MISPLACED_MARKER_RE = /^(\s*)[+~-] +|(-->|->)\s*[+~-] +/gm;
const GROUP_LINE_RE = /^(\s*(?:[+-] +)?group\s+[^:：]+[:：])(.*)$/gim;
const repairSource = (source: string): string =>
	source
		.replace(
			GROUP_LINE_RE,
			(_, head: string, members: string) =>
				head +
				members
					.split(/[,，]/)
					.map((member) =>
						member
							.trim()
							.replace(/^\*/, '')
							.replace(/^\[\((.*)\)\]$|^[[({](.*)[\])}]$/, '$1$2')
					)
					.join(', ')
		)
		.replace(MISPLACED_MARKER_RE, '$1$2 ');

const decodeEntities = (text: string): string =>
	text.replace(ENTITY_RE, (match, entity: string) => {
		const lower = entity.toLowerCase();
		if (lower.startsWith('#')) {
			const code = lower.startsWith('#x')
				? Number.parseInt(lower.slice(2), 16)
				: Number.parseInt(lower.slice(1), 10);
			return Number.isFinite(code) && code > 0 && code <= 0x10ffff
				? String.fromCodePoint(code)
				: match;
		}
		return NAMED_ENTITIES[lower] ?? match;
	});

const escapeHtml = (text: string): string =>
	text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

// The block's source as the reader would see it: tags such as a wrapping <code>
// removed, entities decoded, common indentation kept for tree levels.
const blockSource = (inner: string): string =>
	decodeEntities(inner.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]*>/g, ''))
		.replace(/\r\n?/g, '\n')
		.replace(/^\n+|\s+$/g, '');

export const hasHtmlVisualDiagrams = (html: unknown): boolean =>
	typeof html === 'string' && /\bhv-dia\b/.test(html);

/** Replace every `<pre class="hv-dia">` block of a kit card with its drawing. */
export const renderHtmlVisualDiagrams = (html: string): string => {
	if (!hasHtmlVisualDiagrams(html)) return html;
	let seq = 0;
	const context = (args: string) => ({
		args,
		uid: () => `hvd${++seq}`,
		ui: UI_LABELS,
		dir: 'ltr'
	});

	return html.replace(DIAGRAM_BLOCK_RE, (block, attrs: string, inner: string) => {
		const kindMatch = attrs.match(KIND_ATTR_RE);
		const [name = '', ...rest] = (kindMatch?.[1] ?? kindMatch?.[2] ?? '').trim().split(/\s+/);
		const component = COMPONENTS[name.toLowerCase()];
		const source = blockSource(inner);
		const fallback = `<pre class="hv-dia hv-dia-src">${escapeHtml(source)}</pre>`;
		if (!component || !source) return fallback;
		const args = rest.join(' ');
		const draw = (drawArgs: string) => {
			try {
				return component.render(source, context(drawArgs));
			} catch {
				return component.render(repairSource(source), context(drawArgs));
			}
		};
		try {
			const drawing = draw(args);
			if (name.toLowerCase() === 'flow' && SIDEWAYS_FLOW_RE.test(args)) {
				const narrow = draw(args.replace(SIDEWAYS_FLOW_RE, 'TB'));
				return `<div class="hv-dia" data-kind="flow"><div class="hv-dia-wide">${withMinimumScale(drawing)}</div><div class="hv-dia-narrow">${withMinimumScale(narrow)}</div></div>`;
			}
			return `<div class="hv-dia" data-kind="${name.toLowerCase()}">${withMinimumScale(drawing)}</div>`;
		} catch {
			return fallback;
		}
	});
};

const withMinimumScale = (drawing: string): string =>
	drawing.replace(
		SVG_OPEN_RE,
		(open, width: string) =>
			`${open} style="min-width:${Math.round(Number(width) * MIN_DRAWING_SCALE)}px"`
	);

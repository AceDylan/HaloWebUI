/**
 * The text a completion toast / system notification shows for a reply.
 *
 * The reply's content is its transcript: tool-call `<details>` blocks
 * ("Tool Executed"), a visual card's HTML source, quoted guidance. A person
 * glancing at a toast wants the answer, so: drop all of that and show the
 * start of the last paragraph that has words in it.
 */
const DETAILS_RE = /<details\b[^>]*>[\s\S]*?<\/details\s*>/gi;
const SELF_CLOSING_TOOL_RE = /<tool_calls\b[^>]*\/?>/gi;
const FENCE_RE = /(^|\n)(`{3,}|~{3,})[^\n]*\n[\s\S]*?\n\2[ \t]*(?=\n|$)/g;
const TAG_RE = /<[^>]+>/g;

const toPlainLine = (paragraph: string) =>
	paragraph
		.split('\n')
		.map((line) =>
			line
				.replace(/^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)/, '')
				.replace(/!\[[^\]]*\]\([^)]*\)/g, '')
				.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
				.replace(/(\*\*|__|`)/g, '')
				.trim()
		)
		.filter(Boolean)
		.join(' ');

export const getNotificationPreview = (content: unknown, maxChars = 200): string => {
	let text = String(content ?? '');
	text = text.replace(DETAILS_RE, '\n').replace(SELF_CLOSING_TOOL_RE, '\n');
	text = text.replace(FENCE_RE, '\n');
	text = text.replace(TAG_RE, ' ');
	const paragraphs = text
		.split(/\n\s*\n/)
		.map(toPlainLine)
		// Guidance quotes ("🧭 …") and the undelivered marker are not the answer.
		.filter((line) => line && !line.startsWith('🧭') && !line.startsWith('⚠️ 未送达'));
	const last = paragraphs[paragraphs.length - 1] ?? '';
	return last.length > maxChars ? `${last.slice(0, maxChars - 1).trimEnd()}…` : last;
};

/**
 * What a 对话概述 node shows for a message.
 *
 * A reply's content is its transcript: tool-call `<details>` blocks, an HTML
 * card's source, code, Markdown markup, a runner report's header lines. The
 * node has room for two lines, so it shows the words a person would read and
 * names the rest as tags ("HTML 卡片", "工具 ×3") instead of printing source.
 */
import {
	DETAILS_RE,
	FENCE_RE,
	SELF_CLOSING_TOOL_RE,
	TAG_RE,
	isAnswerLine,
	toPlainLine
} from './notification-preview';
import { describeHermesRunNotice, getRunReportRunId, splitRunReport } from './hermes';

export type OverviewPreview = {
	/** The start of the readable text, for the node. */
	text: string;
	/** A runner report's headline ("✅ cchclaude 已完成"), or ''. */
	status: string;
	/** What the text leaves out: "HTML 卡片", "工具 ×3", "代码", "图片 2", "附件 1". */
	tags: string[];
	/** More of the readable text, for the hover tooltip. */
	detail: string;
};

const TEXT_MAX_CHARS = 140;
const DETAIL_MAX_CHARS = 600;

const TOOL_CALL_RE = /<details\s+type="tool_calls"/gi;
const STYLE_SCRIPT_RE = /<(style|script)\b[^>]*>[\s\S]*?<\/\1\s*>/gi;
const MARKDOWN_IMAGE_RE = /!\[[^\]]*\]\([^)]*\)/g;
const HTML_IMAGE_RE = /<img\b/gi;
const TABLE_RULE_RE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/gm;
const ENTITIES: Record<string, string> = {
	'&nbsp;': ' ',
	'&lt;': '<',
	'&gt;': '>',
	'&quot;': '"',
	'&#39;': "'",
	'&amp;': '&'
};

const clip = (text: string, maxChars: number) =>
	text.length > maxChars ? `${text.slice(0, maxChars - 1).trimEnd()}…` : text;

/** The words a person sees in an HTML card. */
const htmlToText = (html: string) =>
	html
		.replace(STYLE_SCRIPT_RE, ' ')
		.replace(TAG_RE, ' ')
		.replace(/&(?:nbsp|lt|gt|quot|#39|amp);/g, (entity) => ENTITIES[entity])
		.replace(/\s+/g, ' ')
		.trim();

const toParagraphs = (markdown: string) =>
	markdown
		.replace(TABLE_RULE_RE, '')
		.replace(/\|/g, ' ')
		.split(/\n\s*\n/)
		.map((paragraph) => toPlainLine(paragraph).replace(/\s+/g, ' ').trim())
		.filter(isAnswerLine);

export const getOverviewPreview = (content: unknown, files: unknown = []): OverviewPreview => {
	let text = typeof content === 'string' ? content : '';
	let status = '';

	const runId = getRunReportRunId(text);
	const report = runId ? splitRunReport(text, runId) : null;
	if (runId && report) {
		status = describeHermesRunNotice({ agent: '', runId, status: '', sessionLabel: '', sessionId: '' }, text);
		text = report.body;
	}

	const toolCalls = text.match(TOOL_CALL_RE)?.length ?? 0;
	text = text.replace(DETAILS_RE, '\n').replace(SELF_CLOSING_TOOL_RE, '\n');

	const htmlCards: string[] = [];
	let codeBlocks = 0;
	text = text.replace(FENCE_RE, (_match, lead: string, _fence, info: string, body: string) => {
		if (/^\s*html\b/i.test(info)) {
			htmlCards.push(htmlToText(body));
		} else {
			codeBlocks += 1;
		}
		return `${lead}\n`;
	});

	// A bare HTML document or snippet outside a fence reads like a card too.
	if (/^\s*(?:<!doctype\s+html\b|<html\b)/i.test(text)) {
		htmlCards.push(htmlToText(text));
		text = '';
	}

	const fileList = Array.isArray(files) ? files : [];
	const imageFiles = fileList.filter((file) => file?.type === 'image').length;
	const images =
		(text.match(MARKDOWN_IMAGE_RE)?.length ?? 0) +
		(text.match(HTML_IMAGE_RE)?.length ?? 0) +
		imageFiles;
	const attachments = fileList.length - imageFiles;

	text = text.replace(STYLE_SCRIPT_RE, ' ').replace(TAG_RE, ' ');
	let paragraphs = toParagraphs(text);
	// An answer that is only a card: its own words are the answer.
	if (paragraphs.length === 0) {
		paragraphs = htmlCards.filter(Boolean);
	}

	const tags: string[] = [];
	if (htmlCards.length > 0) tags.push(htmlCards.length > 1 ? `HTML 卡片 ×${htmlCards.length}` : 'HTML 卡片');
	if (toolCalls > 0) tags.push(`工具 ×${toolCalls}`);
	if (codeBlocks > 0) tags.push(codeBlocks > 1 ? `代码 ×${codeBlocks}` : '代码');
	if (images > 0) tags.push(`图片 ${images}`);
	if (attachments > 0) tags.push(`附件 ${attachments}`);

	const joined = paragraphs.join(' ');
	return {
		text: clip(joined, TEXT_MAX_CHARS),
		status,
		tags,
		detail: clip(joined, DETAIL_MAX_CHARS)
	};
};

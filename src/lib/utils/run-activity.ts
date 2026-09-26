import { formatRunDuration, getToolCallState, getToolLabel } from './tool-call-preview';

/**
 * What a finished agent reply did, in one line: "20 步 · 终端 8 · 读文件 5 ·
 * 1 分 37 秒 · 1 个失败". Shown above the visual card, which replaces the
 * reply text and with it the tool transcript.
 */

export type RunToolToken = { attributes: Record<string, string> };

const TOOL_DETAILS_RE = /<details\s+type="tool_calls"([^>]*)>/gi;
const ATTRIBUTE_RE = /([\w-]+)="([^"]*)"/g;

export const extractToolCallTokens = (content: string): RunToolToken[] => {
	const tokens: RunToolToken[] = [];
	for (const match of String(content ?? '').matchAll(TOOL_DETAILS_RE)) {
		const attributes: Record<string, string> = { type: 'tool_calls' };
		for (const attribute of match[1].matchAll(ATTRIBUTE_RE)) {
			// Values stay html-escaped, as marked hands them to ToolCallGroup.
			attributes[attribute[1]] = attribute[2];
		}
		tokens.push({ attributes });
	}
	return tokens;
};

export { TOOL_LABELS_ZH, formatRunDuration } from './tool-call-preview';

export const summarizeRunActivity = (
	tokens: RunToolToken[],
	durationSeconds: number | null = null,
	maxTools = 3
): string => {
	if (tokens.length === 0) return '';
	const counts = new Map<string, number>();
	let failed = 0;
	let interrupted = 0;
	for (const token of tokens) {
		const label = getToolLabel(token.attributes?.name ?? '');
		counts.set(label, (counts.get(label) ?? 0) + 1);
		const state = getToolCallState(token.attributes, true);
		if (state === 'error') failed += 1;
		if (state === 'interrupted') interrupted += 1;
	}
	const parts = [`${tokens.length} 步`];
	for (const [label, count] of [...counts.entries()]
		.sort((a, b) => b[1] - a[1])
		.slice(0, maxTools)) {
		parts.push(`${label} ${count}`);
	}
	const duration = formatRunDuration(durationSeconds);
	if (duration) parts.push(duration);
	if (failed > 0) parts.push(`${failed} 个失败`);
	if (interrupted > 0) parts.push(`${interrupted} 个中断`);
	return parts.join(' · ');
};


/** "reclaude · 已运行 12 分钟 · 第 198 步": a background runner in one line. */
export const describeBackgroundRun = (
	run: { agent?: string; started_at?: number | null; step?: number | null },
	nowSeconds: number
): string => {
	const parts = [run.agent || 'runner'];
	if (run.started_at) {
		const minutes = Math.max(0, Math.floor((nowSeconds - Number(run.started_at)) / 60));
		parts.push(
			minutes >= 60
				? `已运行 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`
				: `已运行 ${minutes} 分钟`
		);
	}
	if (run.step) parts.push(`第 ${run.step} 步`);
	return parts.join(' · ');
};

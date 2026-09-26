import { decode } from 'html-entities';

import { getToolCallState } from './tool-call-preview';

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

/** hermes tool names in the words the summary uses; unknown names stay as they are. */
export const TOOL_LABELS_ZH: Record<string, string> = {
	terminal: '终端',
	process: '进程',
	read_file: '读文件',
	write_file: '写文件',
	patch: '改文件',
	search_files: '搜文件',
	web_search: '搜索',
	search_web: '搜索',
	web_extract: '读网页',
	fetch_url: '读网页',
	skill_view: '技能',
	skills_list: '技能',
	execute_code: '运行代码',
	delegate_task: '子任务',
	todo: '待办',
	memory: '记忆',
	session_search: '查会话',
	send_message: '发消息',
	clarify: '询问',
	image_generate: '生图',
	vision_analyze: '看图',
	cronjob: '定时任务'
};

const toolLabel = (name: string) => {
	const key = (name ?? '').trim();
	if (!key) return '工具';
	if (key.startsWith('browser_')) return '浏览器';
	return TOOL_LABELS_ZH[key] ?? decode(key);
};

export const formatRunDuration = (seconds: number | null | undefined): string => {
	if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 1) {
		return '';
	}
	const total = Math.round(seconds);
	const hours = Math.floor(total / 3600);
	const minutes = Math.floor((total % 3600) / 60);
	const rest = total % 60;
	if (hours > 0) return `${hours} 小时 ${minutes} 分`;
	if (minutes > 0) return rest > 0 ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
	return `${rest} 秒`;
};

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
		const label = toolLabel(token.attributes?.name ?? '');
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

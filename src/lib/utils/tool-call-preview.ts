import { decode } from 'html-entities';

/**
 * One-line summaries for `<details type="tool_calls">` blocks.
 *
 * hermes streams every call as `arguments="{"input": <preview>}"` and
 * `result="{"status": "success"|"error", "duration": <s>}"`; native tools carry
 * their real JSON. Either way a person scanning twenty calls wants "terminal ·
 * npm test · 3.2s · failed", not the tool name alone.
 */

const parseJsonLike = (value: unknown): unknown => {
	let current: unknown = decode(String(value ?? ''));
	for (let i = 0; i < 4 && typeof current === 'string'; i += 1) {
		const trimmed = current.trim();
		if (!trimmed) return '';
		try {
			current = JSON.parse(trimmed);
		} catch {
			return current;
		}
	}
	return current;
};

const collapseWhitespace = (text: string) => text.replace(/\s+/g, ' ').trim();

export const truncatePreview = (text: string, max = 96): string => {
	const compact = collapseWhitespace(text);
	if (compact.length <= max) return compact;
	return `${compact.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
};

/** The call's input as one line: the `input` string when that is all there is, else compact JSON. */
export const getToolCallPreview = (argumentsValue: unknown, max = 96): string => {
	const parsed = parseJsonLike(argumentsValue);
	if (parsed === '' || parsed === null || parsed === undefined) return '';
	if (typeof parsed === 'string') return truncatePreview(parsed, max);
	if (typeof parsed === 'object' && !Array.isArray(parsed)) {
		const entries = Object.entries(parsed as Record<string, unknown>);
		if (entries.length === 1) {
			const [key, value] = entries[0];
			if (['input', 'query', 'command', 'cmd', 'prompt', 'path', 'url'].includes(key)) {
				if (typeof value === 'string') return truncatePreview(value, max);
			}
		}
		if (entries.length === 0) return '';
	}
	try {
		return truncatePreview(JSON.stringify(parsed), max);
	} catch {
		return '';
	}
};

export type ToolCallOutcome = {
	/**
	 * null while the call is still running or when the result has no status.
	 * `interrupted`: the run ended (failed, stopped, lost its connection)
	 * before this call reported back.
	 */
	status: 'success' | 'error' | 'interrupted' | null;
	/** Seconds, when the result reports a duration. */
	duration: number | null;
	/** Why an interrupted call was cut short, when known. */
	reason?: string;
};

export const getToolCallOutcome = (resultValue: unknown): ToolCallOutcome => {
	const parsed = parseJsonLike(resultValue);
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		return { status: null, duration: null };
	}
	const record = parsed as Record<string, unknown>;
	const rawStatus = typeof record.status === 'string' ? record.status.toLowerCase() : '';
	const status =
		rawStatus === 'interrupted' || rawStatus === 'cancelled'
			? 'interrupted'
			: rawStatus === 'error' || rawStatus === 'failed' || record.error === true
				? 'error'
				: rawStatus === 'success' || rawStatus === 'ok'
					? 'success'
					: null;
	const duration = Number(record.duration);
	const reason = typeof record.reason === 'string' ? record.reason.trim() : '';
	return {
		status,
		duration: Number.isFinite(duration) && duration >= 0 ? duration : null,
		...(reason ? { reason } : {})
	};
};

type ToolTokenAttributes = {
	name?: string;
	done?: string;
	result?: string;
	arguments?: string;
	started?: string;
};

export type ToolCallState = 'running' | 'success' | 'error' | 'interrupted' | 'done';

/**
 * Where one call stands. A call still marked running in a reply that is no
 * longer streaming never reported back (the run broke off or was stopped):
 * that is `interrupted`, not "executing" forever.
 */
export const getToolCallState = (
	attributes: ToolTokenAttributes | null | undefined,
	settled = false
): ToolCallState => {
	if (attributes?.done !== 'true') {
		return settled ? 'interrupted' : 'running';
	}
	const outcome = getToolCallOutcome(attributes?.result ?? '');
	return outcome.status ?? 'done';
};

/**
 * hermes tool names in the words every tool view uses (the run summary above a
 * card, the tool group, the formatted reply); unknown names stay as they are.
 */
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
	fetch_url_rendered: '读网页',
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
	generate_image: '生图',
	edit_image: '改图',
	vision_analyze: '看图',
	cronjob: '定时任务'
};

export const getToolLabel = (name: string | null | undefined): string => {
	const key = decode(String(name ?? '')).trim();
	if (!key) return '工具';
	if (key.startsWith('browser_')) return '浏览器';
	return TOOL_LABELS_ZH[key] ?? key;
};

/** "终端 6 · 技能 20": what a group of calls did, by tool, most used first. */
export const summarizeToolNames = (names: string[], maxNames = 3): string => {
	const counts = new Map<string, number>();
	for (const raw of names) {
		const name = getToolLabel(raw);
		counts.set(name, (counts.get(name) ?? 0) + 1);
	}
	const ordered = [...counts.entries()].sort((a, b) => b[1] - a[1]);
	const shown = ordered
		.slice(0, maxNames)
		.map(([name, count]) => (count > 1 ? `${name} ${count}` : name));
	const rest = ordered.slice(maxNames).reduce((sum, [, count]) => sum + count, 0);
	if (rest > 0) shown.push(`+${rest}`);
	return shown.join(' · ');
};

/**
 * The whole input of a hermes-style call (`{"input": "<command>"}`), for the
 * detail panel; null when the arguments are a real JSON object.
 */
export const getToolCallInput = (argumentsValue: unknown): string | null => {
	const parsed = parseJsonLike(argumentsValue);
	if (typeof parsed === 'string') return parsed;
	if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
		const entries = Object.entries(parsed as Record<string, unknown>);
		if (entries.length === 1 && typeof entries[0][1] === 'string') {
			const [key] = entries[0];
			if (['input', 'query', 'command', 'cmd', 'prompt', 'path', 'url'].includes(key)) {
				return entries[0][1] as string;
			}
		}
	}
	return null;
};

/**
 * True when the result is what hermes reports: an outcome (status/duration/
 * reason) and, from hermes 975738a413 on, a short preview of what the call
 * returned (`output`). Nothing worth showing as JSON.
 */
export const isOutcomeOnlyResult = (resultValue: unknown): boolean => {
	const parsed = parseJsonLike(resultValue);
	if (parsed === '' || parsed === null || parsed === undefined) return true;
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return false;
	return Object.entries(parsed as Record<string, unknown>).every(
		([key, value]) =>
			['status', 'duration', 'reason', 'error'].includes(key) ||
			(key === 'output' && typeof value === 'string')
	);
};

/** Fields that hold a result's text, in the order they are looked for. */
const RESULT_TEXT_FIELDS = ['output', 'content', 'result', 'text', 'stdout', 'stderr', 'error'];
const JSON_ESCAPE_RE = /\\(u[0-9a-fA-F]{4}|["\\/bfnrt])/g;
const JSON_ESCAPES: Record<string, string> = { b: '', f: '', n: '\n', r: '', t: '\t' };
const TRUNCATED_TEXT_FIELD_RE = new RegExp(`^\\{\\s*"(?:${RESULT_TEXT_FIELDS.join('|')})"\\s*:\\s*"`);

/**
 * A hermes result preview as it should read: a JSON result gives its text
 * field with real line breaks, then its other plain fields as "key: value";
 * a preview cut short at 500 characters is no longer JSON, but its escapes
 * still become line breaks.
 */
export const formatToolOutput = (preview: string): string => {
	const text = String(preview ?? '').trim();
	let parsed: unknown;
	try {
		parsed = JSON.parse(text);
	} catch {
		if (!/^[[{"]/.test(text)) return text;
		return text
			.replace(TRUNCATED_TEXT_FIELD_RE, '')
			.replace(JSON_ESCAPE_RE, (_match, escape: string) =>
				escape.length === 5
					? String.fromCharCode(parseInt(escape.slice(1), 16))
					: (JSON_ESCAPES[escape] ?? escape)
			);
	}
	if (typeof parsed === 'string') return parsed;
	if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
		const record = parsed as Record<string, unknown>;
		const main = RESULT_TEXT_FIELDS.find(
			(key) => typeof record[key] === 'string' && (record[key] as string).trim()
		);
		if (main) {
			const rest = Object.entries(record)
				.filter(
					([key, value]) =>
						key !== main &&
						value !== '' &&
						['string', 'number', 'boolean'].includes(typeof value)
				)
				.map(([key, value]) => `${key}: ${value}`);
			return [(record[main] as string).trimEnd(), ...rest].join('\n');
		}
	}
	return JSON.stringify(parsed, null, 2);
};

/** What a hermes call returned, readable ('' when hermes sent no preview). */
export const getToolCallOutput = (resultValue: unknown): string => {
	if (!isOutcomeOnlyResult(resultValue)) return '';
	const parsed = parseJsonLike(resultValue);
	const output =
		parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>).output : null;
	return typeof output === 'string' && output.trim() ? formatToolOutput(output) : '';
};

/** A hermes result without its `output` preview: the outcome JSON shown beside it. */
export const stripToolCallOutput = (resultValue: unknown): string => {
	const parsed = parseJsonLike(resultValue);
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		return decode(String(resultValue ?? ''));
	}
	const { output: _output, ...outcome } = parsed as Record<string, unknown>;
	return JSON.stringify(outcome);
};

/** Epoch seconds the call started at, from the `started` attribute hermes runs set. */
export const getToolCallStartedAt = (
	attributes: ToolTokenAttributes | null | undefined
): number | null => {
	const value = Number(decode(String(attributes?.started ?? '')));
	return Number.isFinite(value) && value > 0 ? value : null;
};

/** "1 分 37 秒", "2 小时 5 分": a run's length; '' under a second. */
export const formatRunDuration = (seconds: number | null | undefined): string => {
	if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 1) {
		return '';
	}
	const total = Math.round(seconds);
	const hours = Math.floor(total / 3600);
	const minutes = Math.floor((total % 3600) / 60);
	const rest = total % 60;
	if (hours > 0) return minutes > 0 ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
	if (minutes > 0) return rest > 0 ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
	return `${rest} 秒`;
};

/**
 * One call's time in the same words as a run's ("3.3 秒", "2 分 5 秒"), with
 * tenths below ten seconds; a ticking clock passes whole seconds ("45 秒").
 */
export const formatToolDuration = (seconds: number | null | undefined): string => {
	if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
		return '';
	}
	if (seconds >= 60) return formatRunDuration(seconds);
	if (Number.isInteger(seconds) || seconds >= 10) return `${Math.round(seconds)} 秒`;
	if (seconds < 0.1) return '不到 0.1 秒';
	return `${seconds.toFixed(1)} 秒`;
};

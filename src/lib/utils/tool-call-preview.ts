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
	/** null while the call is still running or when the result has no status. */
	status: 'success' | 'error' | null;
	/** Seconds, when the result reports a duration. */
	duration: number | null;
};

export const getToolCallOutcome = (resultValue: unknown): ToolCallOutcome => {
	const parsed = parseJsonLike(resultValue);
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		return { status: null, duration: null };
	}
	const record = parsed as Record<string, unknown>;
	const rawStatus = typeof record.status === 'string' ? record.status.toLowerCase() : '';
	const status =
		rawStatus === 'error' || rawStatus === 'failed' || record.error === true
			? 'error'
			: rawStatus === 'success' || rawStatus === 'ok'
				? 'success'
				: null;
	const duration = Number(record.duration);
	return {
		status,
		duration: Number.isFinite(duration) && duration >= 0 ? duration : null
	};
};

export const formatToolDuration = (seconds: number | null): string => {
	if (seconds === null) return '';
	if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
	if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
	const minutes = Math.floor(seconds / 60);
	const rest = Math.round(seconds % 60);
	return rest > 0 ? `${minutes}m ${rest}s` : `${minutes}m`;
};

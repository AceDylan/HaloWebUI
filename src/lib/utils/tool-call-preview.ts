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

/** "skill_view ×20 · terminal ×6": what a group of calls did, by tool, most used first. */
export const summarizeToolNames = (names: string[], maxNames = 3): string => {
	const counts = new Map<string, number>();
	for (const raw of names) {
		const name = (raw ?? '').trim() || 'tool';
		counts.set(name, (counts.get(name) ?? 0) + 1);
	}
	const ordered = [...counts.entries()].sort((a, b) => b[1] - a[1]);
	const shown = ordered
		.slice(0, maxNames)
		.map(([name, count]) => (count > 1 ? `${name} ×${count}` : name));
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
 * True when the result is only an outcome (status/duration/reason), which is
 * all hermes reports: nothing worth showing as JSON.
 */
export const isOutcomeOnlyResult = (resultValue: unknown): boolean => {
	const parsed = parseJsonLike(resultValue);
	if (parsed === '' || parsed === null || parsed === undefined) return true;
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return false;
	return Object.keys(parsed as Record<string, unknown>).every((key) =>
		['status', 'duration', 'reason', 'error'].includes(key)
	);
};

/** Epoch seconds the call started at, from the `started` attribute hermes runs set. */
export const getToolCallStartedAt = (
	attributes: ToolTokenAttributes | null | undefined
): number | null => {
	const value = Number(decode(String(attributes?.started ?? '')));
	return Number.isFinite(value) && value > 0 ? value : null;
};

export const formatToolDuration = (seconds: number | null): string => {
	if (seconds === null) return '';
	if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
	if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
	const minutes = Math.floor(seconds / 60);
	const rest = Math.round(seconds % 60);
	return rest > 0 ? `${minutes}m ${rest}s` : `${minutes}m`;
};

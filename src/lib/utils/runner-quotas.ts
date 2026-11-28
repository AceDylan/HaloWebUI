import type { RunnerQuota } from '$lib/apis/hermes';

export type QuotaWindow = RunnerQuota['windows'][number];
export type QuotaThemeKey = 'amber' | 'cyan' | 'emerald' | 'slate';
export type QuotaWindowLevel = 'healthy' | 'caution' | 'low' | 'empty';

export type QuotaMeta = {
	runner: string;
	title: string;
	subtitle: string;
	theme: QuotaThemeKey;
};

export type QuotaWindowMetrics = {
	usedPct: number;
	remainingPct: number;
	level: QuotaWindowLevel;
};

const RUNNER_ORDER: Record<string, number> = {
	officlaude: 0,
	offiagy: 1,
	'openai-codex': 2
};

const pad2 = (n: number) => String(n).padStart(2, '0');

export const normalizeQuotaRunner = (runner?: string | null): string => {
	const cleaned = typeof runner === 'string' ? runner.trim().toLowerCase() : '';
	return cleaned || 'officlaude';
};

/** Keep the canonical account order (officlaude → offiagy → openai-codex → others) stably. */
export const orderOfficialQuotas = (quotas: RunnerQuota[]): RunnerQuota[] => {
	if (!Array.isArray(quotas)) return [];
	return quotas
		.map((quota, index) => ({
			quota,
			index,
			rank: RUNNER_ORDER[normalizeQuotaRunner(quota?.runner)] ?? 99
		}))
		.sort((a, b) => a.rank - b.rank || a.index - b.index)
		.map((entry) => entry.quota);
};

export const getQuotaMeta = (quota: Pick<RunnerQuota, 'runner' | 'label'>): QuotaMeta => {
	const runner = normalizeQuotaRunner(quota?.runner);
	if (runner === 'officlaude') {
		return {
			runner,
			title: '官方 Claude',
			subtitle: 'officlaude',
			theme: 'amber'
		};
	}
	if (runner === 'offiagy') {
		return {
			runner,
			title: 'offiagy',
			subtitle: 'AGY · Gemini 官方额度',
			theme: 'cyan'
		};
	}
	if (runner === 'openai-codex') {
		return {
			runner,
			title: 'Hermes Codex',
			subtitle: 'openai-codex',
			theme: 'emerald'
		};
	}
	const fallbackTitle = typeof quota?.label === 'string' && quota.label.trim() ? quota.label.trim() : runner;
	return {
		runner,
		title: fallbackTitle,
		subtitle: runner,
		theme: 'slate'
	};
};

/**
 * Filter quota windows for display.
 * For offiagy, hide Claude/GPT and generic five_hour/seven_day windows while strictly
 * preserving the upstream Hermes window order (Gemini 5h → Gemini Weekly → Argon/others).
 */
export const getVisibleQuotaWindows = (quota: Pick<RunnerQuota, 'runner' | 'windows'>): QuotaWindow[] => {
	const windows = Array.isArray(quota?.windows) ? quota.windows : [];
	if (normalizeQuotaRunner(quota?.runner) !== 'offiagy') {
		return [...windows];
	}
	return windows.filter(
		(w) =>
			!/claude|gpt/i.test(`${w?.key ?? ''} ${w?.label ?? ''}`) &&
			w?.key !== 'five_hour' &&
			w?.key !== 'seven_day'
	);
};

/** Clamp utilization to [0, 100], round to integer percent, and derive remaining percentage & severity level. */
export const computeWindowMetrics = (utilization: number): QuotaWindowMetrics => {
	const finite = typeof utilization === 'number' && Number.isFinite(utilization) ? utilization : 0;
	const clamped = Math.max(0, Math.min(100, finite));
	const usedPct = Math.round(clamped);
	const remainingPct = Math.max(0, Math.min(100, 100 - usedPct));
	const level: QuotaWindowLevel =
		remainingPct <= 0
			? 'empty'
			: remainingPct <= 10
				? 'low'
				: remainingPct <= 25
					? 'caution'
					: 'healthy';
	return { usedPct, remainingPct, level };
};

const toValidDate = (input: number | string | Date | null | undefined): Date | null => {
	if (input === null || input === undefined || input === '') return null;
	const date =
		input instanceof Date
			? input
			: typeof input === 'number'
				? Number.isFinite(input) && input > 0
					? new Date(input * 1000)
					: null
				: new Date(input);
	if (!date || Number.isNaN(date.getTime())) return null;
	return date;
};

const isSameLocalDay = (a: Date, b: Date): boolean =>
	a.getFullYear() === b.getFullYear() &&
	a.getMonth() === b.getMonth() &&
	a.getDate() === b.getDate();

/** Format a Unix timestamp (seconds), ISO string, or Date into "今天 HH:MM[:SS]" or "MM-DD HH:MM[:SS]". */
export const formatQuotaShortTime = (
	input: number | string | Date | null | undefined,
	options: { now?: Date; withSeconds?: boolean } = {}
): string => {
	const date = toValidDate(input);
	if (!date) return '时间未知';
	const now = options.now ?? new Date();
	const hhmm = `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
	const clock = options.withSeconds ? `${hhmm}:${pad2(date.getSeconds())}` : hhmm;
	if (isSameLocalDay(date, now)) {
		return `今天 ${clock}`;
	}
	return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${clock}`;
};

/** Format a human-friendly relative reset countdown from an ISO reset timestamp. */
export const formatResetCountdown = (
	resetsAt: string | null | undefined,
	now: Date = new Date()
): string => {
	const target = toValidDate(resetsAt);
	if (!target) return '';
	const diffMs = target.getTime() - now.getTime();
	if (diffMs <= 0) return '即将重置';
	if (diffMs < 60_000) return '不到 1 分钟后';
	if (diffMs < 3_600_000) {
		const minutes = Math.max(1, Math.round(diffMs / 60_000));
		return minutes >= 60 ? '约 1 小时后' : `约 ${minutes} 分钟后`;
	}
	if (diffMs < 86_400_000) {
		const totalMinutes = Math.round(diffMs / 60_000);
		const hours = Math.floor(totalMinutes / 60);
		const minutes = totalMinutes % 60;
		if (hours >= 24) return '约 1 天后';
		if (minutes === 0) return `约 ${hours} 小时后`;
		return `约 ${hours} 小时 ${minutes} 分钟后`;
	}
	const totalHours = Math.round(diffMs / 3_600_000);
	const days = Math.floor(totalHours / 24);
	const hours = totalHours % 24;
	if (hours === 0) return `约 ${days} 天后`;
	return `约 ${days} 天 ${hours} 小时后`;
};

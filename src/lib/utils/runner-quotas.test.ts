import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RunnerQuota } from '$lib/apis/hermes';
import {
	computeWindowMetrics,
	formatQuotaShortTime,
	formatResetCountdown,
	getQuotaMeta,
	getVisibleQuotaWindows,
	normalizeQuotaRunner,
	orderOfficialQuotas
} from './runner-quotas';

vi.mock('$lib/constants', () => ({ WEBUI_API_BASE_URL: '/api/v1' }));

const makeQuota = (overrides: Partial<RunnerQuota> = {}): RunnerQuota => ({
	runner: 'officlaude',
	label: '官方 Claude',
	available: true,
	checked_at: 1764315720,
	windows: [],
	...overrides
});

describe('normalizeQuotaRunner', () => {
	it('normalizes casing/whitespace and falls back to officlaude', () => {
		expect(normalizeQuotaRunner('  OffiAGY  ')).toBe('offiagy');
		expect(normalizeQuotaRunner('OPENAI-CODEX')).toBe('openai-codex');
		expect(normalizeQuotaRunner('')).toBe('officlaude');
		expect(normalizeQuotaRunner('   ')).toBe('officlaude');
		expect(normalizeQuotaRunner(undefined)).toBe('officlaude');
		expect(normalizeQuotaRunner(null)).toBe('officlaude');
	});
});

describe('orderOfficialQuotas', () => {
	it('orders officlaude → offiagy → openai-codex → others stably without mutating input', () => {
		const input = [
			makeQuota({ runner: 'custom-b', label: 'B' }),
			makeQuota({ runner: 'openai-codex', label: 'Hermes Codex' }),
			makeQuota({ runner: 'offiagy', label: 'offiagy' }),
			makeQuota({ runner: 'custom-a', label: 'A' }),
			makeQuota({ runner: 'officlaude', label: '官方 Claude' })
		];
		const snapshot = input.map((q) => q.runner);

		const ordered = orderOfficialQuotas(input);
		expect(ordered.map((q) => q.runner)).toEqual([
			'officlaude',
			'offiagy',
			'openai-codex',
			'custom-b',
			'custom-a'
		]);
		expect(input.map((q) => q.runner)).toEqual(snapshot);
	});
});

describe('getQuotaMeta', () => {
	it('returns curated metadata for each official account and safe fallback for unknown runners', () => {
		expect(getQuotaMeta(makeQuota({ runner: 'officlaude' }))).toEqual({
			runner: 'officlaude',
			title: '官方 Claude',
			subtitle: 'officlaude',
			theme: 'amber'
		});
		expect(getQuotaMeta(makeQuota({ runner: 'offiagy' }))).toEqual({
			runner: 'offiagy',
			title: 'offiagy',
			subtitle: 'AGY · Gemini 官方额度',
			theme: 'cyan'
		});
		expect(getQuotaMeta(makeQuota({ runner: 'openai-codex' }))).toEqual({
			runner: 'openai-codex',
			title: 'Hermes Codex',
			subtitle: 'openai-codex',
			theme: 'emerald'
		});
		expect(getQuotaMeta(makeQuota({ runner: 'other-sub', label: '自定义订阅' }))).toEqual({
			runner: 'other-sub',
			title: '自定义订阅',
			subtitle: 'other-sub',
			theme: 'slate'
		});
	});
});

describe('getVisibleQuotaWindows', () => {
	it('filters out Claude/GPT and five_hour/seven_day for offiagy while preserving upstream window order', () => {
		const offiagy = makeQuota({
			runner: 'offiagy',
			windows: [
				{ key: 'five_hour', label: '5 小时', utilization: 10, resets_at: null },
				{ key: 'gemini_five_hour', label: 'Gemini 5 小时', utilization: 5, resets_at: null },
				{ key: 'claude_five_hour', label: 'Claude 5 小时', utilization: 40, resets_at: null },
				{ key: 'gpt_weekly', label: 'GPT 每周', utilization: 20, resets_at: null },
				{ key: 'gemini_weekly', label: 'Gemini 每周（Weekly Limit）', utilization: 12, resets_at: null },
				{ key: 'seven_day', label: '每周', utilization: 15, resets_at: null },
				{ key: 'argon', label: 'Argon', utilization: 0, resets_at: null },
				{ key: 'extra', label: 'Claude Pro', utilization: 50, resets_at: null }
			]
		});

		const visible = getVisibleQuotaWindows(offiagy);
		expect(visible.map((w) => w.key)).toEqual(['gemini_five_hour', 'gemini_weekly', 'argon']);
	});

	it('keeps windows untouched for officlaude and openai-codex', () => {
		const claude = makeQuota({
			runner: 'officlaude',
			windows: [
				{ key: 'five_hour', label: '5 小时', utilization: 18, resets_at: null },
				{ key: 'seven_day', label: '每周', utilization: 42, resets_at: null }
			]
		});
		expect(getVisibleQuotaWindows(claude).map((w) => w.key)).toEqual(['five_hour', 'seven_day']);
	});
});

describe('computeWindowMetrics', () => {
	it('clamps utilization to [0, 100], rounds percentages, and classifies levels accurately', () => {
		expect(computeWindowMetrics(0)).toEqual({ usedPct: 0, remainingPct: 100, level: 'healthy' });
		expect(computeWindowMetrics(74)).toEqual({ usedPct: 74, remainingPct: 26, level: 'healthy' });
		expect(computeWindowMetrics(75)).toEqual({ usedPct: 75, remainingPct: 25, level: 'caution' });
		expect(computeWindowMetrics(89)).toEqual({ usedPct: 89, remainingPct: 11, level: 'caution' });
		expect(computeWindowMetrics(90)).toEqual({ usedPct: 90, remainingPct: 10, level: 'low' });
		expect(computeWindowMetrics(99.4)).toEqual({ usedPct: 99, remainingPct: 1, level: 'low' });
		expect(computeWindowMetrics(99.6)).toEqual({ usedPct: 100, remainingPct: 0, level: 'empty' });
		expect(computeWindowMetrics(100)).toEqual({ usedPct: 100, remainingPct: 0, level: 'empty' });
		expect(computeWindowMetrics(135)).toEqual({ usedPct: 100, remainingPct: 0, level: 'empty' });
		expect(computeWindowMetrics(-12)).toEqual({ usedPct: 0, remainingPct: 100, level: 'healthy' });
		expect(computeWindowMetrics(Number.NaN)).toEqual({
			usedPct: 0,
			remainingPct: 100,
			level: 'healthy'
		});
		expect(computeWindowMetrics(Number.POSITIVE_INFINITY)).toEqual({
			usedPct: 0,
			remainingPct: 100,
			level: 'healthy'
		});
	});
});

describe('formatQuotaShortTime', () => {
	const now = new Date(2026, 10, 28, 15, 30, 0); // 2026-11-28 15:30:00 local

	it('formats same-day timestamps with optional seconds', () => {
		const sameDay = new Date(2026, 10, 28, 19, 5, 9);
		expect(formatQuotaShortTime(sameDay, { now })).toBe('今天 19:05');
		expect(formatQuotaShortTime(sameDay, { now, withSeconds: true })).toBe('今天 19:05:09');
		expect(formatQuotaShortTime(sameDay.getTime() / 1000, { now, withSeconds: true })).toBe(
			'今天 19:05:09'
		);
	});

	it('formats different-day timestamps as MM-DD HH:MM[:SS]', () => {
		const nextWeek = new Date(2026, 11, 2, 9, 4, 3);
		expect(formatQuotaShortTime(nextWeek, { now })).toBe('12-02 09:04');
		expect(formatQuotaShortTime(nextWeek, { now, withSeconds: true })).toBe('12-02 09:04:03');
		expect(formatQuotaShortTime(nextWeek.toISOString(), { now })).toBe('12-02 09:04');
	});

	it('returns fallback for nullish or invalid inputs', () => {
		expect(formatQuotaShortTime(null, { now })).toBe('时间未知');
		expect(formatQuotaShortTime(undefined, { now })).toBe('时间未知');
		expect(formatQuotaShortTime('', { now })).toBe('时间未知');
		expect(formatQuotaShortTime(0, { now })).toBe('时间未知');
		expect(formatQuotaShortTime('not-a-date', { now })).toBe('时间未知');
	});
});

describe('formatResetCountdown', () => {
	const now = new Date('2026-11-28T08:00:00Z');

	it('handles past, sub-minute, minute, hour, and day horizons', () => {
		expect(formatResetCountdown('2026-11-28T07:59:00Z', now)).toBe('即将重置');
		expect(formatResetCountdown('2026-11-28T08:00:00Z', now)).toBe('即将重置');
		expect(formatResetCountdown('2026-11-28T08:00:30Z', now)).toBe('不到 1 分钟后');
		expect(formatResetCountdown('2026-11-28T08:25:00Z', now)).toBe('约 25 分钟后');
		expect(formatResetCountdown('2026-11-28T10:00:00Z', now)).toBe('约 2 小时后');
		expect(formatResetCountdown('2026-11-28T10:30:00Z', now)).toBe('约 2 小时 30 分钟后');
		expect(formatResetCountdown('2026-11-30T08:00:00Z', now)).toBe('约 2 天后');
		expect(formatResetCountdown('2026-11-30T11:00:00Z', now)).toBe('约 2 天 3 小时后');
	});

	it('returns empty string for empty or invalid timestamps', () => {
		expect(formatResetCountdown(null, now)).toBe('');
		expect(formatResetCountdown(undefined, now)).toBe('');
		expect(formatResetCountdown('invalid', now)).toBe('');
	});
});

describe('getOfficialQuotas API contract', () => {
	const originalFetch = globalThis.fetch;

	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('requests GET /api/v1/hermes/quotas with Bearer token and normalizes quotas', async () => {
		const fetchMock = vi.fn(async () => ({
			ok: true,
			status: 200,
			statusText: 'OK',
			json: async () => ({
				quotas: [makeQuota({ runner: 'officlaude' }), null],
				fetched_at: 1764315720.89,
				cache_ttl_seconds: 60
			})
		}));
		globalThis.fetch = fetchMock as any;

		const { getOfficialQuotas } = await import('$lib/apis/hermes');
		const data = await getOfficialQuotas('secret-tok');
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/hermes/quotas', {
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: 'Bearer secret-tok'
			}
		});
		expect(data.quotas).toHaveLength(1);
		expect(data.quotas[0].runner).toBe('officlaude');
		expect(data.fetched_at).toBe(1764315720.89);
		expect(data.cache_ttl_seconds).toBe(60);
	});

	it('falls back to legacy single quota payload and maps 401/501 errors properly', async () => {
		const { getOfficialQuotas, HermesSessionExpiredError } = await import('$lib/apis/hermes');

		globalThis.fetch = vi.fn(async () => ({
			ok: true,
			status: 200,
			statusText: 'OK',
			json: async () => ({ quota: makeQuota({ runner: 'officlaude' }) })
		})) as any;
		const legacy = await getOfficialQuotas('tok');
		expect(legacy.quotas).toHaveLength(1);
		expect(legacy.fetched_at).toBeGreaterThan(0);

		globalThis.fetch = vi.fn(async () => ({
			ok: false,
			status: 401,
			statusText: 'Unauthorized',
			json: async () => ({ detail: 'Not authenticated' })
		})) as any;
		await expect(getOfficialQuotas('tok')).rejects.toBeInstanceOf(HermesSessionExpiredError);

		globalThis.fetch = vi.fn(async () => ({
			ok: false,
			status: 501,
			statusText: 'Not Implemented',
			json: async () => ({
				detail: '这个 Hermes 还不支持额度查询，更新 Hermes 并重启网关后再试'
			})
		})) as any;
		await expect(getOfficialQuotas('tok')).rejects.toBe(
			'这个 Hermes 还不支持额度查询，更新 Hermes 并重启网关后再试'
		);
	});
});


import { describe, expect, it } from 'vitest';
import { formatHours, formatTokens, formatUsd, summarizeRuns, tokensTitle } from './runner-stats';

const now = new Date(2026, 9, 9, 20, 0, 0).getTime() / 1000;
const run = (patch: object) => ({
	run_id: 'r',
	agent: 'reclaude',
	status: 'success',
	failure_kind: '',
	started_at: now - 3600,
	ended_at: now - 3000,
	duration_s: 600,
	cost_usd: 2,
	turns: 10,
	tool_calls: 5,
	model: 'claude-opus-5-5',
	cwd: '/root/HaloWebUI',
	project: 'HaloWebUI',
	origin: 'telegram',
	parent_run: '',
	title: 't',
	...patch
});

describe('summarizeRuns', () => {
	it('keeps the first partial day of the rolling window so daily costs match the total', () => {
		const stats = summarizeRuns(
			[run({ started_at: now - 7 * 86400 + 3600, cost_usd: 104.78 }), run({ cost_usd: 2 })] as any,
			7,
			now
		);
		expect(stats.daily[0]).toMatchObject({ day: '2026-10-02', runs: 1, cost: 104.78 });
		expect(stats.daily).toHaveLength(8);
		expect(stats.daily.reduce((sum, day) => sum + day.cost, 0)).toBeCloseTo(stats.total.cost);
		expect(stats.daily.reduce((sum, day) => sum + day.runs, 0)).toBe(stats.total.runs);
	});
	it('sums per runner, per project and per day, with every day of the window', () => {
		const runs = [
			run({}),
			run({ agent: 'codex', cost_usd: 0, status: 'error', project: '', duration_s: 300 }),
			run({
				status: 'error',
				failure_kind: 'quota_reset',
				cost_usd: 1,
				started_at: now - 2 * 86400
			}),
			run({ agent: 'agy', cost_usd: null, duration_s: null, turns: null, status: 'running' })
		];
		const s = summarizeRuns(runs as any, 7, now);
		expect(s.total).toMatchObject({ runs: 4, ok: 1, failed: 2, quota: 1, cost: 3, seconds: 1500 });
		expect(s.byRunner.map((g) => [g.key, g.runs, g.cost])).toEqual([
			['reclaude', 2, 3],
			['codex', 1, 0],
			['agy', 1, 0]
		]);
		expect(s.byProject.map((g) => g.key)).toEqual(['HaloWebUI', '（不在项目里）']);
		expect(s.daily).toHaveLength(7);
		expect(s.daily.at(-1)).toMatchObject({ day: '2026-10-09', runs: 3, cost: 2 });
		expect(s.daily.at(-3)).toMatchObject({ day: '2026-10-07', runs: 1, cost: 1 });
		expect(s.daily[0]).toMatchObject({ day: '2026-10-03', runs: 0, cost: 0 });
	});

	it('counts estimated costs and tokens (codex / agy report tokens, Hermes prices them)', () => {
		const tokens = { input: 1000, cached: 20000, output: 500 };
		const s = summarizeRuns(
			[
				run({}),
				run({ agent: 'codex', cost_usd: 0.5, cost_estimated: true, tokens }),
				run({ agent: 'codex', cost_usd: 0.25, cost_estimated: true, tokens })
			] as any,
			1,
			now
		);
		expect(s.total).toMatchObject({ cost: 2.75, estimated: 2, tokens: 43000 });
		expect(s.byRunner.find((g) => g.key === 'codex')).toMatchObject({ estimated: 2, cost: 0.75 });
		expect(s.byRunner.find((g) => g.key === 'reclaude')).toMatchObject({ estimated: 0, tokens: 0 });
		expect(formatTokens(43000)).toBe('4.3 万');
		expect(formatTokens(256_000)).toBe('26 万');
		expect(formatTokens(170_000_000)).toBe('1.7 亿');
		expect(tokensTitle({ tokens } as any)).toContain('缓存 2.0 万');
	});

	it('formats money and time', () => {
		expect(formatUsd(533.66)).toBe('$534');
		expect(formatUsd(2.19)).toBe('$2.2');
		expect(formatUsd(0.04)).toBe('$0.04');
		expect(formatHours(45)).toBe('45 秒');
		expect(formatHours(1800)).toBe('30 分钟');
		expect(formatHours(5.1 * 3600)).toBe('5.1 小时');
		expect(formatHours(29.5 * 3600)).toBe('30 小时');
	});

	it('counts official subscription limits as quota interruptions', () => {
		const stats = summarizeRuns(
			[run({ status: 'error', failure_kind: 'official_limit' })] as any,
			1,
			now
		);
		expect(stats.total).toMatchObject({ failed: 1, quota: 1 });
	});
});

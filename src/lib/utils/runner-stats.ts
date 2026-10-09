// 数据分析 → 后台任务: the runner runs Hermes reports (GET /v1/runners/stats), summed up —
// overall, per runner, per project and per day.

import type { RunnerRun } from '$lib/apis/hermes';

export type RunnerGroup = {
	key: string;
	runs: number;
	ok: number;
	failed: number;
	/** runs that stopped because the subscription's quota ran out */
	quota: number;
	cost: number;
	seconds: number;
	turns: number;
};

const FAILED = new Set(['error', 'failed', 'timeout', 'max_turns', 'killed']);
const OK = new Set(['success', 'done', 'completed']);
const QUOTA_STOPS = new Set(['quota_reset', 'quota_window', 'quota', 'official_limit']);

/** the run stopped because a subscription's quota ran out */
export const isQuotaStop = (run: RunnerRun) => QUOTA_STOPS.has(run.failure_kind);
export const isFailed = (run: RunnerRun) => FAILED.has(run.status);

export const STATUS_LABEL: Record<string, string> = {
	success: '完成',
	done: '完成',
	completed: '完成',
	error: '失败',
	failed: '失败',
	timeout: '超时',
	max_turns: '轮数上限',
	killed: '已终止',
	stopped: '已停止',
	interrupted: '已中断',
	question: '等你回答',
	running: '运行中',
	queued: '排队中',
	quota_blocked: '额度不足'
};

const emptyGroup = (key: string): RunnerGroup => ({
	key,
	runs: 0,
	ok: 0,
	failed: 0,
	quota: 0,
	cost: 0,
	seconds: 0,
	turns: 0
});

const add = (group: RunnerGroup, run: RunnerRun) => {
	group.runs += 1;
	if (OK.has(run.status)) group.ok += 1;
	else if (FAILED.has(run.status)) group.failed += 1;
	if (isQuotaStop(run)) group.quota += 1;
	group.cost += run.cost_usd ?? 0;
	group.seconds += run.duration_s ?? 0;
	group.turns += run.turns ?? 0;
};

const groupBy = (runs: RunnerRun[], keyOf: (run: RunnerRun) => string) => {
	const groups = new Map<string, RunnerGroup>();
	for (const run of runs) {
		const key = keyOf(run);
		if (!groups.has(key)) groups.set(key, emptyGroup(key));
		add(groups.get(key)!, run);
	}
	return [...groups.values()].sort((a, b) => b.cost - a.cost || b.runs - a.runs);
};

const dayKey = (ts: number) => {
	const d = new Date(ts * 1000);
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export const summarizeRuns = (runs: RunnerRun[], days: number, now = Date.now() / 1000) => {
	const total = emptyGroup('all');
	runs.forEach((run) => add(total, run));
	// The API uses a rolling N * 24-hour window. Keep its first partial calendar
	// day too, otherwise the daily chart silently drops runs counted in the total.
	const daily: (RunnerGroup & { day: string })[] = [];
	const byDay = new Map(groupBy(runs, (run) => dayKey(run.started_at)).map((g) => [g.key, g]));
	const start = new Date(now * 1000);
	start.setHours(0, 0, 0, 0);
	start.setDate(start.getDate() - days + 1);
	for (const run of runs) {
		const date = new Date(run.started_at * 1000);
		date.setHours(0, 0, 0, 0);
		if (date < start) start.setTime(date.getTime());
	}
	for (
		const date = new Date(start);
		date.getTime() <= now * 1000;
		date.setDate(date.getDate() + 1)
	) {
		const day = dayKey(date.getTime() / 1000);
		daily.push({ ...(byDay.get(day) ?? emptyGroup(day)), day });
	}
	return {
		total,
		byRunner: groupBy(runs, (run) => run.agent),
		byProject: groupBy(runs, (run) => run.project || '（不在项目里）'),
		daily
	};
};

export const formatUsd = (value: number) =>
	value >= 100
		? `$${Math.round(value)}`
		: value >= 1
			? `$${value.toFixed(1)}`
			: `$${value.toFixed(2)}`;

export const formatHours = (seconds: number) => {
	if (seconds < 60) return `${Math.round(seconds)} 秒`;
	if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
	const hours = seconds / 3600;
	return `${hours >= 10 ? Math.round(hours) : hours.toFixed(1)} 小时`;
};

export const RUNNER_LABEL: Record<string, string> = {
	officlaude: '官方 Claude'
};
export const runnerName = (key: string) => RUNNER_LABEL[key] ?? key;

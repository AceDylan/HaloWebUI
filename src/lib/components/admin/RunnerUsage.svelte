<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getRunnerStats, type RunnerRun, type RunnerQuota } from '$lib/apis/hermes';
	import { summarizeRuns, formatUsd, formatHours, RUNNER_LABEL } from '$lib/utils/runner-stats';

	export let days = 30;
	let loadedDays = 0;
	let runs: RunnerRun[] = [];
	let quota: RunnerQuota | undefined;
	let loading = true;
	let error = '';
	let runner = '';
	let project = '';
	let page = 0;
	let showDailyTable = false;
	let requestId = 0;
	let mounted = false;
	const pageSize = 25;
	const labels: Record<string, string> = {
		success: '完成',
		done: '完成',
		completed: '完成',
		error: '失败',
		failed: '失败',
		timeout: '超时',
		max_turns: '轮数上限',
		killed: '已终止',
		stopped: '已停止',
		running: '运行中',
		queued: '排队中',
		quota_blocked: '额度不足'
	};
	const runnerName = (key: string) => RUNNER_LABEL[key] ?? key;
	const dateTime = (ts: number) => new Date(ts * 1000).toLocaleString();
	const resetTime = (value: string | null) => (value ? new Date(value).toLocaleString() : '未知');

	const load = async (windowDays = days) => {
		const id = ++requestId;
		loading = true;
		error = '';
		try {
			const data = await getRunnerStats(localStorage.token, Math.min(windowDays, 90));
			if (id !== requestId) return;
			runs = data.runs;
			quota = data.quota;
			loadedDays = data.days;
			page = 0;
		} catch (err) {
			if (id === requestId) error = String(err);
		} finally {
			if (id === requestId) loading = false;
		}
	};
	onMount(() => {
		mounted = true;
	});
	onDestroy(() => {
		mounted = false;
		requestId += 1;
	});
	$: if (mounted && days) load(days);
	$: filtered = runs.filter(
		(run) => (!runner || run.agent === runner) && (!project || run.project === project)
	);
	$: summary = summarizeRuns(filtered, loadedDays || Math.min(days, 90));
	$: maxCost = Math.max(...summary.daily.map((day) => day.cost), 0.01);
	$: reportedCost = filtered.filter((run) => run.cost_usd !== null).length;
	$: pages = Math.max(1, Math.ceil(filtered.length / pageSize));
	$: visible = filtered.slice(page * pageSize, (page + 1) * pageSize);
	$: runnerOptions = [...new Set(runs.map((run) => run.agent))].sort();
	$: projectOptions = [...new Set(runs.map((run) => run.project).filter(Boolean))].sort();
</script>

<div class="space-y-5" data-halo-runner-usage>
	<div class="flex flex-wrap items-center gap-3 text-sm">
		<label
			>执行器
			<select
				class="ml-2 rounded-lg bg-gray-100 p-2 dark:bg-gray-850"
				bind:value={runner}
				on:change={() => (page = 0)}
			>
				<option value="">全部</option>
				{#each runnerOptions as key}<option value={key}>{runnerName(key)}</option>{/each}
			</select>
		</label>
		<label
			>项目
			<select
				class="ml-2 rounded-lg bg-gray-100 p-2 dark:bg-gray-850"
				bind:value={project}
				on:change={() => (page = 0)}
			>
				<option value="">全部</option>
				{#each projectOptions as name}<option value={name}>{name}</option>{/each}
			</select>
		</label>
		<button
			class="ml-auto rounded-lg px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-800"
			disabled={loading}
			on:click={() => load()}>刷新</button
		>
	</div>
	{#if quota?.available}
		<div
			class="rounded-xl border border-gray-200 p-3 text-sm dark:border-gray-700"
			data-halo-runner-quota
		>
			<div class="font-medium">官方 Claude 订阅额度</div>
			{#each quota.windows as window}
				<p class="mt-1" role={window.utilization >= 90 ? 'alert' : undefined}>
					{#if window.utilization >= 90}<span aria-hidden="true">⚠ </span>{/if}
					{window.label}已用 {Math.round(window.utilization)}% · {resetTime(window.resets_at)} 重置
					{#if window.utilization >= 100}
						· 额度已用完{:else if window.utilization >= 90}
						· 额度即将用完{/if}
				</p>
			{/each}
			<p class="mt-1 text-xs text-gray-500">查询于 {dateTime(quota.checked_at)}</p>
		</div>
	{:else if !loading && !error}
		<p class="text-xs text-gray-500">{quota?.notice || '当前执行器未提供实时订阅额度。'}</p>
	{/if}
	{#if loading}
		<p class="py-8 text-center text-sm text-gray-500" role="status">正在读取后台任务…</p>
	{:else if error}
		<div class="rounded-xl border border-gray-200 p-4 text-sm dark:border-gray-700" role="alert">
			读取失败：{error}。请刷新重试。
		</div>
	{:else if filtered.length === 0}
		<p class="py-8 text-center text-sm text-gray-500">这段时间没有符合条件的后台任务。</p>
	{:else}
		<div class="grid grid-cols-2 gap-3 md:grid-cols-4">
			{#each [{ label: '任务数', value: summary.total.runs }, { label: 'API 折算费用', value: formatUsd(summary.total.cost) }, { label: '累计耗时', value: formatHours(summary.total.seconds) }, { label: '累计轮数', value: summary.total.turns }] as card}
				<div
					class="rounded-2xl border border-gray-100 bg-white/70 p-4 dark:border-gray-800 dark:bg-gray-900/60"
				>
					<div class="text-2xl font-semibold tabular-nums">{card.value}</div>
					<div class="mt-1 text-xs text-gray-500">{card.label}</div>
				</div>
			{/each}
		</div>
		<p class="text-xs text-gray-500">
			最近 {loadedDays} 天的已保留记录 · 完成 {summary.total.ok}，失败 {summary.total
				.failed}，额度中断 {summary.total.quota}。费用是执行器自报的 API
			价格折算值，订阅实际账单另计；{reportedCost}/{filtered.length} 次任务提供了费用，缺失值不参与合计。
		</p>
		<section aria-label="每日 API 折算费用">
			<div class="mb-3 flex items-center justify-between text-sm">
				<h3 class="font-medium">每日 API 折算费用（USD）</h3>
				<button class="text-xs underline" on:click={() => (showDailyTable = !showDailyTable)}
					>{showDailyTable ? '隐藏每日明细' : '查看每日明细'}</button
				>
			</div>
			<div
				class="relative flex h-36 items-end gap-px rounded-xl border border-gray-200 p-3 dark:border-gray-700"
			>
				<span class="absolute right-2 top-1 text-xs text-gray-500">{formatUsd(maxCost)}</span>
				{#each summary.daily as day}
					<div
						class="flex-1 rounded-t bg-gray-600 dark:bg-gray-400"
						style="height: {(day.cost / maxCost) * 100}%"
						role="img"
						aria-label={`${day.day}：${formatUsd(day.cost)}，${day.runs} 次任务`}
						title={`${day.day}：${formatUsd(day.cost)}，${day.runs} 次任务`}
					></div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between text-xs text-gray-500">
				<span>{summary.daily[0]?.day}</span><span>{summary.daily.at(-1)?.day}</span>
			</div>
			{#if showDailyTable}
				<div class="mt-3 max-h-64 overflow-auto text-sm">
					<table class="w-full text-left">
						<thead><tr><th>日期</th><th>任务数</th><th>折算费用</th><th>耗时</th></tr></thead><tbody
						>
							{#each summary.daily as day}<tr
									><td>{day.day}</td><td>{day.runs}</td><td>{formatUsd(day.cost)}</td><td
										>{formatHours(day.seconds)}</td
									></tr
								>{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>
		{#each [{ title: '按执行器', rows: summary.byRunner }, { title: '按项目', rows: summary.byProject }] as group}
			<section class="overflow-x-auto">
				<h3 class="mb-2 text-sm font-medium">{group.title}</h3>
				<table class="w-full text-left text-sm">
					<thead class="text-xs text-gray-500"
						><tr
							><th class="py-2">名称</th><th>任务数</th><th>折算费用</th><th>耗时</th><th>轮数</th
							><th>失败 / 额度中断</th></tr
						></thead
					>
					<tbody
						>{#each group.rows as row}<tr class="border-t border-gray-100 dark:border-gray-800"
								><td class="py-2">{group.title === '按执行器' ? runnerName(row.key) : row.key}</td
								><td>{row.runs}</td><td>{formatUsd(row.cost)}</td><td>{formatHours(row.seconds)}</td
								><td>{row.turns}</td><td>{row.failed} / {row.quota}</td></tr
							>{/each}</tbody
					>
				</table>
			</section>
		{/each}
		<section class="overflow-x-auto">
			<h3 class="mb-2 text-sm font-medium">每次运行</h3>
			<table class="w-full text-left text-sm" data-halo-runner-rows>
				<thead class="text-xs text-gray-500"
					><tr
						><th class="py-2">任务 / 项目</th><th>执行器</th><th>状态</th><th>折算费用</th><th
							>耗时</th
						><th>轮数</th></tr
					></thead
				>
				<tbody
					>{#each visible as run}<tr class="border-t border-gray-100 dark:border-gray-800">
							<td class="max-w-xs py-3 pr-3"
								><div class="truncate" title={run.title}>{run.title || run.run_id}</div>
								<div class="text-xs text-gray-500">
									{run.project || '（不在项目里）'} · {dateTime(run.started_at)}
								</div></td
							>
							<td>{runnerName(run.agent)}</td><td
								>{labels[run.status] ??
									run.status}{#if ['quota_reset', 'quota', 'official_limit'].includes(run.failure_kind)}
									· 额度中断{/if}</td
							>
							<td>{run.cost_usd === null ? '—' : formatUsd(run.cost_usd)}</td><td
								>{run.duration_s === null ? '—' : formatHours(run.duration_s)}</td
							><td>{run.turns ?? '—'}</td>
						</tr>{/each}</tbody
				>
			</table>
			<div class="mt-3 flex items-center justify-end gap-3 text-xs">
				<button disabled={page === 0} on:click={() => (page -= 1)}>上一页</button><span
					>{page + 1} / {pages}</span
				><button disabled={page + 1 >= pages} on:click={() => (page += 1)}>下一页</button>
			</div>
		</section>
	{/if}
</div>

<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		ListChecks,
		CircleDollarSign,
		Timer,
		Repeat2,
		RefreshCw,
		ChevronLeft,
		ChevronRight
	} from 'lucide-svelte';
	import { getRunnerStats, type RunnerRun, type RunnerQuota } from '$lib/apis/hermes';
	import HaloSelect from '$lib/components/common/HaloSelect.svelte';
	import {
		summarizeRuns,
		formatUsd,
		formatHours,
		formatTokens,
		tokensTitle,
		runnerName,
		isFailed,
		isQuotaStop,
		STATUS_LABEL
	} from '$lib/utils/runner-stats';

	export let days = 30;
	let loadedDays = 0;
	let runs: RunnerRun[] = [];
	let quota: RunnerQuota | undefined;
	let loading = true;
	let error = '';
	const ALL = '__all';
	let runner = ALL;
	let project = ALL;
	let page = 0;
	let showDailyTable = false;
	let hoveredDay: number | null = null;
	let requestId = 0;
	let mounted = false;
	const pageSize = 25;

	// Same surfaces as the 总览 tab, so the two tabs read as one page.
	const card =
		'rounded-2xl border border-gray-100/90 bg-white/70 shadow-sm shadow-gray-900/[0.04] dark:border-gray-800/70 dark:bg-gray-900/60 dark:shadow-black/30';
	const th =
		'whitespace-nowrap px-4 py-2.5 text-2xs font-medium uppercase tracking-wider text-gray-400 dark:text-gray-500';
	const pagerButton =
		'flex items-center gap-1 rounded-lg border border-gray-200/50 px-2.5 py-1.5 text-gray-600 transition-colors hover:bg-gray-50 disabled:pointer-events-none disabled:opacity-40 dark:border-white/[0.06] dark:text-gray-300 dark:hover:bg-white/[0.03]';

	const pad = (n: number) => String(n).padStart(2, '0');
	/** 今天 23:40 / 10-14 22:00 */
	const shortTime = (date: Date) => {
		const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
		return date.toDateString() === new Date().toDateString()
			? `今天 ${time}`
			: `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${time}`;
	};
	const runTime = (ts: number) => shortTime(new Date(ts * 1000));
	const resetTime = (value: string | null) => (value ? shortTime(new Date(value)) : '时间未知');
	const quotaTone = (pct: number) =>
		pct >= 100
			? 'bg-red-500 dark:bg-red-400'
			: pct >= 90
				? 'bg-amber-400 dark:bg-amber-500'
				: 'bg-gray-800 dark:bg-gray-200';

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
		(run) =>
			(runner === ALL || run.agent === runner) && (project === ALL || run.project === project)
	);
	$: summary = summarizeRuns(filtered, loadedDays || Math.min(days, 90));
	$: maxCost = Math.max(...summary.daily.map((day) => day.cost), 0.01);
	$: reportedCost = filtered.filter((run) => run.cost_usd !== null).length;
	$: pages = Math.max(1, Math.ceil(filtered.length / pageSize));
	$: visible = filtered.slice(page * pageSize, (page + 1) * pageSize);
	$: runnerOptions = [
		{ value: ALL, label: '全部执行器' },
		...[...new Set(runs.map((run) => run.agent))]
			.sort()
			.map((key) => ({ value: key, label: runnerName(key) }))
	];
	$: projectOptions = [
		{ value: ALL, label: '全部项目' },
		...[...new Set(runs.map((run) => run.project).filter(Boolean))]
			.sort()
			.map((name) => ({ value: name, label: name }))
	];
	$: cards = [
		{ icon: ListChecks, value: summary.total.runs, label: '任务数' },
		{ icon: CircleDollarSign, value: formatUsd(summary.total.cost), label: 'API 折算费用' },
		{ icon: Timer, value: formatHours(summary.total.seconds), label: '累计耗时' },
		{ icon: Repeat2, value: summary.total.turns, label: '累计轮数' }
	];
	$: groups = [
		{ title: '按执行器', rows: summary.byRunner, name: runnerName },
		{ title: '按项目', rows: summary.byProject, name: (key: string) => key }
	];
	$: hovered = hoveredDay === null ? null : summary.daily[hoveredDay];
</script>

<div class="space-y-5" data-halo-runner-usage>
	<div class="flex flex-wrap items-center gap-2">
		<HaloSelect
			value={runner}
			options={runnerOptions}
			className="h-9"
			on:change={(e) => {
				runner = e.detail.value;
				page = 0;
			}}
		/>
		<HaloSelect
			value={project}
			options={projectOptions}
			className="h-9"
			on:change={(e) => {
				project = e.detail.value;
				page = 0;
			}}
		/>
		<button
			type="button"
			class="halo-icon-btn ml-auto"
			aria-label="刷新"
			title="刷新"
			disabled={loading}
			on:click={() => load()}
		>
			<RefreshCw class="size-4 {loading ? 'animate-spin' : ''}" strokeWidth={2} />
		</button>
	</div>

	{#if quota?.available}
		<section class="{card} p-4" data-halo-runner-quota>
			<div class="flex items-baseline justify-between gap-3">
				<h3 class="text-[13px] font-medium text-gray-500 dark:text-gray-400">官方 Claude 订阅额度</h3>
				<span class="text-2xs tabular-nums text-gray-400 dark:text-gray-500"
					>查询于 {runTime(quota.checked_at)}</span
				>
			</div>
			<div class="mt-3 grid gap-4 sm:grid-cols-2">
				{#each quota.windows as window}
					{@const pct = Math.round(window.utilization)}
					<div role={pct >= 90 ? 'alert' : undefined}>
						<div class="flex items-baseline justify-between text-sm">
							<span class="text-gray-700 dark:text-gray-200">{window.label}</span>
							<span
								class="font-display font-semibold tabular-nums {pct >= 100
									? 'text-red-600 dark:text-red-400'
									: 'text-gray-900 dark:text-gray-100'}">{pct}%</span
							>
						</div>
						<div class="mt-1.5 h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800">
							<div
								class="h-full rounded-full transition-all duration-300 {quotaTone(pct)}"
								style="width: {Math.min(pct, 100)}%"
							></div>
						</div>
						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{resetTime(window.resets_at)} 重置{#if pct >= 100}<span
									class="text-red-600 dark:text-red-400"> · 额度已用完</span
								>{:else if pct >= 90}<span class="text-amber-600 dark:text-amber-400">
									· 额度即将用完</span
								>{/if}
						</div>
					</div>
				{/each}
			</div>
		</section>
	{:else if !loading && !error}
		<p class="text-xs text-gray-400 dark:text-gray-500">
			{quota?.notice || '当前执行器未提供实时订阅额度。'}
		</p>
	{/if}

	{#if loading && runs.length === 0}
		<p class="py-10 text-center text-sm text-gray-400" role="status">正在读取后台任务…</p>
	{:else if error}
		<div
			class="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-300"
			role="alert"
		>
			读取失败：{error}。点右上角刷新重试。
		</div>
	{:else if filtered.length === 0}
		<div class="{card} py-10 text-center text-sm text-gray-400 dark:text-gray-500">
			这段时间没有符合条件的后台任务。
		</div>
	{:else}
		<div class="grid grid-cols-2 gap-3 md:grid-cols-4">
			{#each cards as item}
				<div
					class="{card} min-h-[102px] p-4 transition-all duration-200 hover:border-gray-300/60 dark:hover:border-white/10"
				>
					<div class="glass-icon-badge mb-3 !h-9 !w-9">
						<svelte:component this={item.icon} class="size-[18px]" strokeWidth={1.75} />
					</div>
					<div
						class="font-display text-2xl font-semibold tracking-tight tabular-nums text-gray-900 dark:text-gray-100"
					>
						{item.value}
					</div>
					<div class="mt-0.5 text-[13px] text-gray-400 dark:text-gray-500">{item.label}</div>
				</div>
			{/each}
		</div>
		<p class="text-xs leading-relaxed text-gray-400 dark:text-gray-500">
			最近 {loadedDays} 天 · 完成 {summary.total.ok} · 失败
			<span class={summary.total.failed ? 'text-red-600 dark:text-red-400' : ''}
				>{summary.total.failed}</span
			>
			· 额度中断 {summary.total.quota}。费用是执行器自报的 API 价格折算值，订阅实际账单另计；codex / agy 不报费用，按 token × 中转单价估算，标「≈」{#if summary.total.estimated}（{summary.total.estimated} 次，共 {formatTokens(summary.total.tokens)} token）{/if}；{`${reportedCost}/${filtered.length} 次任务提供了费用`}，缺失值不参与合计。
		</p>

		<section aria-label="每日 API 折算费用">
			<div class="mb-3 flex items-center justify-between">
				<h3 class="text-[13px] font-medium text-gray-500 dark:text-gray-400">每日 API 折算费用</h3>
				<button
					type="button"
					class="text-xs text-gray-400 transition-colors hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-200"
					on:click={() => (showDailyTable = !showDailyTable)}
					>{showDailyTable ? '隐藏每日明细' : '查看每日明细'}</button
				>
			</div>
			<div class="relative">
				<div
					class="{card} relative flex h-36 items-end {summary.daily.length > 45
						? 'gap-px'
						: 'gap-1'} p-3 pb-1"
				>
					<!-- Scale: the tallest bar and half of it, so heights read as dollars. -->
					<div class="pointer-events-none absolute inset-x-3 bottom-1 top-3 z-[1]" aria-hidden="true">
						<div class="absolute inset-x-0 top-0 border-t border-dashed border-gray-200 dark:border-gray-700/80">
							<span
								class="absolute -top-[7px] right-0 bg-white/90 pl-1 text-2xs leading-none tabular-nums text-gray-400 dark:bg-gray-900/90 dark:text-gray-500"
								>{formatUsd(maxCost)}</span
							>
						</div>
						<div class="absolute inset-x-0 top-1/2 border-t border-dashed border-gray-100 dark:border-gray-800">
							<span
								class="absolute -top-[7px] right-0 bg-white/90 pl-1 text-2xs leading-none tabular-nums text-gray-400 dark:bg-gray-900/90 dark:text-gray-500"
								>{formatUsd(maxCost / 2)}</span
							>
						</div>
					</div>
					{#each summary.daily as day, idx}
						<div
							class="relative min-h-[2px] flex-1 cursor-default rounded-t transition-all duration-200 {day.runs
								? 'bg-blue-300 hover:bg-blue-500 dark:bg-blue-500/70 dark:hover:bg-blue-400'
								: 'bg-gray-100 dark:bg-gray-800'}"
							style="height: {(day.cost / maxCost) * 100}%"
							role="img"
							aria-label={`${day.day}：${formatUsd(day.cost)}，${day.runs} 次任务`}
							on:mouseenter={() => (hoveredDay = idx)}
							on:mouseleave={() => (hoveredDay = null)}
						></div>
					{/each}
				</div>
				{#if hovered && hoveredDay !== null}
					<div
						class="pointer-events-none absolute -top-12 z-10 whitespace-nowrap rounded-lg bg-zinc-900 px-3 py-1.5 text-xs text-white shadow-lg dark:bg-zinc-100 dark:text-zinc-900"
						style="left: {((hoveredDay + 0.5) / summary.daily.length) * 100}%; transform: translateX({hoveredDay <
						summary.daily.length * 0.15
							? '-15%'
							: hoveredDay > summary.daily.length * 0.85
								? '-85%'
								: '-50%'})"
					>
						<div class="font-medium">{hovered.day}</div>
						<div class="text-zinc-300 dark:text-zinc-600">
							{formatUsd(hovered.cost)} · {hovered.runs} 次 · {formatHours(hovered.seconds)}
						</div>
					</div>
				{/if}
			</div>
			<div class="mt-1 flex justify-between px-3 text-xs text-gray-400">
				<span>{summary.daily[0]?.day}</span><span>{summary.daily.at(-1)?.day}</span>
			</div>
			{#if showDailyTable}
				<div class="{card} mt-3 max-h-64 overflow-auto">
					<table class="w-full whitespace-nowrap text-sm">
						<thead class="sticky top-0 bg-gray-50/95 dark:bg-gray-850/95">
							<tr>
								<th class="{th} text-left">日期</th>
								<th class="{th} text-right">任务</th>
								<th class="{th} text-right">折算费用</th>
								<th class="{th} text-right">耗时</th>
							</tr>
						</thead>
						<tbody>
							{#each [...summary.daily].reverse() as day}
								<tr class="border-t border-gray-100 tabular-nums dark:border-white/[0.06]">
									<td class="px-4 py-2 text-gray-700 dark:text-gray-300">{day.day}</td>
									<td class="px-4 py-2 text-right">{day.runs}</td>
									<td class="px-4 py-2 text-right">{formatUsd(day.cost)}</td>
									<td class="px-4 py-2 text-right text-gray-500">{formatHours(day.seconds)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<div class="space-y-4">
			{#each groups as group}
				<section class="{card} overflow-hidden">
					<h3
						class="border-b border-gray-100 px-4 py-3 text-[13px] font-medium text-gray-500 dark:border-white/[0.06] dark:text-gray-400"
					>
						{group.title}
					</h3>
					<div class="overflow-x-auto">
						<table class="w-full whitespace-nowrap text-sm">
							<thead class="bg-gray-50/80 dark:bg-gray-850/50">
								<tr>
									<th class="{th} text-left">名称</th>
									<th class="{th} text-right">任务</th>
									<th class="{th} text-right">折算费用</th>
									<th class="{th} text-right">Token</th>
									<th class="{th} text-right">耗时</th>
									<th class="{th} text-right">轮数</th>
									<th class="{th} text-right">失败 / 额度</th>
								</tr>
							</thead>
							<tbody>
								{#each group.rows as row}
									<tr class="border-t border-gray-100 tabular-nums dark:border-white/[0.06]">
										<td class="max-w-[12rem] px-4 py-2.5">
											<div class="truncate font-medium text-gray-800 dark:text-gray-200" title={row.key}>
												{group.name(row.key)}
											</div>
											<!-- share of the filtered cost -->
											<div class="mt-1 h-1 overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800">
												<div
													class="h-full rounded-full bg-gray-800 dark:bg-gray-300"
													style="width: {summary.total.cost ? (row.cost / summary.total.cost) * 100 : 0}%"
												></div>
											</div>
										</td>
										<td class="px-4 py-2.5 text-right">{row.runs}</td>
										<td
											class="px-4 py-2.5 text-right"
											title={row.estimated ? `其中 ${row.estimated} 次按 token 估算` : undefined}
										>
											{row.estimated ? '≈' : ''}{formatUsd(row.cost)}
										</td>
										<td class="px-4 py-2.5 text-right text-gray-500">
											{row.tokens ? formatTokens(row.tokens) : '—'}
										</td>
										<td class="whitespace-nowrap px-4 py-2.5 text-right text-gray-500">
											{formatHours(row.seconds)}
										</td>
										<td class="px-4 py-2.5 text-right text-gray-500">{row.turns}</td>
										<td class="px-4 py-2.5 text-right">
											<span class={row.failed ? 'text-red-600 dark:text-red-400' : 'text-gray-400'}
												>{row.failed}</span
											><span class="text-gray-400"> / {row.quota}</span>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</section>
			{/each}
		</div>

		<section class="{card} overflow-hidden">
			<div
				class="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-white/[0.06]"
			>
				<h3 class="text-[13px] font-medium text-gray-500 dark:text-gray-400">每次运行</h3>
				<span class="workspace-count-pill !py-0.5 !text-xs">{filtered.length}</span>
			</div>
			<div class="overflow-x-auto">
				<table class="w-full text-sm" data-halo-runner-rows>
					<thead class="bg-gray-50/80 dark:bg-gray-850/50">
						<tr>
							<th class="{th} text-left">任务</th>
							<th class="{th} text-left">执行器</th>
							<th class="{th} text-left">状态</th>
							<th class="{th} text-right">折算费用</th>
							<th class="{th} hidden text-right sm:table-cell">耗时</th>
							<th class="{th} hidden text-right sm:table-cell">轮数</th>
						</tr>
					</thead>
					<tbody>
						{#each visible as run (run.agent + run.run_id)}
							<tr
								class="border-t border-gray-100 transition-colors hover:bg-gray-50/60 dark:border-white/[0.06] dark:hover:bg-white/[0.02]"
							>
								<td class="max-w-xs px-4 py-2.5">
									<div class="truncate text-gray-800 dark:text-gray-200" title={run.title}>
										{run.title || run.run_id}
									</div>
									<div class="mt-0.5 truncate text-xs text-gray-400 dark:text-gray-500">
										{run.project || '（不在项目里）'} · {runTime(run.started_at)}
									</div>
								</td>
								<td class="whitespace-nowrap px-4 py-2.5">
									<span class="halo-chip">{runnerName(run.agent)}</span>
								</td>
								<td
									class="whitespace-nowrap px-4 py-2.5 {isFailed(run) || isQuotaStop(run)
										? 'text-red-600 dark:text-red-400'
										: 'text-gray-600 dark:text-gray-300'}"
								>
									{STATUS_LABEL[run.status] ?? run.status}{#if isQuotaStop(run)} · 额度中断{/if}
								</td>
								<td
									class="px-4 py-2.5 text-right tabular-nums"
									title={run.cost_estimated ? tokensTitle(run) : undefined}
									data-halo-runner-cost-estimated={run.cost_estimated ? '' : undefined}
								>
									{run.cost_usd === null
										? '—'
										: `${run.cost_estimated ? '≈' : ''}${formatUsd(run.cost_usd)}`}
								</td>
								<td
									class="hidden whitespace-nowrap px-4 py-2.5 text-right tabular-nums text-gray-500 sm:table-cell"
								>
									{run.duration_s === null ? '—' : formatHours(run.duration_s)}
								</td>
								<td class="hidden px-4 py-2.5 text-right tabular-nums text-gray-500 sm:table-cell">
									{run.turns ?? '—'}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if pages > 1}
				<div
					class="flex items-center justify-end gap-2 border-t border-gray-100 px-4 py-2.5 text-xs dark:border-white/[0.06]"
				>
					<button type="button" class={pagerButton} disabled={page === 0} on:click={() => (page -= 1)}>
						<ChevronLeft class="size-3.5" strokeWidth={2.25} />上一页
					</button>
					<span class="tabular-nums text-gray-500">{page + 1} / {pages}</span>
					<button
						type="button"
						class={pagerButton}
						disabled={page + 1 >= pages}
						on:click={() => (page += 1)}
					>
						下一页<ChevronRight class="size-3.5" strokeWidth={2.25} />
					</button>
				</div>
			{/if}
		</section>
	{/if}
</div>

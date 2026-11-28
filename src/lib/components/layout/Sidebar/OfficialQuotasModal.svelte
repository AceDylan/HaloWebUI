<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';

	import { mobile, showSidebar, user } from '$lib/stores';
	import {
		getOfficialQuotas,
		HermesSessionExpiredError,
		type RunnerQuota
	} from '$lib/apis/hermes';
	import {
		computeWindowMetrics,
		formatQuotaShortTime,
		formatResetCountdown,
		getQuotaMeta,
		getVisibleQuotaWindows,
		orderOfficialQuotas,
		type QuotaThemeKey,
		type QuotaWindowLevel
	} from '$lib/utils/runner-quotas';
	import Modal from '$lib/components/common/Modal.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	export let show = false;

	let opened = false;
	let requestSeq = 0;
	let loading = false;
	let hasLoadedOnce = false;
	let quotas: RunnerQuota[] = [];
	let fetchedAt: number | null = null;
	let error = '';

	const SKELETON_THEMES: QuotaThemeKey[] = ['amber', 'cyan', 'emerald'];

	const formatError = (err: unknown): string => {
		if (err instanceof HermesSessionExpiredError) {
			return '登录状态已失效或缺少管理员权限，请重新登录后重试';
		}
		if (err instanceof Error && err.message) {
			return err.message;
		}
		return typeof err === 'string' && err.trim() ? err.trim() : '获取官方额度失败，请稍后重试';
	};

	const load = async () => {
		if ($user?.role !== 'admin') return;
		const seq = ++requestSeq;
		loading = true;
		error = '';
		try {
			const token = typeof localStorage !== 'undefined' ? (localStorage.token ?? '') : '';
			const data = await getOfficialQuotas(token);
			if (seq !== requestSeq) return;
			quotas = data.quotas;
			fetchedAt = data.fetched_at;
			hasLoadedOnce = true;
		} catch (err) {
			if (seq !== requestSeq) return;
			error = formatError(err);
		} finally {
			if (seq === requestSeq) {
				loading = false;
			}
		}
	};

	$: if (show && !opened) {
		opened = true;
		if ($user?.role === 'admin') {
			void load();
		}
	}
	$: if (!show && opened) {
		opened = false;
		requestSeq += 1;
		loading = false;
	}

	onDestroy(() => {
		requestSeq += 1;
	});

	$: orderedQuotas = orderOfficialQuotas(quotas);

	$: subtitleText =
		loading && !hasLoadedOnce
			? '正在同步最新额度…'
			: loading
				? '正在刷新…'
				: error
					? '同步失败'
					: fetchedAt
						? `查询于 ${formatQuotaShortTime(fetchedAt, { withSeconds: true })}`
						: '点击刷新获取三账号实时额度';

	const dotColor = (theme: QuotaThemeKey) => {
		if (theme === 'amber') return 'bg-amber-500 ring-amber-500/20';
		if (theme === 'cyan') return 'bg-cyan-500 ring-cyan-500/20';
		if (theme === 'emerald') return 'bg-emerald-500 ring-emerald-500/20';
		return 'bg-gray-400 ring-gray-400/20';
	};

	const barFillClass = (level: QuotaWindowLevel, theme: QuotaThemeKey) => {
		if (level === 'empty') {
			return 'bg-gradient-to-r from-red-500 to-rose-400 dark:from-red-500 dark:to-rose-400';
		}
		if (level === 'low') {
			return 'bg-gradient-to-r from-orange-500 to-amber-400 dark:from-orange-400 dark:to-amber-400';
		}
		if (level === 'caution') {
			return 'bg-gradient-to-r from-amber-500 to-yellow-400 dark:from-amber-400 dark:to-yellow-300';
		}
		if (theme === 'amber') {
			return 'bg-gradient-to-r from-amber-500 to-orange-400 dark:from-amber-400 dark:to-orange-300';
		}
		if (theme === 'cyan') {
			return 'bg-gradient-to-r from-cyan-500 to-sky-400 dark:from-cyan-400 dark:to-sky-300';
		}
		if (theme === 'emerald') {
			return 'bg-gradient-to-r from-emerald-500 to-teal-400 dark:from-emerald-400 dark:to-teal-300';
		}
		return 'bg-gradient-to-r from-blue-500 to-cyan-400 dark:from-blue-400 dark:to-cyan-300';
	};

	const percentTextClass = (level: QuotaWindowLevel, theme: QuotaThemeKey) => {
		if (level === 'empty') return 'text-red-600 dark:text-red-400';
		if (level === 'low') return 'text-orange-600 dark:text-orange-400';
		if (level === 'caution') return 'text-amber-600 dark:text-amber-400';
		if (theme === 'amber') return 'text-amber-700 dark:text-amber-300';
		if (theme === 'cyan') return 'text-cyan-700 dark:text-cyan-300';
		if (theme === 'emerald') return 'text-emerald-700 dark:text-emerald-300';
		return 'text-gray-900 dark:text-gray-100';
	};

	const openAnalytics = async () => {
		show = false;
		if ($mobile) {
			showSidebar.set(false);
		}
		await goto('/settings/analytics');
	};
</script>

<Modal
	size="sm"
	bind:show
	className="bg-[var(--surface-overlay)] rounded-2xl overflow-hidden"
>
	<div class="flex flex-col text-gray-900 dark:text-gray-100" data-halo-official-quotas-modal>
		<!-- Header -->
		<div
			class="halo-quota-header flex items-center justify-between gap-3 border-b border-gray-100 px-4 py-3.5 dark:border-white/[0.07]"
		>
			<div class="flex min-w-0 items-center gap-3">
				<div
					class="halo-quota-badge flex size-9 shrink-0 items-center justify-center rounded-xl"
					aria-hidden="true"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						class="size-[19px]"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M4.75 16.25a8.25 8.25 0 1 1 14.5 0"
						/>
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 13.5 15.75 9.25" />
						<circle cx="12" cy="13.5" r="1.25" fill="currentColor" stroke="none" />
					</svg>
				</div>
				<div class="min-w-0">
					<h2 class="font-display truncate text-[15px] font-semibold leading-snug tracking-tight">
						官方订阅额度
					</h2>
					<div
						class="mt-0.5 flex items-center gap-1.5 text-xs tabular-nums text-gray-500 dark:text-gray-400"
						aria-live="polite"
					>
						<span
							class="size-1.5 shrink-0 rounded-full {loading
								? 'bg-cyan-500 animate-pulse'
								: error
									? 'bg-red-500'
									: hasLoadedOnce
										? 'bg-emerald-500'
										: 'bg-gray-300 dark:bg-gray-600'}"
							aria-hidden="true"
						></span>
						<span class="truncate">{subtitleText}</span>
					</div>
				</div>
			</div>

			<div class="flex shrink-0 items-center gap-1">
				<button
					type="button"
					class="inline-flex size-8 items-center justify-center rounded-xl text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 disabled:pointer-events-none disabled:opacity-50 dark:text-gray-400 dark:hover:bg-white/[0.06] dark:hover:text-gray-100"
					aria-label="刷新额度"
					title="刷新额度"
					disabled={loading}
					data-halo-official-quotas-refresh
					on:click={() => void load()}
				>
					<ArrowPath className="size-4 {loading ? 'animate-spin' : ''}" strokeWidth="1.9" />
				</button>
				<button
					type="button"
					class="inline-flex size-8 items-center justify-center rounded-xl text-gray-400 transition hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-white/[0.06] dark:hover:text-gray-200"
					aria-label="关闭"
					title="关闭"
					on:click={() => {
						show = false;
					}}
				>
					<XMark className="size-4" strokeWidth="2" />
				</button>
			</div>
		</div>

		<!-- Body -->
		<div class="max-h-[70vh] space-y-2.5 overflow-y-auto px-4 py-3.5 scrollbar-hidden">
			{#if error && hasLoadedOnce}
				<div
					class="flex items-center justify-between gap-2.5 rounded-xl border border-red-200/80 bg-red-50/80 px-3 py-2 text-xs text-red-700 dark:border-red-500/25 dark:bg-red-950/35 dark:text-red-300"
					role="alert"
				>
					<span class="min-w-0 flex-1 leading-relaxed">{error}</span>
					<button
						type="button"
						class="shrink-0 rounded-lg bg-red-600/10 px-2.5 py-1 font-medium text-red-700 transition hover:bg-red-600/20 disabled:opacity-50 dark:bg-red-400/15 dark:text-red-200 dark:hover:bg-red-400/25"
						disabled={loading}
						on:click={() => void load()}
					>
						重试
					</button>
				</div>
			{/if}

			{#if loading && !hasLoadedOnce}
				<div class="space-y-2.5" data-halo-official-quotas-skeleton role="status" aria-label="正在加载官方订阅额度">
					{#each SKELETON_THEMES as skelTheme}
						<div class="halo-quota-card halo-quota-card--{skelTheme} p-3.5">
							<div class="flex items-center justify-between gap-2">
								<div class="flex items-center gap-2">
									<div class="halo-quota-skeleton-bar size-2 rounded-full"></div>
									<div class="halo-quota-skeleton-bar h-3.5 w-24 rounded-md"></div>
									<div class="halo-quota-skeleton-bar h-3 w-14 rounded-md opacity-70"></div>
								</div>
								<div class="halo-quota-skeleton-bar h-3 w-20 rounded-md opacity-70"></div>
							</div>
							<div class="mt-3 space-y-2.5">
								{#each [0, 1] as _row}
									<div class="space-y-1.5">
										<div class="flex items-center justify-between">
											<div class="halo-quota-skeleton-bar h-3 w-20 rounded"></div>
											<div class="halo-quota-skeleton-bar h-3.5 w-14 rounded"></div>
										</div>
										<div class="halo-quota-bar-track h-2 w-full overflow-hidden rounded-full">
											<div class="halo-quota-skeleton-bar h-full w-2/3 rounded-full"></div>
										</div>
										<div class="flex items-center justify-between">
											<div class="halo-quota-skeleton-bar h-2.5 w-28 rounded opacity-70"></div>
											<div class="halo-quota-skeleton-bar h-2.5 w-12 rounded opacity-70"></div>
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/each}
					<p class="pt-0.5 text-center text-[11px] text-gray-400 dark:text-gray-500">
						正在并行查询 3 个官方账号，offiagy 可能需要 10–15 秒…
					</p>
				</div>
			{:else if error && !hasLoadedOnce}
				<div
					class="flex flex-col items-center justify-center gap-3 rounded-2xl border border-red-200/70 bg-red-50/50 px-5 py-7 text-center dark:border-red-500/20 dark:bg-red-950/20"
					role="alert"
				>
					<div
						class="flex size-10 items-center justify-center rounded-full bg-red-500/10 text-red-600 dark:bg-red-400/15 dark:text-red-400"
						aria-hidden="true"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.8"
							class="size-5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M12 9v3.75m0 3.75h.008v.008H12v-.008ZM21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
							/>
						</svg>
					</div>
					<div class="space-y-1">
						<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
							暂时无法读取官方额度
						</div>
						<p class="text-xs leading-relaxed text-gray-600 dark:text-gray-400">{error}</p>
					</div>
					<button
						type="button"
						class="inline-flex items-center gap-1.5 rounded-xl bg-gray-900 px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-gray-800 disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
						disabled={loading}
						on:click={() => void load()}
					>
						<ArrowPath className="size-3.5" strokeWidth="2" />
						<span>重试</span>
					</button>
				</div>
			{:else if orderedQuotas.length === 0}
				<div
					class="flex flex-col items-center justify-center gap-2.5 rounded-2xl border border-dashed border-gray-200/90 px-5 py-8 text-center dark:border-white/[0.08]"
				>
					<div class="text-sm font-medium text-gray-700 dark:text-gray-200">
						暂无可展示的官方订阅额度
					</div>
					<p class="text-xs text-gray-500 dark:text-gray-400">
						请确认宿主机 Hermes 已登录官方账号并启用额度探测。
					</p>
					<button
						type="button"
						class="mt-1 inline-flex items-center gap-1.5 rounded-xl border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 dark:border-white/10 dark:text-gray-200 dark:hover:bg-white/[0.05]"
						disabled={loading}
						on:click={() => void load()}
					>
						<ArrowPath className="size-3.5" strokeWidth="2" />
						<span>重新查询</span>
					</button>
				</div>
			{:else}
				{#each orderedQuotas as quota, qIdx (`${getQuotaMeta(quota).runner}-${qIdx}`)}
					{@const meta = getQuotaMeta(quota)}
					{@const windows = getVisibleQuotaWindows(quota)}
					{@const isAvailable = quota.available && windows.length > 0}
					<section
						class="halo-quota-card halo-quota-card--{meta.theme} p-3.5"
						data-halo-official-quota-card={meta.runner}
					>
						<!-- Card header -->
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0">
								<div class="flex flex-wrap items-center gap-1.5">
									<span
										class="size-2 shrink-0 rounded-full ring-2 {dotColor(meta.theme)}"
										aria-hidden="true"
									></span>
									<h3 class="font-display text-sm font-semibold leading-tight text-gray-900 dark:text-gray-50">
										{meta.title}
									</h3>
									{#if quota.plan}
										<span
											class="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-emerald-700 dark:border-emerald-400/25 dark:bg-emerald-400/15 dark:text-emerald-300"
										>
											{quota.plan}
										</span>
									{/if}
									{#if quota.banked_resets && quota.banked_resets > 0}
										<span
											class="rounded-full bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium leading-none tabular-nums text-cyan-700 dark:bg-cyan-400/15 dark:text-cyan-300"
											data-halo-quota-banked-resets
										>
											备用重置 {quota.banked_resets} 次
										</span>
									{/if}
								</div>
								<div class="mt-0.5 pl-3.5 font-mono text-[11px] text-gray-400 dark:text-gray-500">
									{meta.subtitle}
								</div>
							</div>

							<span
								class="shrink-0 pt-0.5 text-[11px] tabular-nums text-gray-400 dark:text-gray-500"
							>
								查询于 {formatQuotaShortTime(quota.checked_at, { withSeconds: true })}
							</span>
						</div>

						<!-- Windows or unavailable fallback -->
						{#if isAvailable}
							<div class="mt-3 space-y-2.5">
								{#each windows as window, wIdx (`${window.key}-${wIdx}`)}
									{@const metrics = computeWindowMetrics(window.utilization)}
									{@const countdown = formatResetCountdown(window.resets_at)}
									{@const isAlert = metrics.level === 'low' || metrics.level === 'empty'}
									<div
										role={isAlert ? 'alert' : undefined}
										class="rounded-xl px-2.5 py-2 transition-colors {metrics.level === 'empty'
											? 'bg-red-500/[0.06] ring-1 ring-inset ring-red-500/20 dark:bg-red-500/[0.09] dark:ring-red-400/25'
											: metrics.level === 'low'
												? 'bg-orange-500/[0.06] ring-1 ring-inset ring-orange-500/20 dark:bg-orange-400/[0.08] dark:ring-orange-400/25'
												: 'bg-gray-50/75 dark:bg-white/[0.025]'}"
										data-halo-quota-window={window.key}
									>
										<div class="flex items-baseline justify-between gap-2">
											<div class="flex min-w-0 items-center gap-1.5">
												<span class="truncate text-[13px] font-medium text-gray-700 dark:text-gray-200">
													{window.label}
												</span>
												{#if metrics.level === 'empty'}
													<span
														class="shrink-0 rounded-full bg-red-500/15 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-red-700 dark:bg-red-400/20 dark:text-red-300"
													>
														已用完
													</span>
												{:else if metrics.level === 'low'}
													<span
														class="shrink-0 rounded-full bg-orange-500/15 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-orange-700 dark:bg-orange-400/20 dark:text-orange-300"
													>
														额度紧张
													</span>
												{/if}
											</div>
											<span
												class="font-display shrink-0 text-[13px] font-semibold tabular-nums {percentTextClass(
													metrics.level,
													meta.theme
												)}"
											>
												剩余 {metrics.remainingPct}%
											</span>
										</div>

										<div class="halo-quota-bar-track mt-1.5 h-2 w-full overflow-hidden rounded-full">
											<div
												class="h-full rounded-full transition-[width] duration-300 ease-out {barFillClass(
													metrics.level,
													meta.theme
												)}"
												style="width: {metrics.remainingPct}%; {metrics.remainingPct > 0 &&
												metrics.remainingPct < 4
													? 'min-width: 4px;'
													: ''}"
											></div>
										</div>

										<div
											class="mt-1.5 flex items-center justify-between gap-2 text-[11px] tabular-nums text-gray-400 dark:text-gray-500"
										>
											<span class="truncate">
												{#if window.resets_at}
													重置：{formatQuotaShortTime(window.resets_at)}{#if countdown}（{countdown}）{/if}
												{:else}
													重置时间未知
												{/if}
											</span>
											<span class="shrink-0">已用 {metrics.usedPct}%</span>
										</div>
									</div>
								{/each}
							</div>
						{:else}
							<div
								class="mt-2.5 flex items-center gap-2 rounded-xl border border-dashed border-gray-200/90 bg-gray-50/50 px-3 py-2.5 text-xs text-gray-500 dark:border-white/[0.08] dark:bg-white/[0.02] dark:text-gray-400"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="none"
									stroke="currentColor"
									stroke-width="1.7"
									class="size-4 shrink-0 text-gray-400 dark:text-gray-500"
									aria-hidden="true"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M10 6.5v4m0 3h.01M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z"
									/>
								</svg>
								<span class="leading-relaxed">
									{quota.notice || '暂时无法获取该账号的实时额度'}
								</span>
							</div>
						{/if}
					</section>
				{/each}
			{/if}
		</div>

		<!-- Footer -->
		<div
			class="flex items-center justify-between gap-3 border-t border-gray-100 bg-gray-50/60 px-4 py-2.5 dark:border-white/[0.07] dark:bg-white/[0.02]"
		>
			<div class="min-w-0 text-[11px] leading-snug text-gray-400 dark:text-gray-500">
				<div>只读查询 · 不消耗额度</div>
				<div class="truncate text-[10px] opacity-85">1 分钟内重复刷新会返回同一份结果</div>
			</div>
			<button
				type="button"
				class="shrink-0 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-blue-600 transition hover:bg-blue-500/10 dark:text-blue-400 dark:hover:bg-blue-400/15"
				data-halo-official-quotas-analytics-link
				on:click={() => void openAnalytics()}
			>
				<span>用量统计</span>
				<span aria-hidden="true">→</span>
			</button>
		</div>
	</div>
</Modal>

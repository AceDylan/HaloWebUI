<script lang="ts">
	/** How far the team is: one segmented bar (done / running / needs attention / waiting) and the
	 *  numbers behind it, plus the facts that explain the run (fallbacks, lead model, workspace). */
	export let counts: {
		done: number;
		running: number;
		waiting: number;
		attention: number;
		total: number;
	};
	export let fallbacks = 0;
	export let leadModel = '';
	export let workspace = '';

	$: total = Math.max(1, counts.total);
	$: segments = [
		{ key: 'done', n: counts.done, cls: 'bg-emerald-500', label: '完成' },
		{ key: 'running', n: counts.running, cls: 'bg-sky-500 team-progress-live', label: '执行中' },
		{ key: 'attention', n: counts.attention, cls: 'bg-red-500', label: '需处理' },
		{ key: 'waiting', n: counts.waiting, cls: 'bg-gray-200 dark:bg-gray-700', label: '等待' }
	];
	$: percent = Math.round((counts.done / total) * 100);
</script>

<section class="flex flex-col gap-2" aria-label="进度" data-team-progress>
	<div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
		<div class="flex items-baseline gap-1.5">
			<span
				class="text-xl font-semibold tabular-nums tracking-tight text-gray-900 dark:text-gray-100"
				>{counts.done}</span
			>
			<span class="text-sm tabular-nums text-gray-400">/ {counts.total}</span>
			<span class="text-xs text-gray-500">个任务完成</span>
		</div>
		<ul class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
			{#each segments.slice(1) as s}
				{#if s.n}
					<li class="flex items-center gap-1.5">
						<span class="size-1.5 rounded-full {s.cls.split(' ')[0]}" aria-hidden="true" />{s.label}
						<b class="font-semibold tabular-nums text-gray-800 dark:text-gray-200">{s.n}</b>
					</li>
				{/if}
			{/each}
			{#if fallbacks}
				<li
					class="text-amber-700 dark:text-amber-300"
					title="有任务因为默认执行来源不可用而改由下一个执行"
				>
					兜底改派 <b class="tabular-nums">{fallbacks}</b>
				</li>
			{/if}
		</ul>
		<div class="ml-auto hidden min-w-0 items-center gap-3 text-xs text-gray-400 md:flex">
			{#if leadModel}<span
					>负责人 <span class="font-mono text-gray-600 dark:text-gray-300">{leadModel}</span></span
				>{/if}
			{#if workspace}<span class="min-w-0 truncate font-mono" title={workspace}>{workspace}</span
				>{/if}
		</div>
	</div>
	<div
		class="flex h-1.5 w-full gap-[2px] overflow-hidden rounded-full"
		role="progressbar"
		aria-valuemin="0"
		aria-valuemax={counts.total}
		aria-valuenow={counts.done}
		aria-valuetext="{percent}%"
	>
		{#each segments as s (s.key)}
			{#if s.n}
				<div
					class="h-full first:rounded-l-full last:rounded-r-full transition-[flex-grow] duration-700 ease-out {s.cls}"
					style="flex-grow:{s.n}"
				/>
			{/if}
		{/each}
	</div>
</section>

<style>
	:global(.team-progress-live) {
		background-image: linear-gradient(
			90deg,
			transparent 0%,
			rgb(255 255 255 / 0.45) 50%,
			transparent 100%
		);
		background-size: 200% 100%;
		animation: team-progress-sheen 1.8s linear infinite;
	}
	@keyframes team-progress-sheen {
		from {
			background-position: 200% 0;
		}
		to {
			background-position: -200% 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		:global(.team-progress-live) {
			animation: none;
		}
	}
</style>

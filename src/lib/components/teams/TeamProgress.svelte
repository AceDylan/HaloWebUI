<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { elapsed, now } from './clock';

	/** How far the team is: a ring and one segmented bar (done / running / needs attention /
	 *  waiting) with the numbers behind it, and the facts that explain the run — how long it has
	 *  been going, fallbacks, the lead's model, the workspace. */
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
	/** When the team started (approved) and finished; the clock runs while not finished. */
	export let startedAt: number | null = null;
	export let finishedAt: number | null = null;

	$: total = Math.max(1, counts.total);
	$: segments = [
		{ key: 'done', n: counts.done, cls: 'bg-emerald-500', label: '完成' },
		{ key: 'running', n: counts.running, cls: 'bg-sky-500 team-progress-live', label: '执行中' },
		{ key: 'attention', n: counts.attention, cls: 'bg-red-500', label: '需处理' },
		{ key: 'waiting', n: counts.waiting, cls: 'bg-gray-900/10 dark:bg-white/10', label: '等待' }
	];
	$: percent = Math.round((counts.done / total) * 100);
	$: complete = counts.total > 0 && counts.done === counts.total;
	$: shortWorkspace = workspace.split('/').filter(Boolean).slice(-2).join('/');
	$: took = startedAt ? (finishedAt ?? $now) - startedAt : null;
	const R = 15;
	const C = 2 * Math.PI * R;

	const copy = async () => {
		try {
			await navigator.clipboard.writeText(workspace);
			toast.success('已复制工作目录');
		} catch {
			toast.error('复制失败');
		}
	};
</script>

<section class="flex flex-col gap-2.5" aria-label="进度" data-team-progress>
	<div class="flex flex-wrap items-center gap-x-5 gap-y-2">
		<div class="flex items-center gap-3">
			<svg class="size-10 -rotate-90" viewBox="0 0 36 36" aria-hidden="true">
				<circle
					cx="18"
					cy="18"
					r={R}
					fill="none"
					class="stroke-gray-900/[0.07] dark:stroke-white/10"
					stroke-width="3"
				/>
				<circle
					cx="18"
					cy="18"
					r={R}
					fill="none"
					stroke-width="3"
					stroke-linecap="round"
					class="ring-arc {complete ? 'stroke-emerald-500' : 'stroke-sky-500'}"
					stroke-dasharray="{(C * percent) / 100} {C}"
				/>
			</svg>
			<div class="flex flex-col leading-tight">
				<div class="flex items-baseline gap-1">
					<span class="tm-num text-2xl font-semibold text-gray-900 dark:text-gray-50"
						>{counts.done}</span
					>
					<span class="tm-num text-sm text-gray-400">/ {counts.total}</span>
				</div>
				<span class="text-[11px] text-gray-500 dark:text-gray-400">个任务完成 · {percent}%</span>
			</div>
		</div>
		<ul
			class="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-gray-500 dark:text-gray-400"
		>
			{#each segments.slice(1) as s}
				{#if s.n}
					<li class="flex items-center gap-1.5">
						<span class="size-1.5 rounded-full {s.cls.split(' ')[0]}" aria-hidden="true" />{s.label}
						<b class="tm-num font-semibold text-gray-800 dark:text-gray-200">{s.n}</b>
					</li>
				{/if}
			{/each}
			{#if took !== null}
				<li class="flex items-center gap-1.5" title={finishedAt ? '总用时' : '已运行'}>
					<svg class="size-3.5 opacity-70" viewBox="0 0 16 16" fill="none" aria-hidden="true"
						><circle cx="8" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.4" /><path
							d="M8 5.5v3l2 1.3M6.5 1.8h3"
							stroke="currentColor"
							stroke-width="1.4"
							stroke-linecap="round"
						/></svg
					>
					<span class="tm-num text-gray-800 dark:text-gray-200" data-team-elapsed
						>{elapsed(took)}</span
					>
				</li>
			{/if}
			{#if fallbacks}
				<li
					class="text-amber-700 dark:text-amber-300"
					title="有任务因为默认执行来源不可用而改由下一个执行"
				>
					兜底改派 <b class="tm-num">{fallbacks}</b>
				</li>
			{/if}
		</ul>
		<div class="ml-auto hidden min-w-0 items-center gap-2 text-xs text-gray-400 md:flex">
			{#if leadModel}
				<span class="meta-pill"
					>负责人 <span class="font-mono text-gray-700 dark:text-gray-200">{leadModel}</span></span
				>
			{/if}
			{#if workspace}
				<button
					type="button"
					class="meta-pill min-w-0 max-w-[22rem] transition hover:text-gray-700 dark:hover:text-gray-200"
					title="复制工作目录：{workspace}"
					on:click={copy}
				>
					<svg class="size-3.5 shrink-0" viewBox="0 0 16 16" fill="none" aria-hidden="true"
						><path
							d="M2 4.5A1.5 1.5 0 0 1 3.5 3h3l1.5 1.5h4.5A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5v-7Z"
							stroke="currentColor"
							stroke-width="1.3"
						/></svg
					>
					<span class="min-w-0 truncate font-mono">{shortWorkspace}</span>
				</button>
			{/if}
		</div>
	</div>
	<div
		class="flex h-1.5 w-full gap-[3px] overflow-hidden rounded-full"
		role="progressbar"
		aria-valuemin="0"
		aria-valuemax={counts.total}
		aria-valuenow={counts.done}
		aria-valuetext="{percent}%"
	>
		{#each segments as s (s.key)}
			{#if s.n}
				<div
					class="h-full rounded-full transition-[flex-grow] duration-700 ease-out {s.cls}"
					style="flex-grow:{s.n}"
				/>
			{/if}
		{/each}
	</div>
</section>

<style>
	.ring-arc {
		transition: stroke-dasharray 0.8s cubic-bezier(0.22, 1, 0.36, 1);
	}
	.meta-pill {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		border-radius: 9999px;
		padding: 0.2rem 0.6rem;
		border: 1px solid hsl(var(--tm-line));
		background: hsl(var(--tm-surface) / 0.6);
	}
	:global(.team-progress-live) {
		background-image: linear-gradient(
			90deg,
			transparent 0%,
			rgb(255 255 255 / 0.5) 50%,
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

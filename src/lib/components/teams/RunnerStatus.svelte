<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { slide } from 'svelte/transition';

	import type { RunnerInfo, TeamsMeta } from '$lib/apis/teams';
	import { formatStamp, runnerLabel } from './model';

	/**
	 * The execution sources and whether each one can take work right now. A runner that is down
	 * says at which layer (installed → executable → account / quota → network → recent run) and
	 * why; the chain order is the fallback order.
	 */
	export let registry: TeamsMeta['registry'] | null = null;
	export let checking = false;
	export let error = '';

	const dispatch = createEventDispatcher<{ check: void }>();
	let open: string | null = null;

	const LAYER_LABEL: Record<string, string> = {
		configured: '已配置',
		manual: '手动标记',
		installed: '已安装',
		executable: '可执行',
		account: '账号 / 额度',
		reachable: '网络可达',
		recent: '最近运行'
	};

	$: runners = registry?.runners ?? [];
	$: order = registry?.order ?? [];
	$: checkedAt = Math.max(0, ...runners.map((r) => r.checked_at || 0));
	$: down = runners.filter((r) => !r.available).length;

	const dot = (r: RunnerInfo) =>
		r.available
			? 'bg-emerald-500'
			: r.state === 'not_configured'
				? 'bg-gray-300 dark:bg-gray-600'
				: 'bg-red-500';
</script>

<section
	class="rounded-2xl border border-gray-100 dark:border-gray-850"
	aria-label="执行来源可用性"
	data-runner-status
>
	<header class="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3">
		<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">执行来源</h3>
		<span class="text-xs text-gray-500 dark:text-gray-400">
			{#if !registry && !error}正在检测…{:else if error}检测失败{:else if down === 0}全部可用{:else}{down}
				个暂不可用{/if}
			{#if checkedAt}
				· {formatStamp(checkedAt)} 检测{/if}
		</span>
		<button
			type="button"
			class="ml-auto inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-gray-600 transition hover:bg-gray-100 active:scale-[0.98] disabled:opacity-50 dark:text-gray-300 dark:hover:bg-gray-850"
			disabled={checking}
			on:click={() => dispatch('check')}
		>
			<svg
				class="size-3.5 {checking ? 'animate-spin' : ''}"
				viewBox="0 0 16 16"
				fill="none"
				aria-hidden="true"
				><path
					d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
					stroke-linejoin="round"
				/></svg
			>
			{checking ? '检测中…' : '重新检测'}
		</button>
	</header>
	{#if error}
		<p class="px-4 pt-1 text-xs text-red-600 dark:text-red-400" role="alert">{error}</p>
	{/if}
	<ol class="flex flex-wrap gap-1.5 px-4 pb-3 pt-2.5" aria-label="兜底顺序">
		{#each order.length ? order : runners.map((r) => r.name) as name, index}
			{@const r = runners.find((x) => x.name === name)}
			{#if r}
				<li class="flex items-center gap-1.5">
					<button
						type="button"
						class="group inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400
						{open === r.name
							? 'border-gray-300 bg-gray-50 dark:border-gray-700 dark:bg-gray-850'
							: 'border-gray-100 hover:border-gray-200 dark:border-gray-850 dark:hover:border-gray-700'}"
						aria-expanded={open === r.name}
						title={r.available ? `${runnerLabel(r.name)}：${r.reason}` : r.reason}
						on:click={() => (open = open === r.name ? null : r.name)}
						data-runner-chip={r.name}
						data-available={r.available ? 'true' : 'false'}
					>
						<span class="size-1.5 shrink-0 rounded-full {dot(r)}" aria-hidden="true" />
						<span class="font-mono font-medium text-gray-800 dark:text-gray-100"
							>{runnerLabel(r.name)}</span
						>
						<span class="hidden truncate text-gray-400 sm:inline">{r.engine}</span>
						<span class="sr-only">{r.available ? '可用' : `不可用：${r.reason}`}</span>
					</button>
					{#if index < (order.length || runners.length) - 1}
						<span class="text-[10px] text-gray-300 dark:text-gray-700" aria-hidden="true">›</span>
					{/if}
				</li>
			{/if}
		{/each}
	</ol>
	{#if open}
		{@const r = runners.find((x) => x.name === open)}
		{#if r}
			<div
				class="border-t border-gray-100 px-4 py-3 text-xs dark:border-gray-850"
				transition:slide={{ duration: 160 }}
			>
				<div class="flex flex-wrap items-baseline gap-x-2">
					<span class="font-semibold text-gray-900 dark:text-gray-100">{runnerLabel(r.name)}</span>
					<span class="text-gray-500">{r.note}</span>
				</div>
				<div
					class="mt-1 {r.available
						? 'text-emerald-700 dark:text-emerald-300'
						: 'text-red-700 dark:text-red-300'}"
				>
					{r.available ? '可用' : '不可用'}：{r.reason}{r.resume_at
						? `（约 ${r.resume_at} 恢复）`
						: ''}
				</div>
				{#if r.layers?.length}
					<ol class="mt-2 grid gap-1 sm:grid-cols-2">
						{#each r.layers as layer}
							<li class="flex min-w-0 items-start gap-1.5">
								<span
									class="mt-[3px] size-1.5 shrink-0 rounded-full {layer.ok
										? 'bg-emerald-500'
										: 'bg-red-500'}"
									aria-hidden="true"
								/>
								<span class="shrink-0 text-gray-600 dark:text-gray-300"
									>{LAYER_LABEL[layer.layer] ?? layer.layer}</span
								>
								{#if layer.detail}<span class="min-w-0 break-words text-gray-400"
										>{layer.detail}</span
									>{/if}
							</li>
						{/each}
					</ol>
				{/if}
			</div>
		{/if}
	{/if}
</section>

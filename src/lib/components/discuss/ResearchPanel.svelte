<script lang="ts">
	import { slide } from 'svelte/transition';

	import type { DiscussResearch } from '$lib/apis/discussions';
	import { now } from '$lib/components/teams/clock';
	import { domainOf } from './model';

	/** The web notes every seat reads before round 1: looking up, then the numbered sources. */
	export let research: DiscussResearch;

	let open = false;

	$: running = research.status === 'running' || research.status === 'waiting';
	$: waited = research.startedAt ? Math.max(0, Math.floor($now - research.startedAt / 1000)) : 0;
</script>

<div class="dc-research flex flex-col gap-2" data-discuss-research={research.status}>
	{#if running}
		<div class="flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
			<span class="size-3 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />
			<span>正在联网查资料{waited ? `… ${waited} 秒` : '…'}</span>
			{#each research.queries ?? [] as q}
				<span class="dc-chip !py-0.5">{q}</span>
			{/each}
			<span class="text-gray-400 dark:text-gray-500">查到的资料会同时给每位参与者</span>
		</div>
	{:else if research.status === 'done'}
		<div class="flex flex-wrap items-center gap-1.5">
			<button
				type="button"
				class="dc-chip !text-gray-700 dark:!text-gray-200"
				aria-expanded={open}
				on:click={() => (open = !open)}
				data-discuss-research-toggle
			>
				<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
					><circle cx="8" cy="8" r="6.2" stroke="currentColor" stroke-width="1.3" /><path
						d="M1.8 8h12.4M8 1.8c1.8 2 1.8 10.4 0 12.4M8 1.8c-1.8 2-1.8 10.4 0 12.4"
						stroke="currentColor"
						stroke-width="1.1"
					/></svg
				>
				资料 · {research.sources.length} 个来源
				<svg class="size-3 transition-transform {open ? 'rotate-180' : ''}" viewBox="0 0 12 12" fill="none" aria-hidden="true"
					><path d="m3 4.5 3 3 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg
				>
			</button>
			{#each research.sources as source (source.n)}
				<a
					href={source.url}
					target="_blank"
					rel="noopener noreferrer"
					class="dc-chip max-w-[12rem] truncate"
					title={source.title}
					><span class="tm-num text-gray-400">[{source.n}]</span> {domainOf(source.url)}</a
				>
			{/each}
		</div>
		{#if open}
			<ol class="flex flex-col gap-2 rounded-xl bg-gray-500/5 p-3" transition:slide={{ duration: 180 }} data-discuss-sources>
				{#each research.sources as source (source.n)}
					<li class="min-w-0 text-xs leading-relaxed">
						<a href={source.url} target="_blank" rel="noopener noreferrer" class="font-medium text-gray-800 hover:underline dark:text-gray-100"
							><span class="tm-num mr-1 text-gray-400">[{source.n}]</span>{source.title}</a
						>
						<span class="ml-1 text-gray-400">{domainOf(source.url)}</span>
						<p class="mt-0.5 line-clamp-2 text-gray-500 dark:text-gray-400">{source.excerpt}</p>
					</li>
				{/each}
			</ol>
		{/if}
	{:else}
		<p class="text-xs text-gray-400 dark:text-gray-500">
			{research.status === 'empty'
				? '联网没有找到可用的资料，讨论照常进行。'
				: research.status === 'stopped'
					? '查资料被停止。'
					: `联网查资料失败：${research.error || '未知原因'}。讨论照常进行。`}
		</p>
	{/if}
</div>

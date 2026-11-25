<script lang="ts">
	import { slide } from 'svelte/transition';

	import type { LocalInspect } from '$lib/apis/discussions';
	import { now } from '$lib/components/teams/clock';

	/** Read-only local evidence gathered via Hermes before 精答 / 讨论台 answers. */
	export let inspect: LocalInspect | null | undefined = null;

	let open = false;

	const kindLabel = (kind?: string) => (kind === 'command' ? '只读命令' : kind === 'search' ? '检索' : '文件');

	$: running = inspect?.status === 'running' || inspect?.status === 'waiting';
	$: waited = inspect?.startedAt ? Math.max(0, Math.floor($now - inspect.startedAt / 1000)) : 0;
	$: sources = inspect?.sources ?? [];
</script>

{#if inspect}
	<div class="dc-research flex flex-col gap-2" data-local-inspect={inspect.status}>
		{#if running}
			<div class="flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
				<span class="size-3 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />
				<span>正在本机只读取证{waited ? `… ${waited} 秒` : '…'}</span>
				<span class="text-gray-400 dark:text-gray-500">自动脱敏后提供给模型，不改文件、不写记忆</span>
			</div>
		{:else if inspect.status === 'done'}
			<div class="flex flex-wrap items-center gap-1.5">
				<button
					type="button"
					class="dc-chip !text-gray-700 dark:!text-gray-200"
					aria-expanded={open}
					on:click={() => (open = !open)}
					data-local-inspect-toggle
				>
					<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
						><rect x="2.2" y="2.8" width="11.6" height="10.4" rx="2" stroke="currentColor" stroke-width="1.3" /><path
							d="m5 6.3 2 1.7-2 1.7M8.5 9.7h2.5"
							stroke="currentColor"
							stroke-width="1.2"
							stroke-linecap="round"
							stroke-linejoin="round"
						/></svg
					>
					本机取证{sources.length ? ` · ${sources.length} 项` : ''}（只读已脱敏）
					<svg class="size-3 transition-transform {open ? 'rotate-180' : ''}" viewBox="0 0 12 12" fill="none" aria-hidden="true"
						><path d="m3 4.5 3 3 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg
					>
				</button>
				{#each sources.slice(0, 6) as source (source.kind + ':' + source.path)}
					<span class="dc-chip max-w-[14rem] truncate" title="{kindLabel(source.kind)}：{source.path}">{source.path}</span>
				{/each}
			</div>
			{#if open}
				<div class="flex flex-col gap-2 rounded-xl bg-gray-500/5 p-3 text-xs leading-relaxed" transition:slide={{ duration: 180 }} data-local-inspect-detail>
					{#if sources.length}
						<ul class="flex flex-wrap gap-1.5">
							{#each sources as source (source.kind + ':' + source.path)}
								<li class="rounded-md bg-gray-500/10 px-2 py-0.5 font-mono text-[11px] text-gray-600 dark:text-gray-300">
									<span class="mr-1 text-gray-400">{kindLabel(source.kind)}</span>{source.path}
								</li>
							{/each}
						</ul>
					{/if}
					{#if inspect.summary}
						<div class="whitespace-pre-wrap text-gray-600 dark:text-gray-300">{inspect.summary}</div>
					{/if}
				</div>
			{/if}
		{:else if inspect.status !== 'skipped'}
			<p class="text-xs text-gray-400 dark:text-gray-500">
				{inspect.status === 'empty'
					? '本机只读取证没有发现补充材料，已照常继续。'
					: inspect.status === 'stopped'
						? '本机只读取证被停止。'
						: `本机只读取证失败：${inspect.error || '未知原因'}。已照常继续。`}
			</p>
		{/if}
	</div>
{/if}

<script lang="ts">
	/**
	 * 提示词增强 in a studio (utils/studio-prep.ts): while it runs, its steps (分析需求 → 联网搜索
	 * or 精答 / 讨论 → 增强提示词) and a way to stop it; once done, what it brought (the key facts,
	 * the sources, the 精答 / 讨论 it asked) and a way back to the words before it.
	 */
	import type { StudioPrepJob, StudioPrepResult } from '$lib/apis/studio-prep';
	import { prepSummary } from '$lib/utils/studio-prep';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';

	/** The job while it runs (or just failed). */
	export let job: StudioPrepJob | null = null;
	/** What the last finished enhancement brought, while its text is in the box. */
	export let result: StudioPrepResult | null = null;
	export let model = '';
	export let onCancel: (() => void) | null = null;
	export let onUndo: (() => void) | null = null;

	$: running = job?.status === 'running';
	$: run = job?.run ?? result?.run ?? null;
</script>

{#if running && job}
	<div class="space-y-2 rounded-xl bg-gray-50 p-3 ring-1 ring-gray-200/70 dark:bg-gray-900/60 dark:ring-white/10" data-studio-prep="running">
		<div class="flex items-center justify-between gap-2">
			<div class="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-gray-800 dark:text-gray-100">
				<Sparkles className="size-3.5 shrink-0" strokeWidth="2" />
				<span class="truncate">正在增强需求{job.model ? `（${job.model}）` : ''}</span>
			</div>
			{#if onCancel}
				<button
					type="button"
					class="h-7 shrink-0 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
					on:click={onCancel}
					data-studio-prep-cancel>取消</button
				>
			{/if}
		</div>
		<ol class="space-y-1">
			{#each job.steps as step (step.key)}
				<li class="flex items-start gap-2 text-xs leading-5" data-studio-prep-step={step.key} data-status={step.status}>
					<span class="mt-0.5 grid size-4 shrink-0 place-items-center">
						{#if step.status === 'running'}
							<Spinner className="size-3.5" />
						{:else if step.status === 'done'}
							<Check className="size-3.5 text-gray-700 dark:text-gray-200" strokeWidth="2.5" />
						{:else}
							<span class="size-1.5 rounded-full {step.status === 'error' ? 'bg-red-500' : 'bg-gray-400'}" />
						{/if}
					</span>
					<span class="min-w-0">
						<span class="font-medium text-gray-700 dark:text-gray-200">{step.label}</span>
						{#if step.detail}
							<span class="text-gray-500 dark:text-gray-400"> · {step.detail}</span>
						{/if}
					</span>
				</li>
			{/each}
		</ol>
		{#if run}
			<a
				href={run.href}
				target="_blank"
				rel="noopener"
				class="inline-flex text-xs text-gray-600 underline decoration-gray-300 underline-offset-2 hover:text-gray-900 dark:text-gray-300 dark:decoration-gray-600 dark:hover:text-white"
				data-studio-prep-run={run.kind}>在新标签页看{run.label}进度 ↗</a
			>
		{/if}
	</div>
{:else if result}
	<details class="group rounded-xl bg-gray-50 px-3 py-2 ring-1 ring-gray-200/70 dark:bg-gray-900/60 dark:ring-white/10" data-studio-prep="done">
		<summary class="flex cursor-pointer select-none list-none items-center justify-between gap-2 text-xs">
			<span class="flex min-w-0 items-center gap-1.5 text-gray-700 dark:text-gray-200">
				<Sparkles className="size-3.5 shrink-0" strokeWidth="2" />
				<span class="truncate">{prepSummary(result, model)}</span>
				{#if result.notes || result.sources.length || run}
					<span class="shrink-0 text-gray-400 group-open:hidden">· 展开依据</span>
				{/if}
			</span>
			{#if onUndo}
				<button
					type="button"
					class="h-7 shrink-0 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
					on:click|preventDefault={onUndo}
					data-studio-prep-undo>撤销增强</button
				>
			{/if}
		</summary>
		{#if result.notes || result.sources.length || run}
			<div class="mt-2 space-y-2 text-xs leading-relaxed text-gray-600 dark:text-gray-300">
				{#if result.notes}
					<p class="whitespace-pre-wrap" data-studio-prep-notes>{result.notes}</p>
				{/if}
				{#if run}
					<a href={run.href} target="_blank" rel="noopener" class="inline-flex underline decoration-gray-300 underline-offset-2 hover:text-gray-900 dark:decoration-gray-600 dark:hover:text-white">打开{run.label}结论 ↗</a>
				{/if}
				{#if result.sources.length}
					<ol class="list-decimal space-y-0.5 pl-4" data-studio-prep-sources>
						{#each result.sources as source (source.url)}
							<li class="truncate"><a href={source.url} target="_blank" rel="noopener noreferrer" class="hover:underline" title={source.url}>{source.title || source.url}</a></li>
						{/each}
					</ol>
				{/if}
			</div>
		{/if}
	</details>
{:else if job?.status === 'error' && job.error}
	<p class="text-xs text-red-600 dark:text-red-400" data-studio-prep="error">{job.error}</p>
{/if}

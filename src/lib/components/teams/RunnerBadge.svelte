<script lang="ts">
	import { runnerLabel } from './model';

	/** Who does the work: "codex", or "cchclaude → anyclaude" when it fell back (with why). */
	export let chosen: string | null | undefined = null;
	export let actual: string | null | undefined;
	export let reason = '';
	export let size: 'xs' | 'sm' = 'xs';

	$: moved = !!chosen && chosen !== actual;
	$: title = moved
		? `默认 ${runnerLabel(chosen)}，实际 ${actual ? runnerLabel(actual) : '没有可用的执行来源'}${reason ? `：${reason}` : ''}`
		: `由 ${runnerLabel(actual)} 执行`;
</script>

<span
	class="inline-flex min-w-0 max-w-full items-center gap-1 rounded-md px-1.5 py-[1px] font-mono leading-5 {size ===
	'xs'
		? 'text-[10.5px]'
		: 'text-xs'} {moved
		? 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200/80 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-800/70'
		: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'}"
	{title}
	data-runner={actual ?? ''}
	data-runner-chosen={chosen ?? ''}
>
	{#if moved}
		<span class="truncate line-through decoration-amber-500/50 opacity-60"
			>{runnerLabel(chosen)}</span
		>
		<svg class="size-3 shrink-0 opacity-70" viewBox="0 0 16 16" fill="none" aria-hidden="true"
			><path
				d="M3 8h9m-3-3 3 3-3 3"
				stroke="currentColor"
				stroke-width="1.6"
				stroke-linecap="round"
				stroke-linejoin="round"
			/></svg
		>
		<span class="sr-only">改为</span>
	{/if}
	<span class="truncate">{actual ? runnerLabel(actual) : '无可用'}</span>
</span>

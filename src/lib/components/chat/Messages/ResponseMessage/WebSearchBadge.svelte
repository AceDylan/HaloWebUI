<script lang="ts">
	import Spinner from '$lib/components/common/Spinner.svelte';

	// 独立的联网状态标记：一眼看出这条回答到底有没有联网、联网结果如何。
	// state 由后端 web_search 状态推导（见 ResponseMessage.svelte computeWebSearchBadge）。
	// 取值：searching | searched | skipped | native_pending | no_results | failed
	export let state = 'skipped';
	export let label = '';

	// 每种状态对应一套配色（浅色/深色都覆盖）。
	const STYLES: Record<string, string> = {
		searching:
			'text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-800/60',
		searched:
			'text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60',
		native_pending:
			'text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800/60',
		no_results:
			'text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800/60',
		failed:
			'text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800/60',
		skipped:
			'text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/50 border-gray-200 dark:border-gray-700/60'
	};

	$: styleClass = STYLES[state] ?? STYLES.skipped;
</script>

<span
	class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium leading-none {styleClass}"
	title={label}
>
	{#if state === 'searching'}
		<Spinner className="size-3" />
	{:else if state === 'searched'}
		<!-- 地球 + 对勾：已联网 -->
		<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5 shrink-0">
			<path
				fill-rule="evenodd"
				d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1ZM2.5 8c0-.32.027-.633.08-.938l.21.21c.2.2.47.312.752.312H4.5a1 1 0 0 1 1 1v.5a1 1 0 0 0 1 1 1 1 0 0 1 1 1v1.36A5.502 5.502 0 0 1 2.5 8Zm8.973 3.124A1 1 0 0 0 10.5 10.5h-1a1 1 0 0 1-1-1 1 1 0 0 0-1-1 1 1 0 0 1-1-1 1 1 0 0 1 1-1h.5a1 1 0 0 0 1-1V3.4a5.503 5.503 0 0 1 2.973 7.724Z"
				clip-rule="evenodd"
			/>
		</svg>
	{:else if state === 'failed'}
		<!-- 警示 -->
		<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3.5 shrink-0">
			<path
				fill-rule="evenodd"
				d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 6zm0 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"
				clip-rule="evenodd"
			/>
		</svg>
	{:else}
		<!-- 地球：未联网 / 原生待定 / 无结果 -->
		<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5 shrink-0">
			<path
				fill-rule="evenodd"
				d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1ZM2.5 8c0-.32.027-.633.08-.938l.21.21c.2.2.47.312.752.312H4.5a1 1 0 0 1 1 1v.5a1 1 0 0 0 1 1 1 1 0 0 1 1 1v1.36A5.502 5.502 0 0 1 2.5 8Zm8.973 3.124A1 1 0 0 0 10.5 10.5h-1a1 1 0 0 1-1-1 1 1 0 0 0-1-1 1 1 0 0 1-1-1 1 1 0 0 1 1-1h.5a1 1 0 0 0 1-1V3.4a5.503 5.503 0 0 1 2.973 7.724Z"
				clip-rule="evenodd"
			/>
		</svg>
	{/if}
	<span class="line-clamp-1">{label}</span>
</span>

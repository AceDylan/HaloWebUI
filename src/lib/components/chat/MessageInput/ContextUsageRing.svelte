<script lang="ts">
	import { DropdownMenu } from 'bits-ui';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { flyAndScale } from '$lib/utils/transitions';
	import {
		CONTEXT_FULL_RATIO,
		CONTEXT_WARN_RATIO,
		formatTokenCount,
		type ContextUsage
	} from '$lib/utils/context-usage';

	/** How full this chat's context is, next to the send button. Click for the
	 * numbers and 总结后在新对话继续. */
	export let usage: ContextUsage;
	export let canHandoff = false;
	export let handingOff = false;
	export let onHandoff: () => void = () => {};

	let show = false;

	const RADIUS = 7;
	const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

	$: percent = Math.min(999, Math.round(usage.ratio * 100));
	$: filled = Math.min(1, Math.max(0.02, usage.ratio));
	$: tone =
		usage.ratio >= CONTEXT_FULL_RATIO
			? 'text-red-500 dark:text-red-400'
			: usage.ratio >= CONTEXT_WARN_RATIO
				? 'text-amber-500 dark:text-amber-400'
				: 'text-gray-400 dark:text-gray-500';
	$: windowNote =
		usage.windowSource === 'model'
			? '上限取自模型设置'
			: usage.windowSource === 'family'
				? '上限按模型系列估计'
				: '不知道这个模型的上限，按 128k 估计';
</script>

<Dropdown bind:show side="top" align="end">
	<button
		type="button"
		class="flex size-8 items-center justify-center rounded-full transition hover:bg-gray-100 dark:hover:bg-gray-800 {tone}"
		aria-label="上下文已用 {percent}%"
		data-halo-context-usage={percent}
	>
		<svg viewBox="0 0 18 18" class="size-[18px] -rotate-90" aria-hidden="true">
			<circle cx="9" cy="9" r={RADIUS} fill="none" stroke="currentColor" stroke-opacity="0.22" stroke-width="2.2" />
			<circle
				cx="9"
				cy="9"
				r={RADIUS}
				fill="none"
				stroke="currentColor"
				stroke-width="2.2"
				stroke-linecap="round"
				stroke-dasharray={CIRCUMFERENCE}
				stroke-dashoffset={CIRCUMFERENCE * (1 - filled)}
			/>
		</svg>
	</button>

	<div slot="content">
		<DropdownMenu.Content
			class="z-50 w-[17rem] max-w-[calc(100vw-2rem)] rounded-xl border border-gray-200/70 bg-white px-3.5 py-3 text-sm shadow-lg dark:border-gray-800 dark:bg-gray-850 dark:text-white"
			sideOffset={8}
			side="top"
			align="end"
			transition={flyAndScale}
		>
			<div class="flex items-baseline justify-between gap-2">
				<span class="font-medium">上下文</span>
				<span class="tabular-nums {tone}">{percent}%</span>
			</div>
			<div class="mt-1 text-xs tabular-nums text-gray-600 dark:text-gray-300">
				{usage.estimated ? '约 ' : ''}{formatTokenCount(usage.tokens)} / {formatTokenCount(usage.window)} tokens
			</div>
			<div class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
				<div class="h-full rounded-full bg-current {tone}" style="width: {Math.min(100, percent)}%"></div>
			</div>
			<div class="mt-2 text-xs leading-5 text-gray-500 dark:text-gray-400">
				{usage.estimated ? '这段对话的回复没带用量，按字数估算。' : '按上一条回复的实际用量计算。'}{windowNote}。
				{#if usage.ratio >= CONTEXT_WARN_RATIO}
					快满时模型会忘掉前面的内容，或者直接报错。
				{/if}
			</div>

			{#if canHandoff}
				<button
					type="button"
					class="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-gray-800 disabled:opacity-60 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100"
					disabled={handingOff}
					data-halo-context-handoff
					on:click={() => {
						show = false;
						onHandoff();
					}}
				>
					{#if handingOff}
						<Spinner className="size-3.5" />
						<span>正在写摘要…</span>
					{:else}
						<span>总结后在新对话继续</span>
					{/if}
				</button>
			{/if}
		</DropdownMenu.Content>
	</div>
</Dropdown>

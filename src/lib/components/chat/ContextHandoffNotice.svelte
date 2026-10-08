<script context="module" lang="ts">
	// Per page load, across chat switches.
	const dismissed = new Set<string>();
</script>

<script lang="ts">
	import { fade } from 'svelte/transition';

	import { CONTEXT_NOTICE_RATIO, type ContextUsage } from '$lib/utils/context-usage';

	/** A chat close to its model's context limit says so once, above the composer,
	 * and offers 总结后在新对话继续. Dismissing hides it for this chat until the page reloads. */
	export let chatId = '';
	export let usage: ContextUsage | null = null;
	export let handingOff = false;
	export let onHandoff: () => void = () => {};

	// Bumped on dismiss so the check below runs again (the set is not reactive).
	let dismissedRevision = 0;
	const isDismissed = (id: string, _revision: number) => dismissed.has(id);

	$: visible =
		Boolean(chatId) &&
		usage !== null &&
		usage.ratio >= CONTEXT_NOTICE_RATIO &&
		!isDismissed(chatId, dismissedRevision);
</script>

{#if visible && usage}
	<div
		class="mx-auto mb-2 flex w-full max-w-3xl flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-amber-500/10 px-3 py-1.5 text-xs text-amber-800 dark:text-amber-200"
		transition:fade={{ duration: 120 }}
		data-halo-context-notice
	>
		<span>
			这段对话已用掉约 {Math.min(999, Math.round(usage.ratio * 100))}% 的上下文，再聊下去模型可能会忘掉前面的内容或者报错。
		</span>
		<button
			type="button"
			class="font-medium text-gray-900 hover:underline disabled:opacity-50 dark:text-white"
			disabled={handingOff}
			on:click={onHandoff}
			data-halo-context-notice-handoff
			>{handingOff ? '正在写摘要…' : '总结后在新对话继续'}</button
		>
		<button
			type="button"
			class="ml-auto text-amber-700/70 hover:text-amber-900 dark:text-amber-200/70 dark:hover:text-amber-100"
			aria-label="知道了"
			on:click={() => {
				dismissed.add(chatId);
				dismissedRevision += 1;
			}}>×</button
		>
	</div>
{/if}

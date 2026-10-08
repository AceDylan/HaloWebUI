<script lang="ts">
	import { onDestroy } from 'svelte';

	/**
	 * The end of a list that comes a page at a time: the next page is read as this comes into
	 * view (a little before it does), with a button for when that does not happen (no
	 * IntersectionObserver, a short list that never scrolls).
	 */
	export let more = false;
	export let loading = false;
	export let onMore: () => void;
	/** What the list holds, for the line at its end ("共 120 条"); null: not known. */
	export let total: number | null = null;
	export let shown = 0;

	let sentinel: HTMLDivElement;
	let observer: IntersectionObserver | null = null;

	const observe = (node: HTMLDivElement | undefined) => {
		observer?.disconnect();
		observer = null;
		if (!node || typeof IntersectionObserver === 'undefined') return;
		observer = new IntersectionObserver(
			(entries) => {
				if (entries.some((entry) => entry.isIntersecting) && more && !loading) onMore();
			},
			{ rootMargin: '480px 0px' }
		);
		observer.observe(node);
	};
	$: observe(more ? sentinel : undefined);
	onDestroy(() => observer?.disconnect());
</script>

{#if more}
	<div bind:this={sentinel} class="flex justify-center py-3" data-load-more>
		<button
			type="button"
			class="rounded-full px-3 py-1.5 text-xs text-gray-500 transition hover:bg-gray-500/10 hover:text-gray-800 disabled:opacity-60 dark:text-gray-400 dark:hover:text-gray-200"
			disabled={loading}
			on:click={onMore}
			data-load-more-button>{loading ? '正在加载…' : '加载更多'}</button
		>
	</div>
{:else if shown >= 20}
	<div class="py-3 text-center text-[11px] text-gray-400 dark:text-gray-500" data-load-more-end>
		已经到底了{total !== null ? ` · 共 ${total} 条` : ''}
	</div>
{/if}

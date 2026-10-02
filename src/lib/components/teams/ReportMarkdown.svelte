<script lang="ts">
	import { onMount } from 'svelte';
	import type { HeadingItem } from '$lib/utils/headings';

	/**
	 * A report or a task result, rendered by the chat's Markdown renderer (code blocks with copy,
	 * tables, math, images with preview) with a reading layer on top: report spacing, images as
	 * wide as the column, tables that scroll instead of overflowing. `content` is already
	 * prepared (see model.prepareReport). The renderer (KaTeX, highlighting, …) loads on first
	 * use, so the board does not pay for it until a result is shown.
	 */
	export let id: string;
	export let content: string;
	export let size: 'page' | 'panel' = 'panel';
	export let headings: HeadingItem[] = [];

	let Markdown: any = null;
	onMount(async () => {
		Markdown = (await import('$lib/components/chat/Messages/Markdown.svelte')).default;
	});
</script>

<div
	class="markdown-prose team-report {size === 'page' ? 'team-report--page' : 'team-report--panel'}"
>
	{#if Markdown}
		<svelte:component this={Markdown} {id} {content} bind:headings />
	{:else}
		<div class="flex flex-col gap-2 py-1" aria-busy="true">
			<div class="h-3 w-11/12 animate-pulse rounded bg-gray-100 dark:bg-gray-850" />
			<div class="h-3 w-4/5 animate-pulse rounded bg-gray-100 dark:bg-gray-850" />
			<div class="h-3 w-2/3 animate-pulse rounded bg-gray-100 dark:bg-gray-850" />
		</div>
	{/if}
</div>

<style>
	.team-report {
		max-width: 100%;
		overflow-wrap: anywhere;
	}
	.team-report--page {
		font-size: 15.5px;
		line-height: 1.8;
		max-width: 46rem;
	}
	.team-report--panel {
		font-size: 14px;
		line-height: 1.7;
	}
	.team-report :global(h1) {
		font-size: 1.55em;
		line-height: 1.25;
		letter-spacing: -0.015em;
		margin: 0 0 0.9em;
		font-weight: 650;
	}
	.team-report :global(h2) {
		font-size: 1.2em;
		line-height: 1.35;
		margin: 2em 0 0.6em;
		padding-bottom: 0.35em;
		border-bottom: 1px solid rgb(0 0 0 / 0.06);
	}
	:global(.dark) .team-report :global(h2) {
		border-bottom-color: rgb(255 255 255 / 0.07);
	}
	.team-report :global(h3) {
		font-size: 1.04em;
		margin: 1.5em 0 0.4em;
	}
	.team-report :global(h4) {
		font-size: 1em;
		margin: 1.2em 0 0.3em;
	}
	.team-report :global(p) {
		margin: 0.6em 0;
	}
	.team-report :global(ul),
	.team-report :global(ol) {
		margin: 0.5em 0 0.8em;
	}
	.team-report :global(li) {
		margin: 0.25em 0;
	}
	.team-report :global(blockquote) {
		margin: 1em 0;
		padding: 0.5em 1em;
		border-radius: 0 0.75rem 0.75rem 0;
		background: rgb(0 0 0 / 0.025);
	}
	/* A report quotes its one-line verdict; the typography plugin's curly quotes add nothing. */
	.team-report :global(blockquote p::before),
	.team-report :global(blockquote p::after) {
		content: none;
	}
	:global(.dark) .team-report :global(blockquote) {
		background: rgb(255 255 255 / 0.035);
	}
	.team-report :global(img) {
		max-width: 100% !important;
		max-height: 70vh !important;
		height: auto;
		border-radius: 0.75rem;
		margin: 0.75em 0;
	}
	.team-report :global(pre) {
		max-width: 100%;
	}
</style>

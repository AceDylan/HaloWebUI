<script lang="ts">
	import { onDestroy } from 'svelte';
	import tippy from 'tippy.js';
	import { getDisplayTitle, decodeString } from '$lib/utils/marked/citation-extension';

	export let id: string;
	export let token: any;
	export let onClick: Function = () => {};

	$: citations = token.citations ?? [];
	$: isMulti = citations.length > 1;
	$: firstCitation = citations[0];

	function formattedTitle(title: string): string {
		return getDisplayTitle(decodeString(title));
	}

	// Tippy popover for multi-citation
	let buttonElement: HTMLElement;
	let tippyInstance: any;

	function createPopoverContent(): HTMLElement {
		const container = document.createElement('div');
		container.className = 'flex flex-col gap-0.5 p-1';

		for (const c of citations) {
			const item = document.createElement('button');
			item.className =
				'flex items-center gap-1.5 text-xs w-full px-2 py-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition text-left';

			const badge = document.createElement('span');
			badge.className =
				'flex-shrink-0 size-[1.125rem] rounded-md bg-gray-100 dark:bg-gray-600 text-2xs flex items-center justify-center font-semibold';
			badge.textContent = String(c.index);

			const label = document.createElement('span');
			label.className = 'truncate max-w-[200px]';
			label.textContent = formattedTitle(c.title);

			item.appendChild(badge);
			item.appendChild(label);
			item.addEventListener('click', () => {
				onClick(id, c.identifier ?? c.index);
				tippyInstance?.hide();
			});
			container.appendChild(item);
		}
		return container;
	}

	function setupTippy(el: HTMLElement, multi: boolean) {
		tippyInstance?.destroy();
		if (!el || !multi) return;
		tippyInstance = tippy(el, {
			content: createPopoverContent(),
			interactive: true,
			placement: 'bottom-start',
			trigger: 'click',
			appendTo: () => document.body,
			animation: 'shift-away-subtle',
			theme: 'citation-popover',
			maxWidth: 280
		});
	}

	$: setupTippy(buttonElement, isMulti);

	onDestroy(() => {
		tippyInstance?.destroy();
	});
</script>

{#if firstCitation && firstCitation.title !== 'N/A'}
	{#if isMulti}
		<!-- Multi-citation: click opens popover listing all sources -->
		<button
			bind:this={buttonElement}
			data-inline-citation="true"
			class="inline-flex items-center gap-0.5 text-2xs font-medium w-fit translate-y-[2px] px-2 py-0.5 dark:bg-white/5 dark:text-white/80 dark:hover:text-white bg-gray-50 text-black/80 hover:text-black transition rounded-xl"
		>
			<span class="line-clamp-1 max-w-[200px]">
				{formattedTitle(firstCitation.title)}
			</span>
			<span class="opacity-50">+{citations.length - 1}</span>
		</button>
	{:else}
		<!-- Single citation: click navigates directly -->
		<button
			data-inline-citation="true"
			class="inline-flex items-center text-2xs font-medium w-fit translate-y-[2px] px-2 py-0.5 dark:bg-white/5 dark:text-white/80 dark:hover:text-white bg-gray-50 text-black/80 hover:text-black transition rounded-xl"
			on:click={() => {
				onClick(id, firstCitation.identifier ?? firstCitation.index);
			}}
		>
			<span class="line-clamp-1 max-w-[200px]">
				{formattedTitle(firstCitation.title)}
			</span>
		</button>
	{/if}
{/if}

<style>
	:global(.tippy-box[data-theme~='citation-popover']) {
		background-color: white;
		color: #374151;
		border: 1px solid #e5e7eb;
		border-radius: 0.75rem;
		box-shadow:
			0 4px 6px -1px rgb(0 0 0 / 0.1),
			0 2px 4px -2px rgb(0 0 0 / 0.1);
		font-size: 0.75rem;
	}
	:global(.tippy-box[data-theme~='citation-popover'] .tippy-content) {
		padding: 0.125rem;
	}
	:global(.tippy-box[data-theme~='citation-popover'] .tippy-arrow) {
		color: white;
	}
	:global(.dark .tippy-box[data-theme~='citation-popover']) {
		background-color: #1f2937;
		color: #d1d5db;
		border-color: #374151;
	}
	:global(.dark .tippy-box[data-theme~='citation-popover'] .tippy-arrow) {
		color: #1f2937;
	}
</style>

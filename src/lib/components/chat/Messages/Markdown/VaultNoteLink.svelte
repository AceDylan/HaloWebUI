<script lang="ts">
	// A note of the Hub's vault named in a reply (see hub-embed.ts): framed by the
	// Hub, a plain click asks the Hub to open it in its 笔记 tab; otherwise the link
	// is the Hub's own address for the note and opens in a new tab.
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';

	import { config } from '$lib/stores';
	import { hubNoteUrl, openNoteInHub } from '$lib/utils/hub-embed';
	import BookOpen from '$lib/components/icons/BookOpen.svelte';

	const i18n: Writable<any> = getContext('i18n');

	export let path: string;
	/** A small "打开笔记" button after a code span (whose own click still copies). */
	export let compact = false;

	$: href = hubNoteUrl(path, $config?.hub_origin);

	const open = (event: MouseEvent) => {
		// Middle / modified clicks keep the browser's own new-tab behaviour.
		if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
			return;
		}
		if (openNoteInHub(path, $config?.hub_origin)) {
			event.preventDefault();
		}
	};
</script>

{#if href && compact}
	<a
		{href}
		target="_blank"
		rel="noopener noreferrer"
		title={$i18n.t('Open in notes')}
		class="vault-note-open ml-1 inline-flex items-center gap-0.5 rounded-md px-1 align-baseline text-xs font-medium text-sky-700 no-underline hover:bg-sky-500/10 dark:text-sky-400"
		on:click={open}><BookOpen className="size-3.5" strokeWidth="1.8" />{$i18n.t('Open note')}</a
	>
{:else if href}
	<a
		{href}
		target="_blank"
		rel="noopener noreferrer"
		title={$i18n.t('Open in notes')}
		on:click={open}><slot /></a
	>
{:else if !compact}
	<slot />
{/if}

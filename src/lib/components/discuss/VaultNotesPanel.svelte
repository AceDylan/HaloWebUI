<script lang="ts">
	import { slide } from 'svelte/transition';

	import type { VaultNote } from '$lib/apis/discussions';

	/** The notes of the user's own knowledge base (Obsidian) that the run read with the question
	 * (utils/vault_notes.related_notes): a chip, then each note's excerpt. */
	export let notes: VaultNote[] = [];

	let open = false;
</script>

{#if notes?.length}
	<div class="dc-research flex flex-col gap-2" data-vault-notes={notes.length}>
		<div class="flex flex-wrap items-center gap-1.5">
			<button
				type="button"
				class="dc-chip !text-gray-700 dark:!text-gray-200"
				aria-expanded={open}
				on:click={() => (open = !open)}
				data-vault-notes-toggle
			>
				<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
					><path d="M3.5 2.5h6l3 3v8h-9z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" /><path
						d="M9.5 2.5v3h3M5.5 8.5h5M5.5 11h3.5"
						stroke="currentColor"
						stroke-width="1.1"
						stroke-linecap="round"
					/></svg
				>
				笔记库 · {notes.length} 篇
				<svg class="size-3 transition-transform {open ? 'rotate-180' : ''}" viewBox="0 0 12 12" fill="none" aria-hidden="true"
					><path d="m3 4.5 3 3 3-3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" /></svg
				>
			</button>
			{#each notes as note (note.path)}
				<span class="dc-chip max-w-[14rem] truncate" title={note.path}>{note.title}</span>
			{/each}
		</div>
		{#if open}
			<ol class="flex flex-col gap-2 rounded-xl bg-gray-500/5 p-3" transition:slide={{ duration: 180 }} data-vault-notes-list>
				{#each notes as note (note.path)}
					<li class="flex min-w-0 flex-col gap-0.5 text-xs leading-relaxed">
						<div class="min-w-0 truncate">
							<span class="font-medium text-gray-800 dark:text-gray-100">《{note.title}》</span>
							<span class="ml-1 text-gray-400">{note.path}</span>
						</div>
						{#if note.excerpt}
							<div class="dc-excerpt line-clamp-4 whitespace-pre-line text-gray-500 dark:text-gray-400">{note.excerpt}</div>
						{/if}
					</li>
				{/each}
			</ol>
		{/if}
	</div>
{/if}

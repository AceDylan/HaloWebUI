<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import Modal from '../common/Modal.svelte';

	const i18n: Writable<any> = getContext('i18n');

	export let show = false;

	type Shortcut = { label: string; keys: string[] };

	// Every entry is handled in routes/(app)/+layout.svelte (or the composer);
	// keep the two lists in step.
	const shortcutColumns: Shortcut[][] = [
		[
			{ label: 'Search Chats', keys: ['Ctrl/⌘', 'K'] },
			{ label: 'Open new chat', keys: ['Ctrl/⌘', 'Shift', 'O'] },
			{ label: 'Focus chat input', keys: ['Shift', 'Esc'] },
			{ label: 'Copy last code block', keys: ['Ctrl/⌘', 'Shift', ';'] },
			{ label: 'Copy last response', keys: ['Ctrl/⌘', 'Shift', 'C'] },
			{ label: 'Generate prompt pair', keys: ['Ctrl/⌘', 'Shift', 'Enter'] }
		],
		[
			{ label: 'Toggle settings', keys: ['Ctrl/⌘', '.'] },
			{ label: 'Toggle sidebar', keys: ['Ctrl/⌘', 'Shift', 'S'] },
			{ label: 'Delete chat', keys: ['Ctrl/⌘', 'Shift', '⌫/Delete'] },
			{ label: 'Temporary Chat', keys: ['Ctrl/⌘', 'Shift', "'"] },
			{ label: 'Open model selector', keys: ['Ctrl/⌘', 'Shift', 'M'] },
			{ label: 'Show shortcuts', keys: ['Ctrl/⌘', '/'] }
		]
	];

	const inputCommandColumns: Shortcut[][] = [
		[
			{ label: 'Attach file from knowledge', keys: ['#'] },
			{ label: 'Add custom prompt', keys: ['/'] },
			{ label: 'Talk to model', keys: ['@'] }
		],
		[
			{ label: 'Use a skill', keys: ['$'] },
			{ label: 'Stop the running reply', keys: ['Esc'] },
			{ label: 'Accept autocomplete generation / Jump to prompt variable', keys: ['TAB'] }
		]
	];
</script>

<Modal bind:show>
	<div class="text-gray-700 dark:text-gray-100">
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4">
			<div class=" text-lg font-medium self-center">{$i18n.t('Keyboard shortcuts')}</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		{#each [{ title: null, columns: shortcutColumns }, { title: 'Input commands', columns: inputCommandColumns }] as section}
			{#if section.title}
				<div class=" flex justify-between dark:text-gray-300 px-5">
					<div class=" text-lg font-medium self-center">{$i18n.t(section.title)}</div>
				</div>
			{/if}

			<div class="flex flex-col md:flex-row w-full p-5 gap-3 md:gap-6 dark:text-gray-200">
				{#each section.columns as column}
					<div class="flex flex-col gap-3 w-full self-start">
						{#each column as shortcut}
							<div class="w-full flex justify-between items-center gap-3">
								<div class="text-sm min-w-0">{$i18n.t(shortcut.label)}</div>

								<div class="flex shrink-0 gap-1 text-xs">
									{#each shortcut.keys as key}
										<kbd
											class="h-fit py-1 px-2 flex items-center justify-center whitespace-nowrap rounded-sm border border-black/10 font-sans capitalize text-gray-600 dark:border-white/10 dark:text-gray-300"
										>
											{key}
										</kbd>
									{/each}
								</div>
							</div>
						{/each}
					</div>
				{/each}
			</div>
		{/each}
	</div>
</Modal>

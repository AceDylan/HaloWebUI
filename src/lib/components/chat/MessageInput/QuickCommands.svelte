<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { prompts, user } from '$lib/stores';
	import { getPrompts } from '$lib/apis/prompts';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	// Workspace prompts as one-click chips above the input. A click prepends the
	// prompt to whatever is typed, so "instruction + question" is one click
	// instead of a retyped preamble. Managed in Workspace → Prompts.
	export let max = 8;

	onMount(async () => {
		if ($prompts === null) {
			const res = await getPrompts(localStorage.token).catch(() => null);
			if (Array.isArray(res)) {
				prompts.set(res);
			}
		}
	});

	$: chips = ($prompts ?? []).slice(0, max);
	$: canManage = $user?.role === 'admin' || $user?.permissions?.workspace?.prompts;

	const preview = (content: string) => (content ?? '').split('\n')[0].slice(0, 80);
</script>

{#if chips.length > 0}
	<div
		class="flex items-center gap-1.5 overflow-x-auto scrollbar-hidden px-1 pb-1.5 text-xs"
		aria-label={$i18n.t('Quick commands')}
	>
		{#each chips as chip (chip.command)}
			<Tooltip content={preview(chip.content)} placement="top">
				<button
					type="button"
					class="shrink-0 rounded-full border border-gray-200/80 bg-white/70 px-2.5 py-1 text-gray-600 transition hover:bg-gray-100 dark:border-gray-800 dark:bg-gray-900/60 dark:text-gray-300 dark:hover:bg-gray-850"
					on:click={() => dispatch('select', chip)}
				>
					{chip.name || chip.title || chip.command}
				</button>
			</Tooltip>
		{/each}
		{#if canManage}
			<a
				href="/workspace/prompts"
				class="shrink-0 px-1.5 py-1 text-gray-400 transition hover:text-gray-600 dark:hover:text-gray-300"
				title={$i18n.t('Prompts')}
			>
				+
			</a>
		{/if}
	</div>
{/if}

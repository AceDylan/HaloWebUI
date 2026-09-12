<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { prompts, user } from '$lib/stores';
	import { getPrompts } from '$lib/apis/prompts';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	// Workspace prompts as one-click chips above the input. A click prepends the
	// prompt to whatever is typed, so "instruction + question" is one click
	// instead of a retyped preamble. Managed in Workspace → Prompts.
	//
	// Layout: the row wraps instead of scrolling, every chip keeps its own width
	// (the tooltip wrapper used to shrink and the chips drew over each other on
	// phones) and long names are truncated with the full first line in the tooltip.
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
	const label = (chip: { name?: string; title?: string; command?: string }) =>
		(chip.name || chip.title || chip.command || '').trim();
</script>

{#if chips.length > 0}
	<div
		class="flex flex-wrap items-center gap-1.5 px-1 pb-2 text-xs"
		role="toolbar"
		aria-label={$i18n.t('Quick commands')}
	>
		{#each chips as chip (chip.command)}
			<Tooltip content={preview(chip.content)} placement="top" className="flex min-w-0 max-w-full">
				<button
					type="button"
					class="group inline-flex max-w-[11rem] items-center gap-1 rounded-full border border-gray-200/80 bg-white/80 py-1 pr-2.5 pl-2 text-gray-600 shadow-xs transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900 active:scale-[0.97] sm:max-w-[16rem] dark:border-gray-800 dark:bg-gray-900/70 dark:text-gray-300 dark:hover:border-gray-700 dark:hover:bg-gray-850 dark:hover:text-gray-100"
					on:click={() => dispatch('select', chip)}
				>
					<Sparkles
						className="size-3 shrink-0 text-gray-400 transition group-hover:text-amber-500 dark:text-gray-500"
						strokeWidth="2"
					/>
					<span class="truncate">{label(chip)}</span>
				</button>
			</Tooltip>
		{/each}
		{#if canManage}
			<Tooltip content={$i18n.t('Manage prompts')} placement="top" className="flex">
				<a
					href="/workspace/prompts"
					class="inline-flex size-[26px] items-center justify-center rounded-full border border-dashed border-gray-300 text-gray-400 transition hover:border-gray-400 hover:text-gray-600 dark:border-gray-700 dark:hover:border-gray-600 dark:hover:text-gray-300"
					aria-label={$i18n.t('Manage prompts')}
				>
					<Plus className="size-3" strokeWidth="2.5" />
				</a>
			</Tooltip>
		{/if}
	</div>
{/if}

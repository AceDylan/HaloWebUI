<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';
	import type { i18n as I18n } from 'i18next';
	import { prompts, user } from '$lib/stores';
	import { getPrompts } from '$lib/apis/prompts';
	import ImagePromptPicker from './ImagePromptPicker.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';

	const i18n = getContext<Readable<I18n>>('i18n');
	const dispatch = createEventDispatcher();

	// One-click chips inside the input's tool row (next to the "+" menu). A click
	// prepends the chip's text to whatever is typed, so "instruction + question" is
	// one click instead of a retyped preamble.
	//
	// Image mode has its own searchable picker, with access to every saved template.
	// Chat mode keeps the existing workspace prompt chips and their limit.
	export let max = 8;
	export let imageMode = false;

	type Chip = { key: string; label: string; content: string };

	onMount(async () => {
		if ($prompts === null) {
			const res = await getPrompts(localStorage.token).catch(() => null);
			if (Array.isArray(res)) {
				prompts.set(res);
			}
		}
	});

	const asChipLabel = (value: unknown) => `${value ?? ''}`.trim();

	$: promptChips = ($prompts ?? []).map(
		(prompt): Chip => ({
			key: `prompt:${prompt.command}`,
			label: asChipLabel((prompt as any).name || prompt.title || prompt.command),
			content: prompt.content ?? ''
		})
	);
	$: chips = promptChips.slice(0, max);

	$: canManagePrompts =
		$user?.role === 'admin' ||
		($user?.permissions?.workspace as { prompts?: boolean } | undefined)?.prompts;
	$: manageLabel = $i18n.t('Manage prompts');

	const preview = (content: string) => (content ?? '').split('\n')[0].slice(0, 80);
</script>

{#if imageMode}
	<ImagePromptPicker on:select />
{:else if chips.length > 0}
	<div
		class="flex shrink-0 items-center gap-1 text-xs"
		role="toolbar"
		aria-label={$i18n.t('Quick commands')}
		data-halo-quick-commands="chat"
	>
		{#each chips as chip (chip.key)}
			<Tooltip content={preview(chip.content)} placement="top" className="flex shrink-0">
				<button
					type="button"
					class="group inline-flex h-7 max-w-[9rem] items-center gap-1 rounded-full border border-gray-200/80 bg-white/80 pr-2.5 pl-2 text-gray-600 transition hover:border-primary-200 hover:bg-primary-50 hover:text-primary-800 active:scale-[0.97] sm:max-w-[13rem] dark:border-gray-700/80 dark:bg-gray-900/60 dark:text-gray-300 dark:hover:border-primary-500/40 dark:hover:bg-primary-500/10 dark:hover:text-primary-100"
					on:click={() => dispatch('select', { name: chip.label, content: chip.content })}
				>
					<Sparkles
						className="size-3 shrink-0 text-gray-400 transition group-hover:text-primary-500 dark:text-gray-500"
						strokeWidth="2"
					/>
					<span class="truncate">{chip.label}</span>
				</button>
			</Tooltip>
		{/each}
		{#if canManagePrompts}
			<Tooltip content={manageLabel} placement="top" className="flex shrink-0">
				<a
					href="/workspace/prompts"
					class="inline-flex size-7 items-center justify-center rounded-full border border-dashed border-gray-300 text-gray-500 transition hover:border-primary-400 hover:text-primary-600 dark:border-gray-700 dark:text-gray-400 dark:hover:border-primary-500/60 dark:hover:text-primary-300"
					aria-label={manageLabel}
				>
					<Plus className="size-3" strokeWidth="2.5" />
				</a>
			</Tooltip>
		{/if}
	</div>
{/if}

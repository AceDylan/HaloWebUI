<script lang="ts">
	import { createEventDispatcher, getContext, onMount, tick } from 'svelte';
	import type { Readable } from 'svelte/store';
	import type { i18n as I18n } from 'i18next';
	import { Dialog } from 'bits-ui';
	import { imageStudioTemplates, prompts, settings, user } from '$lib/stores';
	import { getImageStudioItems } from '$lib/apis/image-studio';
	import { partitionImageStudioItems } from '$lib/utils/image-studio-storage';
	import {
		filterImageTemplates,
		sortImageTemplates,
		type ImageTemplate
	} from '$lib/utils/image-templates';
	import { getPrompts } from '$lib/apis/prompts';
	import { saveUserSettingsPatch } from '$lib/utils/user-settings';
	import { chatPromptKey, orderPrompts, movePrompt } from '$lib/utils/prompt-order';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n = getContext<Readable<I18n>>('i18n');
	const dispatch = createEventDispatcher<{ select: { name: string; content: string } }>();
	export let imageMode = false;
	let orderKey: 'imagePromptOrder' | 'chatPromptOrder';
	let open = false;
	let sorting = false;
	let saving = false;
	let saveError = '';
	let saved = false;
	let query = '';
	let loading = false;
	let loadFailed = false;
	let mounted = false;
	let searchInput: HTMLInputElement;
	let resultsElement: HTMLDivElement;

	const loadTemplates = async () => {
		if (loading || (imageMode ? $imageStudioTemplates : $prompts) !== null) return;
		loading = true;
		loadFailed = false;
		try {
			if (imageMode) {
				const items = await getImageStudioItems(localStorage.token, 'template');
				if (mounted) imageStudioTemplates.set(partitionImageStudioItems(items).templates);
			} else {
				const items = await getPrompts(localStorage.token);
				if (mounted) prompts.set(items);
			}
		} catch {
			if (mounted) loadFailed = true;
		} finally {
			if (mounted) loading = false;
		}
	};

	onMount(() => {
		mounted = true;
		void loadTemplates();
		return () => {
			mounted = false;
		};
	});

	$: title = imageMode ? 'Image prompts' : 'Prompts';
	$: orderKey = imageMode ? 'imagePromptOrder' : 'chatPromptOrder';
	// Adapt workspace prompts to the existing template search/display contract.
	// Preserve original content and legacy title/command fields for insertion.
	$: sourceTemplates = imageMode
		? sortImageTemplates($imageStudioTemplates ?? [], 'recent')
		: ($prompts ?? [])
				.filter((prompt) => prompt.is_active !== false)
				.map(
					(prompt): ImageTemplate => ({
						id: chatPromptKey(prompt),
						name: (prompt.name || prompt.title || prompt.command || '').trim(),
						tags: [...(prompt.tags ?? []), prompt.command].filter(Boolean),
						config: { prompt: prompt.content ?? '' },
						createdAt: 0,
						updatedAt: 0
					})
				);
	$: templates = orderPrompts(
		sourceTemplates.filter((template) => Boolean(template.config.prompt?.trim())),
		$settings[orderKey],
		(template) => template.id
	);
	$: matches = filterImageTemplates(templates, { query });
	$: canManage =
		$user?.role === 'admin' ||
		Boolean(
			imageMode
				? ($user?.permissions?.features as { image_generation?: boolean } | undefined)
						?.image_generation
				: ($user?.permissions?.workspace as { prompts?: boolean } | undefined)?.prompts
		);
	$: if (!open) {
		query = '';
		sorting = false;
	}
	// Only a new search resets scroll; moving an item must not jump to the top.
	$: if (query !== undefined && resultsElement) resultsElement.scrollTop = 0;

	const moveActions = (index: number) => [
		{ label: 'Move to top', target: 0 },
		{ label: 'Move up', target: index - 1 },
		{ label: 'Move down', target: index + 1 }
	];

	const reorder = async (id: string, target: number) => {
		if (saving) return;
		const order = movePrompt(
			templates.map((template) => template.id),
			id,
			target
		);
		saving = true;
		saveError = '';
		saved = false;
		try {
			// The shared settings helper uses revisions and reloads on conflict.
			// Keep the displayed order unchanged until the server acknowledges it.
			const result = await saveUserSettingsPatch(localStorage.token, { [orderKey]: order });
			if (!result) throw new Error('Missing settings response');
			saved = true;
		} catch (error) {
			saveError =
				(error as { status?: number })?.status === 409
					? 'Prompt order changed elsewhere. Please try again.'
					: 'Failed to save prompt order. Please try again.';
		} finally {
			saving = false;
		}
	};

	const selectTemplate = async (template: ImageTemplate) => {
		open = false;
		// Release the dialog's focus trap before MessageInput focuses the editor.
		await tick();
		dispatch('select', { name: template.name, content: template.config.prompt ?? '' });
	};
</script>

<Dialog.Root
	bind:open
	openFocus={(dialog) =>
		window.matchMedia('(pointer: fine)').matches ? searchInput : (dialog ?? null)}
>
	<Dialog.Trigger
		class="inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-gray-200/80 bg-white/80 px-2.5 text-xs text-gray-600 transition hover:border-primary-200 hover:bg-primary-50 hover:text-primary-800 dark:border-gray-700/80 dark:bg-gray-900/60 dark:text-gray-300 dark:hover:border-primary-500/40 dark:hover:bg-primary-500/10"
		data-halo-quick-commands={imageMode ? 'image' : 'chat'}
	>
		{#if imageMode}
			<Photo className="size-3.5 shrink-0" strokeWidth="2" />
		{:else}
			<Sparkles className="size-3.5 shrink-0" strokeWidth="2" />
		{/if}
		<span>{$i18n.t(title)}</span>
		{#if (imageMode ? $imageStudioTemplates : $prompts) !== null}
			<span class="rounded-full bg-gray-100 px-1.5 tabular-nums dark:bg-gray-800">
				{templates.length}
			</span>
		{/if}
	</Dialog.Trigger>
	<Dialog.Portal>
		<Dialog.Overlay class="fixed inset-0 z-9999 bg-black/40 dark:bg-black/60" />
		<Dialog.Content
			class="fixed left-1/2 top-1/2 z-9999 flex max-h-[85dvh] w-[calc(100%-1.5rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white text-gray-900 shadow-2xl dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
		>
			<div class="flex shrink-0 items-start justify-between gap-3 px-4 pt-4">
				<div class="min-w-0">
					<Dialog.Title class="text-base font-semibold">{$i18n.t(title)}</Dialog.Title>
					<Dialog.Description class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
						{$i18n.t('Select a prompt to insert it into your message.')}
					</Dialog.Description>
				</div>
				<Dialog.Close
					class="flex size-10 shrink-0 items-center justify-center rounded-xl text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
					aria-label={$i18n.t('Close')}
				>
					<XMark className="size-5" />
				</Dialog.Close>
			</div>
			<div class="shrink-0 px-4 pb-2 pt-3">
				<div
					class="flex items-center gap-2 rounded-xl border border-gray-200 px-3 dark:border-gray-700"
				>
					<Search className="size-4 shrink-0 text-gray-400" />
					<input
						bind:this={searchInput}
						bind:value={query}
						type="search"
						disabled={sorting}
						class="min-w-0 flex-1 bg-transparent py-2.5 text-base outline-none sm:text-sm"
						placeholder={$i18n.t(imageMode ? 'Search templates' : 'Search prompts')}
						aria-label={$i18n.t(imageMode ? 'Search templates' : 'Search prompts')}
						on:keydown={(event) => {
							if (event.key === 'ArrowDown' && !event.isComposing) {
								event.preventDefault();
								resultsElement?.querySelector('button')?.focus();
							}
						}}
					/>
				</div>
				<div class="pt-2 text-xs tabular-nums text-gray-500" role="status" aria-live="polite">
					{#if loading}
						{$i18n.t('Loading...')}
					{:else}
						{matches.length} / {templates.length}
					{/if}
				</div>
			</div>
			<div class="flex flex-wrap items-center justify-between gap-2 px-4 pb-2">
				<button
					type="button"
					class="min-h-10 rounded-lg border border-gray-200 px-3 text-xs disabled:opacity-40 dark:border-gray-700"
					disabled={saving || (!sorting && templates.length < 2)}
					aria-pressed={sorting}
					on:click={() => {
						query = '';
						sorting = !sorting;
						saved = false;
						saveError = '';
					}}>{$i18n.t(sorting ? 'Done' : 'Sort prompts')}</button
				>
				<span class="text-xs text-gray-500" role="status" aria-live="polite">
					{#if saving}{$i18n.t('Saving...')}{:else if saved}{$i18n.t('Prompt order saved.')}{/if}
				</span>
			</div>
			{#if saveError}
				<p class="px-4 pb-2 text-sm text-red-600 dark:text-red-400" role="alert">
					{$i18n.t(saveError)}
				</p>
			{/if}
			<div
				bind:this={resultsElement}
				class="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain px-4 pb-4"
				aria-busy={loading}
			>
				{#if loadFailed}
					<div class="py-6 text-center text-sm" role="alert">
						<p>
							{$i18n.t(imageMode ? 'Failed to load image prompts.' : 'Failed to load prompts.')}
						</p>
						<button
							type="button"
							class="mt-3 rounded-xl border border-gray-200 px-4 py-2 dark:border-gray-700"
							on:click={loadTemplates}>{$i18n.t('Retry')}</button
						>
					</div>
				{:else if !loading && matches.length === 0}
					<p class="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
						{$i18n.t(
							imageMode
								? templates.length === 0
									? 'No templates saved yet'
									: 'No templates match'
								: templates.length === 0
									? 'No prompts yet. Create your first prompt to get started.'
									: 'No matching prompts.'
						)}
					</p>
				{:else}
					{#each matches as template, index (template.id)}
						<div class="rounded-xl" data-prompt-id={template.id}>
							<button
								type="button"
								class="block w-full min-w-0 rounded-xl border border-gray-200 p-3 text-left transition [overflow-wrap:anywhere] hover:border-primary-300 hover:bg-primary-50 dark:border-gray-700 dark:hover:border-primary-500/50 dark:hover:bg-primary-500/10"
								aria-label={template.name}
								disabled={sorting}
								data-prompt-select
								on:click={() => selectTemplate(template)}
							>
								<span class="block whitespace-normal text-sm font-medium leading-5"
									>{template.name}</span
								>
								{#if template.tags?.length}
									<span class="mt-1 block text-xs text-primary-600 dark:text-primary-300">
										{template.tags.join(' · ')}
									</span>
								{/if}
								<span
									class="mt-1.5 line-clamp-2 whitespace-pre-wrap text-xs leading-5 text-gray-500 dark:text-gray-400"
								>
									{template.config.prompt}
								</span>
							</button>
							{#if sorting}
								<div
									class="flex flex-wrap justify-end gap-1 py-1"
									role="group"
									aria-label={template.name}
								>
									{#each moveActions(index) as { label, target }}
										<button
											type="button"
											class="min-h-10 rounded-lg px-3 text-xs hover:bg-gray-100 disabled:opacity-40 dark:hover:bg-gray-800"
											disabled={saving ||
												target === index ||
												target < 0 ||
												target >= matches.length}
											on:click={() => reorder(template.id, target)}>{$i18n.t(label)}</button
										>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				{/if}
			</div>
			{#if canManage}
				<div class="shrink-0 border-t border-gray-100 px-4 py-3 dark:border-gray-800">
					<a
						href={imageMode ? '/workspace/images?tab=prompts' : '/workspace/prompts'}
						class="inline-flex min-h-10 items-center text-sm text-primary-600 hover:underline dark:text-primary-300"
						on:click={() => (open = false)}
						>{$i18n.t(imageMode ? 'Manage image prompts' : 'Manage prompts')}</a
					>
				</div>
			{/if}
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>

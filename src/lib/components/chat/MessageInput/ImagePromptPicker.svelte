<script lang="ts">
	import { createEventDispatcher, getContext, onMount, tick } from 'svelte';
	import type { Readable } from 'svelte/store';
	import type { i18n as I18n } from 'i18next';
	import { Dialog } from 'bits-ui';
	import { imageStudioTemplates, user } from '$lib/stores';
	import { getImageStudioItems } from '$lib/apis/image-studio';
	import { partitionImageStudioItems } from '$lib/utils/image-studio-storage';
	import {
		filterImageTemplates,
		sortImageTemplates,
		type ImageTemplate
	} from '$lib/utils/image-templates';
	import Photo from '$lib/components/icons/Photo.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n = getContext<Readable<I18n>>('i18n');
	const dispatch = createEventDispatcher<{ select: { name: string; content: string } }>();
	let open = false;
	let query = '';
	let loading = false;
	let loadFailed = false;
	let mounted = false;
	let searchInput: HTMLInputElement;
	let resultsElement: HTMLDivElement;

	const loadTemplates = async () => {
		if (loading || $imageStudioTemplates !== null) return;
		loading = true;
		loadFailed = false;
		try {
			const items = await getImageStudioItems(localStorage.token, 'template');
			if (mounted) imageStudioTemplates.set(partitionImageStudioItems(items).templates);
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

	$: templates = sortImageTemplates($imageStudioTemplates ?? [], 'recent').filter((template) =>
		Boolean(template.config.prompt?.trim())
	);
	$: matches = filterImageTemplates(templates, { query });
	$: canManage =
		$user?.role === 'admin' ||
		Boolean(
			($user?.permissions?.features as { image_generation?: boolean } | undefined)?.image_generation
		);
	$: if (!open) query = '';
	// A new search must start at the top even after scrolling to an older template.
	$: if (matches && resultsElement) resultsElement.scrollTop = 0;

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
		data-halo-quick-commands="image"
	>
		<Photo className="size-3.5 shrink-0" strokeWidth="2" />
		<span>{$i18n.t('Image prompts')}</span>
		{#if $imageStudioTemplates !== null}
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
					<Dialog.Title class="text-base font-semibold">{$i18n.t('Image prompts')}</Dialog.Title>
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
						class="min-w-0 flex-1 bg-transparent py-2.5 text-base outline-none sm:text-sm"
						placeholder={$i18n.t('Search templates')}
						aria-label={$i18n.t('Search templates')}
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
			<div
				bind:this={resultsElement}
				class="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain px-4 pb-4"
				aria-busy={loading}
			>
				{#if loadFailed}
					<div class="py-6 text-center text-sm" role="alert">
						<p>{$i18n.t('Failed to load image prompts.')}</p>
						<button
							type="button"
							class="mt-3 rounded-xl border border-gray-200 px-4 py-2 dark:border-gray-700"
							on:click={loadTemplates}>{$i18n.t('Retry')}</button
						>
					</div>
				{:else if !loading && matches.length === 0}
					<p class="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
						{$i18n.t(templates.length === 0 ? 'No templates saved yet' : 'No templates match')}
					</p>
				{:else}
					{#each matches as template (template.id)}
						<button
							type="button"
							class="block w-full min-w-0 rounded-xl border border-gray-200 p-3 text-left transition [overflow-wrap:anywhere] hover:border-primary-300 hover:bg-primary-50 dark:border-gray-700 dark:hover:border-primary-500/50 dark:hover:bg-primary-500/10"
							aria-label={template.name}
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
					{/each}
				{/if}
			</div>
			{#if canManage}
				<div class="shrink-0 border-t border-gray-100 px-4 py-3 dark:border-gray-800">
					<a
						href="/workspace/images?tab=prompts"
						class="inline-flex min-h-10 items-center text-sm text-primary-600 hover:underline dark:text-primary-300"
						on:click={() => (open = false)}>{$i18n.t('Manage image prompts')}</a
					>
				</div>
			{/if}
		</Dialog.Content>
	</Dialog.Portal>
</Dialog.Root>

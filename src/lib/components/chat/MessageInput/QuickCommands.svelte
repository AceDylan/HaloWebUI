<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { imageStudioTemplates, prompts, user } from '$lib/stores';
	import { getPrompts } from '$lib/apis/prompts';
	import { getImageStudioItems } from '$lib/apis/image-studio';
	import { partitionImageStudioItems } from '$lib/utils/image-studio-storage';
	import { sortImageTemplates } from '$lib/utils/image-templates';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	// One-click chips inside the input's tool row (next to the "+" menu). A click
	// prepends the chip's text to whatever is typed, so "instruction + question" is
	// one click instead of a retyped preamble.
	//
	// Two separate sources, never mixed: while the chat is talking, the chips are the
	// workspace prompts (Workspace → Prompts); while it is drawing (`imageMode`: the
	// image toggle is on or the selected model is itself an image model) they are the
	// image studio's saved prompt templates (Workspace → Images → Prompts), so a chat
	// prompt never ends up inside an image brief and vice versa.
	//
	// Layout: the row lives inside the horizontally scrolling tool strip, so chips never
	// wrap into a second line on phones; every chip keeps its own width (the tooltip wrapper
	// used to shrink and the chips drew over each other) and long names are truncated with
	// the full first line in the tooltip.
	export let max = 8;
	export let imageMode = false;

	type Chip = { key: string; label: string; content: string };

	let loadingTemplates = false;

	onMount(async () => {
		if ($prompts === null) {
			const res = await getPrompts(localStorage.token).catch(() => null);
			if (Array.isArray(res)) {
				prompts.set(res);
			}
		}
	});

	const loadImageTemplates = async () => {
		if (loadingTemplates || $imageStudioTemplates !== null) {
			return;
		}
		loadingTemplates = true;
		try {
			const items = await getImageStudioItems(localStorage.token, 'template');
			imageStudioTemplates.set(partitionImageStudioItems(items).templates);
		} catch (error) {
			console.warn('Failed to load image studio templates for quick commands', error);
		} finally {
			loadingTemplates = false;
		}
	};

	$: if (imageMode) {
		void loadImageTemplates();
	}

	const asChipLabel = (value: unknown) => `${value ?? ''}`.trim();

	$: promptChips = ($prompts ?? []).map(
		(prompt): Chip => ({
			key: `prompt:${prompt.command}`,
			label: asChipLabel((prompt as any).name || prompt.title || prompt.command),
			content: prompt.content ?? ''
		})
	);
	$: templateChips = sortImageTemplates($imageStudioTemplates ?? [], 'recent')
		.filter((template) => Boolean(template.config.prompt))
		.map(
			(template): Chip => ({
				key: `template:${template.id}`,
				label: asChipLabel(template.name),
				content: template.config.prompt ?? ''
			})
		);
	$: chips = (imageMode ? templateChips : promptChips).slice(0, max);

	$: canManagePrompts = $user?.role === 'admin' || $user?.permissions?.workspace?.prompts;
	$: canManageTemplates =
		$user?.role === 'admin' || Boolean($user?.permissions?.features?.image_generation);
	$: canManage = imageMode ? canManageTemplates : canManagePrompts;
	$: manageHref = imageMode ? '/workspace/images?tab=prompts' : '/workspace/prompts';
	$: manageLabel = imageMode ? $i18n.t('Manage image prompts') : $i18n.t('Manage prompts');

	const preview = (content: string) => (content ?? '').split('\n')[0].slice(0, 80);
</script>

{#if chips.length > 0}
	<div
		class="flex shrink-0 items-center gap-1 text-xs"
		role="toolbar"
		aria-label={imageMode ? $i18n.t('Image prompts') : $i18n.t('Quick commands')}
		data-halo-quick-commands={imageMode ? 'image' : 'chat'}
	>
		{#each chips as chip (chip.key)}
			<Tooltip content={preview(chip.content)} placement="top" className="flex shrink-0">
				<button
					type="button"
					class="group inline-flex h-7 max-w-[9rem] items-center gap-1 rounded-full border border-gray-200/80 bg-white/80 pr-2.5 pl-2 text-gray-600 transition hover:border-primary-200 hover:bg-primary-50 hover:text-primary-800 active:scale-[0.97] sm:max-w-[13rem] dark:border-gray-700/80 dark:bg-gray-900/60 dark:text-gray-300 dark:hover:border-primary-500/40 dark:hover:bg-primary-500/10 dark:hover:text-primary-100"
					on:click={() => dispatch('select', { name: chip.label, content: chip.content })}
				>
					{#if imageMode}
						<Photo
							className="size-3 shrink-0 text-gray-400 transition group-hover:text-primary-500 dark:text-gray-500"
							strokeWidth="2"
						/>
					{:else}
						<Sparkles
							className="size-3 shrink-0 text-gray-400 transition group-hover:text-primary-500 dark:text-gray-500"
							strokeWidth="2"
						/>
					{/if}
					<span class="truncate">{chip.label}</span>
				</button>
			</Tooltip>
		{/each}
		{#if canManage}
			<Tooltip content={manageLabel} placement="top" className="flex shrink-0">
				<a
					href={manageHref}
					class="inline-flex size-7 items-center justify-center rounded-full border border-dashed border-gray-300 text-gray-500 transition hover:border-primary-400 hover:text-primary-600 dark:border-gray-700 dark:text-gray-400 dark:hover:border-primary-500/60 dark:hover:text-primary-300"
					aria-label={manageLabel}
				>
					<Plus className="size-3" strokeWidth="2.5" />
				</a>
			</Tooltip>
		{/if}
	</div>
{/if}

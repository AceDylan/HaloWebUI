<script lang="ts">
	import { config, models, modelsError, modelsStatus, user } from '$lib/stores';
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { canJoinDiscussion } from '$lib/utils/discussion-seats';
	import type { Writable } from 'svelte/store';
	import Selector from './ModelSelector/Selector.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { getModelChatDisplayName } from '$lib/utils/model-display';
	import { getModelSelectionId, resolveModelSelectionId } from '$lib/utils/model-identity';
	import { getTemporaryChatAccess } from '$lib/utils/temporary-chat';
	const i18n: Writable<any> = getContext('i18n');

	export let selectedModels = [''];
	export let disabled = false;
	export let multiModelDiscussionEnabled = false;
	export let maxDiscussionModels = 5;

	export let showSetDefault = true;
	/**
	 * Several models = a discussion: ticking a second model in the menu hands the ticked models
	 * here (the chat carries the draft and the conversation along); without it, 讨论台 opens with
	 * the models as seats.
	 */
	export let onDiscuss: ((models: string[]) => void) | null = null;
	const startDiscussion = (picked: string[]) =>
		onDiscuss
			? onDiscuss(picked)
			: goto(`/discuss${picked.length ? `?models=${encodeURIComponent(picked.join(','))}` : ''}`);
	$: discussPickable =
		canUseMultipleModels && !disabled
			? (item: { model?: any }) => canJoinDiscussion(item?.model, $config?.hermes_agent_model_ids)
			: null;

	$: canUseMultipleModels =
		$user?.role === 'admin' || ($user?.permissions?.chat?.multiple_models ?? true);
	$: selectedModelCount = selectedModels.filter((model) => `${model ?? ''}`.trim()).length;
	$: showMultiModelDiscussionToggle = canUseMultipleModels && selectedModels.length >= 2;
	$: discussionDisabled = disabled || !canUseMultipleModels || selectedModelCount < 2;
	$: discussionIssue = !canUseMultipleModels
		? $i18n.t('Multiple models are not enabled for your account')
		: selectedModelCount < 2
			? $i18n.t('Select at least 2 models to start a discussion')
			: selectedModelCount > maxDiscussionModels
				? $i18n.t('Discussion uses the first {{count}} selected models', {
						count: maxDiscussionModels
					})
				: '';
	// Discussions moved to their own page (讨论台, /discuss): the old in-chat switch is gone, and a
	// value restored from an older chat's composer state is turned off rather than silently used.
	$: if (multiModelDiscussionEnabled) {
		multiModelDiscussionEnabled = false;
	}
	$: discussHref = `/discuss?models=${encodeURIComponent(
		selectedModels.filter((model) => `${model ?? ''}`.trim()).join(',')
	)}`;

	// Stable items array: only recomputed when $models reference changes
	$: selectorItems = $models.map((model) => ({
		value: getModelSelectionId(model),
		label: getModelChatDisplayName(model),
		model: model
	}));

	$: if (selectedModels.length > 0 && $models.length > 0) {
		const normalizedModels = selectedModels.map((model) =>
			resolveModelSelectionId($models, model, { preserveAmbiguous: true, preserveMissing: true })
		);
		if (JSON.stringify(normalizedModels) !== JSON.stringify(selectedModels)) {
			selectedModels = normalizedModels;
		}
	}

	let temporaryChatAccess = { allowed: true, enforced: false };
	$: temporaryChatAccess = getTemporaryChatAccess($user);
</script>

<div class="flex min-w-0 flex-col w-full items-start">
	{#if $modelsStatus === 'loading' && $models.length === 0}
		<div class="flex items-center gap-2 text-xs text-gray-500 ml-1 pb-1">
			<Spinner className="size-3.5" />
			<span>{$i18n.t('Loading models...')}</span>
		</div>
	{:else if $modelsStatus === 'error' && $models.length === 0}
		<div class="text-xs text-gray-500 ml-1 pb-1">
			<span>{$i18n.t('Failed to load models')}</span>
			{#if $modelsError}
				<span class="text-gray-400">: {$modelsError}</span>
			{/if}
		</div>
	{/if}

	{#if selectedModels.length <= 1}
		<!-- 单模型：菜单里能参加讨论的模型带勾选框，勾第二个就去讨论台（取代「添加模型对比」）。 -->
		{#each selectedModels as selectedModel, selectedModelIdx}
			<div class="flex w-fit max-w-full min-w-0 items-center gap-1.5">
				<div class="min-w-0 max-w-full overflow-hidden">
					<div class="min-w-0 max-w-full">
						<Selector
							id={`${selectedModelIdx}`}
							placeholder={$i18n.t('Select a model')}
							items={selectorItems}
							showSetDefaultAction={showSetDefault && selectedModelIdx === 0}
							showTemporaryChatControl={temporaryChatAccess.allowed &&
								!temporaryChatAccess.enforced}
							{discussPickable}
							onDiscuss={discussPickable ? startDiscussion : null}
							bind:value={selectedModel}
						/>
					</div>
				</div>
			</div>
		{/each}
	{:else}
		<!-- 多模型：每个模型都是完整胶囊，删除按钮始终占位可见，避免 hover 时出现隐形框。 -->
		<div class="flex w-full min-w-0 flex-wrap items-center gap-1.5 max-w-full">
			{#each selectedModels as selectedModel, selectedModelIdx}
				<div
					class="group/chip flex min-w-0 max-w-full items-center gap-1 rounded-xl border border-gray-200 bg-white px-1 py-0.5 shadow-xs transition-colors hover:border-gray-300 dark:border-gray-700 dark:bg-gray-900/70 dark:hover:border-gray-600"
				>
					<div class="min-w-0 overflow-hidden max-w-[210px] rounded-lg">
						<Selector
							id={`${selectedModelIdx}`}
							placeholder={$i18n.t('Select a model')}
							items={selectorItems}
							showSetDefaultAction={showSetDefault && selectedModelIdx === 0}
							showTemporaryChatControl={selectedModelIdx === 0 &&
								temporaryChatAccess.allowed &&
								!temporaryChatAccess.enforced}
							triggerClassName="text-sm rounded-lg !border-transparent !bg-transparent !shadow-none hover:!border-transparent hover:!bg-transparent dark:!border-transparent dark:!bg-transparent dark:hover:!border-transparent dark:hover:!bg-transparent"
							bind:value={selectedModel}
						/>
					</div>
					{#if selectedModelIdx > 0}
						<Tooltip content={$i18n.t('Remove Model')}>
							<button
								class="inline-flex items-center justify-center
									size-6 shrink-0 rounded-lg
									text-gray-400 dark:text-gray-500
									bg-transparent
									border border-transparent
									hover:border-red-100 dark:hover:border-red-900/40
									hover:bg-red-50/80 dark:hover:bg-red-900/20
									hover:text-red-500 dark:hover:text-red-400
									active:scale-[0.88]
									transition-all duration-150
									disabled:opacity-40 disabled:pointer-events-none"
								{disabled}
								on:click={() => {
									selectedModels.splice(selectedModelIdx, 1);
									selectedModels = selectedModels;
								}}
								aria-label={$i18n.t('Remove Model')}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2.5"
									stroke="currentColor"
									class="size-3"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						</Tooltip>
					{/if}
				</div>
			{/each}

			<!-- 不再往旧的并排对话里加模型：多个模型一起答问题去讨论台（下面的链接）。 -->
		</div>
	{/if}

	{#if showMultiModelDiscussionToggle && !discussionDisabled}
		<a
			href={discussHref}
			class="mt-1.5 inline-flex max-w-full items-center gap-1 rounded-full bg-white/85 px-2 py-0.5 text-xs text-gray-500 backdrop-blur-sm transition hover:bg-gray-100 hover:text-gray-900 dark:bg-gray-900/70 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
			title={discussionIssue || '让这几个模型在讨论台里讨论，主持人给出结论'}
			data-open-discuss
			on:click={(event) => {
				if (!onDiscuss || event.metaKey || event.ctrlKey || event.shiftKey) return;
				event.preventDefault();
				startDiscussion(selectedModels.filter((model) => `${model ?? ''}`.trim()));
			}}
		>
			<svg class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
				><path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" /><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" /></svg
			>
			到讨论台讨论
			<span aria-hidden="true">→</span>
		</a>
	{/if}
</div>

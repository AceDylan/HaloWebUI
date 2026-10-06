<script context="module" lang="ts">
	import type { ChatAssistantSnapshot as Snapshot } from '$lib/utils/chat-assistants';

	/** What a pick hands back: the assistant for the chat, plus its library ref (`model:<id>` for
	 * the user's own, `builtin:<id>` for a template). */
	export type PickedAssistant = Snapshot & { ref: string };
</script>

<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import agentsData from '$lib/data/agents-zh.json';
	import { listLibrary, sourceLabel, type LibraryEntry } from '$lib/apis/assistant-library';
	import { translateWithDefault } from '$lib/i18n';
	import {
		type ChatAssistantSnapshot,
		libraryEntryToSnapshot,
		toChatAssistantSnapshot
	} from '$lib/utils/chat-assistants';

	const i18n = getContext('i18n');
	const tr = (zh: string, en: string, options: Record<string, any> = {}) =>
		translateWithDefault($i18n, zh, en, options);

	const dispatch = createEventDispatcher<{
		select: PickedAssistant;
		close: void;
	}>();

	export let show = false;
	/** Refs (or template ids) already chosen: shown ticked and not selectable. */
	export let excludeIds: string[] = [];
	/** `featured`: adding to the home page's list; `activate`: using one in this chat. */
	export let mode: 'featured' | 'activate' = 'featured';

	const MINE_GROUP = '__mine';

	let searchValue = '';
	let selectedGroup = '';
	let previousShow = false;
	let excludedIdSet: Set<string> = new Set();

	type AssistantPickerItem = PickedAssistant & {
		groups: string[];
		note?: string;
	};

	const templateItems = (agentsData as Array<Record<string, unknown>>)
		.map((agent) => {
			const assistant = toChatAssistantSnapshot(agent);
			if (!assistant) {
				return null;
			}

			return {
				...assistant,
				ref: `builtin:${assistant.id}`,
				groups: ((agent.group ?? []) as string[]).filter(Boolean)
			} satisfies AssistantPickerItem;
		})
		.filter(Boolean) as AssistantPickerItem[];

	const groupCounts: Record<string, number> = {};
	for (const assistant of templateItems) {
		for (const group of assistant.groups) {
			groupCounts[group] = (groupCounts[group] ?? 0) + 1;
		}
	}

	const groups = Object.entries(groupCounts)
		.sort((a, b) => b[1] - a[1])
		.map(([name, count]) => ({ name, count }));

	// The user's own assistants (hidden ones too: hiding is for the model menus), loaded on open.
	let mineItems: AssistantPickerItem[] = [];
	let mineLoading = false;
	let mineError = '';

	const toMineItem = (entry: LibraryEntry): AssistantPickerItem | null => {
		const snapshot = libraryEntryToSnapshot(entry);
		if (!snapshot) return null;
		return {
			...snapshot,
			ref: entry.ref,
			groups: [],
			note: [sourceLabel(entry.source), entry.version ? `v${entry.version}` : '', entry.hidden ? tr('菜单中隐藏', 'Hidden in menus') : '']
				.filter(Boolean)
				.join(' · ')
		};
	};

	const loadMine = async () => {
		mineLoading = true;
		mineError = '';
		try {
			const res = await listLibrary(localStorage.token);
			mineItems = (res?.assistants ?? []).map(toMineItem).filter(Boolean) as AssistantPickerItem[];
		} catch (e: any) {
			mineItems = [];
			mineError = e?.message ?? String(e);
		} finally {
			mineLoading = false;
		}
	};

	const matches = (assistant: AssistantPickerItem, query: string) =>
		query === '' ||
		assistant.name.toLowerCase().includes(query) ||
		(assistant.description ?? '').toLowerCase().includes(query);

	$: excludedIdSet = new Set(excludeIds);
	$: query = searchValue.trim().toLowerCase();
	$: filteredMine =
		selectedGroup === '' || selectedGroup === MINE_GROUP
			? mineItems.filter((assistant) => matches(assistant, query))
			: [];
	$: filteredAssistants =
		selectedGroup === MINE_GROUP
			? []
			: templateItems.filter(
					(assistant) =>
						matches(assistant, query) &&
						(selectedGroup === '' || assistant.groups.includes(selectedGroup))
				);

	const isExcluded = (assistant: AssistantPickerItem) =>
		excludedIdSet.has(assistant.ref) || excludedIdSet.has(assistant.id);

	const handleClose = () => {
		show = false;
	};

	const handleSelect = (assistant: AssistantPickerItem) => {
		if (isExcluded(assistant)) {
			return;
		}

		const { groups: _groups, note: _note, ...picked } = assistant;
		dispatch('select', picked);
		show = false;
	};

	$: {
		if (show && !previousShow) {
			searchValue = '';
			selectedGroup = '';
			void loadMine();
		}

		if (!show && previousShow) {
			dispatch('close');
		}

		previousShow = show;
	}
</script>

<Modal bind:show size="lg">
	<div class="flex max-h-[80dvh] flex-col overflow-hidden">
		<div class="flex items-center justify-between border-b border-gray-100 px-5 py-4 dark:border-gray-800">
			<div>
				<div class="text-lg font-semibold text-gray-900 dark:text-gray-100">
					{$i18n.t('Select Assistant')}
				</div>
				<div class="mt-1 text-sm text-gray-500 dark:text-gray-400">
					{#if mode === 'activate'}
						{tr('在当前模型上套用这个助手的设定', "Apply the assistant's prompt on the current model")}
					{:else}
						{$i18n.t('Choose an assistant to add to your featured list.')}
					{/if}
				</div>
			</div>
			<button
				class="rounded-xl p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
				on:click={handleClose}
				aria-label={$i18n.t('Close')}
			>
				<XMark className="size-4" />
			</button>
		</div>

		<div class="flex flex-col gap-4 overflow-y-auto px-5 py-4">
			<div class="workspace-search">
				<Search className="size-4 text-gray-400" />
				<input
					class="ml-1 w-full bg-transparent text-sm outline-none"
					bind:value={searchValue}
					placeholder={$i18n.t('Search assistants...')}
				/>
			</div>

			<div class="flex flex-wrap gap-2">
				<button
					class="rounded-full px-3 py-1.5 text-xs transition {selectedGroup === ''
						? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
						: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'}"
					on:click={() => (selectedGroup = '')}
				>
					{$i18n.t('All')}
				</button>
				{#if mineItems.length > 0}
					<button
						class="rounded-full px-3 py-1.5 text-xs transition {selectedGroup === MINE_GROUP
							? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
							: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'}"
						data-picker-group="mine"
						on:click={() => (selectedGroup = MINE_GROUP)}
					>
						{tr('我的助手', 'My assistants')}
						<span class="ml-1 opacity-70">{mineItems.length}</span>
					</button>
				{/if}
				{#each groups as group}
					<button
						class="rounded-full px-3 py-1.5 text-xs transition {selectedGroup === group.name
							? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
							: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'}"
						on:click={() => (selectedGroup = group.name)}
					>
						{group.name}
						<span class="ml-1 opacity-70">{group.count}</span>
					</button>
				{/each}
			</div>

			{#if selectedGroup === '' || selectedGroup === MINE_GROUP}
				{#if mineLoading && mineItems.length === 0}
					<div class="flex justify-center py-2"><Spinner className="size-4" /></div>
				{:else if filteredMine.length > 0}
					<section data-picker-section="mine">
						<div class="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
							{tr('我的助手', 'My assistants')}
						</div>
						<div class="grid grid-cols-1 gap-3 md:grid-cols-2">
							{#each filteredMine as assistant (assistant.ref)}
								{@const disabled = isExcluded(assistant)}
								<button
									class="relative rounded-2xl border px-4 py-3 text-left transition {disabled
										? 'cursor-not-allowed border-emerald-200 bg-emerald-50/70 dark:border-emerald-800/60 dark:bg-emerald-950/20'
										: 'border-gray-200/70 bg-white hover:border-primary-200 hover:bg-primary-50/60 dark:border-gray-700/60 dark:bg-gray-900/50 dark:hover:border-primary-700/50 dark:hover:bg-primary-950/20'}"
									data-picker-item={assistant.ref}
									on:click={() => handleSelect(assistant)}
									{disabled}
								>
									{#if disabled}
										<div class="absolute right-3 top-3 flex size-6 items-center justify-center rounded-full bg-emerald-500 text-white">
											<Check className="size-3.5" strokeWidth="2.5" />
										</div>
									{/if}
									<div class="flex items-start gap-3 pr-8">
										<div class="text-xl leading-none">{assistant.emoji}</div>
										<div class="min-w-0 flex-1">
											<div class="text-sm font-medium text-gray-900 dark:text-gray-100">{assistant.name}</div>
											{#if assistant.description}
												<div class="mt-1 line-clamp-2 text-xs leading-5 text-gray-500 dark:text-gray-400">
													{assistant.description}
												</div>
											{/if}
											{#if assistant.note}
												<div class="mt-1 text-2xs text-gray-400 dark:text-gray-500">{assistant.note}</div>
											{/if}
										</div>
									</div>
								</button>
							{/each}
						</div>
					</section>
				{:else if mineError && selectedGroup === MINE_GROUP}
					<div class="text-xs text-red-600 dark:text-red-400">{mineError}</div>
				{/if}
			{/if}

			{#if filteredAssistants.length > 0}
				<section data-picker-section="templates">
					{#if selectedGroup === '' && filteredMine.length > 0}
						<div class="mb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
							{tr('内置模板', 'Built-in templates')}
						</div>
					{/if}
					<div class="grid grid-cols-1 gap-3 md:grid-cols-2">
						{#each filteredAssistants as assistant (assistant.ref)}
							{@const disabled = isExcluded(assistant)}
							<button
								class="relative rounded-2xl border px-4 py-3 text-left transition {disabled
									? 'cursor-not-allowed border-emerald-200 bg-emerald-50/70 dark:border-emerald-800/60 dark:bg-emerald-950/20'
									: 'border-gray-200/70 bg-white hover:border-primary-200 hover:bg-primary-50/60 dark:border-gray-700/60 dark:bg-gray-900/50 dark:hover:border-primary-700/50 dark:hover:bg-primary-950/20'}"
								data-picker-item={assistant.ref}
								on:click={() => handleSelect(assistant)}
								{disabled}
							>
								{#if disabled}
									<div class="absolute right-3 top-3 flex size-6 items-center justify-center rounded-full bg-emerald-500 text-white">
										<Check className="size-3.5" strokeWidth="2.5" />
									</div>
								{/if}

								<div class="flex items-start gap-3 pr-8">
									<div class="text-xl leading-none">{assistant.emoji}</div>
									<div class="min-w-0 flex-1">
										<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
											{assistant.name}
										</div>
										{#if assistant.description}
											<div class="mt-1 line-clamp-2 text-xs leading-5 text-gray-500 dark:text-gray-400">
												{assistant.description}
											</div>
										{/if}
									</div>
								</div>
							</button>
						{/each}
					</div>
				</section>
			{/if}

			{#if filteredAssistants.length === 0 && filteredMine.length === 0 && !mineLoading}
				<div class="rounded-2xl border border-dashed border-gray-200 px-4 py-10 text-center text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
					{$i18n.t('No assistants found')}
				</div>
			{/if}
		</div>
	</div>
</Modal>

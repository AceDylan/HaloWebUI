<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { WEBUI_NAME, settings } from '$lib/stores';
	import { translateWithDefault } from '$lib/i18n';
	import { builtinRef, workbenchHref, type WorkbenchTarget } from '$lib/utils/assistant-library';
	import {
		ensureFavoriteRefs,
		normalizeFavoriteRefs,
		sortFavoritesFirst,
		toggleFavorite
	} from '$lib/utils/assistant-favorites';
	import Star from '../icons/Star.svelte';

	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import ChatBubbleOval from '../icons/ChatBubbleOval.svelte';
	import Spinner from '../common/Spinner.svelte';
	import AssistantDetailModal from './AssistantDetailModal.svelte';

	import agentsData from '$lib/data/agents-zh.json';
	import {
		PENDING_ASSISTANT_STORAGE_KEY,
		toChatAssistantSnapshot
	} from '$lib/utils/chat-assistants';

	const i18n = getContext('i18n');
	const tr = (zh: string, en: string, options: Record<string, any> = {}) =>
		translateWithDefault($i18n, zh, en, options);

	// Starred templates (`builtin:<id>`) share the favourites with the user's assistants; the
	// home page's 精选助手 shows the first few.
	const FAVORITES_GROUP = '__favorites';
	$: favoriteRefs = normalizeFavoriteRefs($settings?.assistantFavorites);
	$: favoriteCount = agentsData.filter((agent: any) => favoriteRefs.includes(builtinRef(agent.id))).length;

	let loaded = false;
	let searchValue = '';
	let selectedGroup = '';

	// 详情弹窗
	let showDetailModal = false;
	let selectedAgent: any = null;

	// 按数量排序的分组列表
	const groupCounts: Record<string, number> = {};
	agentsData.forEach((agent: any) => {
		(agent.group || []).forEach((g: string) => {
			groupCounts[g] = (groupCounts[g] || 0) + 1;
		});
	});

	const groups = Object.entries(groupCounts)
		.sort((a, b) => b[1] - a[1])
		.map(([name, count]) => ({ name, count }));

	// 过滤助手
	$: filteredAgents = sortFavoritesFirst(
		agentsData.filter((agent: any) => {
			const matchesSearch =
				searchValue === '' ||
				agent.name.toLowerCase().includes(searchValue.toLowerCase()) ||
				(agent.description || '').toLowerCase().includes(searchValue.toLowerCase());
			const matchesGroup =
				selectedGroup === '' ||
				(selectedGroup === FAVORITES_GROUP
					? favoriteRefs.includes(builtinRef(agent.id))
					: (agent.group || []).includes(selectedGroup));
			return matchesSearch && matchesGroup;
		}),
		(agent: any) => builtinRef(agent.id),
		favoriteRefs
	);

	const toggleFavoriteHandler = async (agent: any) => {
		try {
			await toggleFavorite(builtinRef(agent.id));
		} catch (e) {
			toast.error(tr('收藏没有保存：{{error}}', 'Favourite not saved: {{error}}', { error: `${(e as any)?.message ?? e}` }));
		}
	};

	/** 「用于精答 / 协作 / 讨论」: the workbench opens with this template picked. */
	const useIn = (agent: any, target: WorkbenchTarget, fromModal = false) => {
		if (fromModal) showDetailModal = false;
		goto(workbenchHref(target, builtinRef(agent.id)));
	};

	// 打开助手详情
	const openDetail = (agent: any) => {
		selectedAgent = agent;
		showDetailModal = true;
	};

	// 添加到我的助手（跳转到模型创建页面）
	const addAssistant = (agent: any, fromModal = false) => {
		// 构造模型预填数据，跳转到创建页面让用户选择底层 LLM
		const modelData = {
			id: `assistant-${agent.id}`,
			name: agent.name,
			meta: {
				profile_image_url: null,
				description: agent.description || '',
				suggestion_prompts: null,
				// The library records where it came from (and its emoji).
				assistant: { source: builtinRef(agent.id), emoji: agent.emoji || '' }
			},
			params: {
				system: agent.prompt
			},
			preset: true
		};

		// 存储到 sessionStorage，创建页面会读取
		sessionStorage.model = JSON.stringify(modelData);

		if (fromModal) {
			showDetailModal = false;
		}

		// 跳转到模型创建页面
		goto('/workspace/models/create');
	};

	const startChat = (agent: any, fromModal = false) => {
		const assistant = toChatAssistantSnapshot(agent);
		if (!assistant) {
			return;
		}

		sessionStorage.setItem(PENDING_ASSISTANT_STORAGE_KEY, JSON.stringify(assistant));

		if (fromModal) {
			showDetailModal = false;
		}

		goto('/?fresh-chat=true');
	};

	onMount(() => {
		loaded = true;
		// The first visit moves the old featured list into the server favourites.
		void ensureFavoriteRefs();
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Assistant Templates')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div class="flex h-full flex-col gap-4 lg:flex-row">
		<!-- 左侧分类列表：桌面是一列导航行，手机是一行可横向滚动的标签 -->
		<nav class="w-full shrink-0 lg:w-52 lg:overflow-y-auto lg:pr-1" aria-label={$i18n.t('Assistant Templates')}>
			<div class="workspace-count-pill">
				{filteredAgents.length} {$i18n.t('Assistant Templates')}
			</div>
			<div class="-mx-1 mt-3 flex gap-1.5 overflow-x-auto px-1 pb-1 scrollbar-none lg:flex-col lg:gap-0.5 lg:overflow-visible">
				<button
					class="halo-cat-row"
					aria-current={selectedGroup === '' ? 'true' : undefined}
					on:click={() => (selectedGroup = '')}
				>
					<span class="truncate">{$i18n.t('All')}</span>
					<span class="halo-cat-count">{agentsData.length}</span>
				</button>

				{#if favoriteCount > 0}
					<button
						class="halo-cat-row"
						aria-current={selectedGroup === FAVORITES_GROUP ? 'true' : undefined}
						data-favorites-group
						on:click={() => (selectedGroup = FAVORITES_GROUP)}
					>
						<span class="truncate">{tr('已收藏', 'Favourites')}</span>
						<span class="halo-cat-count">{favoriteCount}</span>
					</button>
				{/if}

				{#each groups as group}
					<button
						class="halo-cat-row"
						aria-current={selectedGroup === group.name ? 'true' : undefined}
						on:click={() => (selectedGroup = group.name)}
					>
						<span class="truncate">{group.name}</span>
						<span class="halo-cat-count">{group.count}</span>
					</button>
				{/each}
			</div>
		</nav>

		<!-- 右侧内容区 -->
		<div class="min-w-0 flex-1 overflow-y-auto">
			<div class="space-y-4">
				<!-- 搜索栏 -->
				<div class="flex items-center gap-2">
					<div class="workspace-search flex-1">
						<Search className="size-4 text-gray-400" />
						<input
							class="w-full text-sm ml-1 bg-transparent outline-none"
							bind:value={searchValue}
							placeholder={$i18n.t('Search assistants...')}
						/>
					</div>
				</div>

				<!-- 助手标题 -->
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-2">
						<span class="font-display text-base font-semibold text-gray-900 dark:text-gray-100">
							{selectedGroup === FAVORITES_GROUP ? tr('已收藏', 'Favourites') : selectedGroup || $i18n.t('All')}
						</span>
						<span class="text-sm text-gray-400">{filteredAgents.length}</span>
					</div>
				</div>

				<!-- 助手网格 -->
				<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
					{#each filteredAgents as agent}
						<!-- svelte-ignore a11y-click-events-have-key-events -->
						<!-- svelte-ignore a11y-no-static-element-interactions -->
						<div
							class="glass-item group relative p-4 transition cursor-pointer"
							on:click={() => openDetail(agent)}
						>
							<div class="flex items-start gap-3">
								<div
									class="w-10 h-10 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-xl shrink-0"
								>
									{agent.emoji || '🤖'}
								</div>
								<div class="flex-1 min-w-0">
									<div class="font-medium text-sm line-clamp-1">{agent.name}</div>
									<div class="text-xs text-gray-500 line-clamp-2 mt-1">
										{agent.description || ''}
									</div>
								</div>
							</div>

							<div class="absolute top-2 right-2 flex items-center gap-1">
								<button
									class="p-1.5 rounded-lg transition {favoriteRefs.includes(builtinRef(agent.id))
										? 'text-amber-500 dark:text-amber-400'
										: 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700'}"
									on:click|stopPropagation={() => toggleFavoriteHandler(agent)}
									aria-pressed={favoriteRefs.includes(builtinRef(agent.id))}
									aria-label={favoriteRefs.includes(builtinRef(agent.id)) ? tr('取消收藏', 'Unfavourite') : tr('收藏', 'Favourite')}
									title={favoriteRefs.includes(builtinRef(agent.id)) ? tr('取消收藏', 'Unfavourite') : tr('收藏（显示在首页精选助手）', 'Favourite (shown on the home page)')}
									data-favorite={agent.id}
								>
									<Star className="size-4 {favoriteRefs.includes(builtinRef(agent.id)) ? 'fill-current' : ''}" strokeWidth="1.8" />
								</button>
								<button
									class="p-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
									on:click|stopPropagation={() => startChat(agent)}
									title={$i18n.t('Start Chat')}
								>
									<ChatBubbleOval className="size-4" strokeWidth="2.3" />
								</button>
								<button
									class="p-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
									on:click|stopPropagation={() => addAssistant(agent)}
									title={$i18n.t('Add to workspace')}
								>
									<Plus className="size-4" />
								</button>
							</div>

							<!-- 分组标签 -->
							{#if agent.group && agent.group.length > 0}
								<div class="flex flex-wrap gap-1 mt-3">
									{#each agent.group.slice(0, 3) as tag}
										<span
											class="px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500"
										>
											{tag}
										</span>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>

				{#if filteredAgents.length === 0}
					<div class="text-center py-12 text-gray-400">
						{$i18n.t('No assistants found')}
					</div>
				{/if}
			</div>
		</div>
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}

<AssistantDetailModal
	bind:show={showDetailModal}
	agent={selectedAgent}
	favorite={selectedAgent ? favoriteRefs.includes(builtinRef(selectedAgent.id)) : false}
	on:startChat={(e) => startChat(e.detail, true)}
	on:add={(e) => addAssistant(e.detail, true)}
	on:favorite={(e) => toggleFavoriteHandler(e.detail)}
	on:useIn={(e) => useIn(e.detail.agent, e.detail.target, true)}
/>

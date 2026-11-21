<script lang="ts">
	import type { Writable } from 'svelte/store';
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		WEBUI_NAME,
		banners,
		chatId,
		config,
		mobile,
		requestNewChat,
		selectedAssistantScene,
		settings,
		showArchivedChats,
		showControls,
		showSidebar,
		temporaryChatEnabled,
		user
	} from '$lib/stores';

	import { slide } from 'svelte/transition';
	import { page } from '$app/stores';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';

	import ShareChatModal from '../chat/ShareChatModal.svelte';
	import ModelSelector from '../chat/ModelSelector.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Dropdown from '../common/Dropdown.svelte';
	import Menu from '$lib/components/layout/Navbar/Menu.svelte';
	import UserMenu from '$lib/components/layout/Sidebar/UserMenu.svelte';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';
	import { modeLive, type ModeKey } from '$lib/components/scifi/mode-relay';
	import MenuLines from '../icons/MenuLines.svelte';
	import AdjustmentsHorizontal from '../icons/AdjustmentsHorizontal.svelte';

	import PencilSquare from '../icons/PencilSquare.svelte';
	import Banner from '../common/Banner.svelte';

	const i18n: Writable<any> = getContext('i18n');

	export let title: string = $WEBUI_NAME;
	export let shareEnabled: boolean = false;

	export let chat;
	export let history;
	export let selectedModels;
	export let multiModelDiscussionEnabled = false;
	export let maxDiscussionModels = 5;
	export let showModelSelector = true;
	/** Ticking several models in the menu: the chat hands its draft and conversation to 讨论台. */
	export let onDiscuss: ((models: string[]) => void) | null = null;
	/** Quick workbench switcher in the chat navbar: carries draft + files + conversation context. */
	export let onWorkbenchHandoff:
		| ((to: 'auto' | 'answer' | 'discuss' | 'teams' | 'studio' | 'video') => void)
		| null = null;
	export let hasDraftOrContext = false;
	/** One-line description of what will travel to the workbench (draft / attachments / turns). */
	export let handoffSummary = '';

	let showShareChatModal = false;
	let showDownloadChatModal = false;
	let showWorkbenchMenu = false;

	type WorkbenchKey = 'auto' | 'answer' | 'discuss' | 'teams' | 'studio' | 'video';
	$: studioAllowed =
		!!$config?.features?.enable_image_generation &&
		($user?.role === 'admin' || !!($user as any)?.permissions?.features?.image_generation);
	$: workbenches = (
		[
			{
				key: 'auto' as const,
				label: '自动分流',
				desc: '按问题自动选 Hermes、精答、讨论或协作',
				tone: 'bg-cyan-500/12 text-cyan-700 dark:bg-cyan-400/15 dark:text-cyan-300',
				show: true
			},
			{
				key: 'answer' as const,
				label: '精答',
				desc: '挑最合适的专家助手来答',
				tone: 'bg-amber-500/12 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300',
				show: true
			},
			{
				key: 'discuss' as const,
				label: '讨论台',
				desc: '多模型讨论，主持人写结论',
				tone: 'bg-indigo-500/12 text-indigo-700 dark:bg-indigo-400/15 dark:text-indigo-300',
				show: true
			},
			{
				key: 'teams' as const,
				label: '协作台',
				desc: 'AI 团队拆任务并行完成',
				tone: 'bg-blue-500/12 text-blue-700 dark:bg-blue-400/15 dark:text-blue-300',
				show: !!($config?.features as any)?.enable_agent_teams
			},
			{
				key: 'studio' as const,
				label: '生图工作台',
				desc: '提示词、参考图与图库',
				tone: 'bg-rose-500/12 text-rose-700 dark:bg-rose-400/15 dark:text-rose-300',
				show: studioAllowed
			},
			{
				key: 'video' as const,
				label: '视频工作台',
				desc: 'Hermes / runner 制作视频',
				tone: 'bg-fuchsia-500/12 text-fuchsia-700 dark:bg-fuchsia-400/15 dark:text-fuchsia-300',
				show: true
			}
		] as { key: WorkbenchKey; label: string; desc: string; tone: string; show: boolean }[]
	).filter((w) => w.show);
	$: totalLiveWorkbenches = workbenches.reduce((sum, w) => sum + ($modeLive[w.key as ModeKey] ?? 0), 0);
</script>

<ShareChatModal bind:show={showShareChatModal} chatId={$chatId} />

<nav
	class="sticky top-0 z-40 w-full py-1.5 -mb-8 flex flex-col items-center drag-region glass transition-colors duration-300"
>
	<div class="flex min-w-0 items-center w-full px-1.5">
		<div class=" flex min-w-0 max-w-full w-full mx-auto px-1 pt-0.5 bg-transparent">
			<div class="flex min-w-0 items-center w-full max-w-full">
				<div
					class="{$mobile
						? ''
						: 'hidden'} mr-1 self-start flex flex-none items-center text-gray-600 dark:text-gray-400"
				>
					<button
						id="sidebar-toggle-button"
						class="cursor-pointer halo-icon-btn"
						on:click={() => {
							showSidebar.set(!$showSidebar);
						}}
						aria-label={$i18n.t('Toggle Sidebar')}
					>
						<div class=" m-auto self-center">
							<MenuLines />
						</div>
					</button>
				</div>

				<div
					class="min-w-0 flex-1 overflow-hidden max-w-full py-0.5
			{$showSidebar ? 'ml-1' : ''}
			"
				>
					{#if showModelSelector}
						<ModelSelector
							bind:selectedModels
							bind:multiModelDiscussionEnabled
							{maxDiscussionModels}
							{onDiscuss}
							showSetDefault={!shareEnabled}
						/>
					{/if}
				</div>

				<!-- The open chat's title. Inside the Hub the browser tab belongs to the
				     Hub, so this is the only place it shows. -->
				{#if $chatId && title}
					<div
						class="hidden sm:flex min-w-0 max-w-[40%] shrink items-center self-start py-2 pl-2 pr-1 text-[13px] text-gray-500 dark:text-gray-400"
						{title}
						data-halo-navbar-chat-title
					>
						<span class="truncate">{title}</span>
					</div>
				{/if}

				<div class="self-start flex flex-none items-center gap-0.5 text-gray-600 dark:text-gray-400">
					{#if onWorkbenchHandoff && workbenches.length}
						<div class="flex shrink-0">
							<Dropdown bind:show={showWorkbenchMenu} side="bottom" align="end">
								<button
									type="button"
									class="halo-wb-nav-btn relative inline-flex h-9 items-center gap-1.5 rounded-full border border-gray-200/80 bg-white/75 px-2.5 text-xs font-medium text-gray-700 transition hover:border-gray-300 hover:bg-white hover:text-gray-950 dark:border-gray-700/60 dark:bg-white/[0.04] dark:text-gray-200 dark:hover:border-gray-600 dark:hover:bg-white/[0.08] dark:hover:text-white"
									aria-label="切换工作台"
									title={handoffSummary ||
										(hasDraftOrContext
											? '切换工作台（会带上当前草稿与对话背景，仅预填不会直接开跑）'
											: '快速切换工作台')}
									data-halo-navbar-workbenches
								>
									<svg
										class="size-3.5 shrink-0 text-cyan-600 dark:text-cyan-400"
										viewBox="0 0 20 20"
										fill="none"
										stroke="currentColor"
										stroke-width="1.75"
										stroke-linecap="round"
										stroke-linejoin="round"
										aria-hidden="true"
									>
										<rect x="2.75" y="2.75" width="5.5" height="5.5" rx="1.4" />
										<rect x="11.75" y="2.75" width="5.5" height="5.5" rx="1.4" />
										<rect x="2.75" y="11.75" width="5.5" height="5.5" rx="1.4" />
										<rect x="11.75" y="11.75" width="5.5" height="5.5" rx="1.4" />
									</svg>
									<span class="hidden sm:inline">工作台</span>
									{#if totalLiveWorkbenches > 0}
										<span
											class="inline-grid min-w-[1rem] h-4 place-items-center rounded-full bg-sky-500 px-1 font-mono text-[10px] font-semibold text-white"
											data-halo-navbar-workbenches-live>{totalLiveWorkbenches}</span
										>
									{/if}
								</button>

								<div slot="content">
									<DropdownMenu.Content
										class="w-72 rounded-2xl border border-gray-200/80 bg-white/95 p-1.5 shadow-xl backdrop-blur-xl dark:border-gray-700/60 dark:bg-gray-900/95 dark:text-white z-50"
										sideOffset={8}
										side="bottom"
										align="end"
										transition={flyAndScale}
									>
										<div class="px-2.5 pt-1 pb-1.5">
											<div class="flex items-center justify-between gap-2">
												<span class="text-[11px] font-semibold text-gray-500 dark:text-gray-400"
													>工作台</span
												>
												<span class="text-[10px] text-gray-400 dark:text-gray-500"
													>仅预填，不直接开跑</span
												>
											</div>
											{#if handoffSummary || hasDraftOrContext}
												<div
													class="mt-1 rounded-lg bg-cyan-500/10 px-2 py-1 text-[10.5px] leading-snug font-medium text-cyan-700 dark:bg-cyan-400/10 dark:text-cyan-300"
													data-halo-navbar-handoff-summary
												>
													{handoffSummary || '将带走当前草稿与对话背景（仅预填，不会立即开跑）'}
												</div>
											{/if}
										</div>
										<div class="flex flex-col gap-0.5">
											{#each workbenches as wb (wb.key)}
												{@const live = $modeLive[wb.key] ?? 0}
												<DropdownMenu.Item
													class="flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm cursor-pointer transition hover:bg-gray-100/90 dark:hover:bg-white/[0.06]"
													data-halo-navbar-workbench={wb.key}
													on:click={() => {
														showWorkbenchMenu = false;
														onWorkbenchHandoff?.(wb.key);
													}}
												>
													<span
														class="grid size-7 shrink-0 place-items-center rounded-lg {wb.tone}"
													>
														<SidebarModeIcon mode={wb.key} className="size-4" />
													</span>
													<div class="min-w-0 flex-1">
														<div class="flex items-center gap-1.5">
															<span
																class="truncate text-[13px] font-medium text-gray-900 dark:text-gray-100"
																>{wb.label}</span
															>
															{#if live > 0}
																<span
																	class="inline-grid min-w-[1rem] h-4 place-items-center rounded-full bg-sky-500/15 px-1 font-mono text-[10px] font-semibold text-sky-700 dark:text-sky-300"
																	>{live}</span
																>
															{/if}
														</div>
														<div
															class="truncate text-[11px] text-gray-500 dark:text-gray-400"
														>
															{wb.desc}
														</div>
													</div>
													<span class="text-xs text-gray-400" aria-hidden="true">↗</span>
												</DropdownMenu.Item>
											{/each}
										</div>
									</DropdownMenu.Content>
								</div>
							</Dropdown>
						</div>
					{/if}
					<!-- <div class="md:hidden flex self-center w-[1px] h-5 mx-2 bg-gray-300 dark:bg-stone-700" /> -->
					{#if shareEnabled && chat && (chat.id || $temporaryChatEnabled)}
						<!-- Dropdown's trigger is min-w-0, which let this row squeeze it to 16px
						     while the 36px button kept drawing over "Controls". -->
						<div class="flex shrink-0">
							<Menu
								{chat}
								{shareEnabled}
								shareHandler={() => {
									showShareChatModal = !showShareChatModal;
								}}
								downloadHandler={() => {
									showDownloadChatModal = !showDownloadChatModal;
								}}
							>
								<button
									class="cursor-pointer halo-icon-btn"
									id="chat-context-menu-button"
									aria-label={$i18n.t('Chat Menu')}
								>
									<div class=" m-auto self-center">
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="1.5"
											stroke="currentColor"
											class="size-5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M6.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM18.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
											/>
										</svg>
									</div>
								</button>
							</Menu>
						</div>
					{/if}

					<Tooltip content={$i18n.t('Controls')}>
						<button
							class="cursor-pointer halo-icon-btn"
							on:click={async () => {
								await showControls.set(!$showControls);
							}}
							aria-label={$i18n.t('Controls')}
						>
							<div class=" m-auto self-center">
								<AdjustmentsHorizontal className=" size-5" strokeWidth="0.5" />
							</div>
						</button>
					</Tooltip>

					<Tooltip content={$i18n.t('New Chat')}>
						<button
							id="new-chat-button"
							class="{$mobile ? 'hidden' : 'flex'} {$showSidebar
								? 'md:hidden'
								: ''} cursor-pointer halo-icon-btn"
							on:click={() => {
								selectedAssistantScene.set(null);
								requestNewChat({ source: 'navbar' });
							}}
							aria-label={$i18n.t('New Chat')}
						>
							<div class=" m-auto self-center">
								<PencilSquare className=" size-5" strokeWidth="2" />
							</div>
						</button>
					</Tooltip>

					{#if $user !== undefined && $user !== null}
						<UserMenu
							className="max-w-[200px]"
							role={$user?.role}
							on:show={(e) => {
								if (e.detail === 'archived-chat') {
									showArchivedChats.set(true);
								}
							}}
							let:builder
						>
							<button
								{...builder}
								use:builder.action
								class="select-none flex rounded-full p-1 w-full hover:ring-2 hover:ring-gray-200 dark:hover:ring-gray-700 transition"
								aria-label={$i18n.t('User Menu')}
							>
								<div class=" self-center">
									<img
										src={$user?.profile_image_url}
										class="size-6 object-cover rounded-full"
										alt="User profile"
										draggable="false"
									/>
								</div>
							</button>
						</UserMenu>
					{/if}
				</div>
			</div>
		</div>
	</div>

	{#if !history.currentId && !$chatId && ($banners.length > 0 || ($config?.license_metadata?.type ?? null) === 'trial' || (($config?.license_metadata?.seats ?? null) !== null && $config?.user_count > $config?.license_metadata?.seats))}
		<div class=" w-full z-30 mt-5">
			<div class=" flex flex-col gap-1 w-full">
				{#if ($config?.license_metadata?.type ?? null) === 'trial'}
					<Banner
						banner={{
							type: 'info',
							title: 'Trial License',
							content: $i18n.t(
								'You are currently using a trial license. Please contact support to upgrade your license.'
							)
						}}
					/>
				{/if}

				{#if ($config?.license_metadata?.seats ?? null) !== null && $config?.user_count > $config?.license_metadata?.seats}
					<Banner
						banner={{
							type: 'error',
							title: 'License Error',
							content: $i18n.t(
								'Exceeded the number of seats in your license. Please contact support to increase the number of seats.'
							)
						}}
					/>
				{/if}

				{#each $banners.filter( (b) => (b.dismissible ? !JSON.parse(localStorage.getItem('dismissedBannerIds') ?? '[]').includes(b.id) : true) ) as banner}
					<Banner
						{banner}
						on:dismiss={(e) => {
							const bannerId = e.detail;

							localStorage.setItem(
								'dismissedBannerIds',
								JSON.stringify(
									[
										bannerId,
										...JSON.parse(localStorage.getItem('dismissedBannerIds') ?? '[]')
									].filter((id) => $banners.find((b) => b.id === id))
								)
							);
						}}
					/>
				{/each}
			</div>
		</div>
	{/if}
</nav>

<style>
	:global(html.halo-scifi) .halo-wb-nav-btn {
		border-color: rgb(8 145 178 / 0.22);
	}
	:global(html.halo-scifi.dark) .halo-wb-nav-btn {
		border-color: rgb(94 231 255 / 0.18);
		background: rgb(6 9 20 / 0.55);
		box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.04);
	}
	:global(html.halo-scifi) .halo-wb-nav-btn:hover {
		border-color: var(--scifi-cyan);
		box-shadow: 0 0 16px -4px var(--scifi-glow);
	}
</style>

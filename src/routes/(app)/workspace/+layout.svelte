<script lang="ts">
	import type { Writable } from 'svelte/store';
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, config, showSidebar, user, mobile } from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import WorkspaceHero from '$lib/components/workspace/shell/WorkspaceHero.svelte';
	import {
		getActiveWorkspaceTab,
		getVisibleWorkspaceTabs
	} from '$lib/components/workspace/shell/meta';

	const i18n: Writable<any> = getContext('i18n');

	let loaded = false;
	let activeTab = null;
	let visibleTabs = [];

	onMount(async () => {
		if ($user?.role !== 'admin') {
			if ($page.url.pathname.includes('/models') && !$user?.permissions?.workspace?.models) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/knowledge') &&
				!$user?.permissions?.workspace?.knowledge
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/prompts') &&
				!$user?.permissions?.workspace?.prompts
			) {
				goto('/');
			} else if ($page.url.pathname.includes('/tools') && !$user?.permissions?.workspace?.tools) {
				goto('/');
			} else if ($page.url.pathname.includes('/functions')) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/images') &&
				!$user?.permissions?.features?.image_generation
			) {
				goto('/');
			}
		}

		loaded = true;
	});

	// The image studio is one of the chat's modes (sidebar: 讨论 / 协作 / 生图): it gets a mode page's
	// header, like 讨论台 and 协作台, instead of the workspace's tab strip.
	$: studio = $page.url.pathname.startsWith('/workspace/images');
	$: visibleTabs = getVisibleWorkspaceTabs({ user: $user, config: $config }, $page.url.pathname);
	$: activeTab = getActiveWorkspaceTab($page.url.pathname, visibleTabs);
</script>

<svelte:head>
	<title>
		{studio ? '生图工作台' : activeTab ? $i18n.t(activeTab.labelKey) : $i18n.t('Workspace')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div class="relative flex flex-col w-full h-screen max-h-[100dvh] max-w-full">
		<nav data-halo-layer="0" class="px-2.5 pt-1 backdrop-blur-xl drag-region">
			<div class="flex items-center gap-1">
				<div class="{$mobile ? '' : 'hidden'} self-center flex flex-none items-center">
					<button
						id="sidebar-toggle-button"
						class="cursor-pointer halo-icon-btn !p-1.5"
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

				<div class="halo-crumb flex items-center px-1 py-1">
					{studio ? '生图工作台' : $i18n.t('Workspace')}
				</div>
			</div>
		</nav>

		<div class="pb-1 px-[18px] flex-1 max-h-full overflow-y-auto" id="workspace-container">
			<div class="max-w-6xl mx-auto flex min-h-full flex-col gap-6 pb-4">
				{#if studio}
					<header class="flex flex-col gap-2 pt-4 sm:pt-8" data-studio-hero>
						<div class="flex items-center gap-2">
							<span class="text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-500 dark:text-gray-400">Halo Studio</span>
							<span class="h-3 w-px bg-gray-300 dark:bg-gray-700" aria-hidden="true" />
							<span class="text-xs text-gray-500 dark:text-gray-400">生图</span>
						</div>
						<h2 class="font-display text-[26px] font-semibold leading-[1.15] text-gray-950 sm:text-[32px] dark:text-white">把想法画出来</h2>
						<p class="max-w-2xl text-sm leading-relaxed text-gray-500 dark:text-gray-400">
							写提示词、加参考图、套风格模板；对话里生成的图也会自动进图库，随时拿回来接着改。
						</p>
					</header>
				{:else}
					<WorkspaceHero {activeTab} tabs={visibleTabs} pathname={$page.url.pathname} />
				{/if}
				<div data-halo-layer="2" class="flex-1 min-h-0">
					<slot />
				</div>
			</div>
		</div>
	</div>
{/if}

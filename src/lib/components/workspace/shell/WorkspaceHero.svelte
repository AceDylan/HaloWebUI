<script lang="ts">
	import { getContext } from 'svelte';

	import type { Writable } from 'svelte/store';
	import type { WorkspaceTabMeta } from './meta';

	const i18n: Writable<any> = getContext('i18n');

	export let activeTab: WorkspaceTabMeta | null = null;
	export let tabs: WorkspaceTabMeta[] = [];
	export let pathname = '';

	const swapTabs = (
		items: WorkspaceTabMeta[],
		firstKey: WorkspaceTabMeta['key'],
		secondKey: WorkspaceTabMeta['key']
	) => {
		const reordered = [...items];
		const firstIndex = reordered.findIndex((tab) => tab.key === firstKey);
		const secondIndex = reordered.findIndex((tab) => tab.key === secondKey);

		if (firstIndex === -1 || secondIndex === -1) return reordered;

		[reordered[firstIndex], reordered[secondIndex]] = [
			reordered[secondIndex],
			reordered[firstIndex]
		];

		return reordered;
	};

	const swapWorkspaceHeroTabs = (items: WorkspaceTabMeta[]) => {
		let reordered = swapTabs(items, 'tools', 'images');
		reordered = swapTabs(reordered, 'tools', 'terminal');
		reordered = swapTabs(reordered, 'images', 'skills');
		return reordered;
	};

	const getWorkspaceHeroTabLabel = (tab: WorkspaceTabMeta | null) => {
		if (!tab) return '';
		if (tab.key !== 'terminal') return $i18n.t(tab.labelKey);

		const filesLabel = $i18n.t('Files');
		const terminalLabel = $i18n.t('Terminal');
		const useCompactJoin = /[\u3040-\u30ff\u3400-\u9fff]/.test(`${filesLabel}${terminalLabel}`);

		return `${filesLabel}${useCompactJoin ? '' : ' '}${terminalLabel}`;
	};

	$: heroTabs = swapWorkspaceHeroTabs(tabs);
</script>

{#if activeTab}
	<!-- Page header + tab switcher in one card. The per-page toolbar (count, search, create)
	     sits directly on the page below; the list is not wrapped in another card. -->
	<section class="glass-section p-4 sm:p-5">
		<div class="@container">
			<div
				class="flex flex-col gap-4 @[64rem]:flex-row @[64rem]:items-center @[64rem]:justify-between"
			>
				<div class="min-w-0 @[64rem]:flex-1">
					<div class="flex items-start gap-3">
						<div class="glass-icon-badge shrink-0 {activeTab.badgeColor}">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="currentColor"
								class="size-[18px] {activeTab.iconColor}"
							>
								{#each activeTab.iconPaths as pathD}
									<path fill-rule="evenodd" d={pathD} clip-rule="evenodd" />
								{/each}
							</svg>
						</div>
						<div class="min-w-0 max-w-3xl">
							<div class="text-base font-semibold text-gray-800 dark:text-gray-100">
								{getWorkspaceHeroTabLabel(activeTab)}
							</div>
							<p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t(activeTab.descKey)}
							</p>
						</div>
					</div>
				</div>

				<nav
					class="-mx-4 flex max-w-full gap-1 overflow-x-auto px-4 scrollbar-none scroll-fade-x-cq sm:-mx-5 sm:px-5 @[64rem]:mx-0 @[64rem]:flex-wrap @[64rem]:justify-end @[64rem]:overflow-visible @[64rem]:px-0"
					aria-label={$i18n.t('Workspace')}
				>
					{#each heroTabs as tab (tab.key)}
						{@const active = tab.activeMatch.some((prefix) => pathname.startsWith(prefix))}
						<a
							class="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] font-medium transition-all {active
								? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-fg)]'
								: 'text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800/60 dark:hover:text-gray-200'}"
							href={tab.href}
							aria-current={active ? 'page' : undefined}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="currentColor"
								class="size-4"
							>
								{#each tab.iconPaths as pathD}
									<path fill-rule="evenodd" d={pathD} clip-rule="evenodd" />
								{/each}
							</svg>
							<span>{getWorkspaceHeroTabLabel(tab)}</span>
						</a>
					{/each}
				</nav>
			</div>
		</div>
	</section>
{/if}

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
	<!-- Page title + tab strip, set straight on the panel (no card): the per-page toolbar
	     (count, search, create) and the list follow below. -->
	<header class="halo-page-head @container">
		<div class="flex items-start gap-3.5">
			<div class="halo-page-icon shrink-0 {activeTab.badgeColor}">
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
				<h1 class="halo-page-title">{getWorkspaceHeroTabLabel(activeTab)}</h1>
				<p class="halo-page-desc">{$i18n.t(activeTab.descKey)}</p>
			</div>
		</div>
		<nav class="halo-tabs scrollbar-none scroll-fade-x-cq" aria-label={$i18n.t('Workspace')}>
			{#each heroTabs as tab (tab.key)}
				{@const active = tab.activeMatch.some((prefix) => pathname.startsWith(prefix))}
				<a class="halo-tab" href={tab.href} aria-current={active ? 'page' : undefined}>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-4">
						{#each tab.iconPaths as pathD}
							<path fill-rule="evenodd" d={pathD} clip-rule="evenodd" />
						{/each}
					</svg>
					<span>{getWorkspaceHeroTabLabel(tab)}</span>
				</a>
			{/each}
		</nav>
	</header>
{/if}

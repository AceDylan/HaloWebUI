<script lang="ts">
	import { getContext } from 'svelte';

	import type { Writable } from 'svelte/store';
	import type { WorkspaceTabMeta } from './meta';

	const i18n: Writable<any> = getContext('i18n');

	export let activeTab: WorkspaceTabMeta | null = null;

	const getWorkspaceHeroTabLabel = (tab: WorkspaceTabMeta | null) =>
		tab ? $i18n.t(tab.labelKey) : '';
</script>

{#if activeTab}
	<!-- Page title, set straight on the panel (no card): the per-page toolbar (count, search,
	     create) and the list follow below. The pages are reached from the sidebar (助手 / 提示词). -->
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
	</header>
{/if}

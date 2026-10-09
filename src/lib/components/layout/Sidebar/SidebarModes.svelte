<script lang="ts">
	import { page } from '$app/stores';
	import { config, user } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import TeamsBadge from '$lib/components/teams/TeamsBadge.svelte';
	import DiscussBadge from '$lib/components/discuss/DiscussBadge.svelte';
	import AnswerBadge from '$lib/components/answer/AnswerBadge.svelte';
	import SidebarModeIcon from './SidebarModeIcon.svelte';
	import { isAt, modeDestinations } from '$lib/utils/destinations';

	/**
	 * The chat's modes, next to 新对话: 精答, 讨论 (讨论台), 协作 (协作台), 生图 (the image studio). One row of
	 * equal tiles in the open sidebar, a column of icons in the collapsed one.
	 */
	export let compact = false;
	export let iconButtonClass = '';
	export let onNavigate: () => void = () => {};

	$: path = $page?.url?.pathname ?? '';
	$: modes = modeDestinations($config, $user).map((mode) => ({ ...mode, active: isAt(mode, path) }));
</script>

{#if compact}
	{#each modes as mode (mode.key)}
		<Tooltip content={mode.title}>
			<a
				class="{iconButtonClass} relative"
				href={mode.href}
				aria-label={mode.title}
				aria-current={mode.active ? 'page' : undefined}
				draggable="false"
				on:click={onNavigate}
				data-sidebar-mode={mode.key}
			>
				<SidebarModeIcon mode={mode.key} />
				{#if mode.key === 'teams'}<TeamsBadge compact />{:else if mode.key === 'discuss'}<DiscussBadge compact />{:else if mode.key === 'answer'}<AnswerBadge compact />{/if}
			</a>
		</Tooltip>
	{/each}
{:else if modes.length}
	<div
		class="mb-1.5 grid gap-1 px-2 text-gray-700 dark:text-gray-200"
		style="grid-template-columns: repeat({modes.length}, minmax(0, 1fr))"
		data-sidebar-modes
	>
		{#each modes as mode (mode.key)}
			<a
				class="halo-mode-tile relative flex min-w-0 flex-col items-center gap-1 rounded-xl px-1 pt-2 pb-1.5 text-[12px] font-medium transition-colors hover:bg-gray-100 dark:hover:bg-gray-850"
				class:is-active={mode.active}
				href={mode.href}
				title={mode.title}
				aria-current={mode.active ? 'page' : undefined}
				draggable="false"
				on:click={onNavigate}
				data-sidebar-mode={mode.key}
				data-sidebar-answer={mode.key === 'answer' ? '' : undefined}
				data-sidebar-discuss={mode.key === 'discuss' ? '' : undefined}
				data-sidebar-teams={mode.key === 'teams' ? '' : undefined}
				data-sidebar-studio={mode.key === 'studio' ? '' : undefined}
			>
				<SidebarModeIcon mode={mode.key} className="size-[18px]" />
				<span class="truncate">{mode.label}</span>
				{#if mode.key === 'teams'}<TeamsBadge compact />{:else if mode.key === 'discuss'}<DiscussBadge compact />{:else if mode.key === 'answer'}<AnswerBadge compact />{/if}
			</a>
		{/each}
	</div>
{/if}

<style>
	.halo-mode-tile.is-active {
		background: rgb(127 127 127 / 0.12);
	}
</style>

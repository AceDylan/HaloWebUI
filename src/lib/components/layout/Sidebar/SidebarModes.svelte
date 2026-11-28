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
	export let dense = false;
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
		class="{dense ? 'mb-1' : 'mb-1.5'} grid gap-1 px-2 text-gray-700 dark:text-gray-200"
		style="grid-template-columns: repeat({modes.length}, minmax(0, 1fr))"
		data-sidebar-modes
		data-dense={dense ? 'true' : undefined}
	>
		{#each modes as mode (mode.key)}
			<a
				class="halo-mode-tile relative flex min-w-0 flex-col items-center rounded-xl border border-transparent px-1 font-medium transition hover:bg-gray-100/90 dark:hover:bg-gray-850 {dense
					? 'gap-0.5 pt-1.5 pb-1 text-[11px] leading-tight'
					: 'gap-1 pt-2 pb-1.5 text-[11.5px]'}"
				class:is-active={mode.active}
				data-accent={mode.key}
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
				<SidebarModeIcon
					mode={mode.key}
					className="halo-mode-tile__icon {dense ? 'size-4' : 'size-[17px]'}"
				/>
				<span class="truncate">{mode.label}</span>
				{#if mode.key === 'teams'}<TeamsBadge compact />{:else if mode.key === 'discuss'}<DiscussBadge compact />{:else if mode.key === 'answer'}<AnswerBadge compact />{/if}
			</a>
		{/each}
	</div>
{/if}

<style>
	.halo-mode-tile {
		--tile-hue: 215;
	}
	.halo-mode-tile[data-accent='answer'] {
		--tile-hue: 26;
	}
	.halo-mode-tile[data-accent='discuss'] {
		--tile-hue: 245;
	}
	.halo-mode-tile[data-accent='teams'] {
		--tile-hue: 222;
	}
	.halo-mode-tile[data-accent='studio'] {
		--tile-hue: 342;
	}
	.halo-mode-tile[data-accent='video'] {
		--tile-hue: 288;
	}
	.halo-mode-tile:hover :global(.halo-mode-tile__icon),
	.halo-mode-tile.is-active :global(.halo-mode-tile__icon) {
		color: hsl(var(--tile-hue) 78% 46%);
	}
	:global(.dark) .halo-mode-tile:hover :global(.halo-mode-tile__icon),
	:global(.dark) .halo-mode-tile.is-active :global(.halo-mode-tile__icon) {
		color: hsl(var(--tile-hue) 88% 72%);
	}
	.halo-mode-tile.is-active {
		background: hsl(var(--tile-hue) 85% 56% / 0.1);
		border-color: hsl(var(--tile-hue) 80% 52% / 0.22);
	}
	:global(.dark) .halo-mode-tile.is-active {
		background: hsl(var(--tile-hue) 85% 60% / 0.14);
		border-color: hsl(var(--tile-hue) 85% 68% / 0.24);
	}
</style>

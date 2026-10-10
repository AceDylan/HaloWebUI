<script lang="ts">
	import { page } from '$app/stores';
	import { user } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SidebarModeIcon from './SidebarModeIcon.svelte';
	import { isAt, libraryDestinations } from '$lib/utils/destinations';

	/**
	 * What used to be the workspace, now that the image studio is a mode of its own: 助手 (my
	 * assistants | built-in templates), 提示词 and (admins) 定时 — Hermes' scheduled jobs — side by
	 * side under the modes in the open sidebar, icons in the collapsed one. Users without the
	 * assistants page get the templates.
	 */
	export let compact = false;
	export let actionItemClass = '';
	export let iconButtonClass = '';
	export let onNavigate: () => void = () => {};

	$: path = $page?.url?.pathname ?? '';
	$: links = libraryDestinations($user).map((link) => ({ ...link, active: isAt(link, path) }));
</script>

{#if compact}
	{#each links as link (link.key)}
		<Tooltip content={link.title}>
			<a
				class={iconButtonClass}
				href={link.href}
				aria-label={link.title}
				aria-current={link.active ? 'page' : undefined}
				draggable="false"
				on:click={onNavigate}
				data-sidebar-library={link.key}
			>
				<SidebarModeIcon mode={link.key} />
			</a>
		</Tooltip>
	{/each}
{:else if links.length}
	<div
		class="grid gap-1 px-2 text-gray-700 dark:text-gray-200"
		style="grid-template-columns: repeat({links.length}, minmax(0, 1fr))"
		data-sidebar-library-row
	>
		{#each links as link (link.key)}
			<a
				class="{actionItemClass} halo-library-chip min-w-0"
				href={link.href}
				title={link.title}
				aria-current={link.active ? 'page' : undefined}
				draggable="false"
				on:click={onNavigate}
				data-sidebar-library={link.key}
			>
				<SidebarModeIcon mode={link.key} />
				<span class="truncate">{link.label}</span>
			</a>
		{/each}
	</div>
{/if}

<style>
	/* Three to a row in a ~240px sidebar: the full-width row's padding, gap and 18px icon left
	   「提示词」 room for one character, so the chips centre a smaller icon and drop the slack. */
	.halo-library-chip {
		justify-content: center;
		gap: 0.375rem;
		padding: 0.4375rem 0.375rem;
		font-size: 0.8125rem;
		font-weight: 500;
	}
	.halo-library-chip :global(svg) {
		width: 1rem;
		height: 1rem;
	}
</style>

<script lang="ts">
	import { page } from '$app/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SidebarModeIcon from './SidebarModeIcon.svelte';
	export let compact = false;
	export let buttonClass = '';
	export let onNavigate: () => void = () => {};
	$: active = $page?.url?.pathname?.startsWith('/auto');
</script>

{#if compact}
	<Tooltip content="自动分流工作台"
		><a
			href="/auto"
			class={buttonClass}
			aria-label="自动分流工作台"
			aria-current={active ? 'page' : undefined}
			on:click={onNavigate}
			data-sidebar-auto><SidebarModeIcon mode="auto" /></a
		></Tooltip
	>
{:else}
	<div class="mb-1.5 px-2 text-gray-700 dark:text-gray-200" data-sidebar-auto-row>
		<a
			href="/auto"
			class={buttonClass}
			class:halo-auto-active={active}
			aria-current={active ? 'page' : undefined}
			on:click={onNavigate}
			data-sidebar-auto
		>
			<SidebarModeIcon mode="auto" /><span class="text-sm font-medium whitespace-nowrap"
				>自动分流工作台</span
			>
		</a>
	</div>
{/if}

<style>
	.halo-auto-active {
		background: rgb(6 182 212 / 0.1);
	}
</style>

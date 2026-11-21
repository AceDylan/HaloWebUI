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
			class="{buttonClass} halo-auto-row border border-cyan-500/15 bg-cyan-500/[0.04] hover:border-cyan-500/30 hover:bg-cyan-500/[0.08] dark:border-cyan-400/15 dark:bg-cyan-400/[0.05] dark:hover:border-cyan-400/30 dark:hover:bg-cyan-400/[0.1]"
			class:halo-auto-active={active}
			aria-current={active ? 'page' : undefined}
			on:click={onNavigate}
			data-sidebar-auto
		>
			<span class="text-cyan-600 dark:text-cyan-400 shrink-0"><SidebarModeIcon mode="auto" /></span>
			<span class="text-sm font-medium whitespace-nowrap">自动分流工作台</span>
			<span class="ml-auto rounded-full bg-cyan-500/10 px-1.5 py-px text-[10px] font-medium text-cyan-700 dark:text-cyan-300">智能</span>
		</a>
	</div>
{/if}

<style>
	.halo-auto-active {
		background: rgb(6 182 212 / 0.14);
		border-color: rgb(6 182 212 / 0.35);
	}
</style>

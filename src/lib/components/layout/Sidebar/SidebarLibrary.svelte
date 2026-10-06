<script lang="ts">
	import { page } from '$app/stores';
	import { user } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SidebarModeIcon from './SidebarModeIcon.svelte';

	/**
	 * What used to be the workspace, now that the image studio is a mode of its own: 助手 (my
	 * assistants | built-in templates) and 提示词, side by side under the modes in the open sidebar,
	 * two icons in the collapsed one. Users without the assistants page get the templates.
	 */
	export let compact = false;
	export let actionItemClass = '';
	export let iconButtonClass = '';
	export let onNavigate: () => void = () => {};

	$: path = $page?.url?.pathname ?? '';
	$: perms = $user?.permissions?.workspace ?? {};
	$: admin = $user?.role === 'admin';
	$: links = [
		{
			key: 'assistants',
			href: admin || perms.models ? '/workspace/models' : '/workspace/assistants',
			label: '助手',
			title: '助手：我的助手和内置模板，精答、讨论台、协作台都从这里挑',
			active: path.startsWith('/workspace/models') || path.startsWith('/workspace/assistants'),
			show: admin || perms.models || perms.knowledge || perms.prompts || perms.tools
		},
		{
			key: 'prompts',
			href: '/workspace/prompts',
			label: '提示词',
			title: '提示词：输入框里用 / 调出的常用提示词',
			active: path.startsWith('/workspace/prompts'),
			show: admin || perms.prompts
		}
	].filter((link) => link.show);
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
				class="{actionItemClass} min-w-0"
				href={link.href}
				title={link.title}
				aria-current={link.active ? 'page' : undefined}
				draggable="false"
				on:click={onNavigate}
				data-sidebar-library={link.key}
			>
				<SidebarModeIcon mode={link.key} />
				<span class="truncate text-sm font-medium">{link.label}</span>
			</a>
		{/each}
	</div>
{/if}

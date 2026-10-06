<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import { getContext } from 'svelte';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Tags from '$lib/components/chat/Tags.svelte';
	import Share from '$lib/components/icons/Share.svelte';
	import ArchiveBox from '$lib/components/icons/ArchiveBox.svelte';
	import DocumentDuplicate from '$lib/components/icons/DocumentDuplicate.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import ArrowUpCircle from '$lib/components/icons/ArrowUpCircle.svelte';

	import { MessageSquare, MessagesSquare, Users, History, EyeOff, Eye, ArchiveRestore } from 'lucide-svelte';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';

	import { config } from '$lib/stores';
	import { translateWithDefault } from '$lib/i18n';
	import type { WorkbenchTarget } from '$lib/utils/assistant-library';

	const i18n = getContext('i18n');
	const tr = (zh: string, en: string) => translateWithDefault($i18n, zh, en);

	export let user;
	export let model;

	export let shareHandler: Function;
	export let cloneHandler: Function;
	export let exportHandler: Function;

	export let hideHandler: Function;
	export let deleteHandler: Function;
	export let onClose: Function;

	// Assistant actions (left out when a handler is not given).
	/** Kept out of the model menus (meta.hidden). */
	export let hidden = false;
	export let archived = false;
	export let canWrite = false;
	export let startChatHandler: Function | null = null;
	export let useInHandler: ((target: WorkbenchTarget) => void) | null = null;
	export let versionsHandler: Function | null = null;
	export let archiveHandler: Function | null = null;

	const itemClass =
		'flex gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md';

	let show = false;
</script>

<Dropdown
	bind:show
	on:change={(e) => {
		if (e.detail === false) {
			onClose();
		}
	}}
>
	<Tooltip content={$i18n.t('More')}>
		<slot />
	</Tooltip>

	<div slot="content">
		<DropdownMenu.Content
			class="w-full max-w-[220px] rounded-xl px-1 py-1.5 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-sm"
			sideOffset={-2}
			side="bottom"
			align="start"
			transition={flyAndScale}
		>
			{#if !archived && startChatHandler}
				<DropdownMenu.Item class={itemClass} data-model-action="chat" on:click={() => startChatHandler?.()}>
					<MessageSquare class="size-4" strokeWidth={2} />
					<div class="flex items-center">{tr('开始对话', 'Start chat')}</div>
				</DropdownMenu.Item>
			{/if}
			{#if !archived && useInHandler}
				<DropdownMenu.Item class={itemClass} data-model-action="answer" on:click={() => useInHandler?.('answer')}>
					<SidebarModeIcon mode="answer" className="size-4" />
					<div class="flex items-center">{tr('用于精答', 'Use in Answer')}</div>
				</DropdownMenu.Item>
				{#if $config?.features?.enable_agent_teams}
					<DropdownMenu.Item class={itemClass} data-model-action="teams" on:click={() => useInHandler?.('teams')}>
						<Users class="size-4" strokeWidth={2} />
						<div class="flex items-center">{tr('用于协作', 'Use in Team')}</div>
					</DropdownMenu.Item>
				{/if}
				<DropdownMenu.Item class={itemClass} data-model-action="discuss" on:click={() => useInHandler?.('discuss')}>
					<MessagesSquare class="size-4" strokeWidth={2} />
					<div class="flex items-center">{tr('用于讨论', 'Use in Discussion')}</div>
				</DropdownMenu.Item>
			{/if}
			{#if versionsHandler}
				<DropdownMenu.Item class={itemClass} data-model-action="versions" on:click={() => versionsHandler?.()}>
					<History class="size-4" strokeWidth={2} />
					<div class="flex items-center">{tr('版本记录', 'Versions')}</div>
				</DropdownMenu.Item>
			{/if}
			{#if startChatHandler || useInHandler || versionsHandler}
				<hr class="border-gray-100 dark:border-gray-850 my-1" />
			{/if}

			{#if canWrite && !archived}
				<DropdownMenu.Item class={itemClass} data-model-action="hide" on:click={() => hideHandler()}>
					{#if hidden}
						<Eye class="size-4" strokeWidth={2} />
						<div class="flex items-center">{tr('在模型菜单中显示', 'Show in model menus')}</div>
					{:else}
						<EyeOff class="size-4" strokeWidth={2} />
						<div class="flex items-center">{tr('在模型菜单中隐藏', 'Hide from model menus')}</div>
					{/if}
				</DropdownMenu.Item>
			{/if}

			{#if $config?.features.enable_community_sharing}
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm  font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800  rounded-md"
					on:click={() => {
						shareHandler();
					}}
				>
					<Share />
					<div class="flex items-center">{$i18n.t('Share')}</div>
				</DropdownMenu.Item>
			{/if}

			<DropdownMenu.Item
				class="flex gap-2 items-center px-3 py-2 text-sm  font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
				on:click={() => {
					cloneHandler();
				}}
			>
				<DocumentDuplicate />

				<div class="flex items-center">{$i18n.t('Clone')}</div>
			</DropdownMenu.Item>

			<DropdownMenu.Item
				class="flex gap-2 items-center px-3 py-2 text-sm  font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
				on:click={() => {
					exportHandler();
				}}
			>
				<ArrowDownTray />

				<div class="flex items-center">{$i18n.t('Export')}</div>
			</DropdownMenu.Item>

			<hr class="border-gray-100 dark:border-gray-850 my-1" />

			{#if canWrite && archiveHandler}
				<DropdownMenu.Item class={itemClass} data-model-action="archive" on:click={() => archiveHandler?.()}>
					{#if archived}
						<ArchiveRestore class="size-4" strokeWidth={2} />
						<div class="flex items-center">{tr('恢复', 'Restore')}</div>
					{:else}
						<ArchiveBox className="size-4" strokeWidth="2" />
						<div class="flex items-center">{tr('归档', 'Archive')}</div>
					{/if}
				</DropdownMenu.Item>
			{/if}

			<DropdownMenu.Item
				class="flex  gap-2  items-center px-3 py-2 text-sm  font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
				on:click={() => {
					deleteHandler();
				}}
			>
				<GarbageBin strokeWidth="2" />
				<div class="flex items-center">{$i18n.t('Delete')}</div>
			</DropdownMenu.Item>
		</DropdownMenu.Content>
	</div>
</Dropdown>

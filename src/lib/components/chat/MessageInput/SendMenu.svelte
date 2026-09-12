<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import { getContext } from 'svelte';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Brain from '$lib/components/icons/Brain.svelte';

	const i18n = getContext('i18n');

	export let onSend: () => void;
	export let onSendWithThinking: (effort: string) => void;
	export let onSendToNewChat: () => void;
	export let showThinkingOptions: boolean = false;

	let dropdownOpen = false;
</script>

<Dropdown bind:show={dropdownOpen} side="top" align="end">
	<button
		type="button"
		class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300
			   transition p-1 rounded-full opacity-0 group-hover:opacity-100
			   focus:opacity-100"
		aria-label={$i18n.t('Send options')}
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 20 20"
			fill="currentColor"
			class="size-3.5"
		>
			<path
				fill-rule="evenodd"
				d="M9.47 6.47a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 1 1-1.06 1.06L10 8.06l-3.72 3.72a.75.75 0 0 1-1.06-1.06l4.25-4.25Z"
				clip-rule="evenodd"
			/>
		</svg>
	</button>

	<div slot="content">
		<DropdownMenu.Content
			class="w-56 rounded-xl px-1 py-1 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-sm"
			sideOffset={8}
			side="top"
			align="end"
			transition={flyAndScale}
		>
			<!-- 普通发送 -->
			<DropdownMenu.Item
				class="flex items-center justify-between px-3 py-2 text-sm rounded-xl cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800"
				on:click={() => {
					onSend();
					dropdownOpen = false;
				}}
			>
				<span>{$i18n.t('Send')}</span>
				<kbd
					class="text-2xs text-gray-400 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded font-mono"
					>Enter</kbd
				>
			</DropdownMenu.Item>

			<!-- 深度思考发送 -->
			{#if showThinkingOptions}
				<DropdownMenu.Item
					class="flex items-center justify-between px-3 py-2 text-sm rounded-xl cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800"
					on:click={() => {
						onSendWithThinking('high');
						dropdownOpen = false;
					}}
				>
					<span class="flex items-center gap-1.5">
						<Brain className="size-4 text-blue-500" strokeWidth="1.75" />
						{$i18n.t('Deep Thinking')}
					</span>
				</DropdownMenu.Item>
			{/if}

			<hr class="border-black/5 dark:border-white/5 my-1" />

			<!-- 发到新对话 -->
			<DropdownMenu.Item
				class="flex items-center justify-between px-3 py-2 text-sm rounded-xl cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800"
				on:click={() => {
					onSendToNewChat();
					dropdownOpen = false;
				}}
			>
				<span>{$i18n.t('New Chat')}</span>
				<kbd
					class="text-2xs text-gray-400 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded font-mono"
					>⌘⇧↵</kbd
				>
			</DropdownMenu.Item>

			<hr class="border-black/5 dark:border-white/5 my-1" />

			<!-- 快捷键提示 -->
			<div class="px-3 py-2 text-2xs text-gray-400 dark:text-gray-500 space-y-1">
				<div class="flex justify-between">
					<span>{$i18n.t('New line')}</span>
					<kbd class="font-mono">Shift + Enter</kbd>
				</div>
				<div class="flex justify-between">
					<span>{$i18n.t('Stop')}</span>
					<kbd class="font-mono">Escape</kbd>
				</div>
			</div>
		</DropdownMenu.Content>
	</div>
</Dropdown>

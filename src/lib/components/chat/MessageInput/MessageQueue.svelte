<script lang="ts">
	import { fly } from 'svelte/transition';
	import { getContext } from 'svelte';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';

	const i18n = getContext('i18n');

	export let queue: { id: string; prompt: string; files: any[] }[] = [];
	export let onEdit: (id: string) => void = () => {};
	export let onDelete: (id: string) => void = () => {};
	export let onClearAll: () => void = () => {};
</script>

{#if queue.length > 0}
	<div class="px-3 pb-2" transition:fly={{ y: 10, duration: 200 }}>
		<div class="flex items-center justify-between mb-1.5">
			<span class="text-xs font-medium text-gray-500 dark:text-gray-400">
				{$i18n.t('{{count}} message(s) queued', { count: queue.length })}
			</span>
			<button
				class="text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors max-sm:px-2 max-sm:py-1.5"
				on:click={onClearAll}
			>
				{$i18n.t('Clear All')}
			</button>
		</div>

		<div class="space-y-1 max-h-[25vh] overflow-y-auto scrollbar-hidden">
			{#each queue as item (item.id)}
				<div
					class="flex items-center gap-2 px-3 py-1.5 bg-gray-50 dark:bg-gray-800/50
						   rounded-lg border border-gray-100 dark:border-gray-700/50 text-sm"
					transition:fly={{ y: 5, duration: 150 }}
				>
					<!-- 预览文本 -->
					<div class="flex-1 truncate text-gray-600 dark:text-gray-300">
						{item.prompt.split('\n')[0].slice(0, 80)}
					</div>

					<!-- 附件计数 -->
					{#if item.files?.length > 0}
						<span class="text-xs text-gray-400 shrink-0">
							{item.files.length}
							{$i18n.t('file(s)')}
						</span>
					{/if}

					<!-- 编辑 -->
					<Tooltip content={$i18n.t('Edit')}>
						<button
							class="text-gray-400 hover:text-blue-500 dark:hover:text-blue-400 transition-colors p-0.5 max-sm:p-2"
							on:click={() => onEdit(item.id)}
						>
							<Pencil className="size-3.5" />
						</button>
					</Tooltip>

					<!-- 删除 -->
					<Tooltip content={$i18n.t('Remove')}>
						<button
							class="text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors p-0.5 max-sm:p-2"
							on:click={() => onDelete(item.id)}
						>
							<XMark className="size-3.5" />
						</button>
					</Tooltip>
				</div>
			{/each}
		</div>
	</div>
{/if}

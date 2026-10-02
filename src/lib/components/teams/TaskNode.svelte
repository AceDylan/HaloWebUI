<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';

	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import RunnerBadge from './RunnerBadge.svelte';
	import { toneOf } from './model';
	import { TONE_BORDER } from './tones';

	type $$Props = NodeProps;
	export let data: $$Props['data'];

	$: tone = toneOf(data?.sub_status);
</script>

<Handle
	type="target"
	position={Position.Left}
	class="!opacity-0 !pointer-events-none"
	isConnectable={false}
/>
<button
	type="button"
	class="nodrag w-[220px] h-[104px] text-left rounded-2xl border-2 bg-white dark:bg-gray-900 px-3 py-2.5 shadow-sm transition
	hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 {TONE_BORDER[
		tone
	]} {data?.selected ? 'ring-2 ring-sky-400 dark:ring-sky-500' : ''} {tone === 'idle'
		? 'opacity-70'
		: ''}"
	aria-label="任务 {data?.key} {data?.title}，{data?.member}，{data?.statusText}"
	aria-pressed={data?.selected ? 'true' : 'false'}
	on:click|stopPropagation={() => data?.onSelect?.(data?.id)}
	data-task-key={data?.key}
	data-sub-status={data?.sub_status}
>
	<div class="flex items-center justify-between gap-2">
		<span class="font-mono text-xs font-semibold text-gray-500 dark:text-gray-400"
			>#{data?.key}</span
		>
		<StatusChip status={data?.sub_status} />
	</div>
	<div
		class="mt-1 text-[13px] font-medium leading-snug text-gray-900 dark:text-gray-100 line-clamp-2"
	>
		{data?.title}
	</div>
	<div class="mt-1 flex items-center gap-1.5 min-w-0 text-[11px] text-gray-500 dark:text-gray-400">
		<TeamAvatar kind={data?.avatar} size={18} />
		<span class="min-w-0 truncate">{data?.member}</span>
		<span class="min-w-0 shrink-[2]"
			><RunnerBadge
				chosen={data?.runner?.chosen}
				actual={data?.executor}
				reason={data?.runner?.reason}
			/></span
		>
		{#if data?.waitingFor?.length}
			<span class="ml-auto shrink-0 text-amber-600 dark:text-amber-400"
				>等 {data.waitingFor.join('、')}</span
			>
		{:else if data?.attempts > 1}
			<span class="ml-auto shrink-0">第 {data.attempts} 次</span>
		{/if}
	</div>
</button>
<Handle
	type="source"
	position={Position.Right}
	class="!opacity-0 !pointer-events-none"
	isConnectable={false}
/>

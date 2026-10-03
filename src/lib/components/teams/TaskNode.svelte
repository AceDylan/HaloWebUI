<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';

	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import RunnerBadge from './RunnerBadge.svelte';
	import { elapsed, now } from './clock';
	import { toneOf } from './model';
	import { TONE_BORDER } from './tones';

	type $$Props = NodeProps;
	export let data: $$Props['data'];

	$: tone = toneOf(data?.sub_status);
	$: running = tone === 'run';
	$: took =
		data?.startedAt && (running || data?.completedAt)
			? (data?.completedAt ?? $now) - data.startedAt
			: null;
</script>

<Handle
	type="target"
	position={data?.direction === 'TB' ? Position.Top : Position.Left}
	class="!opacity-0 !pointer-events-none"
	isConnectable={false}
/>
<button
	type="button"
	class="node nodrag relative flex h-[104px] w-[220px] flex-col rounded-2xl border px-3 py-2.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 {TONE_BORDER[
		tone
	]} {running ? 'tm-live' : ''} {data?.selected ? 'is-selected' : ''}"
	data-tone={tone}
	aria-label="任务 {data?.key} {data?.title}，{data?.member}，{data?.statusText}"
	aria-pressed={data?.selected ? 'true' : 'false'}
	on:click|stopPropagation={() => data?.onSelect?.(data?.id)}
	data-task-key={data?.key}
	data-sub-status={data?.sub_status}
>
	<div class="flex min-w-0 items-center gap-1.5">
		<span
			class="shrink-0 font-mono text-[11px] font-semibold tracking-wide text-gray-400 dark:text-gray-500"
			>#{data?.key}</span
		>
		<span class="min-w-0 shrink"
			><RunnerBadge
				chosen={data?.runner?.chosen}
				actual={data?.executor}
				reason={data?.runner?.reason}
				model={data?.model}
				compact
			/></span
		>
		<span class="ml-auto shrink-0"><StatusChip status={data?.sub_status} /></span>
	</div>
	<div
		class="mt-1 line-clamp-2 text-[13px] font-semibold leading-snug text-gray-900 dark:text-gray-50"
	>
		{data?.title}
	</div>
	<div
		class="mt-auto flex min-w-0 items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400"
	>
		<TeamAvatar kind={data?.avatar} size={18} />
		<span class="min-w-0 truncate">{data?.member}</span>
		{#if data?.waitingFor?.length}
			<span class="ml-auto shrink-0 text-amber-600 dark:text-amber-400"
				>等 {data.waitingFor.join('、')}</span
			>
		{:else if took !== null}
			<span
				class="tm-num ml-auto shrink-0 {running ? 'text-sky-600 dark:text-sky-300' : ''}"
				title={running ? '已执行' : '用时'}>{elapsed(took)}</span
			>
		{:else if data?.attempts > 1}
			<span class="ml-auto shrink-0">第 {data.attempts} 次</span>
		{/if}
	</div>
</button>
<Handle
	type="source"
	position={data?.direction === 'TB' ? Position.Bottom : Position.Right}
	class="!opacity-0 !pointer-events-none"
	isConnectable={false}
/>

<style>
	.node {
		background: hsl(var(--tm-surface));
		box-shadow: var(--tm-shadow);
		transition:
			box-shadow 0.3s var(--tm-ease),
			transform 0.3s var(--tm-ease),
			opacity 0.3s ease;
	}
	.node:hover {
		box-shadow: var(--tm-shadow-lift);
	}
	.node[data-tone='done'] {
		background: linear-gradient(180deg, hsl(var(--tm-done) / 0.05), transparent 60%),
			hsl(var(--tm-surface));
	}
	.node[data-tone='fail'] {
		background: linear-gradient(180deg, hsl(var(--tm-bad) / 0.07), transparent 60%),
			hsl(var(--tm-surface));
	}
	.node[data-tone='user'],
	.node[data-tone='quota'] {
		background: linear-gradient(180deg, hsl(var(--tm-violet) / 0.07), transparent 60%),
			hsl(var(--tm-surface));
	}
	.node[data-tone='idle'],
	.node[data-tone='wait'] {
		background: hsl(var(--tm-surface-2));
		box-shadow: none;
	}
	.node[data-tone='idle'] {
		opacity: 0.78;
	}
	.node.is-selected {
		box-shadow:
			0 0 0 3px hsl(var(--tm-accent) / 0.22),
			var(--tm-shadow-lift);
	}
</style>

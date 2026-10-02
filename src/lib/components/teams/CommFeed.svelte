<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import type { TeamEvent } from '$lib/apis/teams';
	import StatusChip from './StatusChip.svelte';
	import { deliveryAt, feedCategory, formatClock, type FeedCategory } from './model';

	/**
	 * Messages, handoffs, tool logs and system events, newest first. Everything here is a
	 * recorded event; nothing is generated for display. In a replay `cursorSeq` is the point in
	 * time shown, so a note's delivery state is the one it had then.
	 */
	export let events: TeamEvent[] = [];
	export let cursorSeq: number | null = null;
	export let memberFilter: string | null = null;
	export let taskFilter: string | null = null;
	export let titles: Map<string, string> = new Map();
	export let pageSize = 150;

	const dispatch = createEventDispatcher();
	let category: FeedCategory | 'all' = 'all';
	let shown = pageSize;

	const FILTERS: { value: FeedCategory | 'all'; label: string }[] = [
		{ value: 'all', label: '全部' },
		{ value: 'message', label: '通讯' },
		{ value: 'tool', label: '工具日志' },
		{ value: 'system', label: '状态' }
	];

	$: filtered = events.filter(
		(ev) =>
			(category === 'all' || feedCategory(ev) === category) &&
			(!memberFilter || ev.member === memberFilter || (ev.type === 'handoff' && ev.data?.to?.some((t) => t.member === memberFilter))) &&
			(!taskFilter || ev.task_id === taskFilter)
	);
	$: newestFirst = filtered.slice().reverse();
	$: visible = newestFirst.slice(0, shown);
	$: hidden = Math.max(0, newestFirst.length - visible.length);

	const toneOfType = (ev: TeamEvent) => {
		if (ev.type === 'message' && ev.who === 'user') return 'border-l-violet-400';
		if (ev.type === 'message') return 'border-l-sky-400';
		if (ev.type === 'handoff') return 'border-l-emerald-400';
		if (ev.type === 'runner') return 'border-l-orange-400';
		if (ev.type === 'team') return 'border-l-indigo-400';
		return 'border-l-transparent';
	};

	const runnerLabel: Record<string, string> = {
		launched: '已启动',
		continued: '续跑',
		answered: '已回答',
		quota_wait: '额度等待',
		question: '等你回答',
		failed: '失败',
		stopped: '已停止'
	};
</script>

<div class="flex flex-col min-h-0 h-full" data-team-feed>
	<div class="flex items-center gap-1 pb-2 flex-wrap" role="radiogroup" aria-label="筛选通讯和日志">
		{#each FILTERS as option}
			<button
				type="button"
				role="radio"
				aria-checked={category === option.value}
				class="rounded-full px-2.5 py-1 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 {category ===
				option.value
					? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:hover:bg-gray-800'}"
				on:click={() => (category = option.value)}>{option.label}</button
			>
		{/each}
		{#if memberFilter || taskFilter}
			<button
				type="button"
				class="ml-auto rounded-full px-2.5 py-1 text-xs text-sky-700 bg-sky-50 hover:bg-sky-100 dark:bg-sky-950/40 dark:text-sky-300"
				on:click={() => dispatch('clearfilter')}
			>
				只看 {memberFilter ?? `#${titles.get(taskFilter ?? '') ?? ''}`} · 清除
			</button>
		{/if}
	</div>

	{#if visible.length === 0}
		<div class="py-8 text-center text-sm text-gray-400 dark:text-gray-500">还没有记录</div>
	{:else}
		<ol class="flex-1 min-h-0 overflow-y-auto space-y-1 pr-1" aria-label="通讯和日志，最新的在上面" aria-live="polite">
			{#each visible as ev (ev.id)}
				{@const delivery = deliveryAt(ev, cursorSeq)}
				<li class="border-l-2 {toneOfType(ev)} pl-2 py-1 text-xs" data-event-type={ev.type}>
					<div class="flex items-baseline gap-1.5 text-gray-400 dark:text-gray-500">
						<time class="font-mono tabular-nums shrink-0">{formatClock(ev.ts)}</time>
						{#if ev.key}
							<button
								type="button"
								class="font-mono text-gray-500 hover:text-sky-600 dark:text-gray-400 dark:hover:text-sky-300"
								on:click={() => dispatch('task', ev.task_id)}>#{ev.key}</button
							>
						{/if}
						{#if ev.type === 'message' && ev.who === 'user'}
							<span class="font-medium text-violet-700 dark:text-violet-300">{ev.author ?? '你'} → {ev.member ?? '成员'}</span>
						{:else if ev.type === 'message'}
							<span class="font-medium text-sky-700 dark:text-sky-300">{ev.member ?? ev.author} 留言</span>
						{:else if ev.type === 'handoff'}
							<span class="font-medium text-emerald-700 dark:text-emerald-300"
								>{ev.member} 完成并交接{ev.data?.to?.length
									? ` → ${ev.data.to.map((t) => `${t.member}(#${t.key})`).join('、')}`
									: ''}</span
							>
						{:else if ev.type === 'tool'}
							<span class="text-gray-500 dark:text-gray-400">{ev.member ?? ''}{ev.data?.subagent ? ` › 子代理 ${ev.data.subagent}` : ''}</span>
							<span class="font-mono font-medium text-gray-700 dark:text-gray-300">{ev.data?.name ?? ''}</span>
						{:else if ev.type === 'subagent'}
							<span class="text-gray-600 dark:text-gray-300">{ev.member} {ev.data?.phase === 'start' ? '派出子代理' : '子代理结束'}</span>
						{:else if ev.type === 'runner'}
							<span class="font-medium text-orange-700 dark:text-orange-300">reclaude {runnerLabel[ev.data?.phase] ?? ev.data?.phase}</span>
						{:else if ev.type === 'team'}
							<span class="font-medium text-indigo-700 dark:text-indigo-300">团队</span>
						{:else if ev.member}
							<span class="text-gray-500 dark:text-gray-400">{ev.member}</span>
						{/if}
						{#if ev.sub_status && (ev.type === 'status' || ev.type === 'attempt')}
							<StatusChip status={ev.sub_status} />
						{/if}
					</div>
					{#if ev.text}
						<div
							class="mt-0.5 whitespace-pre-wrap break-words {ev.type === 'tool'
								? 'font-mono text-[11px] text-gray-500 dark:text-gray-400 line-clamp-2'
								: ev.type === 'message' || ev.type === 'handoff' || ev.type === 'runner'
									? 'text-[13px] text-gray-800 dark:text-gray-200'
									: 'text-gray-600 dark:text-gray-300'}"
						>
							{ev.text}
						</div>
					{/if}
					{#if delivery}
						<div class="mt-0.5">
							<StatusChip
								status={delivery.state === 'delivered' ? 'done' : delivery.state === 'queued' ? 'queued' : 'failed'}
								label={delivery.label}
							/>
						</div>
					{/if}
				</li>
			{/each}
		</ol>
		{#if hidden > 0}
			<button
				type="button"
				class="mt-2 self-center rounded-full px-3 py-1 text-xs text-gray-600 bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300"
				on:click={() => (shown += pageSize)}>显示更早的 {Math.min(hidden, pageSize)} 条（还有 {hidden} 条）</button
			>
		{/if}
	{/if}
</div>

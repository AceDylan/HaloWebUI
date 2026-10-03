<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import type { TeamEvent } from '$lib/apis/teams';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import {
		avatarKind,
		deliveryAt,
		feedCategory,
		formatClock,
		plainPreview,
		RUNNER_EVENT_LABEL,
		type FeedCategory
	} from './model';

	/**
	 * Messages, handoffs, tool logs and system events, newest first, on one timeline. Everything
	 * here is a recorded event; nothing is generated for display. In a replay `cursorSeq` is the
	 * point in time shown, so a note's delivery state is the one it had then.
	 */
	export let events: TeamEvent[] = [];
	export let cursorSeq: number | null = null;
	export let memberFilter: string | null = null;
	export let taskFilter: string | null = null;
	export let titles: Map<string, string> = new Map();
	export let members: { name: string; role?: string }[] = [];
	export let pageSize = 150;

	const dispatch = createEventDispatcher();
	let category: FeedCategory | 'all' = 'all';
	let shown = pageSize;
	let expanded = new Set<string>();
	const toggle = (id: string) => {
		expanded.has(id) ? expanded.delete(id) : expanded.add(id);
		expanded = expanded;
	};

	const FILTERS: { value: FeedCategory | 'all'; label: string }[] = [
		{ value: 'all', label: '全部' },
		{ value: 'message', label: '通讯' },
		{ value: 'tool', label: '工具日志' },
		{ value: 'system', label: '状态' }
	];

	$: roles = new Map(members.map((m) => [m.name, m]));
	$: filtered = events.filter(
		(ev) =>
			(category === 'all' || feedCategory(ev) === category) &&
			(!memberFilter ||
				ev.member === memberFilter ||
				(ev.type === 'handoff' && ev.data?.to?.some((t) => t.member === memberFilter))) &&
			(!taskFilter || ev.task_id === taskFilter)
	);
	$: newestFirst = filtered.slice().reverse();
	$: visible = newestFirst.slice(0, shown);
	$: hidden = Math.max(0, newestFirst.length - visible.length);

	const kindOf = (name: string | null | undefined) =>
		avatarKind(roles.get(name ?? '') ?? { name: name ?? '' });

	const NODE: Record<string, string> = {
		message: 'bg-sky-500',
		user: 'bg-violet-500',
		handoff: 'bg-gray-500 dark:bg-gray-400',
		runner: 'bg-orange-500',
		team: 'bg-indigo-500',
		tool: 'bg-gray-300 dark:bg-gray-600',
		subagent: 'bg-gray-300 dark:bg-gray-600',
		delivery: 'bg-sky-300 dark:bg-sky-700'
	};
	const nodeOf = (ev: TeamEvent) =>
		ev.type === 'message' && ev.who === 'user'
			? NODE.user
			: ev.type === 'message' && ev.who === 'lead'
				? NODE.team
				: (NODE[ev.type] ?? 'bg-gray-300 dark:bg-gray-600');
</script>

<div class="flex h-full min-h-0 flex-col" data-team-feed>
	<div class="flex flex-wrap items-center gap-2 pb-3">
		<div class="tm-segment" role="radiogroup" aria-label="筛选通讯和日志">
			{#each FILTERS as option}
				<button
					type="button"
					role="radio"
					aria-checked={category === option.value}
					class="focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
					on:click={() => (category = option.value)}>{option.label}</button
				>
			{/each}
		</div>
		{#if memberFilter || taskFilter}
			<button
				type="button"
				class="ml-auto rounded-full bg-sky-500/10 px-2.5 py-1 text-xs text-sky-700 hover:bg-sky-500/15 dark:text-sky-300"
				on:click={() => dispatch('clearfilter')}
			>
				只看 {memberFilter ?? `#${titles.get(taskFilter ?? '') ?? ''}`} · 清除
			</button>
		{/if}
	</div>

	{#if visible.length === 0}
		<div class="flex flex-1 flex-col items-center justify-center gap-2 py-10 text-center">
			<span class="size-2 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
			<span class="text-sm text-gray-400 dark:text-gray-500">还没有记录</span>
		</div>
	{:else}
		<ol
			class="feed tm-scroll relative min-h-0 flex-1 overflow-y-auto pr-1"
			aria-label="通讯和日志，最新的在上面"
			aria-live="polite"
		>
			{#each visible as ev (ev.id)}
				{@const delivery = deliveryAt(ev, cursorSeq)}
				<li
					class="item relative pb-3 pl-6 text-xs {ev.type === 'tool' || ev.type === 'subagent'
						? 'pb-1.5'
						: ''}"
					data-event-type={ev.type}
				>
					<span
						class="node absolute left-[5px] top-[5px] size-[7px] rounded-full ring-[3px] ring-[hsl(var(--tm-surface))] {nodeOf(
							ev
						)}"
						aria-hidden="true"
					/>
					{#if ev.type === 'team'}
						<div class="flex items-center gap-2 text-gray-500 dark:text-gray-400">
							<span class="font-semibold text-indigo-600 dark:text-indigo-300">团队</span>
							<span class="min-w-0 flex-1 text-[12.5px] text-gray-700 dark:text-gray-200"
								>{ev.text ?? ''}</span
							>
							<time class="tm-num shrink-0 text-[11px] text-gray-400">{formatClock(ev.ts)}</time>
						</div>
					{:else if ev.type === 'tool' || ev.type === 'subagent'}
						<div class="flex min-w-0 items-baseline gap-1.5 text-gray-400 dark:text-gray-500">
							<span class="shrink-0 text-gray-500 dark:text-gray-400"
								>{ev.member ?? ''}{ev.data?.subagent ? ` › 子代理 ${ev.data.subagent}` : ''}</span
							>
							{#if ev.type === 'tool'}
								<span class="shrink-0 font-mono font-medium text-gray-700 dark:text-gray-300"
									>{ev.data?.name ?? ''}</span
								>
							{:else}
								<span class="shrink-0 text-gray-600 dark:text-gray-300"
									>{ev.data?.phase === 'start' ? '派出子代理' : '子代理结束'}</span
								>
							{/if}
							{#if ev.key}
								<button
									type="button"
									class="shrink-0 font-mono hover:text-sky-600 dark:hover:text-sky-300"
									on:click={() => dispatch('task', ev.task_id)}>#{ev.key}</button
								>
							{/if}
							<time class="tm-num ml-auto shrink-0 text-[11px]">{formatClock(ev.ts)}</time>
						</div>
						{#if ev.text}
							<div
								class="mt-0.5 line-clamp-2 whitespace-pre-wrap break-words font-mono text-[11px] text-gray-500 dark:text-gray-400"
							>
								{ev.text}
							</div>
						{/if}
					{:else}
						<div
							class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-gray-400 dark:text-gray-500"
						>
							{#if ev.type === 'message' && ev.who === 'user'}
								<span class="font-medium text-violet-700 dark:text-violet-300"
									>{ev.author ?? '你'} → {ev.member ?? '成员'}</span
								>
							{:else if ev.type === 'message' && ev.who === 'lead'}
								<TeamAvatar kind="lead" size={16} />
								<span class="font-medium text-indigo-700 dark:text-indigo-300"
									>负责人 → {ev.member ?? '成员'}</span
								>
							{:else if ev.type === 'message'}
								<TeamAvatar kind={kindOf(ev.member)} size={16} />
								<span class="font-medium text-gray-800 dark:text-gray-100"
									>{ev.member ?? ev.author}</span
								>
								<span>留言</span>
							{:else if ev.type === 'handoff'}
								<TeamAvatar kind={kindOf(ev.member)} size={16} />
								<span class="font-medium text-gray-900 dark:text-gray-100"
									>{ev.member} 完成并交接{ev.data?.to?.length
										? ` → ${ev.data.to.map((t) => `${t.member}(#${t.key})`).join('、')}`
										: ''}</span
								>
							{:else if ev.type === 'runner'}
								<span
									class="rounded-md bg-orange-500/10 px-1.5 py-px font-mono text-[11px] text-orange-700 dark:text-orange-300"
									>{ev.data?.runner ?? 'runner'}</span
								>
								<span class="font-medium text-orange-700 dark:text-orange-300"
									>{RUNNER_EVENT_LABEL[ev.data?.phase] ?? ev.data?.phase}</span
								>
							{:else if ev.member}
								<span class="text-gray-600 dark:text-gray-300">{ev.member}</span>
							{/if}
							{#if ev.key}
								<button
									type="button"
									class="shrink-0 whitespace-nowrap font-mono text-gray-400 hover:text-sky-600 dark:hover:text-sky-300"
									on:click={() => dispatch('task', ev.task_id)}>#{ev.key}</button
								>
							{/if}
							{#if ev.sub_status && (ev.type === 'status' || ev.type === 'attempt')}
								<StatusChip status={ev.sub_status} />
							{/if}
							<time class="tm-num ml-auto shrink-0 text-[11px]">{formatClock(ev.ts)}</time>
						</div>
						{#if ev.text}
							<div
								class="mt-1 whitespace-pre-wrap break-words {ev.type === 'message'
									? ev.who === 'user'
										? 'bubble bubble-user'
										: ev.who === 'lead'
											? 'bubble bubble-lead'
											: 'bubble'
									: ev.type === 'handoff'
										? 'bubble bubble-handoff'
										: ev.type === 'runner'
											? 'text-[12.5px] text-gray-700 dark:text-gray-200'
											: 'text-gray-600 dark:text-gray-300'}"
							>
								{#if ev.type === 'message' || ev.type === 'handoff'}
									{@const plain = plainPreview(ev.text)}
									<span class={expanded.has(ev.id) ? '' : 'line-clamp-4'}>{plain}</span>
									{#if plain.length > 160 || plain.split('\n').length > 4}
										<button
											type="button"
											class="mt-1 block text-[11px] font-medium text-sky-700 hover:underline dark:text-sky-300"
											on:click={() => toggle(ev.id)}
											>{expanded.has(ev.id) ? '收起' : '展开全文'}</button
										>
									{/if}
								{:else}
									{ev.text}
								{/if}
							</div>
						{/if}
						{#if delivery}
							<div class="mt-1">
								<StatusChip
									status={delivery.state === 'delivered'
										? 'done'
										: delivery.state === 'queued'
											? 'queued'
											: 'failed'}
									label={delivery.label}
								/>
							</div>
						{/if}
					{/if}
				</li>
			{/each}
		</ol>
		{#if hidden > 0}
			<button
				type="button"
				class="tm-btn-ghost mt-2 self-center"
				on:click={() => (shown += pageSize)}
				>显示更早的 {Math.min(hidden, pageSize)} 条（还有 {hidden} 条）</button
			>
		{/if}
	{/if}
</div>

<style>
	.feed::before {
		content: '';
		position: absolute;
		left: 8px;
		top: 8px;
		bottom: 0;
		width: 1px;
		background: linear-gradient(hsl(var(--tm-line-strong)), hsl(var(--tm-line)) 80%, transparent);
	}
	.bubble {
		display: block;
		width: fit-content;
		max-width: 100%;
		border-radius: 0.35rem 0.9rem 0.9rem 0.9rem;
		padding: 0.45rem 0.7rem;
		font-size: 12.5px;
		line-height: 1.55;
		color: hsl(var(--tm-ink));
		background: hsl(var(--tm-surface-2));
		border: 1px solid hsl(var(--tm-line));
	}
	.bubble-user {
		background: hsl(var(--tm-violet) / 0.08);
		border-color: hsl(var(--tm-violet) / 0.2);
	}
	.bubble-lead {
		background: hsl(var(--tm-accent) / 0.07);
		border-color: hsl(var(--tm-accent) / 0.2);
	}
	.bubble-handoff {
		background: hsl(var(--tm-done) / 0.06);
		border-color: hsl(var(--tm-done) / 0.2);
	}
	.item {
		animation: feed-in 0.4s cubic-bezier(0.22, 1, 0.36, 1) both;
	}
	@keyframes feed-in {
		from {
			opacity: 0;
			transform: translateY(-4px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.item {
			animation: none;
		}
	}
</style>

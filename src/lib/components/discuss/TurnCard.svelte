<script lang="ts">
	import { afterUpdate, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import type { DiscussSeat, DiscussTurn } from '$lib/apis/discussions';
	import { copyToClipboard } from '$lib/utils';
	import ReportMarkdown from '$lib/components/teams/ReportMarkdown.svelte';
	import SeatAvatar from './SeatAvatar.svelte';
	import { seconds, tokens, turnStatusText } from './model';

	/** One seat's turn in one round. */
	export let turn: DiscussTurn;
	export let seat: DiscussSeat | undefined;
	export let hue = 226;

	let body: HTMLDivElement;
	let expanded = false;
	let long = false;
	let follow = true;

	$: live = turn.status === 'streaming';
	$: ringState = (
		turn.status === 'streaming' ? (turn.thinking && !turn.content ? 'thinking' : 'streaming') : turn.status
	) as any;
	$: statusText = turnStatusText(turn);
	$: took = seconds(turn.startedAt, turn.endedAt);
	$: used = tokens(turn.usage?.completion_tokens ?? turn.usage?.total_tokens);
	$: showRole = !!seat?.role && !seat.label.includes(seat.role);

	afterUpdate(() => {
		if (!body) return;
		if (live && follow) body.scrollTop = body.scrollHeight;
		if (!live) long = body.scrollHeight > 300 || long;
	});

	const onScroll = () => {
		if (!live || !body) return;
		follow = body.scrollHeight - body.scrollTop - body.clientHeight < 48;
	};

	const copy = async () => {
		if (await copyToClipboard(turn.content)) toast.success('已复制这段发言');
	};

	$: if (!live) tick().then(() => (long = !!body && body.scrollHeight > 300));
</script>

<article
	class="dc-turn"
	data-state={turn.status}
	style="--dc-hue: {hue}"
	data-discuss-turn={turn.id}
	aria-busy={live}
>
	<header class="flex items-center gap-2.5 px-3.5 pt-3 pb-2">
		<SeatAvatar model={seat?.model ?? ''} name={seat?.label ?? ''} {hue} state={ringState} size={24} />
		<div class="min-w-0 flex-1">
			<div class="flex min-w-0 items-center gap-1.5">
				<span class="truncate text-[13px] font-semibold text-gray-900 dark:text-gray-100"
					>{seat?.label ?? turn.seat}</span
				>
				{#if showRole}
					<span
						class="dc-seat-color shrink-0 rounded-full px-1.5 py-px text-[10.5px] font-medium"
						style="background: hsl({hue} 85% 58% / 0.1)">{seat?.role}</span
					>
				{/if}
			</div>
		</div>
		<span class="shrink-0 text-[11px] text-gray-400 tabular-nums dark:text-gray-500">
			{#if statusText}
				{statusText}
			{:else}
				{[took !== null ? `${took}s` : '', used ? `${used} tokens` : ''].filter(Boolean).join(' · ')}
			{/if}
		</span>
	</header>

	<div
		bind:this={body}
		class="dc-turn-body px-3.5 pb-3"
		data-live={live}
		data-clamped={!live && long && !expanded}
		on:scroll={onScroll}
	>
		{#if turn.status === 'waiting' || (turn.status === 'streaming' && !turn.content)}
			<div class="flex flex-col gap-2 pt-1" style="--dc-hue: {hue}" aria-label={statusText}>
				<div class="dc-skeleton w-11/12" />
				<div class="dc-skeleton w-4/5" />
				<div class="dc-skeleton w-2/3" />
			</div>
		{:else if turn.status === 'error' && !turn.content}
			<p class="rounded-lg bg-red-500/5 px-2.5 py-2 text-xs leading-relaxed text-red-700 dark:text-red-300">
				{turn.error || '这一轮没有发言'}
			</p>
		{:else}
			<ReportMarkdown id="dc-{turn.id}" content={turn.content} />
			{#if turn.status === 'stopped'}
				<p class="mt-1 text-[11px] text-gray-400">（被停止，发言不完整）</p>
			{:else if turn.status === 'error'}
				<p class="mt-1 text-[11px] text-red-600 dark:text-red-300">（中途出错：{turn.error}）</p>
			{/if}
		{/if}
	</div>

	{#if turn.status === 'done' && turn.content}
		<footer class="flex items-center gap-1 px-2.5 pb-2">
			{#if long}
				<button
					type="button"
					class="rounded-lg px-2 py-1 text-[11.5px] font-medium text-gray-500 hover:bg-gray-500/10 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-100"
					on:click={() => (expanded = !expanded)}
					aria-expanded={expanded}>{expanded ? '收起' : '展开全部'}</button
				>
			{/if}
			<button
				type="button"
				class="ml-auto rounded-lg px-2 py-1 text-[11.5px] text-gray-400 hover:bg-gray-500/10 hover:text-gray-700 dark:hover:text-gray-200"
				on:click={copy}
				aria-label="复制 {seat?.label ?? ''} 的发言">复制</button
			>
		</footer>
	{/if}
</article>

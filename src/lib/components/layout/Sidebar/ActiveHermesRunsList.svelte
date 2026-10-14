<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import {
		chatId,
		chats,
		hermesActiveRuns,
		hermesBackgroundRuns,
		hermesUnreadChatIds,
		mobile,
		pinnedChats,
		workActivity
	} from '$lib/stores';
	import { describeBackgroundRun } from '$lib/utils/run-activity';
	import { createRunStopper } from '$lib/utils/runner-stop';
	import { formatToolDuration } from '$lib/utils/tool-call-preview';

	const i18n = getContext('i18n');

	// The rows of 运行中, shared by the sidebar section and the collapsed
	// rail's popup. `showUnread` adds the finished-not-opened chats: the
	// sidebar marks those on the chat list itself, the popup has no chat list.
	export let showUnread = false;
	// Called after a row was chosen (close the popup / the mobile drawer).
	export let onNavigate: () => void = () => {};

	// hermes turns run for minutes. This is the one place that answers "what is
	// still executing, and for how long" without remembering which chat it was.
	// The data comes from the page-level poll (utils/hermes-activity.ts), which
	// keeps going while this list is not shown. Colours match the chat list:
	// blue = running, green = finished and not opened yet, amber = waiting for
	// your approval.
	let now = Date.now() / 1000;
	let clockTimer: ReturnType<typeof setInterval> | null = null;

	$: runs = $hermesActiveRuns;
	// reclaude / codex / agy runs a chat launched, as their reporters last
	// described them (the launching hermes turn is over by then).
	$: background = $hermesBackgroundRuns;
	// Titles come from the chat lists already loaded; unread chats are recent,
	// so they are almost always on the first page.
	$: knownTitles = new Map(
		[...($pinnedChats ?? []), ...($chats ?? [])].map((chat: any) => [chat.id, chat.title])
	);
	// Every other mode at work (a chat replying, 精答, 讨论台, 协作台, 自动分流, 生图), each row
	// marked with its mode; amber when it waits for you (a plan to approve, a member's question).
	$: work = $workActivity;
	const WORK_LABEL: Record<string, string> = {
		chat: '对话',
		image: '生图',
		answer: '精答',
		discuss: '讨论',
		team: '协作',
		auto: '自动分流'
	};
	const workCurrent = (row: { chat_id: string | null; id: string }) =>
		!!$chatId && (row.chat_id === $chatId || row.id === $chatId);
	$: unread = showUnread
		? [...$hermesUnreadChatIds].map((id) => ({ id, title: knownTitles.get(id) ?? null }))
		: [];

	// Same words as every other duration: "45 秒", "12 分 3 秒".
	const elapsed = (startedAt: number) =>
		formatToolDuration(Math.max(0, Math.floor(now - startedAt)));

	onMount(() => {
		clockTimer = setInterval(() => {
			now = Date.now() / 1000;
		}, 1000);
	});

	// A background runner can be stopped from here without opening its chat;
	// same two-press confirm as the chat's banner.
	let armed: string | null = null;
	let stopping: string | null = null;
	const stopper = createRunStopper((state) => ({ armed, stopping } = state));

	onDestroy(() => {
		if (clockTimer) clearInterval(clockTimer);
		stopper.dispose();
	});
</script>

{#each runs as run (run.run_id)}
	<a
		class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-900 {run.chat_id ===
		$chatId
			? 'bg-gray-100 dark:bg-gray-900'
			: ''}"
		href="/c/{run.chat_id}"
		title={run.awaiting_approval
			? `${$i18n.t('Waiting for your approval')}${run.approval?.command ? ` · ${run.approval.command}` : ''}`
			: (run.title ?? '')}
		data-halo-hermes-run-state={run.awaiting_approval ? 'approval' : 'running'}
		on:click={onNavigate}
	>
		{#if run.awaiting_approval}
			<span class="relative flex h-2 w-2 shrink-0">
				<span
					class="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75"
				></span>
				<span class="relative inline-flex h-2 w-2 rounded-full bg-amber-500"></span>
			</span>
		{:else}
			<span class="relative flex h-2 w-2 shrink-0">
				<span
					class="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75"
				></span>
				<span class="relative inline-flex h-2 w-2 rounded-full bg-blue-500"></span>
			</span>
		{/if}
		<span class="flex-1 truncate">{run.title ?? $i18n.t('New Chat')}</span>
		{#if run.awaiting_approval}
			<span
				class="shrink-0 rounded-full bg-amber-100 px-1.5 py-0.5 text-2xs font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
			>
				{$i18n.t('Waiting for your approval')}
			</span>
		{:else}
			{#if run.steers > 0}
				<span class="shrink-0 text-xs text-gray-400">🧭{run.steers}</span>
			{/if}
			<span class="shrink-0 font-mono text-xs tabular-nums text-gray-500">
				{elapsed(run.started_at)}
			</span>
		{/if}
	</a>
{/each}
{#each background as run (run.run_id)}
	<div class="group relative flex w-full items-center" data-halo-hermes-background-row>
		<a
			class="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-900 {run.chat_id ===
			$chatId
				? 'bg-gray-100 dark:bg-gray-900'
				: ''}"
			href="/c/{run.chat_id}"
			title={run.last_activity
				? `${describeBackgroundRun(run, now)} · ${run.last_activity}`
				: describeBackgroundRun(run, now)}
			data-halo-hermes-run-state="background"
			on:click={onNavigate}
		>
			<span class="relative flex h-2 w-2 shrink-0">
				<span
					class="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-60"
				></span>
				<span class="relative inline-flex h-2 w-2 rounded-full bg-blue-500"></span>
			</span>
			<span class="min-w-0 flex-1 truncate">{run.title ?? $i18n.t('New Chat')}</span>
			<span
				class="shrink-0 rounded bg-blue-50 px-1 py-0.5 text-2xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
			>
				{run.agent}
			</span>
			{#if run.started_at}
				<span class="shrink-0 font-mono text-xs tabular-nums text-gray-500">
					{elapsed(run.started_at)}
				</span>
			{/if}
		</a>
		<button
			type="button"
			class="ml-0.5 shrink-0 rounded-md px-1.5 text-2xs font-medium transition max-md:min-h-8 md:py-1 disabled:opacity-60 {armed ===
			run.run_id
				? 'bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400'
				: 'text-gray-400 hover:bg-gray-100 hover:text-red-600 dark:hover:bg-gray-900 dark:hover:text-red-400'} {$mobile ||
			armed === run.run_id ||
			stopping === run.run_id
				? ''
				: 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100'}"
			disabled={stopping === run.run_id}
			data-halo-hermes-background-stop={run.run_id}
			aria-label={armed === run.run_id ? `确认停止 ${run.agent}` : `停止 ${run.agent}`}
			on:click|stopPropagation={() => stopper.press(run)}
		>
			{stopping === run.run_id ? '停止中…' : armed === run.run_id ? '确认停止' : '停止'}
		</button>
	</div>
{/each}
{#each work as row (`${row.kind}:${row.id}`)}
	<a
		class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-900 {workCurrent(
			row
		)
			? 'bg-gray-100 dark:bg-gray-900'
			: ''}"
		href={row.href}
		title={row.note ? `${row.note} · ${row.title ?? ''}` : (row.title ?? '')}
		data-halo-work-row={row.kind}
		data-halo-hermes-run-state={row.state === 'waiting' ? 'approval' : 'running'}
		on:click={onNavigate}
	>
		<span class="relative flex h-2 w-2 shrink-0">
			<span
				class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 {row.state ===
				'waiting'
					? 'bg-amber-400'
					: 'bg-blue-400'}"
			></span>
			<span
				class="relative inline-flex h-2 w-2 rounded-full {row.state === 'waiting'
					? 'bg-amber-500'
					: 'bg-blue-500'}"
			></span>
		</span>
		<span class="min-w-0 flex-1 truncate">{row.title ?? WORK_LABEL[row.kind] ?? ''}</span>
		<span
			class="shrink-0 rounded px-1 py-0.5 text-2xs font-medium {row.state === 'waiting'
				? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
				: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'}"
		>
			{row.state === 'waiting' && row.note ? row.note : WORK_LABEL[row.kind] ?? row.kind}
		</span>
		{#if row.state !== 'waiting'}
			<span class="shrink-0 font-mono text-xs tabular-nums text-gray-500">
				{elapsed(row.started_at)}
			</span>
		{/if}
	</a>
{/each}
{#each unread as chat (chat.id)}
	<a
		class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-900"
		href="/c/{chat.id}"
		title={$i18n.t('Finished, not yet opened')}
		data-halo-hermes-run-state="unread"
		on:click={onNavigate}
	>
		<span class="relative inline-flex h-2 w-2 shrink-0 rounded-full bg-emerald-500"></span>
		<span class="min-w-0 flex-1 truncate">{chat.title ?? $i18n.t('Chat')}</span>
		<span class="shrink-0 text-xs text-emerald-700 dark:text-emerald-400">已完成</span>
	</a>
{/each}

<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import {
		chatId,
		hermesActiveRuns,
		hermesBackgroundRuns,
		hermesUnreadChatIds,
		mobile,
		showSidebar
	} from '$lib/stores';
	import { describeBackgroundRun } from '$lib/utils/run-activity';
	import { formatToolDuration } from '$lib/utils/tool-call-preview';
	import Folder from '../../common/Folder.svelte';
	import Tooltip from '../../common/Tooltip.svelte';
	import Bolt from '../../icons/Bolt.svelte';

	const i18n = getContext('i18n');

	// `compact` is the collapsed-rail form: one icon with a count badge that
	// expands the sidebar. The full form lists the runs under "Running".
	export let compact = false;
	export let buttonClass = '';

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
	$: unreadCount = $hermesUnreadChatIds.size;
	$: approvalCount = runs.filter((run) => run.awaiting_approval).length;
	$: runningCount = runs.length + background.length;

	// Same words as every other duration: "45 秒", "12 分 3 秒".
	const elapsed = (startedAt: number) =>
		formatToolDuration(Math.max(0, Math.floor(now - startedAt)));

	onMount(() => {
		clockTimer = setInterval(() => {
			now = Date.now() / 1000;
		}, 1000);
	});

	onDestroy(() => {
		if (clockTimer) clearInterval(clockTimer);
	});
</script>

{#if compact}
	{#if runningCount > 0 || unreadCount > 0}
		<Tooltip
			content={approvalCount > 0
				? `${$i18n.t('Waiting for your approval')} · ${approvalCount}`
				: runningCount > 0
					? `${$i18n.t('Running')} · ${runningCount}`
					: `${$i18n.t('Finished, not yet opened')} · ${unreadCount}`}
		>
			<button
				class="{buttonClass} relative"
				type="button"
				on:click={() => {
					showSidebar.set(true);
				}}
				aria-label={approvalCount > 0
					? $i18n.t('Waiting for your approval')
					: runningCount > 0
						? $i18n.t('Running')
						: $i18n.t('Finished, not yet opened')}
			>
				<Bolt
					className="size-5 {approvalCount > 0
						? 'text-amber-600 dark:text-amber-400'
						: runningCount > 0
							? 'text-blue-600 dark:text-blue-400'
							: 'text-emerald-600 dark:text-emerald-400'}"
					strokeWidth="2"
				/>
				<span
					class="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-2xs font-semibold leading-none text-white {approvalCount >
					0
						? 'bg-amber-500'
						: runningCount > 0
							? 'bg-blue-500'
							: 'bg-emerald-500'}"
				>
					{approvalCount > 0 ? approvalCount : runningCount > 0 ? runningCount : unreadCount}
				</span>
			</button>
		</Tooltip>
	{/if}
{:else if runningCount > 0}
	<Folder className="px-2 mt-0.5" name={$i18n.t('Running')} dragAndDrop={false}>
		<div
			class="ml-3 pl-1 mt-[1px] flex flex-col border-s border-gray-100 dark:border-gray-900"
		>
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
					on:click={() => {
						if ($mobile) {
							showSidebar.set(false);
						}
					}}
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
				<a
					class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-900 {run.chat_id ===
					$chatId
						? 'bg-gray-100 dark:bg-gray-900'
						: ''}"
					href="/c/{run.chat_id}"
					title={run.last_activity
						? `${describeBackgroundRun(run, now)} · ${run.last_activity}`
						: describeBackgroundRun(run, now)}
					data-halo-hermes-run-state="background"
					on:click={() => {
						if ($mobile) {
							showSidebar.set(false);
						}
					}}
				>
					<span class="relative flex h-2 w-2 shrink-0">
						<span
							class="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-60"
						></span>
						<span class="relative inline-flex h-2 w-2 rounded-full bg-blue-500"></span>
					</span>
					<span class="min-w-0 flex-1 truncate">{run.title ?? $i18n.t('New Chat')}</span>
					<span class="shrink-0 rounded bg-blue-50 px-1 py-0.5 text-2xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
						{run.agent}
					</span>
					{#if run.started_at}
						<span class="shrink-0 font-mono text-xs tabular-nums text-gray-500">
							{elapsed(run.started_at)}
						</span>
					{/if}
				</a>
			{/each}
		</div>
	</Folder>
{/if}

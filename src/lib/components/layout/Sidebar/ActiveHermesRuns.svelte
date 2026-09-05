<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { chatId, mobile, showSidebar } from '$lib/stores';
	import { getActiveHermesRuns, type HermesActiveRun } from '$lib/apis/hermes';
	import Folder from '../../common/Folder.svelte';

	const i18n = getContext('i18n');

	// hermes turns run for minutes. This is the one place that answers "what is
	// still executing, and for how long" without remembering which chat it was.
	const POLL_MS = 10000;

	let runs: HermesActiveRun[] = [];
	let now = Date.now() / 1000;
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let clockTimer: ReturnType<typeof setInterval> | null = null;

	const refresh = async () => {
		if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
			return;
		}
		runs = await getActiveHermesRuns(localStorage.token).catch(() => runs);
	};

	const elapsed = (startedAt: number) => {
		const seconds = Math.max(0, Math.floor(now - startedAt));
		const minutes = Math.floor(seconds / 60);
		if (minutes >= 60) {
			return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}m`;
		}
		return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
	};

	onMount(() => {
		refresh();
		pollTimer = setInterval(refresh, POLL_MS);
		clockTimer = setInterval(() => {
			now = Date.now() / 1000;
		}, 1000);
		document.addEventListener('visibilitychange', refresh);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
		if (clockTimer) clearInterval(clockTimer);
		if (typeof document !== 'undefined') {
			document.removeEventListener('visibilitychange', refresh);
		}
	});
</script>

{#if runs.length > 0}
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
					title={run.title ?? ''}
					on:click={() => {
						if ($mobile) {
							showSidebar.set(false);
						}
					}}
				>
					<span class="relative flex h-2 w-2 shrink-0">
						<span
							class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
						></span>
						<span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
					</span>
					<span class="flex-1 truncate">{run.title ?? $i18n.t('New Chat')}</span>
					{#if run.steers > 0}
						<span class="shrink-0 text-xs text-gray-400">🧭{run.steers}</span>
					{/if}
					<span class="shrink-0 font-mono text-xs tabular-nums text-gray-500">
						{elapsed(run.started_at)}
					</span>
				</a>
			{/each}
		</div>
	</Folder>
{/if}

<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	import { chatId, hermesBackgroundRuns } from '$lib/stores';
	import { describeBackgroundRun } from '$lib/utils/run-activity';

	// A reclaude / codex / agy runner this chat launched is still working: say
	// where it is, from its own progress reports, so nobody has to spend a
	// two-minute hermes turn asking "查看进度".
	let now = Date.now() / 1000;
	let clock: ReturnType<typeof setInterval> | null = null;

	onMount(() => {
		clock = setInterval(() => {
			now = Date.now() / 1000;
		}, 15000);
	});
	onDestroy(() => {
		if (clock) clearInterval(clock);
	});

	$: runs = $hermesBackgroundRuns.filter((run) => run.chat_id === $chatId);
</script>

{#each runs as run (run.run_id)}
	<div
		class="mx-auto mb-2 flex w-full max-w-3xl items-start gap-2 rounded-xl border border-blue-200/70 bg-blue-50/80 px-3 py-2 text-xs text-blue-800 dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-200"
		role="status"
		data-halo-background-runner={run.agent}
	>
		<span class="relative mt-1 flex h-2 w-2 shrink-0">
			<span
				class="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-60"
			></span>
			<span class="relative inline-flex h-2 w-2 rounded-full bg-blue-500"></span>
		</span>
		<div class="min-w-0 flex-1">
			<div class="font-medium tabular-nums">
				{describeBackgroundRun(run, now)} · 后台运行中，结束后报告会自动发到这里
			</div>
			{#if run.last_activity}
				<div class="mt-0.5 truncate font-mono text-2xs text-blue-700/80 dark:text-blue-300/80">
					最近：{run.last_activity}
				</div>
			{/if}
		</div>
	</div>
{/each}

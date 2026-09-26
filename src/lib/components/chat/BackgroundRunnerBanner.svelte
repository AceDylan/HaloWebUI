<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { stopHermesBackgroundRunner } from '$lib/apis/hermes';
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
		if (armTimer) clearTimeout(armTimer);
	});

	// Stopping ends a task that may have been running for an hour: the first
	// press only arms the button ("确认停止"), a second one within 5 s stops it.
	let armed: string | null = null;
	let armTimer: ReturnType<typeof setTimeout> | null = null;
	let stopping: string | null = null;

	const stop = async (run: { run_id: string; agent: string }) => {
		if (stopping) return;
		if (armed !== run.run_id) {
			armed = run.run_id;
			if (armTimer) clearTimeout(armTimer);
			armTimer = setTimeout(() => (armed = null), 5000);
			return;
		}
		armed = null;
		stopping = run.run_id;
		try {
			const result = await stopHermesBackgroundRunner(localStorage.token, run.run_id);
			hermesBackgroundRuns.update((runs) => runs.filter((item) => item.run_id !== run.run_id));
			toast.success(
				result.report_shown
					? `已停止 ${run.agent}，直接回复就能让它按新说明接着做`
					: `已停止 ${run.agent}`
			);
		} catch (error) {
			toast.error(`没能停止 ${run.agent}：${error}`);
		} finally {
			stopping = null;
		}
	};

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
				<div
					class="mt-0.5 truncate font-mono text-2xs text-blue-700/80 dark:text-blue-300/80"
					title={run.last_activity}
				>
					最近：{run.last_activity}
				</div>
			{/if}
		</div>
		<button
			type="button"
			class="shrink-0 self-center rounded-lg px-2.5 py-1 text-xs font-medium transition max-sm:px-3 max-sm:py-1.5 {armed ===
			run.run_id
				? 'bg-red-600 text-white hover:bg-red-700'
				: 'text-blue-700 hover:bg-blue-100 dark:text-blue-200 dark:hover:bg-blue-900/60'} disabled:opacity-60"
			disabled={stopping === run.run_id}
			data-halo-background-runner-stop={run.run_id}
			aria-label={armed === run.run_id ? `确认停止 ${run.agent}` : `停止 ${run.agent}`}
			on:click={() => stop(run)}
		>
			{stopping === run.run_id ? '停止中…' : armed === run.run_id ? '确认停止' : '停止'}
		</button>
	</div>
{/each}

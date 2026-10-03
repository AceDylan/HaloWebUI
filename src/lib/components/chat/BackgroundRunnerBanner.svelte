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

	// The reporter posts every few minutes (at least every 3); twice that without a
	// word means the runner may be stuck rather than working.
	const STALE_AFTER_SECONDS = 7 * 60;
	// What the runner last reported: its own words ("在做：核对部署…"), or — a runner that
	// narrates nothing yet — its last tool call ("最近：Bash: npm test"), shown as code.
	const COMMAND_RE = /^[A-Za-z][\w.-]*(?:#\d+)?:\s/;
	const describeActivity = (text: string | null | undefined) => {
		const value = String(text ?? '').trim();
		return { text: value, command: COMMAND_RE.test(value) };
	};
	const quietMinutes = (run: { updated_at: number }, at: number) => {
		const quiet = at - Number(run.updated_at || 0);
		return run.updated_at && quiet > STALE_AFTER_SECONDS ? Math.floor(quiet / 60) : 0;
	};
</script>

{#each runs as run (run.run_id)}
	{@const quiet = quietMinutes(run, now)}
	{@const activity = describeActivity(run.last_activity)}
	<div
		class="halo-runner mx-auto mb-2 flex w-full max-w-3xl items-center gap-3 rounded-2xl px-3.5 py-2.5 text-xs"
		class:is-quiet={quiet > 0}
		role="status"
		data-halo-background-runner={run.agent}
	>
		<span class="halo-runner__ring" aria-hidden="true"><span></span></span>
		<div class="min-w-0 flex-1">
			<div class="flex min-w-0 items-baseline gap-1.5 tabular-nums">
				<span class="halo-runner__name font-display shrink-0">{run.agent}</span>
				<span class="truncate text-gray-500 dark:text-gray-400"
					>{describeBackgroundRun(run, now).split(' · ').slice(1).join(' · ') ||
						'刚开始'}<span class="max-sm:hidden"> · 后台进行中，做完报告发到这里</span></span
				>
			</div>
			{#if quiet}
				<div
					class="mt-0.5 text-2xs text-amber-700 dark:text-amber-300"
					data-halo-background-runner-quiet
				>
					已经 {quiet} 分钟没有新进度，可能卡住了；需要时可以停止它
				</div>
			{:else if activity.text}
				<div
					class="mt-0.5 truncate text-2xs text-gray-500 dark:text-gray-400 {activity.command
						? 'font-mono'
						: ''}"
					title={run.last_activity}
				>
					{activity.command ? '最近' : '在做'}：{activity.text}
				</div>
			{/if}
		</div>
		<button
			type="button"
			class="halo-runner__stop shrink-0 rounded-full px-3 py-1 text-xs font-medium transition max-sm:px-3.5 max-sm:py-2 disabled:opacity-60"
			class:is-armed={armed === run.run_id}
			disabled={stopping === run.run_id}
			data-halo-background-runner-stop={run.run_id}
			aria-label={armed === run.run_id ? `确认停止 ${run.agent}` : `停止 ${run.agent}`}
			on:click={() => stop(run)}
		>
			{stopping === run.run_id ? '停止中…' : armed === run.run_id ? '确认停止' : '停止'}
		</button>
	</div>
{/each}

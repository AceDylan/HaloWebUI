<script lang="ts">
	import {
		describeHermesRunNotice,
		describeTeamNotice,
		reportDurationSeconds,
		type HermesRunNotice
	} from '$lib/utils/hermes';
	import { formatRunDuration } from '$lib/utils/run-activity';

	// A background runner's completion notice. It stays a user message (hermes
	// reads the run id and session from it on the next turn), but nobody typed
	// it: it shows as a system line, not a bubble signed "你", with the ids one
	// click away instead of a full UUID in the transcript.
	export let notice: HermesRunNotice;
	export let content = '';
	// The report right under the notice, for the run's headline and duration.
	export let report = '';

	let open = false;

	$: duration = formatRunDuration(reportDurationSeconds(report));
	// A 协作台 team's conclusion: posted by the team, not a runner.
	$: team = describeTeamNotice(notice, content);
	$: headline = team
		? team.headline
		: [describeHermesRunNotice(notice, report), duration].filter(Boolean).join(' · ');
</script>

<div class="flex w-full flex-col items-center py-1" data-halo-hermes-run-notice>
	<button
		type="button"
		class="flex max-w-full items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600 transition hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:hover:bg-gray-800"
		aria-expanded={open}
		title={team
			? '协作任务的结论（由协作台发来，不是你发的消息）'
			: '后台任务完成通知（由 runner 发送，不是你发的消息）'}
		on:click={() => {
			open = !open;
		}}
	>
		<span class="truncate">{headline}</span>
		<span class="shrink-0 text-gray-400 dark:text-gray-500">{open ? '收起' : '详情'}</span>
	</button>
	{#if open}
		<div
			class="mt-1.5 max-w-full rounded-xl border border-gray-100 bg-gray-50 px-3 py-2 text-2xs text-gray-500 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400"
			data-halo-hermes-run-notice-details
		>
			{#if team}
				<div class="whitespace-pre-wrap break-all">{content}</div>
				{#if team.teamId}
					<a
						class="mt-1 inline-block text-sky-700 underline underline-offset-2 dark:text-sky-300"
						href="/teams/{team.teamId}/conclusion"
						data-halo-team-notice-link>在协作台打开结论 →</a
					>
				{/if}
			{:else if notice.runId}
				<div class="break-all">run：<span class="font-mono">{notice.runId}</span></div>
			{/if}
			{#if !team && notice.sessionId}
				<div class="break-all">
					{notice.sessionLabel || '会话'}：<span class="font-mono">{notice.sessionId}</span>
				</div>
			{/if}
			{#if !team && !notice.runId && !notice.sessionId}
				<div class="whitespace-pre-wrap break-all">{content}</div>
			{/if}
		</div>
	{/if}
</div>

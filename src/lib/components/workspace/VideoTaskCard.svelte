<script lang="ts">
	/**
	 * One video the workbench started (backend utils/video_tasks.py), in the 精答 / 讨论 card's
	 * language: the steps (a halo on it while it works), what is happening right now and for how
	 * long, the way to stop it, and the video once it is made. The same card stands in the
	 * workbench's list (`where="studio"`: it leads to the chat, and plays the video) and on the
	 * chat's reply (`where="chat"`: it leads back to the workbench; the reply below shows the
	 * video).
	 */
	import { createEventDispatcher } from 'svelte';

	import '$lib/components/teams/teams.css';
	import type { VideoTask } from '$lib/apis/video-studio';
	import StatusChip from '$lib/components/teams/StatusChip.svelte';
	import { elapsed, now } from '$lib/components/teams/clock';

	export let task: VideoTask;
	export let where: 'studio' | 'chat' = 'studio';
	export let stopping = false;
	/** Opened from the chat's card: shown with a ring until the next look elsewhere. */
	export let highlight = false;

	const dispatch = createEventDispatcher<{ stop: VideoTask }>();

	type StepState = 'done' | 'active' | 'pending' | 'failed';
	type Step = { key: string; label: string; state: StepState };

	const STATE_LABEL: Record<VideoTask['state'], string> = {
		running: '制作中',
		background: '后台制作',
		done: '已完成',
		replied: '已回复',
		failed: '失败',
		stopped: '已停止'
	};
	const CHIP: Record<VideoTask['state'], string> = {
		running: 'running',
		background: 'running',
		done: 'done',
		replied: 'waiting_user',
		failed: 'failed',
		stopped: 'stopped'
	};

	$: live = task.state === 'running' || task.state === 'background';
	$: ended = task.state === 'failed' || task.state === 'stopped';
	$: viaRunner = task.maker !== 'Hermes';
	// the step it is at (or ended at): the ones before are done, the ones after still to come
	const stageKey = (t: VideoTask, runner: boolean): string => {
		const stage =
			t.state === 'running'
				? t.prep === 'running'
					? 'prep'
					: 'make'
				: t.state === 'background'
					? 'runner'
					: t.state === 'done' || t.state === 'replied'
						? 'video'
						: (t.endedIn ?? 'make');
		if (stage === 'make') return runner ? 'hand' : 'make';
		return stage === 'runner' ? 'make' : stage;
	};
	$: steps = ((): Step[] => {
		const list = [
			...(task.prep || task.endedIn === 'prep' ? [{ key: 'prep', label: '增强需求' }] : []),
			...(viaRunner
				? [
						{ key: 'hand', label: `交给 ${task.maker}` },
						{ key: 'make', label: `${task.maker} 制作` }
					]
				: [{ key: 'make', label: 'Hermes 制作' }]),
			{ key: 'video', label: '成片入库' }
		];
		if (task.state === 'done') return list.map((step) => ({ ...step, state: 'done' as StepState }));
		const at = Math.max(0, list.findIndex((step) => step.key === stageKey(task, viaRunner)));
		return list.map((step, i) => ({
			...step,
			state: (i < at ? 'done' : i > at ? 'pending' : ended ? 'failed' : 'active') as StepState
		}));
	})();
	$: tone = live ? 'moving' : task.state === 'done' ? 'done' : task.state === 'replied' ? 'waiting' : 'ended';
	$: runnerSince = task.runner?.startedAt ?? null;
	$: spent = live && task.startedAt ? $now - task.startedAt : null;
	$: took = !live && task.startedAt && task.endedAt && task.endedAt > task.startedAt ? task.endedAt - task.startedAt : null;
	$: facts = [
		'视频',
		task.maker,
		task.steps ? `${task.steps} 步` : '',
		task.state === 'background' && task.runner?.step ? `${task.maker} 第 ${task.runner.step} 步` : '',
		task.state === 'background' && runnerSince ? `后台已 ${elapsed($now - runnerSince)}` : ''
	].filter(Boolean);
	$: chatHref = `/c/${encodeURIComponent(task.chatId)}`;
	$: studioHref = `/workspace/videos?task=${encodeURIComponent(task.chatId)}`;
</script>

<div
	class="vt-card not-prose flex max-w-2xl flex-col gap-2 {highlight ? 'vt-highlight' : ''}"
	data-teams-ui
	data-video-task={task.chatId}
	data-video-task-state={task.state}
	data-video-task-where={where}
>
	<div class="flex min-w-0 items-center gap-2.5">
		<span class="vt-tile size-[32px] text-[15px] {live ? 'tm-live' : ''}" aria-hidden="true">🎬</span>
		<div class="min-w-0 flex-1">
			<div class="flex min-w-0 items-center gap-2">
				<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100" title={task.title}
					>{task.title}</span
				>
				<span class="shrink-0"><StatusChip status={CHIP[task.state]} label={STATE_LABEL[task.state]} size="sm" /></span>
			</div>
			<div class="truncate text-[11px] text-gray-500 dark:text-gray-400" data-video-task-facts>{facts.join(' · ')}</div>
		</div>
		{#if where === 'studio'}
			<a href={chatHref} class="tm-btn-ghost shrink-0 !text-xs" data-video-task-chat>打开对话 ↗</a>
		{:else}
			<a href={studioHref} class="tm-btn-ghost shrink-0 !text-xs" data-video-task-studio>在视频工作台看 ↗</a>
		{/if}
	</div>

	<section class="vt-stage tm-card px-4 py-3 {live ? 'tm-live' : ''}" data-tone={tone} aria-label="视频任务的进度">
		<ol class="mb-2.5 flex list-none items-center p-0" aria-label="步骤">
			{#each steps as step, i (step.key)}
				<li class="vt-step flex shrink-0 items-center gap-1.5" data-step={step.key} data-state={step.state} aria-current={step.state === 'active' ? 'step' : undefined}>
					<span class="vt-dot grid size-[18px] place-items-center rounded-full" aria-hidden="true">
						{#if step.state === 'done'}
							<svg class="size-2.5" viewBox="0 0 12 12" fill="none"
								><path d="m2.5 6.3 2.2 2.2 4.8-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg
							>
						{:else if step.state === 'failed'}
							<svg class="size-2.5" viewBox="0 0 12 12" fill="none"
								><path d="m3.5 3.5 5 5m0-5-5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg
							>
						{:else}
							<span class="vt-core size-1.5 rounded-full" />
						{/if}
					</span>
					<span class="vt-label whitespace-nowrap text-xs">{step.label}</span>
				</li>
				{#if i < steps.length - 1}
					<li class="vt-bar mx-1.5 h-px min-w-3 flex-1" data-state={step.state === 'done' ? 'done' : 'pending'} aria-hidden="true" />
				{/if}
			{/each}
		</ol>

		<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
			<p class="min-w-0 flex-1 basis-48 break-words text-sm text-gray-800 dark:text-gray-100" data-video-task-now>
				<span class={live ? 'tm-shimmer' : ''}>{task.now}</span>
			</p>
			{#if spent !== null || took !== null}
				<span class="tm-num shrink-0 text-xs text-gray-500 dark:text-gray-400" data-video-task-clock
					>{spent !== null ? `已用 ${elapsed(spent)}` : `用时 ${elapsed(took ?? 0)}`}</span
				>
			{/if}
		</div>

		{#if live}
			<div class="mt-2 flex justify-end">
				<button
					type="button"
					class="rounded-lg px-1 text-[11px] text-gray-400 transition hover:text-red-600 disabled:opacity-60 dark:hover:text-red-400"
					disabled={stopping}
					on:click={() => dispatch('stop', task)}
					data-video-task-stop>{stopping ? '停止中…' : '停止'}</button
				>
			</div>
		{/if}

		{#if task.state === 'done' && task.videos.length}
			<div class="vt-foot mt-3 pt-2.5" data-video-task-videos>
				{#if where === 'studio'}
					<div class="grid gap-2 {task.videos.length > 1 ? 'sm:grid-cols-2' : ''}">
						{#each task.videos as video (video.id)}
							<div class="min-w-0">
								<!-- svelte-ignore a11y-media-has-caption -->
								<video src="{video.url}#t=0.1" controls playsinline preload="metadata" class="aspect-video w-full rounded-lg bg-black" data-video-task-player={video.id} />
								<div class="mt-1 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
									<span class="min-w-0 flex-1 truncate" title={video.name}>{video.title || video.name}</span>
									<a href={video.url} download={video.name} class="shrink-0 hover:underline">下载</a>
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-600 dark:text-gray-300">
						<span class="font-medium text-gray-900 dark:text-gray-100">成片已进视频库</span>
						<span class="min-w-0 flex-1 truncate">{task.videos.map((v) => v.name).join('、')}</span>
						<a href="/workspace/videos?tab=library" class="shrink-0 font-medium text-sky-700 hover:underline dark:text-sky-300">视频库 ↗</a>
					</div>
				{/if}
			</div>
		{/if}
	</section>
</div>

<style>
	.vt-tile {
		display: inline-grid;
		place-items: center;
		flex: none;
		border-radius: 9999px;
		background: linear-gradient(135deg, hsl(282 85% 60% / 0.16), hsl(330 85% 58% / 0.1));
		box-shadow: inset 0 0 0 1px hsl(290 70% 55% / 0.22);
	}
	.vt-highlight {
		border-radius: 1rem;
		box-shadow: 0 0 0 2px hsl(var(--tm-accent) / 0.55);
	}
	.vt-stage {
		--vt-tone: var(--tm-accent);
	}
	.vt-stage[data-tone='done'] {
		--vt-tone: var(--tm-done);
	}
	.vt-stage[data-tone='waiting'] {
		--vt-tone: var(--tm-ok);
	}
	.vt-stage[data-tone='ended'] {
		--vt-tone: var(--tm-warn);
	}
	/* in a chat reply's Markdown too: the steps are not a numbered list */
	.vt-stage :global(li) {
		list-style: none;
	}
	.vt-stage li::marker {
		content: none;
	}
	.vt-dot {
		border: 1.5px solid hsl(var(--tm-line-strong));
		color: hsl(var(--tm-muted));
	}
	.vt-step[data-state='done'] .vt-dot {
		border-color: transparent;
		background: hsl(var(--tm-done));
		color: white;
	}
	.vt-step[data-state='active'] .vt-dot {
		border-color: hsl(var(--vt-tone));
		color: hsl(var(--vt-tone));
	}
	.vt-step[data-state='active'] .vt-core {
		background: currentColor;
	}
	.vt-stage[data-tone='moving'] .vt-step[data-state='active'] .vt-core {
		animation: vt-beat 1.6s var(--tm-ease) infinite;
	}
	.vt-step[data-state='failed'] .vt-dot {
		border-color: transparent;
		background: hsl(var(--tm-warn));
		color: white;
	}
	.vt-label {
		color: hsl(var(--tm-muted));
	}
	.vt-step[data-state='active'] .vt-label,
	.vt-step[data-state='failed'] .vt-label {
		color: hsl(var(--tm-ink));
		font-weight: 600;
	}
	.vt-step[data-state='done'] .vt-label {
		color: hsl(var(--tm-ink) / 0.75);
	}
	.vt-bar {
		background: hsl(var(--tm-line-strong));
	}
	.vt-bar[data-state='done'] {
		background: hsl(var(--tm-done) / 0.6);
	}
	.vt-foot {
		border-top: 1px solid hsl(var(--tm-line));
	}
	@keyframes vt-beat {
		50% {
			transform: scale(1.7);
			opacity: 0.55;
		}
	}
	@media (max-width: 480px) {
		.vt-step:not([data-state='active']):not([data-state='failed']) .vt-label {
			display: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.vt-core {
			animation: none !important;
		}
	}
</style>

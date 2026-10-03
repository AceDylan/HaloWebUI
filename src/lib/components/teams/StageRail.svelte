<script lang="ts">
	import type { TeamStage } from '$lib/apis/teams';
	import { elapsed, now } from './clock';
	import { STAGE_MOVING, STAGE_STEPS, etaSentence, formatEta } from './model';

	/**
	 * 阶段条: where the team is (计划 → 批准 → 执行 → 整理结果 → 验收), what is happening right now,
	 * how long this stage has taken and about how long is left — the same for every status, so the
	 * user never waits without knowing why.
	 */
	export let stage: TeamStage | null = null;
	/** Hide the five steps (a page that shows them elsewhere). */
	export let steps = true;

	$: moving = !!stage && STAGE_MOVING.has(stage.key);
	$: stepState = new Map((stage?.steps ?? []).map((s) => [s.key, s.state]));
	$: spent = moving && stage?.started_at ? $now - stage.started_at : null;
	$: etaText = moving ? etaSentence(stage?.eta, stage?.at, $now) : '';
	$: lines = stage?.running ?? [];
	$: tone =
		stage?.key === 'attention'
			? 'attention'
			: stage?.key === 'paused'
				? 'paused'
				: stage?.key === 'done'
					? 'done'
					: ['stopped', 'plan_failed', 'start_failed', 'cancelled'].includes(stage?.key ?? '')
						? 'ended'
						: stage?.key === 'approval'
							? 'waiting'
							: 'moving';
	$: after = stage?.key === 'approval' ? stage.after_approval : null;
</script>

{#if stage}
	<section
		class="stage tm-card px-4 py-3 {moving ? 'tm-live' : ''}"
		data-stage={stage.key}
		data-tone={tone}
		aria-label="当前阶段"
	>
		{#if steps && stage.steps?.length}
			<ol class="rail mb-2.5 flex list-none items-center p-0" aria-label="阶段">
				{#each STAGE_STEPS as step, i (step.key)}
					{@const state = stepState.get(step.key) ?? 'pending'}
					<li
						class="step flex shrink-0 items-center gap-1.5"
						data-step={step.key}
						data-state={state}
						aria-current={state === 'active' ? 'step' : undefined}
					>
						<span class="dot grid size-[18px] place-items-center rounded-full" aria-hidden="true">
							{#if state === 'done'}
								<svg class="size-2.5" viewBox="0 0 12 12" fill="none"
									><path
										d="m2.5 6.3 2.2 2.2 4.8-5"
										stroke="currentColor"
										stroke-width="1.8"
										stroke-linecap="round"
										stroke-linejoin="round"
									/></svg
								>
							{:else}
								<span class="core size-1.5 rounded-full" />
							{/if}
						</span>
						<span class="label whitespace-nowrap text-xs"
							>{step.label}{#if step.key === 'run' && stage.total}<span
									class="tm-num ml-1 font-normal opacity-70">{stage.done ?? 0}/{stage.total}</span
								>{/if}</span
						>
					</li>
					{#if i < STAGE_STEPS.length - 1}
						<li
							class="bar mx-1.5 h-px min-w-3 flex-1"
							data-state={state === 'done' ? 'done' : 'pending'}
							aria-hidden="true"
						/>
					{/if}
				{/each}
			</ol>
		{/if}
		<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
			<span class="kind shrink-0 text-xs font-semibold" data-stage-label>{stage.label ?? ''}</span>
			<p
				class="min-w-0 flex-1 basis-60 break-words text-sm text-gray-800 dark:text-gray-100"
				data-stage-now
			>
				<span class={moving ? 'tm-shimmer' : ''}>{stage.now ?? ''}</span>
			</p>
			{#if spent !== null || etaText || after}
				<span
					class="tm-num shrink-0 text-xs text-gray-500 dark:text-gray-400"
					title={stage.eta?.basis ?? after?.basis ?? ''}
					data-stage-clock
				>
					{#if spent !== null}已用 {elapsed(spent)}{/if}{#if spent !== null && etaText}{' · '}{/if}{#if etaText}<b
							class="font-semibold text-gray-800 dark:text-gray-100"
							data-stage-eta>{etaText}</b
						>{/if}{#if after}批准后预计 <b
							class="font-semibold text-gray-800 dark:text-gray-100"
							data-stage-eta>{formatEta(after.seconds, after.high)}</b
						> 出结果{/if}
				</span>
			{/if}
		</div>
		{#if lines.length > 1}
			<ul class="mt-2 flex list-none flex-col gap-1 p-0" aria-label="正在执行的成员" data-stage-lines>
				{#each lines as l (l.key)}
					<li class="flex min-w-0 items-center gap-2 font-mono text-[11px]">
						<span class="shrink-0 font-semibold text-gray-400">#{l.key}</span>
						<span class="shrink-0 text-gray-500">{l.member}</span>
						<span class="min-w-0 flex-1 truncate text-gray-700 dark:text-gray-200">{l.text}</span>
						{#if l.since}
							<span
								class="tm-num shrink-0 text-gray-400"
								title={l.typical ? `这类任务在本机通常 ${formatEta(l.typical, l.typical_high)}` : ''}
								>{elapsed($now - l.since)}{#if l.typical}<span class="opacity-70">
										/ 通常{formatEta(l.typical, l.typical_high).replace('约', '')}</span
									>{/if}</span
							>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
		{#if moving && stage.eta?.basis}
			<p class="mt-1.5 text-[11px] text-gray-400 dark:text-gray-500" data-stage-basis>
				{stage.eta.basis}{stage.key === 'running' ? '（含整理结果和验收）' : ''}
			</p>
		{:else if after?.basis}
			<p class="mt-1.5 text-[11px] text-gray-400 dark:text-gray-500" data-stage-basis>
				{after.basis}（含整理结果和验收）
			</p>
		{/if}
	</section>
{/if}

<style>
	.stage {
		--stage-tone: var(--tm-accent);
	}
	/* Wherever it sits (a chat reply's Markdown styles too): steps are not a numbered list. */
	.stage :global(li) {
		list-style: none;
	}
	.stage li::marker {
		content: none;
	}
	.stage[data-tone='attention'] {
		--stage-tone: var(--tm-violet);
	}
	.stage[data-tone='paused'],
	.stage[data-tone='waiting'] {
		--stage-tone: var(--tm-warn);
	}
	.stage[data-tone='done'] {
		--stage-tone: var(--tm-done);
	}
	.stage[data-tone='ended'] {
		--stage-tone: var(--tm-muted);
	}
	.kind {
		color: hsl(var(--stage-tone));
	}
	.dot {
		border: 1.5px solid hsl(var(--tm-line-strong));
		color: hsl(var(--tm-muted));
	}
	.step[data-state='done'] .dot {
		border-color: transparent;
		background: hsl(var(--tm-done));
		color: white;
	}
	.step[data-state='active'] .dot {
		border-color: hsl(var(--stage-tone));
		color: hsl(var(--stage-tone));
	}
	.step[data-state='active'] .core {
		background: currentColor;
	}
	.stage[data-tone='moving'] .step[data-state='active'] .core,
	.stage[data-tone='attention'] .step[data-state='active'] .core {
		animation: stage-beat 1.6s var(--tm-ease) infinite;
	}
	.label {
		color: hsl(var(--tm-muted));
	}
	.step[data-state='active'] .label {
		color: hsl(var(--tm-ink));
		font-weight: 600;
	}
	.step[data-state='done'] .label {
		color: hsl(var(--tm-ink) / 0.75);
	}
	.bar {
		background: hsl(var(--tm-line-strong));
	}
	.bar[data-state='done'] {
		background: hsl(var(--tm-done) / 0.6);
	}
	@keyframes stage-beat {
		50% {
			transform: scale(1.7);
			opacity: 0.55;
		}
	}
	@media (max-width: 480px) {
		.step:not([data-state='active']) .label {
			display: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.stage .core {
			animation: none !important;
		}
	}
</style>

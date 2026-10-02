<script lang="ts">
	import { createEventDispatcher, onMount, tick } from 'svelte';

	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import RunnerBadge from './RunnerBadge.svelte';
	import { now, shortAgo, timeAgo } from './clock';
	import { avatarKind, toneOf } from './model';

	/** The lead and every member: who is on the team and what each one is doing right now —
	 *  the latest thing it did is shown live under its name. */
	export let lead: { name: string; role: string; status: string; note?: string; model?: string };
	export let members: {
		name: string;
		role: string;
		executor: string;
		status: string;
		focus?: string;
		currentKey?: string | null;
		currentTitle?: string | null;
		waitingFor?: string[];
		chosenRunner?: string;
		actualRunner?: string | null;
		assistant?: { name: string; emoji?: string } | null;
		activity?: { text: string; ts: number; type: string } | null;
	}[] = [];
	export let selected: string | null = null;
	export let layout: 'row' | 'list' = 'row';

	const dispatch = createEventDispatcher();

	// In a row that does not fit, the cut edge fades out and arrow buttons page through it
	// (a mouse has no easy sideways scroll).
	let rowEl: HTMLDivElement | null = null;
	let canLeft = false;
	let canRight = false;
	const measure = () => {
		if (!rowEl || layout !== 'row') {
			canLeft = canRight = false;
			return;
		}
		canLeft = rowEl.scrollLeft > 4;
		canRight = rowEl.scrollLeft + rowEl.clientWidth < rowEl.scrollWidth - 4;
	};
	const page = (dir: 1 | -1) => {
		if (!rowEl) return;
		const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
		rowEl.scrollBy({
			left: dir * Math.max(240, rowEl.clientWidth * 0.8),
			behavior: reduce ? 'auto' : 'smooth'
		});
	};
	onMount(() => {
		if (typeof ResizeObserver === 'undefined' || !rowEl) return;
		const observer = new ResizeObserver(measure);
		observer.observe(rowEl);
		return () => observer.disconnect();
	});
	$: members, layout, tick().then(measure);
</script>

<div class="strip relative" class:fade-left={canLeft} class:fade-right={canRight}>
	<div
		bind:this={rowEl}
		on:scroll={measure}
		class={layout === 'row'
			? 'row tm-scroll -mx-1 flex gap-2.5 overflow-x-auto px-1 pt-1 pb-2'
			: 'flex flex-col gap-2'}
		role="list"
		aria-label="团队成员"
	>
		<div
			role="listitem"
			class="lead tm-card flex items-center gap-3 px-3 py-2.5 {layout === 'row'
				? 'min-w-[210px] shrink-0'
				: ''}"
		>
			<TeamAvatar kind="lead" status={lead.status} size={38} />
			<div class="min-w-0">
				<div class="flex items-center gap-1.5">
					<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100"
						>{lead.name}</span
					>
					<StatusChip status={lead.status} />
				</div>
				<div class="truncate text-xs text-gray-500 dark:text-gray-400">
					{lead.role}{lead.note ? ` · ${lead.note}` : ''}
				</div>
				{#if lead.model}
					<div class="truncate font-mono text-[11px] text-gray-400">{lead.model}</div>
				{/if}
			</div>
		</div>
		{#each members as member (member.name)}
			{@const working = toneOf(member.status) === 'run'}
			<div role="listitem" class={layout === 'row' ? 'shrink-0' : ''}>
				<button
					type="button"
					class="member tm-card tm-hover flex h-full items-start gap-3 px-3 py-2.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400
			{selected === member.name ? 'is-selected' : ''} {working ? 'tm-live' : ''}
			{layout === 'row' ? 'w-[268px]' : 'w-full'}"
					aria-pressed={selected === member.name}
					on:click={() => dispatch('select', selected === member.name ? null : member.name)}
					data-member={member.name}
				>
					<TeamAvatar kind={avatarKind(member)} status={member.status} size={38} />
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-1.5">
							<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100"
								>{member.name}</span
							>
							<span class="ml-auto shrink-0"><StatusChip status={member.status} /></span>
						</div>
						<div
							class="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400"
						>
							<span
								class="min-w-0 truncate"
								title={member.assistant ? `助手模板：${member.assistant.name}` : ''}
								>{member.assistant?.emoji ? `${member.assistant.emoji} ` : ''}{member.role}</span
							>
							<span class="min-w-0 shrink-[2]"
								><RunnerBadge
									chosen={member.chosenRunner ?? member.executor}
									actual={member.actualRunner ?? member.executor}
								/></span
							>
						</div>
						{#if member.currentKey}
							<div class="mt-1 truncate text-xs font-medium text-sky-700 dark:text-sky-300">
								#{member.currentKey}
								{member.currentTitle ?? ''}
							</div>
						{:else if member.waitingFor?.length}
							<div class="mt-1 truncate text-xs text-amber-600 dark:text-amber-400">
								等 {member.waitingFor.join('、')} 完成
							</div>
						{/if}
						{#if member.activity}
							<div
								class="activity mt-1 flex min-w-0 items-center gap-1.5 font-mono text-[11px]"
								title={member.activity.text}
								data-member-activity
							>
								<span
									class="shrink-0 {working ? 'text-sky-500' : 'text-gray-400'}"
									aria-hidden="true">›</span
								>
								<span
									class="min-w-0 truncate {working
										? 'text-gray-700 dark:text-gray-200 tm-caret'
										: 'text-gray-400 dark:text-gray-500'}">{member.activity.text}</span
								>
								<span
									class="tm-num ml-auto shrink-0 text-gray-400 dark:text-gray-500"
									title={timeAgo(member.activity.ts, $now)}
									>{shortAgo(member.activity.ts, $now)}</span
								>
							</div>
						{/if}
					</div>
				</button>
			</div>
		{/each}
	</div>
	{#if canLeft}
		<button
			type="button"
			class="pager tm-glass absolute left-0 top-[calc(50%-4px)] size-8 -translate-y-1/2 place-items-center rounded-full text-gray-600 dark:text-gray-300"
			aria-label="向左看更多成员"
			tabindex="-1"
			on:click={() => page(-1)}
			><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
				><path
					d="m10 3.5-4.5 4.5 4.5 4.5"
					stroke="currentColor"
					stroke-width="1.7"
					stroke-linecap="round"
					stroke-linejoin="round"
				/></svg
			></button
		>
	{/if}
	{#if canRight}
		<button
			type="button"
			class="pager tm-glass absolute right-0 top-[calc(50%-4px)] size-8 -translate-y-1/2 place-items-center rounded-full text-gray-600 dark:text-gray-300"
			aria-label="向右看更多成员"
			tabindex="-1"
			on:click={() => page(1)}
			><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
				><path
					d="m6 3.5 4.5 4.5-4.5 4.5"
					stroke="currentColor"
					stroke-width="1.7"
					stroke-linecap="round"
					stroke-linejoin="round"
				/></svg
			></button
		>
	{/if}
</div>

<style>
	.fade-right .row {
		mask-image: linear-gradient(90deg, #000 calc(100% - 56px), transparent);
	}
	.fade-left .row {
		mask-image: linear-gradient(90deg, transparent, #000 56px);
	}
	.fade-left.fade-right .row {
		mask-image: linear-gradient(90deg, transparent, #000 56px, #000 calc(100% - 56px), transparent);
	}
	.pager {
		display: none;
		box-shadow: var(--tm-shadow);
	}
	.pager:hover {
		color: hsl(var(--tm-ink));
	}
	@media (hover: hover) {
		.pager {
			display: grid;
		}
	}
	.lead {
		background: radial-gradient(120% 140% at 0% 0%, hsl(250 90% 65% / 0.1), transparent 60%),
			hsl(var(--tm-surface));
	}
	.member.is-selected {
		border-color: hsl(var(--tm-accent) / 0.55);
		box-shadow:
			0 0 0 3px hsl(var(--tm-accent) / 0.12),
			var(--tm-shadow);
	}
	.activity .tm-caret {
		display: inline-block;
	}
</style>

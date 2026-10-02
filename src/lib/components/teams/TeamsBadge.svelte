<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	import { listTeams } from '$lib/apis/teams';

	/**
	 * Sidebar hint for the 协作台 entry: how many of your teams are at work right now (a live
	 * count), and a violet dot when a plan waits for your approval. Reads the list once a minute
	 * while the page is visible; quiet when nothing is going on or the feature is unavailable.
	 */
	export let compact = false;

	const EVERY_MS = 60000;
	let active = 0;
	let review = 0;
	let timer: ReturnType<typeof setInterval> | null = null;
	let stopped = false;

	const load = async () => {
		if (stopped || typeof localStorage === 'undefined' || !localStorage.token) return;
		if (document.visibilityState === 'hidden') return;
		try {
			const { teams } = await listTeams(localStorage.token);
			active = teams.filter(
				(t) =>
					['planning', 'starting'].includes(t.status) ||
					(t.status === 'running' && !['completed', 'stopped'].includes(t.phase ?? ''))
			).length;
			review = teams.filter((t) => t.status === 'plan_ready').length;
		} catch (e) {
			// 404 = feature off, 403 = no Hermes connection: nothing to show, stop asking.
			if ([403, 404].includes((e as { status?: number })?.status ?? 0)) stopped = true;
		}
	};
	const onVisible = () => document.visibilityState === 'visible' && load();

	onMount(() => {
		load();
		timer = setInterval(load, EVERY_MS);
		document.addEventListener('visibilitychange', onVisible);
	});
	onDestroy(() => {
		if (timer) clearInterval(timer);
		if (typeof document !== 'undefined')
			document.removeEventListener('visibilitychange', onVisible);
	});
</script>

{#if compact}
	{#if active || review}
		<span
			class="absolute right-1 top-1 size-2 rounded-full ring-2 ring-white dark:ring-gray-900 {active
				? 'teams-badge-live bg-sky-500'
				: 'bg-violet-500'}"
			aria-label={active ? `${active} 个协作任务进行中` : `${review} 个计划等你批准`}
			data-teams-badge
		/>
	{/if}
{:else if active || review}
	<span class="ml-auto flex items-center gap-1.5" data-teams-badge>
		{#if review}
			<span
				class="size-1.5 rounded-full bg-violet-500"
				title="{review} 个计划等你批准"
				aria-label="{review} 个计划等你批准"
			/>
		{/if}
		{#if active}
			<span
				class="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-1.5 py-px text-[11px] font-semibold tabular-nums text-sky-700 dark:text-sky-300"
				title="{active} 个协作任务进行中"
				><span
					class="teams-badge-live size-1.5 rounded-full bg-sky-500"
					aria-hidden="true"
				/>{active}</span
			>
		{/if}
	</span>
{/if}

<style>
	.teams-badge-live {
		animation: teams-badge 1.8s ease-in-out infinite;
	}
	@keyframes teams-badge {
		50% {
			opacity: 0.35;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.teams-badge-live {
			animation: none;
		}
	}
</style>

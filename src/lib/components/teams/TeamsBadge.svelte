<script context="module" lang="ts">
	// What each team looked like at the last read, kept across remounts (the sidebar swaps its
	// expanded / collapsed entry), so a change is announced once and only when it happens.
	const seen = new Map<string, string>();
	let primed = false;
</script>

<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { listTeams, type Team } from '$lib/apis/teams';
	import { APP_NAME, WEBUI_BASE_URL } from '$lib/constants';
	import { isLastActiveTab, settings } from '$lib/stores';
	import NotificationToast from '$lib/components/NotificationToast.svelte';
	import { setModeLive } from '$lib/components/scifi/mode-relay';
	import { chatStatesOf, teamChatStates } from './live';

	/**
	 * Sidebar hint for the 协作台 entry: how many of your teams are at work right now (a live
	 * count), and a violet dot when a plan waits for your approval. Teams work in the background,
	 * so when one finishes, needs you, or has its plan ready, this says so (the app's toast, and a
	 * browser notification when those are on) — unless you are looking at that team already.
	 */
	export let compact = false;

	const ACTIVE_MS = 30000;
	const IDLE_MS = 60000;
	let active = 0;
	let review = 0;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let stopped = false;
	let destroyed = false;

	const stateOf = (t: Team) =>
		t.status === 'running' ? `running:${t.phase ?? 'running'}` : t.status;
	const isActive = (t: Team) =>
		['planning', 'starting'].includes(t.status) ||
		(t.status === 'running' && !['completed', 'stopped'].includes(t.phase ?? ''));

	const NEWS: Record<string, string> = {
		plan_ready: '计划好了，等你批准',
		plan_failed: '计划没做出来',
		'running:completed': '全部任务完成，负责人在写结论',
		'running:attention': '有任务需要你处理'
	};

	// the mode dock on the other pages shows the same count
	$: setModeLive('teams', active);

	const announce = (team: Team, state: string) => {
		const text = NEWS[state];
		if (!text) return;
		if (location.pathname.startsWith(`/teams/${team.id}`)) return;
		const title = `协作台 · ${team.title}`;
		const href =
			state === 'running:completed' ? `/teams/${team.id}/conclusion` : `/teams/${team.id}`;
		if ($isLastActiveTab && ($settings?.notificationEnabled ?? false)) {
			try {
				new Notification(`${title} | ${APP_NAME}`, {
					body: text,
					icon: `${WEBUI_BASE_URL}/static/favicon.png`
				});
			} catch {
				/* notifications unavailable */
			}
		}
		toast.custom(NotificationToast, {
			componentProps: { onClick: () => goto(href), content: text, title },
			duration: 15000,
			unstyled: true
		});
	};

	const load = async () => {
		if (stopped || destroyed || typeof localStorage === 'undefined' || !localStorage.token) return;
		if (document.visibilityState === 'hidden') return schedule();
		try {
			const { teams } = await listTeams(localStorage.token);
			active = teams.filter(isActive).length;
			review = teams.filter((t) => t.status === 'plan_ready').length;
			// each team's chat in the history shows what the team is doing
			teamChatStates.set(chatStatesOf(teams));
			for (const t of teams) {
				const state = stateOf(t);
				const before = seen.get(t.id);
				if (primed && before !== undefined && before !== state) announce(t, state);
				seen.set(t.id, state);
			}
			primed = true;
		} catch (e) {
			// 404 = feature off, 403 = no Hermes connection: nothing to show, stop asking.
			if ([403, 404].includes((e as { status?: number })?.status ?? 0)) stopped = true;
		}
		schedule();
	};
	const schedule = () => {
		if (timer) clearTimeout(timer);
		if (stopped || destroyed) return;
		timer = setTimeout(load, active ? ACTIVE_MS : IDLE_MS);
	};
	const onVisible = () => document.visibilityState === 'visible' && load();

	onMount(() => {
		load();
		document.addEventListener('visibilitychange', onVisible);
	});
	onDestroy(() => {
		destroyed = true;
		if (timer) clearTimeout(timer);
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

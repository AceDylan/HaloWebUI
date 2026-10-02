<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	import './teams.css';
	import { getTeam, type Team, type TeamStage } from '$lib/apis/teams';
	import StageRail from './StageRail.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { PHASE_LABEL } from './model';

	/**
	 * A team started from this chat (派发方式「协作台」): where it is, live — the same stage rail as
	 * the 协作台 page — with the way there, and to its result once it is written (the result
	 * itself comes back into the chat as its own reply).
	 */
	export let teamId: string;

	const POLL_MS = 5000;
	const POLL_HIDDEN_MS = 30000;
	const SETTLED = new Set(['done', 'stopped', 'plan_failed', 'start_failed', 'cancelled']);

	let team: Team | null = null;
	let stage: TeamStage | null = null;
	let error = '';
	let timer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	$: key = stage?.key ?? '';
	$: settled = SETTLED.has(key) || (team?.status === 'running' && team.phase === 'stopped');
	$: chip =
		key === 'done'
			? 'done'
			: key === 'approval' || key === 'attention'
				? 'waiting_user'
				: ['plan_failed', 'start_failed'].includes(key)
					? 'failed'
					: ['stopped', 'cancelled'].includes(key)
						? 'stopped'
						: 'running';
	$: chipLabel =
		key === 'done'
			? '已完成'
			: (stage?.label ?? PHASE_LABEL[team?.status ?? ''] ?? '协作台');

	const load = async () => {
		try {
			const data = await getTeam(localStorage.token, teamId);
			team = data.team;
			stage = data.stage ?? stage;
			error = '';
		} catch (e) {
			error = `${(e as any)?.message ?? e}`;
			if ((e as any)?.status === 404) return; // deleted: nothing more to read
		}
		schedule();
	};

	const schedule = () => {
		if (timer) clearTimeout(timer);
		if (destroyed || settled) return;
		const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
		timer = setTimeout(load, hidden ? POLL_HIDDEN_MS : POLL_MS);
	};

	const onVisibility = () => {
		if (document.visibilityState === 'visible' && !settled) load();
	};

	onMount(() => {
		load();
		document.addEventListener('visibilitychange', onVisibility);
	});
	onDestroy(() => {
		destroyed = true;
		if (timer) clearTimeout(timer);
		if (typeof document !== 'undefined')
			document.removeEventListener('visibilitychange', onVisibility);
	});
</script>

<!-- not-prose: the chat's Markdown typography must not number the rail's steps -->
<div class="not-prose my-2 flex max-w-2xl flex-col gap-2" data-teams-ui data-team-chat-card={teamId}>
	<div class="flex min-w-0 items-center gap-2.5">
		<TeamAvatar kind="lead" status={settled ? (key === 'done' ? 'done' : 'idle') : 'running'} size={28} />
		<div class="min-w-0 flex-1">
			<div class="flex min-w-0 items-center gap-2">
				<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100"
					>{team?.title ?? '协作任务'}</span
				>
				{#if team}<span class="shrink-0"><StatusChip status={chip} label={chipLabel} size="sm" /></span
					>{/if}
			</div>
			<div class="truncate text-[11px] text-gray-500 dark:text-gray-400">
				协作台 · {team?.member_count ? `${team.member_count} 位成员` : '负责人在组队'}{team?.task_count
					? ` · ${team.task_count} 个任务`
					: ''}
			</div>
		</div>
		<a
			href="/teams/{teamId}"
			class="tm-btn-ghost shrink-0 !text-xs"
			data-team-chat-open
			>{key === 'approval' ? '去批准' : key === 'attention' ? '去处理' : '打开协作台'}</a
		>
	</div>
	{#if stage && key !== 'done'}
		<StageRail {stage} />
	{:else if key === 'done'}
		<div
			class="tm-card-quiet flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5 text-xs text-gray-600 dark:text-gray-300"
			data-team-chat-done
		>
			<span class="font-medium text-emerald-700 dark:text-emerald-300">完整结果已整理好</span>
			<span class="min-w-0 flex-1">已发回这个对话（在下面）；也可以在协作台看结果页和产出文件。</span>
			<a href="/teams/{teamId}/conclusion" class="shrink-0 text-sky-700 hover:underline dark:text-sky-300"
				>结果页 →</a
			>
		</div>
	{:else if error}
		<div class="text-xs text-amber-700 dark:text-amber-300">读不到团队的进度：{error}</div>
	{:else}
		<div class="tm-card-quiet h-16 animate-pulse" aria-busy="true" />
	{/if}
</div>

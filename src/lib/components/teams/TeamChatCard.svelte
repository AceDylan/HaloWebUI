<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import './teams.css';
	import { chatId as currentChatId } from '$lib/stores';
	import { followUpTeamConclusion, getTeam, type Team, type TeamStage } from '$lib/apis/teams';
	import StageRail from './StageRail.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import TeamResultBar from './TeamResultBar.svelte';
	import { avatarKind, PHASE_LABEL } from './model';

	/**
	 * A 协作台 team in its chat: who is on it and where it is, live — the same stage rail as the
	 * 协作台 page — with the way there (to approve, to step in, to watch), and once the result is
	 * written, the way to it: in this chat (it comes back as its own reply) and on the 协作台.
	 */
	export let teamId: string;
	/** The chat around the card: whether the team's result is already in it, and where. */
	export let history: { messages?: Record<string, any> } | null = null;

	const POLL_MS = 5000;
	const POLL_HIDDEN_MS = 30000;
	const SETTLED = new Set(['done', 'stopped', 'plan_failed', 'start_failed', 'cancelled']);
	const ENDED = new Set(['stopped', 'plan_failed', 'start_failed', 'cancelled']);

	let team: Team | null = null;
	let stage: TeamStage | null = null;
	let error = '';
	let gone = false;
	let bringing = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	$: key = stage?.key ?? '';
	$: settled = gone || SETTLED.has(key) || (team?.status === 'running' && team.phase === 'stopped');
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
		key === 'done' ? '已完成' : (stage?.label ?? PHASE_LABEL[team?.status ?? ''] ?? '协作台');
	$: action =
		key === 'approval'
			? '去批准'
			: key === 'attention'
				? '去处理'
				: ['plan_failed', 'start_failed'].includes(key)
					? '去看看'
					: '打开协作台';
	$: roster = team?.roster ?? [];
	$: facts = [
		team?.member_count ? `负责人 + ${team.member_count} 位成员` : '负责人在组队',
		team?.task_count ? `${team.task_count} 个任务` : '',
		team?.project?.name ? `在 ${team.project.name} 里做` : '',
		team?.inputs?.length ? `附带 ${team.inputs.length} 个文件` : ''
	].filter(Boolean);

	// The team's result posted into this chat: the reply under its 「协作任务结论」 notice (the
	// newest version when it was written more than once).
	const findResult = (h: typeof history, id: string): string | null => {
		const prefix = `team:${id}:`;
		let found: { id: string; at: number } | null = null;
		for (const m of Object.values(h?.messages ?? {})) {
			const runId = m?.hermes_notice?.run_id;
			const reply = m?.childrenIds?.[0];
			if (m?.role !== 'user' || typeof runId !== 'string' || !runId.startsWith(prefix) || !reply)
				continue;
			const at = Number(m.timestamp ?? 0);
			if (!found || at >= found.at) found = { id: reply, at };
		}
		return found?.id ?? null;
	};
	$: resultId = findResult(history, teamId);

	const jump = () => {
		document
			.getElementById(`message-${resultId}`)
			?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	};

	// 「把结果放进这个对话」: a team that finished before its chat existed, or whose result did not
	// make it in (the chat was busy).
	const bring = async () => {
		if (bringing) return;
		bringing = true;
		try {
			const out = await followUpTeamConclusion(localStorage.token, teamId);
			if (out.busy) toast.info('这个对话正在回答别的问题，结果稍后会补进来');
			if (out.chat_id && out.chat_id !== $currentChatId) await goto(`/c/${out.chat_id}`);
		} catch (e) {
			toast.error(`${(e as Error)?.message ?? e}`);
		} finally {
			bringing = false;
		}
	};

	const load = async () => {
		try {
			const data = await getTeam(localStorage.token, teamId);
			team = data.team;
			stage = data.stage ?? stage;
			error = '';
		} catch (e) {
			if ((e as any)?.status === 404) {
				gone = true; // deleted on the 协作台: nothing more to read
				return;
			}
			error = `${(e as any)?.message ?? e}`;
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
<div
	class="not-prose my-2 flex max-w-2xl flex-col gap-2"
	data-teams-ui
	data-team-chat-card={teamId}
	data-team-chat-state={gone ? 'gone' : key || 'loading'}
>
	{#if gone}
		<div
			class="tm-card-quiet flex items-center gap-2.5 px-3.5 py-2.5 text-xs text-gray-500 dark:text-gray-400"
			data-team-chat-gone
		>
			<TeamAvatar kind="lead" size={22} />
			这个协作任务已经在协作台删除了；对话和发回来的结果都还在。
		</div>
	{:else}
		<div class="flex min-w-0 items-center gap-2.5">
			<TeamAvatar
				kind="lead"
				status={settled
					? key === 'done'
						? 'done'
						: 'idle'
					: key === 'approval'
						? 'waiting_user'
						: 'running'}
				size={30}
			/>
			<div class="min-w-0 flex-1">
				<div class="flex min-w-0 items-center gap-2">
					<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100"
						>{team?.title ?? '协作任务'}</span
					>
					{#if team}<span class="shrink-0"
							><StatusChip status={chip} label={chipLabel} size="sm" /></span
						>{/if}
				</div>
				<div class="flex min-w-0 items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
					{#if roster.length}
						<span class="flex shrink-0 -space-x-1" aria-hidden="true">
							{#each roster.slice(0, 5) as m}
								<span class="stack" title="{m.name} · {m.role}"
									><TeamAvatar kind={avatarKind(m)} size={16} /></span
								>
							{/each}
						</span>
					{/if}
					<span class="truncate">协作台 · {facts.join(' · ')}</span>
				</div>
			</div>
			<a
				href="/teams/{teamId}"
				class="{key === 'approval' || key === 'attention'
					? 'tm-btn-primary !gap-1 !px-2.5 !py-1 !text-xs'
					: 'tm-btn-ghost !text-xs'} shrink-0"
				data-team-chat-open>{action}</a
			>
		</div>
		{#if key === 'done'}
			<div class="tm-card-quiet flex flex-col gap-2 px-3.5 py-2.5" data-team-chat-done>
				<div
					class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-gray-600 dark:text-gray-300"
				>
					<span class="font-medium text-gray-900 dark:text-gray-100">完整结果已整理好</span>
					{#if resultId}
						<span class="min-w-0 flex-1">已发回这个对话，可以接着追问。</span>
						<button
							type="button"
							class="shrink-0 font-medium text-sky-700 hover:underline dark:text-sky-300"
							on:click={jump}
							data-team-chat-jump>看结果 ↓</button
						>
					{:else}
						<span class="min-w-0 flex-1">还没放进这个对话。</span>
						<button
							type="button"
							class="shrink-0 font-medium text-sky-700 hover:underline disabled:opacity-60 dark:text-sky-300"
							disabled={bringing}
							on:click={bring}
							data-team-chat-bring>{bringing ? '正在放进来…' : '把结果放进这个对话'}</button
						>
					{/if}
				</div>
				<TeamResultBar {teamId} team={false} />
			</div>
		{:else if stage}
			<StageRail {stage} />
			{#if ENDED.has(key) && team?.error}
				<div class="text-xs text-gray-500 dark:text-gray-400">{team.error}</div>
			{/if}
		{:else if error}
			<div class="text-xs text-amber-700 dark:text-amber-300">读不到团队的进度：{error}</div>
		{:else}
			<div class="tm-card-quiet h-16 animate-pulse" aria-busy="true" />
		{/if}
	{/if}
</div>

<style>
	.stack {
		border-radius: 9999px;
		box-shadow: 0 0 0 1.5px hsl(var(--tm-surface));
	}
</style>

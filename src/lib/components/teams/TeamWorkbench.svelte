<script lang="ts">
	import { getContext, onDestroy, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import './teams.css';
	import { mobile, showSidebar, WEBUI_NAME } from '$lib/stores';
	import {
		approveTeam,
		cancelTeam,
		checkRunners,
		controlTeam,
		editTeamPlan,
		getTeam,
		getTeamEvents,
		getTeamsMeta,
		replanTeam,
		type LiveSnapshot,
		type Team,
		type TeamEvent,
		type TeamExecutor,
		type TeamsMeta
	} from '$lib/apis/teams';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import CommFeed from './CommFeed.svelte';
	import ConclusionView from './ConclusionView.svelte';
	import RunnerBadge from './RunnerBadge.svelte';
	import Inspector from './Inspector.svelte';
	import MemberStrip from './MemberStrip.svelte';
	import PlanReview from './PlanReview.svelte';
	import ReplayBar from './ReplayBar.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamBoard from './TeamBoard.svelte';
	import TeamProgress from './TeamProgress.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { elapsed, now } from './clock';
	import {
		countStates,
		foldStates,
		latestActivity,
		layoutTasks,
		leadStatus,
		liveStates,
		memberStatus,
		mergeEvents,
		openParents,
		PHASE_LABEL,
		phaseAt,
		statusLabel,
		taskRunner,
		toneOf
	} from './model';

	export let teamId: string;

	const POLL_VISIBLE_MS = 2500;
	const POLL_PLANNING_MS = 2000;
	const POLL_HIDDEN_MS = 30000;
	const SNAPSHOT_EVERY = 4;

	let team: Team | null = null;
	let live: LiveSnapshot | null = null;
	let liveError: string | null = null;
	let loadError: string | null = null;
	let events: TeamEvent[] = [];
	let after = 0;
	let reconcile: { key: string; history: string | null; live: string }[] = [];
	let truncated = false;
	let replayIndex: number | null = null;
	let selectedTask: string | null = null;
	let selectedMember: string | null = null;
	let mobileTab: 'tasks' | 'members' | 'feed' | 'conclusion' = 'tasks';
	let asideTab: 'feed' | 'conclusion' = 'feed';
	let asideTouched = false;
	let busy = false;
	let showStop = false;
	let disconnected = 0;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let ticks = 0;
	let destroyed = false;
	let finishedFetches = 0;
	let refreshKey = 0;
	let registry: TeamsMeta['registry'] | null = null;
	let registryError = '';
	let checking = false;
	let metaRequested = false;
	let goalOpen = false;

	// --- derived view: live = authoritative snapshot, replay = fold of events up to the cursor ---
	$: tasks = live?.tasks ?? [];
	$: replay = replayIndex !== null;
	$: states = replay ? foldStates(tasks, events, replayIndex ?? 0) : liveStates(tasks);
	$: shownEvents = replay ? events.slice(0, (replayIndex ?? 0) + 1) : events;
	$: cursorSeq = replay ? (events[replayIndex ?? 0]?.seq ?? 0) : null;
	$: phase = replay
		? phaseAt(states, events, replayIndex ?? 0)
		: (live?.team.phase ?? team?.phase ?? 'running');
	$: counts = countStates(states);
	$: keyOf = new Map(tasks.map((t) => [t.id, t.key]));
	$: planMembers =
		live?.members ??
		(team?.plan?.members ?? []).map((m) => ({
			...m,
			status: 'idle',
			task_ids: [],
			current_task: null
		}));
	$: activity = latestActivity(
		shownEvents,
		planMembers.map((m) => m.name)
	);
	$: memberViews = planMembers.map((m) => {
		const mine = tasks.filter((t) => t.member === m.name);
		const mineStates = mine.map(
			(t) => states.get(t.id) ?? { status: 'pending', sub_status: 'pending' }
		);
		const running = mine.find((t) =>
			['running', 'review', 'quota_wait', 'waiting_user'].includes(
				states.get(t.id)?.sub_status ?? ''
			)
		);
		const waiting = mine.find((t) => states.get(t.id)?.sub_status === 'waiting_deps');
		const current =
			running ??
			mine.find((t) => !['done', 'archived'].includes(states.get(t.id)?.status ?? t.status)) ??
			mine[mine.length - 1];
		return {
			...m,
			status: memberStatus(mineStates),
			currentKey: running?.key ?? null,
			currentTitle: running?.title ?? null,
			waitingFor: waiting ? openParents(waiting, states).map((p) => `#${keyOf.get(p) ?? p}`) : [],
			// The member's chosen runner and the one on its current (or next / last) task.
			chosenRunner: m.executor,
			actualRunner: current?.executor ?? m.runner ?? m.executor,
			activity: activity.get(m.name) ?? null
		};
	});
	$: lead = {
		name: live?.team.lead?.name ?? 'team-lead',
		role: '负责人',
		status:
			team?.status === 'running'
				? leadStatus(phase)
				: team?.status === 'planning'
					? 'running'
					: 'idle',
		note: PHASE_LABEL[phase] ?? '',
		model: leadModel
	};
	$: titles = new Map(tasks.map((t) => [t.id, t.key]));
	$: conclusionBrief = live?.team.conclusion;
	$: leadModel =
		live?.team.lead_model?.model ?? team?.plan?.lead_model?.model ?? team?.plan?.lead?.model ?? '';
	$: fallbacks = tasks.filter((t) => taskRunner(t).changed).length;
	// When the team finishes, the conclusion becomes the default view beside the board (once).
	$: if (!replay && phase === 'completed' && !asideTouched && asideTab !== 'conclusion')
		asideTab = 'conclusion';
	$: stopped = phase === 'stopped' || live?.team.state === 'stopped';
	$: finished = phase === 'completed' || stopped;
	$: running = team?.status === 'running';
	$: headerStatus = !team
		? null
		: team.status === 'running'
			? ({ completed: 'done', attention: 'waiting_user', paused: 'paused', stopped: 'stopped' }[
					phase
				] ?? 'running')
			: team.status === 'planning'
				? 'running'
				: team.status === 'plan_ready'
					? 'waiting_user'
					: team.status === 'cancelled'
						? 'stopped'
						: team.status.endsWith('failed')
							? 'failed'
							: 'queued';
	$: headerLabel = team
		? (PHASE_LABEL[team.status === 'running' ? phase : team.status] ?? team.status)
		: '';
	$: pageTitle = team
		? `${running && !finished && counts.total ? `(${counts.done}/${counts.total}) ` : ''}${team.title}`
		: '协作台';
	$: layers = (() => {
		const layout = layoutTasks(tasks);
		const out: (typeof tasks)[] = [];
		for (const t of tasks) {
			const d = layout.positions.get(t.id)?.depth ?? 0;
			(out[d] ??= []).push(t);
		}
		return out;
	})();

	// --- loading / polling -------------------------------------------------------------------
	const schedule = (ms?: number) => {
		if (timer) clearTimeout(timer);
		if (destroyed) return;
		const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
		const base =
			team?.status === 'planning' || team?.status === 'starting'
				? POLL_PLANNING_MS
				: POLL_VISIBLE_MS;
		const backoff = disconnected ? Math.min(30000, 2500 * 2 ** Math.min(disconnected, 4)) : 0;
		timer = setTimeout(poll, ms ?? (hidden ? POLL_HIDDEN_MS : Math.max(base, backoff)));
	};

	const fetchTeam = async () => {
		const data = await getTeam(localStorage.token, teamId);
		team = data.team;
		live = data.live ?? live;
		liveError = data.live_error;
	};

	const fetchEvents = async () => {
		let got = 0;
		for (let page = 0; page < 20; page++) {
			const res = await getTeamEvents(localStorage.token, teamId, after, 1000);
			const before = events.length;
			events = mergeEvents(events, res.events);
			got += events.length - before;
			after = Math.max(after, res.next_after ?? after);
			reconcile = res.reconcile ?? [];
			truncated = !!res.truncated;
			if (!res.has_more) break;
		}
		return got;
	};

	const poll = async () => {
		try {
			if (!team || team.status !== 'running' || ticks % SNAPSHOT_EVERY === 0) {
				await fetchTeam();
			}
			if (team?.status === 'running') {
				const fresh = await fetchEvents();
				if (fresh > 0 && ticks % SNAPSHOT_EVERY !== 0) {
					await fetchTeam();
					refreshKey += 1;
				}
			}
			disconnected = 0;
			loadError = null;
		} catch (error) {
			disconnected += 1;
			if (!team) loadError = `${error?.message ?? error}`;
			if ((error as any)?.status === 404) {
				loadError = '协作任务不存在，或不属于你';
				return;
			}
		}
		ticks += 1;
		const settled =
			team && ['plan_ready', 'plan_failed', 'cancelled', 'start_failed'].includes(team.status);
		if (finished) finishedFetches += 1;
		// Nothing more happens on its own once finished — except the lead's conclusion being written.
		const conclusionPending =
			phase === 'completed' && !['ready', 'failed'].includes(live?.team.conclusion?.status ?? '');
		if (settled || (finished && finishedFetches > 2 && !conclusionPending)) return;
		schedule();
	};

	const restart = () => {
		ticks = 0;
		finishedFetches = 0;
		schedule(0);
	};

	const onVisibility = () => {
		if (document.visibilityState === 'visible') schedule(0);
	};

	onMount(() => {
		poll();
		document.addEventListener('visibilitychange', onVisibility);
	});
	onDestroy(() => {
		destroyed = true;
		if (timer) clearTimeout(timer);
		if (typeof document !== 'undefined')
			document.removeEventListener('visibilitychange', onVisibility);
	});

	// --- actions -------------------------------------------------------------------------------
	const act = async (fn: () => Promise<unknown>, ok?: string) => {
		if (busy) return;
		busy = true;
		try {
			await fn();
			if (ok) toast.success(ok);
		} catch (error) {
			toast.error(`${error?.message ?? error}`);
		} finally {
			busy = false;
			restart();
		}
	};

	const approve = () => act(() => approveTeam(localStorage.token, teamId), '已批准，成员开始工作');
	const replan = (feedback: string) => act(() => replanTeam(localStorage.token, teamId, feedback));
	const cancel = () => act(() => cancelTeam(localStorage.token, teamId), '已取消');
	const setExecutor = (name: string, executor: TeamExecutor, source: 'user' | 'auto') =>
		act(async () => {
			team = await editTeamPlan(localStorage.token, teamId, [{ name, executor, source }]);
		});

	// Runner availability for the plan review: loaded once, re-checked on request (which also lets
	// Hermes work out every member's runner again).
	const loadMeta = async () => {
		metaRequested = true;
		try {
			registry = (await getTeamsMeta(localStorage.token)).registry;
			registryError = '';
		} catch (error) {
			registryError = `${error?.message ?? error}`;
		}
	};
	$: if (!metaRequested && team && ['planning', 'plan_ready', 'start_failed'].includes(team.status))
		loadMeta();

	const recheck = async () => {
		if (checking) return;
		checking = true;
		try {
			registry = await checkRunners(localStorage.token);
			registryError = '';
			if (team && ['plan_ready', 'start_failed'].includes(team.status)) {
				team = await editTeamPlan(localStorage.token, teamId, []);
			}
		} catch (error) {
			registryError = `${error?.message ?? error}`;
		} finally {
			checking = false;
		}
	};
	const pauseDispatch = () =>
		act(
			() => controlTeam(localStorage.token, teamId, 'pause'),
			'已暂停派发：正在执行的成员会做完手上的任务，不再开始新任务'
		);
	const resumeDispatch = () =>
		act(() => controlTeam(localStorage.token, teamId, 'resume'), '已恢复派发');
	const stopAll = () =>
		act(
			() => controlTeam(localStorage.token, teamId, 'stop'),
			'已停止：正在执行的成员已结束，不会再自动启动'
		);

	const showConclusion = async () => {
		if ($mobile) {
			mobileTab = 'conclusion';
			selectedTask = null;
			selectedMember = null;
			return;
		}
		selectedTask = null;
		selectedMember = null;
		asideTab = 'conclusion';
		asideTouched = true;
	};

	const selectTask = async (id: string | null) => {
		selectedTask = id;
		if (id) selectedMember = null;
		if ($mobile && id) {
			await tick();
			document
				.getElementById('team-inspector')
				?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	};
	const selectMember = (name: string | null) => {
		selectedMember = name;
		if (name) selectedTask = null;
	};
	// Esc closes the task / member details (not while typing a note).
	const onKey = (e: KeyboardEvent) => {
		if (e.key !== 'Escape' || !(selectedTask || selectedMember)) return;
		const el = e.target as HTMLElement | null;
		if (el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable)) return;
		selectedTask = null;
		selectedMember = null;
	};
	const seek = (index: number | null) => {
		replayIndex = index === null ? null : Math.max(0, Math.min(index, events.length - 1));
	};
</script>

<svelte:head>
	<title>{pageTitle} · 协作台 | {$WEBUI_NAME}</title>
</svelte:head>
<svelte:window on:keydown={onKey} />

<div
	class="relative flex h-screen max-h-[100dvh] w-full max-w-full flex-col"
	data-team-workbench
	data-teams-ui
>
	<nav class="flex items-center gap-2 px-3 pt-2.5 pb-2 sm:px-4">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="cursor-pointer rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<a
			href="/teams"
			class="flex shrink-0 items-center whitespace-nowrap text-sm text-gray-500 transition hover:text-gray-900 dark:hover:text-gray-100"
			aria-label="回到协作台"
			><svg class="size-4 sm:hidden" viewBox="0 0 16 16" fill="none" aria-hidden="true"
				><path
					d="M10 3.5 5.5 8l4.5 4.5"
					stroke="currentColor"
					stroke-width="1.6"
					stroke-linecap="round"
					stroke-linejoin="round"
				/></svg
			><span class="max-sm:hidden">协作台</span></a
		>
		<span class="text-gray-300 max-sm:hidden dark:text-gray-700" aria-hidden="true">/</span>
		<h1
			class="tm-display min-w-0 truncate text-[15px] font-semibold text-gray-900 dark:text-gray-50"
			title={team?.title ?? ''}
		>
			{team?.title ?? '…'}
		</h1>
		{#if team && headerStatus}
			<span class="shrink-0"
				><StatusChip status={headerStatus} label={headerLabel} size="sm" /></span
			>
		{/if}
		<div class="ml-auto flex shrink-0 items-center gap-1.5">
			{#if running && (conclusionBrief?.status || finished)}
				<a
					href="/teams/{teamId}/conclusion"
					class="tm-btn-ghost hidden !text-emerald-700 sm:inline-flex dark:!text-emerald-300"
					data-header-conclusion
					><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
						><path
							d="M4 1.8h5.2L12.5 5v9.2H4V1.8Z"
							stroke="currentColor"
							stroke-width="1.4"
							stroke-linejoin="round"
						/><path
							d="M6 8h4.5M6 10.8h3"
							stroke="currentColor"
							stroke-width="1.4"
							stroke-linecap="round"
						/></svg
					>结论</a
				>
			{/if}
			{#if team?.chat_id}
				<a href="/c/{team.chat_id}" class="tm-btn-ghost hidden sm:inline-flex">返回对话</a>
			{/if}
			{#if running && !finished && !replay}
				{#if phase === 'paused'}
					<button
						type="button"
						class="tm-btn-ghost"
						disabled={busy}
						on:click={resumeDispatch}
						title="让派发器继续开始新的任务"
						><svg class="size-3" viewBox="0 0 12 12" aria-hidden="true"
							><path d="M3 1.8v8.4L10 6 3 1.8Z" fill="currentColor" /></svg
						><span class="max-sm:sr-only">恢复派发</span></button
					>
				{:else}
					<button
						type="button"
						class="tm-btn-ghost"
						disabled={busy}
						on:click={pauseDispatch}
						title="不再开始新任务；正在执行的成员会继续做完手上的任务"
						><svg class="size-3" viewBox="0 0 12 12" aria-hidden="true"
							><path d="M3 2h2v8H3zM7 2h2v8H7z" fill="currentColor" /></svg
						><span class="max-sm:sr-only">暂停派发</span></button
					>
				{/if}
				<button
					type="button"
					class="tm-btn-ghost tm-btn-danger"
					disabled={busy}
					on:click={() => (showStop = true)}
					title="结束所有正在执行的成员，整个协作任务停止，不会被自动恢复"
					><svg class="size-3" viewBox="0 0 12 12" aria-hidden="true"
						><rect x="2.5" y="2.5" width="7" height="7" rx="1.5" fill="currentColor" /></svg
					><span class="max-sm:sr-only">停止执行</span></button
				>
			{/if}
		</div>
	</nav>

	<div class="tm-scroll min-h-0 flex-1 overflow-y-auto px-3 pb-6 sm:px-4">
		{#if loadError && !team}
			<div class="mx-auto mt-16 max-w-md text-center text-sm text-gray-500">
				{loadError}
				<div class="mt-3"><a class="text-sky-600 hover:underline" href="/teams">回到协作台</a></div>
			</div>
		{:else if !team}
			<div class="mx-auto mt-10 flex max-w-4xl flex-col gap-3" aria-busy="true">
				<div class="tm-card-quiet h-20 animate-pulse" />
				<div class="tm-card-quiet h-64 animate-pulse" />
			</div>
		{:else if team.status !== 'running'}
			<div class="mx-auto flex max-w-4xl flex-col gap-5 pt-2">
				<section class="goal tm-card-quiet px-5 py-4" aria-label="目标">
					<div class="tm-eyebrow mb-1.5">目标</div>
					<div
						class="whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-800 dark:text-gray-200 {goalOpen
							? ''
							: 'line-clamp-6'}"
					>
						{team.goal}
					</div>
					{#if team.goal.split('\n').length > 6 || team.goal.length > 420}
						<button
							type="button"
							class="mt-1.5 text-xs text-sky-700 hover:underline dark:text-sky-300"
							on:click={() => (goalOpen = !goalOpen)}>{goalOpen ? '收起' : '展开全部'}</button
						>
					{/if}
				</section>
				{#if team.status === 'planning'}
					<section
						class="tm-card tm-live flex items-start gap-4 px-5 py-5"
						role="status"
						data-team-planning
					>
						<TeamAvatar kind="lead" status="running" size={46} />
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="tm-shimmer text-[15px] font-semibold text-gray-900 dark:text-gray-50"
									>负责人正在制定计划</span
								>
								<span class="tm-num ml-auto text-xs text-gray-400"
									>{elapsed($now - (team.updated_at || team.created_at))}</span
								>
							</div>
							<p class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
								理解目标 → 从助手模板里挑选成员 → 拆分带依赖的任务 → 为每位成员匹配执行来源。通常
								10–60 秒；计划出来后要你批准才会开始执行。
							</p>
							<div class="mt-4 grid gap-2 sm:grid-cols-3" aria-hidden="true">
								{#each [0, 1, 2] as i}
									<div
										class="ghost tm-card-quiet flex items-center gap-2.5 px-3 py-2.5"
										style="--i:{i}"
									>
										<span
											class="size-7 shrink-0 rounded-full bg-gray-900/[0.06] dark:bg-white/[0.07]"
										/>
										<span class="flex flex-1 flex-col gap-1.5">
											<span
												class="h-2 w-3/4 rounded-full bg-gray-900/[0.07] dark:bg-white/[0.08]"
											/>
											<span
												class="h-2 w-1/2 rounded-full bg-gray-900/[0.05] dark:bg-white/[0.05]"
											/>
										</span>
									</div>
								{/each}
							</div>
						</div>
					</section>
				{:else if team.status === 'starting'}
					<section class="tm-card tm-live flex items-center gap-3 px-5 py-5 text-sm" role="status">
						<TeamAvatar kind="lead" status="running" size={36} />
						<span class="tm-shimmer font-medium">正在启动成员…</span>
					</section>
				{/if}
				{#if team.error}
					<div
						class="whitespace-pre-wrap break-words rounded-2xl border border-red-500/20 bg-red-500/[0.06] px-4 py-3 text-sm text-red-800 dark:text-red-200"
						role="alert"
					>
						{team.error}
					</div>
				{/if}
				{#if team.status === 'plan_failed'}
					<div class="flex gap-2">
						<button type="button" class="tm-btn-primary" disabled={busy} on:click={() => replan('')}
							>重新生成计划</button
						>
						<button type="button" class="tm-btn-ghost" disabled={busy} on:click={cancel}
							>取消</button
						>
					</div>
				{/if}
				{#if team.status === 'cancelled'}
					<div class="text-sm text-gray-500">这个协作任务已取消，没有执行任何成员。</div>
				{/if}
				{#if team.plan && ['plan_ready', 'start_failed', 'cancelled'].includes(team.status)}
					<PlanReview
						{team}
						{busy}
						{registry}
						{registryError}
						{checking}
						on:approve={approve}
						on:replan={(e) => replan(e.detail)}
						on:cancel={cancel}
						on:executor={(e) => setExecutor(e.detail.name, e.detail.executor, e.detail.source)}
						on:recheck={recheck}
					/>
				{/if}
			</div>
		{:else}
			<div class="flex flex-col gap-4 pt-1">
				<TeamProgress
					{counts}
					{fallbacks}
					{leadModel}
					workspace={live?.team.workspace ?? ''}
					startedAt={replay ? null : team.approved_at}
					finishedAt={finished ? (team.finished_at ?? null) : null}
				/>

				{#if liveError}
					<div
						class="rounded-xl border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2 text-xs text-amber-800 dark:text-amber-200"
						role="alert"
					>
						读不到 Hermes 上的实时状态：{liveError}（显示的是最后一次读到的内容）
					</div>
				{:else if disconnected > 0}
					<div
						class="rounded-xl border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2 text-xs text-amber-800 dark:text-amber-200"
						role="status"
					>
						连接中断，正在重试（第 {disconnected} 次）…恢复后会补上漏掉的记录
					</div>
				{/if}
				{#if reconcile.length && !replay}
					<div class="tm-card-quiet px-3 py-2 text-xs text-gray-600 dark:text-gray-300">
						历史记录与当前状态不一致：{reconcile
							.map(
								(r) =>
									`#${r.key} 历史为「${statusLabel(r.history)}」，当前为「${statusLabel(r.live)}」`
							)
							.join('；')}。以当前状态为准，回放到最后可能与之不同。
					</div>
				{/if}
				{#if truncated}
					<div class="tm-card-quiet px-3 py-2 text-xs text-gray-600 dark:text-gray-300">
						记录太多，只载入了最早的一部分；回放和通讯不完整。
					</div>
				{/if}

				{#if phase === 'completed' && !replay}
					<div
						class="done-banner tm-card flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5"
						data-completed-banner
					>
						<span
							class="check grid size-9 shrink-0 place-items-center rounded-full text-white"
							aria-hidden="true"
							><svg class="size-4" viewBox="0 0 16 16" fill="none"
								><path
									d="m3.5 8.5 3 3 6-7"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									pathLength="1"
								/></svg
							></span
						>
						<div class="min-w-0 flex-1">
							<div class="text-sm font-semibold text-gray-900 dark:text-gray-50">
								全部 {counts.total} 个任务已完成{#if team.approved_at && team.finished_at}<span
										class="tm-num ml-2 inline-block whitespace-nowrap text-xs font-normal text-gray-500"
										>用时 {elapsed(team.finished_at - team.approved_at)}</span
									>{/if}
							</div>
							<div class="text-xs text-gray-500 dark:text-gray-400">
								{#if conclusionBrief?.status === 'ready'}
									负责人写好了结论{conclusionBrief.model ? `（${conclusionBrief.model}）` : ''}
								{:else if conclusionBrief?.status === 'failed'}
									结论没写成，可以在「结论」里重新生成
								{:else}
									<span class="tm-shimmer">负责人正在根据所有成员的结果写结论…</span>
								{/if}
							</div>
						</div>
						<button type="button" class="tm-btn-primary !py-1.5 !text-xs" on:click={showConclusion}
							>阅读结论</button
						>
					</div>
				{/if}

				<MemberStrip
					{lead}
					members={memberViews}
					selected={selectedMember}
					layout={$mobile && mobileTab === 'members' ? 'list' : 'row'}
					on:select={(e) => selectMember(e.detail)}
				/>

				<ReplayBar {events} index={replayIndex} on:seek={(e) => seek(e.detail)} />

				{#if $mobile}
					<div class="tm-segment w-full" role="tablist" aria-label="协作台视图">
						{#each [['tasks', '任务'], ['members', '成员'], ['feed', '通讯'], ['conclusion', '结论']] as [value, label]}
							<button
								type="button"
								role="tab"
								aria-selected={mobileTab === value}
								class="flex-1 !py-1.5 !text-sm"
								on:click={() => (mobileTab = value)}>{label}</button
							>
						{/each}
					</div>
					{#if selectedTask || selectedMember}
						<div id="team-inspector" class="tm-card p-3">
							<Inspector
								{teamId}
								taskId={selectedTask}
								memberName={selectedMember}
								{tasks}
								{states}
								members={memberViews}
								events={shownEvents}
								{replay}
								teamStopped={stopped}
								workspace={live?.team.workspace ?? null}
								{refreshKey}
								on:close={() => {
									selectedTask = null;
									selectedMember = null;
								}}
								on:task={(e) => selectTask(e.detail)}
								on:changed={restart}
							/>
						</div>
					{/if}
					{#if mobileTab === 'tasks'}
						<ol class="flex flex-col gap-4">
							{#each layers as layer, depth}
								<li>
									<div class="mb-1.5 flex items-center gap-2 text-xs text-gray-500">
										<span
											class="tm-num grid size-5 place-items-center rounded-full border text-[10px] font-semibold tm-hairline"
											>{depth + 1}</span
										>
										第 {depth + 1} 步{layer.length > 1 ? ` · ${layer.length} 个并行` : ''}
									</div>
									<ul class="flex flex-col gap-2">
										{#each layer as t (t.id)}
											{@const s = states.get(t.id)}
											<li>
												<button
													type="button"
													class="tm-card w-full px-3 py-2.5 text-left {toneOf(s?.sub_status) ===
													'run'
														? 'tm-live'
														: ''} {selectedTask === t.id ? '!border-sky-400/60' : ''}"
													on:click={() => selectTask(t.id)}
												>
													<div class="flex items-center gap-2 text-xs">
														<span class="font-mono font-semibold text-gray-400">#{t.key}</span>
														<span class="min-w-0 truncate text-gray-500">{t.member}</span>
														<RunnerBadge
															chosen={taskRunner(t).chosen}
															actual={t.executor}
															reason={taskRunner(t).reason}
														/>
														<span class="ml-auto shrink-0"
															><StatusChip status={s?.sub_status} /></span
														>
													</div>
													<div class="mt-1 text-sm font-medium">{t.title}</div>
													{#if s?.sub_status === 'waiting_deps'}
														<div class="text-xs text-amber-600 dark:text-amber-400">
															等 {openParents(t, states)
																.map((p) => `#${keyOf.get(p) ?? p}`)
																.join('、')} 完成
														</div>
													{:else if toneOf(s?.sub_status) === 'run'}
														{@const act = activity.get(t.member)}
														<div
															class="mt-1 flex min-w-0 items-center gap-1.5 font-mono text-[11px]"
															data-task-activity
														>
															<span class="shrink-0 text-sky-500" aria-hidden="true">›</span>
															<span
																class="tm-caret min-w-0 truncate text-gray-600 dark:text-gray-300"
																>{act?.text ?? '开始执行…'}</span
															>
															{#if !replay && t.started_at}
																<span class="tm-num ml-auto shrink-0 text-sky-600 dark:text-sky-300"
																	>{elapsed($now - t.started_at)}</span
																>
															{/if}
														</div>
													{:else if s?.status === 'done' && !replay && t.started_at && t.completed_at}
														<div class="tm-num mt-0.5 text-[11px] text-gray-400">
															用时 {elapsed(t.completed_at - t.started_at)}
														</div>
													{/if}
												</button>
											</li>
										{/each}
									</ul>
								</li>
							{/each}
						</ol>
					{:else if mobileTab === 'feed'}
						<div class="tm-card h-[60vh] p-3">
							<CommFeed
								events={shownEvents}
								{cursorSeq}
								memberFilter={selectedMember}
								{titles}
								members={planMembers}
								on:task={(e) => selectTask(e.detail)}
								on:clearfilter={() => selectMember(null)}
							/>
						</div>
					{:else if mobileTab === 'conclusion'}
						<ConclusionView
							{teamId}
							title={team.title}
							{phase}
							brief={conclusionBrief}
							progress={{ done: counts.done, total: counts.total }}
						/>
					{/if}
				{:else}
					<div
						class="grid gap-4 {asideTab === 'conclusion' && !selectedTask && !selectedMember
							? 'lg:grid-cols-[minmax(0,1fr)_420px] xl:grid-cols-[minmax(0,1fr)_520px]'
							: 'lg:grid-cols-[minmax(0,1fr)_380px]'}"
					>
						<div class="flex min-w-0 flex-col gap-2">
							<TeamBoard
								{tasks}
								{states}
								{replay}
								members={memberViews}
								selectedTaskId={selectedTask}
								on:select={(e) => selectTask(e.detail)}
							/>
							<div
								class="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px] text-gray-500"
								aria-label="图例"
							>
								<span class="flex items-center gap-1.5"
									><span
										class="h-0.5 w-4 rounded bg-emerald-500"
										aria-hidden="true"
									/>前置任务已完成</span
								>
								<span class="flex items-center gap-1.5"
									><span
										class="legend-run h-0.5 w-4 rounded"
										aria-hidden="true"
									/>前置任务执行中</span
								>
								<span class="flex items-center gap-1.5"
									><span class="legend-wait h-0.5 w-4 rounded" aria-hidden="true" />还在等</span
								>
							</div>
						</div>
						<aside
							class="tm-card flex min-h-[420px] flex-col p-3 lg:sticky lg:top-0 lg:max-h-[calc(100dvh-9rem)]"
						>
							{#if selectedTask || selectedMember}
								<div class="tm-scroll min-h-0 overflow-y-auto">
									<Inspector
										{teamId}
										taskId={selectedTask}
										memberName={selectedMember}
										{tasks}
										{states}
										members={memberViews}
										events={shownEvents}
										{replay}
										teamStopped={stopped}
										workspace={live?.team.workspace ?? null}
										{refreshKey}
										on:close={() => {
											selectedTask = null;
											selectedMember = null;
										}}
										on:task={(e) => selectTask(e.detail)}
										on:changed={restart}
									/>
								</div>
							{:else}
								<div class="mb-3 flex items-center">
									<div class="tm-segment" role="tablist" aria-label="通讯与结论">
										{#each [['feed', '通讯与日志'], ['conclusion', '结论']] as [value, label]}
											<button
												type="button"
												role="tab"
												aria-selected={asideTab === value}
												class="relative focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
												on:click={() => {
													asideTab = value;
													asideTouched = true;
												}}
												data-aside-tab={value}
												>{label}{#if value === 'conclusion' && conclusionBrief?.status === 'ready' && asideTab !== 'conclusion'}<span
														class="absolute right-1 top-1 size-1.5 rounded-full bg-emerald-500"
														aria-label="结论已生成"
													/>{/if}</button
											>
										{/each}
									</div>
								</div>
								{#if asideTab === 'conclusion'}
									<div class="tm-scroll min-h-0 flex-1 overflow-y-auto pr-1">
										<ConclusionView
											{teamId}
											title={team.title}
											{phase}
											brief={conclusionBrief}
											progress={{ done: counts.done, total: counts.total }}
										/>
									</div>
								{:else}
									<div class="min-h-0 flex-1">
										<CommFeed
											events={shownEvents}
											{cursorSeq}
											{titles}
											members={planMembers}
											on:task={(e) => selectTask(e.detail)}
											on:clearfilter={() => selectMember(null)}
										/>
									</div>
								{/if}
							{/if}
						</aside>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<ConfirmDialog
	bind:show={showStop}
	title="停止整个协作任务？"
	message="正在执行的成员会被结束（reclaude、codex 等 runner 的运行会被停止），还没开始的任务不再开始。已完成的产出保留。停止后不会被自动恢复，也不能再继续这个协作任务。"
	confirmLabel="停止执行"
	on:confirm={stopAll}
/>

<style>
	.goal {
		position: relative;
	}
	.ghost {
		animation: ghost 1.6s ease-in-out infinite;
		animation-delay: calc(var(--i) * 0.2s);
	}
	@keyframes ghost {
		50% {
			opacity: 0.45;
		}
	}
	.done-banner {
		background: radial-gradient(120% 160% at 0% 0%, hsl(var(--tm-ok) / 0.14), transparent 55%),
			hsl(var(--tm-surface));
		border-color: hsl(var(--tm-ok) / 0.28);
	}
	.check {
		background: linear-gradient(160deg, hsl(152 70% 48%), hsl(162 80% 34%));
		box-shadow: 0 6px 18px -6px hsl(158 70% 40% / 0.7);
	}
	.check path {
		stroke-dasharray: 1;
		stroke-dashoffset: 1;
		animation: draw 0.6s 0.15s cubic-bezier(0.22, 1, 0.36, 1) forwards;
	}
	@keyframes draw {
		to {
			stroke-dashoffset: 0;
		}
	}
	.legend-run {
		background: repeating-linear-gradient(90deg, #1d8cff 0 4px, transparent 4px 7px);
	}
	.legend-wait {
		background: repeating-linear-gradient(90deg, #94a3b8 0 3px, transparent 3px 6px);
	}
	@media (prefers-reduced-motion: reduce) {
		.ghost {
			animation: none;
		}
		.check path {
			animation: none;
			stroke-dashoffset: 0;
		}
	}
</style>

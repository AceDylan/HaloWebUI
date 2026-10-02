<script lang="ts">
	import { getContext, onDestroy, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { mobile, showSidebar } from '$lib/stores';
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
	import {
		countStates,
		foldStates,
		layoutTasks,
		leadStatus,
		liveStates,
		memberStatus,
		mergeEvents,
		openParents,
		PHASE_LABEL,
		phaseAt,
		statusLabel,
		taskRunner
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
		const now =
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
			actualRunner: now?.executor ?? m.runner ?? m.executor
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
		note: PHASE_LABEL[phase] ?? ''
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
		if (settled || (finished && finishedFetches > 2)) return; // nothing more will happen on its own
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
	const seek = (index: number | null) => {
		replayIndex = index === null ? null : Math.max(0, Math.min(index, events.length - 1));
	};
</script>

<div class="relative flex h-screen max-h-[100dvh] w-full max-w-full flex-col" data-team-workbench>
	<nav class="flex items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="cursor-pointer rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<a href="/teams" class="text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100"
			>协作台</a
		>
		<span class="text-gray-300 dark:text-gray-700">/</span>
		<h1 class="min-w-0 truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
			{team?.title ?? '…'}
		</h1>
		{#if team}
			<StatusChip
				status={team.status === 'running'
					? phase === 'completed'
						? 'done'
						: phase === 'attention'
							? 'waiting_user'
							: phase === 'paused'
								? 'paused'
								: phase === 'stopped'
									? 'stopped'
									: 'running'
					: team.status === 'planning'
						? 'running'
						: team.status === 'plan_ready'
							? 'waiting_user'
							: team.status === 'cancelled'
								? 'stopped'
								: team.status.endsWith('failed')
									? 'failed'
									: 'queued'}
				label={PHASE_LABEL[team.status === 'running' ? phase : team.status] ?? team.status}
				size="sm"
			/>
		{/if}
		<div class="ml-auto flex items-center gap-1.5">
			{#if running && (conclusionBrief?.status || finished)}
				<a
					href="/teams/{teamId}/conclusion"
					class="hidden rounded-xl px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50 sm:inline-flex dark:text-emerald-300 dark:hover:bg-emerald-950/40"
					data-header-conclusion>结论</a
				>
			{/if}
			{#if team?.chat_id}
				<a
					href="/c/{team.chat_id}"
					class="rounded-xl px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-850"
					>返回对话</a
				>
			{/if}
			{#if running && !finished && !replay}
				{#if phase === 'paused'}
					<button
						type="button"
						class="rounded-xl bg-gray-100 px-2.5 py-1 text-xs font-medium hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-850"
						disabled={busy}
						on:click={resumeDispatch}
						title="让派发器继续开始新的任务">恢复派发</button
					>
				{:else}
					<button
						type="button"
						class="rounded-xl bg-gray-100 px-2.5 py-1 text-xs font-medium hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-850"
						disabled={busy}
						on:click={pauseDispatch}
						title="不再开始新任务；正在执行的成员会继续做完手上的任务">暂停派发</button
					>
				{/if}
				<button
					type="button"
					class="rounded-xl bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 dark:bg-red-950/40 dark:text-red-300"
					disabled={busy}
					on:click={() => (showStop = true)}
					title="结束所有正在执行的成员，整个协作任务停止，不会被自动恢复">停止执行</button
				>
			{/if}
		</div>
	</nav>

	<div class="flex-1 min-h-0 overflow-y-auto px-3 pb-6">
		{#if loadError && !team}
			<div class="mx-auto mt-16 max-w-md text-center text-sm text-gray-500">
				{loadError}
				<div class="mt-3"><a class="text-sky-600 hover:underline" href="/teams">回到协作台</a></div>
			</div>
		{:else if !team}
			<div class="mt-16 text-center text-sm text-gray-400">正在加载…</div>
		{:else if team.status !== 'running'}
			<div class="mx-auto max-w-4xl flex flex-col gap-4 pt-2">
				<div
					class="rounded-2xl bg-gray-50 px-4 py-3 text-sm text-gray-700 dark:bg-gray-850 dark:text-gray-300"
				>
					<div class="text-xs text-gray-500 mb-1">目标</div>
					<div class="whitespace-pre-wrap break-words">{team.goal}</div>
				</div>
				{#if team.status === 'planning'}
					<div
						class="flex items-center gap-3 rounded-2xl border border-gray-100 px-4 py-6 dark:border-gray-850"
						role="status"
					>
						<span class="size-3 rounded-full bg-sky-500 animate-pulse" aria-hidden="true" />
						<div>
							<div class="text-sm font-medium">负责人正在制定计划…</div>
							<div class="text-xs text-gray-500">
								通常 10–60 秒；计划出来后要你批准才会开始执行。
							</div>
						</div>
					</div>
				{:else if team.status === 'starting'}
					<div
						class="rounded-2xl border border-gray-100 px-4 py-6 text-sm dark:border-gray-850"
						role="status"
					>
						正在启动…
					</div>
				{/if}
				{#if team.error}
					<div
						class="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200 whitespace-pre-wrap break-words"
						role="alert"
					>
						{team.error}
					</div>
				{/if}
				{#if team.status === 'plan_failed'}
					<div class="flex gap-2">
						<button
							type="button"
							class="rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
							disabled={busy}
							on:click={() => replan('')}>重新生成计划</button
						>
						<button
							type="button"
							class="rounded-xl px-4 py-2 text-sm text-gray-500"
							disabled={busy}
							on:click={cancel}>取消</button
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
			<div class="flex flex-col gap-3 pt-1">
				<div
					class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500"
					aria-label="进度"
				>
					<span
						>完成 <b class="text-gray-900 dark:text-gray-100 tabular-nums">{counts.done}</b
						>/{counts.total}</span
					>
					<span
						>执行中 <b class="text-sky-700 dark:text-sky-300 tabular-nums">{counts.running}</b
						></span
					>
					<span>等待 <b class="tabular-nums">{counts.waiting}</b></span>
					{#if counts.attention}<span
							>需处理 <b class="text-red-600 tabular-nums">{counts.attention}</b></span
						>{/if}
					{#if fallbacks}<span
							class="text-amber-700 dark:text-amber-300"
							title="有任务因为默认执行来源不可用而改由下一个执行"
							>兜底改派 <b class="tabular-nums">{fallbacks}</b></span
						>{/if}
					{#if leadModel}<span
							>负责人模型 <span class="font-mono text-gray-700 dark:text-gray-300">{leadModel}</span
							></span
						>{/if}
					{#if live?.team.workspace}<span class="truncate"
							>工作目录 <span class="font-mono">{live.team.workspace}</span></span
						>{/if}
				</div>

				{#if liveError}
					<div
						class="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
						role="alert"
					>
						读不到 Hermes 上的实时状态：{liveError}（显示的是最后一次读到的内容）
					</div>
				{:else if disconnected > 0}
					<div
						class="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
						role="status"
					>
						连接中断，正在重试（第 {disconnected} 次）…恢复后会补上漏掉的记录
					</div>
				{/if}
				{#if reconcile.length && !replay}
					<div
						class="rounded-xl bg-gray-50 px-3 py-2 text-xs text-gray-600 dark:bg-gray-850 dark:text-gray-300"
					>
						历史记录与当前状态不一致：{reconcile
							.map(
								(r) =>
									`#${r.key} 历史为「${statusLabel(r.history)}」，当前为「${statusLabel(r.live)}」`
							)
							.join('；')}。以当前状态为准，回放到最后可能与之不同。
					</div>
				{/if}
				{#if truncated}
					<div
						class="rounded-xl bg-gray-50 px-3 py-2 text-xs text-gray-600 dark:bg-gray-850 dark:text-gray-300"
					>
						记录太多，只载入了最早的一部分；回放和通讯不完整。
					</div>
				{/if}

				{#if phase === 'completed' && !replay}
					<div
						class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-emerald-200/70 bg-emerald-50/70 px-4 py-3 dark:border-emerald-900/60 dark:bg-emerald-950/25"
						data-completed-banner
					>
						<span
							class="grid size-8 shrink-0 place-items-center rounded-full bg-emerald-500 text-white"
							aria-hidden="true"
							><svg class="size-4" viewBox="0 0 16 16" fill="none"
								><path
									d="m3.5 8.5 3 3 6-7"
									stroke="currentColor"
									stroke-width="1.9"
									stroke-linecap="round"
									stroke-linejoin="round"
								/></svg
							></span
						>
						<div class="min-w-0 flex-1">
							<div class="text-sm font-semibold text-emerald-900 dark:text-emerald-100">
								全部 {counts.total} 个任务已完成
							</div>
							<div class="text-xs text-emerald-800/80 dark:text-emerald-200/80">
								{conclusionBrief?.status === 'ready'
									? `负责人写好了结论${conclusionBrief.model ? `（${conclusionBrief.model}）` : ''}`
									: conclusionBrief?.status === 'failed'
										? '结论没写成，可以在「结论」里重新生成'
										: '负责人正在根据所有成员的结果写结论…'}
							</div>
						</div>
						<button
							type="button"
							class="rounded-xl bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700 active:scale-[0.98]"
							on:click={showConclusion}>阅读结论</button
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
					<div
						class="flex rounded-xl bg-gray-100 p-0.5 text-sm dark:bg-gray-850"
						role="tablist"
						aria-label="协作台视图"
					>
						{#each [['tasks', '任务'], ['members', '成员'], ['feed', '通讯'], ['conclusion', '结论']] as [value, label]}
							<button
								type="button"
								role="tab"
								aria-selected={mobileTab === value}
								class="flex-1 rounded-lg py-1.5 {mobileTab === value
									? 'bg-white shadow-sm dark:bg-gray-900'
									: 'text-gray-500'}"
								on:click={() => (mobileTab = value)}>{label}</button
							>
						{/each}
					</div>
					{#if selectedTask || selectedMember}
						<div
							id="team-inspector"
							class="rounded-2xl border border-gray-100 p-3 dark:border-gray-850"
						>
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
						<ol class="flex flex-col gap-3">
							{#each layers as layer, depth}
								<li>
									<div class="mb-1 text-xs text-gray-500">
										第 {depth + 1} 步{layer.length > 1 ? ` · ${layer.length} 个并行` : ''}
									</div>
									<ul class="flex flex-col gap-1.5">
										{#each layer as t (t.id)}
											{@const s = states.get(t.id)}
											<li>
												<button
													type="button"
													class="w-full rounded-2xl border px-3 py-2 text-left {selectedTask ===
													t.id
														? 'border-sky-300 dark:border-sky-700'
														: 'border-gray-100 dark:border-gray-850'}"
													on:click={() => selectTask(t.id)}
												>
													<div class="flex items-center gap-2 text-xs">
														<span class="font-mono font-semibold text-gray-500">#{t.key}</span>
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
													<div class="mt-0.5 text-sm font-medium">{t.title}</div>
													{#if s?.sub_status === 'waiting_deps'}
														<div class="text-xs text-amber-600 dark:text-amber-400">
															等 {openParents(t, states)
																.map((p) => `#${keyOf.get(p) ?? p}`)
																.join('、')} 完成
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
						<div class="h-[60vh]">
							<CommFeed
								events={shownEvents}
								{cursorSeq}
								memberFilter={selectedMember}
								{titles}
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
						class="grid gap-3 {asideTab === 'conclusion' && !selectedTask && !selectedMember
							? 'lg:grid-cols-[minmax(0,1fr)_420px] xl:grid-cols-[minmax(0,1fr)_520px]'
							: 'lg:grid-cols-[minmax(0,1fr)_380px]'}"
					>
						<div class="flex min-w-0 flex-col gap-3">
							<TeamBoard
								{tasks}
								{states}
								members={memberViews}
								selectedTaskId={selectedTask}
								on:select={(e) => selectTask(e.detail)}
							/>
							<div
								class="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-500"
								aria-label="图例"
							>
								<span>实线 = 前置任务已完成</span><span>流动虚线 = 前置任务执行中</span><span
									>灰色虚线 = 还在等</span
								>
							</div>
						</div>
						<aside
							class="flex min-h-[420px] flex-col rounded-2xl border border-gray-100 p-3 dark:border-gray-850 lg:sticky lg:top-0 lg:max-h-[calc(100dvh-9rem)]"
						>
							{#if selectedTask || selectedMember}
								<div class="min-h-0 overflow-y-auto">
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
								<div class="mb-2 flex items-center gap-1" role="tablist" aria-label="通讯与结论">
									{#each [['feed', '通讯与日志'], ['conclusion', '结论']] as [value, label]}
										<button
											type="button"
											role="tab"
											aria-selected={asideTab === value}
											class="relative rounded-lg px-2.5 py-1 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 {asideTab ===
											value
												? 'bg-gray-100 font-semibold text-gray-900 dark:bg-gray-850 dark:text-gray-100'
												: 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-200'}"
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
								{#if asideTab === 'conclusion'}
									<div class="min-h-0 flex-1 overflow-y-auto pr-1">
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

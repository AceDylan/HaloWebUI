<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { slide } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import './teams.css';
	import { mobile, showSidebar } from '$lib/stores';
	import {
		checkRunners,
		createTeam,
		deleteTeam,
		getTeamsMeta,
		listTeams,
		type Team,
		type TeamsMeta
	} from '$lib/apis/teams';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import RunnerStatus from './RunnerStatus.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { now, timeAgo } from './clock';
	import { avatarKind, PHASE_LABEL, runnerLabel } from './model';

	/** Your collaboration tasks (only yours) and a box to start a new one. */
	let teams: Team[] = [];
	let loaded = false;
	let error = '';
	let goal = '';
	let creating = false;
	let chatId: string | null = null;
	let meta: TeamsMeta | null = null;
	let metaError = '';
	let checking = false;
	let leadModel = '';
	let showRunners = false;
	let filter: 'all' | 'active' | 'review' | 'done' | 'ended' = 'all';
	let query = '';
	let composer: HTMLTextAreaElement;
	let pendingDelete: Team | null = null;
	let showDelete = false;
	let refreshTimer: ReturnType<typeof setInterval> | null = null;
	let isMac = false;

	// The lead follows Hermes' default model unless this team picks another configured one.
	$: defaultModel = meta?.lead_model?.choices?.[0] ?? meta?.lead_model?.model ?? '';
	$: modelChoices = (meta?.lead_model?.choices ?? []).filter((m) => m !== defaultModel);
	$: runners = meta?.registry?.runners ?? [];
	$: runnersUp = runners.filter((r) => r.available).length;

	$: chatTeams = chatId ? teams.filter((t) => t.chat_id === chatId) : [];

	const statusOf = (t: Team) => (t.status === 'running' ? (t.phase ?? 'running') : t.status);
	const chipOf = (s: string) =>
		({
			planning: 'running',
			plan_ready: 'waiting_user',
			plan_failed: 'failed',
			starting: 'queued',
			start_failed: 'failed',
			cancelled: 'stopped',
			running: 'running',
			attention: 'waiting_user',
			paused: 'paused',
			stopped: 'stopped',
			completed: 'done'
		})[s] ?? 'queued';
	const bucketOf = (t: Team): typeof filter => {
		const s = statusOf(t);
		if (s === 'plan_ready') return 'review';
		if (s === 'completed') return 'done';
		if (['cancelled', 'plan_failed', 'start_failed', 'stopped'].includes(s)) return 'ended';
		return 'active';
	};

	const FILTERS: { value: typeof filter; label: string }[] = [
		{ value: 'all', label: '全部' },
		{ value: 'active', label: '进行中' },
		{ value: 'review', label: '待批准' },
		{ value: 'done', label: '已完成' },
		{ value: 'ended', label: '已结束' }
	];
	$: counts = teams.reduce((acc, t) => ({ ...acc, [bucketOf(t)]: (acc[bucketOf(t)] ?? 0) + 1 }), {
		all: teams.length
	} as Record<string, number>);
	$: needle = query.trim().toLowerCase();
	$: shown = teams.filter(
		(t) =>
			(filter === 'all' || bucketOf(t) === filter) &&
			(!needle || `${t.title}\n${t.goal}`.toLowerCase().includes(needle))
	);
	$: activeCount = counts.active ?? 0;

	const QUICK_STARTS = [
		{
			icon: 'research',
			title: '调研对比',
			text: '调研 3 个主流的开源看板工具，对比功能、活跃度、部署难度和上手成本，写一份带推荐结论的报告；最后由评审成员核对事实和出处。'
		},
		{
			icon: 'build',
			title: '功能开发',
			text: '在工作目录实现一个命令行待办工具：后端成员写核心逻辑和单元测试并跑通，前端成员做一个单文件网页界面，最后写 README 说明用法和测试结果。'
		},
		{
			icon: 'review',
			title: '代码审查',
			text: '审查 /root/项目路径 最近的改动：分别从正确性、性能、安全三个角度找问题，按严重程度列出并给出修改建议，最后汇总成一份审查报告。'
		},
		{
			icon: 'doc',
			title: '方案撰写',
			text: '为「团队知识库」写一份技术方案：背景与目标、架构图（Mermaid）、数据模型、里程碑和风险；写完由评审成员挑错并修订。'
		}
	];

	const useQuickStart = async (text: string) => {
		goal = text;
		await tick();
		resize();
		composer?.focus();
	};

	const resize = () => {
		if (!composer) return;
		composer.style.height = 'auto';
		composer.style.height = `${Math.min(composer.scrollHeight, 320)}px`;
	};

	const load = async () => {
		try {
			teams = (await listTeams(localStorage.token)).teams;
			error = '';
		} catch (e) {
			error = `${e?.message ?? e}`;
		} finally {
			loaded = true;
		}
	};

	const loadMeta = async () => {
		try {
			meta = await getTeamsMeta(localStorage.token);
			metaError = '';
		} catch (e) {
			metaError = `${e?.message ?? e}`;
		}
	};

	const recheck = async () => {
		if (checking) return;
		checking = true;
		try {
			const registry = await checkRunners(localStorage.token);
			meta = meta ? { ...meta, registry } : meta;
			if (!meta) await loadMeta();
			metaError = '';
		} catch (e) {
			metaError = `${e?.message ?? e}`;
		} finally {
			checking = false;
		}
	};

	const create = async () => {
		const text = goal.trim();
		if (!text || creating) return;
		creating = true;
		try {
			const team = await createTeam(localStorage.token, text, chatId, leadModel || null);
			goto(`/teams/${team.id}`);
		} catch (e) {
			toast.error(`${e?.message ?? e}`);
		} finally {
			creating = false;
		}
	};

	const again = async (team: Team) => {
		goal = team.goal;
		await tick();
		resize();
		composer?.focus();
		composer?.scrollIntoView({ behavior: 'smooth', block: 'center' });
	};

	const askDelete = (team: Team) => {
		pendingDelete = team;
		showDelete = true;
	};
	const confirmDelete = async () => {
		const team = pendingDelete;
		if (!team) return;
		try {
			await deleteTeam(localStorage.token, team.id);
			teams = teams.filter((t) => t.id !== team.id);
			toast.success('已删除');
		} catch (e) {
			toast.error(`${e?.message ?? e}`);
		} finally {
			pendingDelete = null;
		}
	};

	// Teams at work move on their own: refresh the list while any is active and the page is seen.
	const startRefresh = () => {
		if (refreshTimer) return;
		refreshTimer = setInterval(() => {
			if (document.visibilityState === 'visible' && activeCount > 0) load();
		}, 15000);
	};

	onMount(() => {
		// "发起协作任务" from a chat links here with ?chat=<id> (and an optional ?goal=).
		const params = new URLSearchParams(window.location.search);
		chatId = params.get('chat');
		goal = params.get('goal') ?? '';
		isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
		load();
		loadMeta();
		startRefresh();
		tick().then(resize);
	});
	onDestroy(() => {
		if (refreshTimer) clearInterval(refreshTimer);
	});
</script>

<div
	class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col"
	data-teams-home
	data-teams-ui
>
	<nav class="flex items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<h1 class="text-sm font-semibold text-gray-900 dark:text-gray-100">协作台</h1>
		{#if chatId}
			<a
				href="/c/{chatId}"
				class="ml-auto rounded-xl px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-850"
				>← 返回对话</a
			>
		{/if}
	</nav>

	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-16">
		<div class="mx-auto flex max-w-3xl flex-col pt-6 sm:pt-14">
			<!-- hero -->
			<header class="tm-rise mb-6 flex flex-col gap-3">
				<div class="flex items-center gap-2">
					<span class="tm-eyebrow">Halo Teams</span>
					<span class="h-3 w-px bg-gray-300 dark:bg-gray-700" aria-hidden="true" />
					<span class="text-xs text-gray-500 dark:text-gray-400">多代理协作</span>
				</div>
				<h2
					class="tm-display text-[28px] font-semibold leading-[1.15] text-gray-950 sm:text-[36px] dark:text-white"
				>
					把目标交给一支 AI 团队
				</h2>
				<p class="max-w-xl text-sm leading-relaxed text-gray-500 dark:text-gray-400">
					负责人拆分任务、为每位成员挑选最合适的代理并按依赖并行推进；你批准计划后才开工，结束时交付一份完整结论。
				</p>
			</header>

			<!-- composer -->
			<form
				class="tm-rise composer tm-card relative flex flex-col"
				style="--i:1"
				on:submit|preventDefault={create}
				data-team-composer
			>
				<label for="team-goal" class="sr-only">要协作完成的目标</label>
				<textarea
					id="team-goal"
					bind:this={composer}
					bind:value={goal}
					rows="3"
					maxlength="8000"
					class="tm-scroll w-full resize-none bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
					placeholder="描述你想完成的事，比如：调研三个开源看板工具并写一份对比报告，最后由评审成员检查结论"
					on:input={resize}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
							e.preventDefault();
							create();
						}
					}}
				/>
				{#if chatId}
					<div class="px-5 pb-1 text-xs text-sky-700 dark:text-sky-300">会关联到你刚才的对话</div>
				{/if}
				<div class="flex flex-wrap items-center gap-2 px-3 pt-1 pb-3">
					<label
						class="pill flex min-w-0 items-center gap-1.5 rounded-full py-1 pr-1 pl-2.5 text-xs"
						data-lead-model
						title="负责人做计划、写结论用的模型；默认跟随 Hermes 当前的默认模型"
					>
						<TeamAvatar kind="lead" size={16} />
						<span class="shrink-0 text-gray-500 dark:text-gray-400">负责人</span>
						<select bind:value={leadModel} class="compact-select min-w-0 max-w-[12rem] truncate">
							<option value=""
								>{meta?.lead_model?.model ? `Hermes 默认 · ${defaultModel}` : 'Hermes 默认'}</option
							>
							{#each modelChoices as model}
								<option value={model}>{model}</option>
							{/each}
						</select>
					</label>
					<button
						type="button"
						class="pill inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-gray-600 dark:text-gray-300"
						aria-expanded={showRunners}
						on:click={() => (showRunners = !showRunners)}
						data-runner-summary
					>
						<span class="flex -space-x-0.5" aria-hidden="true">
							{#each runners.slice(0, 6) as r}
								<span
									class="size-1.5 rounded-full ring-2 ring-white dark:ring-gray-900 {r.available
										? 'bg-emerald-500'
										: r.state === 'not_configured'
											? 'bg-gray-300 dark:bg-gray-600'
											: 'bg-red-500'}"
								/>
							{/each}
						</span>
						{#if !meta && !metaError}
							检测执行来源…
						{:else if metaError}
							执行来源检测失败
						{:else}
							执行来源 <b class="tm-num font-semibold">{runnersUp}/{runners.length}</b> 可用
						{/if}
						<svg
							class="size-3 transition-transform {showRunners ? 'rotate-180' : ''}"
							viewBox="0 0 12 12"
							fill="none"
							aria-hidden="true"
							><path
								d="m3 4.5 3 3 3-3"
								stroke="currentColor"
								stroke-width="1.4"
								stroke-linecap="round"
								stroke-linejoin="round"
							/></svg
						>
					</button>
					<div class="ml-auto flex items-center gap-2">
						<span class="hidden items-center gap-1 text-[11px] text-gray-400 sm:inline-flex">
							<kbd class="tm-kbd">{isMac ? '⌘' : 'Ctrl'}</kbd><kbd class="tm-kbd">↵</kbd>
						</span>
						<button
							type="submit"
							class="tm-btn-primary"
							disabled={creating || !goal.trim()}
							data-create-team
						>
							{#if creating}
								<span
									class="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
									aria-hidden="true"
								/>提交中…
							{:else}
								让负责人做计划
								<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
									><path
										d="M3 8h9.5M8.5 4l4 4-4 4"
										stroke="currentColor"
										stroke-width="1.7"
										stroke-linecap="round"
										stroke-linejoin="round"
									/></svg
								>
							{/if}
						</button>
					</div>
				</div>
			</form>
			<p class="mt-2 px-1 text-[11px] text-gray-400 dark:text-gray-500">
				做计划只调用一次模型，不会启动任何成员；计划要你批准才会执行。
			</p>

			{#if showRunners}
				<div class="mt-3" transition:slide={{ duration: 220 }}>
					<RunnerStatus
						registry={meta?.registry ?? null}
						{checking}
						error={metaError}
						on:check={recheck}
					/>
				</div>
			{/if}

			<!-- quick starts -->
			<section class="tm-rise mt-6" style="--i:2" aria-label="快速开始">
				<div class="mb-2 flex items-center gap-2">
					<span class="tm-eyebrow">快速开始</span>
				</div>
				<ul class="grid grid-cols-2 gap-2 sm:grid-cols-4">
					{#each QUICK_STARTS as q}
						<li>
							<button
								type="button"
								class="quick tm-card-quiet tm-hover flex h-full w-full flex-col items-start gap-2 px-3 py-2.5 text-left"
								on:click={() => useQuickStart(q.text)}
								title={q.text}
							>
								<span class="quick-icon grid size-7 place-items-center rounded-lg">
									<svg class="size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
										{#if q.icon === 'research'}
											<circle cx="7" cy="7" r="4.2" stroke="currentColor" stroke-width="1.5" />
											<path
												d="m10.2 10.2 3.3 3.3"
												stroke="currentColor"
												stroke-width="1.6"
												stroke-linecap="round"
											/>
										{:else if q.icon === 'build'}
											<path
												d="M5.5 4.5 2 8l3.5 3.5M10.5 4.5 14 8l-3.5 3.5"
												stroke="currentColor"
												stroke-width="1.5"
												stroke-linecap="round"
												stroke-linejoin="round"
											/>
										{:else if q.icon === 'review'}
											<path
												d="M8 1.8 13.2 4v3.6c0 3-2.2 5.4-5.2 6.6-3-1.2-5.2-3.6-5.2-6.6V4L8 1.8Z"
												stroke="currentColor"
												stroke-width="1.4"
												stroke-linejoin="round"
											/>
											<path
												d="m5.8 8 1.6 1.6 3-3.2"
												stroke="currentColor"
												stroke-width="1.5"
												stroke-linecap="round"
												stroke-linejoin="round"
											/>
										{:else}
											<path
												d="M4 1.8h5.2L12.5 5v9.2H4V1.8Z"
												stroke="currentColor"
												stroke-width="1.4"
												stroke-linejoin="round"
											/>
											<path
												d="M6 8h4.5M6 10.8h3"
												stroke="currentColor"
												stroke-width="1.4"
												stroke-linecap="round"
											/>
										{/if}
									</svg>
								</span>
								<span class="text-[13px] font-medium text-gray-800 dark:text-gray-100"
									>{q.title}</span
								>
							</button>
						</li>
					{/each}
				</ul>
			</section>

			{#if chatId && chatTeams.length}
				<section class="mt-8" aria-label="这个对话的协作任务">
					<h3 class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
						这个对话的协作任务
					</h3>
					<ul class="flex flex-col gap-2">
						{#each chatTeams as team (team.id)}
							<li>
								<a
									href="/teams/{team.id}"
									class="tm-card tm-hover flex items-center gap-3 px-4 py-3"
								>
									<span class="min-w-0 flex-1 truncate text-sm font-medium">{team.title}</span>
									<StatusChip
										status={chipOf(statusOf(team))}
										label={PHASE_LABEL[statusOf(team)] ?? statusOf(team)}
									/>
									<span class="text-xs text-sky-700 dark:text-sky-300">打开 →</span>
								</a>
							</li>
						{/each}
					</ul>
				</section>
			{/if}

			<!-- the list -->
			<section class="mt-10" aria-label="我的协作任务">
				<div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
					<h3 class="tm-display text-base font-semibold text-gray-900 dark:text-gray-100">
						我的协作
					</h3>
					{#if teams.length}
						<span class="tm-num text-xs text-gray-400">{teams.length}</span>
					{/if}
					<label class="search ml-auto flex min-w-0 items-center gap-1.5 rounded-xl px-2.5 py-1.5">
						<svg
							class="size-3.5 shrink-0 text-gray-400"
							viewBox="0 0 16 16"
							fill="none"
							aria-hidden="true"
							><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5" /><path
								d="m10.5 10.5 3 3"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
							/></svg
						>
						<span class="sr-only">搜索协作任务</span>
						<input
							type="search"
							bind:value={query}
							placeholder="搜索标题或目标"
							class="w-36 min-w-0 bg-transparent text-xs outline-none placeholder:text-gray-400 sm:w-44"
						/>
					</label>
				</div>
				{#if teams.length}
					<div class="tm-scroll mb-3 overflow-x-auto pb-1">
						<div class="tm-segment" role="tablist" aria-label="按状态筛选">
							{#each FILTERS as f}
								<button
									type="button"
									role="tab"
									aria-selected={filter === f.value}
									class="whitespace-nowrap"
									on:click={() => (filter = f.value)}
									data-filter={f.value}
									>{f.label}{#if counts[f.value]}<span class="tm-num ml-1 opacity-60"
											>{counts[f.value]}</span
										>{/if}</button
								>
							{/each}
						</div>
					</div>
				{/if}

				{#if !loaded}
					<ul class="flex flex-col gap-2" aria-busy="true">
						{#each [0, 1, 2] as i}
							<li class="skeleton tm-card-quiet h-[72px]" style="--i:{i}" />
						{/each}
					</ul>
				{:else if error}
					<div class="text-sm text-red-600" role="alert">{error}</div>
				{:else if teams.length === 0}
					<div class="tm-card-quiet flex flex-col gap-4 px-5 py-6" data-teams-empty>
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100">
							还没有协作任务 · 三步走完一次
						</div>
						<ol class="grid gap-3 sm:grid-cols-3">
							{#each [['描述目标', '在上面写下要完成的事，或点一个快速开始'], ['批准计划', '负责人给出成员分工和任务依赖，你可以改执行来源或要求重做'], ['收结论', '成员并行执行、自动兜底，完成后负责人写出完整报告']] as [title, text], i}
								<li class="flex gap-3">
									<span
										class="tm-num grid size-6 shrink-0 place-items-center rounded-full border text-[11px] font-semibold text-gray-500 tm-hairline"
										>{i + 1}</span
									>
									<div>
										<div class="text-[13px] font-medium text-gray-800 dark:text-gray-100">
											{title}
										</div>
										<div class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
											{text}
										</div>
									</div>
								</li>
							{/each}
						</ol>
					</div>
				{:else if shown.length === 0}
					<div class="py-10 text-center text-sm text-gray-400">没有符合条件的协作任务</div>
				{:else}
					<ul class="flex flex-col gap-2" data-team-list>
						{#each shown as team, i (team.id)}
							{@const s = statusOf(team)}
							{@const bucket = bucketOf(team)}
							{@const p = team.progress}
							{@const total = p?.total || team.task_count || 0}
							{@const done = s === 'completed' ? total : (p?.done ?? 0)}
							<li
								class="row tm-card tm-hover tm-rise relative flex items-center gap-3 px-4 py-3 {bucket ===
									'active' && s !== 'paused'
									? 'tm-live'
									: ''}"
								style="--i:{Math.min(i, 8)}"
								data-team-row={team.id}
								data-bucket={bucket}
							>
								<a
									href="/teams/{team.id}"
									class="min-w-0 flex-1 after:absolute after:inset-0 after:rounded-[1.125rem] focus:outline-none focus-visible:after:ring-2 focus-visible:after:ring-sky-400"
								>
									<div class="flex min-w-0 items-center gap-2">
										<span
											class="min-w-0 truncate text-sm font-medium text-gray-900 dark:text-gray-100"
											>{team.title}</span
										>
									</div>
									<div
										class="mt-1 flex min-w-0 items-center gap-1.5 truncate text-xs text-gray-500 dark:text-gray-400"
									>
										<span class="shrink-0">{timeAgo(team.updated_at, $now)}</span>
										{#if team.task_count}
											<span aria-hidden="true">·</span>
											<span class="shrink-0">{team.member_count} 位成员</span>
										{/if}
										{#if team.executors?.length}
											<span aria-hidden="true">·</span>
											<span class="truncate font-mono text-[11px]"
												>{team.executors.map(runnerLabel).join(' + ')}</span
											>
										{/if}
									</div>
								</a>
								{#if team.roster?.length}
									<span
										class="hidden shrink-0 items-center -space-x-1.5 md:flex"
										aria-hidden="true"
									>
										<span class="stack"><TeamAvatar kind="lead" size={22} /></span>
										{#each team.roster.slice(0, 4) as m}
											<span class="stack"><TeamAvatar kind={avatarKind(m)} size={22} /></span>
										{/each}
										{#if team.roster.length > 4}
											<span
												class="stack tm-num grid size-[22px] place-items-center rounded-full bg-gray-100 text-[10px] text-gray-500 dark:bg-gray-800"
												>+{team.roster.length - 4}</span
											>
										{/if}
									</span>
								{/if}
								{#if total && (bucket === 'active' || bucket === 'done' || s === 'stopped')}
									<span
										class="hidden w-20 shrink-0 flex-col gap-1 sm:flex"
										title="{done}/{total} 个任务完成"
									>
										<span class="tm-num text-right text-[11px] text-gray-500"
											>{done}<span class="opacity-50">/{total}</span></span
										>
										<span
											class="flex h-1 overflow-hidden rounded-full bg-gray-900/[0.06] dark:bg-white/[0.08]"
										>
											<span
												class="h-full rounded-full {s === 'completed'
													? 'bg-emerald-500'
													: 'bg-sky-500'} transition-[width] duration-700"
												style="width:{Math.round((done / total) * 100)}%"
											/>
										</span>
									</span>
								{/if}
								<span class="shrink-0">
									<StatusChip status={chipOf(s)} label={PHASE_LABEL[s] ?? s} />
								</span>
								<span class="actions relative z-10 flex shrink-0 items-center gap-0.5">
									{#if s === 'completed' || s === 'stopped'}
										<a
											href="/teams/{team.id}/conclusion"
											class="icon-btn text-emerald-600 dark:text-emerald-300"
											title="阅读结论"
											aria-label="阅读「{team.title}」的结论"
											><svg class="size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true"
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
											></a
										>
									{/if}
									<button
										type="button"
										class="icon-btn reveal"
										title="用相同目标再发起一次"
										aria-label="用「{team.title}」的目标再发起一次"
										on:click={() => again(team)}
										><svg class="size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true"
											><path
												d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3"
												stroke="currentColor"
												stroke-width="1.4"
												stroke-linecap="round"
												stroke-linejoin="round"
											/></svg
										></button
									>
									{#if team.deletable}
										<button
											type="button"
											class="icon-btn reveal hover:!text-red-600"
											title="删除"
											aria-label="删除「{team.title}」"
											on:click={() => askDelete(team)}
											data-delete-team
											><svg class="size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true"
												><path
													d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.6c.05.8.7 1.4 1.5 1.4h2.8c.8 0 1.45-.6 1.5-1.4l.6-8.6"
													stroke="currentColor"
													stroke-width="1.4"
													stroke-linecap="round"
													stroke-linejoin="round"
												/></svg
											></button
										>
									{/if}
								</span>
							</li>
						{/each}
					</ul>
				{/if}
			</section>
		</div>
	</div>
</div>

<ConfirmDialog
	bind:show={showDelete}
	title="删除这个协作任务？"
	message={`「${pendingDelete?.title ?? ''}」会从你的列表里移除，计划、通讯记录入口和结论入口都不再显示。成员写在工作目录里的文件保留在 Hermes 上。`}
	confirmLabel="删除"
	on:confirm={confirmDelete}
/>

<style>
	.composer {
		border-radius: 1.4rem;
		transition:
			box-shadow 0.3s var(--tm-ease),
			border-color 0.3s ease;
	}
	.composer:focus-within {
		border-color: hsl(var(--tm-accent) / 0.45);
		box-shadow:
			0 0 0 4px hsl(var(--tm-accent) / 0.1),
			var(--tm-shadow-lift);
	}
	.pill {
		border: 1px solid hsl(var(--tm-line));
		background: hsl(var(--tm-surface-2));
		transition:
			border-color 0.15s ease,
			background 0.15s ease;
	}
	.pill:hover {
		border-color: hsl(var(--tm-line-strong));
	}
	/* The app's global `select` rule (unlayered) outranks Tailwind's utilities: size these here. */
	.compact-select {
		font-size: 0.75rem;
		line-height: 1rem;
		padding: 0.15rem 1.5rem 0.15rem 0.2rem;
		background-color: transparent;
		background-size: 1em 1em;
		border: 0;
		color: inherit;
		box-shadow: none;
		font-weight: 500;
	}
	.quick-icon {
		color: hsl(var(--tm-accent));
		background: hsl(var(--tm-accent) / 0.09);
		box-shadow: inset 0 0 0 1px hsl(var(--tm-accent) / 0.14);
	}
	.search {
		border: 1px solid hsl(var(--tm-line));
		background: hsl(var(--tm-surface) / 0.7);
	}
	.search:focus-within {
		border-color: hsl(var(--tm-accent) / 0.45);
	}
	.stack {
		border-radius: 9999px;
		box-shadow: 0 0 0 2px hsl(var(--tm-surface));
	}
	.icon-btn {
		display: grid;
		place-items: center;
		width: 1.85rem;
		height: 1.85rem;
		border-radius: 0.6rem;
		color: hsl(var(--tm-muted));
		transition:
			background 0.15s ease,
			color 0.15s ease,
			opacity 0.2s ease;
	}
	.icon-btn:hover {
		background: hsl(var(--tm-line));
		color: hsl(var(--tm-ink));
	}
	@media (hover: hover) {
		.row .actions .reveal {
			opacity: 0;
		}
		.row:hover .actions .reveal,
		.row:focus-within .actions .reveal {
			opacity: 1;
		}
	}
	.skeleton {
		position: relative;
		overflow: hidden;
	}
	.skeleton::after {
		content: '';
		position: absolute;
		inset: 0;
		background: linear-gradient(90deg, transparent, hsl(var(--tm-line)), transparent);
		animation: skeleton 1.4s ease-in-out infinite;
		animation-delay: calc(var(--i) * 120ms);
	}
	@keyframes skeleton {
		from {
			transform: translateX(-100%);
		}
		to {
			transform: translateX(100%);
		}
	}
</style>

<script lang="ts">
	import { createEventDispatcher, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		approveTeam,
		cancelTeam,
		controlTeam,
		editTeamPlan,
		getTeamsMeta,
		replanTeam,
		retryTeamTask,
		sendTeamMessage,
		taskDiagnosis,
		type HermesModel,
		type LiveSnapshot,
		type LiveTask,
		type Team,
		type TeamExecutor,
		type TeamPlanMember,
		type TeamsMeta
	} from '$lib/apis/teams';
	import TeamAvatar from './TeamAvatar.svelte';
	import {
		avatarKind,
		EXECUTOR_OPTIONS,
		memberModelOptions,
		memberRunner,
		offChainRunners,
		runnerLabel,
		runsOnHermes
	} from './model';

	/**
	 * What the team needs from the user, done right in the chat card instead of on the 协作台:
	 * approve the lead's plan (or ask for another / cancel it), plan again after a failed plan,
	 * answer a member's question or retry its failed task, and stop a team at work. Before approving,
	 * each member's runner and model (the lead's recommendation) can be changed here too. The 协作台
	 * stays the place for the details (each task, the board, the logs).
	 */
	export let teamId: string;
	export let team: Team;
	export let live: LiveSnapshot | null = null;
	/** The stage key the card shows (approval / attention / running / plan_failed / …). */
	export let stageKey = '';

	const dispatch = createEventDispatcher<{ changed: void }>();

	let busy = '';
	let feedback = '';
	let showFeedback = false;
	let replies: Record<string, string> = {};
	let stopArmed = false;
	let stopTimer: ReturnType<typeof setTimeout> | null = null;

	// 「换执行者/模型」: what can run a member and which models Hermes has — read only when opened
	// (Hermes checks every runner for it, which takes a moment).
	let adjusting = false;
	let registry: TeamsMeta['registry'] | null = null;
	let models: HermesModel[] = [];
	let metaState: '' | 'loading' | 'ready' | 'error' = '';
	let metaError = '';

	$: plan = team.plan ?? null;
	$: reviewing = !!plan && ['plan_ready', 'start_failed'].includes(team.status);
	$: members = plan?.members ?? [];
	$: blocked = members.filter((m) => memberRunner(m).actual === null).length;
	$: order = registry?.order?.length ? registry.order : EXECUTOR_OPTIONS.map((o) => o.value);
	$: runnersBy = new Map((registry?.runners ?? []).map((r) => [r.name, r]));
	$: choices = [...order, ...offChainRunners(order, registry?.runners ?? []).map((r) => r.name)];
	// tasks waiting on the user: a member's question first, then failures
	$: needs = (live?.tasks ?? [])
		.filter(
			(t) =>
				['waiting_user', 'failed', 'blocked'].includes(t.sub_status) || t.status === 'triage'
		)
		.sort((a, b) => Number(b.sub_status === 'waiting_user') - Number(a.sub_status === 'waiting_user'))
		.slice(0, 3);
	$: moreNeeds = Math.max(
		0,
		(live?.tasks ?? []).filter(
			(t) => ['waiting_user', 'failed', 'blocked'].includes(t.sub_status) || t.status === 'triage'
		).length - needs.length
	);
	$: working =
		team.status === 'running' &&
		!['completed', 'stopped'].includes(live?.team?.phase ?? team.phase ?? '') &&
		live?.team?.state !== 'stopped';

	const act = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
		if (busy) return false;
		busy = key;
		try {
			await fn();
			if (ok) toast.success(ok);
			dispatch('changed');
			return true;
		} catch (error) {
			toast.error(`${(error as Error)?.message ?? error}`);
			return false;
		} finally {
			busy = '';
		}
	};

	const loadMeta = async () => {
		if (metaState === 'loading' || metaState === 'ready') return;
		metaState = 'loading';
		try {
			const meta = await getTeamsMeta(localStorage.token);
			registry = meta.registry ?? null;
			models = meta.hermes_models ?? [];
			metaState = 'ready';
		} catch (error) {
			metaError = `${(error as Error)?.message ?? error}`;
			metaState = 'error';
		}
	};
	const toggleAdjust = () => {
		adjusting = !adjusting;
		if (adjusting) void loadMeta();
	};
	const runnerOption = (name: string) => {
		const info = runnersBy.get(name as TeamExecutor);
		const base = name === 'hermes' ? 'Hermes 代理' : runnerLabel(name);
		return info && !info.available ? `${base}（不可用）` : base;
	};
	// a refused change puts the selects back to what the plan says
	const edit = async (key: string, change: Parameters<typeof editTeamPlan>[2][number]) => {
		if (!(await act(key, () => editTeamPlan(localStorage.token, teamId, [change])))) team = team;
	};
	const setRunner = (m: TeamPlanMember, value: string, source: 'user' | 'auto' = 'user') =>
		edit(`runner:${m.name}`, {
			name: m.name,
			executor: EXECUTOR_OPTIONS.find((o) => o.value === value)?.value ?? m.executor,
			source
		});
	const setModel = (m: TeamPlanMember, model: string) =>
		edit(
			`model:${m.name}`,
			model ? { name: m.name, model, model_source: 'user' } : { name: m.name, model_source: 'auto' }
		);

	const approve = () =>
		act('approve', () => approveTeam(localStorage.token, teamId), '已批准，成员开始工作');
	const cancel = () => act('cancel', () => cancelTeam(localStorage.token, teamId), '已取消');
	const replan = async () => {
		const done = await act(
			'replan',
			() => replanTeam(localStorage.token, teamId, feedback.trim()),
			'已交给负责人重新规划'
		);
		if (done) {
			feedback = '';
			showFeedback = false;
		}
	};
	const reply = async (task: LiveTask) => {
		const body = (replies[task.id] ?? '').trim();
		if (!body) return;
		const done = await act(`reply:${task.id}`, () =>
			sendTeamMessage(localStorage.token, teamId, task.id, body)
		);
		if (done) {
			replies = { ...replies, [task.id]: '' };
			toast.success(`已回复 ${task.member}`);
		}
	};
	const retry = (task: LiveTask) =>
		act(
			`retry:${task.id}`,
			() => retryTeamTask(localStorage.token, teamId, task.id),
			'已重新排队，会作为新的执行尝试开始'
		);
	const applyDiagnosis = (task: LiveTask) =>
		act(
			`diagnosis:${task.id}`,
			() => taskDiagnosis(localStorage.token, teamId, task.id, 'apply'),
			'已按负责人的建议处理'
		);
	// two presses, like the runner banner: a stray click must not end an hour of work
	const stop = () => {
		if (!stopArmed) {
			stopArmed = true;
			if (stopTimer) clearTimeout(stopTimer);
			stopTimer = setTimeout(() => (stopArmed = false), 4000);
			return;
		}
		stopArmed = false;
		if (stopTimer) clearTimeout(stopTimer);
		void act(
			'stop',
			() => controlTeam(localStorage.token, teamId, 'stop'),
			'已停止：正在执行的成员已结束，不会再自动启动'
		);
	};

	onDestroy(() => {
		if (stopTimer) clearTimeout(stopTimer);
	});

	const reason = (t: LiveTask) =>
		t.sub_status === 'waiting_user'
			? t.block_reason || `${t.member} 在等你回答`
			: t.block_reason || (t.sub_status === 'failed' ? '这一步没有做成' : '这一步卡住了');
</script>

{#if reviewing && plan}
	<div class="tm-card-quiet flex flex-col gap-2.5 px-3.5 py-3" data-team-chat-plan>
		{#if plan.summary}
			<p
				class="line-clamp-3 whitespace-pre-wrap text-xs leading-relaxed text-gray-700 dark:text-gray-200"
				title={plan.summary}
			>
				{plan.summary}
			</p>
		{/if}
		{#if members.length}
			<ul class="flex list-none flex-wrap gap-1.5 p-0" data-team-chat-plan-members>
				{#each members as m (m.name)}
					{@const runner = memberRunner(m)}
					<li
						class="inline-flex max-w-full items-center gap-1.5 rounded-full bg-gray-500/[0.07] px-2 py-[3px] text-[11px]"
						title={m.focus || m.role}
					>
						<TeamAvatar kind={avatarKind(m)} size={14} />
						<span class="truncate font-medium text-gray-800 dark:text-gray-100">{m.name}</span>
						<span
							class="shrink-0 {runner.actual === null
								? 'text-amber-700 dark:text-amber-300'
								: 'text-gray-500 dark:text-gray-400'}"
							>{runner.actual === null ? '无可用执行者' : runnerLabel(runner.actual)}{runsOnHermes(
								m,
								runner.actual
							) && m.model
								? ` · ${m.model}`
								: ''}</span
						>
					</li>
				{/each}
			</ul>
		{/if}
		<p class="text-[11px] text-gray-500 dark:text-gray-400">
			{members.length} 位成员 · {plan.tasks?.length ?? 0} 个任务{plan.project?.name
				? ` · 在 ${plan.project.name} 里做`
				: ''}。批准后成员才开始工作，会消耗模型额度；执行者和模型可以在这里换，细看每个任务到协作台。
		</p>
		{#if blocked}
			<p class="text-[11px] text-amber-700 dark:text-amber-300" data-team-chat-plan-blocked>
				{blocked} 位成员现在没有可用的执行来源，批准时会再检查一次；也可以点「换执行者/模型」给它换一个。
			</p>
		{/if}
		<div class="flex flex-wrap items-center gap-2">
			<button
				type="button"
				class="tm-btn-primary !gap-1 !px-3 !py-1.5 !text-xs"
				disabled={!!busy}
				on:click={approve}
				data-team-chat-approve
				>{busy === 'approve'
					? '处理中…'
					: team.status === 'start_failed'
						? '重新批准'
						: '批准并开始'}</button
			>
			{#if members.length}
				<button
					type="button"
					class="tm-btn-ghost !text-xs"
					aria-expanded={adjusting}
					on:click={toggleAdjust}
					data-team-chat-adjust-toggle>换执行者/模型</button
				>
			{/if}
			<button
				type="button"
				class="tm-btn-ghost !text-xs"
				disabled={!!busy}
				aria-expanded={showFeedback}
				on:click={() => (showFeedback = !showFeedback)}
				data-team-chat-replan-toggle>按意见重新规划</button
			>
			<button
				type="button"
				class="rounded-lg px-2 py-1 text-xs text-gray-500 transition hover:text-red-600 disabled:opacity-50"
				disabled={!!busy}
				on:click={cancel}
				data-team-chat-cancel>{busy === 'cancel' ? '取消中…' : '取消'}</button
			>
		</div>
		{#if adjusting}
			<div class="tm-hairline flex flex-col gap-2 border-t pt-2.5" data-team-chat-adjust>
				{#if metaState === 'loading'}
					<p class="text-[11px] text-gray-500 dark:text-gray-400">正在查看哪些执行者和模型能用…</p>
				{:else if metaState === 'error'}
					<p class="text-[11px] text-amber-700 dark:text-amber-300" data-team-chat-adjust-error>
						没读到可用的执行者和模型：{metaError}
						<button
							type="button"
							class="ml-1 text-sky-700 hover:underline dark:text-sky-300"
							on:click={loadMeta}>再试一次</button
						>
					</p>
				{/if}
				<ul class="flex list-none flex-col gap-2 p-0">
					{#each members as m (m.name)}
						{@const runner = memberRunner(m)}
						{@const onHermes = runsOnHermes(m, runner.actual)}
						<li class="flex min-w-0 flex-col gap-1.5" data-team-chat-adjust-member={m.name}>
							<div class="flex min-w-0 items-center gap-1.5 text-xs">
								<TeamAvatar kind={avatarKind(m)} size={14} />
								<span class="truncate font-medium text-gray-800 dark:text-gray-100">{m.name}</span>
								<span class="truncate text-[11px] text-gray-400">{m.role}</span>
							</div>
							<div class="flex min-w-0 flex-wrap items-center gap-1.5 pl-5">
								<select
									class="chat-select min-w-0 max-w-[12rem] flex-1 truncate rounded-lg border border-gray-200 bg-white py-1 pl-2 pr-6 text-xs text-gray-900 focus:border-sky-400 focus:outline-none disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
									aria-label="{m.name} 的执行者"
									value={m.executor}
									disabled={!!busy || m.kind === 'image'}
									title={m.kind === 'image' ? '生图成员只能由 Hermes 执行' : ''}
									on:change={(e) => setRunner(m, e.currentTarget.value)}
									data-team-chat-runner={m.name}
								>
									{#each choices.includes(m.executor) ? choices : [m.executor, ...choices] as name}
										<option value={name}
											>{runnerOption(name)}{m.recommended === name ? ' · 推荐' : ''}</option
										>
									{/each}
								</select>
								{#if onHermes && (models.length || m.model)}
									<select
										class="chat-select min-w-0 max-w-[14rem] flex-1 truncate rounded-lg border border-gray-200 bg-white py-1 pl-2 pr-6 font-mono text-xs text-gray-900 focus:border-sky-400 focus:outline-none disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
										aria-label="{m.name} 的模型"
										value={m.model ?? ''}
										disabled={!!busy || !models.length}
										on:change={(e) => setModel(m, e.currentTarget.value)}
										data-team-chat-model={m.name}
									>
										{#each memberModelOptions(m, models) as option (option.model)}
											<option value={option.model} title={option.hint}
												>{option.model}{option.model === m.model_recommended
													? ' · 推荐'
													: option.default
														? ' · 默认'
														: ''}</option
											>
										{/each}
									</select>
								{/if}
								{#if m.model_source === 'user' && m.model_recommended && m.model_recommended !== m.model}
									<button
										type="button"
										class="shrink-0 rounded-md px-1.5 py-0.5 text-[11px] text-sky-700 transition hover:bg-sky-50 disabled:opacity-50 dark:text-sky-300 dark:hover:bg-sky-950/40"
										disabled={!!busy}
										title="用负责人推荐的 {m.model_recommended}"
										on:click={() => setModel(m, '')}
										data-team-chat-model-reset={m.name}>恢复推荐模型</button
									>
								{:else if m.executor_source === 'user'}
									<button
										type="button"
										class="shrink-0 rounded-md px-1.5 py-0.5 text-[11px] text-sky-700 transition hover:bg-sky-50 disabled:opacity-50 dark:text-sky-300 dark:hover:bg-sky-950/40"
										disabled={!!busy}
										title="按任务类型重新自动选择执行者"
										on:click={() => setRunner(m, m.executor, 'auto')}
										data-team-chat-runner-reset={m.name}>恢复自动</button
									>
								{/if}
							</div>
							{#if runner.actual === null}
								<p class="pl-5 text-[11px] text-red-700 dark:text-red-300">
									{runnerLabel(runner.chosen)} 之后的执行来源都不可用{runner.reason
										? `：${runner.reason}`
										: ''}
								</p>
							{:else if runner.changed}
								<p class="pl-5 text-[11px] text-amber-800 dark:text-amber-200">
									实际将由 {runnerLabel(runner.actual)} 执行{runner.reason ? ` · ${runner.reason}` : ''}
								</p>
							{/if}
						</li>
					{/each}
				</ul>
				<p class="text-[11px] text-gray-400">
					改完立即生效，批准时按这里的选择开始；执行者不可用时会沿兜底链往后换。
				</p>
			</div>
		{/if}
		{#if showFeedback}
			<div class="flex flex-col gap-1.5">
				<textarea
					bind:value={feedback}
					rows="2"
					maxlength="2000"
					class="w-full rounded-xl border border-gray-200 bg-white px-2.5 py-2 text-xs outline-none transition focus:border-sky-400 dark:border-gray-800 dark:bg-gray-900"
					placeholder="你希望怎么改？例如：再加一个测试成员；前端交给 codex"
					data-team-chat-replan-text
				/>
				<button
					type="button"
					class="tm-btn-primary self-start !py-1 !text-xs"
					disabled={!!busy}
					on:click={replan}
					data-team-chat-replan>{busy === 'replan' ? '提交中…' : '让负责人重新规划'}</button
				>
			</div>
		{/if}
	</div>
{:else if team.status === 'plan_failed'}
	<div class="flex flex-wrap items-center gap-2" data-team-chat-plan-failed>
		<button
			type="button"
			class="tm-btn-primary !px-3 !py-1.5 !text-xs"
			disabled={!!busy}
			on:click={() => act('replan', () => replanTeam(localStorage.token, teamId, ''))}
			data-team-chat-replan-again>{busy === 'replan' ? '处理中…' : '重新生成计划'}</button
		>
		<button
			type="button"
			class="rounded-lg px-2 py-1 text-xs text-gray-500 transition hover:text-red-600 disabled:opacity-50"
			disabled={!!busy}
			on:click={cancel}
			data-team-chat-cancel>取消</button
		>
	</div>
{:else if team.status === 'planning'}
	<button
		type="button"
		class="self-start rounded-lg px-1 text-[11px] text-gray-400 transition hover:text-red-600 disabled:opacity-60 dark:hover:text-red-400"
		disabled={!!busy}
		on:click={cancel}
		data-team-chat-cancel>{busy === 'cancel' ? '取消中…' : '不用了，取消这个协作'}</button
	>
{:else if working}
	{#if needs.length}
		<ul class="flex list-none flex-col gap-2 p-0" data-team-chat-needs>
			{#each needs as task (task.id)}
				{@const diagnosis = task.diagnosis?.status === 'ready' ? task.diagnosis : null}
				<li
					class="tm-card-quiet flex flex-col gap-1.5 px-3.5 py-2.5"
					data-team-chat-need={task.sub_status}
				>
					<div class="flex min-w-0 items-center gap-2 text-xs">
						<TeamAvatar kind={avatarKind({ name: task.member })} size={16} status="waiting_user" />
						<span class="shrink-0 font-medium text-gray-900 dark:text-gray-100">{task.member}</span>
						<span class="truncate text-gray-500 dark:text-gray-400" title={task.title}
							>#{task.key} {task.title}</span
						>
					</div>
					<p class="whitespace-pre-wrap text-xs leading-relaxed text-gray-700 dark:text-gray-200">
						{reason(task)}
					</p>
					{#if task.sub_status === 'waiting_user'}
						<div class="flex items-end gap-2">
							<textarea
								bind:value={replies[task.id]}
								rows="1"
								maxlength="4000"
								class="min-w-0 flex-1 resize-none rounded-xl border border-gray-200 bg-white px-2.5 py-1.5 text-xs outline-none transition focus:border-sky-400 dark:border-gray-800 dark:bg-gray-900"
								placeholder="回答 {task.member}…"
								on:keydown={(e) => {
									if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
										e.preventDefault();
										void reply(task);
									}
								}}
								data-team-chat-reply-text={task.id}
							/>
							<button
								type="button"
								class="tm-btn-primary shrink-0 !px-2.5 !py-1 !text-xs"
								disabled={!!busy || !(replies[task.id] ?? '').trim()}
								on:click={() => reply(task)}
								data-team-chat-reply={task.id}
								>{busy === `reply:${task.id}` ? '发送中…' : '回复'}</button
							>
						</div>
					{:else}
						<div class="flex flex-wrap items-center gap-2">
							{#if diagnosis?.action_label}
								<button
									type="button"
									class="tm-btn-primary !px-2.5 !py-1 !text-xs"
									disabled={!!busy}
									title={diagnosis.cause || ''}
									on:click={() => applyDiagnosis(task)}
									data-team-chat-diagnosis={task.id}
									>{busy === `diagnosis:${task.id}`
										? '处理中…'
										: `按负责人建议：${diagnosis.action_label}`}</button
								>
							{/if}
							<button
								type="button"
								class="tm-btn-ghost !text-xs"
								disabled={!!busy}
								on:click={() => retry(task)}
								data-team-chat-retry={task.id}
								>{busy === `retry:${task.id}` ? '排队中…' : '重试这一步'}</button
							>
						</div>
					{/if}
				</li>
			{/each}
		</ul>
		{#if moreNeeds}
			<a href="/teams/{teamId}" class="self-start text-xs text-sky-700 hover:underline dark:text-sky-300"
				>还有 {moreNeeds} 个任务等你处理，到协作台看 →</a
			>
		{/if}
	{/if}
	{#if stageKey !== 'done'}
		<button
			type="button"
			class="self-start rounded-lg px-1 text-[11px] transition disabled:opacity-60 {stopArmed
				? 'font-medium text-red-600 dark:text-red-400'
				: 'text-gray-400 hover:text-red-600 dark:hover:text-red-400'}"
			disabled={busy === 'stop'}
			on:click={stop}
			data-team-chat-stop>{busy === 'stop' ? '停止中…' : stopArmed ? '确认停止整个团队？' : '停止团队'}</button
		>
	{/if}
{/if}

<style>
	/* The app's global `select` rule (unlayered) outranks Tailwind's utilities: size these here. */
	.chat-select {
		font-size: 0.75rem;
		line-height: 1rem;
		padding: 0.3rem 1.6rem 0.3rem 0.5rem;
		background-size: 1em 1em;
	}
</style>

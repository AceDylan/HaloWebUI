<script lang="ts">
	import { createEventDispatcher, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		approveTeam,
		cancelTeam,
		controlTeam,
		replanTeam,
		retryTeamTask,
		sendTeamMessage,
		taskDiagnosis,
		type LiveSnapshot,
		type LiveTask,
		type Team
	} from '$lib/apis/teams';
	import TeamAvatar from './TeamAvatar.svelte';
	import { avatarKind, memberRunner, runnerLabel } from './model';

	/**
	 * What the team needs from the user, done right in the chat card instead of on the 协作台:
	 * approve the lead's plan (or ask for another / cancel it), plan again after a failed plan,
	 * answer a member's question or retry its failed task, and stop a team at work. The 协作台
	 * stays the place for the details (runners per member, the board, the logs).
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

	$: plan = team.plan ?? null;
	$: reviewing = !!plan && ['plan_ready', 'start_failed'].includes(team.status);
	$: members = plan?.members ?? [];
	$: blocked = members.filter((m) => memberRunner(m).actual === null).length;
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
							>{runner.actual === null ? '无可用执行者' : runnerLabel(runner.actual)}</span
						>
					</li>
				{/each}
			</ul>
		{/if}
		<p class="text-[11px] text-gray-500 dark:text-gray-400">
			{members.length} 位成员 · {plan.tasks?.length ?? 0} 个任务{plan.project?.name
				? ` · 在 ${plan.project.name} 里做`
				: ''}。批准后成员才开始工作，会消耗模型额度；要换执行者或细看每个任务，到协作台调整。
		</p>
		{#if blocked}
			<p class="text-[11px] text-amber-700 dark:text-amber-300" data-team-chat-plan-blocked>
				{blocked} 位成员现在没有可用的执行来源，批准时会再检查一次；也可以到协作台给它换一个。
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

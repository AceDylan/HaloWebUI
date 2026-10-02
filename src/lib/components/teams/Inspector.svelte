<script lang="ts">
	import { createEventDispatcher, getContext, onDestroy, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getTeamTask,
		retryTeamTask,
		sendTeamMessage,
		taskDiagnosis,
		type LiveTask,
		type TaskDetail,
		type TeamEvent
	} from '$lib/apis/teams';
	import { teamFilePath } from '$lib/apis/teams';
	import ReportMarkdown from './ReportMarkdown.svelte';
	import RunnerBadge from './RunnerBadge.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import {
		avatarKind,
		formatClock,
		isRunnerExecutor,
		KIND_LABEL,
		memberRunner,
		openParents,
		plainPreview,
		prepareReport,
		RUNNER_EVENT_LABEL,
		RUNNER_PHASE_LABEL,
		runnerLabel,
		SOURCE_LABEL,
		taskRunner,
		toneOf,
		type TaskState,
		type Tone
	} from './model';
	import { elapsed, now } from './clock';
	import { TONE_DOT, TONE_TEXT } from './tones';

	const OUTCOME_LABEL: Record<string, string> = {
		completed: '完成',
		done: '完成',
		failed: '失败',
		crashed: '中途退出',
		blocked: '受阻',
		stopped: '已停止',
		timed_out: '超时',
		running: '执行中',
		reclaimed: '被收回重派',
		spawn_failed: '没启动起来',
		cancelled: '已取消',
		timeout: '超时',
		review_requested: '转评审'
	};

	const OUTCOME_TONE: Record<string, Tone> = {
		completed: 'done',
		done: 'done',
		failed: 'fail',
		crashed: 'fail',
		spawn_failed: 'fail',
		timed_out: 'fail',
		timeout: 'fail',
		blocked: 'deps',
		reclaimed: 'deps',
		stopped: 'stop',
		cancelled: 'stop',
		running: 'run',
		review_requested: 'user'
	};

	/** Details of the selected task or member. Read-only in a replay. */
	export let teamId: string;
	export let taskId: string | null = null;
	export let memberName: string | null = null;
	export let tasks: LiveTask[] = [];
	export let states: Map<string, TaskState> = new Map();
	export let members: {
		name: string;
		role: string;
		executor: string;
		focus?: string;
		status?: string;
		kind?: string;
		assistant?: { id: string; name: string; emoji?: string; description?: string } | null;
		recommended?: string;
		executor_source?: string;
		runner?: string | null;
		runner_note?: string;
		actualRunner?: string | null;
		model?: string;
	}[] = [];
	/** Workspace of the team: absolute paths in a result that point into it become links. */
	export let workspace: string | null = null;
	export let events: TeamEvent[] = [];
	export let replay = false;
	export let teamStopped = false;
	/** Bumped by the parent when new events arrive for the shown task, to refresh the detail. */
	export let refreshKey = 0;

	const dispatch = createEventDispatcher();
	let detail: TaskDetail | null = null;
	let loadError = '';
	let loading = false;
	let logText: TaskDetail['log'] | null = null;
	let logLoading = false;
	let note = '';
	let sending = false;
	let lastExpect = '';
	let retrying = false;
	let diagnosing: '' | 'apply' | 'again' = '';
	let loadedFor = '';
	// The log of a running task follows along (re-read every few seconds, kept scrolled to the end).
	const LOG_FOLLOW_MS = 4000;
	let follow = true;
	let logTimer: ReturnType<typeof setInterval> | null = null;
	let logEl: HTMLPreElement | null = null;

	$: task = tasks.find((t) => t.id === taskId) ?? null;
	$: state = task
		? (states.get(task.id) ?? { status: task.status, sub_status: task.sub_status })
		: null;
	$: member = members.find((m) => m.name === (task ? task.member : memberName)) ?? null;
	$: keyOf = new Map(tasks.map((t) => [t.id, t.key]));
	$: waitingFor =
		task && state?.sub_status === 'waiting_deps'
			? openParents(task, states).map((p) => keyOf.get(p) ?? p)
			: [];
	$: canWrite =
		!replay && !teamStopped && task && !['done', 'archived'].includes(state?.status ?? '');
	// A member that stopped on the board to ask (Kanban block, not a runner's open question) can be
	// started again too; a note answering it does that by itself.
	$: canRetry =
		!replay &&
		!teamStopped &&
		task &&
		(['failed', 'blocked'].includes(state?.sub_status ?? '') ||
			(state?.sub_status === 'waiting_user' && state?.status === 'blocked'));
	$: memberTasks = memberName ? tasks.filter((t) => t.member === memberName) : [];
	// A note to a member goes to the task it is on now, else its next unfinished one.
	$: memberTarget =
		memberTasks.find((t) => ['running', 'review'].includes(states.get(t.id)?.status ?? t.status)) ??
		memberTasks.find((t) => !['done', 'archived'].includes(states.get(t.id)?.status ?? t.status)) ??
		null;
	$: canWriteMember = !replay && !teamStopped && !!memberTarget;
	$: memberTools = memberName
		? events
				.filter((e) => e.member === memberName && (e.type === 'tool' || e.type === 'subagent'))
				.slice(-40)
				.reverse()
		: [];
	$: taskEvents = task
		? events
				.filter((e) => e.task_id === task.id && e.type !== 'tool')
				.slice(-30)
				.reverse()
		: [];
	$: decision = task ? taskRunner(task) : null;
	$: trail = task?.trail ?? detail?.runner?.trail ?? [];
	$: memberDecision = member ? memberRunner(member) : null;
	$: resultMd = detail?.result
		? prepareReport(detail.result, { workspace, fileUrl: (path) => teamFilePath(teamId, path) })
		: '';

	/**
	 * Dot colour, headline and headline colour of one entry on a task's record. Status and attempt
	 * events are one short sentence, so that sentence is the headline and there is no body.
	 */
	const eventMark = (
		ev: TeamEvent
	): { dot: string; text: string; label: string; body: boolean } => {
		if (ev.type === 'message' && ev.who === 'user')
			return {
				dot: 'bg-violet-500',
				text: 'text-violet-700 dark:text-violet-300',
				label: `${ev.author ?? '你'} → ${ev.member ?? '成员'}`,
				body: true
			};
		if (ev.type === 'message')
			return {
				dot: 'bg-sky-500',
				text: 'text-gray-800 dark:text-gray-100',
				label: `${ev.member ?? ev.author ?? '成员'} 留言`,
				body: true
			};
		if (ev.type === 'handoff')
			return {
				dot: 'bg-emerald-500',
				text: 'text-emerald-700 dark:text-emerald-300',
				label: ev.data?.to?.length
					? `完成并交接 → ${ev.data.to.map((t) => t.member).join('、')}`
					: '完成',
				body: true
			};
		if (ev.type === 'runner')
			return {
				dot: 'bg-orange-500',
				text: 'text-orange-700 dark:text-orange-300',
				label: `${ev.data?.runner ?? 'runner'} ${RUNNER_EVENT_LABEL[ev.data?.phase] ?? ev.data?.phase ?? ''}`,
				body: true
			};
		if (ev.type === 'subagent')
			return {
				dot: 'bg-gray-300 dark:bg-gray-600',
				text: 'text-gray-500',
				label: ev.data?.phase === 'start' ? '派出子代理' : '子代理结束',
				body: true
			};
		return {
			dot: ev.sub_status ? TONE_DOT[toneOf(ev.sub_status)] : 'bg-gray-400 dark:bg-gray-500',
			text: 'text-gray-700 dark:text-gray-200',
			label: ev.text || (ev.type === 'delivery' ? '说明送达' : '状态变化'),
			body: false
		};
	};

	const load = async (id: string) => {
		loading = true;
		loadError = '';
		try {
			detail = await getTeamTask(localStorage.token, teamId, id);
		} catch (error) {
			loadError = `${error?.message ?? error}`;
		} finally {
			loading = false;
		}
	};

	$: if (taskId && !replay && `${taskId}:${refreshKey}` !== loadedFor) {
		if (!loadedFor.startsWith(`${taskId}:`)) {
			detail = null;
			logText = null;
			lastExpect = '';
		}
		loadedFor = `${taskId}:${refreshKey}`;
		load(taskId);
	}

	const loadLog = async (quiet = false) => {
		if (!taskId) return;
		const id = taskId;
		const atEnd = !logEl || logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 24;
		if (!quiet) logLoading = true;
		try {
			const log = (await getTeamTask(localStorage.token, teamId, id, true)).log ?? null;
			if (id !== taskId) return;
			logText = log;
			await tick();
			if (logEl && (atEnd || !quiet)) logEl.scrollTop = logEl.scrollHeight;
		} catch (error) {
			if (!quiet) toast.error(`读取日志失败：${error?.message ?? error}`);
		} finally {
			logLoading = false;
		}
	};

	$: liveTask = ['running', 'review'].includes(state?.sub_status ?? '');
	$: following = !!logText && follow && liveTask && !replay;
	$: if (following && !logTimer) {
		logTimer = setInterval(() => loadLog(true), LOG_FOLLOW_MS);
	} else if (!following && logTimer) {
		clearInterval(logTimer);
		logTimer = null;
	}
	onDestroy(() => {
		if (logTimer) clearInterval(logTimer);
	});

	const send = async () => {
		const body = note.trim();
		const target = taskId ?? memberTarget?.id ?? null;
		if (!body || !target || sending) return;
		sending = true;
		try {
			const result = await sendTeamMessage(localStorage.token, teamId, target, body);
			note = '';
			lastExpect = result.expect;
			dispatch('changed');
		} catch (error) {
			toast.error(`${error?.message ?? error}`);
		} finally {
			sending = false;
		}
	};

	// The lead's suggestion for a failed task: apply it, or have the lead look again.
	$: diagnosis = canRetry ? (task?.diagnosis ?? null) : null;
	const diagnose = async (action: 'apply' | 'again') => {
		if (!taskId || diagnosing) return;
		diagnosing = action;
		try {
			await taskDiagnosis(localStorage.token, teamId, taskId, action);
			if (action === 'apply') toast.success('已按负责人的建议处理');
			dispatch('changed');
		} catch (error) {
			toast.error(`${error?.message ?? error}`);
		} finally {
			diagnosing = '';
		}
	};

	const retry = async () => {
		if (!taskId || retrying) return;
		retrying = true;
		try {
			await retryTeamTask(localStorage.token, teamId, taskId);
			toast.success('已重新排队，会作为新的执行尝试开始；已完成的任务不会重做');
			dispatch('changed');
		} catch (error) {
			toast.error(`${error?.message ?? error}`);
		} finally {
			retrying = false;
		}
	};
</script>

<section
	class="flex flex-col gap-3 text-sm min-w-0"
	aria-label={task ? `任务 ${task.key} 详情` : `成员 ${memberName} 详情`}
	data-team-inspector
>
	<div class="flex items-start gap-2">
		<div class="min-w-0 flex-1">
			{#if task}
				<div class="flex items-center gap-2 flex-wrap">
					<span class="font-mono text-xs font-semibold text-gray-500">#{task.key}</span>
					<StatusChip status={state?.sub_status} size="sm" />
					{#if task.attempts > 0}<span class="text-xs text-gray-400">{task.attempts} 次执行</span
						>{/if}
				</div>
				<h3
					class="tm-display mt-1 break-words text-[15px] font-semibold text-gray-900 dark:text-gray-50"
				>
					{task.title}
				</h3>
			{:else if member}
				<div class="flex items-center gap-2.5">
					<TeamAvatar kind={avatarKind(member)} status={member.status} size={40} />
					<div class="min-w-0">
						<h3 class="font-semibold text-gray-900 dark:text-gray-100">{member.name}</h3>
						<div class="truncate text-xs text-gray-500">
							{member.role}{member.kind ? ` · ${KIND_LABEL[member.kind] ?? member.kind}` : ''}
						</div>
					</div>
				</div>
			{/if}
		</div>
		<button
			type="button"
			class="grid size-7 place-items-center rounded-lg text-gray-400 transition hover:bg-gray-500/10 hover:text-gray-700 dark:hover:text-gray-200"
			aria-label="关闭详情"
			title="关闭（Esc）"
			on:click={() => dispatch('close')}
			><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
				><path
					d="m4 4 8 8M12 4l-8 8"
					stroke="currentColor"
					stroke-width="1.6"
					stroke-linecap="round"
				/></svg
			></button
		>
	</div>

	{#if replay}
		<div
			class="rounded-xl border border-sky-500/20 bg-sky-500/[0.07] px-3 py-2 text-xs text-sky-800 dark:text-sky-200"
		>
			回放中：这里只显示到当前时点的记录，发送说明、重试等操作已停用。回到实时后可以操作。
		</div>
	{/if}

	{#if task}
		{#if member}
			<div class="flex items-center gap-2 text-xs text-gray-500">
				<TeamAvatar kind={avatarKind(member)} size={22} />
				<span class="min-w-0 truncate"
					>{member.name}（{member.assistant?.emoji
						? `${member.assistant.emoji} `
						: ''}{member.role}）</span
				>
			</div>
		{/if}
		{#if decision}
			<div class="rounded-xl border tm-hairline px-3 py-2 text-xs" data-task-runner>
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
					<span class="text-gray-500">执行来源</span>
					<RunnerBadge
						chosen={decision.chosen}
						actual={decision.actual}
						reason={decision.reason}
						model={task?.model}
						size="sm"
					/>
					<span class="text-gray-400">{SOURCE_LABEL[decision.source] ?? ''}</span>
				</div>
				{#if decision.changed && decision.chosen !== decision.actual}
					<div class="mt-1 text-amber-800 dark:text-amber-200">
						默认 {runnerLabel(decision.chosen)}，实际由 {runnerLabel(decision.actual)} 执行{decision.reason
							? `：${decision.reason}`
							: ''}
					</div>
				{/if}
				{#if trail.length}
					<ol class="mt-1.5 space-y-0.5 border-t tm-hairline pt-1.5" aria-label="改派记录">
						{#each trail as step}
							<li class="flex gap-1.5 text-gray-500">
								<time class="shrink-0 font-mono text-gray-400">{formatClock(step.at)}</time>
								<span class="min-w-0 break-words"
									>{RUNNER_PHASE_LABEL[step.phase] ?? step.phase}：{runnerLabel(step.from)} → {step.to
										? runnerLabel(step.to)
										: '无可用'}{step.reason ? `（${step.reason}）` : ''}</span
								>
							</li>
						{/each}
					</ol>
				{/if}
			</div>
		{/if}
		{#if waitingFor.length}
			<div
				class="rounded-xl border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2 text-xs text-amber-800 dark:text-amber-200"
			>
				等待前置任务：{waitingFor.map((k) => `#${k}`).join('、')} 完成后才会开始（由派发器检查依赖，不会提前执行）。
			</div>
		{/if}
		{#if task.block_reason && !replay}
			<div
				class="rounded-xl border border-red-500/20 bg-red-500/[0.07] px-3 py-2 text-xs text-red-800 dark:text-red-200 whitespace-pre-wrap break-words"
			>
				{task.block_reason}
			</div>
		{/if}
		{#if !replay && task.current_run?.question}
			<div
				class="rounded-xl border border-violet-500/20 bg-violet-500/[0.07] px-3 py-2 text-xs text-violet-900 dark:text-violet-100 whitespace-pre-wrap break-words"
			>
				<div class="font-semibold mb-1">{task.executor} 在等你回答：</div>
				{task.current_run.question}
			</div>
		{/if}
		{#if !replay && task.current_run?.runner_phase === 'quota_wait'}
			<div
				class="rounded-xl border border-orange-500/20 bg-orange-500/[0.07] px-3 py-2 text-xs text-orange-900 dark:text-orange-100"
			>
				额度等待中（不是失败）：{task.current_run.resume_at
					? `约 ${task.current_run.resume_at} 自动续跑同一会话`
					: '额度恢复后自动继续'}
			</div>
		{/if}

		{#if diagnosis}
			<div
				class="diagnosis rounded-xl border px-3 py-2.5 text-xs"
				data-task-diagnosis={diagnosis.status}
			>
				<div class="flex items-center gap-2">
					<TeamAvatar
						kind="lead"
						size={18}
						status={diagnosis.status === 'thinking' ? 'running' : null}
					/>
					<span class="font-semibold text-gray-900 dark:text-gray-50">负责人诊断</span>
					{#if diagnosis.model}<span class="ml-auto font-mono text-[11px] text-gray-400"
							>{diagnosis.model}</span
						>{/if}
				</div>
				{#if diagnosis.status === 'thinking'}
					<p class="tm-shimmer mt-1.5 text-gray-500">负责人在看原因和日志，想怎么处理…</p>
				{:else if diagnosis.status === 'failed'}
					<p class="mt-1.5 text-gray-600 dark:text-gray-300">
						没诊断出来：{diagnosis.error ?? '原因未知'}
					</p>
				{:else}
					<p
						class="mt-1.5 whitespace-pre-wrap break-words text-[12.5px] text-gray-800 dark:text-gray-100"
					>
						{diagnosis.cause}
					</p>
					<p class="mt-1.5 text-gray-600 dark:text-gray-300">
						<span class="font-medium text-violet-700 dark:text-violet-300"
							>建议：{diagnosis.action_label}</span
						>{#if diagnosis.action === 'switch_runner' && diagnosis.runner}（改由 {runnerLabel(
								diagnosis.runner
							)} 执行）{/if}
					</p>
					{#if diagnosis.note}
						<p
							class="mt-1 whitespace-pre-wrap break-words rounded-lg bg-violet-500/[0.07] px-2 py-1.5 text-gray-700 dark:text-gray-200"
						>
							{diagnosis.action === 'ask_user' ? '要问你：' : '给成员的说明：'}{diagnosis.note}
						</p>
					{/if}
					{#if diagnosis.action === 'ask_user'}
						<p class="mt-1 text-gray-500">
							在下面给成员写上你的答复：停下来等你的任务，发出去就接着做；失败的任务写完再点重试。
						</p>
					{/if}
				{/if}
				{#if diagnosis.status !== 'thinking'}
					<div class="mt-2 flex flex-wrap gap-2">
						{#if diagnosis.status === 'ready' && diagnosis.action !== 'ask_user'}
							<button
								type="button"
								class="tm-btn-primary !py-1 !text-xs"
								disabled={!!diagnosing || retrying}
								on:click={() => diagnose('apply')}
								data-diagnosis-apply>{diagnosing === 'apply' ? '正在处理…' : '按建议处理'}</button
							>
						{/if}
						<button
							type="button"
							class="tm-btn-ghost"
							disabled={!!diagnosing}
							on:click={() => diagnose('again')}
							data-diagnosis-again>{diagnosing === 'again' ? '正在请负责人…' : '再诊断一次'}</button
						>
					</div>
				{/if}
			</div>
		{/if}

		{#if canRetry}
			<button
				type="button"
				class="tm-btn-primary self-start !py-1.5 !text-xs"
				disabled={retrying}
				on:click={retry}>{retrying ? '正在重试…' : '重试这个任务（新的执行尝试）'}</button
			>
		{/if}

		{#if !replay}
			{#if loading && !detail}
				<div class="text-xs text-gray-400">正在读取详情…</div>
			{:else if loadError}
				<div class="text-xs text-red-600">读取详情失败：{loadError}</div>
			{/if}
			{#if detail}
				<details class="group">
					<summary class="tm-eyebrow cursor-pointer">任务说明</summary>
					<div
						class="tm-card-quiet tm-scroll mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap break-words p-2.5 text-xs text-gray-700 dark:text-gray-300"
					>
						{detail.body}
					</div>
				</details>
				{#if resultMd}
					<div>
						<div class="tm-eyebrow">结果 / 交接</div>
						<div
							class="tm-scroll mt-1 max-h-96 overflow-y-auto rounded-xl border border-emerald-500/20 bg-emerald-500/[0.05] px-3 py-2"
							data-task-result
						>
							<ReportMarkdown id={`team-task-${task.key}`} content={resultMd} />
						</div>
					</div>
				{/if}
				{#if detail.attempts.length}
					<div>
						<div class="tm-eyebrow">执行尝试</div>
						<ol class="mt-1 space-y-1">
							{#each detail.attempts as attempt (attempt.id)}
								{@const result = attempt.outcome ?? attempt.status}
								{@const tone = OUTCOME_TONE[result] ?? 'wait'}
								<li class="rounded-xl border tm-hairline px-2.5 py-1.5 text-xs">
									<div class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
										<span
											class="size-1.5 shrink-0 rounded-full {TONE_DOT[tone]} {tone === 'run'
												? 'tm-pulse-dot text-sky-500'
												: ''}"
											aria-hidden="true"
										/>
										<span class="font-medium text-gray-800 dark:text-gray-100"
											>第 {attempt.n} 次</span
										>
										<span class="{TONE_TEXT[tone]} font-medium"
											>{OUTCOME_LABEL[result] ?? result}</span
										>
										{#if attempt.started_at}
											<span class="tm-num text-gray-500 dark:text-gray-400"
												>{attempt.ended_at
													? elapsed(attempt.ended_at - attempt.started_at)
													: elapsed($now - attempt.started_at)}</span
											>
										{/if}
										<span class="tm-num ml-auto text-[11px] text-gray-400"
											>{formatClock(attempt.started_at)}{attempt.ended_at
												? ` – ${formatClock(attempt.ended_at)}`
												: ''}</span
										>
									</div>
									{#if attempt.runner_run_id}
										<div class="mt-0.5 break-all font-mono text-[11px] text-gray-500">
											{attempt.runner ?? task.executor} run {attempt.runner_run_id}{attempt.parent_runner_run_id
												? `（接续 ${attempt.parent_runner_run_id}）`
												: ''}
										</div>
									{/if}
									{#if attempt.error}<div class="mt-0.5 break-words text-red-600 dark:text-red-300">
											{attempt.error}
										</div>{/if}
								</li>
							{/each}
						</ol>
					</div>
				{/if}
				<div>
					{#if logText}
						<div class="flex items-center justify-between text-xs">
							<span class="font-medium text-gray-600 dark:text-gray-300"
								>日志（{logText.source}，最后一段）</span
							>
							<span class="flex items-center gap-2">
								{#if liveTask && !replay}
									<button
										type="button"
										class="inline-flex items-center gap-1 {follow
											? 'text-emerald-600 dark:text-emerald-300'
											: 'text-gray-400'}"
										aria-pressed={follow}
										title="运行中每 4 秒刷新一次并停在末尾"
										on:click={() => (follow = !follow)}
										data-log-follow
										><span
											class="size-1.5 rounded-full {following
												? 'tm-pulse-dot bg-emerald-500 text-emerald-500'
												: 'bg-gray-400'}"
											aria-hidden="true"
										/>实时跟随</button
									>
								{/if}
								<button
									type="button"
									class="text-sky-600 hover:underline"
									on:click={() => loadLog()}>刷新</button
								>
							</span>
						</div>
						{#if logText.note}<div class="text-xs text-gray-400">{logText.note}</div>{/if}
						<pre
							bind:this={logEl}
							class="tm-scroll mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-[#0b0d13] p-3 text-[11px] leading-snug text-gray-100 ring-1 ring-white/10">{logText.text ||
								'（空）'}</pre>
					{:else}
						<button
							type="button"
							class="tm-btn-ghost"
							disabled={logLoading}
							on:click={() => loadLog()}>{logLoading ? '读取中…' : '查看日志'}</button
						>
					{/if}
				</div>
			{/if}
		{/if}

		{#if taskEvents.length}
			<div data-task-timeline>
				<div class="tm-eyebrow">这个任务的记录</div>
				<ol class="trail relative mt-2 text-xs" aria-label="这个任务的记录，最新的在上面">
					{#each taskEvents as ev (ev.id)}
						{@const mark = eventMark(ev)}
						<li class="relative pb-2.5 pl-5 last:pb-0">
							<span
								class="absolute left-[3px] top-[5px] size-[7px] rounded-full ring-[3px] ring-[hsl(var(--tm-surface))] {mark.dot}"
								aria-hidden="true"
							/>
							<div class="flex min-w-0 items-center gap-1.5">
								<span class="min-w-0 truncate font-medium {mark.text}">{mark.label}</span>
								{#if ev.sub_status && (ev.type === 'status' || ev.type === 'attempt')}
									<StatusChip status={ev.sub_status} />
								{/if}
								<time class="tm-num ml-auto shrink-0 text-[11px] text-gray-400"
									>{formatClock(ev.ts)}</time
								>
							</div>
							{#if ev.text && mark.body}
								<div
									class="mt-0.5 line-clamp-3 whitespace-pre-wrap break-words text-gray-600 dark:text-gray-300"
								>
									{plainPreview(ev.text)}
								</div>
							{/if}
						</li>
					{/each}
				</ol>
			</div>
		{/if}

		{#if canWrite}
			<form class="flex flex-col gap-1.5" on:submit|preventDefault={send}>
				<label class="tm-eyebrow" for="team-note-{task.id}">给 {task.member} 补充说明</label>
				<textarea
					id="team-note-{task.id}"
					bind:value={note}
					rows="3"
					maxlength="4000"
					class="note w-full resize-y rounded-xl px-3 py-2 text-sm outline-none"
					placeholder={isRunnerExecutor(task.executor)
						? `${task.executor} 运行中收不到消息，会在它这一轮结束后续跑送达`
						: '成员正在执行时，会在当前这批工具调用结束后读到'}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
					}}
				/>
				<div class="flex items-center gap-2">
					<button
						type="submit"
						class="tm-btn-primary !py-1.5 !text-xs"
						disabled={sending || !note.trim()}>{sending ? '发送中…' : '发送'}</button
					>
					<span class="text-[11px] text-gray-400">Ctrl+Enter 发送 · 只发给这个任务的成员</span>
				</div>
				{#if lastExpect}<div class="text-xs text-violet-700 dark:text-violet-300">
						已排队：{lastExpect}
					</div>{/if}
			</form>
		{/if}
	{:else if member}
		{#if member.focus}<p class="text-xs text-gray-600 dark:text-gray-300">{member.focus}</p>{/if}
		<dl
			class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 rounded-xl border tm-hairline px-3 py-2 text-xs"
			data-member-profile
		>
			<dt class="text-gray-500">助手模板</dt>
			<dd class="min-w-0 text-gray-800 dark:text-gray-200">
				{#if member.assistant}
					<span title={member.assistant.description ?? ''}
						>{member.assistant.emoji ?? ''} {member.assistant.name}</span
					>
				{:else}
					<span class="text-gray-500">自定义角色（没有合适的模板）</span>
				{/if}
			</dd>
			<dt class="text-gray-500">执行来源</dt>
			<dd class="flex min-w-0 flex-wrap items-center gap-1.5">
				<RunnerBadge
					chosen={member.executor}
					actual={member.actualRunner ?? memberDecision?.actual ?? member.executor}
					model={member.model}
					size="sm"
				/>
				<span class="text-gray-400"
					>{SOURCE_LABEL[memberDecision?.source ?? 'auto']}{member.recommended &&
					member.recommended !== member.executor
						? `（推荐 ${runnerLabel(member.recommended)}）`
						: ''}</span
				>
			</dd>
		</dl>
		{#if canWriteMember && memberTarget}
			<form class="flex flex-col gap-1.5" on:submit|preventDefault={send} data-member-note>
				<label class="tm-eyebrow" for="team-member-note-{member.name}"
					>给 {member.name} 补充说明（发到它{['running', 'review'].includes(
						states.get(memberTarget.id)?.status ?? memberTarget.status
					)
						? '正在做'
						: '接下来要做'}的 #{memberTarget.key}）</label
				>
				<textarea
					id="team-member-note-{member.name}"
					bind:value={note}
					rows="3"
					maxlength="4000"
					class="note w-full resize-y rounded-xl px-3 py-2 text-sm outline-none"
					placeholder={isRunnerExecutor(member.executor)
						? `${member.executor} 运行中收不到消息，会在它这一轮结束后续跑送达`
						: '成员正在执行时，会在当前这批工具调用结束后读到'}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
					}}
				/>
				<button
					type="submit"
					class="tm-btn-primary self-start !py-1.5 !text-xs"
					disabled={sending || !note.trim()}>{sending ? '发送中…' : '发送'}</button
				>
				{#if lastExpect}<div class="text-xs text-violet-700 dark:text-violet-300">
						已排队：{lastExpect}
					</div>{/if}
			</form>
		{/if}
		<div>
			<div class="tm-eyebrow">负责的任务</div>
			<ul class="mt-1 space-y-1">
				{#each memberTasks as t (t.id)}
					<li>
						<button
							type="button"
							class="flex w-full items-center gap-2 rounded-xl border tm-hairline px-2 py-1.5 text-left text-xs tm-hover"
							on:click={() => dispatch('task', t.id)}
						>
							<span class="font-mono text-gray-500">#{t.key}</span>
							<span class="truncate flex-1">{t.title}</span>
							<StatusChip status={states.get(t.id)?.sub_status ?? t.sub_status} />
						</button>
					</li>
				{/each}
			</ul>
		</div>
		<div>
			<div class="tm-eyebrow">最近的工具记录</div>
			{#if memberTools.length === 0}
				<div class="mt-1 text-xs text-gray-400">还没有工具记录</div>
			{:else}
				<ol class="trail relative mt-2 text-[11px]">
					{#each memberTools as ev (ev.id)}
						<li class="relative pb-1.5 pl-5 last:pb-0">
							<span
								class="absolute left-[4px] top-[5px] size-[5px] rounded-full bg-gray-300 ring-[3px] ring-[hsl(var(--tm-surface))] dark:bg-gray-600"
								aria-hidden="true"
							/>
							<div class="flex min-w-0 items-baseline gap-1.5">
								<span
									class="min-w-0 truncate font-mono font-medium text-gray-700 dark:text-gray-300"
									>{ev.data?.name ??
										(ev.data?.phase === 'start' ? '子代理开始' : '子代理结束')}</span
								>
								{#if ev.key}<span class="shrink-0 font-mono text-gray-400">#{ev.key}</span>{/if}
								<time class="tm-num ml-auto shrink-0 text-gray-400">{formatClock(ev.ts)}</time>
							</div>
							{#if ev.text}
								<div
									class="mt-0.5 line-clamp-2 break-words font-mono text-gray-500 dark:text-gray-400"
								>
									{ev.text}
								</div>
							{/if}
						</li>
					{/each}
				</ol>
			{/if}
		</div>
	{/if}
</section>

<style>
	.diagnosis {
		border-color: hsl(var(--tm-violet) / 0.25);
		background: hsl(var(--tm-violet) / 0.05);
	}
	.note {
		border: 1px solid hsl(var(--tm-line-strong));
		background: hsl(var(--tm-surface-2));
		transition:
			border-color 0.15s ease,
			box-shadow 0.15s ease;
	}
	.trail::before {
		content: '';
		position: absolute;
		left: 6px;
		top: 8px;
		bottom: 6px;
		width: 1px;
		background: linear-gradient(hsl(var(--tm-line-strong)), hsl(var(--tm-line)) 85%, transparent);
	}
	.note:focus {
		border-color: hsl(var(--tm-accent) / 0.5);
		box-shadow: 0 0 0 3px hsl(var(--tm-accent) / 0.1);
	}
</style>

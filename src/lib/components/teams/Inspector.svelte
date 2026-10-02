<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getTeamTask,
		retryTeamTask,
		sendTeamMessage,
		type LiveTask,
		type TaskDetail,
		type TeamEvent
	} from '$lib/apis/teams';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { avatarKind, EXECUTOR_LABEL, formatClock, openParents, type TaskState } from './model';

	/** Details of the selected task or member. Read-only in a replay. */
	export let teamId: string;
	export let taskId: string | null = null;
	export let memberName: string | null = null;
	export let tasks: LiveTask[] = [];
	export let states: Map<string, TaskState> = new Map();
	export let members: { name: string; role: string; executor: string; focus?: string; status?: string }[] = [];
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
	let loadedFor = '';

	$: task = tasks.find((t) => t.id === taskId) ?? null;
	$: state = task ? (states.get(task.id) ?? { status: task.status, sub_status: task.sub_status }) : null;
	$: member = members.find((m) => m.name === (task ? task.member : memberName)) ?? null;
	$: keyOf = new Map(tasks.map((t) => [t.id, t.key]));
	$: waitingFor = task && state?.sub_status === 'waiting_deps' ? openParents(task, states).map((p) => keyOf.get(p) ?? p) : [];
	$: canWrite = !replay && !teamStopped && task && !['done', 'archived'].includes(state?.status ?? '');
	$: canRetry = !replay && !teamStopped && task && ['failed', 'blocked'].includes(state?.sub_status ?? '');
	$: memberTasks = memberName ? tasks.filter((t) => t.member === memberName) : [];
	// A note to a member goes to the task it is on now, else its next unfinished one.
	$: memberTarget =
		memberTasks.find((t) => ['running', 'review'].includes(states.get(t.id)?.status ?? t.status)) ??
		memberTasks.find((t) => !['done', 'archived'].includes(states.get(t.id)?.status ?? t.status)) ??
		null;
	$: canWriteMember = !replay && !teamStopped && !!memberTarget;
	$: memberTools = memberName
		? events.filter((e) => e.member === memberName && (e.type === 'tool' || e.type === 'subagent')).slice(-40).reverse()
		: [];
	$: taskEvents = task ? events.filter((e) => e.task_id === task.id && e.type !== 'tool').slice(-30).reverse() : [];

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

	const loadLog = async () => {
		if (!taskId) return;
		logLoading = true;
		try {
			logText = (await getTeamTask(localStorage.token, teamId, taskId, true)).log ?? null;
		} catch (error) {
			toast.error(`读取日志失败：${error?.message ?? error}`);
		} finally {
			logLoading = false;
		}
	};

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

<section class="flex flex-col gap-3 text-sm min-w-0" aria-label={task ? `任务 ${task.key} 详情` : `成员 ${memberName} 详情`} data-team-inspector>
	<div class="flex items-start gap-2">
		<div class="min-w-0 flex-1">
			{#if task}
				<div class="flex items-center gap-2 flex-wrap">
					<span class="font-mono text-xs font-semibold text-gray-500">#{task.key}</span>
					<StatusChip status={state?.sub_status} size="sm" />
					{#if task.attempts > 0}<span class="text-xs text-gray-400">{task.attempts} 次执行</span>{/if}
				</div>
				<h3 class="mt-1 font-semibold text-gray-900 dark:text-gray-100 break-words">{task.title}</h3>
			{:else if member}
				<div class="flex items-center gap-2.5">
					<TeamAvatar kind={avatarKind(member)} status={member.status} size={40} />
					<div class="min-w-0">
						<h3 class="font-semibold text-gray-900 dark:text-gray-100">{member.name}</h3>
						<div class="text-xs text-gray-500">{member.role} · {EXECUTOR_LABEL[member.executor] ?? member.executor}</div>
					</div>
				</div>
			{/if}
		</div>
		<button
			type="button"
			class="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-850 dark:hover:text-gray-200"
			aria-label="关闭详情"
			on:click={() => dispatch('close')}>✕</button
		>
	</div>

	{#if replay}
		<div class="rounded-xl bg-sky-50 px-3 py-2 text-xs text-sky-800 dark:bg-sky-950/40 dark:text-sky-200">
			回放中：这里只显示到当前时点的记录，发送说明、重试等操作已停用。回到实时后可以操作。
		</div>
	{/if}

	{#if task}
		{#if member}
			<div class="flex items-center gap-2 text-xs text-gray-500">
				<TeamAvatar kind={avatarKind(member)} size={22} />
				<span>{member.name}（{member.role}）· {EXECUTOR_LABEL[task.executor] ?? task.executor}</span>
			</div>
		{/if}
		{#if waitingFor.length}
			<div class="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
				等待前置任务：{waitingFor.map((k) => `#${k}`).join('、')} 完成后才会开始（由派发器检查依赖，不会提前执行）。
			</div>
		{/if}
		{#if task.block_reason && !replay}
			<div class="rounded-xl bg-red-50 px-3 py-2 text-xs text-red-800 dark:bg-red-950/40 dark:text-red-200 whitespace-pre-wrap break-words">
				{task.block_reason}
			</div>
		{/if}
		{#if !replay && task.current_run?.question}
			<div class="rounded-xl bg-violet-50 px-3 py-2 text-xs text-violet-900 dark:bg-violet-950/40 dark:text-violet-100 whitespace-pre-wrap break-words">
				<div class="font-semibold mb-1">reclaude 在等你回答：</div>{task.current_run.question}
			</div>
		{/if}
		{#if !replay && task.current_run?.runner_phase === 'quota_wait'}
			<div class="rounded-xl bg-orange-50 px-3 py-2 text-xs text-orange-900 dark:bg-orange-950/40 dark:text-orange-100">
				额度等待中（不是失败）：{task.current_run.resume_at ? `约 ${task.current_run.resume_at} 自动续跑同一会话` : '额度恢复后自动继续'}
			</div>
		{/if}

		{#if canRetry}
			<button
				type="button"
				class="self-start rounded-xl bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
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
					<summary class="cursor-pointer text-xs font-medium text-gray-600 dark:text-gray-300">任务说明</summary>
					<div class="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-gray-50 p-2 text-xs text-gray-700 dark:bg-gray-850 dark:text-gray-300">{detail.body}</div>
				</details>
				{#if detail.result}
					<div>
						<div class="text-xs font-medium text-gray-600 dark:text-gray-300">结果 / 交接</div>
						<div class="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-emerald-50/60 p-2 text-xs text-gray-800 dark:bg-emerald-950/20 dark:text-gray-200">{detail.result}</div>
					</div>
				{/if}
				{#if detail.attempts.length}
					<div>
						<div class="text-xs font-medium text-gray-600 dark:text-gray-300">执行尝试</div>
						<ol class="mt-1 space-y-1">
							{#each detail.attempts as attempt (attempt.id)}
								<li class="rounded-xl border border-gray-100 px-2 py-1.5 text-xs dark:border-gray-850">
									<div class="flex items-center gap-2 flex-wrap">
										<span class="font-medium">第 {attempt.n} 次</span>
										<span class="text-gray-500">{attempt.outcome ?? attempt.status}</span>
										<span class="text-gray-400 font-mono">{formatClock(attempt.started_at)}{attempt.ended_at ? ` – ${formatClock(attempt.ended_at)}` : ''}</span>
									</div>
									{#if attempt.runner_run_id}
										<div class="mt-0.5 text-gray-500 font-mono break-all">reclaude run {attempt.runner_run_id}{attempt.parent_runner_run_id ? `（接续 ${attempt.parent_runner_run_id}）` : ''}</div>
									{/if}
									{#if attempt.error}<div class="mt-0.5 text-red-600 break-words">{attempt.error}</div>{/if}
								</li>
							{/each}
						</ol>
					</div>
				{/if}
				<div>
					{#if logText}
						<div class="flex items-center justify-between text-xs">
							<span class="font-medium text-gray-600 dark:text-gray-300">日志（{logText.source}，最后一段）</span>
							<button type="button" class="text-sky-600 hover:underline" on:click={loadLog}>刷新</button>
						</div>
						{#if logText.note}<div class="text-xs text-gray-400">{logText.note}</div>{/if}
						<pre class="mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-gray-900 p-2 text-[11px] leading-snug text-gray-100">{logText.text || '（空）'}</pre>
					{:else}
						<button
							type="button"
							class="rounded-lg bg-gray-100 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-200"
							disabled={logLoading}
							on:click={loadLog}>{logLoading ? '读取中…' : '查看日志'}</button
						>
					{/if}
				</div>
			{/if}
		{/if}

		{#if taskEvents.length}
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-300">这个任务的记录</div>
				<ol class="mt-1 space-y-0.5 text-xs">
					{#each taskEvents as ev (ev.id)}
						<li class="flex gap-1.5 text-gray-600 dark:text-gray-400">
							<time class="font-mono text-gray-400 shrink-0">{formatClock(ev.ts)}</time>
							<span class="break-words min-w-0">{ev.type === 'message' ? `${ev.who === 'user' ? ev.author ?? '你' : ev.member}：` : ''}{ev.text ?? ''}</span>
						</li>
					{/each}
				</ol>
			</div>
		{/if}

		{#if canWrite}
			<form class="flex flex-col gap-1.5" on:submit|preventDefault={send}>
				<label class="text-xs font-medium text-gray-600 dark:text-gray-300" for="team-note-{task.id}">给 {task.member} 补充说明</label>
				<textarea
					id="team-note-{task.id}"
					bind:value={note}
					rows="3"
					maxlength="4000"
					class="w-full resize-y rounded-xl border border-gray-200 bg-white px-2.5 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-800 dark:bg-gray-900"
					placeholder={task.executor === 'reclaude'
						? 'reclaude 运行中收不到消息，会在它这一轮结束后续跑送达'
						: '成员正在执行时，会在当前这批工具调用结束后读到'}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
					}}
				/>
				<div class="flex items-center gap-2">
					<button
						type="submit"
						class="rounded-xl bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-50"
						disabled={sending || !note.trim()}>{sending ? '发送中…' : '发送'}</button
					>
					<span class="text-[11px] text-gray-400">Ctrl+Enter 发送 · 只发给这个任务的成员</span>
				</div>
				{#if lastExpect}<div class="text-xs text-violet-700 dark:text-violet-300">已排队：{lastExpect}</div>{/if}
			</form>
		{/if}
	{:else if member}
		{#if member.focus}<p class="text-xs text-gray-600 dark:text-gray-300">{member.focus}</p>{/if}
		{#if canWriteMember && memberTarget}
			<form class="flex flex-col gap-1.5" on:submit|preventDefault={send} data-member-note>
				<label class="text-xs font-medium text-gray-600 dark:text-gray-300" for="team-member-note-{member.name}"
					>给 {member.name} 补充说明（发到它{['running', 'review'].includes(states.get(memberTarget.id)?.status ?? memberTarget.status)
						? '正在做'
						: '接下来要做'}的 #{memberTarget.key}）</label
				>
				<textarea
					id="team-member-note-{member.name}"
					bind:value={note}
					rows="3"
					maxlength="4000"
					class="w-full resize-y rounded-xl border border-gray-200 bg-white px-2.5 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-800 dark:bg-gray-900"
					placeholder={member.executor === 'reclaude'
						? 'reclaude 运行中收不到消息，会在它这一轮结束后续跑送达'
						: '成员正在执行时，会在当前这批工具调用结束后读到'}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
					}}
				/>
				<button
					type="submit"
					class="self-start rounded-xl bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-50"
					disabled={sending || !note.trim()}>{sending ? '发送中…' : '发送'}</button
				>
				{#if lastExpect}<div class="text-xs text-violet-700 dark:text-violet-300">已排队：{lastExpect}</div>{/if}
			</form>
		{/if}
		<div>
			<div class="text-xs font-medium text-gray-600 dark:text-gray-300">负责的任务</div>
			<ul class="mt-1 space-y-1">
				{#each memberTasks as t (t.id)}
					<li>
						<button
							type="button"
							class="flex w-full items-center gap-2 rounded-xl border border-gray-100 px-2 py-1.5 text-left text-xs hover:border-gray-200 dark:border-gray-850 dark:hover:border-gray-700"
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
			<div class="text-xs font-medium text-gray-600 dark:text-gray-300">最近的工具记录</div>
			{#if memberTools.length === 0}
				<div class="mt-1 text-xs text-gray-400">还没有工具记录</div>
			{:else}
				<ol class="mt-1 space-y-0.5 font-mono text-[11px] text-gray-600 dark:text-gray-400">
					{#each memberTools as ev (ev.id)}
						<li class="break-words"><span class="text-gray-400">{formatClock(ev.ts)}</span> {ev.data?.name ?? (ev.data?.phase === 'start' ? '子代理开始' : '子代理结束')} {ev.text ?? ''}</li>
					{/each}
				</ol>
			{/if}
		</div>
	{/if}
</section>

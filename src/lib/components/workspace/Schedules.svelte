<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		createHermesJob,
		deleteHermesJob,
		getHermesJobOutputs,
		hermesJobAction,
		listHermesJobs,
		updateHermesJob,
		type HermesJob,
		type HermesJobOutput
	} from '$lib/apis/hermes';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ReportMarkdown from '$lib/components/teams/ReportMarkdown.svelte';
	import {
		buildSchedule,
		cronText,
		defaultScheduleForm,
		deliverText,
		scheduleFormOf,
		scheduleText,
		type ScheduleForm
	} from '$lib/utils/schedule-text';

	/**
	 * 定时任务: the jobs hermes runs on a schedule (a Telegram-made reminder, the weekly CLI update
	 * script, a long task set to start at 08:20), which until now were only reachable by asking
	 * hermes. See them, run one now, pause, change the time, read what the last runs produced, or
	 * set up a new one. Admin only (a job runs on the hermes host with its tools).
	 */

	let jobs: HermesJob[] | null = null;
	let loadError = '';
	let busy: Record<string, string> = {};
	let outputs: Record<string, HermesJobOutput[] | 'loading' | string> = {};
	let open: Record<string, boolean> = {};
	let showEnded = false;
	let deleting: HermesJob | null = null;
	let showDelete = false;

	type Draft = {
		id: string | null;
		name: string;
		prompt: string;
		deliver: string;
		script: string | null;
		form: ScheduleForm;
	};
	let draft: Draft | null = null;
	let saving = false;

	const load = async () => {
		try {
			jobs = await listHermesJobs(localStorage.token);
			loadError = '';
		} catch (e) {
			loadError = `${e}`;
			jobs = jobs ?? [];
		}
	};

	let timer: ReturnType<typeof setInterval> | null = null;
	onMount(() => {
		void load();
		// A job set to run in a minute, or one started with 立即运行, changes state on its own.
		timer = setInterval(() => {
			if (document.visibilityState === 'visible' && !draft) void load();
		}, 30_000);
	});
	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	const isEnded = (job: HermesJob) => job.state === 'completed';
	const isRunning = (job: HermesJob) =>
		job.state === 'running' || job.latest_execution?.status === 'running';
	const isPaused = (job: HermesJob) => job.state === 'paused' || (!job.enabled && !isEnded(job));

	$: active = (jobs ?? []).filter((job) => !isEnded(job));
	$: ended = (jobs ?? []).filter(isEnded);

	// Where results can go: the places the existing jobs deliver to (the Telegram chat they were
	// made from), and keeping the result in hermes only.
	$: deliverOptions = Array.from(
		new Set([...(jobs ?? []).map((job) => job.deliver).filter((d) => d && d !== 'local'), 'local'])
	);

	const pad = (n: number) => String(n).padStart(2, '0');
	const rtf = new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' });
	const whenText = (iso: string | null | undefined) => {
		if (!iso) return '';
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return iso;
		const seconds = (d.getTime() - Date.now()) / 1000;
		const abs = Math.abs(seconds);
		const relative =
			abs < 60
				? rtf.format(Math.round(seconds), 'second')
				: abs < 3600
					? rtf.format(Math.round(seconds / 60), 'minute')
					: abs < 86400
						? rtf.format(Math.round(seconds / 3600), 'hour')
						: rtf.format(Math.round(seconds / 86400), 'day');
		return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${pad(d.getHours())}:${pad(d.getMinutes())}（${relative}）`;
	};

	const act = async (job: HermesJob, action: 'pause' | 'resume' | 'run') => {
		busy = { ...busy, [job.id]: action };
		try {
			await hermesJobAction(localStorage.token, job.id, action);
			toast.success(
				action === 'run'
					? `「${job.name}」已开始运行，结果按设置发送`
					: action === 'pause'
						? `已暂停「${job.name}」`
						: `已恢复「${job.name}」`
			);
			await load();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			const { [job.id]: _done, ...rest } = busy;
			busy = rest;
		}
	};

	const toggleOutputs = async (job: HermesJob) => {
		open = { ...open, [job.id]: !open[job.id] };
		if (!open[job.id] || Array.isArray(outputs[job.id])) return;
		outputs = { ...outputs, [job.id]: 'loading' };
		try {
			outputs = { ...outputs, [job.id]: await getHermesJobOutputs(localStorage.token, job.id, 3) };
		} catch (e) {
			outputs = { ...outputs, [job.id]: `${e}` };
		}
	};

	const outputTime = (name: string) => {
		const match = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})/.exec(name);
		return match ? `${Number(match[2])} 月 ${Number(match[3])} 日 ${match[4]}:${match[5]}` : name;
	};

	const startNew = () => {
		draft = {
			id: null,
			name: '',
			prompt: '',
			deliver: deliverOptions[0] ?? 'local',
			script: null,
			form: defaultScheduleForm()
		};
	};

	const startEdit = (job: HermesJob) => {
		draft = {
			id: job.id,
			name: job.name,
			prompt: job.prompt ?? '',
			deliver: job.deliver || 'local',
			script: job.no_agent ? job.script : null,
			form: scheduleFormOf(job.schedule)
		};
	};

	$: built = draft ? buildSchedule(draft.form) : null;
	$: preview =
		built && 'schedule' in built
			? draft?.form.frequency === 'custom'
				? (cronText(built.schedule) ?? '')
				: scheduleText(scheduleFromForm(built.schedule))
			: '';

	// What the picker makes, in the shape scheduleText reads, for the preview line.
	const scheduleFromForm = (schedule: string) => {
		if (/^every \d+[mhd]$/.test(schedule)) {
			const n = Number(schedule.slice(6, -1));
			const unit = schedule.slice(-1);
			return { kind: 'interval', minutes: n * (unit === 'd' ? 1440 : unit === 'h' ? 60 : 1) };
		}
		if (/^\d{4}-/.test(schedule)) return { kind: 'once', run_at: schedule };
		return { kind: 'cron', expr: schedule };
	};

	const save = async () => {
		if (!draft || saving) return;
		const name = draft.name.trim();
		if (!name) return toast.error('起个名字');
		if (!draft.script && !draft.prompt.trim()) return toast.error('写下到时候要 Hermes 做什么');
		if (!built || 'error' in built) return toast.error(built && 'error' in built ? built.error : '时间不对');
		saving = true;
		try {
			const fields = {
				name,
				schedule: built.schedule,
				deliver: draft.deliver,
				...(draft.script ? {} : { prompt: draft.prompt.trim() })
			};
			if (draft.id) {
				await updateHermesJob(localStorage.token, draft.id, fields);
				toast.success(`已保存「${name}」`);
			} else {
				await createHermesJob(localStorage.token, fields);
				toast.success(`已创建「${name}」`);
			}
			draft = null;
			await load();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			saving = false;
		}
	};

	const remove = async () => {
		const job = deleting;
		if (!job) return;
		try {
			await deleteHermesJob(localStorage.token, job.id);
			toast.success(`已删除「${job.name}」`);
			await load();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			deleting = null;
		}
	};

	const FREQUENCIES: { value: ScheduleForm['frequency']; label: string }[] = [
		{ value: 'daily', label: '每天' },
		{ value: 'weekdays', label: '工作日' },
		{ value: 'weekly', label: '每周' },
		{ value: 'monthly', label: '每月' },
		{ value: 'every', label: '每隔' },
		{ value: 'once', label: '只一次' },
		{ value: 'custom', label: '自己写' }
	];
	const WEEKDAY_OPTIONS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
</script>

<ConfirmDialog
	bind:show={showDelete}
	title="删除定时任务？"
	message={deleting ? `「${deleting.name}」不会再运行，已保存的产出也不再显示。` : ''}
	on:confirm={remove}
	on:cancel={() => (deleting = null)}
/>

<div class="space-y-4" data-halo-schedules>
	<div class="workspace-toolbar-row">
		<div class="workspace-count-pill">
			{active.length} 个进行中{ended.length ? ` · ${ended.length} 个已结束` : ''}
		</div>
		<div class="workspace-toolbar">
			<p class="hidden flex-1 text-xs text-gray-500 sm:block dark:text-gray-400">
				Hermes 按时间自动做的事：在 Telegram 里让它「每天 9 点…」建的提醒、每周的更新脚本，都在这里。
			</p>
			<div class="workspace-toolbar-actions">
				<button
					type="button"
					class="workspace-primary-button"
					on:click={startNew}
					disabled={!!draft}
					data-schedule-new
				>
					<span aria-hidden="true">＋</span>
					<span>新建</span>
				</button>
			</div>
		</div>
	</div>

	{#if draft}
		<form
			class="glass-item space-y-3 rounded-2xl px-4 py-4"
			on:submit|preventDefault={save}
			data-schedule-form
		>
			<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">
				{draft.id ? '修改定时任务' : '新建定时任务'}
			</div>
			<label class="block space-y-1">
				<span class="text-xs text-gray-500 dark:text-gray-400">名称</span>
				<input
					class="halo-input w-full"
					bind:value={draft.name}
					maxlength="200"
					placeholder="例如：每天早上的新闻汇总"
					data-schedule-name
				/>
			</label>
			{#if draft.script}
				<div class="text-xs text-gray-500 dark:text-gray-400">
					运行脚本 <code class="font-mono">{draft.script}</code>（不经过模型，这里只改名称、时间和发送位置）
				</div>
			{:else}
				<label class="block space-y-1">
					<span class="text-xs text-gray-500 dark:text-gray-400">到时候让 Hermes 做什么</span>
					<textarea
						class="halo-input min-h-24 w-full"
						bind:value={draft.prompt}
						maxlength="5000"
						placeholder="例如：搜一下今天 AI 领域的重要新闻，挑 5 条，每条一句话总结并附链接"
						data-schedule-prompt
					/>
				</label>
			{/if}
			<div class="space-y-1">
				<span class="text-xs text-gray-500 dark:text-gray-400">时间</span>
				<div class="flex flex-wrap items-center gap-2">
					<select class="halo-input w-auto" bind:value={draft.form.frequency} data-schedule-frequency>
						{#each FREQUENCIES as f}
							<option value={f.value}>{f.label}</option>
						{/each}
					</select>
					{#if draft.form.frequency === 'weekly'}
						<select class="halo-input w-auto" bind:value={draft.form.weekday} data-schedule-weekday>
							{#each WEEKDAY_OPTIONS as label, i}
								<option value={i}>{label}</option>
							{/each}
						</select>
					{:else if draft.form.frequency === 'monthly'}
						<input
							class="halo-input w-20"
							type="number"
							min="1"
							max="28"
							bind:value={draft.form.day}
							aria-label="几号"
						/>
						<span class="text-sm text-gray-500">日</span>
					{/if}
					{#if ['daily', 'weekdays', 'weekly', 'monthly'].includes(draft.form.frequency)}
						<input
							class="halo-input w-auto"
							type="time"
							bind:value={draft.form.time}
							aria-label="几点"
							data-schedule-time
						/>
					{:else if draft.form.frequency === 'every'}
						<input
							class="halo-input w-20"
							type="number"
							min="1"
							bind:value={draft.form.every}
							aria-label="间隔"
							data-schedule-every
						/>
						<select class="halo-input w-auto" bind:value={draft.form.unit} aria-label="单位">
							<option value="m">分钟</option>
							<option value="h">小时</option>
							<option value="d">天</option>
						</select>
					{:else if draft.form.frequency === 'once'}
						<input
							class="halo-input w-auto"
							type="datetime-local"
							bind:value={draft.form.at}
							aria-label="运行时间"
							data-schedule-at
						/>
					{:else if draft.form.frequency === 'custom'}
						<input
							class="halo-input min-w-0 flex-1 font-mono"
							bind:value={draft.form.custom}
							placeholder="0 9 * * 1-5 · every 2h · every monday 9am"
							aria-label="时间表达式"
							data-schedule-custom
						/>
					{/if}
				</div>
				<div class="text-xs {built && 'error' in built ? 'text-red-600 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}" data-schedule-preview>
					{#if built && 'error' in built}
						{built.error}
					{:else if preview}
						将会：{preview}
					{:else if draft.form.frequency === 'custom'}
						cron 表达式（分 时 日 月 周）、every 30m / every 2h、every monday 9am 都可以
					{/if}
				</div>
			</div>
			<label class="block space-y-1">
				<span class="text-xs text-gray-500 dark:text-gray-400">结果</span>
				<select class="halo-input w-auto" bind:value={draft.deliver} data-schedule-deliver>
					{#each deliverOptions.includes(draft.deliver) ? deliverOptions : [draft.deliver, ...deliverOptions] as option}
						<option value={option}>{deliverText(option)}</option>
					{/each}
				</select>
			</label>
			<div class="flex justify-end gap-2 pt-1">
				<button type="button" class="halo-btn-secondary" on:click={() => (draft = null)}>取消</button>
				<button type="submit" class="halo-btn-primary" disabled={saving} data-schedule-save>
					{saving ? '保存中…' : draft.id ? '保存' : '创建'}
				</button>
			</div>
		</form>
	{/if}

	{#if jobs === null}
		<div class="flex justify-center py-10"><Spinner className="size-5" /></div>
	{:else}
		{#if loadError}
			<div
				class="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-300"
				data-schedule-error
			>
				没能读取定时任务：{loadError}
			</div>
		{/if}
		{#if !active.length && !loadError}
			<div class="workspace-empty-state" data-schedule-empty>
				<p class="text-sm text-gray-500 dark:text-gray-400">
					还没有定时任务。点「新建」，或在对话里对 Hermes 说「每天早上 8 点给我…」。
				</p>
			</div>
		{/if}
		<div class="grid gap-3 lg:grid-cols-2">
			{#each [...active, ...(showEnded ? ended : [])] as job (job.id)}
				{@const failed = job.last_status === 'error' || !!job.last_delivery_error}
				<article
					class="glass-item flex flex-col gap-2 rounded-2xl px-4 py-3 {isEnded(job) ? 'opacity-70' : ''}"
					data-schedule-job={job.id}
					data-schedule-state={isRunning(job) ? 'running' : isPaused(job) ? 'paused' : job.state}
				>
					<div class="flex items-start gap-2">
						<div class="min-w-0 flex-1">
							<div class="line-clamp-2 font-semibold text-gray-900 dark:text-gray-100">{job.name}</div>
							<div class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
								{scheduleText(job.schedule, job.schedule_display ?? '')}
								{#if job.no_agent && job.script}
									· 脚本 <code class="font-mono">{job.script}</code>
								{/if}
							</div>
						</div>
						<span
							class="shrink-0 rounded-full px-2 py-0.5 text-2xs font-medium {isRunning(job)
								? 'bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
								: isPaused(job)
									? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
									: isEnded(job)
										? 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
										: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'}"
						>
							{isRunning(job) ? '运行中' : isPaused(job) ? '已暂停' : isEnded(job) ? '已结束' : '等待中'}
						</span>
					</div>

					{#if !job.no_agent && job.prompt}
						<p class="line-clamp-2 text-sm text-gray-600 dark:text-gray-300" title={job.prompt}>
							{job.prompt}
						</p>
					{/if}

					<dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
						{#if job.next_run_at && !isEnded(job) && !isPaused(job)}
							<dt class="text-gray-400">下次</dt>
							<dd class="tabular-nums text-gray-700 dark:text-gray-200" data-schedule-next>{whenText(job.next_run_at)}</dd>
						{/if}
						<dt class="text-gray-400">上次</dt>
						<dd class="min-w-0 tabular-nums text-gray-700 dark:text-gray-200">
							{#if job.last_run_at}
								{whenText(job.last_run_at)}
								<span class={failed ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'}>
									{failed ? '· 失败' : '· 成功'}
								</span>
								{#if job.repeat?.completed}
									<span class="text-gray-400"> · 共 {job.repeat.completed} 次</span>
								{/if}
							{:else}
								<span class="text-gray-400">还没运行过</span>
							{/if}
						</dd>
						{#if failed && (job.last_error || job.last_delivery_error)}
							<dt class="text-gray-400">原因</dt>
							<dd class="line-clamp-2 text-red-600 dark:text-red-400" title={job.last_error ?? job.last_delivery_error ?? ''}>
								{job.last_error ?? `发送失败：${job.last_delivery_error}`}
							</dd>
						{/if}
						{#if isPaused(job) && job.paused_reason}
							<dt class="text-gray-400">暂停</dt>
							<dd class="text-gray-600 dark:text-gray-300">{job.paused_reason}</dd>
						{/if}
						<dt class="text-gray-400">结果</dt>
						<dd class="text-gray-700 dark:text-gray-200">{deliverText(job.deliver)}</dd>
					</dl>

					<div class="flex flex-wrap gap-1.5 pt-1 text-xs">
						{#if !isEnded(job)}
							<button
								type="button"
								class="halo-chip"
								disabled={!!busy[job.id] || isRunning(job)}
								on:click={() => act(job, 'run')}
								data-schedule-run
							>
								{busy[job.id] === 'run' ? '启动中…' : '立即运行'}
							</button>
							<button
								type="button"
								class="halo-chip"
								disabled={!!busy[job.id]}
								on:click={() => act(job, isPaused(job) ? 'resume' : 'pause')}
								data-schedule-toggle
							>
								{isPaused(job) ? '恢复' : '暂停'}
							</button>
							<button type="button" class="halo-chip" on:click={() => startEdit(job)} data-schedule-edit>
								修改
							</button>
						{/if}
						<button
							type="button"
							class="halo-chip"
							aria-expanded={!!open[job.id]}
							on:click={() => toggleOutputs(job)}
							data-schedule-outputs
						>
							{open[job.id] ? '收起产出' : '最近产出'}
						</button>
						<button
							type="button"
							class="halo-chip !text-red-600 dark:!text-red-400"
							on:click={() => {
								deleting = job;
								showDelete = true;
							}}
							data-schedule-delete
						>
							删除
						</button>
					</div>

					{#if open[job.id]}
						{@const out = outputs[job.id]}
						<div class="mt-1 border-t border-gray-100 pt-2 dark:border-gray-800" data-schedule-output-list>
							{#if out === 'loading'}
								<Spinner className="size-4" />
							{:else if typeof out === 'string'}
								<div class="text-xs text-red-600 dark:text-red-400">没能读取：{out}</div>
							{:else if out && out.length}
								{#each out as item, i (item.name)}
									<details class="group" open={i === 0}>
										<summary class="cursor-pointer select-none py-1 text-xs text-gray-500 dark:text-gray-400">
											{outputTime(item.name)}{item.truncated ? '（太长，只显示前一部分）' : ''}
										</summary>
										<div class="max-h-96 overflow-y-auto pb-2">
											<ReportMarkdown id="schedule-{job.id}-{i}" content={item.content} />
										</div>
									</details>
								{/each}
							{:else}
								<div class="text-xs text-gray-400">还没有保存的产出</div>
							{/if}
						</div>
					{/if}
				</article>
			{/each}
		</div>
		{#if ended.length}
			<button
				type="button"
				class="text-xs text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
				on:click={() => (showEnded = !showEnded)}
				data-schedule-show-ended
			>
				{showEnded ? '隐藏已结束的' : `显示已结束的 ${ended.length} 个`}
			</button>
		{/if}
	{/if}
</div>

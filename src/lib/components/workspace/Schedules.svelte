<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { FileText, Pause, Pencil, Play, Plus, Trash2, X } from 'lucide-svelte';

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
	import HaloSelect from '$lib/components/common/HaloSelect.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ReportMarkdown from '$lib/components/teams/ReportMarkdown.svelte';
	import {
		buildSchedule,
		countdownParts,
		cronText,
		cycleProgress,
		defaultScheduleForm,
		deliverText,
		dialText,
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
	let clock: ReturnType<typeof setInterval> | null = null;
	/** ticks every second for the countdown and the dials */
	let now = Date.now();
	onMount(() => {
		void load();
		// A job set to run in a minute, or one started with 立即运行, changes state on its own.
		timer = setInterval(() => {
			if (document.visibilityState === 'visible' && !draft) void load();
		}, 30_000);
		clock = setInterval(() => {
			if (document.visibilityState === 'visible') now = Date.now();
		}, 1000);
	});
	onDestroy(() => {
		if (timer) clearInterval(timer);
		if (clock) clearInterval(clock);
	});

	const isEnded = (job: HermesJob) => job.state === 'completed';
	const isRunning = (job: HermesJob) =>
		job.state === 'running' || job.latest_execution?.status === 'running';
	const isPaused = (job: HermesJob) => job.state === 'paused' || (!job.enabled && !isEnded(job));

	$: active = (jobs ?? []).filter((job) => !isEnded(job));
	$: ended = (jobs ?? []).filter(isEnded);
	const isFailed = (job: HermesJob) => job.last_status === 'error' || !!job.last_delivery_error;
	// The one job the page leads with: whichever runs next.
	$: upcoming = active
		.filter((job) => job.next_run_at && !isPaused(job))
		.sort((a, b) => Date.parse(a.next_run_at!) - Date.parse(b.next_run_at!))[0];
	$: countdown = upcoming ? countdownParts(upcoming.next_run_at, now) : [];
	$: stats = [
		{ label: '进行中', value: active.filter((job) => !isPaused(job)).length },
		{ label: '已暂停', value: active.filter(isPaused).length },
		{ label: '上次失败', value: active.filter(isFailed).length, alert: true }
	];

	// The dial's ring: a circle of radius 26 in a 64 box, filled as far as the job is from its
	// last run to its next.
	const RING = 2 * Math.PI * 26;
	const ringOffset = (progress: number | null) => RING * (1 - (progress ?? 0));

	// Where results can go: the places the existing jobs deliver to (the Telegram chat they were
	// made from), and keeping the result in hermes only.
	$: deliverOptions = Array.from(
		new Set([...(jobs ?? []).map((job) => job.deliver).filter((d) => d && d !== 'local'), 'local'])
	);

	const pad = (n: number) => String(n).padStart(2, '0');
	const rtf = new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' });
	const whenText = (iso: string | null | undefined, at = Date.now()) => {
		if (!iso) return '';
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return iso;
		const seconds = (d.getTime() - at) / 1000;
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
	const WEEKDAY_OPTIONS = ['日', '一', '二', '三', '四', '五', '六'];
	const UNIT_OPTIONS: { value: ScheduleForm['unit']; label: string }[] = [
		{ value: 'm', label: '分钟' },
		{ value: 'h', label: '小时' },
		{ value: 'd', label: '天' }
	];
</script>

<ConfirmDialog
	bind:show={showDelete}
	title="删除定时任务？"
	message={deleting ? `「${deleting.name}」不会再运行，已保存的产出也不再显示。` : ''}
	on:confirm={remove}
	on:cancel={() => (deleting = null)}
/>

<div class="sch space-y-4" data-halo-schedules>
	<!-- What runs next leads the page: the only halo ring here. -->
	<section class="sch-hero" data-schedule-next-up>
		<div class="sch-hero-orbit" aria-hidden="true">
			<svg viewBox="0 0 64 64" class="sch-ring">
				{#each Array(12) as _, i}
					<line
						class="sch-tick"
						x1="32"
						y1="2.5"
						x2="32"
						y2={i % 3 === 0 ? 6.5 : 5}
						transform="rotate({i * 30} 32 32)"
					/>
				{/each}
				<circle class="sch-ring-track" cx="32" cy="32" r="26" />
				{#if upcoming}
					<circle
						class="sch-ring-fill"
						cx="32"
						cy="32"
						r="26"
						stroke-dasharray={RING}
						stroke-dashoffset={ringOffset(cycleProgress(upcoming, now))}
					/>
				{/if}
			</svg>
			<span class="sch-hero-core"></span>
		</div>
		<div class="min-w-0 flex-1">
			<div class="sch-eyebrow">下一次运行</div>
			{#if upcoming}
				<div class="sch-countdown" data-schedule-countdown>
					{#if countdown.length}
						{#each countdown as [value, unit]}
							<span class="sch-countdown-value">{value}</span><span class="sch-countdown-unit"
								>{unit}</span
							>
						{/each}
					{:else}
						<span class="sch-countdown-value">即将运行</span>
					{/if}
				</div>
				<div class="mt-1 truncate text-sm text-gray-700 dark:text-gray-200" title={upcoming.name}>
					{upcoming.name}
				</div>
				<div class="text-xs tabular-nums text-gray-500 dark:text-gray-400">
					{whenText(upcoming.next_run_at, now)}
				</div>
			{:else}
				<div class="sch-countdown"><span class="sch-countdown-value">—</span></div>
				<div class="mt-1 text-sm text-gray-500 dark:text-gray-400">没有在排队的任务</div>
			{/if}
		</div>
		<div class="sch-hero-side">
			<dl class="sch-stats">
				{#each stats as item}
					<div>
						<dt>{item.label}</dt>
						<dd class={item.alert && item.value ? 'text-red-600 dark:text-red-400' : ''}>
							{jobs === null ? '·' : item.value}
						</dd>
					</div>
				{/each}
			</dl>
			<button
				type="button"
				class="workspace-primary-button"
				on:click={startNew}
				disabled={!!draft}
				data-schedule-new
			>
				<Plus class="size-4" strokeWidth={2.25} />
				<span>新建</span>
			</button>
		</div>
	</section>

	{#if draft}
		<form class="sch-panel sch-form" on:submit|preventDefault={save} data-schedule-form>
			<div class="flex items-center justify-between gap-3">
				<div class="text-[15px] font-semibold text-gray-900 dark:text-gray-100">
					{draft.id ? '修改定时任务' : '新建定时任务'}
				</div>
				<button
					type="button"
					class="halo-icon-btn"
					aria-label="取消"
					title="取消"
					on:click={() => (draft = null)}
				>
					<X class="size-4" strokeWidth={2} />
				</button>
			</div>
			<div class="grid gap-5 md:grid-cols-2">
				<div class="space-y-3">
					<label class="block space-y-1.5">
						<span class="sch-label">名称</span>
						<input
							class="halo-input w-full"
							bind:value={draft.name}
							maxlength="200"
							placeholder="例如：每天早上的新闻汇总"
							data-schedule-name
						/>
					</label>
					{#if draft.script}
						<div class="sch-note">
							运行脚本 <code class="font-mono">{draft.script}</code>，不经过模型；这里只改名称、时间和发送位置。
						</div>
					{:else}
						<label class="block space-y-1.5">
							<span class="sch-label">到时候让 Hermes 做什么</span>
							<textarea
								class="halo-input min-h-28 w-full"
								bind:value={draft.prompt}
								maxlength="5000"
								placeholder="例如：搜一下今天 AI 领域的重要新闻，挑 5 条，每条一句话总结并附链接"
								data-schedule-prompt
							/>
						</label>
					{/if}
				</div>
				<div class="space-y-3">
					<div class="space-y-1.5">
						<span class="sch-label">时间</span>
						<div class="sch-segments" role="group" aria-label="频率" data-schedule-frequency>
							{#each FREQUENCIES as f}
								<button
									type="button"
									aria-pressed={draft.form.frequency === f.value}
									data-value={f.value}
									on:click={() => draft && (draft.form.frequency = f.value)}>{f.label}</button
								>
							{/each}
						</div>
						<div class="flex flex-wrap items-center gap-2 pt-1">
							{#if draft.form.frequency === 'weekly'}
								<div class="sch-segments" role="group" aria-label="星期" data-schedule-weekday>
									{#each WEEKDAY_OPTIONS as label, i}
										<button
											type="button"
											aria-pressed={draft.form.weekday === i}
											data-value={i}
											on:click={() => draft && (draft.form.weekday = i)}>{label}</button
										>
									{/each}
								</div>
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
									class="halo-input w-auto tabular-nums"
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
								<div class="sch-segments" role="group" aria-label="单位">
									{#each UNIT_OPTIONS as u}
										<button
											type="button"
											aria-pressed={draft.form.unit === u.value}
											on:click={() => draft && (draft.form.unit = u.value)}>{u.label}</button
										>
									{/each}
								</div>
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
						<div
							class="sch-preview {built && 'error' in built ? 'is-error' : ''}"
							data-schedule-preview
						>
							{#if built && 'error' in built}
								{built.error}
							{:else if preview}
								将会：{preview}
							{:else if draft.form.frequency === 'custom'}
								cron 表达式（分 时 日 月 周）、every 30m / every 2h、every monday 9am 都可以
							{/if}
						</div>
					</div>
					<div class="space-y-1.5" data-schedule-deliver>
						<span class="sch-label">结果</span>
						<HaloSelect
							value={draft.deliver}
							options={(deliverOptions.includes(draft.deliver)
								? deliverOptions
								: [draft.deliver, ...deliverOptions]
							).map((option) => ({ value: option, label: deliverText(option) }))}
							className="h-9"
							contentAlign="start"
							on:change={(e) => draft && (draft.deliver = e.detail.value)}
						/>
					</div>
				</div>
			</div>
			<div class="flex justify-end gap-2 border-t border-[var(--surface-border)] pt-3">
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
			<div class="sch-panel py-10 text-center" data-schedule-empty>
				<p class="text-sm text-gray-500 dark:text-gray-400">
					还没有定时任务。点「新建」，或在 Telegram / 对话里对 Hermes 说「每天早上 8 点给我…」。
				</p>
			</div>
		{/if}
		<div class="grid gap-3 lg:grid-cols-2">
			{#each [...active, ...(showEnded ? ended : [])] as job (job.id)}
				{@const failed = isFailed(job)}
				{@const state = isRunning(job) ? 'running' : isPaused(job) ? 'paused' : job.state}
				{@const dial = dialText(scheduleText(job.schedule, job.schedule_display ?? ''))}
				{@const progress = isEnded(job) || isPaused(job) ? null : cycleProgress(job, now)}
				<article
					class="sch-panel sch-card"
					class:is-ended={isEnded(job)}
					class:is-failed={failed}
					data-schedule-job={job.id}
					data-schedule-state={state}
				>
					<div class="flex items-start gap-4">
						<div class="sch-dial" aria-hidden="true">
							<svg viewBox="0 0 64 64" class="sch-ring">
								<circle class="sch-ring-track" cx="32" cy="32" r="26" />
								{#if state === 'running'}
									<circle
										class="sch-ring-fill sch-ring-spin"
										cx="32"
										cy="32"
										r="26"
										stroke-dasharray="{RING * 0.28} {RING}"
									/>
								{:else if progress !== null}
									<circle
										class="sch-ring-fill"
										cx="32"
										cy="32"
										r="26"
										stroke-dasharray={RING}
										stroke-dashoffset={ringOffset(progress)}
									/>
								{/if}
							</svg>
							<div class="sch-dial-text">
								<span class="sch-dial-main">{dial.main}</span>
								<span class="sch-dial-sub">{dial.sub}</span>
							</div>
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex items-start gap-2">
								<div class="line-clamp-2 min-w-0 flex-1 font-semibold text-gray-900 dark:text-gray-100">
									{job.name}
								</div>
								<span class="sch-state" data-tone={state}>
									<span class="sch-state-dot"></span>
									{isRunning(job) ? '运行中' : isPaused(job) ? '已暂停' : isEnded(job) ? '已结束' : '等待中'}
								</span>
							</div>
							<div class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
								{scheduleText(job.schedule, job.schedule_display ?? '')}
								{#if job.no_agent && job.script}
									· 脚本 <code class="font-mono">{job.script}</code>
								{/if}
							</div>
							{#if !job.no_agent && job.prompt}
								<p class="mt-1.5 line-clamp-2 text-sm text-gray-600 dark:text-gray-300" title={job.prompt}>
									{job.prompt}
								</p>
							{/if}
						</div>
					</div>

					<dl class="sch-meta">
						{#if job.next_run_at && !isEnded(job) && !isPaused(job)}
							<div>
								<dt>下次</dt>
								<dd class="tabular-nums" data-schedule-next>{whenText(job.next_run_at, now)}</dd>
							</div>
						{/if}
						<div>
							<dt>上次</dt>
							<dd class="tabular-nums">
								{#if job.last_run_at}
									{whenText(job.last_run_at, now)}
									<span class={failed ? 'text-red-600 dark:text-red-400' : 'text-gray-400'}>
										{failed ? '· 失败' : '· 成功'}
									</span>
									{#if job.repeat?.completed}
										<span class="text-gray-400"> · 共 {job.repeat.completed} 次</span>
									{/if}
								{:else}
									<span class="text-gray-400">还没运行过</span>
								{/if}
							</dd>
						</div>
						{#if failed && (job.last_error || job.last_delivery_error)}
							<div>
								<dt>原因</dt>
								<dd
									class="line-clamp-2 text-red-600 dark:text-red-400"
									title={job.last_error ?? job.last_delivery_error ?? ''}
								>
									{job.last_error ?? `发送失败：${job.last_delivery_error}`}
								</dd>
							</div>
						{/if}
						{#if isPaused(job) && job.paused_reason}
							<div>
								<dt>暂停</dt>
								<dd>{job.paused_reason}</dd>
							</div>
						{/if}
						<div>
							<dt>结果</dt>
							<dd>{deliverText(job.deliver)}</dd>
						</div>
					</dl>

					<div class="sch-actions">
						{#if !isEnded(job)}
							<button
								type="button"
								class="sch-action is-primary"
								disabled={!!busy[job.id] || isRunning(job)}
								on:click={() => act(job, 'run')}
								data-schedule-run
							>
								<Play class="size-3.5" strokeWidth={2.25} />
								<span>{busy[job.id] === 'run' ? '启动中…' : '立即运行'}</span>
							</button>
							<button
								type="button"
								class="sch-action"
								disabled={!!busy[job.id]}
								on:click={() => act(job, isPaused(job) ? 'resume' : 'pause')}
								data-schedule-toggle
							>
								<svelte:component this={isPaused(job) ? Play : Pause} class="size-3.5" strokeWidth={2.25} />
								<span>{isPaused(job) ? '恢复' : '暂停'}</span>
							</button>
							<button type="button" class="sch-action" on:click={() => startEdit(job)} data-schedule-edit>
								<Pencil class="size-3.5" strokeWidth={2.25} />
								<span>修改</span>
							</button>
						{/if}
						<button
							type="button"
							class="sch-action"
							aria-expanded={!!open[job.id]}
							on:click={() => toggleOutputs(job)}
							data-schedule-outputs
						>
							<FileText class="size-3.5" strokeWidth={2.25} />
							<span>{open[job.id] ? '收起产出' : '最近产出'}</span>
						</button>
						<button
							type="button"
							class="sch-action is-danger ml-auto"
							aria-label="删除"
							title="删除"
							on:click={() => {
								deleting = job;
								showDelete = true;
							}}
							data-schedule-delete
						>
							<Trash2 class="size-3.5" strokeWidth={2.25} />
						</button>
					</div>

					{#if open[job.id]}
						{@const out = outputs[job.id]}
						<div class="border-t border-[var(--surface-border)] pt-2" data-schedule-output-list>
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

<style>
	/* Halo look: ink surfaces, one accent (ion blue; the sci-fi layer's cyan when it is on) for
	   what is moving, red only for a failure. The hero's ring is the page's one halo. */
	.sch {
		--sch-accent: var(--halo-ion);
		--sch-ink: var(--color-gray-900);
		--sch-muted: var(--color-gray-500);
		--sch-track: oklch(0.3 0.02 268 / 0.1);
	}
	:global(.dark) .sch {
		--sch-ink: var(--color-gray-100);
		--sch-muted: var(--color-gray-400);
		--sch-track: oklch(1 0 0 / 0.08);
	}
	:global(html.halo-scifi) .sch {
		--sch-accent: var(--scifi-cyan);
	}

	.sch-panel {
		position: relative;
		border-radius: 1rem;
		border: 1px solid var(--surface-border);
		background: color-mix(in oklab, var(--surface-overlay) 78%, transparent);
		box-shadow: 0 1px 2px oklch(0.2 0.02 268 / 0.04);
		backdrop-filter: blur(10px);
		transition:
			border-color 0.2s,
			box-shadow 0.2s;
	}
	:global(.dark) .sch-panel {
		background: oklch(0.2 0.015 268 / 0.55);
		box-shadow: inset 0 1px 0 oklch(1 0 0 / 0.04);
	}

	/* ---- next up ---- */
	.sch-hero {
		position: relative;
		display: flex;
		align-items: center;
		gap: 1.25rem;
		overflow: hidden;
		padding: 1.25rem 1.5rem;
		border-radius: 1.25rem;
		border: 1px solid var(--surface-border);
		background:
			radial-gradient(120% 140% at 0% 50%, color-mix(in oklab, var(--sch-accent) 10%, transparent), transparent 55%),
			color-mix(in oklab, var(--surface-overlay) 82%, transparent);
		backdrop-filter: blur(12px);
	}
	:global(.dark) .sch-hero {
		background:
			radial-gradient(120% 160% at 0% 50%, color-mix(in oklab, var(--sch-accent) 16%, transparent), transparent 55%),
			oklch(0.19 0.016 268 / 0.6);
	}
	/* a hairline of light along the top edge */
	.sch-hero::before {
		content: '';
		position: absolute;
		inset: 0 10% auto;
		height: 1px;
		background: linear-gradient(90deg, transparent, color-mix(in oklab, var(--sch-accent) 60%, transparent), transparent);
	}
	.sch-hero-orbit {
		position: relative;
		width: 5.5rem;
		height: 5.5rem;
		flex-shrink: 0;
	}
	.sch-hero-orbit .sch-ring {
		width: 100%;
		height: 100%;
	}
	.sch-hero-orbit::after {
		/* slow halo around the dial */
		content: '';
		position: absolute;
		inset: -6px;
		border-radius: 9999px;
		background: conic-gradient(from var(--halo-angle, 0deg), transparent 0 70%, color-mix(in oklab, var(--sch-accent) 45%, transparent) 88%, transparent);
		mask: radial-gradient(circle, transparent 62%, #000 64%, #000 70%, transparent 72%);
		animation: sch-orbit 9s linear infinite;
		opacity: 0.8;
	}
	.sch-hero-core {
		position: absolute;
		inset: 36%;
		border-radius: 9999px;
		background: radial-gradient(circle, color-mix(in oklab, var(--sch-accent) 70%, white), var(--sch-accent) 45%, transparent 72%);
		box-shadow: 0 0 18px color-mix(in oklab, var(--sch-accent) 55%, transparent);
		animation: sch-breathe 3.2s ease-in-out infinite;
	}
	.sch-eyebrow {
		font-size: 0.6875rem;
		font-weight: 600;
		letter-spacing: 0.18em;
		color: var(--sch-accent);
	}
	.sch-countdown {
		display: flex;
		align-items: baseline;
		gap: 0.25rem;
		margin-top: 0.125rem;
		color: var(--sch-ink);
		font-variant-numeric: tabular-nums;
	}
	.sch-countdown-value {
		font-family: var(--font-display, inherit);
		font-size: 2.125rem;
		line-height: 1.05;
		font-weight: 600;
		letter-spacing: -0.02em;
	}
	.sch-countdown-unit {
		margin-right: 0.5rem;
		font-size: 0.875rem;
		color: var(--sch-muted);
	}
	.sch-hero-side {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 0.875rem;
	}
	.sch-stats {
		display: flex;
		gap: 1.25rem;
	}
	.sch-stats > div {
		text-align: right;
	}
	.sch-stats dt {
		font-size: 0.6875rem;
		color: var(--sch-muted);
	}
	.sch-stats dd {
		font-size: 1.125rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--sch-ink);
	}

	/* ---- the dials ---- */
	.sch-ring {
		transform: rotate(-90deg);
		overflow: visible;
	}
	.sch-tick {
		stroke: var(--sch-muted);
		stroke-width: 1;
		opacity: 0.45;
	}
	.sch-ring-track {
		fill: none;
		stroke: var(--sch-track);
		stroke-width: 2.5;
	}
	.sch-ring-fill {
		fill: none;
		stroke: var(--sch-accent);
		stroke-width: 2.5;
		stroke-linecap: round;
		transition: stroke-dashoffset 1s linear;
		filter: drop-shadow(0 0 3px color-mix(in oklab, var(--sch-accent) 50%, transparent));
	}
	.sch-ring-spin {
		transform-origin: 32px 32px;
		animation: sch-orbit 1.4s linear infinite;
	}
	.sch-dial {
		position: relative;
		width: 4.25rem;
		height: 4.25rem;
		flex-shrink: 0;
	}
	.sch-dial .sch-ring {
		width: 100%;
		height: 100%;
	}
	.sch-dial-text {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		line-height: 1.1;
	}
	.sch-dial-main {
		font-family: var(--font-display, inherit);
		font-size: 0.9375rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--sch-ink);
	}
	.sch-dial-sub {
		max-width: 3.4rem;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
		font-size: 0.625rem;
		color: var(--sch-muted);
	}

	/* ---- cards ---- */
	.sch-card {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1rem 1.125rem 0.75rem;
	}
	.sch-card:hover {
		border-color: var(--surface-border-strong);
		box-shadow: 0 6px 24px -12px oklch(0.2 0.02 268 / 0.18);
	}
	:global(.dark) .sch-card:hover {
		box-shadow: 0 8px 28px -14px color-mix(in oklab, var(--sch-accent) 35%, transparent);
	}
	.sch-card[data-schedule-state='running'] {
		border-color: color-mix(in oklab, var(--sch-accent) 45%, var(--surface-border));
	}
	.sch-card.is-failed .sch-ring-fill {
		stroke: var(--color-red-500, #ef4444);
		filter: none;
	}
	.sch-card.is-ended {
		opacity: 0.65;
	}
	.sch-state {
		display: inline-flex;
		flex-shrink: 0;
		align-items: center;
		gap: 0.375rem;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		border: 1px solid var(--surface-border);
		font-size: 0.6875rem;
		color: var(--sch-muted);
	}
	.sch-state-dot {
		width: 0.375rem;
		height: 0.375rem;
		border-radius: 9999px;
		background: currentColor;
	}
	.sch-state[data-tone='scheduled'] {
		color: var(--sch-ink);
	}
	.sch-state[data-tone='running'] {
		color: var(--sch-accent);
		border-color: color-mix(in oklab, var(--sch-accent) 40%, transparent);
	}
	.sch-state[data-tone='running'] .sch-state-dot {
		box-shadow: 0 0 0 0 currentColor;
		animation: sch-ping 1.6s ease-out infinite;
	}
	.sch-state[data-tone='paused'] .sch-state-dot {
		background: transparent;
		box-shadow: inset 0 0 0 1.5px currentColor;
	}
	.sch-meta {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
		gap: 0.375rem 1rem;
		padding: 0.625rem 0.75rem;
		border-radius: 0.75rem;
		background: oklch(0.3 0.02 268 / 0.035);
		font-size: 0.75rem;
	}
	:global(.dark) .sch-meta {
		background: oklch(1 0 0 / 0.03);
	}
	.sch-meta > div {
		display: flex;
		min-width: 0;
		gap: 0.5rem;
	}
	.sch-meta dt {
		flex-shrink: 0;
		color: var(--sch-muted);
	}
	.sch-meta dd {
		min-width: 0;
		color: var(--sch-ink);
	}
	.sch-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.25rem;
		padding-top: 0.5rem;
		border-top: 1px solid var(--surface-border);
	}
	.sch-action {
		display: inline-flex;
		align-items: center;
		gap: 0.375rem;
		height: 1.875rem;
		padding: 0 0.625rem;
		border-radius: 0.5rem;
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--color-gray-600);
		transition:
			background-color 0.15s,
			color 0.15s;
	}
	:global(.dark) .sch-action {
		color: var(--color-gray-300);
	}
	.sch-action:hover:not(:disabled) {
		background: oklch(0.3 0.02 268 / 0.06);
		color: var(--sch-ink);
	}
	:global(.dark) .sch-action:hover:not(:disabled) {
		background: oklch(1 0 0 / 0.06);
	}
	.sch-action:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.sch-action.is-primary {
		color: var(--sch-accent);
	}
	.sch-action.is-primary:hover:not(:disabled) {
		background: color-mix(in oklab, var(--sch-accent) 12%, transparent);
		color: var(--sch-accent);
	}
	.sch-action.is-danger:hover:not(:disabled) {
		background: oklch(0.63 0.22 25 / 0.1);
		color: var(--color-red-600, #dc2626);
	}

	/* ---- the form ---- */
	.sch-form {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1.125rem 1.25rem;
		border-color: color-mix(in oklab, var(--sch-accent) 30%, var(--surface-border));
	}
	.sch-label {
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--sch-muted);
	}
	.sch-note {
		padding: 0.625rem 0.75rem;
		border-radius: 0.75rem;
		background: oklch(0.3 0.02 268 / 0.04);
		font-size: 0.75rem;
		color: var(--sch-muted);
	}
	.sch-segments {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 2px;
		padding: 3px;
		border-radius: 0.75rem;
		border: 1px solid var(--surface-border);
		background: oklch(0.3 0.02 268 / 0.03);
	}
	:global(.dark) .sch-segments {
		background: oklch(1 0 0 / 0.03);
	}
	.sch-segments button {
		min-width: 2rem;
		padding: 0.3125rem 0.625rem;
		border-radius: 0.5rem;
		font-size: 0.8125rem;
		color: var(--sch-muted);
		transition:
			background-color 0.15s,
			color 0.15s;
	}
	.sch-segments button:hover {
		color: var(--sch-ink);
	}
	.sch-segments button[aria-pressed='true'] {
		background: var(--surface-overlay);
		color: var(--sch-ink);
		font-weight: 600;
		box-shadow:
			0 1px 2px oklch(0.2 0.02 268 / 0.1),
			inset 0 -2px 0 var(--sch-accent);
	}
	:global(.dark) .sch-segments button[aria-pressed='true'] {
		background: oklch(1 0 0 / 0.08);
	}
	.sch-preview {
		min-height: 1.75rem;
		padding: 0.3125rem 0.625rem;
		border-left: 2px solid var(--sch-accent);
		border-radius: 0 0.5rem 0.5rem 0;
		background: color-mix(in oklab, var(--sch-accent) 7%, transparent);
		font-size: 0.75rem;
		color: var(--sch-ink);
	}
	.sch-preview:empty {
		visibility: hidden;
	}
	.sch-preview.is-error {
		border-left-color: var(--color-red-500, #ef4444);
		background: oklch(0.63 0.22 25 / 0.08);
		color: var(--color-red-600, #dc2626);
	}

	@keyframes sch-orbit {
		to {
			transform: rotate(360deg);
		}
	}
	@keyframes sch-breathe {
		50% {
			opacity: 0.55;
			transform: scale(0.88);
		}
	}
	@keyframes sch-ping {
		70%,
		100% {
			box-shadow: 0 0 0 5px transparent;
		}
		0% {
			box-shadow: 0 0 0 0 color-mix(in oklab, currentColor 60%, transparent);
		}
	}

	@media (max-width: 640px) {
		.sch-hero {
			flex-wrap: wrap;
			gap: 1rem;
			padding: 1rem;
		}
		.sch-hero-orbit {
			width: 4.25rem;
			height: 4.25rem;
		}
		.sch-hero-side {
			width: 100%;
			flex-direction: row;
			align-items: center;
			justify-content: space-between;
		}
		.sch-stats > div {
			text-align: left;
		}
		.sch-countdown-value {
			font-size: 1.75rem;
		}
		.sch-dial {
			width: 3.5rem;
			height: 3.5rem;
		}
		.sch-dial-main {
			font-size: 0.8125rem;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.sch-hero-orbit::after,
		.sch-hero-core,
		.sch-ring-spin,
		.sch-state-dot {
			animation: none !important;
		}
	}
</style>

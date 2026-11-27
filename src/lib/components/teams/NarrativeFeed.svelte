<script lang="ts">
	import { createEventDispatcher, onDestroy, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { retryTeamTask, sendTeamMessage } from '$lib/apis/teams';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { avatarKind, formatClock, formatDuration, type TaskState } from './model';
	import {
		LEAD_LANE_ID,
		lanePalette,
		type LanePalette,
		type NarrativeItem,
		type NarrativeKind,
		type StageSegment,
		type ToolIcon
	} from './narrative';

	/**
	 * Structured chronological narrative stream for 协作台.
	 * - Collapses consecutive tool/subagent steps into expandable pill cards (steps · duration)
	 * - Renders semantic rows for handoffs, approvals (with inline quick reply), failures (inline retry),
	 *   runner fallbacks, messages, milestones & deploy steps
	 * - Two-way synchronized with SwimlaneTree via `focusId` (rAF-throttled hover + click-only scroll)
	 */
	export let teamId: string;
	export let items: NarrativeItem[] = [];
	export let members: { name: string; role?: string }[] = [];
	export let states: Map<string, TaskState> = new Map();
	export let lanePalettes: Map<string, LanePalette> | null = null;
	export let memberFilter: string | null = null;
	export let stageFilter: string | null = null;
	export let focusId: string | null = null;
	/** Source of the current focus ('swimlane' + focusPin triggers local container scroll). */
	export let focusSource: 'feed' | 'swimlane' | null = null;
	export let focusPin = false;
	export let replay = false;
	export let teamStopped = false;
	export let autoFollow = true;
	export let stages: StageSegment[] = [];

	const dispatch = createEventDispatcher<{
		focus: { id: string | null; source: 'feed'; pin?: boolean };
		selectTask: string;
		clearFilters: void;
		changed: void;
		scroll: void;
	}>();

	type Category = 'all' | 'key' | 'message' | 'tool';
	let order: 'asc' | 'desc' = 'asc';
	let category: Category = 'all';
	let expandedTools = new Set<string>();
	let expandedBodies = new Set<string>();
	let listEl: HTMLOListElement | null = null;
	let manualScrollUntil = 0;
	let rafHover: number | null = null;

	// Inline quick-reply state keyed by item.id, busy state keyed by taskId
	let replyDrafts: Record<string, string> = {};
	let busyTasks = new Set<string>();

	const toggleTool = (id: string) => {
		if (expandedTools.has(id)) expandedTools.delete(id);
		else expandedTools.add(id);
		expandedTools = expandedTools;
	};
	const toggleBody = (id: string) => {
		if (expandedBodies.has(id)) expandedBodies.delete(id);
		else expandedBodies.add(id);
		expandedBodies = expandedBodies;
	};

	const setAllToolsExpanded = (open: boolean) => {
		if (!open) {
			expandedTools = new Set();
			return;
		}
		expandedTools = new Set(visible.filter((it) => it.kind === 'tool_group').map((it) => it.id));
	};

	$: roles = new Map(members.map((m) => [m.name, m]));
	$: laneIndexMap = new Map<string, number>([
		[LEAD_LANE_ID, 0],
		...members.map((m, i): [string, number] => [m.name, i + 1])
	]);
	$: stageById = new Map(stages.map((stage) => [stage.id, stage]));
	$: headId = items.at(-1)?.id;
	const kindOf = (name: string | null | undefined, isLead = false) =>
		avatarKind(roles.get(name ?? '') ?? { name: name ?? '' }, isLead);

	// Track the latest actionable item per task so historical fail/question items don't show stale controls.
	$: latestApprovalByTask = (() => {
		const m = new Map<string, string>();
		for (const it of items) if (it.actionable === 'reply' && it.taskId) m.set(it.taskId, it.id);
		return m;
	})();
	$: latestFailByTask = (() => {
		const m = new Map<string, string>();
		for (const it of items) if (it.actionable === 'retry' && it.taskId) m.set(it.taskId, it.id);
		return m;
	})();

	const canInlineReply = (
		item: NarrativeItem,
		liveStates: Map<string, TaskState>,
		latest: Map<string, string>,
		isReplay: boolean,
		stopped: boolean
	): boolean => {
		if (item.actionable !== 'reply' || !item.taskId || isReplay || stopped) return false;
		if (latest.get(item.taskId) !== item.id) return false;
		if (liveStates.size === 0) return true;
		const st = liveStates.get(item.taskId);
		return st?.sub_status === 'waiting_user' || st?.status === 'triage';
	};
	const canInlineRetry = (
		item: NarrativeItem,
		liveStates: Map<string, TaskState>,
		latest: Map<string, string>,
		isReplay: boolean,
		stopped: boolean
	): boolean => {
		if (item.actionable !== 'retry' || !item.taskId || isReplay || stopped) return false;
		if (latest.get(item.taskId) !== item.id) return false;
		if (liveStates.size === 0) return true;
		const st = liveStates.get(item.taskId);
		return ['failed', 'blocked'].includes(st?.sub_status ?? '');
	};

	const KEY_KINDS = new Set<NarrativeKind>([
		'message',
		'handoff',
		'approval',
		'fail',
		'retry',
		'milestone',
		'deploy'
	]);

	$: filtered = items.filter((it) => {
		if (category === 'key' && !KEY_KINDS.has(it.kind)) return false;
		if (category === 'message' && !['message', 'handoff', 'approval'].includes(it.kind))
			return false;
		if (category === 'tool' && it.kind !== 'tool_group') return false;
		if (memberFilter) {
			const hitLane = it.lane === memberFilter || it.member === memberFilter;
			const hitTarget =
				it.targetLane === memberFilter ||
				it.handoffTo.some((t) => t.member === memberFilter);
			if (!hitLane && !hitTarget) return false;
		}
		if (stageFilter && it.stageId !== stageFilter) return false;
		return true;
	});

	$: visible = order === 'asc' ? filtered : filtered.slice().reverse();
	$: hasExpandedTools = visible.some((it) => it.kind === 'tool_group' && expandedTools.has(it.id));

	// Auto-scroll to bottom when new items arrive in chronological live mode.
	let prevCount = 0;
	$: if (visible.length !== prevCount) {
		const grew = visible.length > prevCount;
		prevCount = visible.length;
		if (grew && order === 'asc' && autoFollow && Date.now() > manualScrollUntil) {
			tick().then(() => {
				if (listEl) listEl.scrollTop = listEl.scrollHeight;
			});
		}
	}

	// Scroll focused row within listEl only on explicit click from SwimlaneTree (never outer page).
	$: if (focusId && focusSource === 'swimlane' && focusPin && listEl) {
		const id = focusId;
		tick().then(() => {
			if (!listEl) return;
			const escaped =
				typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
					? CSS.escape(id)
					: id.replace(/["\\]/g, '\\$&');
			const el = listEl.querySelector(`[data-narrative-id="${escaped}"]`) as HTMLElement | null;
			if (!el) return;
			const box = listEl.getBoundingClientRect();
			const rect = el.getBoundingClientRect();
			const delta = rect.top - box.top - box.height * 0.35;
			const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
			listEl.scrollTo({
				top: Math.max(0, listEl.scrollTop + delta),
				behavior: reduced ? 'auto' : 'smooth'
			});
		});
	}

	const onWheelOrTouch = () => {
		manualScrollUntil = Date.now() + 2000;
	};
	const onListScroll = () => {
		dispatch('scroll');
	};
	$: visible, expandedTools, expandedBodies, tick().then(onListScroll);

	const hoverItem = (id: string | null) => {
		if (typeof window === 'undefined') {
			dispatch('focus', { id, source: 'feed', pin: false });
			return;
		}
		if (rafHover !== null) cancelAnimationFrame(rafHover);
		rafHover = requestAnimationFrame(() => {
			rafHover = null;
			dispatch('focus', { id, source: 'feed', pin: false });
		});
	};

	onDestroy(() => {
		if (rafHover !== null && typeof cancelAnimationFrame === 'function')
			cancelAnimationFrame(rafHover);
	});

	const sendInlineReply = async (item: NarrativeItem) => {
		if (!item.taskId || replay || teamStopped) return;
		const text = (replyDrafts[item.id] ?? '').trim();
		if (!text || busyTasks.has(item.taskId)) return;
		busyTasks.add(item.taskId);
		busyTasks = busyTasks;
		try {
			await sendTeamMessage(localStorage.token, teamId, item.taskId, text);
			replyDrafts[item.id] = '';
			replyDrafts = replyDrafts;
			toast.success('已发送回复，成员将继续执行');
			dispatch('changed');
		} catch (error) {
			toast.error(`${(error as any)?.message ?? error}`);
		} finally {
			busyTasks.delete(item.taskId);
			busyTasks = busyTasks;
		}
	};

	const retryInline = async (item: NarrativeItem) => {
		if (!item.taskId || replay || teamStopped || busyTasks.has(item.taskId)) return;
		busyTasks.add(item.taskId);
		busyTasks = busyTasks;
		try {
			await retryTeamTask(localStorage.token, teamId, item.taskId);
			toast.success(`已重新派发 #${item.taskKey ?? ''}`);
			dispatch('changed');
		} catch (error) {
			toast.error(`${(error as any)?.message ?? error}`);
		} finally {
			busyTasks.delete(item.taskId);
			busyTasks = busyTasks;
		}
	};

	const badgeClass = (kind: NarrativeKind) => {
		switch (kind) {
			case 'handoff':
				return 'badge-handoff';
			case 'tool_group':
				return 'badge-tool';
			case 'approval':
				return 'badge-approval';
			case 'fail':
				return 'badge-fail';
			case 'retry':
				return 'badge-retry';
			case 'deploy':
				return 'badge-deploy';
			case 'milestone':
				return 'badge-milestone';
			default:
				return 'badge-neutral';
		}
	};

	const CATS: { value: Category; label: string; icon: string }[] = [
		{ value: 'all', label: '全部', icon: 'M3 4h10M3 8h10M3 12h10' },
		{ value: 'key', label: '关键节点', icon: 'm8 2 6 6-6 6-6-6Z' },
		{ value: 'message', label: '对话/交接', icon: 'M3 3.5h10v7H7l-3 2v-2H3Z' },
		{ value: 'tool', label: '步骤组', icon: 'm3 5 3 3-3 3m5 0h5' }
	];
	const TOOL_ICONS: Record<ToolIcon, string> = {
		search: 'M11 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Zm-1 3 3.5 3.5',
		edit: 'm3 10 7.8-7.8 3 3L6 13H3Zm6.2-6.2 3 3',
		terminal: 'm3 5 3 3-3 3m5 0h5',
		image: 'M2.5 3.5h11v9h-11Zm0 7 3-3 2.5 2.5 2-2 3.5 3.5M10 6h.1',
		subagent: 'M6 2.5h4v4H6ZM3 10h3v3H3Zm7 0h3v3h-3ZM8 6.5V8m-3.5 2V8h7v2',
		generic: 'm8 2.5 5 2.75v5.5L8 13.5l-5-2.75v-5.5Zm-5 2.75L8 8l5-2.75M8 8v5.5'
	};
</script>

<div class="flex h-full min-h-0 flex-col" data-narrative-feed>
	<!-- Toolbar -->
	<div class="workbench-pane-head flex flex-wrap items-center gap-2 border-b px-3 py-2 tm-hairline">
		<div class="tm-segment !p-[2px]" role="radiogroup" aria-label="筛选叙事流">
			{#each CATS as opt}
				<button
					type="button"
					role="radio"
					aria-checked={category === opt.value}
					class="!inline-flex items-center gap-1 !px-2 !py-0.5 !text-[11px]"
					on:click={() => (category = opt.value)}
				>
					<svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
						<path
							d={opt.icon}
							stroke="currentColor"
							stroke-width="1.4"
							stroke-linejoin="round"
							stroke-linecap="round"
						/>
					</svg>
					{opt.label}
				</button>
			{/each}
		</div>

		<div class="ml-auto flex items-center gap-1.5">
			<span class="feed-count tm-num" title="显示条数 / 总条数"
				>{visible.length} / {items.length}</span
			>
			{#if memberFilter || stageFilter || category !== 'all'}
				<button
					type="button"
					class="rounded-full bg-sky-500/10 px-2 py-0.5 text-[11px] font-medium text-sky-700 hover:bg-sky-500/15 dark:text-sky-300"
					on:click={() => {
						category = 'all';
						dispatch('clearFilters');
					}}
					data-clear-filters
				>
					已筛选 · 清除
				</button>
			{/if}
			<button
				type="button"
				class="tm-btn-ghost !px-2 !py-0.5 !text-[11px]"
				on:click={() => setAllToolsExpanded(!hasExpandedTools)}
				title="一键展开或折叠所有工具步骤组"
			>
				{hasExpandedTools ? '折叠步骤' : '展开步骤'}
			</button>
			<button
				type="button"
				class="tm-btn-ghost !px-2 !py-0.5 !text-[11px]"
				on:click={() => (order = order === 'asc' ? 'desc' : 'asc')}
				title="切换时间排序"
				data-order-toggle
			>
				{order === 'asc' ? '正序叙事' : '最新在上'}
			</button>
		</div>
	</div>

	<!-- Narrative list -->
	{#if visible.length === 0}
		<div class="flex flex-1 flex-col items-center justify-center gap-2 py-12 text-center">
			<span class="size-2 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
			<span class="text-sm text-gray-400 dark:text-gray-500">
				{items.length ? '当前筛选条件下没有记录' : '等待成员产生第一条协作记录…'}
			</span>
			{#if memberFilter || stageFilter || category !== 'all'}
				<button
					type="button"
					class="tm-btn-ghost mt-1"
					on:click={() => {
						category = 'all';
						dispatch('clearFilters');
					}}>显示全部记录</button
				>
			{/if}
		</div>
	{:else}
		<ol
			bind:this={listEl}
			on:wheel|passive={onWheelOrTouch}
			on:touchstart|passive={onWheelOrTouch}
			on:scroll|passive={onListScroll}
			class="timeline tm-scroll min-h-0 flex-1 overflow-y-auto"
			aria-label="结构化协作流"
			aria-live="polite"
		>
			{#each visible as item, i (item.id)}
				{@const stage = stageById.get(item.stageId)}
				{@const pal =
					lanePalettes?.get(item.lane) ?? lanePalette(item.lane, laneIndexMap.get(item.lane) ?? 1)}
				{@const focused = focusId === item.id}
				{@const isToolOpen = expandedTools.has(item.id)}
				{@const isBodyOpen = expandedBodies.has(item.id)}
				{@const taskBusy = !!item.taskId && busyTasks.has(item.taskId)}
				{@const actionable = canInlineReply(
					item,
					states,
					latestApprovalByTask,
					replay,
					teamStopped
				)}
				{#if stage && visible[i - 1]?.stageId !== item.stageId}
					<li
						class="timeline-stage"
						data-narrative-stage={stage.id}
						style="--stage-color:{stage.color}"
					>
						<span class="stage-dot" aria-hidden="true" />
						<span>{stage.shortLabel}</span>
						<span class="feed-count tm-num">{stage.done}/{stage.total}</span>
						<span class="stage-rule" aria-hidden="true" />
					</li>
				{/if}
				<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-noninteractive-element-interactions -->
				<li
					class="row-card {focused ? 'is-focused' : ''} kind-{item.kind}"
					class:is-actionable={actionable}
					style="--lane-color:{pal.stroke};--lane-soft:{pal.soft}"
					data-narrative-id={item.id}
					data-narrative-kind={item.kind}
					data-focus={focused ? 'true' : undefined}
					on:mouseenter={() => hoverItem(item.id)}
					on:mouseleave={() => hoverItem(null)}
					on:click={() => dispatch('focus', { id: item.id, source: 'feed', pin: true })}
				>
					<span class="timeline-anchor" class:is-head={item.id === headId} aria-hidden="true" />
					{#if focused}<span class="connector-anchor" aria-hidden="true" />{/if}
					{#if item.kind === 'tool_group'}
						<!-- Collapsible structured tool batch -->
						<div class="flex items-start gap-1.5">
							<button
								type="button"
								class="tool-toggle min-w-0 flex-1 text-left"
								aria-expanded={isToolOpen}
								on:click|stopPropagation={() => {
									toggleTool(item.id);
									dispatch('focus', { id: item.id, source: 'feed', pin: true });
								}}
								data-tool-group-toggle={item.id}
							>
								<span
									class="chevron shrink-0 text-gray-400 transition-transform {isToolOpen ? 'rotate-90' : ''}"
									aria-hidden="true"
									><svg class="size-3.5" viewBox="0 0 16 16" fill="none"
										><path
											d="m6 4 4 4-4 4"
											stroke="currentColor"
											stroke-width="1.6"
											stroke-linecap="round"
											stroke-linejoin="round"
										/></svg
									></span
								>
								<span class="tool-icon" title={item.badge}>
									<svg
										width="15"
										height="15"
										viewBox="0 0 16 16"
										fill="none"
										role="img"
										aria-label={item.badge}
									>
										<path
											d={TOOL_ICONS[item.toolIcon ?? 'generic']}
											stroke="currentColor"
											stroke-width="1.4"
											stroke-linejoin="round"
											stroke-linecap="round"
										/>
									</svg>
								</span>
								<span class="min-w-0">
									<span class="block break-words text-xs font-semibold" title={item.title}
										>{item.title}</span
									>
									<span class="block truncate text-[11px] text-gray-500 dark:text-gray-400"
										>{item.member ?? '系统'}</span
									>
								</span>
								<span class="tool-stats tm-num">
									{item.stepCount} 步{item.durationSec > 0 ? ` · ${item.durationSec}s` : ''}
								</span>
							</button>
							{#if item.taskKey && item.taskId}
								<button
									type="button"
									class="task-chip shrink-0 self-center"
									on:click|stopPropagation={() =>
										item.taskId && dispatch('selectTask', item.taskId)}>#{item.taskKey}</button
								>
							{/if}
						</div>

						{#if item.files.length && !isToolOpen}
							<div class="mt-1.5 flex flex-wrap gap-1 pl-6">
								{#each item.files as file}
									<span class="file-chip">{file}</span>
								{/each}
							</div>
						{/if}

						{#if isToolOpen}
							<div class="terminal mt-2" data-tool-group-steps={item.id}>
								<div class="terminal-head">
									已执行 {item.stepCount} 个步骤{item.durationSec > 0
										? ` · 用时 ${formatDuration(item.durationSec)}`
										: ''} · {formatClock(item.ts)}
								</div>
								<ol class="terminal-steps">
									{#each item.steps as step, index (step.id)}
										<li class="terminal-row">
											<span class="terminal-number">{String(index + 1).padStart(2, '0')}</span>
											<span class="terminal-tool">
												{step.type === 'subagent'
													? step.data?.phase === 'start'
														? 'subagent:start'
														: 'subagent:end'
													: step.data?.name ?? 'tool'}
											</span>
											{#if step.text}
												<code class="terminal-command">{step.text}</code>
											{/if}
											<time class="terminal-time">{formatClock(step.ts)}</time>
										</li>
									{/each}
								</ol>
							</div>
						{/if}
					{:else}
						<!-- Semantic card: message / handoff / approval / fail / retry / runner / milestone / deploy -->
						<div class="flex items-start gap-2.5">
							<div class="shrink-0 pt-0.5">
								{#if item.kind === 'milestone' || item.kind === 'deploy'}
									<svg
										class="banner-icon"
										width="24"
										height="24"
										viewBox="0 0 24 24"
										fill="none"
										aria-hidden="true"
									>
										<path
											d={item.kind === 'deploy'
												? 'M9 15c0-5 4-9 10-10-1 6-5 10-10 10Zm0 0-3 3m3-7H6l-2 3h5m6 1v3l-3 2v-5m2-5h.1'
												: 'm12 4 8 8-8 8-8-8Zm0 4 4 4-4 4-4-4Z'}
											stroke="currentColor"
											stroke-width="1.4"
											stroke-linejoin="round"
										/>
									</svg>
								{:else if item.lane === LEAD_LANE_ID}
									<TeamAvatar kind="lead" size={24} />
								{:else}
									<TeamAvatar kind={kindOf(item.member)} size={24} />
								{/if}
							</div>
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
									<span class="badge {badgeClass(item.kind)}">{item.badge}</span>
									{#if item.kind !== 'handoff'}
										<span class="break-words font-semibold text-gray-900 dark:text-gray-100"
											>{item.title}</span
										>
									{/if}
									{#if item.taskKey}
										<button
											type="button"
											class="task-chip"
											on:click|stopPropagation={() => item.taskId && dispatch('selectTask', item.taskId)}
											>#{item.taskKey}</button
										>
									{/if}
									{#if item.runnerMeta && item.kind !== 'runner'}
										<span
											class="font-mono text-[10px] text-gray-500 dark:text-gray-400"
											class:sha-chip={item.stageId === 'deploy'}>{item.runnerMeta}</span
										>
									{/if}
									<time class="tm-num ml-auto shrink-0 text-[11px] text-gray-400">
										{formatClock(item.ts)}
									</time>
								</div>
								{#if item.kind === 'handoff'}
									<div class="handoff-route">
										<span class="handoff-chip">{item.member ?? item.author ?? '负责人'}</span>
										<svg
											class="handoff-arrow"
											width="29"
											height="12"
											viewBox="0 0 29 12"
											fill="none"
											role="img"
											aria-label="交接至"
										>
											<path
												d="M1 6h26m-5-4 5 4-5 4"
												stroke="currentColor"
												stroke-width="1.4"
												stroke-linejoin="round"
											/>
										</svg>
										{#each item.handoffTo as to}
											<span class="handoff-chip">{to.member}{to.key ? ` #${to.key}` : ''}</span>
										{:else}
											<span class="handoff-chip">下一阶段</span>
										{/each}
									</div>
								{/if}

								{#if item.body}
									{@const longBody = item.body.length > 220 || item.body.split('\n').length > 4}
									<div
										class="mt-1.5 whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-gray-700 dark:text-gray-200 {longBody &&
										!isBodyOpen
											? 'line-clamp-4'
											: ''}"
									>
										{item.body}
									</div>
									{#if longBody}
										<button
											type="button"
											class="mt-1 text-[11px] font-medium text-sky-600 hover:underline dark:text-sky-300"
											on:click|stopPropagation={() => toggleBody(item.id)}
										>
											{isBodyOpen ? '收起' : '展开全文'}
										</button>
									{/if}
								{/if}

								{#if item.files.length}
									<div class="mt-1.5 flex flex-wrap gap-1">
										{#each item.files as file}
											<span class="file-chip">{file}</span>
										{/each}
									</div>
								{/if}

								{#if item.delivery}
									<div class="mt-1.5">
										<StatusChip
											status={item.delivery.state === 'delivered'
												? 'done'
												: item.delivery.state === 'queued'
													? 'queued'
													: 'failed'}
											label={item.delivery.label}
										/>
									</div>
								{/if}

								<!-- Inline approval reply right in the stream (only when task is currently waiting_user) -->
								{#if actionable}
									<form
										class="mt-2 flex items-center gap-1.5"
										on:click|stopPropagation
										on:submit|preventDefault={() => sendInlineReply(item)}
										data-inline-reply={item.id}
									>
										<input
											type="text"
											class="reply-field min-w-0 flex-1 rounded-lg border px-2.5 py-1 text-xs"
											placeholder="直接在这里回复并继续…"
											aria-label="回复待确认事项"
											bind:value={replyDrafts[item.id]}
											disabled={taskBusy}
										/>
										<button
											type="submit"
											class="tm-btn-primary !px-2.5 !py-1 !text-xs"
											disabled={taskBusy || !(replyDrafts[item.id] ?? '').trim()}
										>
											{taskBusy ? '发送中…' : '回复'}
										</button>
									</form>
								{/if}

								<!-- Inline fail actions (only when task is currently failed/blocked) -->
								{#if canInlineRetry(item, states, latestFailByTask, replay, teamStopped)}
									<div
										class="mt-2 flex flex-wrap items-center gap-1.5"
										on:click|stopPropagation
										data-inline-retry={item.id}
									>
										<button
											type="button"
											class="tm-btn-ghost !py-0.5 !text-[11px]"
											disabled={taskBusy}
											on:click={() => retryInline(item)}
										>
											{taskBusy ? '重派中…' : '重试任务'}
										</button>
										<button
											type="button"
											class="tm-btn-ghost !py-0.5 !text-[11px]"
											on:click={() => item.taskId && dispatch('selectTask', item.taskId)}
										>
											查看日志 / 换执行源
										</button>
									</div>
								{/if}
							</div>
						</div>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.timeline {
		padding: 0.65rem 0.85rem 0.75rem 1.9rem;
	}
	.timeline > li + li {
		margin-top: 0.55rem;
	}
	.timeline-anchor {
		position: absolute;
		z-index: 1;
		left: -1.3rem;
		top: calc(50% - 4px);
		width: 8px;
		height: 8px;
		border: 1.5px solid var(--lane-color);
		border-radius: 50%;
		background: var(--tm-workbench-pill);
	}
	.timeline-anchor.is-head {
		background: var(--lane-color);
	}
	.timeline-anchor.is-head::after {
		content: '';
		position: absolute;
		inset: -4px;
		border: 1px solid var(--lane-color);
		border-radius: inherit;
		animation: tm-feed-pulse 2.4s ease-out infinite;
		animation-play-state: var(--tm-workbench-play-state, running);
	}
	.timeline-stage {
		position: relative;
		display: flex;
		align-items: center;
		gap: 0.45rem;
		padding: 0.2rem 0;
		color: hsl(var(--tm-ink));
		font-size: 0.7rem;
		font-weight: 650;
	}
	.timeline-stage::before,
	.row-card::after {
		content: '';
		position: absolute;
		width: 1px;
		left: -1.05rem;
		inset-block: -0.55rem 0;
		background: hsl(var(--tm-line-strong));
		pointer-events: none;
	}
	.timeline > li:first-child::before,
	.timeline > .row-card:first-child::after {
		inset-block-start: 50%;
	}
	.timeline > .row-card:last-child::after {
		inset-block-end: 50%;
	}
	.stage-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		flex: none;
		background: var(--stage-color);
	}
	.stage-rule {
		position: relative;
		height: 1px;
		min-width: 0.65rem;
		flex: 1;
		overflow: hidden;
		background: linear-gradient(90deg, var(--stage-color), transparent);
	}
	.feed-count {
		flex: none;
		padding: 0.1rem 0.35rem;
		border-radius: 4px;
		border: 1px solid hsl(var(--tm-line));
		color: hsl(var(--tm-muted));
		font-size: 0.65rem;
	}
	.row-card {
		position: relative;
		border-radius: 0.85rem;
		border: 1px solid hsl(var(--tm-line));
		background: var(--tm-workbench-card);
		padding: 0.55rem 0.75rem;
		transition:
			border-color 0.16s ease,
			box-shadow 0.16s ease,
			background 0.16s ease;
	}
	.row-card::before {
		content: '';
		position: absolute;
		left: 0;
		top: 0.5rem;
		bottom: 0.5rem;
		width: 2.5px;
		border-radius: 9999px;
		background: var(--lane-color, hsl(var(--tm-accent)));
		opacity: 0.45;
		transition: opacity 0.16s ease;
	}
	.row-card:hover::before,
	.row-card.is-focused::before {
		opacity: 1;
	}
	.row-card.is-focused {
		border-color: color-mix(in srgb, var(--lane-color) 55%, transparent);
		box-shadow:
			0 0 0 2px color-mix(in srgb, var(--lane-color) 16%, transparent),
			var(--tm-shadow);
	}
	.connector-anchor {
		position: absolute;
		right: 0;
		top: 50%;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--lane-color);
		box-shadow: 0 0 6px var(--lane-color);
		transform: translate(50%, -50%);
		pointer-events: none;
	}
	.row-card.is-focused::before {
		box-shadow: 0 0 6px var(--lane-color);
	}
	.row-card.kind-tool_group {
		background: hsl(var(--tm-surface-2) / 0.85);
		padding: 0.45rem 0.7rem;
	}
	.row-card.kind-handoff {
		background: linear-gradient(90deg, hsl(158 64% 42% / 0.06), var(--tm-workbench-card) 55%);
		border-color: hsl(158 64% 42% / 0.22);
	}
	.row-card.kind-approval {
		background: linear-gradient(90deg, hsl(var(--tm-violet) / 0.09), var(--tm-workbench-card) 65%);
		border-color: hsl(var(--tm-violet) / 0.32);
	}
	.row-card.kind-approval.is-actionable {
		border-color: hsl(var(--tm-violet) / 0.68);
	}
	.row-card.kind-approval.is-actionable::before {
		background: hsl(var(--tm-violet));
		animation: tm-approval-pulse 2.6s ease-in-out infinite alternate;
		animation-play-state: var(--tm-workbench-play-state, running);
	}
	.reply-field {
		border-color: hsl(var(--tm-violet) / 0.36);
		background: var(--tm-workbench-pill);
		color: hsl(var(--tm-ink));
	}
	.reply-field:focus {
		border-color: hsl(var(--tm-violet));
		outline: 2px solid hsl(var(--tm-violet) / 0.22);
	}
	@keyframes tm-feed-pulse {
		from {
			opacity: 0.8;
			transform: scale(0.8);
		}
		to {
			opacity: 0;
			transform: scale(1.55);
		}
	}
	@keyframes tm-approval-pulse {
		from {
			opacity: 0.55;
		}
		to {
			opacity: 1;
			box-shadow: 0 0 8px hsl(var(--tm-violet) / 0.75);
		}
	}
	.row-card.kind-fail {
		background: linear-gradient(90deg, hsl(var(--tm-bad) / 0.08), var(--tm-workbench-card) 65%);
		border-color: hsl(var(--tm-bad) / 0.32);
	}
	.row-card.kind-retry {
		background: linear-gradient(90deg, hsl(var(--tm-warn) / 0.08), var(--tm-workbench-card) 60%);
		border-color: hsl(var(--tm-warn) / 0.28);
	}
	.kind-fail::before,
	.kind-retry::before {
		width: 3px;
		opacity: 1;
	}
	.kind-fail::before {
		background: hsl(var(--tm-bad));
	}
	.kind-retry::before {
		background: hsl(var(--tm-warn));
	}
	.row-card.kind-deploy {
		background: linear-gradient(90deg, hsl(var(--tm-ok) / 0.08), var(--tm-workbench-card) 60%);
		border-color: hsl(var(--tm-ok) / 0.26);
	}
	.row-card.kind-milestone {
		background: linear-gradient(90deg, hsl(var(--tm-accent) / 0.08), var(--tm-workbench-card) 68%);
		border-color: hsl(var(--tm-accent) / 0.24);
	}
	.kind-milestone,
	.kind-deploy {
		box-shadow: inset 0 1px hsl(var(--tm-accent) / 0.12);
	}
	.banner-icon {
		color: hsl(var(--tm-accent));
	}
	.kind-deploy .banner-icon {
		color: hsl(var(--tm-ok));
	}
	.handoff-route {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.25rem;
		margin-top: 0.25rem;
	}
	.handoff-chip,
	.sha-chip {
		max-width: 100%;
		border-radius: 5px;
		padding: 0.08rem 0.38rem;
		overflow-wrap: anywhere;
		border: 1px solid hsl(var(--tm-ok) / 0.28);
		background: hsl(var(--tm-ok) / 0.08);
	}
	.handoff-chip {
		font-size: 0.72rem;
		color: hsl(var(--tm-ink));
	}
	.handoff-arrow {
		color: hsl(var(--tm-ok));
	}
	.tool-toggle {
		display: grid;
		grid-template-columns: auto auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 0.35rem;
	}
	.tool-icon {
		display: grid;
		place-items: center;
		width: 1.6rem;
		height: 1.6rem;
		border-radius: 6px;
		background: var(--lane-soft);
		color: hsl(var(--tm-ink));
		border: 1px solid color-mix(in srgb, var(--lane-color) 35%, transparent);
	}
	.tool-stats {
		border-radius: 5px;
		padding: 0.1rem 0.35rem;
		font-size: 0.65rem;
		background: var(--lane-soft);
		color: hsl(var(--tm-muted));
	}
	.terminal {
		border-radius: 0.6rem;
		overflow: hidden;
		background: #101522;
		border: 1px solid #25314a;
		color: #dce6f7;
	}
	.terminal-head {
		padding: 0.35rem 0.55rem;
		border-bottom: 1px solid #25314a;
		background: #182237;
		color: #b6c7e7;
		font-size: 0.68rem;
	}
	.terminal-steps {
		padding: 0.25rem 0.5rem;
	}
	.terminal-row {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 0.2rem 0.45rem;
		align-items: baseline;
		padding: 0.28rem 0;
		font: 0.68rem var(--font-mono);
	}
	.terminal-row + .terminal-row {
		border-top: 1px solid #222c40;
	}
	.terminal-number,
	.terminal-time {
		color: #9eabc2;
	}
	.terminal-tool {
		justify-self: start;
		padding: 0.07rem 0.25rem;
		border-radius: 4px;
		background: #23334f;
		color: #a5dfff;
		overflow-wrap: anywhere;
	}
	.terminal-command {
		grid-column: 2 / -1;
		grid-row: 2;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.terminal-time {
		grid-column: 3;
		grid-row: 1;
	}
	@media (prefers-reduced-motion: reduce), (max-width: 767px) {
		.timeline-anchor.is-head::after,
		.row-card.kind-approval.is-actionable::before {
			animation: none;
		}
	}
	.badge {
		display: inline-flex;
		align-items: center;
		border-radius: 0.4rem;
		padding: 0.08rem 0.42rem;
		font-size: 0.68rem;
		font-weight: 600;
		line-height: 1.3;
		white-space: nowrap;
	}
	.badge-neutral {
		background: hsl(var(--tm-line));
		color: hsl(var(--tm-ink));
	}
	.badge-tool {
		background: hsl(194 78% 50% / 0.12);
		color: hsl(194 82% 34%);
	}
	:global(.dark) .badge-tool {
		color: hsl(194 88% 70%);
	}
	.badge-handoff {
		background: hsl(158 64% 42% / 0.14);
		color: hsl(158 72% 28%);
	}
	:global(.dark) .badge-handoff {
		color: hsl(158 70% 66%);
	}
	.badge-approval {
		background: hsl(var(--tm-violet) / 0.14);
		color: hsl(var(--tm-violet));
	}
	.badge-fail {
		background: hsl(var(--tm-bad) / 0.14);
		color: hsl(var(--tm-bad));
	}
	.badge-retry {
		background: hsl(var(--tm-warn) / 0.16);
		color: hsl(32 88% 36%);
	}
	:global(.dark) .badge-retry {
		color: hsl(var(--tm-warn));
	}
	.badge-deploy {
		background: hsl(var(--tm-ok) / 0.15);
		color: hsl(158 72% 28%);
	}
	:global(.dark) .badge-deploy {
		color: hsl(var(--tm-ok));
	}
	.badge-milestone {
		background: hsl(var(--tm-accent) / 0.14);
		color: hsl(var(--tm-accent));
	}
	.task-chip {
		border-radius: 0.35rem;
		padding: 0.05rem 0.35rem;
		font-family: var(--font-mono);
		font-size: 0.68rem;
		font-weight: 600;
		color: hsl(var(--tm-muted));
		background: hsl(var(--tm-line));
		transition:
			color 0.15s ease,
			background 0.15s ease;
	}
	.task-chip:hover {
		color: hsl(var(--tm-accent));
		background: hsl(var(--tm-accent) / 0.12);
	}
	.file-chip {
		display: inline-flex;
		align-items: center;
		border-radius: 0.35rem;
		padding: 0.08rem 0.4rem;
		font-family: var(--font-mono);
		font-size: 0.66rem;
		color: hsl(var(--tm-muted));
		border: 1px solid hsl(var(--tm-line));
		background: hsl(var(--tm-surface));
	}
</style>

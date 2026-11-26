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
		type NarrativeKind
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

	const dispatch = createEventDispatcher<{
		focus: { id: string | null; source: 'feed'; pin?: boolean };
		selectTask: string;
		clearFilters: void;
		changed: void;
		scroll: void;
	}>();

	let order: 'asc' | 'desc' = 'asc';
	let category: 'all' | 'key' | 'message' | 'tool' = 'all';
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
	const paletteOf = (lane: string) =>
		lanePalettes?.get(lane) ?? lanePalette(lane, laneIndexMap.get(lane) ?? 1);
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
			listEl.scrollTo({ top: Math.max(0, listEl.scrollTop + delta), behavior: 'smooth' });
		});
	}

	const onWheelOrTouch = () => {
		manualScrollUntil = Date.now() + 2000;
	};
	const onListScroll = () => {
		dispatch('scroll');
	};

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

	const CATS: { value: typeof category; label: string }[] = [
		{ value: 'all', label: '全部' },
		{ value: 'key', label: '关键节点' },
		{ value: 'message', label: '对话/交接' },
		{ value: 'tool', label: '步骤组' }
	];
</script>

<div class="flex h-full min-h-0 flex-col" data-narrative-feed>
	<!-- Toolbar -->
	<div class="flex flex-wrap items-center gap-2 border-b px-3 py-2 tm-hairline">
		<div class="tm-segment !p-[2px]" role="radiogroup" aria-label="筛选叙事流">
			{#each CATS as opt}
				<button
					type="button"
					role="radio"
					aria-checked={category === opt.value}
					class="!px-2 !py-0.5 !text-[11px]"
					on:click={() => (category = opt.value)}>{opt.label}</button
				>
			{/each}
		</div>

		<div class="ml-auto flex items-center gap-1.5">
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
			class="tm-scroll min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3"
			aria-label="结构化协作流"
			aria-live="polite"
		>
			{#each visible as item (item.id)}
				{@const pal = paletteOf(item.lane)}
				{@const focused = focusId === item.id}
				{@const isToolOpen = expandedTools.has(item.id)}
				{@const isBodyOpen = expandedBodies.has(item.id)}
				{@const taskBusy = !!item.taskId && busyTasks.has(item.taskId)}
				<li
					class="row-card {focused ? 'is-focused' : ''} kind-{item.kind}"
					style="--lane-color:{pal.stroke};--lane-soft:{pal.soft}"
					data-narrative-id={item.id}
					data-narrative-kind={item.kind}
					data-focus={focused ? 'true' : undefined}
					on:mouseenter={() => hoverItem(item.id)}
					on:mouseleave={() => hoverItem(null)}
					on:click={() => dispatch('focus', { id: item.id, source: 'feed', pin: true })}
				>
					{#if item.kind === 'tool_group'}
						<!-- Collapsible structured tool batch -->
						<div class="flex items-start gap-2.5">
							<button
								type="button"
								class="group flex min-w-0 flex-1 items-center gap-2 text-left"
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
								<span class="lane-bar shrink-0" aria-hidden="true" />
								<span class="badge {badgeClass(item.kind)}">{item.badge}</span>
								<span class="shrink-0 text-xs font-medium text-gray-700 dark:text-gray-200"
									>{item.member ?? '系统'}</span
								>
								<span class="min-w-0 flex-1 truncate text-xs text-gray-600 dark:text-gray-300"
									>{item.title}</span
								>
								{#if item.taskKey}
									<span
										role="button"
										tabindex="0"
										class="task-chip shrink-0"
										on:click|stopPropagation={() => item.taskId && dispatch('selectTask', item.taskId)}
										on:keydown|stopPropagation={(e) =>
											e.key === 'Enter' && item.taskId && dispatch('selectTask', item.taskId)}
										>#{item.taskKey}</span
									>
								{/if}
								<span class="tm-num shrink-0 text-[11px] text-gray-400 dark:text-gray-500">
									{item.stepCount} 步{item.durationSec > 0 ? ` · ${item.durationSec}s` : ''}
								</span>
							</button>
						</div>

						{#if item.files.length && !isToolOpen}
							<div class="mt-1.5 flex flex-wrap gap-1 pl-6">
								{#each item.files as file}
									<span class="file-chip">{file}</span>
								{/each}
							</div>
						{/if}

						{#if isToolOpen}
							<div class="mt-2 border-t pt-2 pl-5 tm-hairline" data-tool-group-steps={item.id}>
								<div class="mb-1.5 text-[11px] text-gray-400">
									已执行 {item.stepCount} 个步骤{item.durationSec > 0
										? ` · 用时 ${formatDuration(item.durationSec)}`
										: ''} · {formatClock(item.ts)}
								</div>
								<ul class="space-y-1">
									{#each item.steps as step (step.id)}
										<li class="flex min-w-0 items-baseline gap-2 font-mono text-[11px]">
											<span class="shrink-0 font-semibold text-gray-700 dark:text-gray-200">
												{step.type === 'subagent'
													? step.data?.phase === 'start'
														? 'subagent:start'
														: 'subagent:end'
													: step.data?.name ?? 'tool'}
											</span>
											{#if step.text}
												<span
													class="min-w-0 flex-1 whitespace-pre-wrap break-all text-gray-500 dark:text-gray-400"
													>{step.text}</span
												>
											{/if}
											<time class="tm-num shrink-0 text-[10px] text-gray-400"
												>{formatClock(step.ts)}</time
											>
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					{:else}
						<!-- Semantic card: message / handoff / approval / fail / retry / runner / milestone / deploy -->
						<div class="flex items-start gap-2.5">
							<div class="shrink-0 pt-0.5">
								{#if item.lane === LEAD_LANE_ID}
									<TeamAvatar kind="lead" size={24} />
								{:else}
									<TeamAvatar kind={kindOf(item.member)} size={24} />
								{/if}
							</div>
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
									<span class="badge {badgeClass(item.kind)}">{item.badge}</span>
									<span class="font-semibold text-gray-900 dark:text-gray-100">{item.title}</span>
									{#if item.taskKey}
										<button
											type="button"
											class="task-chip"
											on:click|stopPropagation={() => item.taskId && dispatch('selectTask', item.taskId)}
											>#{item.taskKey}</button
										>
									{/if}
									{#if item.runnerMeta && item.kind !== 'runner'}
										<span class="font-mono text-[10px] text-gray-400">{item.runnerMeta}</span>
									{/if}
									<time class="tm-num ml-auto shrink-0 text-[11px] text-gray-400">
										{formatClock(item.ts)}
									</time>
								</div>

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
								{#if canInlineReply(item, states, latestApprovalByTask, replay, teamStopped)}
									<form
										class="mt-2 flex items-center gap-1.5"
										on:click|stopPropagation
										on:submit|preventDefault={() => sendInlineReply(item)}
										data-inline-reply={item.id}
									>
										<input
											type="text"
											class="min-w-0 flex-1 rounded-lg border px-2.5 py-1 text-xs text-gray-900 placeholder:text-gray-400 focus:border-violet-400 focus:outline-none dark:bg-gray-900/60 dark:text-gray-100 tm-hairline"
											placeholder="直接在这里回复并继续…"
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
	.row-card {
		position: relative;
		border-radius: 0.85rem;
		border: 1px solid hsl(var(--tm-line));
		background: hsl(var(--tm-surface));
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
	.row-card.kind-tool_group {
		background: hsl(var(--tm-surface-2) / 0.85);
		padding: 0.45rem 0.7rem;
	}
	.row-card.kind-handoff {
		background: linear-gradient(90deg, hsl(158 64% 42% / 0.06), hsl(var(--tm-surface)) 55%);
		border-color: hsl(158 64% 42% / 0.22);
	}
	.row-card.kind-approval {
		background: linear-gradient(90deg, hsl(var(--tm-violet) / 0.09), hsl(var(--tm-surface)) 65%);
		border-color: hsl(var(--tm-violet) / 0.32);
	}
	.row-card.kind-fail {
		background: linear-gradient(90deg, hsl(var(--tm-bad) / 0.08), hsl(var(--tm-surface)) 65%);
		border-color: hsl(var(--tm-bad) / 0.32);
	}
	.row-card.kind-retry {
		background: linear-gradient(90deg, hsl(var(--tm-warn) / 0.08), hsl(var(--tm-surface)) 60%);
		border-color: hsl(var(--tm-warn) / 0.28);
	}
	.row-card.kind-deploy {
		background: linear-gradient(90deg, hsl(var(--tm-ok) / 0.08), hsl(var(--tm-surface)) 60%);
		border-color: hsl(var(--tm-ok) / 0.26);
	}
	.lane-bar {
		width: 6px;
		height: 6px;
		border-radius: 9999px;
		background: var(--lane-color);
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

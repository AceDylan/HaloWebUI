<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import { elapsed, now } from './clock';
	import { runnerLabel, toneOf } from './model';
	import { LEAD_LANE_ID, lanePalette, type LanePalette, type StageSegment } from './narrative';

	/**
	 * Compact top matrix bar ("成员 × 阶段"):
	 * - Row 1: role/member filter pills (with colored lane dots & live pulse) + compact progress + view switcher
	 * - Row 2: colored multi-segment stage progress ruler + clickable stage filter pills
	 */
	export let lead: { name: string; role: string; status: string; model?: string };
	export let members: {
		name: string;
		role: string;
		status: string;
		executor: string;
		actualRunner?: string | null;
		currentKey?: string | null;
		assistant?: { name: string; emoji?: string } | null;
	}[] = [];
	export let lanePalettes: Map<string, LanePalette> | null = null;
	export let stages: StageSegment[] = [];
	export let memberFilter: string | null = null;
	export let stageFilter: string | null = null;
	export let viewMode: 'stream' | 'board' | 'conclusion' | 'changes' = 'stream';
	export let projectTeam = false;
	export let conclusionReady = false;
	export let deployStatus: string | null = null;
	export let counts: {
		done: number;
		running: number;
		waiting: number;
		attention: number;
		total: number;
	};
	export let startedAt: number | null = null;
	export let finishedAt: number | null = null;
	export let fallbacks = 0;

	const dispatch = createEventDispatcher<{
		member: string | null;
		inspectMember: string;
		stage: string | null;
		view: 'stream' | 'board' | 'conclusion' | 'changes';
	}>();

	$: percent = counts.total ? Math.round((counts.done / counts.total) * 100) : 0;
	$: took = startedAt ? (finishedAt ?? $now) - startedAt : null;
	$: totalWeight = stages.reduce((acc, s) => acc + s.weight, 0) || 1;

	const toggleMember = (id: string | null) => {
		dispatch('member', memberFilter === id ? null : id);
	};
	const toggleStage = (id: string | null) => {
		dispatch('stage', stageFilter === id ? null : id);
	};

	const VIEWS: { id: 'stream' | 'board' | 'conclusion' | 'changes'; label: string }[] = [
		{ id: 'stream', label: '泳道协作' },
		{ id: 'board', label: '依赖图' },
		{ id: 'conclusion', label: '结论' },
		{ id: 'changes', label: '变更' }
	];
</script>

<section
	class="filter-bar tm-card-quiet flex flex-col gap-2 px-3 py-2.5"
	aria-label="成员与阶段筛选"
	data-workbench-filter
>
	<!-- Row 1: Member pills + compact stats + desktop view mode switch -->
	<div class="flex flex-wrap items-center gap-2">
		<div
			class="tm-scroll flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto py-0.5"
			role="group"
			aria-label="按成员筛选"
		>
			<span class="shrink-0 text-[11px] font-medium text-gray-400 dark:text-gray-500">角色</span>
			<button
				type="button"
				class="pill {memberFilter === null ? 'is-active' : ''}"
				aria-pressed={memberFilter === null}
				on:click={() => dispatch('member', null)}
				data-filter-member="all"
			>
				全部
			</button>
			<button
				type="button"
				class="pill {memberFilter === LEAD_LANE_ID ? 'is-active' : ''}"
				aria-pressed={memberFilter === LEAD_LANE_ID}
				style="--pill-color:{lanePalette(LEAD_LANE_ID, 0).stroke}"
				on:click={() => toggleMember(LEAD_LANE_ID)}
				data-filter-member={LEAD_LANE_ID}
				title="只看负责人与团队里程碑"
			>
				<span
					class="lane-dot {toneOf(lead.status) === 'run' ? 'tm-pulse-dot' : ''}"
					aria-hidden="true"
				/>
				<span class="max-w-[7rem] truncate">{lead.name}</span>
			</button>
			{#each members as m, idx (m.name)}
				{@const pal = lanePalettes?.get(m.name) ?? lanePalette(m.name, idx + 1)}
				{@const working = toneOf(m.status) === 'run'}
				{@const bad = toneOf(m.status) === 'fail'}
				{@const waitingUser = toneOf(m.status) === 'user'}
				<div class="pill-wrap inline-flex shrink-0 items-center">
					<button
						type="button"
						class="pill {memberFilter === m.name ? 'is-active' : ''}"
						aria-pressed={memberFilter === m.name}
						style="--pill-color:{pal.stroke}"
						on:click={() => toggleMember(m.name)}
						data-filter-member={m.name}
						title="{m.role} · {runnerLabel(m.actualRunner ?? m.executor)}{m.currentKey
							? ` · 正在做 #${m.currentKey}`
							: ''}"
					>
						<span
							class="lane-dot {working ? 'tm-pulse-dot' : ''}"
							style="background:{bad
								? 'hsl(var(--tm-bad))'
								: waitingUser
									? 'hsl(var(--tm-violet))'
									: pal.stroke};color:{pal.stroke}"
							aria-hidden="true"
						/>
						<span class="max-w-[7.5rem] truncate"
							>{m.assistant?.emoji ? `${m.assistant.emoji} ` : ''}{m.name}</span
						>
						{#if m.currentKey}
							<span class="font-mono text-[10px] opacity-65">#{m.currentKey}</span>
						{/if}
					</button>
					<button
						type="button"
						class="inspect-dot"
						title="打开 {m.name} 详情与留言"
						aria-label="查看 {m.name} 详情"
						on:click={() => dispatch('inspectMember', m.name)}
						data-inspect-member={m.name}
					>
						<svg class="size-3" viewBox="0 0 16 16" fill="none" aria-hidden="true"
							><circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.3" /><path
								d="M8 7.4v3.2M8 5.2v.4"
								stroke="currentColor"
								stroke-width="1.4"
								stroke-linecap="round"
							/></svg
						>
					</button>
				</div>
			{/each}
		</div>

		<div class="ml-auto flex shrink-0 items-center gap-2.5">
			<div
				class="hidden items-center gap-2 text-xs text-gray-500 sm:flex dark:text-gray-400"
				data-compact-stats
			>
				<span class="tm-num font-semibold text-gray-900 dark:text-gray-100"
					>{counts.done}/{counts.total}</span
				>
				<span class="tm-num text-[11px] opacity-75">{percent}%</span>
				{#if took !== null}
					<span class="tm-num text-[11px] opacity-75">· {elapsed(took)}</span>
				{/if}
				{#if fallbacks > 0}
					<span class="text-[11px] text-amber-600 dark:text-amber-300">· 改派 {fallbacks}</span>
				{/if}
			</div>

			<div class="tm-segment hidden lg:inline-flex" role="tablist" aria-label="协作台工作区视图">
				{#each VIEWS.filter((v) => v.id !== 'changes' || projectTeam) as v (v.id)}
					<button
						type="button"
						role="tab"
						aria-selected={viewMode === v.id}
						class="relative !px-2.5 !py-1"
						on:click={() => dispatch('view', v.id)}
						data-view-tab={v.id}
					>
						{v.label}
						{#if v.id === 'conclusion' && conclusionReady && viewMode !== 'conclusion'}
							<span
								class="absolute right-1 top-1 size-1.5 rounded-full bg-[hsl(var(--tm-accent))]"
								aria-label="结论已就绪"
							/>
						{:else if v.id === 'changes' && viewMode !== 'changes' && (deployStatus === 'running' || deployStatus === 'failed')}
							<span
								class="absolute right-1 top-1 size-1.5 rounded-full {deployStatus === 'failed'
									? 'bg-red-500'
									: 'bg-sky-500'}"
								aria-label="部署状态"
							/>
						{/if}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<!-- Row 2: Colored stage progress ruler + clickable stage pills -->
	{#if stages.length > 0}
		<div class="flex flex-col gap-1.5 border-t pt-2 tm-hairline">
			<div
				class="ruler flex h-1.5 w-full gap-1 overflow-hidden rounded-full"
				aria-label="阶段进度条"
				data-stage-ruler
			>
				{#each stages as seg (seg.id)}
					{@const fillPct = seg.total ? Math.round((seg.done / seg.total) * 100) : 0}
					{@const active = stageFilter === null || stageFilter === seg.id}
					<button
						type="button"
						class="ruler-seg relative h-full overflow-hidden rounded-full transition-opacity {active
							? 'opacity-100'
							: 'opacity-30 hover:opacity-70'}"
						style="flex-grow:{seg.weight};--seg-color:{seg.color}"
						title="{seg.label}（{seg.done}/{seg.total}）"
						aria-label="筛选 {seg.label}"
						on:click={() => toggleStage(seg.id)}
					>
						<span
							class="block h-full rounded-full transition-all duration-500 {seg.status === 'running'
								? 'team-progress-live'
								: ''}"
							style="width:{seg.status === 'running'
								? Math.max(35, fillPct)
								: seg.status === 'done'
									? 100
									: Math.max(seg.status === 'attention' ? 60 : 0, fillPct)}%;background:{seg.status ===
							'attention'
								? 'hsl(var(--tm-bad))'
								: seg.color}"
						/>
					</button>
				{/each}
			</div>

			<div
				class="tm-scroll flex items-center gap-1.5 overflow-x-auto"
				role="group"
				aria-label="按阶段筛选"
			>
				<span class="shrink-0 text-[11px] font-medium text-gray-400 dark:text-gray-500">阶段</span>
				<button
					type="button"
					class="pill pill-sm {stageFilter === null ? 'is-active' : ''}"
					aria-pressed={stageFilter === null}
					on:click={() => dispatch('stage', null)}
					data-filter-stage="all"
				>
					全部阶段
				</button>
				{#each stages as seg (seg.id)}
					<button
						type="button"
						class="pill pill-sm {stageFilter === seg.id ? 'is-active' : ''}"
						aria-pressed={stageFilter === seg.id}
						style="--pill-color:{seg.color}"
						on:click={() => toggleStage(seg.id)}
						data-filter-stage={seg.id}
						title={seg.label}
					>
						<span
							class="lane-dot {seg.status === 'running' ? 'tm-pulse-dot' : ''}"
							style="background:{seg.status === 'attention'
								? 'hsl(var(--tm-bad))'
								: seg.color};color:{seg.color}"
							aria-hidden="true"
						/>
						<span class="max-w-[10rem] truncate">{seg.shortLabel}</span>
						<span class="tm-num text-[10px] opacity-65">{seg.done}/{seg.total}</span>
					</button>
				{/each}
			</div>
		</div>
	{/if}
</section>

<style>
	.pill {
		--pill-color: hsl(var(--tm-accent));
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
		border-radius: 9999px;
		padding: 0.22rem 0.6rem;
		font-size: 0.72rem;
		line-height: 1.2;
		color: hsl(var(--tm-muted));
		background: hsl(var(--tm-surface) / 0.72);
		border: 1px solid hsl(var(--tm-line));
		transition:
			border-color 0.16s ease,
			background 0.16s ease,
			color 0.16s ease,
			box-shadow 0.16s ease;
	}
	.pill-sm {
		padding: 0.18rem 0.52rem;
		font-size: 0.7rem;
	}
	.pill:hover {
		color: hsl(var(--tm-ink));
		border-color: hsl(var(--tm-line-strong));
		background: hsl(var(--tm-surface));
	}
	.pill.is-active {
		color: hsl(var(--tm-ink));
		font-weight: 600;
		border-color: color-mix(in srgb, var(--pill-color) 50%, transparent);
		background: color-mix(in srgb, var(--pill-color) 11%, hsl(var(--tm-surface)));
		box-shadow: 0 0 0 1px color-mix(in srgb, var(--pill-color) 18%, transparent);
	}
	.lane-dot {
		width: 0.42rem;
		height: 0.42rem;
		border-radius: 9999px;
		background: var(--pill-color);
		color: var(--pill-color);
		flex-shrink: 0;
	}
	.pill-wrap .inspect-dot {
		margin-left: -0.25rem;
		padding: 0.2rem;
		border-radius: 9999px;
		color: hsl(var(--tm-muted));
		opacity: 0.55;
		transition:
			opacity 0.15s ease,
			color 0.15s ease;
	}
	.pill-wrap:hover .inspect-dot,
	.pill-wrap .inspect-dot:focus-visible {
		opacity: 1;
		color: hsl(var(--tm-ink));
	}
	.ruler-seg {
		background: hsl(var(--tm-line));
		padding: 0;
		border: 0;
		cursor: pointer;
	}
</style>

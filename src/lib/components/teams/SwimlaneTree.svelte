<script lang="ts">
	import { createEventDispatcher, onDestroy, tick } from 'svelte';

	import {
		SWIMLANE_LEGEND,
		layoutSwimlanes,
		type NarrativeItem,
		type SwimlaneEdge,
		type SwimlaneLayout,
		type SwimlaneNode
	} from './narrative';

	/**
	 * Git-graph-style vertical swimlane execution tree.
	 * - Horizontal axis: Lead + each member lane with dedicated Starcore color rail
	 * - Vertical axis: evenly spaced narrative items (naturally grows live during ReplayBar playback)
	 * - Cross-lane Bézier arrows for handoffs, user/lead steers, fail→retry loops & deploy merges
	 * - Viewport-windowed SVG rendering when scroller actually overflows
	 */
	export let items: NarrativeItem[] = [];
	export let members: { name: string; role?: string }[] = [];
	export let leadName = '负责人';
	/** Optional precomputed layout (shared with parent so lane colors stay 100% consistent). */
	export let precomputedLayout: SwimlaneLayout | null = null;
	export let memberFilter: string | null = null;
	export let stageFilter: string | null = null;
	export let focusId: string | null = null;
	export let focusSource: 'feed' | 'swimlane' | null = null;
	export let focusPin = false;
	export let autoFollow = true;
	export let connectorEnabled = true;
	export let showConnectorToggle = true;

	const dispatch = createEventDispatcher<{
		focus: { id: string | null; source: 'swimlane'; pin?: boolean };
		selectTask: string;
		toggleMember: string | null;
		toggleFollow: boolean;
		toggleConnector: boolean;
		scroll: void;
	}>();

	let scroller: HTMLDivElement | null = null;
	let scrollTop = 0;
	let viewHeight = 520;
	let canScroll = false;
	let manualScrollUntil = 0;
	let rafHover: number | null = null;
	const uid = Math.random().toString(36).slice(2, 7);

	$: layout = precomputedLayout ?? layoutSwimlanes(items, members, { leadName });

	// Deduplicated colored arrow markers (avoids context-stroke issues on older browsers & dark mode).
	$: edgeColors = [...new Set(layout.edges.map((e) => e.color))];
	$: markerIdByColor = new Map(edgeColors.map((c, i) => [c, `tm-arr-${uid}-${i}`]));

	// Viewport windowing ONLY when the container actually overflows and scrolls.
	const BUFFER_ROWS = 18;
	$: windowing = canScroll && layout.nodes.length > 100;
	$: startRow = windowing
		? Math.max(0, Math.floor((scrollTop - layout.topPad) / layout.rowHeight) - BUFFER_ROWS)
		: 0;
	$: endRow = windowing
		? Math.min(
				layout.nodes.length - 1,
				Math.ceil((scrollTop + viewHeight - layout.topPad) / layout.rowHeight) + BUFFER_ROWS
			)
		: layout.nodes.length - 1;
	$: visibleNodes = layout.nodes.slice(startRow, endRow + 1);
	$: minVisibleY = layout.topPad + Math.max(0, startRow - 2) * layout.rowHeight;
	$: maxVisibleY = layout.topPad + (endRow + 2) * layout.rowHeight;
	$: visibleEdges = windowing
		? layout.edges.filter(
				(e) =>
					Math.max(e.fromY, e.toY) >= minVisibleY && Math.min(e.fromY, e.toY) <= maxVisibleY
			)
		: layout.edges;

	const syncMetrics = () => {
		if (!scroller) return;
		scrollTop = scroller.scrollTop;
		viewHeight = scroller.clientHeight || 520;
		canScroll = scroller.scrollHeight > scroller.clientHeight + 8;
	};

	// Auto-follow newest node as events arrive or during replay playback.
	let prevNodeCount = 0;
	$: if (layout.nodes.length !== prevNodeCount) {
		const grew = layout.nodes.length > prevNodeCount;
		prevNodeCount = layout.nodes.length;
		tick().then(() => {
			syncMetrics();
			if (grew && autoFollow && scroller && Date.now() > manualScrollUntil) {
				scroller.scrollTop = scroller.scrollHeight;
			}
		});
	}

	// Scroll focused node into view ONLY on explicit click from NarrativeFeed (no hover scroll war).
	$: if (focusId && focusSource === 'feed' && focusPin && scroller) {
		const targetNode = layout.nodes.find((n) => n.id === focusId);
		if (targetNode) {
			const top = scroller.scrollTop;
			const bottom = top + scroller.clientHeight;
			if (targetNode.y < top + 56 || targetNode.y > bottom - 40) {
				scroller.scrollTo({
					top: Math.max(0, targetNode.y - scroller.clientHeight * 0.45),
					behavior: 'smooth'
				});
			}
		}
	}

	const onScroll = () => {
		syncMetrics();
		dispatch('scroll');
	};
	const onManualMove = () => {
		manualScrollUntil = Date.now() + 2000;
	};

	const hoverNode = (id: string | null) => {
		if (typeof window === 'undefined') {
			dispatch('focus', { id, source: 'swimlane', pin: false });
			return;
		}
		if (rafHover !== null) cancelAnimationFrame(rafHover);
		rafHover = requestAnimationFrame(() => {
			rafHover = null;
			dispatch('focus', { id, source: 'swimlane', pin: false });
		});
	};

	onDestroy(() => {
		if (rafHover !== null && typeof cancelAnimationFrame === 'function')
			cancelAnimationFrame(rafHover);
	});

	const isNodeMuted = (n: SwimlaneNode): boolean => {
		if (stageFilter && n.stageId !== stageFilter) return true;
		if (memberFilter && n.laneId !== memberFilter) return true;
		return false;
	};

	const edgePath = (e: SwimlaneEdge): string => {
		if (e.kind === 'retry' && Math.abs(e.fromX - e.toX) < 2) {
			// Same-lane loopback arc on the left side of the rail.
			const bulge = Math.min(34, Math.max(20, (e.toY - e.fromY) * 0.25));
			return `M ${e.fromX} ${e.fromY} C ${e.fromX - bulge} ${e.fromY + 12}, ${e.toX - bulge} ${e.toY - 12}, ${e.toX} ${e.toY}`;
		}
		const dy = Math.max(18, Math.abs(e.toY - e.fromY) * 0.48);
		return `M ${e.fromX} ${e.fromY} C ${e.fromX} ${e.fromY + dy}, ${e.toX} ${e.toY - dy}, ${e.toX} ${e.toY}`;
	};
</script>

<div class="flex h-full min-h-0 flex-col" data-swimlane-tree>
	<!-- Header -->
	<div class="flex flex-wrap items-center gap-2 border-b px-3 py-2 tm-hairline">
		<div class="flex items-center gap-1.5">
			<span class="text-xs font-semibold text-gray-900 dark:text-gray-100">工作树 · 泳道</span>
			<span class="tm-num rounded-full bg-gray-500/10 px-1.5 py-px text-[10px] text-gray-500">
				{layout.nodes.length}
			</span>
		</div>
		<div class="ml-auto flex items-center gap-1">
			{#if showConnectorToggle}
				<button
					type="button"
					class="mini-toggle {connectorEnabled ? 'is-on' : ''}"
					aria-pressed={connectorEnabled}
					title="悬停时绘制中右联动引导线"
					on:click={() => dispatch('toggleConnector', !connectorEnabled)}
					data-connector-toggle
				>
					连线
				</button>
			{/if}
			<button
				type="button"
				class="mini-toggle {autoFollow ? 'is-on' : ''}"
				aria-pressed={autoFollow}
				title="有新节点时自动滚到最新位置"
				on:click={() => dispatch('toggleFollow', !autoFollow)}
				data-follow-toggle
			>
				自动跟随
			</button>
		</div>
	</div>

	<!-- Sticky lane headers + scrollable SVG canvas -->
	<div
		bind:this={scroller}
		on:scroll|passive={onScroll}
		on:wheel|passive={onManualMove}
		on:touchstart|passive={onManualMove}
		class="tm-scroll relative min-h-0 flex-1 overflow-auto"
		data-swimlane-scroll
	>
		<!-- Sticky column headers aligned 1:1 with lane x positions -->
		<div
			class="lane-headers sticky top-0 z-10 flex items-center border-b backdrop-blur-md tm-hairline"
			style="width:{layout.width}px"
		>
			{#each layout.lanes as lane (lane.id)}
				{@const selected = memberFilter === lane.id}
				<button
					type="button"
					class="lane-head absolute top-0 flex h-full -translate-x-1/2 flex-col items-center justify-center px-1 transition-opacity {memberFilter &&
					!selected
						? 'opacity-45 hover:opacity-85'
						: 'opacity-100'}"
					style="left:{lane.x}px;width:{layout.laneWidth - 6}px"
					title="{lane.name}（{lane.role}）· 点击筛选"
					on:click={() => dispatch('toggleMember', selected ? null : lane.id)}
					data-swimlane-lane={lane.id}
				>
					<span class="flex max-w-full items-center gap-1">
						<span
							class="size-2 shrink-0 rounded-full"
							style="background:{lane.palette.stroke}"
							aria-hidden="true"
						/>
						<span class="truncate text-[11px] font-semibold text-gray-800 dark:text-gray-100">
							{lane.name}
						</span>
					</span>
				</button>
			{/each}
		</div>

		{#if layout.nodes.length === 0}
			<div class="flex h-48 items-center justify-center text-xs text-gray-400">
				等待执行节点…
			</div>
		{:else}
			<svg
				class="block select-none"
				width={layout.width}
				height={layout.height}
				viewBox="0 0 {layout.width} {layout.height}"
				role="img"
				aria-label="多角色泳道执行树"
				data-swimlane-svg
			>
				<defs>
					{#each edgeColors as color (color)}
						<marker
							id={markerIdByColor.get(color)}
							viewBox="0 0 10 10"
							refX="8"
							refY="5"
							markerWidth="5.5"
							markerHeight="5.5"
							orient="auto-start-reverse"
						>
							<path d="M 1 1.5 L 8.5 5 L 1 8.5 z" fill={color} />
						</marker>
					{/each}
				</defs>

				<!-- Lane background tracks & active spans -->
				{#each layout.lanes as lane (lane.id)}
					{@const laneMuted = !!memberFilter && memberFilter !== lane.id}
					<line
						x1={lane.x}
						y1={8}
						x2={lane.x}
						y2={layout.height - 12}
						stroke={lane.palette.stroke}
						stroke-opacity={laneMuted ? 0.08 : 0.16}
						stroke-width="1.5"
						stroke-dasharray="3 5"
					/>
					{#if lane.firstRow !== null && lane.lastRow !== null && lane.lastRow > lane.firstRow}
						<line
							x1={lane.x}
							y1={layout.topPad + lane.firstRow * layout.rowHeight}
							x2={lane.x}
							y2={layout.topPad + lane.lastRow * layout.rowHeight}
							stroke={lane.palette.stroke}
							stroke-opacity={laneMuted ? 0.2 : 0.58}
							stroke-width="2"
							stroke-linecap="round"
						/>
					{/if}
				{/each}

				<!-- Cross-lane curves: handoffs, steers, fail→retry loops, merge convergence -->
				{#each visibleEdges as edge (edge.id)}
					{@const focusedEdge = focusId === edge.fromNodeId || focusId === edge.toNodeId}
					<g class="edge" style="color:{edge.color}" opacity={focusedEdge ? 1 : 0.72}>
						<path
							d={edgePath(edge)}
							fill="none"
							stroke={edge.color}
							stroke-width={focusedEdge ? 2.4 : 1.6}
							stroke-dasharray={edge.dashed ? '4 4' : undefined}
							stroke-linecap="round"
							marker-end="url(#{markerIdByColor.get(edge.color)})"
							class={focusedEdge ? 'edge-focused' : ''}
						/>
						{#if edge.compact && edge.label}
							<text
								x={(edge.fromX + edge.toX) / 2}
								y={edge.toY - 4}
								text-anchor="middle"
								class="edge-label"
								fill={edge.color}>{edge.label}</text
							>
						{/if}
					</g>
				{/each}

				<!-- Nodes -->
				{#each visibleNodes as node (node.id)}
					{@const focused = focusId === node.id}
					{@const muted = isNodeMuted(node)}
					{@const labelOnLeft = node.laneIndex === layout.lanes.length - 1 && layout.lanes.length > 1}
					<g
						class="node-group"
						class:is-focused={focused}
						opacity={muted && !focused ? 0.28 : 1}
						transform="translate({node.x}, {node.y})"
						data-swimlane-node={node.id}
						data-focus={focused ? 'true' : undefined}
						role="button"
						tabindex="0"
						aria-label="{node.label} {node.sublabel}"
						on:mouseenter={() => hoverNode(node.id)}
						on:mouseleave={() => hoverNode(null)}
						on:click={() => dispatch('focus', { id: node.id, source: 'swimlane', pin: true })}
						on:dblclick={() => node.taskId && dispatch('selectTask', node.taskId)}
						on:keydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								dispatch('focus', { id: node.id, source: 'swimlane', pin: true });
							}
						}}
					>
						{#if node.isHead || focused}
							<circle
								r={focused ? 12 : 11}
								fill={node.color}
								fill-opacity={focused ? 0.18 : 0.12}
								class={node.isHead ? 'head-ring' : ''}
							/>
						{/if}

						<!-- Node circle / semantic glyph -->
						{#if node.kind === 'tool_group'}
							<rect
								x="-6.5"
								y="-6.5"
								width="13"
								height="13"
								rx="3.5"
								class="node-bg"
								stroke={node.color}
								stroke-width={focused ? 2.4 : 1.7}
							/>
							<text
								y="3"
								text-anchor="middle"
								class="step-num"
								fill={node.color}>{Math.min(99, node.stepCount)}</text
							>
						{:else if node.kind === 'fail'}
							<circle r="7" fill={node.color} />
							<path
								d="M -2.6 -2.6 L 2.6 2.6 M 2.6 -2.6 L -2.6 2.6"
								stroke="white"
								stroke-width="1.6"
								stroke-linecap="round"
							/>
						{:else if node.kind === 'handoff'}
							<circle r="7" class="node-bg" stroke={node.color} stroke-width={focused ? 2.5 : 2} />
							<path
								d="M -2.5 0 H 2.5 M 0.5 -2.3 L 2.8 0 L 0.5 2.3"
								fill="none"
								stroke={node.color}
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							/>
						{:else if node.kind === 'approval'}
							<circle r="7.5" fill={node.color} />
							<text y="3.2" text-anchor="middle" class="glyph-txt" fill="white">?</text>
						{:else if node.kind === 'deploy'}
							<polygon
								points="0,-7.5 7.5,0 0,7.5 -7.5,0"
								fill={node.color}
							/>
						{:else if node.kind === 'retry'}
							<circle r="6.5" class="node-bg" stroke={node.color} stroke-width="2" />
							<circle r="2.2" fill={node.color} />
						{:else}
							<circle
								r={focused ? 6.5 : 5.5}
								fill={node.kind === 'milestone' ? node.color : undefined}
								class={node.kind === 'milestone' ? '' : 'node-bg'}
								stroke={node.color}
								stroke-width={focused ? 2.4 : 2}
							/>
						{/if}

						<!-- Compact inline node label -->
						<text
							x={labelOnLeft ? -12 : 12}
							y={node.sublabel ? -1 : 3.5}
							text-anchor={labelOnLeft ? 'end' : 'start'}
							class="node-label {focused ? 'is-bold' : ''}"
						>
							{node.label}
						</text>
						{#if node.sublabel}
							<text
								x={labelOnLeft ? -12 : 12}
								y="9.5"
								text-anchor={labelOnLeft ? 'end' : 'start'}
								class="node-sub"
							>
								{node.sublabel}
							</text>
						{/if}
					</g>
				{/each}
			</svg>
		{/if}
	</div>

	<!-- Static compact legend -->
	<div
		class="legend grid grid-cols-4 gap-x-2 gap-y-1 border-t px-3 py-2 text-[10.5px] text-gray-500 tm-hairline dark:text-gray-400"
		aria-label="泳道图例"
	>
		{#each SWIMLANE_LEGEND as item (item.kind)}
			<span class="flex min-w-0 items-center gap-1.5">
				<span
					class="size-2 shrink-0 rounded-full"
					style="background:{item.color}"
					aria-hidden="true"
				/>
				<span class="truncate">{item.label}</span>
			</span>
		{/each}
	</div>
</div>

<style>
	.lane-headers {
		height: 34px;
		background: hsl(var(--tm-surface) / 0.88);
	}
	.mini-toggle {
		border-radius: 0.45rem;
		padding: 0.14rem 0.45rem;
		font-size: 0.68rem;
		font-weight: 500;
		color: hsl(var(--tm-muted));
		border: 1px solid hsl(var(--tm-line));
		background: transparent;
		transition:
			background 0.15s ease,
			color 0.15s ease,
			border-color 0.15s ease;
	}
	.mini-toggle:hover {
		color: hsl(var(--tm-ink));
	}
	.mini-toggle.is-on {
		color: hsl(var(--tm-accent));
		border-color: hsl(var(--tm-accent) / 0.35);
		background: hsl(var(--tm-accent) / 0.08);
	}
	.node-group {
		cursor: pointer;
		outline: none;
	}
	.node-bg {
		fill: hsl(var(--tm-surface));
	}
	.node-label {
		font-size: 10.5px;
		fill: hsl(var(--tm-ink) / 0.84);
		font-family: var(--font-sans);
	}
	.node-label.is-bold {
		font-weight: 600;
		fill: hsl(var(--tm-ink));
	}
	.node-sub {
		font-size: 9px;
		fill: hsl(var(--tm-muted));
		font-family: var(--font-mono);
	}
	.step-num {
		font-size: 8.5px;
		font-weight: 700;
		font-family: var(--font-mono);
	}
	.glyph-txt {
		font-size: 9.5px;
		font-weight: 700;
	}
	.edge-label {
		font-size: 9px;
		font-family: var(--font-mono);
		font-weight: 600;
	}
	.head-ring {
		animation: tm-swim-pulse 2s ease-out infinite;
	}
	.edge-focused {
		filter: drop-shadow(0 0 3px currentColor);
	}
	@keyframes tm-swim-pulse {
		0% {
			opacity: 0.9;
		}
		70% {
			opacity: 0.25;
		}
		100% {
			opacity: 0.9;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.head-ring {
			animation: none;
		}
	}
</style>

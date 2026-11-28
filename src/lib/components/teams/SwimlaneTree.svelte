<script lang="ts">
	import { createEventDispatcher, onDestroy, tick } from 'svelte';
	import {
		formatDuration,
		runnerFamily,
		runnerLabel,
		toneOf,
		type RunnerFamily
	} from './model';

	import {
		SWIMLANE_HEADER_HEIGHT,
		SWIMLANE_LEGEND,
		connectedSwimlaneIds,
		fitSwimlaneLabel,
		layoutSwimlanes,
		swimlaneEdgeCurveEndY,
		swimlaneEdgePath,
		type NarrativeItem,
		type NarrativeKind,
		type StageSegment,
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
	export let activeLanes: Set<string> | string[] = [];
	export let stages: StageSegment[] = [];
	export let wide = false;
	export let showWideToggle = true;
	export let motion = true;
	/** The team is done: play the closing sequence once (rails sweep, merges light up, head bursts). */
	export let finished = false;
	/** Per lane: who runs it (runner name) and its status, for the lane header. */
	export let laneMeta: Map<string, { runner?: string | null; status?: string | null }> | null =
		null;

	const dispatch = createEventDispatcher<{
		focus: { id: string | null; source: 'swimlane'; pin?: boolean };
		selectTask: string;
		toggleMember: string | null;
		toggleFollow: boolean;
		toggleConnector: boolean;
		toggleWide: boolean;
		scroll: void;
	}>();

	let scroller: HTMLDivElement | null = null;
	let scrollTop = 0;
	let viewHeight = 520;
	let canScroll = false;
	let manualScrollUntil = 0;
	let rafHover: number | null = null;
	let legendKind: NarrativeKind | null = null;
	const uid = Math.random().toString(36).slice(2, 7);

	$: layout = precomputedLayout ?? layoutSwimlanes(items, members, { leadName, stages });
	$: active = new Set(activeLanes);
	$: connected = connectedSwimlaneIds(layout, focusId);
	$: spotlight = connected.nodeIds.size > 0;
	$: hudNode = layout.nodes.find((node) => node.id === focusId) ?? layout.nodes.at(-1);
	$: recentEdges = new Set(
		layout.edges
			.filter((edge) => edge.kind !== 'steer')
			.slice(-4)
			.map((edge) => edge.id)
	);

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
	$: visibleBands = windowing
		? layout.stageBands.filter((band) => band.endRow >= startRow && band.startRow <= endRow)
		: layout.stageBands;

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

	const pinNode = (id: string) => dispatch('focus', { id, source: 'swimlane', pin: true });
	const outsideLaneViewport = (el: HTMLElement, x: number) =>
		x < el.scrollLeft + 14 || x > el.scrollLeft + el.clientWidth - 14;
	const scrollToNode = (node: SwimlaneNode) => {
		if (!scroller) return;
		const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
		const viewport = scroller.clientWidth;
		scroller.scrollTo({
			top: Math.max(0, node.y - (scroller.clientHeight - SWIMLANE_HEADER_HEIGHT) * 0.45),
			left: outsideLaneViewport(scroller, node.x)
				? Math.max(0, node.x - viewport / 2)
				: scroller.scrollLeft,
			behavior: reduced ? 'auto' : 'smooth'
		});
	};

	const locateFocusedNode = (id: string, el: HTMLElement) => {
		const node = layout.nodes.find((entry) => entry.id === id);
		if (!node) return;
		const top = el.scrollTop + SWIMLANE_HEADER_HEIGHT;
		const bottom = el.scrollTop + el.clientHeight;
		const y = node.y + SWIMLANE_HEADER_HEIGHT;
		if (y < top + 16 || y > bottom - 24 || outsideLaneViewport(el, node.x)) {
			scrollToNode(node);
		}
	};
	// Depend on the explicit selection, so polling and playback don't pull the scroll position back.
	$: if (focusId && focusSource === 'feed' && focusPin && scroller) {
		locateFocusedNode(focusId, scroller);
	}

	const FAMILY_MARK: Record<RunnerFamily, string> = {
		claude: 'CL',
		codex: 'CX',
		gemini: 'AG',
		hermes: 'H',
		other: ''
	};
	$: finale = finished && motion;
	$: mergeOrder = new Map(
		layout.edges.filter((edge) => edge.kind === 'merge').map((edge, i) => [edge.id, i])
	);
	// The head bursts once the merges have lit up (or right after the rails sweep without merges).
	$: burstDelay = 0.55 + Math.max(mergeOrder.size, 1) * 0.18 + 0.5;

	// Gradient ids must be valid in url(#…); node ids may contain any character.
	const edgeGradientId = (index: number) => `tm-edge-${uid}-${index}`;
	// Skip the entrance pop while windowing, otherwise every scroll re-pops the rows coming into view.
	$: nodeEnter = motion && !windowing;
</script>

<div class="flex h-full min-h-0 flex-col" data-swimlane-tree>
	<div class="workbench-pane-head flex flex-wrap items-center gap-2 border-b px-3 py-2 tm-hairline">
		<div class="flex items-center gap-1.5">
			<svg class="tree-icon size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
				<path d="M3 4v8m0-6c0 4 10 0 10 4v2" stroke="currentColor" stroke-width="1.3" />
				<circle cx="3" cy="3" r="1.8" fill="currentColor" />
				<circle cx="3" cy="13" r="1.8" fill="currentColor" />
				<circle cx="13" cy="13" r="1.8" fill="currentColor" />
			</svg>
			<span class="text-xs font-semibold">工作树 · 泳道</span>
			<span class="count-chip tm-num" title="执行节点数">{layout.nodes.length}</span>
			{#if active.size}
				<span class="count-chip tm-num">{active.size} 运行中</span>
			{/if}
		</div>
		<div class="ml-auto flex flex-wrap items-center gap-1">
			{#if showWideToggle}
				<button
					type="button"
					class="mini-toggle hidden lg:inline-block"
					aria-pressed={wide}
					on:click={() => dispatch('toggleWide', !wide)}
					data-wide-toggle>{wide ? '标准' : '宽画布'}</button
				>
			{/if}
			{#if showConnectorToggle}
				<button
					type="button"
					class="mini-toggle"
					aria-pressed={connectorEnabled}
					title="绘制叙事流与泳道之间的定位连线"
					on:click={() => dispatch('toggleConnector', !connectorEnabled)}
					data-connector-toggle>连线</button
				>
			{/if}
			<button
				type="button"
				class="mini-toggle"
				aria-pressed={autoFollow}
				title="有新节点时自动滚到最新位置"
				on:click={() => dispatch('toggleFollow', !autoFollow)}
				data-follow-toggle>自动跟随</button
			>
		</div>
	</div>

	<div
		bind:this={scroller}
		on:scroll|passive={onScroll}
		on:wheel|passive={onManualMove}
		on:touchstart|passive={onManualMove}
		class="canvas tm-scroll relative min-h-0 flex-1 overflow-auto"
		data-swimlane-scroll
	>
		<div
			class="lane-headers sticky top-0 z-10 border-b tm-hairline"
			style="width:{layout.width}px;height:{SWIMLANE_HEADER_HEIGHT}px"
		>
			{#each layout.lanes as lane (lane.id)}
				{@const selected = memberFilter === lane.id}
				{@const meta = laneMeta?.get(lane.id)}
				{@const tone = meta?.status ? toneOf(meta.status) : 'idle'}
				{@const family = runnerFamily(meta?.runner)}
				<button
					type="button"
					class="lane-head absolute top-0 flex h-full -translate-x-1/2 flex-col items-center justify-center px-1"
					class:is-muted={memberFilter && !selected}
					aria-pressed={selected}
					style="left:{lane.x}px;width:{layout.laneWidth - 6}px;--lane-color:{lane.palette.stroke}"
					title="{lane.name}（{lane.role}）{meta?.runner
						? ` · 由 ${runnerLabel(meta.runner)} 执行`
						: ''} · {lane.nodeCount} 个节点 · 点击筛选"
					on:click={() => dispatch('toggleMember', selected ? null : lane.id)}
					data-swimlane-lane={lane.id}
					data-lane-active={active.has(lane.id) ? 'true' : undefined}
					data-lane-tone={tone}
				>
					<span class="flex max-w-full items-center gap-1.5">
						<span class="lane-status" data-tone={tone} aria-hidden="true" />
						<span class="truncate text-[11px] font-semibold">{lane.name}</span>
					</span>
					<span class="lane-count tm-num">
						{#if meta?.runner}
							<span class="runner-mark" data-family={family} data-lane-runner={meta.runner}
								>{FAMILY_MARK[family] || meta.runner.slice(0, 2).toUpperCase()}</span
							>
						{/if}
						{lane.nodeCount}
					</span>
				</button>
			{/each}
		</div>

		{#if !layout.nodes.length}
			<div class="flex h-48 items-center justify-center text-xs text-gray-500 dark:text-gray-400">
				等待执行节点…
			</div>
		{:else}
			<svg
				class="block select-none"
				width={layout.width}
				height={layout.height}
				viewBox="0 0 {layout.width} {layout.height}"
				role="group"
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
							orient="auto"
						>
							<path d="M1 1.5 8.5 5 1 8.5Z" fill={color} />
						</marker>
					{/each}
					{#each visibleEdges as edge, index (edge.id)}
						{#if edge.fromColor !== edge.color}
							<linearGradient
								id={edgeGradientId(index)}
								gradientUnits="userSpaceOnUse"
								x1={edge.fromX}
								y1={edge.fromY}
								x2={edge.toX}
								y2={edge.toY}
							>
								<stop offset="0.08" stop-color={edge.fromColor} />
								<stop offset="0.92" stop-color={edge.color} />
							</linearGradient>
						{/if}
					{/each}
					{#each layout.lanes as lane (lane.id)}
						<linearGradient id={`tm-lane-${uid}-${lane.index}`} x2="0" y2="1">
							<stop stop-color={lane.palette.stroke} stop-opacity="0.14" />
							<stop offset="1" stop-color={lane.palette.stroke} stop-opacity="0.035" />
						</linearGradient>
					{/each}
					<radialGradient id="tm-node-glow-{uid}">
						<stop stop-color="hsl(var(--tm-accent))" stop-opacity="0.38" />
						<stop offset="1" stop-color="hsl(var(--tm-accent))" stop-opacity="0" />
					</radialGradient>
					<linearGradient id="tm-stage-line-{uid}">
						<stop stop-color="white" stop-opacity="0.9" />
						<stop offset="1" stop-color="white" stop-opacity="0.2" />
					</linearGradient>
					<mask
						id="tm-stage-mask-{uid}"
						maskUnits="userSpaceOnUse"
						x="0"
						y="0"
						width={layout.width}
						height={layout.height}
					>
						<rect width={layout.width} height={layout.height} fill="url(#tm-stage-line-{uid})" />
					</mask>
				</defs>

				{#each visibleBands as band (band.id)}
					{@const label = fitSwimlaneLabel(band.label, layout.width - 28)}
					<g data-swimlane-stage-band={band.stageId} aria-hidden="true">
						<title>{band.label}</title>
						<rect
							y={band.topY}
							width={layout.width}
							height={band.bottomY - band.topY}
							fill={band.color}
							fill-opacity={band.startRow % 2 ? 0.065 : 0.038}
						/>
						<path
							d="M0 {band.topY}H{layout.width}"
							stroke={band.color}
							stroke-opacity="0.52"
							stroke-dasharray="3 4"
							mask="url(#tm-stage-mask-{uid})"
						/>
						{#if layout.rowHeight >= 44}
							<rect
								x="10"
								y={band.topY + 2}
								width={label.width + 10}
								height="14"
								rx="5"
								class="node-pill-bg"
								stroke={band.color}
								stroke-opacity="0.38"
							/>
							<text x="15" y={band.topY + 12} class="stage-label">{label.text}</text>
						{/if}
					</g>
				{/each}

				{#each layout.lanes as lane (lane.id)}
					{@const live = active.has(lane.id)}
					{@const muted = !!memberFilter && memberFilter !== lane.id}
					{#if live && !muted}
						<rect
							class="lane-glow"
							class:workbench-motion={motion}
							class:lane-breathe={motion}
							x={lane.x - layout.laneWidth * 0.26}
							width={layout.laneWidth * 0.52}
							height={layout.height}
							fill="url(#tm-lane-{uid}-{lane.index})"
						/>
					{/if}
					<path
						d="M{lane.x} 0V{layout.height - 12}"
						stroke={lane.palette.stroke}
						stroke-opacity={muted ? 0.08 : 0.26}
						stroke-dasharray="2 5"
					/>
					{#if lane.firstRow !== null && lane.lastRow !== null && lane.lastRow > lane.firstRow}
						{@const rail = `M${lane.x} ${layout.topPad + lane.firstRow * layout.rowHeight}V${layout.topPad + lane.lastRow * layout.rowHeight}`}
						<g stroke={lane.palette.stroke} stroke-linecap="round">
							<path d={rail} stroke-width="6" stroke-opacity={muted ? 0.04 : live ? 0.26 : 0.12} />
							<path d={rail} stroke-width="2.2" stroke-opacity={muted ? 0.2 : live ? 0.9 : 0.58} />
							{#if live && !muted && motion}
								<path
									d={rail}
									pathLength="100"
									stroke-width="3"
									stroke-dasharray="12 88"
									class="rail-scan workbench-motion"
								/>
							{/if}
							{#if finale}
								<path
									d={rail}
									pathLength="100"
									stroke-width="3.2"
									class="rail-finale workbench-motion"
									style="color:{lane.palette.stroke};animation-delay:{lane.index * 0.12}s"
									data-swimlane-finale="rail"
								/>
							{/if}
						</g>
					{/if}
				{/each}

				{#each visibleEdges as edge, index (edge.id)}
					{@const focusedEdge = connected.edgeIds.has(edge.id)}
					{@const path = swimlaneEdgePath(edge)}
					{@const stroke =
						edge.fromColor !== edge.color ? `url(#${edgeGradientId(index)})` : 'currentColor'}
					{@const label =
						edge.compact && edge.label ? fitSwimlaneLabel(edge.label, layout.laneWidth - 24) : null}
					<g
						class="edge"
						class:edge-focused={focusedEdge}
						style="color:{edge.color}"
						opacity={focusedEdge ? 1 : spotlight ? 0.18 : 0.78}
					>
						<path d={path} fill="none" {stroke} stroke-width="5.5" stroke-opacity="0.2" />
						<path
							d={path}
							fill="none"
							{stroke}
							stroke-width={focusedEdge ? 2.4 : 1.6}
							stroke-dasharray={edge.dashed ? '4 4' : undefined}
							stroke-linecap="round"
							marker-end="url(#{markerIdByColor.get(edge.color)})"
						/>
						{#if motion && !edge.dashed}
							<path
								d={path}
								pathLength="100"
								fill="none"
								class="edge-flow workbench-motion"
								stroke-dasharray="6 94"
								aria-hidden="true"
							/>
						{/if}
						{#if finale && mergeOrder.has(edge.id)}
							<path
								d={path}
								pathLength="100"
								fill="none"
								stroke="currentColor"
								class="edge-ignite workbench-motion"
								style="animation-delay:{0.55 + (mergeOrder.get(edge.id) ?? 0) * 0.18}s"
								aria-hidden="true"
								data-swimlane-finale="merge"
							/>
						{/if}
						{#if motion && (focusedEdge || recentEdges.has(edge.id))}
							<g class="workbench-motion-particle" aria-hidden="true">
								<circle r="5" fill="currentColor" opacity="0.32" />
								<circle r="2.3" fill="var(--tm-workbench-spark)" />
								<animateMotion {path} dur="1.8s" repeatCount="indefinite" />
							</g>
						{/if}
						{#if label?.text}
							<g
								transform="translate({(edge.fromX + edge.toX) / 2}, {swimlaneEdgeCurveEndY(edge) -
									9})"
							>
								<rect
									x={-label.width / 2 - 4}
									y="-7"
									width={label.width + 8}
									height="14"
									rx="5"
									class="node-pill-bg"
									stroke="currentColor"
									stroke-opacity="0.4"
								/>
								<text y="3" text-anchor="middle" class="stage-label">{label.text}</text>
							</g>
						{/if}
					</g>
				{/each}

				{#each visibleNodes as node (node.id)}
					{@const focused = focusId === node.id}
					{@const related = connected.nodeIds.has(node.id)}
					{@const muted =
						(stageFilter && node.stageId !== stageFilter) ||
						(memberFilter && node.laneId !== memberFilter)}
					{@const glyph = node.kind === 'runner' ? 'status' : node.kind}
					{@const labelOnLeft =
						node.laneIndex === layout.lanes.length - 1 && layout.lanes.length > 1}
					{@const name = fitSwimlaneLabel(node.label, layout.laneWidth - 34)}
					{@const sub = fitSwimlaneLabel(node.sublabel, layout.laneWidth - 34)}
					{@const labelWidth = Math.max(name.width, sub.width) + 10}
					<g
						class="node-group"
						class:is-focused={focused}
						opacity={related
							? 1
							: spotlight
								? 0.26
								: muted
									? 0.28
									: legendKind && legendKind !== glyph
										? 0.56
										: 1}
						style="color:{node.color}"
						transform="translate({node.x}, {node.y})"
						data-swimlane-node={node.id}
						data-focus={focused ? 'true' : undefined}
						role="button"
						tabindex="0"
						aria-label="{node.fullTitle} {node.sublabel}"
						aria-pressed={focused && focusPin}
						on:mouseenter={() => hoverNode(node.id)}
						on:mouseleave={() => hoverNode(null)}
						on:focus={() => hoverNode(node.id)}
						on:blur={() => hoverNode(null)}
						on:click={() => pinNode(node.id)}
						on:dblclick={() => node.taskId && dispatch('selectTask', node.taskId)}
						on:keydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								pinNode(node.id);
							}
						}}
					>
						{#if node.isHead || related}
							<circle r="18" fill="url(#tm-node-glow-{uid})" class="node-halo" />
						{/if}
						{#if node.isHead && !finished}
							<circle r="12" class="head-radar head-radar-1 workbench-motion" />
							<circle r="15" class="head-radar head-radar-2 workbench-motion" />
						{:else if node.isHead && finale}
							{#each [0, 1, 2] as ring}
								<circle
									r="10"
									class="finale-burst workbench-motion"
									style="animation-delay:{burstDelay + ring * 0.22}s"
									data-swimlane-finale={ring === 0 ? 'burst' : undefined}
								/>
							{/each}
						{/if}
						<circle data-swimlane-anchor r="9" fill="transparent" />
						<g class="node-glyph" class:node-enter={nodeEnter}>
							<use href="#tm-glyph-{uid}-{glyph}" />
							{#if node.isHead && node.kind !== 'tool_group'}
								<circle cx="0" cy="-5.5" r="1.35" fill="var(--tm-workbench-spark)" />
							{/if}
							{#if node.kind === 'tool_group'}
								<text y="3.1" text-anchor="middle" class="glyph-text count-text"
									>{Math.min(99, node.stepCount)}</text
								>
							{/if}
						</g>

						{#if name.text || sub.text}
							<svg
								x={labelOnLeft ? -14 - labelWidth : 14}
								y={sub.text ? -10 : -8}
								width={labelWidth}
								height={sub.text ? 24 : 16}
								aria-hidden="true"
							>
								<rect
									x="0.5"
									y="0.5"
									width={labelWidth - 1}
									height={sub.text ? 23 : 15}
									rx="5"
									class="node-pill-bg"
									stroke="currentColor"
									stroke-opacity={focused ? 0.72 : 0.24}
								/>
								<text x="5" y={sub.text ? 10 : 11.5} class="node-label">{name.text}</text>
								{#if sub.text}<text x="5" y="20" class="node-sub">{sub.text}</text>{/if}
							</svg>
						{/if}
					</g>
				{/each}
			</svg>
		{/if}
	</div>

	{#if hudNode}
		{@const node = hudNode}
		<div
			class="hud border-t px-3 py-2 tm-hairline"
			data-swimlane-hud
			style="--hud-color:{node.color}"
		>
			<div class="hud-info">
				<div class="flex min-w-0 items-center gap-1.5 text-xs">
					<span class="hud-badge shrink-0">{node.badge}</span>
					<strong class="min-w-0 break-words">{node.fullTitle}</strong>
				</div>
				<div class="hud-meta tm-num">
					{node.memberName}{node.taskKey ? ` · #${node.taskKey}` : ''}
					{node.kind === 'tool_group' ? ` · ${node.stepCount} 步` : ''}
					{node.durationSec > 0 ? ` · ${formatDuration(node.durationSec)}` : ''}
					{#each node.files as file (file)}
						<span class="hud-file">{file}</span>
					{/each}
				</div>
			</div>
			<div class="flex shrink-0 gap-1">
				<button
					type="button"
					class="mini-toggle"
					on:click={() => {
						scrollToNode(node);
						pinNode(node.id);
					}}
				>
					定位
				</button>
				{#if node.taskId}
					<button
						type="button"
						class="mini-toggle"
						title="双击节点也可打开详情"
						on:click={() => node.taskId && dispatch('selectTask', node.taskId)}>详情</button
					>
				{/if}
			</div>
		</div>
	{/if}

	<div
		class="legend flex flex-wrap gap-x-3 gap-y-1 border-t px-3 py-2 tm-hairline"
		aria-label="泳道图例"
	>
		{#each SWIMLANE_LEGEND as item (item.kind)}
			<span
				class="flex min-w-0 items-center gap-1"
				on:mouseenter={() => (legendKind = item.kind)}
				on:mouseleave={() => (legendKind = null)}
			>
				<svg
					class="shrink-0"
					width="14"
					height="14"
					viewBox="-10 -10 20 20"
					style="color:{item.color}"
					aria-hidden="true"
				>
					<use href="#tm-glyph-{uid}-{item.kind}" />
				</svg>
				{item.label}
			</span>
		{/each}
	</div>

	<svg class="absolute size-0 overflow-hidden" aria-hidden="true">
		<defs>
			{#each SWIMLANE_LEGEND as item (item.kind)}
				<g id="tm-glyph-{uid}-{item.kind}" stroke="currentColor" stroke-width="1.6">
					{#if item.kind === 'tool_group'}
						<rect x="-7.5" y="-7.5" width="15" height="15" rx="3.7" class="node-pill-bg" />
					{:else if item.kind === 'handoff' || item.kind === 'message'}
						<circle r="8" class="node-pill-bg" />
						{#if item.kind === 'handoff'}
							<path
								d="M-4 0H4M1-3l3 3-3 3"
								fill="none"
								stroke-linecap="round"
								stroke-linejoin="round"
							/>
						{:else}
							<path d="M-3.5-2h7v4H0L-2 3.5V2h-1.5Z" fill="none" stroke-linejoin="round" />
						{/if}
					{:else if item.kind === 'approval' || item.kind === 'fail'}
						<circle r="8" fill="currentColor" />
						{#if item.kind === 'approval'}
							<text y="3.5" text-anchor="middle" class="glyph-text" fill="white" stroke="none"
								>?</text
							>
						{:else}
							<path d="M-3-3 3 3M3-3-3 3" stroke="white" stroke-linecap="round" />
						{/if}
					{:else if item.kind === 'milestone' || item.kind === 'deploy'}
						<path
							d="M0-8 8 0 0 8-8 0Z"
							class:node-pill-bg={item.kind === 'milestone'}
							fill={item.kind === 'deploy' ? 'currentColor' : undefined}
						/>
						{#if item.kind === 'deploy'}<path d="m-3 0 2 2 4-4" stroke="white" fill="none" />{/if}
					{:else}
						<circle r="7" class="node-pill-bg" />
						<circle r={item.kind === 'retry' ? 2.4 : 1.6} fill="currentColor" stroke="none" />
					{/if}
				</g>
			{/each}
		</defs>
	</svg>
</div>

<style>
	.canvas {
		background:
			radial-gradient(circle at center, var(--tm-workbench-grid) 0.75px, transparent 1px) 0 0 / 16px
				16px,
			radial-gradient(ellipse at top, var(--tm-workbench-glow), transparent 58%),
			var(--tm-workbench-canvas);
	}
	.tree-icon {
		color: hsl(var(--tm-accent));
	}
	.count-chip,
	.hud-badge {
		border-radius: 5px;
		padding: 1px 5px;
		font-size: 10px;
		font-weight: 650;
		background: hsl(var(--tm-accent) / 0.09);
		color: hsl(var(--tm-accent));
	}
	.mini-toggle {
		border-radius: 0.45rem;
		padding: 0.14rem 0.45rem;
		font-size: 0.68rem;
		color: hsl(var(--tm-muted));
		border: 1px solid hsl(var(--tm-line-strong));
		transition:
			background 160ms ease,
			color 160ms ease;
	}
	.mini-toggle:hover,
	.mini-toggle:focus-visible {
		color: hsl(var(--tm-ink));
		background: hsl(var(--tm-accent) / 0.1);
	}
	.mini-toggle[aria-pressed='true'] {
		color: hsl(var(--tm-accent));
		border-color: hsl(var(--tm-accent) / 0.36);
		background: hsl(var(--tm-accent) / 0.08);
	}
	.lane-headers {
		background: var(--tm-workbench-pill);
	}
	.lane-head {
		border-bottom: 2px solid transparent;
		color: hsl(var(--tm-ink));
	}
	.lane-head.is-muted {
		opacity: 0.58;
	}
	.lane-head:hover,
	.lane-head:focus-visible {
		opacity: 1;
	}
	.lane-head[aria-pressed='true'],
	.lane-head[data-lane-active] {
		border-bottom-color: var(--lane-color);
		background: linear-gradient(
			0deg,
			color-mix(in srgb, var(--lane-color) 14%, transparent),
			transparent 72%
		);
	}
	.lane-count {
		font-size: 10px;
		line-height: 1;
		color: hsl(var(--tm-muted));
	}
	.lane-status {
		position: relative;
		width: 7px;
		height: 7px;
		flex: none;
		border-radius: 50%;
		background: var(--lane-color);
	}
	.lane-head[data-lane-active] {
		box-shadow: inset 0 -12px 18px -14px var(--lane-color);
	}
	/* Status ring around the lane dot: spinning while it works, violet when it needs you, red when
	   it failed, amber dashes while it waits, a quiet green ring when done. */
	.lane-status::after {
		content: '';
		position: absolute;
		inset: -3.5px;
		border-radius: 50%;
		border: 1.5px solid transparent;
		animation-play-state: var(--tm-workbench-play-state, running);
	}
	.lane-status[data-tone='run']::after {
		border-color: var(--lane-color) transparent var(--lane-color) transparent;
		animation: tm-lane-spin 1.1s linear infinite;
	}
	.lane-status[data-tone='user']::after {
		border-color: hsl(var(--tm-violet));
		animation: tm-radar 2s ease-out infinite;
	}
	.lane-status[data-tone='fail']::after {
		border-color: hsl(var(--tm-bad));
	}
	.lane-status[data-tone='done']::after {
		border-color: hsl(var(--tm-ok) / 0.75);
	}
	.lane-status:is([data-tone='wait'], [data-tone='deps'], [data-tone='quota'])::after {
		border: 1.5px dashed hsl(var(--tm-warn) / 0.8);
	}
	@keyframes tm-lane-spin {
		to {
			transform: rotate(360deg);
		}
	}
	.lane-count {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.runner-mark {
		--mark: hsl(var(--tm-muted));
		border-radius: 4px;
		padding: 0 3px;
		font: 700 8.5px/12px var(--font-mono);
		letter-spacing: 0.02em;
		color: var(--mark);
		background: color-mix(in srgb, var(--mark) 16%, transparent);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--mark) 38%, transparent);
	}
	.runner-mark[data-family='claude'] {
		--mark: #e8875b;
	}
	.runner-mark[data-family='codex'] {
		--mark: #34d399;
	}
	.runner-mark[data-family='gemini'] {
		--mark: #6ea8ff;
	}
	.runner-mark[data-family='hermes'] {
		--mark: hsl(var(--tm-violet));
	}
	.lane-breathe {
		animation: tm-lane-breathe 3.2s ease-in-out infinite alternate;
	}
	@keyframes tm-lane-breathe {
		from {
			opacity: 0.55;
		}
		to {
			opacity: 1;
		}
	}
	/* Closing sequence, played once when the team finishes. */
	.rail-finale {
		fill: none;
		stroke-dasharray: 0 100;
		filter: drop-shadow(0 0 3px currentColor);
		animation: tm-rail-finale 1.5s cubic-bezier(0.3, 0.7, 0.2, 1) both;
	}
	@keyframes tm-rail-finale {
		0% {
			stroke-dasharray: 0 100;
			opacity: 0.95;
		}
		70% {
			stroke-dasharray: 100 0;
			opacity: 0.95;
		}
		100% {
			stroke-dasharray: 100 0;
			opacity: 0;
		}
	}
	.edge-ignite {
		stroke-width: 2.8px;
		stroke-linecap: round;
		stroke-dasharray: 100;
		filter: drop-shadow(0 0 4px currentColor);
		animation: tm-edge-ignite 0.9s cubic-bezier(0.3, 0.7, 0.2, 1) both;
	}
	@keyframes tm-edge-ignite {
		from {
			stroke-dashoffset: 100;
			opacity: 1;
		}
		to {
			stroke-dashoffset: 0;
			opacity: 0.6;
		}
	}
	.finale-burst {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.6px;
		transform-box: fill-box;
		transform-origin: center;
		animation: tm-finale-burst 1.3s cubic-bezier(0.2, 0.8, 0.3, 1) both;
	}
	@keyframes tm-finale-burst {
		from {
			opacity: 0.95;
			transform: scale(0.6);
		}
		to {
			opacity: 0;
			transform: scale(3.2);
		}
	}
	.rail-scan {
		animation: tm-rail-scan 3.8s linear infinite;
	}
	@keyframes tm-rail-scan {
		to {
			stroke-dashoffset: -100;
		}
	}
	.node-group {
		cursor: pointer;
		outline: none;
	}
	.node-group,
	.edge {
		transition: opacity var(--dur-micro, 160ms) ease;
	}
	.node-group:focus-visible [data-swimlane-anchor] {
		stroke: currentColor;
		stroke-width: 2px;
	}
	.node-group.is-focused .node-label {
		font-weight: 650;
	}
	.edge-focused {
		filter: drop-shadow(0 0 2px currentColor);
	}
	/* A short bright comet travelling each solid edge: idle edges look alive without extra DOM nodes. */
	.edge-flow {
		stroke: var(--tm-workbench-spark);
		stroke-width: 1.6px;
		stroke-linecap: round;
		opacity: 0.55;
		animation: tm-edge-flow 3.6s linear infinite;
	}
	.edge-focused .edge-flow {
		opacity: 0.95;
		animation-duration: 2.2s;
	}
	@keyframes tm-edge-flow {
		from {
			stroke-dashoffset: 100;
		}
		to {
			stroke-dashoffset: 0;
		}
	}
	.node-enter {
		transform-box: fill-box;
		transform-origin: center;
		animation: tm-node-in 460ms cubic-bezier(0.2, 1.5, 0.4, 1) both;
	}
	@keyframes tm-node-in {
		from {
			opacity: 0;
			transform: scale(0.2);
		}
	}
	.head-radar {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.1px;
		opacity: 0.55;
		transform-box: fill-box;
		transform-origin: center;
		animation: tm-radar 2.4s ease-out infinite;
	}
	.head-radar-2 {
		animation-delay: -1.2s;
	}
	@keyframes tm-radar {
		from {
			opacity: 0.85;
			transform: scale(0.8);
		}
		to {
			opacity: 0;
			transform: scale(1.45);
		}
	}
	.node-pill-bg {
		fill: var(--tm-workbench-pill);
	}
	.node-label,
	.node-sub,
	.stage-label {
		font-family: var(--font-mono);
		fill: hsl(var(--tm-ink));
	}
	.node-label {
		font-size: 10.5px;
	}
	.stage-label {
		font-size: 9.5px;
		font-weight: 650;
	}
	.node-sub {
		font-size: 8.5px;
		fill: hsl(var(--tm-muted));
	}
	.glyph-text {
		font: 700 10px var(--font-mono);
	}
	.count-text {
		fill: hsl(var(--tm-ink));
		font-size: 8.5px;
	}
	.hud {
		display: flex;
		min-height: 3.65rem;
		align-items: center;
		gap: 0.5rem;
		background: linear-gradient(
			90deg,
			color-mix(in srgb, var(--hud-color) 9%, transparent),
			transparent 82%
		);
	}
	.hud-info {
		flex: 1;
		min-width: 0;
		max-height: 2.65rem;
		overflow: auto;
		scrollbar-width: thin;
	}
	.hud-badge {
		color: hsl(var(--tm-ink));
		background: color-mix(in srgb, var(--hud-color) 20%, var(--tm-workbench-pill));
	}
	.hud-meta,
	.legend {
		font-size: 10px;
		color: hsl(var(--tm-muted));
	}
	.hud-file {
		display: inline-block;
		margin-inline-start: 0.25rem;
		overflow-wrap: anywhere;
		font-family: var(--font-mono);
	}
	@media (prefers-reduced-motion: reduce), (max-width: 767px) {
		.edge-focused {
			filter: none;
		}
		.edge-flow,
		.rail-finale,
		.edge-ignite,
		.finale-burst {
			display: none;
		}
		.lane-status::after {
			animation: none;
		}
		.node-enter {
			animation: none;
		}
	}
</style>

<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { writable } from 'svelte/store';
	import { Background, BackgroundVariant, Controls, MarkerType, SvelteFlow } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';

	import { theme } from '$lib/stores';
	import BoardCamera from './BoardCamera.svelte';
	import { prefersReducedMotion } from '$lib/utils/transitions';
	import FlowEdge from './FlowEdge.svelte';
	import TaskNode from './TaskNode.svelte';
	import {
		avatarKind,
		boardDirection,
		layoutTasks,
		openParents,
		statusLabel,
		taskRunner,
		toneOf,
		type TaskState
	} from './model';
	import { TONE_STROKE } from './tones';

	/** The shared task board: one lane per dependency depth, edges coloured by the parent's state. */
	export let tasks: {
		id: string;
		key: string;
		seq: number;
		title: string;
		member: string;
		executor: string;
		model?: string;
		chosen?: string;
		chosen_by?: string;
		trail?: { from: string; to: string | null; reason: string }[];
		parents: string[];
		attempts?: number;
		started_at?: number | null;
		completed_at?: number | null;
	}[] = [];
	export let states: Map<string, TaskState> = new Map();
	export let members: { name: string; role: string }[] = [];
	export let selectedTaskId: string | null = null;
	/** In a replay the timers would lie: hide them. */
	export let replay = false;
	export let replayTaskId: string | null = null;
	let cameraCancel = 0;

	const dispatch = createEventDispatcher();
	const nodes = writable([]);
	const edges = writable([]);
	const nodeTypes = { task: TaskNode };
	const edgeTypes = { flow: FlowEdge };

	// Long chains on a narrow board read better top to bottom than shrunk left to right.
	const MAX_HEIGHT = 640;
	let boxWidth = 0;
	$: direction = boardDirection(tasks, boxWidth - 24, MAX_HEIGHT);
	$: layout = layoutTasks(tasks, direction);
	$: height = Math.min(direction === 'TB' ? MAX_HEIGHT : 580, Math.max(280, layout.height + 48));
	$: byKey = new Map(tasks.map((t) => [t.id, t.key]));
	$: roles = new Map(members.map((m) => [m.name, m]));
	$: dark = colorMode === 'dark';

	$: {
		nodes.set(
			tasks.map((t) => {
				const pos = layout.positions.get(t.id);
				const state = states.get(t.id) ?? { status: 'pending', sub_status: 'pending' };
				const waiting =
					state.sub_status === 'waiting_deps'
						? openParents(t, states).map((p) => byKey.get(p) ?? p)
						: [];
				return {
					id: t.id,
					type: 'task',
					position: { x: pos?.x ?? 0, y: pos?.y ?? 0 },
					draggable: false,
					connectable: false,
					selectable: false,
					data: {
						id: t.id,
						key: t.key,
						title: t.title,
						member: t.member,
						executor: t.executor,
						model: t.model ?? '',
						runner: taskRunner(t),
						attempts: t.attempts ?? 0,
						sub_status: state.sub_status,
						statusText: statusLabel(state.sub_status),
						waitingFor: waiting,
						direction,
						startedAt: replay ? null : (t.started_at ?? null),
						completedAt: replay || state.status !== 'done' ? null : (t.completed_at ?? null),
						avatar: avatarKind(roles.get(t.member) ?? { name: t.member }),
						selected: t.id === selectedTaskId,
						onSelect: (id: string) => dispatch('select', id)
					}
				};
			})
		);
		edges.set(
			tasks.flatMap((t) =>
				t.parents.map((p) => {
					const parent = states.get(p)?.sub_status ?? 'pending';
					const done = parent === 'done';
					const running = toneOf(parent) === 'run';
					const color = done
						? TONE_STROKE.done
						: running
							? TONE_STROKE.run
							: dark
								? '#475569'
								: TONE_STROKE.idle;
					return {
						id: `${p}->${t.id}`,
						source: p,
						target: t.id,
						type: 'flow',
						data: {
							state: done ? 'done' : running ? 'run' : 'wait',
							color,
							selected: p === selectedTaskId || t.id === selectedTaskId
						},
						markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 }
					};
				})
			)
		);
	}

	$: colorMode = $theme?.includes('dark')
		? 'dark'
		: $theme === 'system' &&
			  typeof window !== 'undefined' &&
			  window.matchMedia('(prefers-color-scheme: dark)').matches
			? 'dark'
			: 'light';
</script>

<div
	class="board tm-card relative w-full overflow-hidden"
	style="height:{height}px"
	bind:clientWidth={boxWidth}
	on:pointerdown={() => cameraCancel++}
	on:wheel={() => cameraCancel++}
	data-team-board
	data-direction={direction}
>
	{#key direction}
		<SvelteFlow
			{nodes}
			{edges}
			{nodeTypes}
			{edgeTypes}
			fitView
			fitViewOptions={{ padding: 0.06, maxZoom: 1, duration: prefersReducedMotion() ? 0 : 560 }}
			minZoom={0.3}
			maxZoom={1.5}
			nodesDraggable={false}
			nodesConnectable={false}
			elementsSelectable={false}
			proOptions={{ hideAttribution: true }}
			{colorMode}
			on:paneclick={() => dispatch('select', null)}
		>
			<BoardCamera
				target={selectedTaskId ?? (replay ? replayTaskId : null)}
				width={boxWidth}
				{height}
				cancel={cameraCancel}
			/>
			<Controls showLock={false} />
			<Background
				variant={BackgroundVariant.Dots}
				gap={20}
				size={1.2}
				bgColor="transparent"
				patternColor={dark ? 'rgba(148,163,184,0.16)' : 'rgba(15,23,42,0.13)'}
			/>
		</SvelteFlow>
	{/key}
	<div class="vignette pointer-events-none absolute inset-0" aria-hidden="true" />
</div>

<style>
	.board {
		background: radial-gradient(80% 60% at 50% 0%, hsl(var(--tm-accent) / 0.05), transparent 70%),
			hsl(var(--tm-surface-2));
	}
	.vignette {
		border-radius: inherit;
		box-shadow: inset 0 0 60px -20px hsl(var(--tm-surface-2));
	}
	.board :global(.svelte-flow) {
		background: transparent;
	}
	.board :global(.svelte-flow__controls) {
		border-radius: 0.8rem;
		overflow: hidden;
		border: 1px solid hsl(var(--tm-line));
		box-shadow: var(--tm-shadow);
		background: hsl(var(--tm-surface) / 0.8);
		backdrop-filter: blur(10px);
	}
	.board :global(.svelte-flow__controls-button) {
		background: transparent;
		border-bottom: 1px solid hsl(var(--tm-line));
		color: hsl(var(--tm-muted));
		width: 28px;
		height: 28px;
	}
	.board :global(.svelte-flow__controls-button:hover) {
		background: hsl(var(--tm-line));
		color: hsl(var(--tm-ink));
	}
	.board :global(.svelte-flow__controls-button svg) {
		fill: currentColor;
	}
	.board :global(.tm-edge-run) {
		stroke-dasharray: 6 6;
		animation: tm-edge-flow 0.9s linear infinite;
	}
	.board :global(.tm-edge-wait) {
		stroke-dasharray: 4 6;
		opacity: 0.8;
	}
	.board :global(.tm-edge-done) {
		opacity: 0.75;
	}
	@keyframes -global-tm-edge-flow {
		to {
			stroke-dashoffset: -24;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.board :global(.tm-edge-run) {
			animation: none;
		}
		.board :global(.tm-edge-pulse) {
			display: none;
		}
	}
</style>

<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { writable } from 'svelte/store';
	import { Background, BackgroundVariant, Controls, MarkerType, SvelteFlow } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';

	import { theme } from '$lib/stores';
	import TaskNode from './TaskNode.svelte';
	import {
		avatarKind,
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
		chosen?: string;
		chosen_by?: string;
		trail?: { from: string; to: string | null; reason: string }[];
		parents: string[];
		attempts?: number;
	}[] = [];
	export let states: Map<string, TaskState> = new Map();
	export let members: { name: string; role: string }[] = [];
	export let selectedTaskId: string | null = null;

	const dispatch = createEventDispatcher();
	const nodes = writable([]);
	const edges = writable([]);
	const nodeTypes = { task: TaskNode };

	$: layout = layoutTasks(tasks);
	$: height = Math.min(560, Math.max(260, layout.height + 40));
	$: byKey = new Map(tasks.map((t) => [t.id, t.key]));
	$: roles = new Map(members.map((m) => [m.name, m]));

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
						runner: taskRunner(t),
						attempts: t.attempts ?? 0,
						sub_status: state.sub_status,
						statusText: statusLabel(state.sub_status),
						waitingFor: waiting,
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
					const color = done ? TONE_STROKE.done : running ? TONE_STROKE.run : TONE_STROKE.idle;
					return {
						id: `${p}->${t.id}`,
						source: p,
						target: t.id,
						type: 'smoothstep',
						animated: running,
						style: `stroke:${color};stroke-width:2;${done ? '' : 'stroke-dasharray:6 5;'}`,
						markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 }
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
	class="w-full rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden"
	style="height:{height}px"
	data-team-board
>
	<SvelteFlow
		{nodes}
		{edges}
		{nodeTypes}
		fitView
		fitViewOptions={{ padding: 0.12, maxZoom: 1 }}
		minZoom={0.3}
		maxZoom={1.5}
		nodesDraggable={false}
		nodesConnectable={false}
		elementsSelectable={false}
		proOptions={{ hideAttribution: true }}
		{colorMode}
		on:paneclick={() => dispatch('select', null)}
	>
		<Controls showLock={false} />
		<Background variant={BackgroundVariant.Dots} />
	</SvelteFlow>
</div>

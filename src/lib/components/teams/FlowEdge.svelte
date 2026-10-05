<script lang="ts">
	import { BaseEdge, getBezierPath, type Position } from '@xyflow/svelte';

	/**
	 * A dependency on the board. Done: a solid line. The parent still working: a dashed line
	 * with a pulse travelling along it towards the waiting task. Not started: faint and dashed.
	 */
	export let id: string;
	export let sourceX: number;
	export let sourceY: number;
	export let targetX: number;
	export let targetY: number;
	export let sourcePosition: Position;
	export let targetPosition: Position;
	export let markerEnd: string | undefined = undefined;
	export let data: { state?: 'done' | 'run' | 'wait'; color?: string; selected?: boolean } = {};

	$: [path] = getBezierPath({
		sourceX,
		sourceY,
		targetX,
		targetY,
		sourcePosition,
		targetPosition
	});
	$: state = data?.state ?? 'wait';
	$: color = data?.color ?? '#94a3b8';
</script>

<BaseEdge
	{id}
	{path}
	{markerEnd}
	class="tm-edge tm-edge-{state}"
	style="stroke:{color};stroke-width:{state === 'wait' ? 1.5 : 2};"
/>
{#if state === 'run'}
	<circle r="7" fill={color} opacity="0.18" class="tm-edge-pulse">
		<animateMotion dur="1.6s" repeatCount="indefinite" {path} />
	</circle>
	<circle r="3" fill={color} class="tm-edge-pulse">
		<animateMotion dur="1.6s" repeatCount="indefinite" {path} />
	</circle>
{/if}
{#if data.selected}
	<path d={path} fill="none" stroke={color} stroke-width="7" opacity="0.12" class="tm-edge-glow" />
{/if}

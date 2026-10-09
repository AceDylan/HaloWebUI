<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import { isDarkMode } from '$lib/utils/dark-mode';
	import { Background, Controls, SvelteFlow, BackgroundVariant } from '@xyflow/svelte';

	export let nodes;
	export let nodeTypes;
	export let edges;
</script>

<SvelteFlow
	{nodes}
	{nodeTypes}
	{edges}
	fitView
	minZoom={0.001}
	proOptions={{ hideAttribution: true }}
	colorMode={$isDarkMode ? 'dark' : 'light'}
	nodesConnectable={false}
	nodesDraggable={false}
	on:nodeclick={(e) => dispatch('nodeclick', e.detail)}
	oninit={() => {
		console.log('Flow initialized');
	}}
>
	<Controls showLock={false} />
	<Background variant={BackgroundVariant.Dots} />
</SvelteFlow>

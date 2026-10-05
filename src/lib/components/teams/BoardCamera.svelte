<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { useSvelteFlow } from '@xyflow/svelte';
	import { LAYOUT } from './model';
	import { DUR, prefersReducedMotion, springGentle } from '$lib/utils/transitions';
	export let target: string | null = null;
	export let width = 0;
	export let height = 0;
	export let cancel = 0;
	const flow = useSvelteFlow();
	let frame = 0;
	let generation = 0;
	const stop = () => {
		generation++;
		if (frame) cancelAnimationFrame(frame);
		frame = 0;
	};
	const focus = (id: string | null) => {
		stop();
		if (!id || typeof document === 'undefined' || document.hidden) return;
		const node = flow.getNode(id);
		if (!node) return;
		const zoom = Math.min(1.15, Math.max(0.85, flow.getZoom()));
		const x = node.position.x + (node.measured?.width ?? LAYOUT.cardWidth) / 2;
		const y = node.position.y + (node.measured?.height ?? LAYOUT.cardHeight) / 2;
		const from = flow.getViewport();
		const to = { x: width / 2 - x * zoom, y: height / 2 - y * zoom, zoom };
		if (prefersReducedMotion()) {
			void flow.setCenter(x, y, { zoom, duration: 0 });
			return;
		}
		const started = performance.now(),
			gen = generation;
		const step = () => {
			if (gen !== generation || document.hidden) {
				stop();
				return;
			}
			const t = Math.min(1, (performance.now() - started) / DUR.hero),
				e = springGentle(t);
			void flow.setViewport(
				{
					x: from.x + (to.x - from.x) * e,
					y: from.y + (to.y - from.y) * e,
					zoom: from.zoom + (to.zoom - from.zoom) * e
				},
				{ duration: 0 }
			);
			frame = t < 1 ? requestAnimationFrame(step) : 0;
		};
		frame = requestAnimationFrame(step);
	};
	$: {
		cancel;
		stop();
	}
	$: focus(target);
	onMount(() => {
		const pause = () => {
			if (document.hidden) stop();
		};
		document.addEventListener('visibilitychange', pause);
		return () => document.removeEventListener('visibilitychange', pause);
	});
	onDestroy(stop);
</script>

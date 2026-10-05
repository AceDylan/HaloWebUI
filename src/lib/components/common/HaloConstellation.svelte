<script lang="ts">
	import { onMount } from 'svelte';
	let canvas: HTMLCanvasElement;
	onMount(() => {
		if (!canvas || typeof canvas.getContext !== 'function') return;
		let ctx: CanvasRenderingContext2D | null;
		try {
			ctx = canvas.getContext('2d');
		} catch {
			return;
		}
		if (!ctx) return;
		const draw = () => {
			if (document.hidden) return;
			const w = canvas.clientWidth || 420,
				h = canvas.clientHeight || 420;
			const ratio = Math.min(window.devicePixelRatio || 1, 2);
			canvas.width = w * ratio;
			canvas.height = h * ratio;
			ctx!.setTransform(ratio, 0, 0, ratio, 0, 0);
			const points = Array.from({ length: 22 }, (_, i) => {
				const a = i * 2.39996,
					r = 0.1 + Math.sqrt((i + 1) / 22) * 0.32;
				return { x: w * (0.5 + Math.cos(a) * r), y: h * (0.5 + Math.sin(a) * r) };
			});
			ctx!.lineWidth = 0.7;
			for (let i = 1; i < points.length; i++) {
				const a = points[i],
					b = points[Math.floor((i - 1) / 2)];
				ctx!.strokeStyle = 'rgba(141,163,204,.24)';
				ctx!.beginPath();
				ctx!.moveTo(a.x, a.y);
				ctx!.bezierCurveTo(a.x, (a.y + b.y) / 2, b.x, (a.y + b.y) / 2, b.x, b.y);
				ctx!.stroke();
			}
			if (window.matchMedia('(min-width: 769px) and (pointer: fine)').matches) {
				const glow = ctx!.createRadialGradient(w / 2, h / 2, 1, w / 2, h / 2, w * 0.16);
				glow.addColorStop(0, 'rgba(147,166,225,.2)');
				glow.addColorStop(1, 'rgba(147,166,225,0)');
				ctx!.fillStyle = glow;
				ctx!.fillRect(0, 0, w, h);
			}
			points.forEach((p, i) => {
				ctx!.fillStyle = i % 5 === 0 ? '#b7a3c9' : '#92aacd';
				ctx!.beginPath();
				ctx!.arc(p.x, p.y, i % 5 === 0 ? 2.2 : 1.3, 0, Math.PI * 2);
				ctx!.fill();
			});
			ctx!.fillStyle = '#c4d5f1';
			ctx!.beginPath();
			ctx!.arc(w / 2, h / 2, 5, 0, Math.PI * 2);
			ctx!.fill();
		};
		draw();
		const resize = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(draw) : null;
		resize?.observe(canvas);
		document.addEventListener('visibilitychange', draw);
		return () => {
			resize?.disconnect();
			document.removeEventListener('visibilitychange', draw);
		};
	});
</script>

<canvas bind:this={canvas} class="halo-constellation" aria-hidden="true" />

<style>
	.halo-constellation {
		width: 100%;
		height: 100%;
		display: block;
	}
</style>

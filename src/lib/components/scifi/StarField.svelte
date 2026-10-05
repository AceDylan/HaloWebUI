<script lang="ts">
	/**
	 * Deep-space backdrop (Halo sci-fi layer): three depths of stars drifting towards the
	 * viewer, a little twinkle, a few pixels of pointer parallax on desktop. A `halo:warp`
	 * window event turns the drift into a jump for a moment (stars streak). Hidden tabs stop
	 * drawing; reduced motion gets one still frame. Decoration only: aria-hidden, no input.
	 */
	import { onMount } from 'svelte';
	import { WARP_EVENT } from './scifi';

	/** 'auto' follows the page (light → ink specks, dark → starlight); 'dark' always starlight. */
	export let tone: 'auto' | 'dark' = 'auto';
	/** 0..1 overall strength (the chat page runs dimmer than the landing). */
	export let intensity = 1;

	let canvas: HTMLCanvasElement;

	onMount(() => {
		const ctx = canvas?.getContext?.('2d');
		if (!ctx) return;
		const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
		const fine = window.matchMedia('(pointer: fine) and (min-width: 769px)');
		const phone = !fine.matches;
		const TINTS = ['#ffffff', '#bfe9ff', '#9fd8ff', '#d7c8ff', '#ffe6c4'];

		type Star = { x: number; y: number; z: number; pz: number; tint: string; ph: number };
		let stars: Star[] = [];
		let w = 0,
			h = 0,
			ratio = 1;
		let frame = 0,
			last = 0,
			warpUntil = 0,
			skip = false;
		let px = 0,
			py = 0,
			tx = 0,
			ty = 0;

		const spawn = (far = false): Star => ({
			x: (Math.random() * 2 - 1) * 1.2,
			y: (Math.random() * 2 - 1) * 1.2,
			z: far ? 1 : 0.15 + Math.random() * 0.85,
			pz: 1,
			tint: TINTS[(Math.random() * TINTS.length) | 0],
			ph: Math.random() * Math.PI * 2
		});

		const resize = () => {
			w = canvas.clientWidth;
			h = canvas.clientHeight;
			ratio = Math.min(window.devicePixelRatio || 1, phone ? 1.5 : 2);
			canvas.width = Math.max(1, w * ratio);
			canvas.height = Math.max(1, h * ratio);
			ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
			const n = Math.round(Math.min(phone ? 110 : 260, Math.max(60, (w * h) / 5200)));
			while (stars.length < n) stars.push(spawn());
			stars.length = n;
			if (!frame) draw(performance.now(), 0);
		};

		const dark = () => tone === 'dark' || document.documentElement.classList.contains('dark');

		const draw = (now: number, dt: number) => {
			const warp = now < warpUntil;
			const speed = warp ? 1.35 : 0.035;
			const cx = w / 2 + px,
				cy = h / 2 + py;
			const scale = Math.max(w, h) * 0.55;
			const isDark = dark();
			ctx.clearRect(0, 0, w, h);
			ctx.lineCap = 'round';
			for (const s of stars) {
				s.pz = s.z;
				s.z -= speed * dt;
				if (s.z <= 0.04) {
					Object.assign(s, spawn(true));
					s.pz = s.z;
					continue;
				}
				const x = cx + (s.x / s.z) * scale,
					y = cy + (s.y / s.z) * scale;
				if (x < -20 || x > w + 20 || y < -20 || y > h + 20) {
					Object.assign(s, spawn(true));
					s.pz = s.z;
					continue;
				}
				const near = 1 - s.z;
				const twinkle = warp ? 1 : 0.7 + 0.3 * Math.sin(now / 620 + s.ph);
				const alpha = Math.min(1, (0.15 + near * 0.95) * twinkle) * intensity;
				const size = 0.35 + near * near * (phone ? 1.6 : 2.1);
				ctx.globalAlpha = isDark ? alpha : alpha * 0.32;
				const color = isDark ? s.tint : '#3b4a7a';
				if (warp) {
					const ox = cx + (s.x / s.pz) * scale,
						oy = cy + (s.y / s.pz) * scale;
					ctx.strokeStyle = color;
					ctx.lineWidth = size;
					ctx.beginPath();
					ctx.moveTo(ox, oy);
					ctx.lineTo(x, y);
					ctx.stroke();
				} else {
					ctx.fillStyle = color;
					ctx.beginPath();
					ctx.arc(x, y, size, 0, Math.PI * 2);
					ctx.fill();
				}
			}
			ctx.globalAlpha = 1;
		};

		const loop = (now: number) => {
			frame = 0;
			if (document.hidden || reduced.matches) return;
			const dt = last ? Math.min(0.05, (now - last) / 1000) : 0;
			// phones draw every other frame: same motion, half the battery
			skip = phone && !skip;
			if (!skip) {
				px += (tx - px) * 0.06;
				py += (ty - py) * 0.06;
				draw(now, phone ? dt * 2 : dt);
			}
			last = now;
			frame = requestAnimationFrame(loop);
		};
		const start = () => {
			if (frame || document.hidden) return;
			if (reduced.matches) {
				draw(performance.now(), 0);
				return;
			}
			last = 0;
			frame = requestAnimationFrame(loop);
		};
		const stop = () => {
			if (frame) cancelAnimationFrame(frame);
			frame = 0;
		};

		const onPointer = (e: PointerEvent) => {
			if (!fine.matches || e.pointerType !== 'mouse') return;
			tx = (e.clientX / window.innerWidth - 0.5) * -24;
			ty = (e.clientY / window.innerHeight - 0.5) * -24;
		};
		const onWarp = (e: Event) => {
			if (reduced.matches) return;
			warpUntil = performance.now() + ((e as CustomEvent).detail?.ms ?? 900);
			start();
		};
		const onVisibility = () => (document.hidden ? stop() : start());

		const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
		ro?.observe(canvas);
		resize();
		start();
		window.addEventListener('pointermove', onPointer, { passive: true });
		window.addEventListener(WARP_EVENT, onWarp);
		document.addEventListener('visibilitychange', onVisibility);
		const onReduced = () => (stop(), start());
		reduced.addEventListener?.('change', onReduced);
		return () => {
			stop();
			ro?.disconnect();
			window.removeEventListener('pointermove', onPointer);
			window.removeEventListener(WARP_EVENT, onWarp);
			document.removeEventListener('visibilitychange', onVisibility);
			reduced.removeEventListener?.('change', onReduced);
		};
	});
</script>

<canvas bind:this={canvas} class="halo-starfield" aria-hidden="true" />

<style>
	.halo-starfield {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		display: block;
		pointer-events: none;
	}
</style>

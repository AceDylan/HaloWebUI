<script lang="ts">
	/**
	 * Deep-space backdrop (Halo sci-fi layer): three depths of stars drifting towards the
	 * viewer, a little twinkle, a few pixels of pointer parallax on desktop. In the dark a few
	 * near stars flare into four-point spikes and now and then a meteor crosses. A `halo:warp`
	 * window event turns the drift into a jump for a moment (stars streak, speed ramps up and
	 * down, the centre flashes). Hidden tabs stop drawing; reduced motion gets one still frame.
	 * Decoration only: aria-hidden, no input.
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

		type Star = { x: number; y: number; z: number; pz: number; tint: string; ph: number; flare: boolean };
		type Meteor = { x: number; y: number; vx: number; vy: number; age: number; life: number };
		let stars: Star[] = [];
		let meteors: Meteor[] = [];
		let nextMeteor = 0;
		let w = 0,
			h = 0,
			ratio = 1;
		let frame = 0,
			last = 0,
			warpFrom = 0,
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
			ph: Math.random() * Math.PI * 2,
			flare: Math.random() < 0.035
		});

		// a meteor enters from the top or a side and crosses about a third of the view
		const launch = (): Meteor => {
			const fromLeft = Math.random() < 0.5;
			const angle = (fromLeft ? 0.35 : Math.PI - 0.35) + (Math.random() - 0.5) * 0.4;
			const v = Math.max(w, h) * (0.9 + Math.random() * 0.5);
			return {
				x: fromLeft ? Math.random() * w * 0.5 : w * (0.5 + Math.random() * 0.5),
				y: Math.random() * h * 0.35,
				vx: Math.cos(angle) * v,
				vy: Math.sin(angle) * v,
				age: 0,
				life: 0.7 + Math.random() * 0.5
			};
		};

		// Giving a canvas a new size wipes it. On a phone the address bar sliding in and out
		// changes the height all the time, and every wipe showed as the stars blinking off for a
		// frame or two (the loop only draws every other frame there). So on a phone the canvas
		// only grows — a shorter view leaves its bottom rows under the clip of the layer it sits
		// in — and whenever it is resized it is drawn again at once.
		const host = (canvas.parentElement ?? canvas) as HTMLElement;
		let bw = 0,
			bh = 0;
		const resize = () => {
			w = host.clientWidth;
			h = host.clientHeight;
			const nextW = phone ? Math.max(bw, w) : w;
			const nextH = phone ? Math.max(bh, h) : h;
			const changed = nextW !== bw || nextH !== bh;
			if (changed) {
				bw = nextW;
				bh = nextH;
				ratio = Math.min(window.devicePixelRatio || 1, phone ? 1.5 : 2);
				canvas.style.width = `${bw}px`;
				canvas.style.height = `${bh}px`;
				canvas.width = Math.max(1, Math.round(bw * ratio));
				canvas.height = Math.max(1, Math.round(bh * ratio));
				ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
			}
			const n = Math.round(Math.min(phone ? 130 : 320, Math.max(70, (w * h) / 4300)));
			while (stars.length < n) stars.push(spawn());
			stars.length = n;
			// draw now: the loop's next frame may be one it skips
			if (changed || !frame) draw(performance.now(), 0);
		};

		const dark = () => tone === 'dark' || document.documentElement.classList.contains('dark');

		const draw = (now: number, dt: number) => {
			const warp = now < warpUntil;
			// the jump eases in and out instead of switching on and off
			const k = warp ? Math.sin(Math.PI * Math.min(1, (now - warpFrom) / (warpUntil - warpFrom))) : 0;
			const speed = 0.035 + 1.6 * k;
			const cx = w / 2 + px,
				cy = h / 2 + py;
			const scale = Math.max(w, h) * 0.55;
			const isDark = dark();
			ctx.clearRect(0, 0, bw, bh);
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
				if (s.flare && isDark && !warp && near > 0.45) {
					// a near bright star wears diffraction spikes that breathe with its twinkle
					const len = (4 + near * near * 14) * twinkle * (phone ? 0.7 : 1);
					ctx.globalAlpha = 0.55 * near * twinkle * intensity;
					ctx.strokeStyle = s.tint;
					ctx.lineWidth = 0.6;
					ctx.beginPath();
					ctx.moveTo(x - len, y);
					ctx.lineTo(x + len, y);
					ctx.moveTo(x, y - len * 0.7);
					ctx.lineTo(x, y + len * 0.7);
					ctx.stroke();
				}
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
			if (isDark && k > 0.05) {
				// the jump flashes at the vanishing point
				const r = Math.max(w, h) * (0.12 + 0.25 * k);
				const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
				g.addColorStop(0, `rgba(224, 251, 255, ${0.28 * k * intensity})`);
				g.addColorStop(0.4, `rgba(94, 231, 255, ${0.1 * k * intensity})`);
				g.addColorStop(1, 'rgba(94, 231, 255, 0)');
				ctx.globalAlpha = 1;
				ctx.fillStyle = g;
				ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
			}
			if (isDark && dt > 0) {
				if (!nextMeteor) nextMeteor = now + 2500 + Math.random() * 4000;
				if (now > nextMeteor && meteors.length < 2) {
					meteors.push(launch());
					nextMeteor = now + 4000 + Math.random() * 7000;
				}
				for (const m of meteors) {
					m.age += dt;
					m.x += m.vx * dt;
					m.y += m.vy * dt;
					const t = m.age / m.life;
					const a = Math.sin(Math.PI * Math.min(1, t)) * intensity;
					const tail = 0.16;
					const g = ctx.createLinearGradient(m.x, m.y, m.x - m.vx * tail, m.y - m.vy * tail);
					g.addColorStop(0, `rgba(224, 251, 255, ${0.95 * a})`);
					g.addColorStop(0.25, `rgba(94, 231, 255, ${0.45 * a})`);
					g.addColorStop(1, 'rgba(167, 139, 250, 0)');
					ctx.globalAlpha = 1;
					ctx.strokeStyle = g;
					ctx.lineWidth = phone ? 1.1 : 1.4;
					ctx.beginPath();
					ctx.moveTo(m.x, m.y);
					ctx.lineTo(m.x - m.vx * tail, m.y - m.vy * tail);
					ctx.stroke();
				}
				meteors = meteors.filter((m) => m.age < m.life);
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
			const now = performance.now();
			const ms = (e as CustomEvent).detail?.ms ?? 900;
			// a jump that arrives during another one extends it instead of restarting the ramp
			if (now >= warpUntil) warpFrom = now;
			warpUntil = Math.max(warpUntil, now + ms);
			start();
		};
		const onVisibility = () => (document.hidden ? stop() : start());

		const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
		ro?.observe(host);
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

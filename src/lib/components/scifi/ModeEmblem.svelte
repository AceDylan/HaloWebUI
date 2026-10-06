<script lang="ts">
	/**
	 * The holographic emblem in the header of each mode page (精答 / 讨论台 / 协作台 / 生图工作台).
	 * All four share the reactor's outer halo — a tick ring and arc segments turning against
	 * each other — so they read as one family; inside each draws what the mode does: a beam
	 * sweeping a ring of assistants and lighting the one it picks, a council of seats taking turns
	 * to speak, a lead handing work along a small graph, a lens iris with a scan line. HUD read-outs underneath (clock + the page's own figures). Pure decoration
	 * (aria-hidden); shown only with the sci-fi layer on. Styles: scifi-modes.css (.halo-emblem).
	 */
	import { onMount } from 'svelte';

	export let mode: 'answer' | 'discuss' | 'teams' | 'images';
	export let stats: { k: string; v: string | number }[] = [];

	const TICKS = Array.from({ length: 72 }, (_, i) => i);
	const SEATS = Array.from({ length: 5 }, (_, i) => {
		const a = ((-90 + i * 72) * Math.PI) / 180;
		return { x: Math.round(Math.cos(a) * 58 * 10) / 10, y: Math.round(Math.sin(a) * 58 * 10) / 10 };
	});
	// 精答: six assistants on a ring, a beam visiting each in turn (one a second, clockwise)
	const PICKS = Array.from({ length: 6 }, (_, i) => {
		const a = ((-90 + i * 60) * Math.PI) / 180;
		return { x: Math.round(Math.cos(a) * 56 * 10) / 10, y: Math.round(Math.sin(a) * 56 * 10) / 10 };
	});
	const CHORDS = SEATS.flatMap((s, i) => SEATS.slice(i + 1).map((t) => [s, t]));
	const WORKERS = [-44, 0, 44];
	const at = (deg: number, r: number) => {
		const a = (deg * Math.PI) / 180;
		return [Math.round(Math.cos(a) * r * 10) / 10, Math.round(Math.sin(a) * r * 10) / 10];
	};
	// six iris blades: chords across the lens, each turned 60° from the last
	const BLADES = Array.from({ length: 6 }, (_, i) => [...at(i * 60, 40), ...at(i * 60 + 130, 40)]);
	const arcId = `halo-emblem-arc-${mode}`;
	const lensId = `halo-emblem-lens-${mode}`;

	let clock = '';
	const tick = () => {
		const d = new Date();
		clock = [d.getHours(), d.getMinutes(), d.getSeconds()]
			.map((n) => String(n).padStart(2, '0'))
			.join(':');
	};
	onMount(() => {
		tick();
		const id = setInterval(() => !document.hidden && tick(), 1000);
		return () => clearInterval(id);
	});
</script>

<div class="halo-emblem halo-emblem--{mode}" aria-hidden="true">
	<svg class="halo-emblem__svg" viewBox="-100 -100 200 200">
		<defs>
			<linearGradient id={arcId} x1="0" y1="0" x2="1" y2="1">
				<stop offset="0" stop-color="var(--scifi-cyan)" />
				<stop offset="0.6" stop-color="var(--scifi-violet)" />
				<stop offset="1" stop-color="var(--scifi-magenta)" />
			</linearGradient>
			<clipPath id={lensId}><circle r="56" /></clipPath>
		</defs>

		<g class="halo-emblem__ticks">
			{#each TICKS as i}
				<line x1="0" y1={i % 6 === 0 ? -97 : -95} x2="0" y2="-91" transform="rotate({i * 5})" class:major={i % 6 === 0} />
			{/each}
		</g>
		<g class="halo-emblem__arcs" stroke="url(#{arcId})">
			<circle r="84" pathLength="100" stroke-dasharray="16 84" />
			<circle r="84" pathLength="100" stroke-dasharray="7 93" stroke-dashoffset="-38" />
			<circle r="84" pathLength="100" stroke-dasharray="11 89" stroke-dashoffset="-66" />
		</g>

		{#if mode === 'answer'}
			<circle class="halo-emblem__ring halo-emblem__ring--dash" r="56" />
			<g class="halo-emblem__beam">
				<line x1="0" y1="-12" x2="0" y2="-48" stroke="url(#{arcId})" />
			</g>
			{#each PICKS as p, i}
				<circle class="halo-emblem__pick" cx={p.x} cy={p.y} r="6.5" style="--d:{i}s; --h:{[188, 226, 262, 300, 38, 160][i]}" />
			{/each}
			<circle class="halo-emblem__core" r="11" stroke="url(#{arcId})" />
			<circle class="halo-emblem__dot" r="3.2" />
		{:else if mode === 'discuss'}
			<circle class="halo-emblem__ring" r="58" />
			{#each CHORDS as [s, t], i}
				<line class="halo-emblem__flow" x1={s.x} y1={s.y} x2={t.x} y2={t.y} style="--d:{i * 0.37}s" />
			{/each}
			{#each SEATS as s, i}
				<circle class="halo-emblem__seat" cx={s.x} cy={s.y} r="6" style="--d:{i * 1.1}s; --h:{[188, 262, 318, 38, 210][i]}" />
			{/each}
			<circle class="halo-emblem__core" r="11" stroke="url(#{arcId})" />
			<circle class="halo-emblem__dot" r="3.2" />
		{:else if mode === 'teams'}
			{#each WORKERS as y, i}
				<path class="halo-emblem__flow" d="M-56 0 C -28 0 -28 {y} 0 {y}" style="--d:{i * 0.4}s" />
				<path class="halo-emblem__flow" d="M0 {y} C 28 {y} 28 0 56 0" style="--d:{0.9 + i * 0.4}s" />
			{/each}
			<rect class="halo-emblem__lead" x="-67" y="-11" width="22" height="22" rx="6" stroke="url(#{arcId})" />
			{#each WORKERS as y, i}
				<rect class="halo-emblem__node" x="-8" y={y - 8} width="16" height="16" rx="4.5" style="--d:{i * 0.9}s" />
			{/each}
			<rect class="halo-emblem__goal" x="47" y="-9" width="18" height="18" rx="9" />
			<circle class="halo-emblem__dot" cx="56" cy="0" r="3" />
		{:else}
			<circle class="halo-emblem__ring" r="64" />
			<circle class="halo-emblem__ring halo-emblem__ring--dash" r="50" />
			<g class="halo-emblem__iris">
				{#each BLADES as [x1, y1, x2, y2]}
					<line {x1} {y1} {x2} {y2} />
				{/each}
			</g>
			<g clip-path="url(#{lensId})">
				<rect class="halo-emblem__scan" x="-60" y="-1" width="120" height="2" />
			</g>
			<circle class="halo-emblem__core" r="12" stroke="url(#{arcId})" />
			<circle class="halo-emblem__dot" r="3.6" />
			<g class="halo-emblem__cross">
				<line x1="-74" y1="0" x2="-66" y2="0" /><line x1="66" y1="0" x2="74" y2="0" />
				<line x1="0" y1="-74" x2="0" y2="-66" /><line x1="0" y1="66" x2="0" y2="74" />
			</g>
		{/if}
	</svg>
	<div class="halo-emblem__hud">
		<span><b>SYS</b> T+ {clock}</span>
		{#each stats as s}
			<span><b>{s.k}</b> {s.v}</span>
		{/each}
	</div>
</div>

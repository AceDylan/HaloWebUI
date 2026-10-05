<script lang="ts">
	/**
	 * The holographic reactor around the assistant on the landing page: a tick ring, a dashed
	 * ring and arc segments turning against each other, a radar sweep, two orbiting sparks and
	 * small HUD read-outs (clock, link state, the model). Pure decoration (aria-hidden); it sits
	 * behind the avatar and fades out towards the greeting. Styles: scifi.css (.halo-reactor).
	 */
	import { onMount } from 'svelte';

	export let label = '';

	const TICKS = Array.from({ length: 120 }, (_, i) => i);
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

<div class="halo-reactor" aria-hidden="true">
	<div class="halo-reactor__sweep"></div>
	<svg class="halo-reactor__svg" viewBox="-200 -200 400 400">
		<defs>
			<linearGradient id="halo-reactor-arc" x1="0" y1="0" x2="1" y2="1">
				<stop offset="0" stop-color="var(--scifi-cyan)" />
				<stop offset="0.6" stop-color="var(--scifi-violet)" />
				<stop offset="1" stop-color="var(--scifi-magenta)" />
			</linearGradient>
		</defs>
		<g class="halo-reactor__ticks">
			{#each TICKS as i}
				<line
					x1="0"
					y1={i % 10 === 0 ? -184 : -180}
					x2="0"
					y2="-174"
					transform="rotate({i * 3})"
					class:major={i % 10 === 0}
				/>
			{/each}
		</g>
		<circle class="halo-reactor__dash" r="152" />
		<g class="halo-reactor__arcs">
			<circle r="128" pathLength="100" stroke-dasharray="18 82" />
			<circle r="128" pathLength="100" stroke-dasharray="9 91" stroke-dashoffset="-40" />
			<circle r="128" pathLength="100" stroke-dasharray="14 86" stroke-dashoffset="-68" />
		</g>
		<circle class="halo-reactor__inner" r="96" />
		<g class="halo-reactor__orbit">
			<circle cx="0" cy="-112" r="2.6" />
			<circle cx="0" cy="112" r="1.6" />
		</g>
		<g class="halo-reactor__orbit halo-reactor__orbit--slow">
			<circle cx="-166" cy="0" r="2" />
		</g>
	</svg>
	<div class="halo-reactor__hud halo-reactor__hud--tl"><b>SYS</b> ONLINE<br /><i>T+ {clock}</i></div>
	<div class="halo-reactor__hud halo-reactor__hud--tr"><b>LINK</b> STABLE<br /><i>NEURAL · 100%</i></div>
	{#if label}
		<div class="halo-reactor__hud halo-reactor__hud--br"><b>AGENT</b><br /><i>{label}</i></div>
	{/if}
</div>

<script lang="ts">
	/**
	 * Opening titles (at most every 6 hours, scifi.ts shouldBoot): the ring draws itself, three status lines type
	 * out, then the screen opens like an iris onto the app while the stars jump. About two
	 * seconds; a click, a tap or any key skips it. Never framed, never with reduced motion
	 * (scifi.ts shouldBoot). Styles: scifi.css (.halo-boot).
	 */
	import { createEventDispatcher, onMount } from 'svelte';
	import { markBooted, warp } from './scifi';

	export let name = '';

	const dispatch = createEventDispatcher();
	let leaving = false;
	let timers: ReturnType<typeof setTimeout>[] = [];

	const finish = () => {
		if (leaving) return;
		leaving = true;
		markBooted();
		warp(1100);
		timers.push(setTimeout(() => dispatch('done'), 650));
	};

	onMount(() => {
		timers.push(setTimeout(finish, 2100));
		const skip = () => finish();
		window.addEventListener('keydown', skip, { once: true });
		return () => {
			timers.forEach(clearTimeout);
			window.removeEventListener('keydown', skip);
		};
	});

	$: who = (name || 'operator').toUpperCase();
</script>

<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
<div class="halo-boot" class:halo-boot--leaving={leaving} aria-hidden="true" on:click={finish}>
	<div class="halo-boot__grid"></div>
	<div class="halo-boot__scan"></div>
	<div class="halo-boot__core">
		<svg class="halo-boot__ring" viewBox="-100 -100 200 200">
			<circle class="halo-boot__ring-a" r="86" pathLength="100" />
			<circle class="halo-boot__ring-b" r="70" pathLength="100" />
			<circle class="halo-boot__ring-c" r="54" pathLength="100" />
			<circle class="halo-boot__dot" r="7" />
		</svg>
	</div>
	<div class="halo-boot__title" data-text="HALO">HALO</div>
	<div class="halo-boot__lines">
		<p style="--d: 0.35s">&gt; NEURAL INTERFACE ............ <b>OK</b></p>
		<p style="--d: 0.75s">&gt; LINKING AGENTS ............... <b>OK</b></p>
		<p style="--d: 1.15s">&gt; WELCOME BACK, {who}</p>
	</div>
	<div class="halo-boot__skip">CLICK TO SKIP</div>
</div>

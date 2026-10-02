<script lang="ts">
	import './teams.css';
	import type { AvatarKind } from './model';
	import { toneOf } from './model';

	/**
	 * An agent: a tinted disc with its role's glyph, inside a halo that tells its state — a comet
	 * sweeping round while it works, a closed ring when done, dashed while waiting, red when it
	 * needs you. No images to load.
	 */
	export let kind: AvatarKind = 'generic';
	export let status: string | null = null;
	export let size = 40;
	export let title = '';

	const HUE: Record<AvatarKind, [number, number]> = {
		lead: [250, 85],
		backend: [205, 85],
		frontend: [330, 75],
		qa: [155, 60],
		reviewer: [36, 90],
		docs: [220, 22],
		data: [176, 65],
		ops: [20, 85],
		design: [290, 70],
		generic: [220, 14]
	};

	$: [hue, sat] = HUE[kind] ?? HUE.generic;
	$: tone = status ? toneOf(status) : null;
	$: ring =
		tone === 'run'
			? 'run'
			: tone === 'done'
				? 'done'
				: tone === 'fail'
					? 'fail'
					: tone === 'user' || tone === 'quota'
						? 'ask'
						: tone === 'wait' || tone === 'deps' || tone === 'idle'
							? 'wait'
							: tone === 'stop'
								? 'stop'
								: 'none';
	$: glyph = Math.round(size * 0.46);
</script>

<span
	class="tm-avatar"
	data-ring={ring}
	data-kind={kind}
	style="--s:{size}px;--h:{hue};--sat:{sat}%"
	title={title || null}
	aria-hidden={title ? null : 'true'}
>
	<span class="tm-avatar-ring" />
	<span class="tm-avatar-core">
		<svg viewBox="0 0 16 16" width={glyph} height={glyph} fill="none" aria-hidden="true">
			{#if kind === 'lead'}
				<path
					d="M8 1.8c.4 2.9 1.9 4.4 4.8 4.8-2.9.4-4.4 1.9-4.8 4.8-.4-2.9-1.9-4.4-4.8-4.8C6.1 6.2 7.6 4.7 8 1.8Z"
					fill="currentColor"
				/>
				<path
					d="M12.6 10.4c.15 1 .6 1.45 1.6 1.6-1 .15-1.45.6-1.6 1.6-.15-1-.6-1.45-1.6-1.6 1-.15 1.45-.6 1.6-1.6Z"
					fill="currentColor"
					opacity=".7"
				/>
			{:else if kind === 'backend'}
				<path
					d="M5.5 4.5 2 8l3.5 3.5M10.5 4.5 14 8l-3.5 3.5M9 3 7 13"
					stroke="currentColor"
					stroke-width="1.6"
					stroke-linecap="round"
					stroke-linejoin="round"
				/>
			{:else if kind === 'frontend'}
				<rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" stroke-width="1.5" />
				<path d="M2 6.2h12M6 6.2V13" stroke="currentColor" stroke-width="1.5" />
			{:else if kind === 'qa'}
				<path
					d="M8 1.8 13.2 4v3.6c0 3-2.2 5.4-5.2 6.6-3-1.2-5.2-3.6-5.2-6.6V4L8 1.8Z"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linejoin="round"
				/>
				<path
					d="m5.6 8 1.7 1.7 3.2-3.4"
					stroke="currentColor"
					stroke-width="1.6"
					stroke-linecap="round"
					stroke-linejoin="round"
				/>
			{:else if kind === 'reviewer'}
				<circle cx="7" cy="7" r="4.2" stroke="currentColor" stroke-width="1.6" />
				<path
					d="m10.2 10.2 3.4 3.4"
					stroke="currentColor"
					stroke-width="1.7"
					stroke-linecap="round"
				/>
			{:else if kind === 'docs'}
				<path
					d="M4 1.8h5.2L12.5 5v9.2H4V1.8Z"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linejoin="round"
				/>
				<path
					d="M6 8h4.5M6 10.8h3"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
				/>
			{:else if kind === 'data'}
				<path
					d="M3 13.5V9M6.5 13.5V3M10 13.5V6.5M13.5 13.5v-3"
					stroke="currentColor"
					stroke-width="1.8"
					stroke-linecap="round"
				/>
			{:else if kind === 'ops'}
				<circle cx="8" cy="8" r="2.4" stroke="currentColor" stroke-width="1.5" />
				<path
					d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6 5 5M11 11l1.4 1.4M3.6 12.4 5 11M11 5l1.4-1.4"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
				/>
			{:else if kind === 'design'}
				<path
					d="M2.5 13.5 3.3 10 10.6 2.7a1.6 1.6 0 0 1 2.3 0l.4.4a1.6 1.6 0 0 1 0 2.3L6 12.7l-3.5.8Z"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linejoin="round"
				/>
				<path d="m9.5 3.8 2.7 2.7" stroke="currentColor" stroke-width="1.5" />
			{:else}
				<path
					d="M8 1.8 13.4 5v6L8 14.2 2.6 11V5L8 1.8Z"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linejoin="round"
				/>
				<circle cx="8" cy="8" r="1.6" fill="currentColor" />
			{/if}
		</svg>
	</span>
</span>

<style>
	.tm-avatar {
		position: relative;
		display: inline-grid;
		place-items: center;
		flex-shrink: 0;
		width: var(--s);
		height: var(--s);
		border-radius: 9999px;
	}
	.tm-avatar-core {
		position: absolute;
		inset: 3px;
		display: grid;
		place-items: center;
		border-radius: 9999px;
		color: hsl(var(--h) var(--sat) 40%);
		background: radial-gradient(
			120% 120% at 30% 20%,
			hsl(var(--h) var(--sat) 97%),
			hsl(var(--h) var(--sat) 90%)
		);
		box-shadow:
			inset 0 0 0 1px hsl(var(--h) var(--sat) 40% / 0.14),
			inset 0 1px 0 hsl(0 0% 100% / 0.7);
	}
	:global(.dark) .tm-avatar-core {
		color: hsl(var(--h) var(--sat) 76%);
		background: radial-gradient(
			120% 120% at 30% 20%,
			hsl(var(--h) calc(var(--sat) * 0.6) 24%),
			hsl(var(--h) calc(var(--sat) * 0.5) 14%)
		);
		box-shadow:
			inset 0 0 0 1px hsl(var(--h) var(--sat) 70% / 0.18),
			inset 0 1px 0 hsl(0 0% 100% / 0.06);
	}
	.tm-avatar[data-kind='lead'] .tm-avatar-core {
		color: hsl(0 0% 100%);
		background: radial-gradient(120% 120% at 25% 15%, hsl(245 90% 70%), hsl(258 70% 42%));
		box-shadow:
			inset 0 1px 0 hsl(0 0% 100% / 0.35),
			0 4px 14px -4px hsl(250 80% 50% / 0.55);
	}

	.tm-avatar-ring {
		position: absolute;
		inset: 0;
		border-radius: 9999px;
		border: 1.5px solid hsl(var(--h) var(--sat) 45% / 0.18);
	}
	:global(.dark) .tm-avatar-ring {
		border-color: hsl(var(--h) var(--sat) 70% / 0.16);
	}
	[data-ring='done'] .tm-avatar-ring {
		border-color: hsl(158 64% 42%);
	}
	[data-ring='fail'] .tm-avatar-ring {
		border-color: hsl(0 72% 54%);
	}
	[data-ring='ask'] .tm-avatar-ring {
		border-color: hsl(262 83% 62%);
		animation: tm-avatar-breathe 2.4s ease-in-out infinite;
	}
	[data-ring='stop'] .tm-avatar-ring {
		border-color: hsl(220 9% 60%);
	}
	[data-ring='wait'] .tm-avatar-ring {
		border-style: dashed;
		border-color: hsl(220 9% 55% / 0.55);
	}
	[data-ring='run'] .tm-avatar-ring {
		border: 0;
		padding: 1.75px;
		background: conic-gradient(
			from var(--tm-angle, 0deg),
			hsl(214 100% 56% / 0) 0turn,
			hsl(214 100% 56% / 0.15) 0.45turn,
			hsl(214 100% 56%) 0.85turn,
			hsl(190 95% 60%) 0.97turn,
			hsl(214 100% 56% / 0) 1turn
		);
		-webkit-mask:
			linear-gradient(#000 0 0) content-box,
			linear-gradient(#000 0 0);
		-webkit-mask-composite: xor;
		mask-composite: exclude;
		animation: tm-spin 1.8s linear infinite;
		filter: drop-shadow(0 0 3px hsl(214 100% 60% / 0.55));
	}
	@keyframes tm-avatar-breathe {
		50% {
			box-shadow: 0 0 0 3px hsl(262 83% 62% / 0.18);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.tm-avatar-ring {
			animation: none !important;
		}
	}
</style>

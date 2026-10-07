<script lang="ts">
	/**
	 * How a mode works, as the stages a request passes through (精答: 读助手库 → … → 作答). A signal
	 * runs along them in turn. On a phone it stands in for the page's paragraph of explanation, so
	 * the box to write in is on the first screen; on a wide screen it sits under the paragraph.
	 */
	export let steps: string[] = [];
	export let label = '流程';
</script>

<ol class="halo-flow" aria-label={label} style="--n: {steps.length}" data-halo-flow>
	{#each steps as step, i}
		<li class="halo-flow__step" style="--i: {i}">
			<span class="halo-flow__n" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
			<span class="halo-flow__label">{step}</span>
		</li>
	{/each}
</ol>

<style>
	.halo-flow {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem 0;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.halo-flow__step {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.22rem 0.6rem 0.22rem 0.45rem;
		border-radius: 9999px;
		font-size: 11.5px;
		line-height: 1.3;
		color: rgb(71 85 105);
		background: rgb(255 255 255 / 0.6);
		box-shadow: inset 0 0 0 1px rgb(15 23 42 / 0.08);
		white-space: nowrap;
	}
	:global(.dark) .halo-flow__step {
		color: rgb(203 213 225);
		background: rgb(255 255 255 / 0.035);
		box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.08);
	}
	/* the link to the next stage */
	.halo-flow__step:not(:last-child) {
		margin-right: 1.15rem;
	}
	.halo-flow__step:not(:last-child)::after {
		content: '';
		position: absolute;
		left: calc(100% + 0.2rem);
		top: 50%;
		width: 0.75rem;
		height: 1px;
		background: currentColor;
		opacity: 0.35;
	}
	.halo-flow__n {
		font-family: var(--font-mono);
		font-size: 9.5px;
		font-weight: 600;
		letter-spacing: 0.06em;
		color: rgb(148 163 184);
	}

	/* ---- sci-fi: HUD stages, a signal passing through them in turn ------------------------- */
	:global(html.halo-scifi) .halo-flow__step {
		box-shadow: inset 0 0 0 1px rgb(8 145 178 / 0.2);
	}
	:global(html.halo-scifi.dark) .halo-flow__step {
		background: rgb(94 231 255 / 0.04);
		box-shadow: inset 0 0 0 1px rgb(94 231 255 / 0.16);
	}
	:global(html.halo-scifi) .halo-flow__n {
		color: var(--scifi-cyan);
	}
	:global(html.halo-scifi) .halo-flow__step:not(:last-child)::after {
		background: linear-gradient(90deg, var(--scifi-cyan), var(--scifi-violet));
		opacity: 0.6;
	}
	/* the lit state is a layer that fades in and out (opacity: no repaint) */
	:global(html.halo-scifi) .halo-flow__step::before {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
		pointer-events: none;
		opacity: 0;
		box-shadow:
			inset 0 0 0 1px var(--scifi-cyan),
			0 0 16px -3px var(--scifi-glow);
		background: linear-gradient(to top, rgb(94 231 255 / 0.16), transparent 80%);
		animation: halo-flow-signal calc(var(--n) * 0.9s) ease-in-out infinite;
		animation-delay: calc(var(--i) * 0.9s);
	}
	@keyframes halo-flow-signal {
		0%,
		40%,
		100% {
			opacity: 0;
		}
		12% {
			opacity: 1;
		}
	}
	@media (max-width: 639px) {
		/* one swipeable line on a phone */
		.halo-flow {
			flex-wrap: nowrap;
			overflow-x: auto;
			scrollbar-width: none;
			margin-inline: -1rem;
			padding-inline: 1rem;
		}
		.halo-flow::-webkit-scrollbar {
			display: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		:global(html.halo-scifi) .halo-flow__step::before {
			animation: none;
		}
	}
</style>

<script lang="ts">
	import { onDestroy } from 'svelte';
	import { relay, type Relay } from '$lib/utils/handoff';
	import { MODE_LABEL, type ModeKey } from './mode-relay';
	import { sectionOf } from './scifi';

	/**
	 * Work handed from one part of the app to another (the dock, 「交给…」, 「接下来」) crosses the
	 * screen as a beam of light with a read-out of what it carries: the modes read as one system.
	 * Decoration plus a polite announcement; transform and opacity only, gone in about a second.
	 */
	const SHOW_MS = 1500;

	const modeOfPath = (pathname: string): ModeKey => {
		const section = sectionOf(pathname);
		if (section === 'answer' || section === 'discuss' || section === 'teams') return section;
		if (section === 'workspace') return 'studio';
		return 'chat';
	};

	let shown: (Relay & { source: ModeKey; cargo: string }) | null = null;
	let announce = '';
	let timer: ReturnType<typeof setTimeout> | null = null;

	const play = (value: Relay | null) => {
		// (a subscription starts with the last value: one from before this page is not news)
		if (!value || typeof window === 'undefined' || Date.now() - value.at > 1000) return;
		const source = modeOfPath(window.location.pathname);
		const cargo = [
			value.chars ? `${value.chars} 字` : '',
			value.files ? `${value.files} 个文件` : '',
			value.context ? '含背景' : ''
		]
			.filter(Boolean)
			.join(' · ');
		shown = { ...value, source, cargo };
		announce = `已带到${MODE_LABEL[value.to]}${cargo ? `：${cargo}` : ''}`;
		if (timer) clearTimeout(timer);
		timer = setTimeout(() => (shown = null), SHOW_MS);
	};

	const stop = relay.subscribe(play);
	onDestroy(() => {
		stop();
		if (timer) clearTimeout(timer);
	});
</script>

{#if shown}
	{#key shown.at}
		<div class="halo-relay" aria-hidden="true" data-halo-relay={shown.to}>
			<div class="halo-relay__beam" />
			<div class="halo-relay__tag">
				<span class="halo-relay__k">RELAY</span>
				<span class="halo-relay__from">{MODE_LABEL[shown.source]}</span>
				<span class="halo-relay__arrow">⟶</span>
				<b>{MODE_LABEL[shown.to]}</b>
				{#if shown.cargo}<span class="halo-relay__cargo">{shown.cargo}</span>{/if}
			</div>
		</div>
	{/key}
{/if}
<div class="sr-only" aria-live="polite">{announce}</div>

<style>
	.halo-relay {
		position: fixed;
		inset: 0;
		z-index: 55;
		pointer-events: none;
		overflow: hidden;
		/* its own layer in a page change, above the page's snapshots (halo.css) */
		view-transition-name: halo-relay;
	}
	.halo-relay__beam {
		position: absolute;
		left: 0;
		right: 0;
		top: 44%;
		height: 2px;
		transform-origin: 0 50%;
		background: linear-gradient(
			90deg,
			transparent,
			#0891b2 18%,
			#fff 50%,
			#7c3aed 82%,
			transparent
		);
		box-shadow:
			0 0 18px 2px rgb(8 145 178 / 0.45),
			0 0 60px 8px rgb(124 58 237 / 0.18);
		animation: halo-relay-beam 900ms cubic-bezier(0.16, 1, 0.3, 1) both;
	}
	:global(.dark) .halo-relay__beam {
		background: linear-gradient(
			90deg,
			transparent,
			#5ee7ff 18%,
			#fff 50%,
			#a78bfa 82%,
			transparent
		);
		box-shadow:
			0 0 22px 3px rgb(94 231 255 / 0.55),
			0 0 80px 10px rgb(167 139 250 / 0.22);
	}
	:global(html:not(.halo-scifi)) .halo-relay__beam {
		display: none;
	}
	@keyframes halo-relay-beam {
		0% {
			opacity: 1;
			transform: scaleX(0);
		}
		45% {
			opacity: 1;
			transform: scaleX(1);
		}
		100% {
			opacity: 0;
			transform: scaleX(1) scaleY(0.4);
		}
	}
	.halo-relay__tag {
		position: absolute;
		left: 50%;
		top: calc(44% + 14px);
		display: flex;
		align-items: center;
		gap: 0.5rem;
		max-width: calc(100vw - 2rem);
		padding: 0.4rem 0.85rem;
		border-radius: 9999px;
		font-size: 12px;
		white-space: nowrap;
		color: rgb(15 23 42);
		background: rgb(255 255 255 / 0.92);
		box-shadow:
			0 0 0 1px rgb(8 145 178 / 0.25),
			0 12px 32px -12px rgb(8 145 178 / 0.45);
		transform: translateX(-50%);
		animation: halo-relay-tag 1500ms cubic-bezier(0.16, 1, 0.3, 1) both;
	}
	:global(.dark) .halo-relay__tag {
		color: #e0fbff;
		background: rgb(6 9 20 / 0.9);
		box-shadow:
			0 0 0 1px rgb(94 231 255 / 0.3),
			0 0 30px -6px rgb(94 231 255 / 0.5);
	}
	@keyframes halo-relay-tag {
		0% {
			opacity: 0;
			transform: translateX(-50%) translateY(6px);
		}
		18%,
		72% {
			opacity: 1;
			transform: translateX(-50%) translateY(0);
		}
		100% {
			opacity: 0;
			transform: translateX(-50%) translateY(-4px);
		}
	}
	.halo-relay__k {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.3em;
		color: #0891b2;
	}
	:global(.dark) .halo-relay__k {
		color: #5ee7ff;
		text-shadow: 0 0 8px rgb(94 231 255 / 0.6);
	}
	.halo-relay__from {
		opacity: 0.65;
	}
	.halo-relay__arrow {
		color: #7c3aed;
	}
	:global(.dark) .halo-relay__arrow {
		color: #a78bfa;
	}
	.halo-relay__cargo {
		overflow: hidden;
		text-overflow: ellipsis;
		font-family: var(--font-mono);
		font-size: 10.5px;
		opacity: 0.7;
	}
	@media (prefers-reduced-motion: reduce) {
		.halo-relay__beam {
			display: none;
		}
		.halo-relay__tag {
			animation: halo-relay-fade 1500ms ease both;
		}
		@keyframes halo-relay-fade {
			0%,
			100% {
				opacity: 0;
			}
			15%,
			80% {
				opacity: 1;
			}
		}
	}
</style>

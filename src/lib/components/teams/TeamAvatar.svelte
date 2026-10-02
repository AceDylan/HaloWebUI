<script lang="ts">
	import type { AvatarKind } from './model';
	import { toneOf } from './model';
	import { TONE_DOT } from './tones';

	/** A small robot per role (no images to load), with a status dot. */
	export let kind: AvatarKind = 'generic';
	export let status: string | null = null;
	export let size = 40;
	export let title = '';

	const PALETTE: Record<AvatarKind, { body: string; face: string; badge: string }> = {
		lead: { body: '#6366f1', face: '#eef2ff', badge: '#f59e0b' },
		backend: { body: '#0ea5e9', face: '#f0f9ff', badge: '#0369a1' },
		frontend: { body: '#ec4899', face: '#fdf2f8', badge: '#9d174d' },
		qa: { body: '#10b981', face: '#ecfdf5', badge: '#047857' },
		reviewer: { body: '#f59e0b', face: '#fffbeb', badge: '#b45309' },
		docs: { body: '#64748b', face: '#f8fafc', badge: '#334155' },
		data: { body: '#14b8a6', face: '#f0fdfa', badge: '#0f766e' },
		ops: { body: '#f97316', face: '#fff7ed', badge: '#c2410c' },
		design: { body: '#d946ef', face: '#fdf4ff', badge: '#a21caf' },
		generic: { body: '#9ca3af', face: '#f9fafb', badge: '#4b5563' }
	};

	$: colors = PALETTE[kind] ?? PALETTE.generic;
	$: tone = toneOf(status);
	$: active = tone === 'run';
</script>

<span class="relative inline-flex shrink-0" style="width:{size}px;height:{size}px" {title}>
	<svg viewBox="0 0 40 40" width={size} height={size} aria-hidden="true" class={active ? 'halo-team-bob' : ''}>
		<line x1="20" y1="3.5" x2="20" y2="9" stroke={colors.body} stroke-width="2" stroke-linecap="round" />
		<circle cx="20" cy="3.5" r="2.4" fill={kind === 'lead' ? colors.badge : colors.body} />
		<rect x="5" y="9" width="30" height="25" rx="9" fill={colors.body} />
		<rect x="9" y="13.5" width="22" height="14" rx="6" fill={colors.face} />
		<circle cx="15.5" cy="20.5" r="2.3" fill={colors.body} />
		<circle cx="24.5" cy="20.5" r="2.3" fill={colors.body} />
		<path d="M16.5 25 q3.5 2 7 0" stroke={colors.body} stroke-width="1.6" fill="none" stroke-linecap="round" />
		<rect x="2.5" y="18" width="3" height="7" rx="1.5" fill={colors.body} />
		<rect x="34.5" y="18" width="3" height="7" rx="1.5" fill={colors.body} />
		<g transform="translate(26 26)">
			<circle cx="6" cy="6" r="6.5" fill={colors.badge} stroke="white" stroke-width="1.4" />
			{#if kind === 'lead'}
				<path d="M2.6 8.2 L3.4 4.2 L5 5.8 L6 3.4 L7 5.8 L8.6 4.2 L9.4 8.2 Z" fill="white" />
			{:else if kind === 'backend'}
				<path d="M4.4 4 L2.6 6 L4.4 8 M7.6 4 L9.4 6 L7.6 8" stroke="white" stroke-width="1.3" fill="none" stroke-linecap="round" />
			{:else if kind === 'frontend'}
				<rect x="2.8" y="3.4" width="6.4" height="5.2" rx="1" stroke="white" stroke-width="1.2" fill="none" />
				<line x1="2.8" y1="5.2" x2="9.2" y2="5.2" stroke="white" stroke-width="1.1" />
			{:else if kind === 'qa'}
				<path d="M3.2 6.2 L5.2 8.2 L8.8 4" stroke="white" stroke-width="1.5" fill="none" stroke-linecap="round" />
			{:else if kind === 'reviewer'}
				<circle cx="5.4" cy="5.4" r="2.3" stroke="white" stroke-width="1.3" fill="none" />
				<line x1="7.1" y1="7.1" x2="9" y2="9" stroke="white" stroke-width="1.4" stroke-linecap="round" />
			{:else if kind === 'docs'}
				<path d="M3.6 3.8 H8.4 M3.6 6 H8.4 M3.6 8.2 H6.8" stroke="white" stroke-width="1.2" stroke-linecap="round" />
			{:else if kind === 'data'}
				<path d="M3.6 8.6 V6.4 M6 8.6 V3.6 M8.4 8.6 V5.2" stroke="white" stroke-width="1.4" stroke-linecap="round" />
			{:else if kind === 'ops'}
				<circle cx="6" cy="6" r="1.7" stroke="white" stroke-width="1.2" fill="none" />
				<path d="M6 2.8 V3.9 M6 8.1 V9.2 M2.8 6 H3.9 M8.1 6 H9.2" stroke="white" stroke-width="1.2" stroke-linecap="round" />
			{:else if kind === 'design'}
				<path d="M3.4 8.6 L4 6.6 L7.6 3 L9 4.4 L5.4 8 Z" fill="white" />
			{:else}
				<circle cx="6" cy="6" r="1.8" fill="white" />
			{/if}
		</g>
	</svg>
	{#if status}
		<span
			class="absolute -left-0.5 -top-0.5 size-2.5 rounded-full ring-2 ring-white dark:ring-gray-900 {TONE_DOT[tone]} {active
				? 'animate-pulse'
				: ''}"
			aria-hidden="true"
		/>
	{/if}
</span>

<style>
	@media (prefers-reduced-motion: no-preference) {
		.halo-team-bob {
			animation: halo-team-bob 2.4s ease-in-out infinite;
		}
	}
	@keyframes halo-team-bob {
		0%,
		100% {
			transform: translateY(0);
		}
		50% {
			transform: translateY(-1.5px);
		}
	}
</style>

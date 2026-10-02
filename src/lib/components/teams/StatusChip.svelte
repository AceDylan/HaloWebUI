<script lang="ts">
	import { statusLabel, toneOf } from './model';
	import { TONE_CHIP, TONE_DOT } from './tones';

	export let status: string | null | undefined;
	export let label: string | null = null;
	export let size: 'xs' | 'sm' = 'xs';

	$: tone = toneOf(status);
</script>

<span
	class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-[3px] font-medium leading-none ring-1 ring-inset {size ===
	'xs'
		? 'text-[11px]'
		: 'text-xs'} {TONE_CHIP[tone]}"
	data-status={status}
>
	{#if tone === 'done'}
		<svg class="size-2.5 shrink-0" viewBox="0 0 12 12" fill="none" aria-hidden="true"
			><path
				d="m2.5 6.4 2.2 2.2 4.8-5"
				stroke="currentColor"
				stroke-width="1.8"
				stroke-linecap="round"
				stroke-linejoin="round"
			/></svg
		>
	{:else}
		<span
			class="size-1.5 shrink-0 rounded-full {TONE_DOT[tone]} {tone === 'run'
				? 'tm-pulse-dot text-sky-500'
				: ''}"
			aria-hidden="true"
		/>
	{/if}
	{label ?? statusLabel(status)}
</span>

<script lang="ts">
	import { getContext } from 'svelte';
	import Spinner from './Spinner.svelte';

	const i18n = getContext('i18n');

	// How far an upload has got: a ring with the percentage while the bytes go out, then a
	// spinner while the server stores (and for documents, reads) the file. No number yet
	// (an upload that cannot report progress) is a spinner from the start.

	/** 0–100 as reported by uploadFile's onProgress; null / undefined when unknown. */
	export let progress: number | null | undefined = null;
	/** Placement and backdrop of the whole thing (it centres its content). */
	export let className = '';
	export let ringClassName = 'size-10';
	/** The number inside the ring; off for rings too small to hold it. */
	export let showPercent = true;

	const RADIUS = 15;
	const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

	$: percent =
		typeof progress === 'number' && Number.isFinite(progress)
			? Math.max(0, Math.min(100, Math.floor(progress)))
			: null;
	$: sending = percent !== null && percent < 100;
	$: label = sending
		? $i18n.t('Uploading {{percent}}%', { percent })
		: percent === null
			? $i18n.t('Uploading...')
			: $i18n.t('Processing...');
</script>

<div
	class="flex items-center justify-center {className}"
	role="progressbar"
	aria-label={label}
	aria-valuemin="0"
	aria-valuemax="100"
	aria-valuenow={percent ?? undefined}
	title={label}
	data-upload-progress={percent ?? ''}
>
	{#if sending}
		<span class="relative inline-flex items-center justify-center {ringClassName}">
			<svg viewBox="0 0 36 36" class="absolute inset-0 size-full -rotate-90" aria-hidden="true">
				<circle cx="18" cy="18" r={RADIUS} fill="none" stroke="currentColor" stroke-opacity="0.3" stroke-width="3" />
				<circle
					cx="18"
					cy="18"
					r={RADIUS}
					fill="none"
					stroke="currentColor"
					stroke-width="3"
					stroke-linecap="round"
					stroke-dasharray={CIRCUMFERENCE}
					stroke-dashoffset={CIRCUMFERENCE * (1 - percent / 100)}
					class="transition-[stroke-dashoffset] duration-200 ease-out"
				/>
			</svg>
			{#if showPercent}
				<span class="relative text-[0.6875rem] font-semibold leading-none tabular-nums">{percent}%</span>
			{/if}
		</span>
	{:else}
		<Spinner className={showPercent ? 'size-5' : 'size-4'} />
	{/if}
</div>

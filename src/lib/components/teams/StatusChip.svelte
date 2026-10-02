<script lang="ts">
	import { statusLabel, toneOf } from './model';
	import { TONE_CHIP, TONE_DOT } from './tones';

	export let status: string | null | undefined;
	export let label: string | null = null;
	export let size: 'xs' | 'sm' = 'xs';

	$: tone = toneOf(status);
</script>

<span
	class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 ring-1 ring-inset font-medium {size ===
	'xs'
		? 'text-[11px]'
		: 'text-xs'} {TONE_CHIP[tone]}"
	data-status={status}
>
	<span class="size-1.5 rounded-full {TONE_DOT[tone]} {tone === 'run' ? 'animate-pulse' : ''}" aria-hidden="true" />
	{label ?? statusLabel(status)}
</span>

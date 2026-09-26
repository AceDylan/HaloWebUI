<script lang="ts">
	import { onDestroy } from 'svelte';

	import {
		STREAM_CHAR_SETTLE_MS,
		commonPrefixLength,
		splitStreamText
	} from '$lib/utils/stream-text';

	// A run of streamed text with the fade-in on its newest characters only; see
	// $lib/utils/stream-text.
	export let text = '';

	let settled = 0;
	let previous = '';
	let timer: ReturnType<typeof setTimeout> | null = null;

	const stopTimer = () => {
		if (timer) clearTimeout(timer);
		timer = null;
	};

	// Everything present when the timer starts has finished fading when it fires.
	const settleLater = () => {
		if (timer) return;
		const target = text.length;
		timer = setTimeout(() => {
			timer = null;
			settled = Math.max(settled, Math.min(target, text.length));
			if (settled < text.length) settleLater();
		}, STREAM_CHAR_SETTLE_MS);
	};

	$: {
		const kept = commonPrefixLength(previous, text);
		if (kept < previous.length) {
			// Rewritten rather than appended (the Markdown re-tokenised): settle again
			// from the part that still matches.
			settled = Math.min(settled, kept);
			stopTimer();
		}
		previous = text;
		if (settled < text.length) settleLater();
	}

	$: parts = splitStreamText(text, settled);

	onDestroy(stopTimer);
</script>

{parts.settledText}{#each parts.tail as item (item.index)}<span class="stream-char"
		>{item.char}</span
	>{/each}

<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	import { formatElapsedSeconds } from '$lib/utils/elapsed';

	// Keeps the running time next to the model name for as long as the reply is
	// generating. The initial "thinking" indicator shows it too, but disappears
	// once output starts, and hermes tasks run for minutes after that.
	export let since = 0;

	let now = Date.now() / 1000;
	let timer: ReturnType<typeof setInterval> | null = null;

	onMount(() => {
		now = Date.now() / 1000;
		timer = setInterval(() => {
			now = Date.now() / 1000;
		}, 1000);
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	$: seconds = since > 0 ? Math.max(0, Math.floor(now - since)) : 0;
</script>

{#if since > 0}
	<span
		class="inline-flex shrink-0 items-center gap-1 self-center text-xs font-medium tabular-nums text-gray-500 dark:text-gray-400"
		data-halo-generation-elapsed
	>
		<span class="relative flex size-1.5">
			<span class="absolute inline-flex size-full animate-ping rounded-full bg-blue-400 opacity-75"
			></span>
			<span class="relative inline-flex size-1.5 rounded-full bg-blue-500"></span>
		</span>
		{formatElapsedSeconds(seconds)}
	</span>
{/if}

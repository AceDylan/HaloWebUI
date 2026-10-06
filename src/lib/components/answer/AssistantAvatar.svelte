<script lang="ts">
	import { models } from '$lib/stores';
	import ModelIcon from '$lib/components/common/ModelIcon.svelte';
	import { modelById, modelIcon } from '$lib/components/discuss/model';

	/** An assistant's face in the halo ring (discuss.css .dc-ring: the ring says what it is doing):
	 *  its emoji on a tile when it has one (精答 gives every assistant it makes one), else its icon. */
	export let id = '';
	export let name = '';
	export let emoji = '';
	export let size = 28;
	export let state: 'waiting' | 'thinking' | 'streaming' | 'done' | 'error' | 'stopped' | 'idle' = 'idle';

	$: hue = [...(name || id)].reduce((h, ch) => (h * 31 + ch.codePointAt(0)!) % 360, 17);
	$: entry = emoji ? undefined : modelById($models as any[], id);
</script>

<span class="dc-ring" data-state={state} style="--dc-hue: {hue}; width: {size + 4}px; height: {size + 4}px" title={name}>
	{#if emoji}
		<span class="ad-avatar" style="--ad-hue: {hue}; width: {size}px; height: {size}px; font-size: {Math.round(size * 0.56)}px" aria-hidden="true"
			>{emoji}</span
		>
	{:else}
		<ModelIcon src={modelIcon(entry)} alt={name} className="size-full rounded-full" />
	{/if}
</span>

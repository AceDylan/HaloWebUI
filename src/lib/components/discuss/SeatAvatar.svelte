<script lang="ts">
	import { models } from '$lib/stores';
	import ModelIcon from '$lib/components/common/ModelIcon.svelte';
	import { modelById, modelIcon } from './model';

	/** A seat's model icon in its ring (see discuss.css: the ring says what the seat is doing). */
	export let model: string;
	export let name = '';
	export let hue = 226;
	export let state: 'waiting' | 'thinking' | 'streaming' | 'done' | 'error' | 'stopped' | 'idle' = 'idle';
	export let size = 28;

	$: entry = modelById($models as any[], model);
</script>

<span
	class="dc-ring"
	data-state={state}
	style="--dc-hue: {hue}; width: {size + 4}px; height: {size + 4}px"
	title={name}
>
	<ModelIcon src={modelIcon(entry)} alt={name} className="size-full rounded-full" />
</span>

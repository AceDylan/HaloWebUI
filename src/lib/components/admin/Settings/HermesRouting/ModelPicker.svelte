<script lang="ts">
	// One row of star-core pills: pick the model a slot runs on. `emptyLabel` adds the
	// "follow the default" choice (value ""); a value hermes could not map (set from the
	// command line) shows as its own pressed pill so a save leaves it alone.
	import { createEventDispatcher } from 'svelte';
	import { isForeignModel, modelFamily, modelLabel } from '$lib/utils/hermes-routing';

	export let value = '';
	export let models: string[] = [];
	export let emptyLabel = '';
	export let compact = false;
	export let label = '';

	const dispatch = createEventDispatcher<{ change: string }>();
	const pick = (id: string) => {
		if (id !== value) dispatch('change', id);
	};
</script>

<div class="hr-picker" class:compact role="radiogroup" aria-label={label}>
	{#if emptyLabel}
		<button
			type="button"
			class="halo-wb-opt hr-pill"
			role="radio"
			aria-checked={value === ''}
			on:click={() => pick('')}
		>
			<span class="hr-dot hr-dot-follow" aria-hidden="true"></span>{emptyLabel}
		</button>
	{/if}
	{#each models as id (id)}
		<button
			type="button"
			class="halo-wb-opt hr-pill"
			role="radio"
			data-model={id}
			aria-checked={value === id}
			on:click={() => pick(id)}
		>
			<span class="hr-dot" data-family={modelFamily(id)} aria-hidden="true"></span>{id}
		</button>
	{/each}
	{#if isForeignModel(value)}
		<span
			class="halo-wb-opt hr-pill"
			role="radio"
			aria-checked="true"
			title="命令行配置的，页面不改它"
		>
			<span class="hr-dot" aria-hidden="true"></span>{modelLabel(value)}
		</span>
	{/if}
</div>

<style>
	.hr-picker {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.hr-picker.compact {
		gap: 0.3rem;
	}
	.hr-picker.compact .hr-pill {
		padding: 0.22rem 0.5rem;
		font-size: 0.7rem;
	}
	.hr-pill {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		letter-spacing: -0.01em;
	}
</style>

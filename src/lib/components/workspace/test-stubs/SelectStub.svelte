<script lang="ts">
	// Stand-in for common/HaloSelect.svelte in DOM mount tests (bits-ui's Select needs pointer
	// events the test DOM lacks): a native <select> bound to the same value.
	export let value = '';
	export let options: { value: string; label: string }[] = [];
	export let className = '';
</script>

<select class={className} data-select-stub={options.map((o) => o.value).join(',')} bind:value>
	{#each options as option}
		<option value={option.value}>{option.label}</option>
	{/each}
</select>

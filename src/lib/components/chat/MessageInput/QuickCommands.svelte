<script lang="ts">
	import PromptPicker from './PromptPicker.svelte';

	export let imageMode = false;
</script>

<!-- Switching model families closes the old dialog and loads the right source. -->
{#key imageMode}
	<PromptPicker {imageMode} on:select />
{/key}

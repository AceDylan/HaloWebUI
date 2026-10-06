<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';
	import AssistantLibrary from '$lib/components/workspace/AssistantLibrary.svelte';

	// The templates are a tab of the 「助手」 page now. Users without the assistants page
	// (no workspace.models permission) keep this one.
	$: canOpenAssistants = $user?.role === 'admin' || !!$user?.permissions?.workspace?.models;

	onMount(() => {
		if (canOpenAssistants) {
			goto('/workspace/models?tab=templates', { replaceState: true });
		}
	});
</script>

{#if !canOpenAssistants}
	<AssistantLibrary />
{/if}

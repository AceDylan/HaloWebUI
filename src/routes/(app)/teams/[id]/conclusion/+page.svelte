<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { WEBUI_NAME, config } from '$lib/stores';
	import ConclusionPage from '$lib/components/teams/ConclusionPage.svelte';

	onMount(() => {
		if ($config && $config.features?.enable_agent_teams === false) goto('/');
	});
</script>

<svelte:head><title>结论 · 协作台 | {$WEBUI_NAME}</title></svelte:head>

{#key $page.params.id}
	<ConclusionPage teamId={$page.params.id} />
{/key}

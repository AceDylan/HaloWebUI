<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	import { WEBUI_NAME, config } from '$lib/stores';
	import TeamsHome from '$lib/components/teams/TeamsHome.svelte';

	onMount(() => {
		if ($config && $config.features?.enable_agent_teams === false) goto('/');
	});
</script>

<svelte:head><title>协作台 | {$WEBUI_NAME}</title></svelte:head>

<TeamsHome />

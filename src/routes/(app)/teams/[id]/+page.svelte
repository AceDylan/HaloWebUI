<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { config } from '$lib/stores';
	import TeamWorkbench from '$lib/components/teams/TeamWorkbench.svelte';

	onMount(() => {
		if ($config && $config.features?.enable_agent_teams === false) goto('/');
	});
</script>

<!-- the workbench sets the title: the team's name and progress -->
{#key $page.params.id}
	<TeamWorkbench teamId={$page.params.id} />
{/key}

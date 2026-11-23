<script lang="ts">
	import HermesRouting from '$lib/components/admin/Settings/HermesRouting.svelte';
	import { user } from '$lib/stores';
</script>

{#if $user?.role === 'admin'}
	<HermesRouting />
{/if}

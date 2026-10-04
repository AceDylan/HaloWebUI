<script lang="ts">
	import { page } from '$app/stores';
	import DiscussRoom from '$lib/components/discuss/DiscussRoom.svelte';
</script>

<!-- the room sets the title -->
{#key $page.params.id}
	<DiscussRoom chatId={$page.params.id} />
{/key}

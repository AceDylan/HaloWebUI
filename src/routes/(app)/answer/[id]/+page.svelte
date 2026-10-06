<script lang="ts">
	import { page } from '$app/stores';
	import AnswerRun from '$lib/components/answer/AnswerRun.svelte';
</script>

<!-- the run page sets the title -->
{#key $page.params.id}
	<AnswerRun chatId={$page.params.id} />
{/key}

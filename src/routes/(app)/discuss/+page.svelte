<script lang="ts">
	import { WEBUI_NAME } from '$lib/stores';
	import DiscussHome from '$lib/components/discuss/DiscussHome.svelte';
</script>

<svelte:head><title>讨论台 | {$WEBUI_NAME}</title></svelte:head>

<DiscussHome />

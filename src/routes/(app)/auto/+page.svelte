<script lang="ts">
	import { WEBUI_NAME } from '$lib/stores';
	import AutoHome from '$lib/components/auto/AutoHome.svelte';
</script>

<svelte:head><title>自动分流工作台 | {$WEBUI_NAME}</title></svelte:head>
<AutoHome />

<script lang="ts">
	import { getContext, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import type { Writable } from 'svelte/store';

	import WebSearch from '$lib/components/admin/Settings/WebSearch.svelte';
	import { config, user } from '$lib/stores';
	import { getBackendConfig } from '$lib/apis';

	const i18n: Writable<any> = getContext('i18n');
</script>

{#if $user?.role === 'admin'}
	<WebSearch
		saveHandler={async () => {
			toast.success($i18n.t('Settings saved successfully!'));
			await tick();
			await config.set(await getBackendConfig(localStorage.token));
		}}
	/>
{/if}

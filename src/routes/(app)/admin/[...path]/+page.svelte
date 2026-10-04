<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	onMount(() => {
		const rest = $page.params.path ?? '';

		let target = '/settings';
		if (rest === 'users') target = '/settings/users';
		else if (rest === 'functions') target = '/workspace/functions';
		else if (rest === 'settings' || rest === 'system') target = '/settings/models';
		else if (rest === 'models') target = '/settings/models';
		else if (rest === 'documents') target = '/settings/documents';
		else if (rest === 'web-search' || rest === 'web') target = '/settings/web-search';
		else if (rest === 'audio') target = '/settings/audio';
		else if (rest === 'images') target = '/settings/images';
		else if (rest.startsWith('functions/')) target = `/workspace/${rest}`;

		goto(`${target}${$page.url.search}`);
	});
</script>

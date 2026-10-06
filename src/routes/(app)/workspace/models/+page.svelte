<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { models } from '$lib/stores';
	import { ensureModels } from '$lib/services/models';
	import { translateWithDefault } from '$lib/i18n';
	import Models from '$lib/components/workspace/Models.svelte';
	import AssistantLibrary from '$lib/components/workspace/AssistantLibrary.svelte';

	const i18n: any = getContext('i18n');
	const tr = (zh: string, en: string) => translateWithDefault($i18n, zh, en);

	// 「助手」 is one page: the user's assistants, or the built-in templates (?tab=templates).
	$: tab = $page.url.searchParams.get('tab') === 'templates' ? 'templates' : 'mine';

	const selectTab = (next: 'mine' | 'templates') => {
		if (next === tab) return;
		void goto(next === 'templates' ? '/workspace/models?tab=templates' : '/workspace/models', {
			replaceState: true,
			noScroll: true,
			keepFocus: true
		});
	};

	onMount(async () => {
		await ensureModels(localStorage.token, { reason: 'workspace-models' });
	});
</script>

<div class="flex h-full flex-col gap-4">
	<div class="halo-seg flex w-fit max-w-full items-center overflow-x-auto scrollbar-hidden" role="tablist" data-assistant-tabs>
		<button
			type="button"
			role="tab"
			aria-selected={tab === 'mine'}
			class="tab-button {tab === 'mine' ? 'active' : ''}"
			on:click={() => selectTab('mine')}
		>
			{tr('我的助手', 'My assistants')}
		</button>
		<button
			type="button"
			role="tab"
			aria-selected={tab === 'templates'}
			class="tab-button {tab === 'templates' ? 'active' : ''}"
			on:click={() => selectTab('templates')}
		>
			{tr('内置模板', 'Built-in templates')}
		</button>
	</div>

	{#if tab === 'templates'}
		<div class="min-h-0 flex-1">
			<AssistantLibrary />
		</div>
	{:else if $models !== null}
		<Models />
	{/if}
</div>

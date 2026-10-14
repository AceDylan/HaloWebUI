<script lang="ts">
	import { onMount } from 'svelte';
	import { targetAutoRoute, MODE_LABEL, type AutoMode, type AutoRoute } from '$lib/apis/auto';
	export let mode: AutoMode;
	export let targetId: string;
	let row: AutoRoute | null = null;
	onMount(() => {
		targetAutoRoute(localStorage.token, mode, targetId)
			.then((r) => (row = r))
			.catch(() => {});
	});
</script>

{#if row}
	<aside
		class="mb-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-sm"
		data-auto-notice
	>
		<div class="flex flex-wrap items-center justify-between gap-2">
			<strong>自动分流 → {MODE_LABEL[mode]}</strong>
			<a class="text-cyan-600 dark:text-cyan-300 hover:underline" href="/auto">返回自动分流工作台</a
			>
		</div>
		<p class="mt-1 text-gray-500 dark:text-gray-400">{row.reason}</p>
	</aside>
{/if}

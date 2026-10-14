<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		getAutoRoute,
		cancelAutoRoute,
		routePending,
		routeStatus,
		MODE_LABEL,
		type AutoRoute
	} from '$lib/apis/auto';
	import ModeDispatchCard from '$lib/components/chat/Messages/ModeDispatchCard.svelte';
	import TeamChatCard from '$lib/components/teams/TeamChatCard.svelte';
	export let id: string;
	export let history: any = null;
	let row: AutoRoute | null = null;
	let error = '';
	let timer: ReturnType<typeof setTimeout> | undefined;
	let destroyed = false;
	async function load() {
		try {
			row = await getAutoRoute(localStorage.token, id);
			error = '';
		} catch (e: any) {
			error = e.message || '读取失败';
		}
		if (!destroyed && (!row || routePending(row)))
			timer = setTimeout(load, document.hidden ? 15000 : 2500);
	}
	async function cancel() {
		try {
			row = await cancelAutoRoute(localStorage.token, id);
		} catch (e: any) {
			error = e.message;
		}
	}
	onMount(() => {
		load();
	});
	onDestroy(() => {
		destroyed = true;
		clearTimeout(timer);
	});
</script>

<div class="my-3 rounded-xl border border-cyan-500/20 p-4 text-sm" data-auto-dispatch>
	<div class="flex flex-wrap justify-between gap-2">
		<strong>自动分流{row?.mode ? ` → ${MODE_LABEL[row.mode]}` : ''}</strong>
		<a href={`/auto?request=${encodeURIComponent(id)}`} class="text-cyan-600 dark:text-cyan-300"
			>查看记录</a
		>
	</div>
	<p class="mt-2 text-gray-500">{row ? row.reason || routeStatus(row) : '正在读取分流进度…'}</p>
	{#if error || row?.error}<p class="mt-2 text-red-500">{error || row?.error}</p>{/if}
	{#if row?.status === 'routing'}<button class="mt-2 underline" on:click={cancel}>取消分流</button
		>{/if}
	{#if row?.status === 'cancelled' || row?.status === 'interrupted'}<p class="mt-2">
			{routeStatus(row)}
		</p>{/if}
</div>
{#if row?.target_id && row.target_status !== 'deleted'}
	{#if row.mode === 'team'}<TeamChatCard teamId={row.target_id} {history} />
	{:else if row.mode === 'answer' || row.mode === 'discuss'}<ModeDispatchCard
			kind={row.mode}
			chatId={row.target_id}
			{history}
		/>{/if}
{/if}

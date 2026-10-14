<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { models } from '$lib/stores';
	import { getModelBaseName } from '$lib/utils/model-display';
	import { findModelByIdentity, parseModelSelectionId } from '$lib/utils/model-identity';
	import '$lib/components/teams/teams.css';
	import {
		getAutoRoute,
		cancelAutoRoute,
		retryAutoRoute,
		routePending,
		routeStatus,
		MODE_LABEL,
		type AutoMode,
		type AutoRoute
	} from '$lib/apis/auto';
	import ModeDispatchCard from '$lib/components/chat/Messages/ModeDispatchCard.svelte';
	import TeamChatCard from '$lib/components/teams/TeamChatCard.svelte';
	export let id: string;
	export let history: any = null;
	let row: AutoRoute | null = null;
	$: routingModel = findModelByIdentity($models ?? [], row?.routing_model);
	$: routingModelName =
		getModelBaseName(routingModel) ||
		parseModelSelectionId(row?.routing_model)?.modelId ||
		row?.routing_model ||
		'';
	let error = '';
	let timer: ReturnType<typeof setTimeout> | undefined;
	let destroyed = false;
	async function load() {
		try {
			row = await getAutoRoute(localStorage.token, id);
			error = '';
		} catch (e: any) {
			error = e.message || '读取失败';
			if (e.status === 404) return;
		}
		if (!destroyed && (!row || routePending(row)))
			timer = setTimeout(load, document.hidden ? 15000 : 2500);
	}
	// failed, interrupted or cancelled: route it again here, automatically or in a chosen mode
	const RETRYABLE = new Set(['error', 'interrupted', 'cancelled']);
	const MODES: AutoMode[] = ['answer', 'discuss', 'team'];
	let retrying = '';
	$: canRetry = !!row && RETRYABLE.has(row.status);
	async function retry(mode: 'auto' | AutoMode) {
		if (retrying) return;
		retrying = mode;
		try {
			row = await retryAutoRoute(localStorage.token, id, mode);
			id = row.id;
			error = '';
			clearTimeout(timer);
			if (routePending(row)) timer = setTimeout(load, 2500);
		} catch (e: any) {
			error = e.message || '重试失败';
		} finally {
			retrying = '';
		}
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

<section
	class="not-prose my-3 flex max-w-2xl flex-col gap-3"
	data-teams-ui
	data-auto-dispatch
	aria-live="polite"
>
	<div class="tm-card overflow-hidden">
		<div class="flex items-center gap-3 px-4 py-3">
			<span
				class="grid size-10 shrink-0 place-items-center rounded-xl bg-cyan-500/10 text-cyan-700 dark:text-cyan-300"
				aria-hidden="true"
			>
				<svg
					width="22"
					height="22"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.7"
					stroke-linecap="round"
					stroke-linejoin="round"
					><path d="M5 12h5m0 0 5-6h4m-9 6 5 6h4" /><circle cx="4" cy="12" r="2" /><path
						d="m17 4 3 2-3 2m0 8 3 2-3 2"
					/></svg
				>
			</span>
			<div class="min-w-0 flex-1">
				<div class="flex flex-wrap items-center gap-2">
					<strong class="text-sm font-semibold"
						>自动{row?.mode ? ` · ${MODE_LABEL[row.mode]}` : '分流'}</strong
					><span class="rounded-full bg-gray-500/10 px-2 py-0.5 text-xs text-gray-500"
						>{row
							? row.status === 'dispatched'
								? '已选择处理方式'
								: routeStatus(row)
							: '正在连接'}</span
					>
				</div>
				<p class="mt-1 text-xs leading-5 text-gray-500">
					{row?.reason || '正在理解目标、附件和约束，选择合适的处理方式…'}
				</p>
			</div>
			<a href={`/auto?request=${encodeURIComponent(id)}`} class="tm-btn-ghost shrink-0"
				>分流详情 ↗</a
			>
		</div>
		{#if row?.routing_model}<div
				class="truncate border-t border-gray-500/10 px-4 py-2 text-xs text-gray-500"
				title={routingModelName}
			>
				主控模型 · {routingModelName}
			</div>{/if}
		{#if error || row?.error}<p role="alert" class="px-4 pb-3 text-xs text-red-500">
				{error || row?.error}
			</p>{/if}
		{#if row?.status === 'routing'}<div class="px-4 pb-3">
				<button class="tm-btn-ghost" on:click={cancel}>取消分流</button>
			</div>{/if}
		{#if canRetry}<div class="flex flex-wrap items-center gap-2 px-4 pb-3" data-auto-retry>
				<button
					type="button"
					class="tm-btn-primary !px-2.5 !py-1 !text-xs"
					disabled={!!retrying}
					on:click={() => retry('auto')}
					data-auto-retry-mode="auto">{retrying === 'auto' ? '分流中…' : '重新分流'}</button
				>
				<span class="text-xs text-gray-500">或直接交给</span>
				{#each MODES as mode}
					<button
						type="button"
						class="tm-btn-ghost !text-xs"
						disabled={!!retrying}
						on:click={() => retry(mode)}
						data-auto-retry-mode={mode}>{MODE_LABEL[mode]}</button
					>
				{/each}
			</div>{/if}
		{#if row?.target_status === 'deleted'}<p class="px-4 pb-3 text-xs text-gray-500">
				目标任务已删除，分流依据仍保留在记录中。
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
</section>

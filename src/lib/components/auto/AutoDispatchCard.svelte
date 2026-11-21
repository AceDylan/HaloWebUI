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
		routeTarget,
		MODE_LABEL,
		type AutoMode,
		type AutoRoute
	} from '$lib/apis/auto';
	import ModeDispatchCard from '$lib/components/chat/Messages/ModeDispatchCard.svelte';
	import TeamChatCard from '$lib/components/teams/TeamChatCard.svelte';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';
	import { elapsed, now } from '$lib/components/teams/clock';
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
	let reasonExpanded = false;
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
	const MODES: AutoMode[] = ['hermes', 'answer', 'discuss', 'team'];
	const modeIcon = (mode: AutoMode) => (mode === 'team' ? 'teams' : mode);
	let retrying = '';
	$: canRetry = !!row && RETRYABLE.has(row.status);
	$: failed = !!row && !row.blocked && (row.status === 'error' || row.status === 'interrupted');
	$: pending = !row || routePending(row);
	// Handed to Hermes: its answer is this reply itself (or a chat of its own, from a retry
	// elsewhere): the strip says so and links there when it is another chat.
	$: toHermes = row?.mode === 'hermes' && row.status === 'dispatched';
	$: hasChildCard = Boolean(row?.target_id && row.target_status !== 'deleted') && !toHermes;
	$: compact = hasChildCard || toHermes;
	$: hermesElsewhere = toHermes && !!row?.target_id && row.target_id !== row.origin_chat_id;
	$: routeStartedAt = row?.created_at ? (row.created_at > 1e12 ? row.created_at / 1000 : row.created_at) : null;
	$: routingElapsed = pending && routeStartedAt ? Math.max(0, $now - routeStartedAt) : null;
	$: longReason = (row?.reason?.length ?? 0) > 90;
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
	class="not-prose my-3 flex max-w-2xl flex-col {compact ? 'gap-0' : 'gap-2.5'}"
	data-teams-ui
	data-auto-dispatch
	data-auto-mode={row?.mode ?? undefined}
	aria-live="polite"
>
	{#if compact}
		<!-- Compact connected routing strip once the target workbench card is rendered below -->
		<div class="wb-route-strip" data-auto-strip>
			<div class="flex items-start gap-2.5">
				<span
					class="mt-0.5 grid size-6 shrink-0 place-items-center rounded-lg bg-cyan-500/12 text-cyan-700 dark:bg-cyan-400/15 dark:text-cyan-300"
					aria-hidden="true"
				>
					<SidebarModeIcon mode={toHermes ? 'hermes' : 'auto'} className="size-3.5" />
				</span>
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-1.5 text-xs">
						<strong class="font-semibold text-gray-900 dark:text-gray-100"
							>自动分流{row?.mode ? ` → ${routeTarget(row)}` : ''}</strong
						>
						<span
							class="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] font-medium text-cyan-700 dark:text-cyan-300"
							>{row?.status === 'dispatched'
								? `已交给${routeTarget(row) || '工作台'}`
								: routeStatus(row)}</span
						>
						{#if row?.degraded}<span
								class="rounded-full bg-amber-500/12 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300"
								data-auto-degraded
								title={row.degraded === 'auto'
									? '判断模型暂不可用，已按规则自动研判'
									: '想用的方式暂时不可用，由这种方式代替'}
								>{row.degraded === 'auto' ? '规则研判' : '临时改用'}</span
							>{/if}
						{#if row?.routing_model}<span
								class="truncate text-[11px] text-gray-400 dark:text-gray-500"
								title={routingModelName}
								data-auto-routing-model
								>· 由 {routingModelName} 判断{row?.decision?.used ? '（辅助决策）' : ''}</span
							>{/if}
					</div>
					{#if row?.reason}
						<p
							class="mt-1 text-xs leading-5 text-gray-600 dark:text-gray-300 {longReason && !reasonExpanded
								? 'line-clamp-2'
								: ''}"
						>
							{row.reason}
						</p>
						{#if longReason}
							<button
								type="button"
								class="mt-0.5 text-[11px] font-medium text-cyan-700 hover:underline dark:text-cyan-300"
								on:click={() => (reasonExpanded = !reasonExpanded)}
								>{reasonExpanded ? '收起依据' : '展开分流依据'}</button
							>
						{/if}
					{/if}
					{#if row?.decision?.fallback}<p
							class="mt-0.5 text-[11px] text-amber-600 dark:text-amber-400"
							data-decision-note
							data-fallback="true"
						>
							辅助决策 {row.decision.name} 没用上（{row.decision.reason || '调用失败'}），按原来的方式选择
						</p>{/if}
				</div>
				{#if hermesElsewhere && row?.href}<a
						href={row.href}
						class="tm-btn-ghost shrink-0 !px-2 !py-1 !text-[11px]"
						data-auto-open-hermes
						title="打开 Hermes 回答的对话">打开对话 →</a
					>{/if}
				<a
					href={`/auto?request=${encodeURIComponent(id)}`}
					class="tm-btn-ghost shrink-0 !px-2 !py-1 !text-[11px]"
					title="在自动分流工作台查看这次分流">分流记录 ↗</a
				>
			</div>
			{#if error || row?.error}<p
					role="alert"
					class="mt-1.5 pl-8 text-xs {row?.blocked && !error
						? 'text-amber-700 dark:text-amber-400'
						: 'text-red-500'}"
					data-auto-blocked={row?.blocked ? 'true' : undefined}
				>
					{error || row?.error}
				</p>{/if}
		</div>
		{#if hasChildCard}<div class="wb-route-connector" aria-hidden="true" />{/if}
	{:else}
		<div class="wb-shell {pending ? 'tm-live' : ''}" data-wb-kind="auto">
			<div class="wb-shell-head">
				<span
					class="grid size-9 shrink-0 place-items-center rounded-xl bg-cyan-500/12 text-cyan-700 dark:bg-cyan-400/15 dark:text-cyan-300"
					aria-hidden="true"
				>
					<SidebarModeIcon mode="auto" className="size-5" />
				</span>
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-2">
						<strong class="text-sm font-semibold text-gray-900 dark:text-gray-100"
							>自动分流{row?.mode ? ` → ${routeTarget(row)}` : ''}</strong
						><span
							class="rounded-full px-2 py-0.5 text-xs font-medium {failed
								? 'bg-red-500/10 text-red-600 dark:text-red-400'
								: row?.blocked
									? 'bg-amber-500/12 text-amber-700 dark:text-amber-400'
									: 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300'}"
							>{row
								? row.status === 'dispatched'
									? `已交给${routeTarget(row) || '工作台'}`
									: routeStatus(row)
								: '正在连接'}</span
						>{#if row?.degraded}<span
								class="rounded-full bg-amber-500/12 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400"
								data-auto-degraded
								title={row.degraded === 'auto'
									? '判断模型暂不可用，已按规则自动研判'
									: '想用的方式暂时不可用，由这种方式代替'}
								>{row.degraded === 'auto' ? '规则研判' : '临时改用'}</span
							>{/if}
						{#if routingElapsed !== null}
							<span class="tm-num text-[11px] text-gray-400 dark:text-gray-500"
								>已用 {elapsed(routingElapsed)}</span
							>
						{/if}
					</div>
					{#if row?.routing_model}<p
							class="mt-0.5 truncate text-[11px] text-gray-500 dark:text-gray-400"
							title={routingModelName}
							data-auto-routing-model
						>
							由 {routingModelName} 判断{row?.decision?.used ? '（辅助决策模型）' : ''}
						</p>{/if}
				</div>
				<a
					href={`/auto?request=${encodeURIComponent(id)}`}
					class="tm-btn-ghost shrink-0 !text-xs"
					title="在自动分流工作台查看这次分流">分流记录 ↗</a
				>
			</div>
			<div class="wb-shell-body space-y-2">
				<p
					class="text-xs leading-5 text-gray-600 dark:text-gray-300 {!row?.reason && pending
						? 'tm-shimmer'
						: ''}"
				>
					{row?.reason || '正在理解目标、附件和约束，选择合适的处理方式…'}
				</p>
				{#if row?.decision?.fallback}<p
						class="text-[11px] text-amber-600 dark:text-amber-400"
						data-decision-note
						data-fallback="true"
					>
						辅助决策 {row.decision.name} 没用上（{row.decision.reason ||
							'调用失败'}），按原来的方式选择
					</p>{/if}
				{#if error || row?.error}<p
						role="alert"
						class="text-xs {row?.blocked && !error
							? 'text-amber-700 dark:text-amber-400'
							: 'text-red-500'}"
						data-auto-blocked={row?.blocked ? 'true' : undefined}
					>
						{error || row?.error}
					</p>{/if}
				{#if row?.target_status === 'deleted'}<p class="text-xs text-gray-500">
						目标任务已删除，分流依据仍保留在记录中。
					</p>{/if}
			</div>
			{#if row?.status === 'routing' || canRetry}
				<div class="wb-shell-foot">
					{#if row?.status === 'routing'}
						<div class="flex justify-end">
							<button class="tm-btn-ghost tm-btn-danger !text-xs" on:click={cancel}>取消分流</button>
						</div>
					{/if}
					{#if canRetry}<div class="flex flex-wrap items-center gap-1.5" data-auto-retry>
							<button
								type="button"
								class="tm-btn-primary !px-2.5 !py-1 !text-xs"
								disabled={!!retrying}
								on:click={() => retry('auto')}
								data-auto-retry-mode="auto">{retrying === 'auto' ? '分流中…' : '重新分流'}</button
							>
							<span class="px-0.5 text-xs text-gray-500">或直接交给</span>
							{#each MODES as mode}
								<button
									type="button"
									class="tm-btn-ghost !text-xs"
									disabled={!!retrying}
									on:click={() => retry(mode)}
									data-auto-retry-mode={mode}
								>
									<SidebarModeIcon mode={modeIcon(mode)} className="size-3.5" />
									{MODE_LABEL[mode]}
								</button>
							{/each}
						</div>{/if}
				</div>
			{/if}
		</div>
	{/if}
	{#if hasChildCard && row?.target_id}
		{#if row.mode === 'team'}<TeamChatCard teamId={row.target_id} {history} />
		{:else if row.mode === 'answer' || row.mode === 'discuss'}<ModeDispatchCard
				kind={row.mode}
				chatId={row.target_id}
				{history}
			/>{/if}
	{/if}
</section>
